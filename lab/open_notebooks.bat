@echo off
rem Double-click: opens the notebooks in Jupyter Lab in your browser.
rem First install notebook extras with setup.bat --notebooks.
cd /d "%~dp0notebooks"
"..\..\.venv\Scripts\python.exe" -m jupyterlab
pause
