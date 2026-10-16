@echo off
REM One-click startup: checks Ollama + backend + frontend, opens browser
cd /d "%~dp0"
echo === Study Assistant (local) starting... ===

where ollama >nul 2>&1
if errorlevel 1 (
  echo [WARN] Ollama not found. Install from https://ollama.com/download
  echo The app will show a setup screen until Ollama + models are ready.
) else (
  echo [OK] Ollama found. Ensuring server is running...
  start /min "" ollama serve 2>nul
)

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python launcher 'py' not found. Install Python 3.11+ from python.org.
  pause
  exit /b 1
)

if not exist "frontend\dist\index.html" (
  echo [INFO] Frontend not built yet - the dev server will be used if available.
)

echo Starting backend on http://127.0.0.1:8000 ...
start "StudyAssistant-Backend" /min py -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000

timeout /t 5 /nobreak >nul

REM Prefer built frontend served by backend; fall back to vite dev server
if exist "frontend\dist\index.html" (
  echo Opening http://127.0.0.1:8000 ...
  start "" http://127.0.0.1:8000
) else (
  echo Starting Vite dev server...
  start "StudyAssistant-Frontend" /min cmd /c "cd frontend && npm run dev"
  timeout /t 5 /nobreak >nul
  start "" http://127.0.0.1:5173
)

echo.
echo Backend: http://127.0.0.1:8000  ^| API docs: http://127.0.0.1:8000/docs
echo Frontend dev (if used): http://127.0.0.1:5173
echo Close the Backend window to stop. Your data stays in data\.
pause
