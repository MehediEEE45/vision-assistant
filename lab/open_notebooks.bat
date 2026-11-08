@echo off
rem Double-click: opens the notebooks in Jupyter Lab in your browser.
rem Pick the kernel "Vision AI Lab (py3.11, CUDA)" if it asks.
cd /d "%~dp0notebooks"
"%USERPROFILE%\.venvs\vision-ai-lab\Scripts\jupyter.exe" lab
pause
