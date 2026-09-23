@echo off
cd /d "%~dp0"
echo ===================================================
echo   KHOI DONG HE THONG KIEM TRA ANH VE TINH SENTINEL-2
echo ===================================================
echo Dang bat ung dung web tai http://localhost:8501...
python -m streamlit run app.py
pause
