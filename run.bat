@echo off
setlocal
cd /d %~dp0
call .\.venv\Scripts\activate
cd app
python -m uvicorn app.main:app --reload --port 8002 --reload-exclude "..\.venv"
endlocal
