<#
.SYNOPSIS
    admin 3-서비스 + 백엔드 E2E smoke 기동 스크립트

.DESCRIPTION
    크롤러 관리(8001/5174) + DB 관리(8002/5175) + AI 관리(8003/5176) 백엔드를 기동하고,
    /health 엔드포인트가 200 응답할 때까지 대기한다.
    smoke 테스트 통과 후 자동 종료한다.

    사용법:
        .\tools\admin_smoke_e2e_bootstrap.ps1                  # smoke 실행 후 자동 종료
        .\tools\admin_smoke_e2e_bootstrap.ps1 -KeepAlive       # smoke 후 서버 유지
        .\tools\admin_smoke_e2e_bootstrap.ps1 -BackendOnly     # 백엔드만 기동 (프론트 없음)
        .\tools\admin_smoke_e2e_bootstrap.ps1 -TimeoutSec 60   # 헬스체크 타임아웃 조정

    종료 코드:
        0 — smoke 전체 통과
        1 — 헬스체크 타임아웃 또는 smoke 실패
#>

param(
    [switch]$KeepAlive,
    [switch]$BackendOnly,
    [int]$TimeoutSec = 45
)

$ErrorActionPreference = "Continue"
$Root = if ($PSScriptRoot) { Split-Path $PSScriptRoot -Parent } else { Get-Location }

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  🛡️  Admin Smoke E2E Bootstrap" -ForegroundColor Cyan
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

# === 경로 설정 ===
$CrawlerBackend  = Join-Path $Root "packages\crawler-admin\backend"
$CrawlerFrontend = Join-Path $Root "packages\crawler-admin\frontend"
$DbBackend       = Join-Path $Root "packages\db-admin\backend"
$DbFrontend      = Join-Path $Root "packages\db-admin\frontend"
$AiBackend       = Join-Path $Root "packages\ai-admin\backend"
$AiFrontend      = Join-Path $Root "packages\ai-admin\frontend"
$SharedDir       = Join-Path $Root "packages\shared"
$IntegTestDir    = Join-Path $Root "packages\integration-tests"

# PYTHONPATH
$env:PYTHONPATH = "$SharedDir;$CrawlerBackend;$DbBackend;$AiBackend"

# === 기존 서버 정리 (포트 충돌 방지) ===
Write-Host "[정리] 포트 8001/8002/8003 정리..." -ForegroundColor Yellow
foreach ($port in @(8001, 8002, 8003)) {
    $conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
             Where-Object { $_.LocalPort -eq $port }
    foreach ($c in $conns) {
        $targetPid = $c.OwningProcess
        if ($targetPid -le 4 -or $targetPid -eq $PID) { continue }
        $proc = Get-Process -Id $targetPid -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "         포트 $port → PID $targetPid ($($proc.ProcessName)) 종료" -ForegroundColor DarkGray
            Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
        }
    }
}
if (-not $BackendOnly) {
    foreach ($port in @(5174, 5175, 5176)) {
        $conns = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
                 Where-Object { $_.LocalPort -eq $port }
        foreach ($c in $conns) {
            $targetPid = $c.OwningProcess
            if ($targetPid -le 4 -or $targetPid -eq $PID) { continue }
            Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
        }
    }
}
Start-Sleep -Seconds 1
Write-Host "         ✅ 정리 완료" -ForegroundColor Green
Write-Host ""

# === 서버 기동 ===
$processes = @()

Write-Host "🚀 [크롤러] 백엔드 시작 (port 8001)..." -ForegroundColor Yellow
$p = Start-Process -PassThru -NoNewWindow -FilePath $PyExe `
    -ArgumentList "-m uvicorn api.app:create_app --factory --port 8001 --host 127.0.0.1" `
    -WorkingDirectory $CrawlerBackend
$processes += [PSCustomObject]@{ Name = "크롤러-백엔드"; Process = $p; Port = 8001 }

Write-Host "🚀 [DB관리] 백엔드 시작 (port 8002)..." -ForegroundColor Yellow
$p = Start-Process -PassThru -NoNewWindow -FilePath $PyExe `
    -ArgumentList "-m uvicorn api.app:create_app --factory --port 8002 --host 127.0.0.1" `
    -WorkingDirectory $DbBackend
$processes += [PSCustomObject]@{ Name = "DB관리-백엔드"; Process = $p; Port = 8002 }

Write-Host "🚀 [AI관리] 백엔드 시작 (port 8003)..." -ForegroundColor Yellow
$p = Start-Process -PassThru -NoNewWindow -FilePath $PyExe `
    -ArgumentList "-m uvicorn api.app:create_app --factory --port 8003 --host 127.0.0.1" `
    -WorkingDirectory $AiBackend
$processes += [PSCustomObject]@{ Name = "AI관리-백엔드"; Process = $p; Port = 8003 }

if (-not $BackendOnly) {
    foreach ($dir in @($CrawlerFrontend, $DbFrontend, $AiFrontend)) {
        if (-not (Test-Path (Join-Path $dir "node_modules"))) {
            Write-Host "[의존성] $(Split-Path (Split-Path $dir -Parent) -Leaf)/frontend npm install..." -ForegroundColor Yellow
            Push-Location $dir
            & npm install --silent 2>&1 | Out-Null
            Pop-Location
        }
    }

    Write-Host "🚀 [크롤러] 프론트엔드 시작 (port 5174)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath "npx.cmd" `
        -ArgumentList "vite --port 5174" `
        -WorkingDirectory $CrawlerFrontend
    $processes += [PSCustomObject]@{ Name = "크롤러-프론트"; Process = $p; Port = 5174 }

    Write-Host "🚀 [DB관리] 프론트엔드 시작 (port 5175)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath "npx.cmd" `
        -ArgumentList "vite --port 5175" `
        -WorkingDirectory $DbFrontend
    $processes += [PSCustomObject]@{ Name = "DB관리-프론트"; Process = $p; Port = 5175 }

    Write-Host "🚀 [AI관리] 프론트엔드 시작 (port 5176)..." -ForegroundColor Yellow
    $p = Start-Process -PassThru -NoNewWindow -FilePath "npx.cmd" `
        -ArgumentList "vite --port 5176" `
        -WorkingDirectory $AiFrontend
    $processes += [PSCustomObject]@{ Name = "AI관리-프론트"; Process = $p; Port = 5176 }
}

Write-Host ""

# === 헬스체크 대기 ===
Write-Host "⏳ 백엔드 헬스체크 대기 중 (최대 ${TimeoutSec}초)..." -ForegroundColor Yellow

$healthChecks = @(
    @{ Name = "크롤러";  Url = "http://127.0.0.1:8001/health"; Ready = $false },
    @{ Name = "DB관리";  Url = "http://127.0.0.1:8002/health"; Ready = $false },
    @{ Name = "AI관리";  Url = "http://127.0.0.1:8003/health"; Ready = $false }
)

$deadline = (Get-Date).AddSeconds($TimeoutSec)
$allReady = $false
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    $pending = 0
    foreach ($c in $healthChecks) {
        if (-not $c.Ready) {
            try {
                $r = Invoke-WebRequest -Uri $c.Url -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
                if ($r -and $r.StatusCode -eq 200) {
                    $c.Ready = $true
                    Write-Host "         ✅ $($c.Name) READY" -ForegroundColor Green
                } else {
                    $pending++
                }
            } catch {
                $pending++
            }
        }
    }
    if ($pending -eq 0) { $allReady = $true; break }
}

if (-not $allReady) {
    $failed = $healthChecks | Where-Object { -not $_.Ready } | ForEach-Object { $_.Name }
    Write-Host ""
    Write-Host "❌ 헬스체크 타임아웃: $($failed -join ', ')" -ForegroundColor Red
    foreach ($item in $processes) {
        if (-not $item.Process.HasExited) {
            Stop-Process -Id $item.Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  ✅ Admin 서버 전체 READY" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host "     크롤러 백엔드: http://127.0.0.1:8001/docs" -ForegroundColor White
Write-Host "     DB관리 백엔드: http://127.0.0.1:8002/docs" -ForegroundColor White
Write-Host "     AI관리 백엔드: http://127.0.0.1:8003/docs" -ForegroundColor White
Write-Host ""

# === Smoke 테스트 실행 ===
Write-Host "🧪 Smoke 테스트 실행 중..." -ForegroundColor Yellow
$smokeExit = 0
try {
    & $PyExe -m pytest "$IntegTestDir\test_admin_smoke_e2e.py" -v --tb=short 2>&1 | ForEach-Object { Write-Host $_ }
    $smokeExit = $LASTEXITCODE
} catch {
    Write-Host "❌ Smoke 테스트 실행 오류: $_" -ForegroundColor Red
    $smokeExit = 1
}

# === 자동 종료 ===
if (-not $KeepAlive) {
    Write-Host ""
    Write-Host "🛑 서버 자동 종료 중..." -ForegroundColor Yellow
    foreach ($item in $processes) {
        if (-not $item.Process.HasExited) {
            $children = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                        Where-Object { $_.ParentProcessId -eq $item.Process.Id }
            foreach ($child in $children) {
                Stop-Process -Id $child.ProcessId -Force -ErrorAction SilentlyContinue
            }
            Stop-Process -Id $item.Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "✅ 모든 서버 종료 완료" -ForegroundColor Green
}

if ($smokeExit -eq 0) {
    Write-Host ""
    Write-Host "🎉 Admin Smoke E2E: PASS" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "❌ Admin Smoke E2E: FAIL (exit $smokeExit)" -ForegroundColor Red
}

exit $smokeExit
