@echo off
setlocal
cd /d "%~dp0"

rem --- find a Python 3 ---
set "PY="
py -3 --version >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY (
  echo Python 3 not found. Install Python 3 from python.org, then double-click again.
  pause & exit /b 1
)

rem --- create the local environment if missing ---
if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up... this happens once.
  %PY% -m venv .venv
)

rem --- ensure required packages are present (covers fresh AND outdated .venv) ---
.venv\Scripts\python -c "import streamlit, imageio_ffmpeg" 2>nul
if errorlevel 1 (
  echo Installing / updating packages...
  if exist "wheelhouse" (
    .venv\Scripts\python -m pip install --no-index --find-links wheelhouse -r requirements.txt
  )
  .venv\Scripts\python -c "import streamlit, imageio_ffmpeg" 2>nul || .venv\Scripts\python -m pip install -r requirements.txt
)

rem --- final guard ---
.venv\Scripts\python -c "import streamlit, imageio_ffmpeg" 2>nul
if errorlevel 1 (
  echo Setup failed: could not install the required packages.
  echo If this machine has no internet, run fetch_offline_cache.bat on a connected
  echo machine first, or use Python 3.13 so the bundled wheels match.
  pause & exit /b 1
)

.venv\Scripts\python -m streamlit run app_ui.py
pause
