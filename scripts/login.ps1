# Sarahzine 800 - Amazon Vine Login Script
$Host.UI.RawUI.WindowTitle = "Sarahzine 800 - Amazon Vine Login"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BaseDir = Split-Path -Parent $ScriptDir
Set-Location $BaseDir

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host " Launching Amazon Vine Login for Sarahzine 800...       " -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

& "C:\Users\DigitalArthas\anaconda3\python.exe" "scripts\vine_watcher.py" login

Write-Host "`nAll done! Press any key to exit..." -ForegroundColor Green
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
