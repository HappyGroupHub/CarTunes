@echo off
title [Setup]CarTunes Backend
echo Starting setup...

REM Check if uv is installed
where uv >nul 2>nul
if %errorlevel% equ 0 (
    echo Found uv! Using uv for setup...
    uv sync
    if errorlevel 1 (
        echo Failed to sync with uv
        pause
        exit /b 1
    )
    echo Setup completed successfully with uv!
) else (
    echo uv not found, falling back to traditional setup...
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
    echo Setup completed successfully with pip!
)

echo Press any key to exit...
pause >nul