@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting Unified 2-Way Bale Chatbot + 30-Minute Signal Hub...
"C:\Users\lenovo\AppData\Local\Python\pythoncore-3.14-64\python.exe" cloud_hub\server.py
pause
