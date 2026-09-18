@echo off
setlocal
echo MAVI Offline Binary Kit Preparation
echo ====================================
echo.

net session >nul 2>&1
if not %errorlevel%==0 (
  echo Requesting Administrator permission...
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Prepare-MAVI-Offline-Binary-Kit.ps1" -InstallMissingToolchain
set "MAVI_EXIT=%errorlevel%"

if not "%MAVI_EXIT%"=="0" (
  echo.
  echo FAILED. Read the error above. Do not use a partially created kit.
  pause
  exit /b %MAVI_EXIT%
)

echo.
echo MAVI Offline Binary Kit created and verified successfully.
pause
endlocal
