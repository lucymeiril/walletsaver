<#
.SYNOPSIS
    지갑 지키미 — 전체 시스템 한 번에 시작
.DESCRIPTION
    웹사이트(8000/5173) + 크롤러 관리(8001/5174) + DB 관리(8002/5175)
    총 6개 서버를 한 번에 시작하고 브라우저를 엽니다.
    Ctrl+C로 전부 종료됩니다.

    사용법:
      .\start-all.ps1          # 전체 시작
      .\start-all.ps1 -Web     # 웹사이트만
      .\start-all.ps1 -Admin   # 관리 도구만
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
$WebFrontend       = Join-Path $Root "packages\website\frontend"
$WebBackend        = Join-Path $Root "packages\website\backend"
$CrawlerFrontend   = Join-Path $Root "packages\crawler-admin\frontend"
$CrawlerBackend    = Join-Path $Root "packages\crawler-admin\backend"
$DbFrontend        = Join-Path $Root "packages\db-admin\frontend"
$DbBackend         = Join-Path $Root "packages\db-admin\backend"
$SharedDir         = Join-Path $Root "packages\shared"

# PYTHONPATH — shared 모듈 참조용
$env:PYTHONPATH = "$SharedDir;$CrawlerBackend;$DbBackend;$WebBackend"

# === 의존성 설치 ===
Write-Host "[의존성] Python 패키지 확인..." -ForegroundColor Yellow
& $PyExe -m pip install --quiet fastapi uvicorn httpx requests beautifulsoup4 lxml 2>$null | Out-Null
Write-Host "         ✅ Python 패키지 완료" -ForegroundColor Green

$frontendDirs = @()
if ($Web)   { $frontendDirs += $WebFrontend }
if ($Admin) { $frontendDirs += $CrawlerFrontend; $frontendDirs += $DbFrontend }

foreach ($dir in $frontendDirs) {
    $name = (Split-Path (Split-Path $dir -Parent) -Leaf) + "/frontend"
    if (-not (Test-Path (Join-Path $dir "node_modules"))) {
        Write-Host "[의존성] $name npm install..." -ForegroundColor Yellow
        Push-Location $dir
        & cmd.exe /c "npm install --silent" 2>&1 | Out-Null
        Pop-Location
        Write-Host "         ✅ $name 완료" -ForegroundColor Green
    } else {
        Write-Host "[의존성] $name ✅" -ForegroundColor Green
    }
}
Write-Host ""

# === 서버 시작 ===
$processes = @()

if ($Web) {
    Write-Host "🚀 [웹] 백엔드 시작 (port 8000)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath $PyExe `
        -ArgumentList "-m uvicorn api.app:create_app --factory --reload --port 8000 --host 127.0.0.1" `
        -WorkingDirectory $WebBackend
    $processes += $p

    Write-Host "🚀 [웹] 프론트엔드 시작 (port 5173)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath "cmd.exe" `
        -ArgumentList "/c cd /d `"$WebFrontend`" && npm run dev" `
        -WorkingDirectory $WebFrontend
    $processes += $p
}

if ($Admin) {
    Write-Host "🚀 [크롤러] 백엔드 시작 (port 8001)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath $PyExe `
        -ArgumentList "-m uvicorn api.app:create_app --factory --reload --port 8001 --host 127.0.0.1" `
        -WorkingDirectory $CrawlerBackend
    $processes += $p

    Write-Host "🚀 [크롤러] 프론트엔드 시작 (port 5174)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath "cmd.exe" `
        -ArgumentList "/c cd /d `"$CrawlerFrontend`" && npm run dev" `
        -WorkingDirectory $CrawlerFrontend
    $processes += $p

    Write-Host "🚀 [DB관리] 백엔드 시작 (port 8002)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath $PyExe `
        -ArgumentList "-m uvicorn api.app:create_app --factory --reload --port 8002 --host 127.0.0.1" `
        -WorkingDirectory $DbBackend
    $processes += $p

    Write-Host "🚀 [DB관리] 프론트엔드 시작 (port 5175)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath "cmd.exe" `
        -ArgumentList "/c cd /d `"$DbFrontend`" && npm run dev" `
        -WorkingDirectory $DbFrontend
    $processes += $p
}

# === 헬스체크 ===
Write-Host ""
Write-Host "⏳ 서버 준비 대기 중..." -ForegroundColor Yellow

$checks = @()
if ($Web)   { $checks += @{ Name = "웹"; Url = "http://127.0.0.1:8000/api/health"; Ready = $false } }
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
    Write-Host "  🌐 웹사이트" -ForegroundColor White
    Write-Host "     프론트엔드: http://localhost:5173" -ForegroundColor White
    Write-Host "     백엔드 API: http://localhost:8000/docs  $stat" -ForegroundColor White
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
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
    Write-Host "✅ 모든 서버가 종료되었습니다." -ForegroundColor Green
}
