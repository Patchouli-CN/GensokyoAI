@echo off
REM 启动 GensokyoAI Runtime HTTP/WebSocket 后端
REM 用法:run_runtime.cmd
REM 监听 127.0.0.1:8765
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m GensokyoAI.backends.web_server --host 127.0.0.1 --port 8765
) else (
    python -m GensokyoAI.backends.web_server --host 127.0.0.1 --port 8765
)