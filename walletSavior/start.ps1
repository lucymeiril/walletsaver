<#
.SYNOPSIS
    지갑 지키미 (WalletSavior) — 웹사이트 개발 서버 시작
.DESCRIPTION
    웹사이트 프론트엔드(5173)와 백엔드(8000)를 동시에 시작하고
    준비되면 브라우저를 자동으로 열어줍니다.
    Ctrl+C로 모든 서버를 종료합니다.
#>

$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
if (-not $Root) { $Root = Get-Location }

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  🛡️  지갑 지키미 — 웹사이트 시작" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# --- Python 실행 파일 감지 ---
$PyExe = $null
foreach ($candidate in @("py", "python", "python3")) {
    try {
        $null = & $candidate --version 2>&1
        if ($LASTEXITCODE -eq 0) { $PyExe = $candidate; break }
    } catch {}
}
if (-not $PyExe) {
    Write-Host "❌ Python을 찾을 수 없습니다. py / python / python3 중 하나가 PATH에 있어야 합니다." -ForegroundColor Red
    exit 1
}
Write-Host "  🐍 Python: $PyExe ($( & $PyExe --version 2>&1 ))" -ForegroundColor DarkGray

# --- npm 실행 파일 감지 ---
$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if (-not $npmCmd) {
    Write-Host "❌ npm을 찾을 수 없습니다. Node.js가 설치되어 있어야 합니다." -ForegroundColor Red
    exit 1
}
$NpmPath = $npmCmd.Source
Write-Host "  📦 npm: $NpmPath" -ForegroundColor DarkGray
Write-Host ""

# --- 의존성 확인 ---
$FrontendDir = Join-Path $Root "packages\website\frontend"
$BackendDir  = Join-Path $Root "packages\website\backend"

if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    Write-Host "[1/2] 프론트엔드 의존성 설치 중..." -ForegroundColor Yellow
    Push-Location $FrontendDir
    & cmd.exe /c "npm install --silent" 2>&1 | Out-Null
    Pop-Location
    Write-Host "      ✅ npm install 완료" -ForegroundColor Green
} else {
    Write-Host "[1/2] 프론트엔드 의존성 ✅" -ForegroundColor Green
}

Write-Host "[2/2] 백엔드 의존성 확인..." -ForegroundColor Yellow
& $PyExe -m pip install --quiet fastapi uvicorn httpx sqlalchemy pyyaml 2>$null | Out-Null
Write-Host "      ✅ 백엔드 의존성 확인 완료" -ForegroundColor Green
Write-Host ""

# --- 백엔드 시작 (port 8000) ---
# PYTHONPATH — shared 모듈 + db-admin 스토리지 참조용
$SharedDir = Join-Path $Root "packages\shared"
$DbBackendDir = Join-Path $Root "packages\db-admin\backend"
$env:PYTHONPATH = "$SharedDir;$DbBackendDir;$BackendDir"

Write-Host "🚀 백엔드 서버 시작 (port 8000)..." -ForegroundColor Yellow
$backend = Start-Process -PassThru -NoNewWindow -FilePath $PyExe `
    -ArgumentList "-m uvicorn api.app:create_app --factory --reload --port 8000 --host 127.0.0.1" `
    -WorkingDirectory $BackendDir

# --- 프론트엔드 시작 (port 5173) ---
Write-Host "🚀 프론트엔드 서버 시작 (port 5173)..." -ForegroundColor Yellow
$frontend = Start-Process -PassThru -NoNewWindow -FilePath "cmd.exe" `
    -ArgumentList "/c cd /d `"$FrontendDir`" && npm run dev" `
    -WorkingDirectory $FrontendDir

# --- 서버 준비 대기 ---
Write-Host ""
Write-Host "⏳ 서버 준비 대기 중..." -ForegroundColor Yellow
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  ✅ 서버가 시작되었습니다!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  🌐 웹사이트:  http://localhost:5173" -ForegroundColor White
Write-Host "  📡 API:       http://localhost:8000/api/health" -ForegroundColor White
Write-Host "  📖 API Docs:  http://localhost:8000/docs" -ForegroundColor White
Write-Host ""

if ($ready) {
    Write-Host "  백엔드 헬스체크: ✅ OK" -ForegroundColor Green
} else {
    Write-Host "  백엔드 헬스체크: ⚠️  아직 시작 중..." -ForegroundColor Yellow
}
Write-Host ""

# --- 브라우저 열기 ---
Start-Process "http://localhost:5173"

Write-Host "  Ctrl+C를 누르면 모든 서버가 종료됩니다." -ForegroundColor DarkGray
Write-Host ""

# --- 종료 대기 ---
try {
    while ($true) {
        if ($backend.HasExited -and $frontend.HasExited) {
            Write-Host "서버가 종료되었습니다." -ForegroundColor Yellow
            break
        }
        Start-Sleep -Seconds 2
    }
} finally {
    Write-Host ""
    Write-Host "🛑 서버 종료 중..." -ForegroundColor Yellow
    if (-not $backend.HasExited)  { Stop-Process -Id $backend.Id  -Force -ErrorAction SilentlyContinue }
    if (-not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue }
    Write-Host "✅ 모든 서버가 종료되었습니다." -ForegroundColor Green
}
