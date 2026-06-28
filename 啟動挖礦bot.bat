@echo off
cd /d "%~dp0"
REM Launch via pythonw (no console window); countdown + status HUD shown by the bot itself
start "" pythonw -m miningbot
