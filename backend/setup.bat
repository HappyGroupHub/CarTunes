@echo off
title [Setup] CarTunes Backend
echo Starting setup...

echo Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo Failed to create virtual environment
    pause
    exit /b 1
)

cd /d %~dp0
echo Activating virtual environment...
call .venv\Scripts\activate
if errorlevel 1 (
    echo Failed to activate virtual environment
    pause
    exit /b 1
)

echo Installing requirements...
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install requirements
    echo Press any key to exit...
    pause >nul
    exit /b 1
)