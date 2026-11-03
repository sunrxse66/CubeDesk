@echo off
cd /d "%~dp0"
python cube_player.py
if errorlevel 1 pause
