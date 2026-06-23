@echo off
setlocal
cd /d "%~dp0"
echo This removes the local environment (.venv) so the next run reinstalls fresh.
echo.
choice /m "Remove the local environment now"
if errorlevel 2 exit /b 0
rmdir /s /q ".venv" 2>nul
rmdir /s /q "__pycache__" 2>nul
rmdir /s /q "tests\__pycache__" 2>nul
echo Done. Double-click run.bat to set up again.
pause
