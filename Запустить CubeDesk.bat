@echo off
cd /d "%~dp0"
python start_cubedesk.py
if errorlevel 1 pause
