@echo off
rem Double-click: starts the whole assistant (camera window, Bangla voice), fully offline.
rem Modes: R read, F find, D describe, I identify. SPACE speak a command. S stop. Q quit.
rem First time only, with internet: tools\download_models.py fetches every model.
cd /d "%~dp0"
set HF_HUB_OFFLINE=1
set TRANSFORMERS_OFFLINE=1
set YOLO_OFFLINE=True
if not exist "..\.venv\Scripts\python.exe" (
    echo Run setup.bat --models first.
    exit /b 1
)
"..\.venv\Scripts\python.exe" -m va_lab.assistant %*
if errorlevel 1 pause
