@echo off
echo ========================================
echo Installing Hyper-RAG Streamlit Dependencies
echo ========================================

echo.
echo Using Tsinghua mirror for faster download...
echo.

pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

if errorlevel 1 (
    echo.
    echo [!] Installation failed. Trying without mirror...
    pip install -r requirements.txt
)

echo.
echo ========================================
echo Installation completed!
echo ========================================
echo.
echo Run application with: streamlit run app.py
echo Or use: start.bat
pause
