@echo off
rem Written into the PoC install root by Install-MAVI-PoC (data root and URL filled in). Stops the Vision worker and the platform.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0overlay\tools\setup\Stop-MaviPoc.ps1" -DataRoot "__MAVI_POC_DATA_ROOT__" %*
