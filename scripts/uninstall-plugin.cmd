@echo off
chcp 65001 >nul
echo ============================================================
echo  Uninstall plugin: dsh-creative-studio from DSH profile
echo  (removes it from profile bundles + node_modules)
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-as-plugin.ps1" -Uninstall
echo.
pause
