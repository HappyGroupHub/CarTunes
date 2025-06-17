@echo off
title CarTunes Backend

cd /d %~dp0
call .venv\Scripts\activate
python main.py
pause