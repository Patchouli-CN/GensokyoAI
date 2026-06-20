@echo off
REM 启动 Streamlit 前端
REM 用法:run_streamlit.cmd
REM 前提:Runtime 已经在另一个终端启动(runtime_http.py)
chcp 65001 >nul
cd /d "%~dp0"

REM 优先用项目的 .venv(uv sync 后会生成)
if exist ".venv\Scripts\python.exe" (
    .venv\Scripts\python.exe -m streamlit run app.py
) else (
    python -m streamlit run app.py
)