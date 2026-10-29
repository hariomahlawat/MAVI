@echo off
rem Written into the PoC install root by Install-MAVI-PoC (data root and URL filled in). Runs the smoke test: Test-MAVI-PoC.cmd -ClipPath "D:\clips\demo.mp4"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0overlay\tools\setup\Test-MaviPocSmoke.ps1" -DataRoot "__MAVI_POC_DATA_ROOT__" %*
exit /b %errorlevel%
