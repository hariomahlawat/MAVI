@echo off
setlocal
echo MAVI Development Environment Setup
echo ==================================

set "MAVI_BUNDLE_ROOT="
if exist "%~dp0MAVI-Offline-Binary-Kit\mavi-offline-binary-kit.json" (
  set "MAVI_BUNDLE_ROOT=%~dp0MAVI-Offline-Binary-Kit"
)
if exist "%~dp0..\MAVI-Offline-Binary-Kit\mavi-offline-binary-kit.json" (
  set "MAVI_BUNDLE_ROOT=%~dp0..\MAVI-Offline-Binary-Kit"
)

if not defined MAVI_BUNDLE_ROOT (
  echo.
  echo MAVI Offline Binary Kit was not found.
  echo Keep the extracted folder named MAVI-Offline-Binary-Kit beside this MAVI repository,
  echo then run Setup-MAVI-Development.cmd again.
  echo.
  echo Expected:
  echo   ^<workspace^>\MAVI\
  echo   ^<workspace^>\MAVI-Offline-Binary-Kit\
  pause
  exit /b 2
)

net session >nul 2>&1
if not %errorlevel%==0 (
  echo Requesting Administrator permission...
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup\Setup-MAVI.ps1" -Profile Development -BundleRoot "%MAVI_BUNDLE_ROOT%" -RepositoryRoot "%~dp0"
set "MAVI_SETUP_EXIT=%errorlevel%"

if not "%MAVI_SETUP_EXIT%"=="0" (
  echo.
  echo MAVI Development Setup FAILED.
  echo Review C:\ProgramData\MAVI\Development\setup\logs.
  pause
  exit /b %MAVI_SETUP_EXIT%
)

echo.
echo MAVI Development Setup completed successfully.
echo Restart Visual Studio once, then build or press F5.
pause
endlocal
