@echo off
setlocal
echo MAVI Development Environment Setup
echo ==================================
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p=Start-Process powershell.exe -Verb RunAs -Wait -PassThru -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File ""%~dp0tools\setup\Setup-MAVI.ps1"" -Profile Development -BundleRoot ""%~dp0"" -RepositoryRoot ""%~dp0""'; exit $p.ExitCode"
if errorlevel 1 (
  echo.
  echo MAVI Development Setup FAILED.
  echo Review C:\ProgramData\MAVI\Development\setup\logs.
  pause
  exit /b 1
)
echo.
echo MAVI Development Setup completed successfully.
echo Restart Visual Studio once, then build or press F5.
pause
endlocal
