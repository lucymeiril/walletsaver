# WalletSavior — 로컬 통합 실행 스크립트
# web-api (uvicorn) + web-frontend (vite dev) 동시 기동
# 사용법: .\tools\run_web_local.ps1

$REPO_ROOT = Split-Path -Parent $PSScriptRoot
$BACKEND_DIR = Join-Path $REPO_ROOT "packages\web-api\backend"
$FRONTEND_DIR = Join-Path $REPO_ROOT "packages\web-frontend"

Write-Host "🚀 WalletSavior 로컬 개발 서버 시작" -ForegroundColor Cyan
Write-Host "  Backend : http://127.0.0.1:8010/api/v1" -ForegroundColor Green
Write-Host "  Frontend: http://127.0.0.1:5173" -ForegroundColor Green
Write-Host ""

# Check snapshot exists
$SNAPSHOT = Join-Path $REPO_ROOT ".walletsavior\public_snapshot.sqlite"
if (-not (Test-Path $SNAPSHOT)) {
    Write-Host "⚠️  스냅샷 없음: $SNAPSHOT" -ForegroundColor Yellow
    Write-Host "   먼저 실행하세요:" -ForegroundColor Yellow
    Write-Host "   py -3 packages\db-admin\backend\scripts\phaseD_oneshot_public_db.py --source fixtures --ai mock --commit" -ForegroundColor Yellow
    Write-Host ""
}

# Start backend
$backendJob = Start-Job -ScriptBlock {
    param($dir)
    Set-Location $dir
    py -3 -m uvicorn api.app:app --host 127.0.0.1 --port 8010 --reload
} -ArgumentList $BACKEND_DIR

Write-Host "✅ Backend 시작 (Job ID: $($backendJob.Id))" -ForegroundColor Green

Start-Sleep -Seconds 2

# Start frontend
$frontendJob = Start-Job -ScriptBlock {
    param($dir)
    Set-Location $dir
    npm run dev
} -ArgumentList $FRONTEND_DIR

Write-Host "✅ Frontend 시작 (Job ID: $($frontendJob.Id))" -ForegroundColor Green
Write-Host ""
Write-Host "종료하려면 Ctrl+C 를 누르거나 아래 명령어를 실행하세요:" -ForegroundColor Gray
Write-Host "  Stop-Job $($backendJob.Id), $($frontendJob.Id); Remove-Job $($backendJob.Id), $($frontendJob.Id)" -ForegroundColor Gray
Write-Host ""

try {
    # Stream output from both jobs
    while ($true) {
        $backendJob | Receive-Job | ForEach-Object { Write-Host "[BACKEND] $_" -ForegroundColor Blue }
        $frontendJob | Receive-Job | ForEach-Object { Write-Host "[FRONTEND] $_" -ForegroundColor Magenta }
        Start-Sleep -Milliseconds 500
    }
} finally {
    Write-Host "`n서버 종료 중..." -ForegroundColor Yellow
    Stop-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
    Remove-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
    Write-Host "완료" -ForegroundColor Green
}
