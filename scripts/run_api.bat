@echo off
cd /d "%~dp0.."
call .venv\Scripts\activate.bat
python -m uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
