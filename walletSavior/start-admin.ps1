<#
.SYNOPSIS
    지갑 지키미 — 관리 도구 시작 (크롤러 관리 + DB 관리)
.DESCRIPTION
    크롤러 관리(8001/5174)와 DB 관리(8002/5175) 서버를 시작합니다.
    서버 전용 내부 도구로 배포하지 않습니다.
#>

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
if (-not $Root) { $Root = Get-Location }

Write-Host ""
Write-Host "============================================" -ForegroundColor Magenta
Write-Host "  🔧 지갑 지키미 — 관리 도구 시작" -ForegroundColor Magenta
Write-Host "============================================" -ForegroundColor Magenta
Write-Host ""

$CrawlerBackendDir  = Join-Path $Root "packages\crawler-admin\backend"
$CrawlerFrontendDir = Join-Path $Root "packages\crawler-admin\frontend"
$DbBackendDir       = Join-Path $Root "packages\db-admin\backend"
$DbFrontendDir      = Join-Path $Root "packages\db-admin\frontend"

# --- 의존성 확인 ---
Write-Host "[의존성] 백엔드 패키지 확인..." -ForegroundColor Yellow
py -m pip install --quiet fastapi uvicorn 2>&1 | Out-Null
Write-Host "         ✅ 완료" -ForegroundColor Green

foreach ($dir in @($CrawlerFrontendDir, $DbFrontendDir)) {
    $name = Split-Path (Split-Path $dir -Parent) -Leaf
    if (-not (Test-Path (Join-Path $dir "node_modules"))) {
        Write-Host "[의존성] $name 프론트엔드 설치 중..." -ForegroundColor Yellow
        Push-Location $dir
        npm install --silent 2>&1 | Out-Null
        Pop-Location
        Write-Host "         ✅ npm install 완료" -ForegroundColor Green
    } else {
        Write-Host "[의존성] $name 프론트엔드 ✅" -ForegroundColor Green
    }
}
Write-Host ""

# --- 크롤러 관리 백엔드 (port 8001) ---
Write-Host "🚀 크롤러 관리 백엔드 시작 (port 8001)..." -ForegroundColor Yellow
$crawlerBackend = Start-Process -PassThru -NoNewWindow -FilePath "py" `
    -ArgumentList "-m uvicorn api.app:create_app --factory --reload --port 8001 --host 127.0.0.1" `
    -WorkingDirectory $CrawlerBackendDir

# --- 크롤러 관리 프론트엔드 (port 5174) ---
Write-Host "🚀 크롤러 관리 프론트엔드 시작 (port 5174)..." -ForegroundColor Yellow
$crawlerFrontend = Start-Process -PassThru -NoNewWindow -FilePath "npm" `
    -ArgumentList "run dev" `
    -WorkingDirectory $CrawlerFrontendDir

# --- DB 관리 백엔드 (port 8002) ---
Write-Host "🚀 DB 관리 백엔드 시작 (port 8002)..." -ForegroundColor Yellow
$dbBackend = Start-Process -PassThru -NoNewWindow -FilePath "py" `
    -ArgumentList "-m uvicorn api.app:create_app --factory --reload --port 8002 --host 127.0.0.1" `
    -WorkingDirectory $DbBackendDir

# --- DB 관리 프론트엔드 (port 5175) ---
Write-Host "🚀 DB 관리 프론트엔드 시작 (port 5175)..." -ForegroundColor Yellow
$dbFrontend = Start-Process -PassThru -NoNewWindow -FilePath "npm" `
    -ArgumentList "run dev" `
    -WorkingDirectory $DbFrontendDir

# --- 서버 준비 대기 ---
Write-Host ""
Write-Host "⏳ 서버 준비 대기 중..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  ✅ 관리 도구가 시작되었습니다!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  🕷️ 크롤러 관리:" -ForegroundColor White
Write-Host "     프론트엔드: http://localhost:5174" -ForegroundColor White
Write-Host "     백엔드 API: http://localhost:8001/docs" -ForegroundColor White
Write-Host ""
Write-Host "  🗄️ DB 관리:" -ForegroundColor White
Write-Host "     프론트엔드: http://localhost:5175" -ForegroundColor White
Write-Host "     백엔드 API: http://localhost:8002/docs" -ForegroundColor White
Write-Host ""
Write-Host "  Ctrl+C를 누르면 모든 서버가 종료됩니다." -ForegroundColor DarkGray
Write-Host ""

$processes = @($crawlerBackend, $crawlerFrontend, $dbBackend, $dbFrontend)

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
        if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
    Write-Host "✅ 모든 서버가 종료되었습니다." -ForegroundColor Green
}
