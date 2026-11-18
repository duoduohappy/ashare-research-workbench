@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo 请先安装 Python 3.10 或以上版本，并勾选 Add Python to PATH。
  pause
  exit /b 1
)
python -c "import requests, numpy, sklearn, akshare" >nul 2>nul
if errorlevel 1 (
  python -m pip install -r requirements.txt
  if errorlevel 1 (
    echo 依赖安装失败，请检查网络后重新运行。
    pause
    exit /b 1
  )
)
start "" http://127.0.0.1:8876
python server.py
pause
