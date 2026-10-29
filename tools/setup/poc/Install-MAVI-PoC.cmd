@echo off
setlocal
echo MAVI PoC installation (profile poc-single-host)
echo ===============================================
echo Proof of concept. Not Production-qualified. Evidence class: Development.
echo.

if not exist "%~dp0mavi-poc-bundle.json" (
  echo This folder is not a MAVI PoC setup bundle: mavi-poc-bundle.json is missing.
  pause
  exit /b 2
)

net session >nul 2>&1
if not %errorlevel%==0 (
  if not "%~1"=="" (
    echo Parameters were given. Run this launcher from an elevated Command Prompt.
    pause
    exit /b 5
  )
  echo Requesting Administrator permission...
  powershell.exe -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0overlay\tools\setup\Install-MAVI-PoC.ps1" -BundleRoot "%~dp0." %*
set "MAVI_INSTALL_EXIT=%errorlevel%"

if not "%MAVI_INSTALL_EXIT%"=="0" (
  echo.
  echo MAVI PoC installation FAILED. Review the logs folder under the PoC data root
  echo ^(default %ProgramData%\MAVI\PoC\logs^).
  pause
  exit /b %MAVI_INSTALL_EXIT%
)

echo.
echo MAVI PoC installation completed. Start it with Start-MAVI-PoC.cmd in the install folder.
pause
endlocal
