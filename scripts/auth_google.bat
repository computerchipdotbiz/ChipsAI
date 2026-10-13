@echo off
setlocal
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Keyrah - Google Account Authorization
pushd "%~dp0.."
echo ========================================================
echo  Keyrah - Google Account Authorization
echo ========================================================
"C:\Users\DigitalArthas\anaconda3\python.exe" "scripts\auth_google.py"
echo.
pause
popd
