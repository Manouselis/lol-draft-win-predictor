@echo off
setlocal
cd /d "%~dp0.."
set "TASK_DESKTOP_SHA=9b202003d44f46276cabaaa3ebccc6dac667b2d3bc74af9576d61f6008a3b3b8"
set "TASK_DESKTOP_URL=https://github.com/Manouselis/lol-draft-win-predictor/releases/download/v0.2.1/LeagueDraftLab-windows-x64-v0.2.1.zip"
if exist ".desktop\LeagueDraftLab\LeagueDraftLab.exe" if exist ".desktop\verified-v0.2.1.txt" (
  findstr /x /c:"%TASK_DESKTOP_SHA%" ".desktop\verified-v0.2.1.txt" >nul
  if not errorlevel 1 exit /b 0
)
where curl.exe >nul 2>nul
if errorlevel 1 goto :missing
where tar.exe >nul 2>nul
if errorlevel 1 goto :missing
where certutil.exe >nul 2>nul
if errorlevel 1 goto :missing
if not exist ".desktop" mkdir ".desktop"
echo Preparing League Draft Lab. This first download includes Python and the app.
curl.exe --fail --location --proto "=https" --proto-redir "=https" --retry 2 --output ".desktop\desktop-download.zip" "%TASK_DESKTOP_URL%"
if errorlevel 1 exit /b 1
certutil.exe -hashfile ".desktop\desktop-download.zip" SHA256 > ".desktop\download-hash.txt"
if errorlevel 1 exit /b 1
findstr /i /x /c:"%TASK_DESKTOP_SHA%" ".desktop\download-hash.txt" >nul
if errorlevel 1 (
  echo Download verification failed. The application will not be executed.
  exit /b 1
)
tar.exe -xf ".desktop\desktop-download.zip" -C ".desktop"
if errorlevel 1 exit /b 1
if not exist ".desktop\LeagueDraftLab\LeagueDraftLab.exe" exit /b 1
> ".desktop\verified-v0.2.1.txt" echo %TASK_DESKTOP_SHA%
exit /b 0
:missing
echo This Windows installation is missing a required built-in download tool.
echo Download and extract the Windows ZIP from:
echo https://github.com/Manouselis/lol-draft-win-predictor/releases
exit /b 1
