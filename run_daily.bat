@echo off
REM Job Hunt HQ - daily refresh. Point Windows Task Scheduler at this file (see README).
cd /d "%~dp0"
call .venv\Scripts\activate.bat
echo ==== %date% %time% ==== >> data\refresh.log
python -m jobhunt.refresh >> data\refresh.log 2>&1
