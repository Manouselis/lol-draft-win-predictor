@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" -u -m loldraft.cli collect --auto-train
pause
