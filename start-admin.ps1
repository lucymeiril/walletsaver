<#
.SYNOPSIS
    지갑 지키미 — 관리 도구 시작 (크롤러 관리 + DB 관리)
.DESCRIPTION
    크롤러 관리(8001/5174), DB 관리(8002/5175) 서버를 시작합니다.
    서버 전용 내부 도구로 배포하지 않습니다.
    --reload를 사용하지 않습니다. 리로더 자식 프로세스가 종료 뒤 포트를 잡는 문제를 피합니다.
#>

$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
if (-not $Root) { $Root = Get-Location }

Write-Host ""
Write-Host "============================================" -ForegroundColor Magenta
Write-Host "  🔧 지갑 지키미 — 관리 도구 시작" -ForegroundColor Magenta
Write-Host "============================================" -ForegroundColor Magenta
Write-Host ""

$PyExe = $null
foreach ($candidate in @("py", "python", "python3")) {
    try {
        $null = & $candidate --version 2>&1
        if ($LASTEXITCODE -eq 0) { $PyExe = $candidate; break }
    } catch {}
}
if (-not $PyExe) {
    Write-Host "❌ Python을 찾을 수 없습니다." -ForegroundColor Red
    exit 1
}
Write-Host "  🐍 Python: $PyExe" -ForegroundColor DarkGray

$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npmCmd) {
    Write-Host "❌ npm을 찾을 수 없습니다." -ForegroundColor Red
    exit 1
}

$CrawlerBackendDir  = Join-Path $Root "packages\crawler-admin\backend"
$CrawlerFrontendDir = Join-Path $Root "packages\crawler-admin\frontend"
$DbBackendDir       = Join-Path $Root "packages\db-admin\backend"
$DbFrontendDir      = Join-Path $Root "packages\db-admin\frontend"
$SharedDir          = Join-Path $Root "packages\shared"

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "$Root;$SharedDir;$CrawlerBackendDir;$DbBackendDir"
if (-not $env:REQUIRE_AUTH) { $env:REQUIRE_AUTH = "false" }
if (-not $env:DB_ADMIN_API_URL) { $env:DB_ADMIN_API_URL = "http://127.0.0.1:8002/api/prices/bulk" }
if (-not $env:INGESTION_API_URL) { $env:INGESTION_API_URL = "http://127.0.0.1:8002/api/ingestions" }
if (-not $env:DATABASE_URL) {
    $env:DATABASE_URL = "sqlite:///" + (Join-Path $DbBackendDir "walletguardian.db").Replace("\", "/")
}
if (-not $env:DB_ADMIN_DATABASE_URL) { $env:DB_ADMIN_DATABASE_URL = $env:DATABASE_URL }

function Install-PythonRequirements {
    param(
        [string]$Name,
        [string]$RequirementsPath
    )

    if (-not (Test-Path $RequirementsPath)) {
        Write-Host "❌ $Name requirements.txt를 찾을 수 없습니다: $RequirementsPath" -ForegroundColor Red
        exit 1
    }

    Write-Host "[의존성] $Name Python 패키지 설치/확인..." -ForegroundColor Yellow
    & $PyExe -m pip install --quiet --disable-pip-version-check -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ $Name Python 패키지 설치에 실패했습니다." -ForegroundColor Red
        exit 1
    }
    Write-Host "         ✅ $Name 완료" -ForegroundColor Green
}

function Ensure-PlaywrightChromium {
    Write-Host "[의존성] Playwright Chromium 설치/확인..." -ForegroundColor Yellow
    & $PyExe -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Playwright Chromium 설치에 실패했습니다." -ForegroundColor Red
        Write-Host "   브라우저 기반 크롤러가 동작하지 않으므로 시작을 중단합니다." -ForegroundColor Red
        exit 1
    }
    Write-Host "         ✅ Playwright Chromium 완료" -ForegroundColor Green
}

function Upgrade-DatabaseSchema {
    Write-Host "[DB] Alembic 마이그레이션 적용 중..." -ForegroundColor Yellow
    Push-Location $DbBackendDir
    & $PyExe -m alembic upgrade head
    $migrationExit = $LASTEXITCODE
    Pop-Location
    if ($migrationExit -ne 0) {
        Write-Host "❌ DB 마이그레이션에 실패했습니다. 서버를 띄우지 않습니다." -ForegroundColor Red
        Write-Host "   기존 DB를 보존한 채 Alembic 오류를 먼저 확인하세요." -ForegroundColor Red
        exit 1
    }
    Write-Host "     ✅ DB 스키마 최신 상태" -ForegroundColor Green
}

Install-PythonRequirements "크롤러 관리자" (Join-Path $Root "packages\crawler-admin\requirements.txt")
Install-PythonRequirements "DB 관리자" (Join-Path $DbBackendDir "requirements.txt")
Ensure-PlaywrightChromium
Upgrade-DatabaseSchema

foreach ($dir in @($CrawlerFrontendDir, $DbFrontendDir)) {
    $name = Split-Path (Split-Path $dir -Parent) -Leaf
    Write-Host "[의존성] $name 프론트엔드 npm 동기화 중..." -ForegroundColor Yellow
    Push-Location $dir
    & cmd.exe /c "npm install --silent" 2>&1 | Out-Null
    $npmExit = $LASTEXITCODE
    Pop-Location
    if ($npmExit -ne 0) {
        Write-Host "❌ $name npm install에 실패했습니다." -ForegroundColor Red
        exit 1
    }
    Write-Host "         ✅ npm install 완료" -ForegroundColor Green
}
Write-Host ""

Write-Host "[정리] 기존 관리 서버 프로세스 정리 중..." -ForegroundColor Yellow
foreach ($port in @(8001, 5174, 8002, 5175)) {
    $conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
             Where-Object { $_.LocalPort -eq $port }
    foreach ($c in $conns) {
        $targetPid = $c.OwningProcess
        if ($targetPid -le 4 -or $targetPid -eq $PID) { continue }
        $children = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                    Where-Object { $_.ParentProcessId -eq $targetPid }
        foreach ($child in $children) {
            Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
        }
        Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 1
Write-Host "         ✅ 정리 완료" -ForegroundColor Green
Write-Host ""

Write-Host "🚀 크롤러 관리 백엔드 시작 (port 8001)..." -ForegroundColor Yellow
$crawlerBackend = Start-Process -PassThru -NoNewWindow -FilePath $PyExe `
    -ArgumentList "-m uvicorn api.app:create_app --factory --port 8001 --host 127.0.0.1" `
    -WorkingDirectory $CrawlerBackendDir

Write-Host "🚀 크롤러 관리 프론트엔드 시작 (port 5174)..." -ForegroundColor Yellow
$crawlerFrontend = Start-Process -PassThru -NoNewWindow -FilePath "npx.cmd" `
    -ArgumentList "vite --host 127.0.0.1 --port 5174 --strictPort" `
    -WorkingDirectory $CrawlerFrontendDir

Write-Host "🚀 DB 관리 백엔드 시작 (port 8002)..." -ForegroundColor Yellow
$dbBackend = Start-Process -PassThru -NoNewWindow -FilePath $PyExe `
    -ArgumentList "-m uvicorn api.app:create_app --factory --port 8002 --host 127.0.0.1" `
    -WorkingDirectory $DbBackendDir

Write-Host "🚀 DB 관리 프론트엔드 시작 (port 5175)..." -ForegroundColor Yellow
$dbFrontend = Start-Process -PassThru -NoNewWindow -FilePath "npx.cmd" `
    -ArgumentList "vite --host 127.0.0.1 --port 5175 --strictPort" `
    -WorkingDirectory $DbFrontendDir

$processes = @($crawlerBackend, $crawlerFrontend, $dbBackend, $dbFrontend)

Write-Host ""
Write-Host "⏳ 서버 준비 대기 중..." -ForegroundColor Yellow
$crawlerReady = $false
$dbReady = $false
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    if (-not $crawlerReady) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:8001/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($r.StatusCode -eq 200) { $crawlerReady = $true }
        } catch {}
    }
    if (-not $dbReady) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:8002/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
            if ($r.StatusCode -eq 200) { $dbReady = $true }
        } catch {}
    }
    if ($crawlerReady -and $dbReady) { break }
}

if (-not $crawlerReady -or -not $dbReady) {
    Write-Host ""
    Write-Host "❌ 관리 서버 준비에 실패했습니다." -ForegroundColor Red
    if (-not $crawlerReady) { Write-Host "   - 크롤러 백엔드(8001) health check 실패" -ForegroundColor Red }
    if (-not $dbReady) { Write-Host "   - DB관리 백엔드(8002) health check 실패" -ForegroundColor Red }
    Write-Host "   성공한 것처럼 계속 두지 않고 시작한 프로세스를 정리합니다." -ForegroundColor Red
    foreach ($p in $processes) {
        if ($p -and -not $p.HasExited) {
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  ✅ 관리 도구가 시작되었습니다!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  🕷️ 크롤러 관리:" -ForegroundColor White
Write-Host "     프론트엔드: http://localhost:5174" -ForegroundColor White
Write-Host "     백엔드 API: http://localhost:8001/docs  (✅ OK)" -ForegroundColor White
Write-Host ""
Write-Host "  🗄️ DB 관리:" -ForegroundColor White
Write-Host "     프론트엔드: http://localhost:5175" -ForegroundColor White
Write-Host "     백엔드 API: http://localhost:8002/docs  (✅ OK)" -ForegroundColor White
Write-Host ""
Write-Host "  Ctrl+C를 누르면 모든 서버가 종료됩니다." -ForegroundColor DarkGray
Write-Host ""

try {
    while ($true) {
        $allExited = $true
        foreach ($p in $processes) {
            if ($p -and -not $p.HasExited) { $allExited = $false; break }
        }
        if ($allExited) {
            Write-Host "모든 서버가 종료되었습니다." -ForegroundColor Yellow
            break
        }
        Start-Sleep -Seconds 2
    }
} finally {
    Write-Host ""
    Write-Host "🛑 서버 종료 중..." -ForegroundColor Yellow
    foreach ($p in $processes) {
        if ($p -and -not $p.HasExited) {
            $children = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                        Where-Object { $_.ParentProcessId -eq $p.Id }
            foreach ($child in $children) {
                Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
            }
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "✅ 모든 서버가 종료되었습니다." -ForegroundColor Green
}