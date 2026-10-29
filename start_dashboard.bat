@echo off
cd /d "%~dp0"
echo Starting the Review 3 dashboard. Use the URL printed below.
echo Keep this window open while using the dashboard. Press Ctrl+C to stop it.
python -u dashboard.py
if errorlevel 1 pause
