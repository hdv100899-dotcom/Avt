@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===================================================
echo   SENTINEL-2 MONITOR
echo ===================================================
set PORT=8765
where python >nul 2>nul
if %errorlevel%==0 (
  echo Dang chay may chu cuc bo tai http://localhost:%PORT%/index.html
  echo Dong cua so nay de tat ung dung.
  start "" /min cmd /c "timeout /t 2 >nul & start "" http://localhost:%PORT%/index.html"
  python -m http.server %PORT% --bind 127.0.0.1
) else (
  echo Khong tim thay Python - mo truc tiep file index.html
  start "" "%~dp0index.html"
)
