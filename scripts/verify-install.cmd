@echo off
chcp 65001 >nul
echo ============================================================
echo  Verify dsh-creative-studio install (plugin + toolkit)
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0verify-install.ps1" %*
echo.
pause
