@echo off
cd /d "%~dp0"
if not exist .venv (
    echo First run: setting up, this takes a minute...
    python -m venv .venv
    .venv\Scripts\python -m pip install -q -r requirements.txt
)
if not exist .env (
    copy .env.example .env >nul
    echo.
    echo A ".env" file was created. Open it, paste your DeepSeek API key, save, then run this again.
    notepad .env
    exit /b
)
start "" http://localhost:8000
.venv\Scripts\python -m uvicorn app.main:app --port 8000
