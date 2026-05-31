<#
.SYNOPSIS
    지갑 지키미 — 전체 시스템 한 번에 시작
.DESCRIPTION
    웹 프론트엔드(5173) + Public API(8000) + 크롤러 관리(8001/5174) + DB 관리(8002/5175)
    총 6개 서버를 한 번에 시작하고 브라우저를 엽니다.
    Ctrl+C로 전부 종료됩니다.

    사용법:
      .\start-all.ps1          # 전체 시작
      .\start-all.ps1 -Web     # 웹사이트만
      .\start-all.ps1 -Admin   # 관리 도구만

    주의: --reload를 사용하지 않습니다.
    WatchFiles + cmd.exe 조합에서 파일 변경 시 "Terminate batch job?" 프롬프트가
    모든 서버를 죽이는 버그가 있으며, 리로더 프로세스가 죽어도 워커가 좀비로 남아
    구(旧) 코드를 계속 서비스하는 심각한 문제가 있습니다.
    코드를 수정한 경우 이 스크립트를 재시작하세요.
#>

param(
    [switch]$Web,
    [switch]$Admin
)

$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
if (-not $Root) { $Root = Get-Location }

# 아무 플래그도 없으면 전부 시작
if (-not $Web -and -not $Admin) { $Web = $true; $Admin = $true }

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  🛡️  지갑 지키미 — 전체 시스템 시작" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# === Python 감지 ===
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
Write-Host "  🐍 Python: $PyExe ($( & $PyExe --version 2>&1 ))" -ForegroundColor DarkGray

# === npm 감지 ===
$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npmCmd) {
    Write-Host "❌ npm을 찾을 수 없습니다." -ForegroundColor Red
    exit 1
}
Write-Host "  📦 npm: $($npmCmd.Source)" -ForegroundColor DarkGray
Write-Host ""

# === 경로 설정 ===
$WebFrontend       = Join-Path $Root "packages\web-frontend"
$WebBackend        = Join-Path $Root "packages\web-api\backend"
$CrawlerFrontend   = Join-Path $Root "packages\crawler-admin\frontend"
$CrawlerBackend    = Join-Path $Root "packages\crawler-admin\backend"
$DbFrontend        = Join-Path $Root "packages\db-admin\frontend"
$DbBackend         = Join-Path $Root "packages\db-admin\backend"
$SharedDir         = Join-Path $Root "packages\shared"

# PYTHONPATH — shared 모듈 및 각 백엔드 직접 실행용
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:PYTHONPATH = "$Root;$SharedDir;$CrawlerBackend;$DbBackend;$WebBackend"
if (-not $env:WALLETSAVIOR_CORS_ORIGINS) { $env:WALLETSAVIOR_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173" }
if (-not $env:DB_ADMIN_API_URL) { $env:DB_ADMIN_API_URL = "http://127.0.0.1:8002/api/prices/bulk" }
if (-not $env:INGESTION_API_URL) { $env:INGESTION_API_URL = "http://127.0.0.1:8002/api/ingestions" }
if (-not $env:WALLETSAVIOR_PUBLIC_DB) { $env:WALLETSAVIOR_PUBLIC_DB = Join-Path $Root "packages\db-admin\backend\walletguardian.db" }
if (-not $env:REQUIRE_AUTH) { $env:REQUIRE_AUTH = "false" }
if (-not $env:DATABASE_URL) { $env:DATABASE_URL = "sqlite:///" + (Join-Path $Root "packages\db-admin\backend\walletguardian.db").Replace("\", "/") }

# === __pycache__ 정리 (좀비 워커 방지) ===
Write-Host "[정리] __pycache__ 정리 중..." -ForegroundColor Yellow
Get-ChildItem -Path (Join-Path $Root "packages") -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
Write-Host "         ✅ __pycache__ 정리 완료" -ForegroundColor Green

# === 의존성 설치 ===
Write-Host "[의존성] Python 패키지 확인..." -ForegroundColor Yellow
& $PyExe -m pip install --quiet fastapi uvicorn pydantic httpx requests beautifulsoup4 lxml sqlalchemy pyyaml slowapi limits psutil python-dotenv python-multipart bcrypt 2>$null | Out-Null
Write-Host "         ✅ Python 패키지 완료" -ForegroundColor Green

$frontendDirs = @()
if ($Web)   { $frontendDirs += $WebFrontend }
if ($Admin) { $frontendDirs += $CrawlerFrontend; $frontendDirs += $DbFrontend }

foreach ($dir in $frontendDirs) {
    $name = (Split-Path (Split-Path $dir -Parent) -Leaf) + "/frontend"
    if (-not (Test-Path (Join-Path $dir "node_modules"))) {
        Write-Host "[의존성] $name npm install..." -ForegroundColor Yellow
        Push-Location $dir
        & npm install --silent 2>&1 | Out-Null
        Pop-Location
        Write-Host "         ✅ $name 완료" -ForegroundColor Green
    } else {
        Write-Host "[의존성] $name ✅" -ForegroundColor Green
    }
}
Write-Host ""

# === 기존 서버 정리 (포트 충돌 방지) ===
Write-Host "[정리] 기존 서버 프로세스 정리 중..." -ForegroundColor Yellow
$portsToClean = @()
if ($Web)   { $portsToClean += @(8000, 5173) }
if ($Admin) { $portsToClean += @(8001, 5174, 8002, 5175) }

foreach ($port in $portsToClean) {
    $conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
             Where-Object { $_.LocalPort -eq $port }
    foreach ($c in $conns) {
        $targetPid = $c.OwningProcess
        if ($targetPid -le 4 -or $targetPid -eq $PID) { continue }
        # 메인 프로세스 종료
        $proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "         포트 $port → PID $targetPid ($($proc.ProcessName)) 종료" -ForegroundColor DarkGray
            Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
        }
        # 좀비 자식 워커도 검색하여 종료
        $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $targetPid }
        foreach ($child in $children) {
            Write-Host "         좀비 자식 PID $($child.ProcessId) 종료" -ForegroundColor DarkGray
            Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
}
Start-Sleep -Seconds 2
Write-Host "         ✅ 정리 완료" -ForegroundColor Green
Write-Host ""

# === 서버 시작 ===
$processes = @()

# --reload 제거: WatchFiles가 cmd.exe와 결합 시 "Terminate batch job?" 프롬프트로
# 모든 서버를 죽이고, 리로더 부모가 죽어도 워커 자식이 좀비로 남아
# 구(旧) 코드를 계속 서비스하는 심각한 문제 방지.
# 코드 수정 후에는 Ctrl+C → 재시작으로 대응.

if ($Web) {
    Write-Host "🚀 [웹] Public API 시작 (port 8000)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath $PyExe `
        -ArgumentList "-m uvicorn main:app --port 8000 --host 127.0.0.1" `
        -WorkingDirectory $WebBackend
    $processes += $p

    Write-Host "🚀 [웹] 프론트엔드 시작 (port 5173)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath "npx.cmd" `
        -ArgumentList "vite --host 127.0.0.1 --port 5173 --strictPort" `
        -WorkingDirectory $WebFrontend
    $processes += $p
}

if ($Admin) {
    Write-Host "🚀 [크롤러] 백엔드 시작 (port 8001)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath $PyExe `
        -ArgumentList "-m uvicorn api.app:create_app --factory --port 8001 --host 127.0.0.1" `
        -WorkingDirectory $CrawlerBackend
    $processes += $p

    Write-Host "🚀 [크롤러] 프론트엔드 시작 (port 5174)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath "npx.cmd" `
        -ArgumentList "vite --host 127.0.0.1 --port 5174 --strictPort" `
        -WorkingDirectory $CrawlerFrontend
    $processes += $p

    Write-Host "🚀 [DB관리] 백엔드 시작 (port 8002)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath $PyExe `
        -ArgumentList "-m uvicorn api.app:create_app --factory --port 8002 --host 127.0.0.1" `
        -WorkingDirectory $DbBackend
    $processes += $p

    Write-Host "🚀 [DB관리] 프론트엔드 시작 (port 5175)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath "npx.cmd" `
        -ArgumentList "vite --host 127.0.0.1 --port 5175 --strictPort" `
        -WorkingDirectory $DbFrontend
    $processes += $p
}

# === 헬스체크 ===
Write-Host ""
Write-Host "⏳ 서버 준비 대기 중..." -ForegroundColor Yellow

$checks = @()
if ($Web)   { $checks += @{ Name = "웹 API"; Url = "http://127.0.0.1:8000/api/health"; Ready = $false } }
if ($Admin) {
    $checks += @{ Name = "크롤러"; Url = "http://127.0.0.1:8001/health"; Ready = $false }
    $checks += @{ Name = "DB관리"; Url = "http://127.0.0.1:8002/health"; Ready = $false }
}

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    $allReady = $true
    foreach ($c in $checks) {
        if (-not $c.Ready) {
            try {
                $r = Invoke-WebRequest -Uri $c.Url -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
                if ($r.StatusCode -eq 200) { $c.Ready = $true }
            } catch {}
        }
        if (-not $c.Ready) { $allReady = $false }
    }
    if ($allReady) { break }
}

# === 결과 출력 ===
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  ✅ 시스템이 시작되었습니다!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""

if ($Web) {
    $stat = if ($checks[0].Ready) { "✅" } else { "⏳" }
    Write-Host "  🌐 웹" -ForegroundColor White
    Write-Host "     프론트엔드: http://localhost:5173" -ForegroundColor White
    Write-Host "     Public API: http://localhost:8000/api/health  $stat" -ForegroundColor White
    Write-Host ""
}
if ($Admin) {
    $idx = if ($Web) { 1 } else { 0 }
    $cStat = if ($checks[$idx].Ready) { "✅" } else { "⏳" }
    $dStat = if ($checks[$idx+1].Ready) { "✅" } else { "⏳" }
    Write-Host "  🕷️ 크롤러 관리" -ForegroundColor White
    Write-Host "     프론트엔드: http://localhost:5174" -ForegroundColor White
    Write-Host "     백엔드 API: http://localhost:8001/docs  $cStat" -ForegroundColor White
    Write-Host ""
    Write-Host "  🗄️ DB 관리" -ForegroundColor White
    Write-Host "     프론트엔드: http://localhost:5175" -ForegroundColor White
    Write-Host "     백엔드 API: http://localhost:8002/docs  $dStat" -ForegroundColor White
    Write-Host ""
}

# 브라우저 열기 — 웹사이트 우선
if ($Web) {
    Start-Process "http://localhost:5173"
}

Write-Host "  Ctrl+C를 누르면 모든 서버가 종료됩니다." -ForegroundColor DarkGray
Write-Host ""

# === 종료 대기 ===
try {
    while ($true) {
        $allExited = $true
        foreach ($p in $processes) {
            if (-not $p.HasExited) { $allExited = $false; break }
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
            # 자식 프로세스도 먼저 종료 (좀비 방지)
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
