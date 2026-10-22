@echo off
rem ---------------------------------------------------------------
rem MediKnow-RAG - one-click start (Windows)
rem   backend  : http://127.0.0.1:8001
rem   frontend : http://127.0.0.1:5173
rem Keep this file ASCII-only: cmd.exe mis-parses UTF-8 batch files
rem (a Chinese word can be treated as a command). Chinese docs live
rem in README.md.
rem ---------------------------------------------------------------
chcp 65001 >nul
title MediKnow-RAG - start
cd /d "%~dp0"

set "BACKEND_PORT=8001"
set "FRONTEND_PORT=5173"
set "ROOT=%CD%"
set "PY=%ROOT%\.venv\Scripts\python.exe"

echo ==========================================================
echo   MediKnow-RAG  -  Hospital Knowledge Base QA
echo   backend    http://127.0.0.1:%BACKEND_PORT%
echo   frontend   http://127.0.0.1:%FRONTEND_PORT%
echo   API docs   http://127.0.0.1:%BACKEND_PORT%/docs
echo ==========================================================
echo.

if not exist "%PY%" goto no_venv
if not exist "%ROOT%\frontend\package.json" goto no_frontend
if not exist "%ROOT%\.env" (
    echo [INFO] .env not found, copying .env.example ...
    copy /y "%ROOT%\.env.example" "%ROOT%\.env" >nul
    echo        Fill in MySQL password, model paths and LLM api key, then run again.
    pause
    exit /b 1
)

rem ---------- locate npm.cmd (PATH may expose only "npm") ----------
set "NPM_CMD="
for /f "delims=" %%P in ('where npm.cmd 2^>nul') do if not defined NPM_CMD set "NPM_CMD=%%P"
if not defined NPM_CMD (
    for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\node\versions\*") do (
        if not defined NPM_CMD if exist "%%D\npm.cmd" set "NPM_CMD=%%D\npm.cmd"
    )
)
if not defined NPM_CMD goto no_node
echo npm: %NPM_CMD%
echo.

rem ---------- port check ----------
call :check_port %BACKEND_PORT% BUSY_BACK
call :check_port %FRONTEND_PORT% BUSY_FRONT

if "%BUSY_BACK%"=="1" (
    echo [1/4] port %BACKEND_PORT% already in use, reuse running backend.
) else (
    echo [1/4] starting backend ...
    start "MediKnow-backend %BACKEND_PORT%" /D "%ROOT%\backend" cmd /k ""%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"
)

if not exist "%ROOT%\frontend\node_modules" (
    echo [2/4] installing frontend dependencies ^(network required^) ...
    pushd "%ROOT%\frontend"
    call "%NPM_CMD%" install
    popd
) else (
    echo [2/4] frontend dependencies ready.
)

if "%BUSY_FRONT%"=="1" (
    echo [3/4] port %FRONTEND_PORT% already in use, reuse running frontend.
) else (
    echo [3/4] starting frontend ...
    start "MediKnow-frontend %FRONTEND_PORT%" /D "%ROOT%\frontend" cmd /k ""%NPM_CMD%" run dev -- --port %FRONTEND_PORT%"
)

echo [4/4] waiting for services ^(max 60s^) ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=@(%BACKEND_PORT%,%FRONTEND_PORT%); foreach($p in $ports){ $ok=$false; for($i=0;$i -lt 120;$i++){ try{ $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',$p); $ok=$true; $c.Close() }catch{}; if($ok){break}; Start-Sleep -Milliseconds 500 } }"

call :check_port %BACKEND_PORT% UP_BACK
call :check_port %FRONTEND_PORT% UP_FRONT
echo.
if "%UP_BACK%"=="1" (echo   backend  : ready) else (echo   backend  : FAILED, check the "MediKnow-backend" window)
if "%UP_FRONT%"=="1" (echo   frontend : ready) else (echo   frontend : FAILED, check the "MediKnow-frontend" window)

if "%UP_FRONT%"=="1" (
    echo.
    echo opening browser ...
    start "" "http://127.0.0.1:%FRONTEND_PORT%"
) else (
    echo.
    echo frontend not ready, open http://127.0.0.1:%FRONTEND_PORT% later.
)

echo.
echo tips:
echo   - closing the backend/frontend windows stops the services
echo   - first launch loads bge-m3 and bge-reranker, takes 20-60s
echo   - run stop_all.bat to stop everything
echo.
pause
exit /b 0

rem ---------- is port in use ----------
:check_port
set "%~2=0"
for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%1 " ^| findstr "LISTENING"') do set "%~2=1"
exit /b 0

:no_venv
echo [ERROR] virtualenv not found: %PY%
echo   python -m venv .venv
echo   .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
echo.
pause
exit /b 1

:no_frontend
echo [ERROR] frontend\package.json not found, run this script from the repo root.
pause
exit /b 1

:no_node
echo [ERROR] npm.cmd not found, install Node.js 18+ and add it to PATH.
pause
exit /b 1
