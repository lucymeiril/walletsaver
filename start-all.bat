@echo off
setlocal
REM WalletSavior Round T — 전체 시스템 한 번에 시작 (cmd 사용자용)
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-all.ps1" %*
endlocal
