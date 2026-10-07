@echo off
REM One-time setup: one Python environment that runs edge + cloud + demo on this laptop.
cd /d %~dp0
if not exist ecoroads-edge\venv\Scripts\python.exe (
  echo Creating virtual environment...
  py -m venv ecoroads-edge\venv
  ecoroads-edge\venv\Scripts\python -m pip install --upgrade pip
  ecoroads-edge\venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
)
ecoroads-edge\venv\Scripts\python -m pip install -r ecoroads-edge\requirements.txt -r ecoroads-cloud\requirements.txt
ecoroads-edge\venv\Scripts\python tools\fetch_offline_assets.py
ecoroads-edge\venv\Scripts\python ecoroads-edge\check_env.py
pause
