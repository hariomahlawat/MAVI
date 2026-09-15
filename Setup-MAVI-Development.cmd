@echo off
setlocal
echo MAVI Development Environment Setup
echo ==================================

net session >nul 2>&1
if not %errorlevel%==0 (
  echo Requesting Administrator permission...
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

set "MAVI_BUNDLE_ROOT=%~dp0"
if exist "%~dp0MAVI-Offline-Binary-Kit\mavi-offline-binary-kit.json" (
  set "MAVI_BUNDLE_ROOT=%~dp0MAVI-Offline-Binary-Kit"
)
if exist "%~dp0..\MAVI-Offline-Binary-Kit\mavi-offline-binary-kit.json" (
  set "MAVI_BUNDLE_ROOT=%~dp0..\MAVI-Offline-Binary-Kit"
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup\Setup-MAVI.ps1" -Profile Development -BundleRoot "%MAVI_BUNDLE_ROOT%" -RepositoryRoot "%~dp0"
set "MAVI_SETUP_EXIT=%errorlevel%"

if not "%MAVI_SETUP_EXIT%"=="0" (
  echo.
  echo MAVI Development Setup FAILED.
  echo Review C:\ProgramData\MAVI\Development\setup\logs.
  echo If this is a fresh disconnected PC, keep MAVI-Offline-Binary-Kit beside the repository.
  pause
  exit /b %MAVI_SETUP_EXIT%
)

echo.
echo MAVI Development Setup completed successfully.
echo Restart Visual Studio once, then build or press F5.
pause
endlocal
