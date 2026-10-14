@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" if exist "frontend\dist\index.html" (
  ".venv\Scripts\python.exe" scripts\launch.py --data-dir "%~dp0data" %*
  if errorlevel 1 goto :failed
  exit /b 0
)
call scripts\DownloadDesktop.cmd
if errorlevel 1 goto :failed
start "" /D "%~dp0" "%~dp0.desktop\LeagueDraftLab\LeagueDraftLab.exe" --data-dir "%~dp0data" %*
exit /b 0
:failed
echo.
echo League Draft Lab could not start. Read the message above and retry.
pause
exit /b 1
