@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run scripts\Setup.ps1 before starting the application.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\launch.py
