@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Keyrah - Amazon Vine Login
pushd "%~dp0.."
echo ========================================================
echo  Launching Amazon Vine Login for Keyrah...
echo ========================================================
"C:\Users\DigitalArthas\anaconda3\python.exe" "scripts\vine_watcher.py" login
if errorlevel 1 (
    echo.
    echo [ERROR] Script encountered an issue.
)
echo.
echo Press any key to exit...
pause >nul
popd
