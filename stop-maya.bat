@echo off
setlocal
cd /d "%~dp0" || exit /b 1
if /i "%~1"=="--dry-run" (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\stop_maya.ps1" -DryRun
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\stop_maya.ps1"
)
set "MAYA_STOP_EXIT=%ERRORLEVEL%"
if not "%MAYA_STOP_EXIT%"=="0" pause
exit /b %MAYA_STOP_EXIT%
