@echo off
chcp 65001 >nul
echo ============================================================
echo  Remove the skills-root copy (junctions under DSH_HOME\skills)
echo  Run this AFTER the plugin is confirmed working, to avoid the
echo  same skill name coming from two places.
echo ============================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-into-dsh.ps1" -Uninstall
echo.
pause
