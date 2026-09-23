@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Sentinel-2 Monitor
echo ===================================================
echo   SENTINEL-2 MONITOR
echo ===================================================
rem Kho anh chung: anh tai ve tu vao %KHO_ANH%\<Ten_muc_tieu>\
set "KHO_ANH=D:\KHO_ANH\TD"
set "PORT=8765"

set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY where py >nul 2>nul && set "PY=py -3"
if not defined PY goto NOPY

rem rasterio dung de cat TCI L1C JP2 goc theo khung, khong phai tai ca o
%PY% -c "import rasterio" >nul 2>nul
if not errorlevel 1 goto RUN
echo Dang cai thu vien rasterio lan dau, can Internet...
%PY% -m pip install --user rasterio
%PY% -c "import rasterio" >nul 2>nul
if not errorlevel 1 goto RUN
echo.
echo [CANH BAO] Chua cai duoc rasterio - van chay app, nhung KHONG cat duoc TCI L1C.
echo            Xem loi ben tren. Thu: %PY% -m pip install rasterio
echo.

:RUN
echo Kho anh chung : %KHO_ANH%
echo Mo ung dung   : http://localhost:%PORT%/
echo Dong cua so nay la tat ung dung.
start "" /min cmd /c "timeout /t 2 >nul & start "" http://localhost:%PORT%/"
%PY% server.py --kho "%KHO_ANH%" --port %PORT%
pause
goto :EOF

:NOPY
echo Khong tim thay Python 3. Cai Python tu https://www.python.org/downloads/
echo va tick "Add python.exe to PATH". Tam thoi mo truc tiep index.html,
echo khi do anh KHONG tu vao kho %KHO_ANH% va khong cat duoc TCI L1C.
start "" "%~dp0index.html"
pause
