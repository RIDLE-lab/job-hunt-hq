@echo off
REM Job Hunt HQ - double-click to start. First run sets everything up (takes a minute).
cd /d "%~dp0"
if not exist .venv (
  echo Setting up for the first time...
  py -3 -m venv .venv 2>nul || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install -q --disable-pip-version-check -r requirements.txt
if not exist config.yaml copy config.example.yaml config.yaml >nul
echo.
echo Job Hunt HQ is running at http://127.0.0.1:5055  (close this window to stop it)
python app.py
pause
