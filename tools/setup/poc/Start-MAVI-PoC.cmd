@echo off
setlocal
rem Written into the PoC install root by Install-MAVI-PoC (data root and URL filled in). Starts the platform and the Vision worker.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0overlay\tools\setup\Start-MaviPoc.ps1" -DataRoot "__MAVI_POC_DATA_ROOT__" %*
set "MAVI_EXIT=%errorlevel%"
if not "%MAVI_EXIT%"=="0" (
  echo MAVI PoC did not start. Review the logs folder under the PoC data root.
  pause
  exit /b %MAVI_EXIT%
)
start "" "__MAVI_POC_URL__/"
endlocal
