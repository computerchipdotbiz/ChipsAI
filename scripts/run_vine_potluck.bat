@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0\.."
if not exist "data" mkdir "data"
echo ============================================================ >> "data\vine_watcher.log"
echo [START] Vine Potluck check at %date% %time% >> "data\vine_watcher.log"
"C:\Users\DigitalArthas\anaconda3\python.exe" "scripts\vine_watcher.py" >> "data\vine_watcher.log" 2>&1
echo [FINISH] Exit code: %errorlevel% at %date% %time% >> "data\vine_watcher.log"
endlocal
