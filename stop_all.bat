@echo off
rem Stop backend / frontend by killing whatever listens on the two ports.
rem ASCII-only on purpose: cmd.exe mis-parses Chinese in UTF-8 batch files.
chcp 65001 >nul
title MediKnow-RAG - stop
cd /d "%~dp0"

set "BACKEND_PORT=8001"
set "FRONTEND_PORT=5173"

echo Stopping processes listening on %BACKEND_PORT% and %FRONTEND_PORT% ...
echo.

for %%P in (%BACKEND_PORT% %FRONTEND_PORT%) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr "LISTENING"') do (
        echo   killing PID %%A ^(port %%P^)
        taskkill /PID %%A /T /F >nul 2>&1
    )
)

echo.
echo Done. Press any key to close.
pause >nul
