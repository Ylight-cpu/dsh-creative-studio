@echo off
chcp 65001 >nul
echo ============================================
echo  dsh-creative-studio - bootstrap runtime
echo ============================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1" %*
echo.
pause
