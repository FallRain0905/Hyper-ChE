@echo off
echo ======================================
echo Hyper-RAG Hypergraph Visualizer
echo Gradio Version with AntV Graphin
echo ======================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found. Please install Python 3.8+
    pause
    exit /b 1
)

REM Install dependencies (use Tsinghua mirror for faster download in China)
echo Installing dependencies...
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

REM Run the app
echo.
echo Starting Gradio app...
echo.
python app.py
