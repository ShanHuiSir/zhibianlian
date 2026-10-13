@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
echo 请打开 http://127.0.0.1:8765，停止请按 Ctrl+C。
.venv\Scripts\python app.py
