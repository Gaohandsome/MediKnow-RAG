@echo off
chcp 65001 >nul
title MediKnow-RAG - 一键启动
cd /d "%~dp0"

set "BACKEND_PORT=8001"
set "FRONTEND_PORT=5173"
set "ROOT=%CD%"
set "PY=%ROOT%\.venv\Scripts\python.exe"

echo ==========================================================
echo   MediKnow-RAG  院内知识库智能问答系统
echo   后端     http://127.0.0.1:%BACKEND_PORT%
echo   前端     http://127.0.0.1:%FRONTEND_PORT%
echo   接口文档 http://127.0.0.1:%BACKEND_PORT%/docs
echo ==========================================================
echo.

if not exist "%PY%" goto no_venv
if not exist "%ROOT%\frontend\package.json" goto no_frontend
if not exist "%ROOT%\.env" (
    echo [提示] 未找到 .env，已从 .env.example 复制一份，请先填写数据库与模型路径。
    copy /y "%ROOT%\.env.example" "%ROOT%\.env" >nul
    echo         编辑好 .env 后重新运行本脚本。
    pause
    exit /b 1
)

rem ---------- 定位 npm.cmd（PATH 里可能只有 npm 而无 npm.cmd）----------
set "NPM_CMD="
for /f "delims=" %%P in ('where npm.cmd 2^>nul') do if not defined NPM_CMD set "NPM_CMD=%%P"
if not defined NPM_CMD (
    for /d %%D in ("%USERPROFILE%\.workbuddy\binaries\node\versions\*") do (
        if not defined NPM_CMD if exist "%%D\npm.cmd" set "NPM_CMD=%%D\npm.cmd"
    )
)
if not defined NPM_CMD goto no_node
echo 使用 npm：%NPM_CMD%
echo.

rem ---------- 端口占用检查 ----------
call :check_port %BACKEND_PORT% BUSY_BACK
call :check_port %FRONTEND_PORT% BUSY_FRONT

if "%BUSY_BACK%"=="1" (
    echo [1/4] 端口 %BACKEND_PORT% 已被占用，复用正在运行的后端进程。
) else (
    echo [1/4] 启动后端服务 ...
    start "MediKnow-后端 %BACKEND_PORT%" /D "%ROOT%\backend" cmd /k ""%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"
)

if not exist "%ROOT%\frontend\node_modules" (
    echo [2/4] 首次运行，安装前端依赖（需要联网）...
    pushd "%ROOT%\frontend"
    call "%NPM_CMD%" install
    popd
) else (
    echo [2/4] 前端依赖已就绪。
)

if "%BUSY_FRONT%"=="1" (
    echo [3/4] 端口 %FRONTEND_PORT% 已被占用，复用正在运行的前端进程。
) else (
    echo [3/4] 启动前端服务 ...
    start "MediKnow-前端 %FRONTEND_PORT%" /D "%ROOT%\frontend" cmd /k ""%NPM_CMD%" run dev -- --port %FRONTEND_PORT%"
)

echo [4/4] 等待服务就绪（最多 60 秒）...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ports=@(%BACKEND_PORT%,%FRONTEND_PORT%); foreach($p in $ports){ $ok=$false; for($i=0;$i -lt 120;$i++){ try{ $c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',$p); $ok=$true; $c.Close() }catch{}; if($ok){break}; Start-Sleep -Milliseconds 500 } }"

call :check_port %BACKEND_PORT% UP_BACK
call :check_port %FRONTEND_PORT% UP_FRONT
echo.
if "%UP_BACK%"=="1" (echo   后端：已就绪) else (echo   后端：未启动，请查看「MediKnow-后端」窗口的报错)
if "%UP_FRONT%"=="1" (echo   前端：已就绪) else (echo   前端：未启动，请查看「MediKnow-前端」窗口的报错)

if "%UP_FRONT%"=="1" (
    echo.
    echo 正在打开浏览器 ...
    start "" "http://127.0.0.1:%FRONTEND_PORT%"
) else (
    echo.
    echo 前端未启动，可稍后手动访问 http://127.0.0.1:%FRONTEND_PORT%
)

echo.
echo 提示：
echo   - 后端窗口标题：MediKnow-后端 %BACKEND_PORT%   （关闭即停止后端）
echo   - 前端窗口标题：MediKnow-前端 %FRONTEND_PORT%   （关闭即停止前端）
echo   - 首次启动会加载 bge-m3 与 bge-reranker，约 20~60 秒
echo   - 需要全部停止时双击 stop_all.bat
echo.
pause
exit /b 0

rem ---------- 子过程：端口是否被占用 ----------
:check_port
set "%~2=0"
for /f "tokens=5" %%A in ('netstat -ano ^| findstr ":%1 " ^| findstr "LISTENING"') do set "%~2=1"
exit /b 0

:no_venv
echo [错误] 未找到虚拟环境：%PY%
echo 请在项目根目录执行：
echo     python -m venv .venv
echo     .venv\Scripts\python.exe -m pip install -r backend\requirements.txt
echo.
pause
exit /b 1

:no_frontend
echo [错误] 未找到 frontend\package.json，请确认脚本位于项目根目录。
pause
exit /b 1

:no_node
echo [错误] 未找到 npm.cmd，请安装 Node.js 18+ 并加入 PATH。
pause
exit /b 1
