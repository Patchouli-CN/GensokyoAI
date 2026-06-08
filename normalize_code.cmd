@echo off
chcp 65001 >nul
echo === ruff format ===
uv run ruff format .
if %errorlevel% neq 0 exit /b %errorlevel%

echo.
echo === ruff check --fix ===
uv run ruff check --fix .
if %errorlevel% neq 0 exit /b %errorlevel%

echo.
echo === pyright ===
uv run pyright
if %errorlevel% neq 0 exit /b %errorlevel%

echo.
echo === pytest ===
uv run pytest -q
if %errorlevel% neq 0 exit /b %errorlevel%

echo.
echo Done.
pause
