@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\setup\Start-MaviVisionWorker.ps1" -RepositoryRoot "%~dp0."
set "EXITCODE=%ERRORLEVEL%"
if not "%EXITCODE%"=="0" (
    echo.
    echo MAVI Vision Worker stopped with exit code %EXITCODE%.
    pause
)
exit /b %EXITCODE%
