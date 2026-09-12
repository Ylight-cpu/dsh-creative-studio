@echo off
chcp 65001 >nul
echo ============================================
echo  dsh-creative-studio - install as DSH plugin
echo ============================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-as-plugin.ps1" %*
echo.
pause
