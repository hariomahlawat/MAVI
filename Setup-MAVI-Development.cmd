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

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup\Setup-MAVI.ps1" -Profile Development -BundleRoot "%~dp0" -RepositoryRoot "%~dp0"
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
