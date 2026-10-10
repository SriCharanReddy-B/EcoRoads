@echo off
REM Old vs new model on held-out shadow frames and on the potholes you marked in the review.
cd /d %~dp0ecoroads-edge
set PY=%~dp0ecoroads-edge\venv\Scripts\python.exe
"%PY%" training\compare_models.py --val %*
start "" explorer "%~dp0ecoroads-edge\runs\compare"
pause
