@echo off
cd /d "%~dp0"
echo ========================================
echo Starting Hyper-RAG Hypergraph Visualizer
echo ========================================

python -m streamlit run app.py

pause
