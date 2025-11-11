@echo off
setlocal enableextensions

rem Navigate to project root (parent of this script folder)
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%.."

echo [AI PDF Reader] Using project root: %CD%

rem Ensure a virtual environment exists
if not exist ".venv\Scripts\python.exe" (
  echo [AI PDF Reader] Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo [AI PDF Reader] Failed to create virtual environment. Ensure Python is installed and on PATH.
    exit /b 1
  )
)

set "PY=%CD%\.venv\Scripts\python.exe"

rem Bootstrap environment file if missing
if not exist ".env" (
  if exist ".env.example" (
    echo [AI PDF Reader] Creating .env from .env.example (edit it to add your API key)...
    copy /Y ".env.example" ".env" >nul
  ) else (
    echo [AI PDF Reader] No .env or .env.example found. You can create .env to set CEREBRAS_API_KEY.
  )
)

rem Install/Update dependencies
echo [AI PDF Reader] Installing dependencies...
"%PY%" -m pip install --upgrade pip >nul
"%PY%" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [AI PDF Reader] Dependency install failed.
  exit /b 1
)

rem Fetch vendor assets (PDF.js) locally for offline/consistent usage
echo [AI PDF Reader] Preparing PDF.js vendor assets...
"%PY%" scripts\fetch_pdfjs.py

rem Start the Flask app
set FLASK_DEBUG=1
echo [AI PDF Reader] Starting server on http://localhost:5000/
"%PY%" -m backend.app

endlocal
