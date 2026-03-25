#!/bin/bash

echo "======================================"
echo "Hyper-RAG Hypergraph Visualizer"
echo "Gradio Version with AntV Graphin"
echo "======================================"
echo ""

# Install dependencies (use Tsinghua mirror for faster download in China)
echo "Installing dependencies..."
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# Run the app
echo ""
echo "Starting Gradio app..."
echo ""
python app.py
