@echo off
cd /d "%~dp0"
".venv\Scripts\python.exe" app.py --watch --autostart --source serial://COM15
if errorlevel 1 pause
