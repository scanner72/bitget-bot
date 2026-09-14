@echo off
setlocal
cd /d "%~dp0"
echo ?? Starting Bitget S2 Divergent Agent Desk...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
endlocal
