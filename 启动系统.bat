@echo off
chcp 65001 >nul
title 集成生产计划与调度系统
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10 以上版本，
    echo        安装时务必勾选 "Add Python to PATH"。
    echo        下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

python -c "import streamlit, plotly, pandas, ortools, openpyxl, numpy" >nul 2>nul
if errorlevel 1 (
    echo [首次运行] 正在安装依赖（约 2~5 分钟，仅需一次）...
    python -m pip install -r requirements.txt -r app\requirements-app.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请检查网络后重新双击本文件。
        pause
        exit /b 1
    )
)

echo.
echo  正在启动系统，浏览器将自动打开 http://localhost:8501
echo  使用完毕后关闭本窗口（或按 Ctrl+C）即可停止系统。
echo.
python -m streamlit run app\webapp.py --server.port 8501
pause
