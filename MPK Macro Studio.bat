@echo off
cd /d "%~dp0"
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 "%~dp0main.py"
) else (
    py -3 "%~dp0main.py"
)
