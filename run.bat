@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ===================================================
echo   SENTINEL-2 MONITOR
echo ===================================================
rem Kho anh chung cua ca he thong: anh tai ve tu vao %KHO_ANH%\<Ten_muc_tieu>\
set KHO_ANH=D:\KHO_ANH\TD
set PORT=8765
set PY=
where python >nul 2>nul && set PY=python
if not defined PY where py >nul 2>nul && set PY=py -3
if defined PY (
  echo Kho anh chung: %KHO_ANH%
  echo Mo ung dung tai http://localhost:%PORT%/  -  dong cua so nay de tat.
  start "" /min cmd /c "timeout /t 2 >nul & start "" http://localhost:%PORT%/"
  %PY% server.py --kho "%KHO_ANH%" --port %PORT%
  pause
) else (
  echo Khong tim thay Python - mo truc tiep index.html (se KHONG tu luu vao kho %KHO_ANH%)
  start "" "%~dp0index.html"
  pause
)
