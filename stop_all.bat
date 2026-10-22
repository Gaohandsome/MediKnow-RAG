@echo off
chcp 65001 >nul
title MediKnow-RAG - 停止全部服务
cd /d "%~dp0"

set "BACKEND_PORT=8001"
set "FRONTEND_PORT=5173"

echo 正在停止占用端口 %BACKEND_PORT% 与 %FRONTEND_PORT% 的进程 ...
echo.

for %%P in (%BACKEND_PORT% %FRONTEND_PORT%) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%%P " ^| findstr "LISTENING"') do (
        echo   结束进程 PID %%A（端口 %%P）
        taskkill /PID %%A /T /F >nul 2>&1
    )
)

echo.
echo 已停止。按任意键关闭窗口。
pause >nul
