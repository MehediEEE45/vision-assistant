@echo off
cd /d "%~dp0"
py -3.11 tools\setup_lab.py %*
if errorlevel 1 pause
