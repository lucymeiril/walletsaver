@echo off
REM 지갑 지키미 — 전체 시스템 한 번에 시작 (cmd 사용자용)
REM 웹사이트 + 크롤러 관리 + DB 관리 전부 기동
powershell -ExecutionPolicy Bypass -File "%~dp0start-all.ps1" %*
