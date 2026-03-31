<#
.SYNOPSIS
    지갑 지키미 — 실행 중인 모든 개발 서버 종료
.DESCRIPTION
    포트 5173, 5174, 5175, 8000, 8001, 8002에서 실행 중인 프로세스를 종료합니다.
#>

Write-Host ""
Write-Host "🛑 지갑 지키미 서버 종료 중..." -ForegroundColor Yellow
Write-Host ""

$ports = @(8000, 8001, 8002, 5173, 5174, 5175)
$killed = 0

foreach ($port in $ports) {
    $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $connections) {
        $pid = $conn.OwningProcess
        $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "  포트 $port → PID $pid ($($proc.ProcessName)) 종료" -ForegroundColor White
            Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            $killed++
        }
    }
}

Write-Host ""
if ($killed -gt 0) {
    Write-Host "✅ $killed 개 프로세스가 종료되었습니다." -ForegroundColor Green
} else {
    Write-Host "ℹ️  실행 중인 서버가 없습니다." -ForegroundColor Cyan
}
Write-Host ""
