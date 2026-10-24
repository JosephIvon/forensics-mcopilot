@echo off
REM mcopilot 命令行入口（Windows）
REM 用法: mcopilot <命令> [参数]   例: mcopilot requirements report
setlocal
set "MCOPILOT_DIR=%~dp0"
set "PYTHONIOENCODING=utf-8"
if defined MCOPILOT_PYTHON (
    set "PY=%MCOPILOT_PYTHON%"
) else (
    set "PY=python"
)
"%PY%" -c "import sys" >nul 2>&1
if errorlevel 1 (
    echo [mcopilot] 找不到 Python，请安装 Python 3.9+ 或设置 MCOPILOT_PYTHON 环境变量
    exit /b 1
)
set "PYTHONPATH=%MCOPILOT_DIR%src;%PYTHONPATH%"
"%PY%" -m mcopilot %*
