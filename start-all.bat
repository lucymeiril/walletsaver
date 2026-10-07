@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

rem Teacher/team double-click uses the shipped demo in its separate data directory.
rem Explicit arguments are forwarded unchanged; developer mode is direct start-all.ps1.
if "%~1"=="" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1" -TeamDemo
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1" %*
)
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo ============================================
    echo start-all.ps1 failed. Exit code: %EXIT_CODE%
    echo ============================================
    pause
)

endlocal & exit /b %EXIT_CODE%
