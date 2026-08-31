@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo ============================================
    echo start-all.ps1 failed. Exit code: %EXIT_CODE%
    echo ============================================
    pause
)

endlocal & exit /b %EXIT_CODE%
