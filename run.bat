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

if not exist ".venv\Scripts\python.exe" (
  echo First run: setting up... this happens once.
  %PY% -m venv .venv
  rem 1) try the bundled offline cache (works with no internet if the wheels match this Python)
  if exist "wheelhouse" (
    .venv\Scripts\python -m pip install --no-index --find-links wheelhouse -r requirements.txt
  )
  rem 2) if that did not provide the packages, fall back to pip's normal index
  .venv\Scripts\python -c "import streamlit" 2>nul || .venv\Scripts\python -m pip install -r requirements.txt
)

rem final guard: confirm install succeeded before launching
.venv\Scripts\python -c "import streamlit" 2>nul
if errorlevel 1 (
  echo Setup failed: could not install the required packages.
  echo If this machine has no internet, the bundled wheels must match its Python version.
  pause & exit /b 1
)

.venv\Scripts\python -m streamlit run app_ui.py
pause
