@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Virtual environment missing. Run install_windows.ps1 first.
  pause
  exit /b 1
)

".venv\Scripts\python.exe" tray_app.py --model small --language fr

pause
