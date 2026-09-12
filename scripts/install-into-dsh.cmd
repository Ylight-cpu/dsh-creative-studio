@echo off
chcp 65001 >nul
echo ============================================
echo  dsh-creative-studio - install skills into DSH
echo ============================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-into-dsh.ps1" %*
echo.
pause
