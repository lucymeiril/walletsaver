<#
.SYNOPSIS
    지갑 지키미 — 로컬 웹/관리 도구 시작
.DESCRIPTION
    -Web   : web-api(8000) + web-frontend(5173)만 실행
    -Admin : crawler-admin(8001/5174) + db-admin(8002/5175)만 실행
    -ForcePorts : 필요한 포트를 점유한 기존 프로세스를 명시적으로 종료
    옵션이 없으면 둘 다 실행합니다.

    web-api는 db-admin 소스나 walletguardian.db를 직접 사용하지 않습니다.
    교체 가능한 공개 snapshot과 서버 소유 SQLite(accounts/board/interactions)를
    분리한 실제 배포 구조를 로컬에서도 그대로 사용합니다.
#>

param(
    [switch]$Web,
    [switch]$Admin,
    [switch]$ForcePorts
)

$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
if (-not $Root) { $Root = Get-Location }
if (-not $Web -and -not $Admin) { $Web = $true; $Admin = $true }

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  🛡️  지갑 지키미 — 로컬 시스템 시작" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
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

$npmCmd = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $npmCmd) {
    Write-Host "❌ npm을 찾을 수 없습니다." -ForegroundColor Red
    exit 1
}

$WebFrontend     = Join-Path $Root "packages\web-frontend"
$WebBackend      = Join-Path $Root "packages\web-api\backend"
$CrawlerFrontend = Join-Path $Root "packages\crawler-admin\frontend"
$CrawlerBackend  = Join-Path $Root "packages\crawler-admin\backend"
$DbFrontend      = Join-Path $Root "packages\db-admin\frontend"
$DbBackend       = Join-Path $Root "packages\db-admin\backend"
$SharedDir       = Join-Path $Root "packages\shared"
$DataDir         = Join-Path $Root ".walletsavior"
New-Item -ItemType Directory -Force -Path $DataDir | Out-Null

# crawler-admin과 web-api가 반드시 같은 로컬 OPINET snapshot을 보게 합니다.
# 아직 크롤링하지 않은 새 환경에서도 빈 스키마를 준비해 /api/gas/nearby가
# "snapshot 없음" 503 대신 정상적인 빈 결과를 반환하도록 합니다.
if (-not $env:OPINET_DB_PATH) {
    $env:OPINET_DB_PATH = Join-Path $DataDir "opinet.db"
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"

$pythonPaths = @($Root, $SharedDir)
if ($Web) { $pythonPaths += $WebBackend }
if ($Admin) { $pythonPaths += @($CrawlerBackend, $DbBackend) }
$env:PYTHONPATH = ($pythonPaths -join ";")

if ($Web) {
    if (-not $env:WALLETSAVIOR_CORS_ORIGINS) {
        $env:WALLETSAVIOR_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173"
    }
    if (-not $env:WALLETSAVIOR_PUBLIC_DB) {
        $env:WALLETSAVIOR_PUBLIC_DB = Join-Path $DataDir "public_snapshot.sqlite"
    }
    if (-not $env:WALLETSAVIOR_EXTERNAL_HOTDEAL_DB) {
        $env:WALLETSAVIOR_EXTERNAL_HOTDEAL_DB = Join-Path $DataDir "external_hotdeals.sqlite"
    }
    if (-not $env:WALLETSAVIOR_ACCOUNT_DB) {
        $env:WALLETSAVIOR_ACCOUNT_DB = Join-Path $DataDir "accounts.sqlite"
    }
    if (-not $env:WALLETSAVIOR_INTERACTION_DB) {
        $env:WALLETSAVIOR_INTERACTION_DB = Join-Path $DataDir "interactions.sqlite"
    }
    if (-not $env:WALLETSAVIOR_BOARD_DB) {
        $env:WALLETSAVIOR_BOARD_DB = Join-Path $DataDir "board.sqlite"
    }
}

if ($Admin) {
    if (-not $env:DB_ADMIN_API_URL) {
        $env:DB_ADMIN_API_URL = "http://127.0.0.1:8002/api/prices/bulk"
    }
    if (-not $env:INGESTION_API_URL) {
        $env:INGESTION_API_URL = "http://127.0.0.1:8002/api/ingestions"
    }
    if (-not $env:REQUIRE_AUTH) { $env:REQUIRE_AUTH = "false" }
    if (-not $env:DATABASE_URL) {
        $dbPath = (Join-Path $DataDir "admin.sqlite").Replace("\", "/")
        $env:DATABASE_URL = "sqlite:///$dbPath"
    }
    if (-not $env:DB_ADMIN_DATABASE_URL) {
        $env:DB_ADMIN_DATABASE_URL = $env:DATABASE_URL
    }
    if (-not $env:WALLETSAVIOR_PUBLIC_DB) {
        $env:WALLETSAVIOR_PUBLIC_DB = Join-Path $DataDir "public_snapshot.sqlite"
    }
    if (-not $env:WALLETSAVIOR_EXTERNAL_HOTDEAL_DB) {
        $env:WALLETSAVIOR_EXTERNAL_HOTDEAL_DB = Join-Path $DataDir "external_hotdeals.sqlite"
    }
}

# 로컬에서 web+admin을 함께 켤 때 db-admin의 커뮤니티 관리 요청은
# loopback web-api를 통해 전달합니다. 공개 서버용 토큰은 환경변수로 따로 설정하세요.
if ($Web -and $Admin) {
    if (-not $env:WALLETSAVIOR_REMOTE_ADMIN_URL) {
        $env:WALLETSAVIOR_REMOTE_ADMIN_URL = "http://127.0.0.1:8000"
    }
    if (-not $env:WALLETSAVIOR_REMOTE_ADMIN_TOKEN) {
        $env:WALLETSAVIOR_REMOTE_ADMIN_TOKEN = "walletsavior-local-loopback-admin"
    }
    if (
        -not $env:WALLETSAVIOR_REMOTE_SNAPSHOT_UPLOAD -and
        $env:WALLETSAVIOR_REMOTE_ADMIN_URL -match "^https?://(127\.0\.0\.1|localhost)(:\d+)?/?$"
    ) {
        # 같은 로컬 파일을 web-api와 db-admin이 공유하므로 자기 자신에게 다시
        # HTTP 업로드하지 않습니다. 실제 원격 URL을 설정하면 기본값(true)으로 업로드됩니다.
        $env:WALLETSAVIOR_REMOTE_SNAPSHOT_UPLOAD = "false"
    }
}

# 로컬 실행용 임시 JWT 키. 배포에서는 JWT_SECRET_KEY를 명시적으로 지정합니다.
if ($Web -and -not $env:JWT_SECRET_KEY) {
    $jwtBytes = New-Object byte[] 48
    $jwtRng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $jwtRng.GetBytes($jwtBytes)
        $env:JWT_SECRET_KEY = [Convert]::ToBase64String($jwtBytes)
    } finally {
        $jwtRng.Dispose()
    }
    Write-Host "  🔐 로컬용 임시 JWT 키를 생성했습니다." -ForegroundColor DarkGray
}

Write-Host "  🐍 Python: $PyExe ($( & $PyExe --version 2>&1 ))" -ForegroundColor DarkGray
Write-Host "  📦 npm: $($npmCmd.Source)" -ForegroundColor DarkGray
Write-Host ""

Write-Host "[정리] __pycache__ 정리 중..." -ForegroundColor Yellow
Get-ChildItem -Path (Join-Path $Root "packages") -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    ForEach-Object { Remove-Item $_.FullName -Recurse -Force -ErrorAction SilentlyContinue }
Write-Host "         ✅ 완료" -ForegroundColor Green

function Install-PythonRequirements {
    param([string]$Name, [string]$RequirementsPath)
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
    Write-Host "         ✅ $Name" -ForegroundColor Green
}

function Upgrade-DbAdminSchema {
    Write-Host "[DB] DB Admin Alembic 마이그레이션 적용 중..." -ForegroundColor Yellow
    Push-Location $DbBackend
    & $PyExe -m alembic upgrade head
    $exitCode = $LASTEXITCODE
    Pop-Location
    if ($exitCode -ne 0) {
        Write-Host "❌ DB Admin 마이그레이션에 실패했습니다." -ForegroundColor Red
        exit 1
    }
    Write-Host "     ✅ DB Admin 스키마 최신 상태" -ForegroundColor Green
}

function Initialize-WebStorage {
    Write-Host "[DB] Web API 서버 소유 SQLite 초기화 중..." -ForegroundColor Yellow
    Push-Location $WebBackend
    & $PyExe -c "from services.runtime_storage import RuntimeStorage; from services.board_storage import get_board_engine; from core.fuel_store import FuelStore; s=RuntimeStorage(); s.init_db(); get_board_engine(); FuelStore(); s.close()"
    $exitCode = $LASTEXITCODE
    Pop-Location
    if ($exitCode -ne 0) {
        Write-Host "❌ accounts/interactions/board DB 초기화에 실패했습니다." -ForegroundColor Red
        exit 1
    }
    Write-Host "     ✅ accounts / interactions / board / OPINET 준비 완료" -ForegroundColor Green
}

# 공개 catalog는 관리자 승인 API를 호출할 때만 생성/교체합니다.
if (-not $env:WALLETSAVIOR_AUTO_SNAPSHOT_PUBLISHER) {
    $env:WALLETSAVIOR_AUTO_SNAPSHOT_PUBLISHER = "false"
}

function Ensure-PlaywrightChromium {
    Write-Host "[의존성] Playwright Chromium 설치/확인..." -ForegroundColor Yellow
    & $PyExe -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Host "❌ Playwright Chromium 설치에 실패했습니다." -ForegroundColor Red
        exit 1
    }
    Write-Host "         ✅ Playwright Chromium" -ForegroundColor Green
}

if ($Web) {
    Install-PythonRequirements "웹 API" (Join-Path $WebBackend "requirements.txt")
    Initialize-WebStorage
    if (-not $Admin) {
        Ensure-PlaywrightChromium
    }
}

if ($Admin) {
    Install-PythonRequirements "크롤러 관리자" (Join-Path $Root "packages\crawler-admin\requirements.txt")
    Install-PythonRequirements "DB 관리자" (Join-Path $DbBackend "requirements.txt")
    Upgrade-DbAdminSchema
    Ensure-PlaywrightChromium
}

$frontendDirs = @()
if ($Web) { $frontendDirs += $WebFrontend }
if ($Admin) { $frontendDirs += @($CrawlerFrontend, $DbFrontend) }

foreach ($dir in $frontendDirs) {
    $name = if ($dir -eq $WebFrontend) {
        "web-frontend"
    } else {
        (Split-Path (Split-Path $dir -Parent) -Leaf) + "/frontend"
    }
    Write-Host "[의존성] $name npm install/동기화..." -ForegroundColor Yellow
    Push-Location $dir
    $npmOutput = & npm.cmd install
    $npmExit = $LASTEXITCODE
    Pop-Location
    if ($npmExit -ne 0) {
        $npmOutput | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        Write-Host "❌ $name npm install에 실패했습니다." -ForegroundColor Red
        exit 1
    }
    Write-Host "         ✅ $name 설치" -ForegroundColor Green

    Write-Host "[검증] $name 프로덕션 빌드..." -ForegroundColor Yellow
    Push-Location $dir
    $buildOutput = & npm.cmd run build
    $buildExit = $LASTEXITCODE
    Pop-Location
    if ($buildExit -ne 0) {
        $buildOutput | ForEach-Object { Write-Host $_ -ForegroundColor Red }
        Write-Host "❌ $name 프론트엔드 빌드에 실패했습니다." -ForegroundColor Red
        exit 1
    }
    Write-Host "       ✅ $name 빌드" -ForegroundColor Green
}

Write-Host ""
Write-Host "[확인] 서버 포트 점유 상태 확인 중..." -ForegroundColor Yellow
$portsToClean = @()
if ($Web) { $portsToClean += @(8000, 5173) }
if ($Admin) { $portsToClean += @(8001, 5174, 8002, 5175) }

$occupied = @(
    Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $portsToClean -contains $_.LocalPort -and $_.OwningProcess -gt 4 -and $_.OwningProcess -ne $PID } |
        Sort-Object LocalPort, OwningProcess -Unique
)
if ($occupied.Count -gt 0 -and -not $ForcePorts) {
    Write-Host "❌ 필요한 포트가 이미 사용 중입니다. 기존 서비스를 직접 종료하거나 -ForcePorts를 명시하세요." -ForegroundColor Red
    foreach ($c in $occupied) {
        $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
        Write-Host "   - $($c.LocalPort): PID $($c.OwningProcess) $($proc.ProcessName)" -ForegroundColor Red
    }
    exit 1
}
if ($ForcePorts) {
    foreach ($targetPid in @($occupied.OwningProcess | Sort-Object -Unique)) {
        Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ParentProcessId -eq $targetPid } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $targetPid -Force -ErrorAction SilentlyContinue
    }
    if ($occupied.Count -gt 0) { Start-Sleep -Seconds 2 }
}
Write-Host "         ✅ 사용 가능" -ForegroundColor Green

$processes = @()

if ($Web) {
    Write-Host "🚀 [웹] Public API 시작 (8000)..." -ForegroundColor Yellow
    $processes += Start-Process -PassThru -WindowStyle Hidden -FilePath $PyExe `
        -ArgumentList "-m uvicorn main:app --port 8000 --host 127.0.0.1" `
        -WorkingDirectory $WebBackend

    Write-Host "🚀 [웹] 프론트엔드 시작 (5173)..." -ForegroundColor Yellow
    $processes += Start-Process -PassThru -WindowStyle Hidden -FilePath "npx.cmd" `
        -ArgumentList "vite --host 127.0.0.1 --port 5173 --strictPort" `
        -WorkingDirectory $WebFrontend
}

if ($Admin) {
    Write-Host "🚀 [크롤러] 백엔드 시작 (8001)..." -ForegroundColor Yellow
    $processes += Start-Process -PassThru -WindowStyle Hidden -FilePath $PyExe `
        -ArgumentList "-m uvicorn api.app:create_app --factory --port 8001 --host 127.0.0.1" `
        -WorkingDirectory $CrawlerBackend

    Write-Host "🚀 [크롤러] 프론트엔드 시작 (5174)..." -ForegroundColor Yellow
    $processes += Start-Process -PassThru -WindowStyle Hidden -FilePath "npx.cmd" `
        -ArgumentList "vite --host 127.0.0.1 --port 5174 --strictPort" `
        -WorkingDirectory $CrawlerFrontend

    Write-Host "🚀 [DB관리] 백엔드 시작 (8002)..." -ForegroundColor Yellow
    $processes += Start-Process -PassThru -WindowStyle Hidden -FilePath $PyExe `
        -ArgumentList "-m uvicorn api.app:create_app --factory --port 8002 --host 127.0.0.1" `
        -WorkingDirectory $DbBackend

    Write-Host "🚀 [DB관리] 프론트엔드 시작 (5175)..." -ForegroundColor Yellow
    $processes += Start-Process -PassThru -WindowStyle Hidden -FilePath "npx.cmd" `
        -ArgumentList "vite --host 127.0.0.1 --port 5175 --strictPort" `
        -WorkingDirectory $DbFrontend
}

Write-Host ""
Write-Host "⏳ 백엔드 준비 확인 중..." -ForegroundColor Yellow
$checks = @()
if ($Web) { $checks += @{ Name = "웹 API"; Url = "http://127.0.0.1:8000/openapi.json"; Ready = $false } }
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

$failedChecks = @($checks | Where-Object { -not $_.Ready })
if ($failedChecks.Count -gt 0) {
    Write-Host "❌ 일부 백엔드가 준비되지 못했습니다." -ForegroundColor Red
    foreach ($failed in $failedChecks) {
        Write-Host "   - $($failed.Name): $($failed.Url)" -ForegroundColor Red
    }
    foreach ($p in $processes) {
        if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    }
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  ✅ 시스템이 시작되었습니다" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
if ($Web) {
    Write-Host "  🌐 Web: http://localhost:5173  (API 8000)" -ForegroundColor White
}
if ($Admin) {
    Write-Host "  🕷️ Crawler Admin: http://localhost:5174  (API 8001)" -ForegroundColor White
    Write-Host "  🗄️ DB Admin:      http://localhost:5175  (API 8002)" -ForegroundColor White
}
Write-Host "  Ctrl+C로 종료합니다." -ForegroundColor DarkGray
Write-Host ""

if ($Web) { Start-Process "http://localhost:5173" }

try {
    while ($true) {
        $running = @($processes | Where-Object { $_ -and -not $_.HasExited })
        if ($running.Count -eq 0) { break }
        Start-Sleep -Seconds 2
    }
} finally {
    Write-Host "🛑 서버 종료 중..." -ForegroundColor Yellow
    foreach ($p in $processes) {
        if ($p -and -not $p.HasExited) {
            Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
                Where-Object { $_.ParentProcessId -eq $p.Id } |
                ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
            Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "✅ 종료 완료" -ForegroundColor Green
}
