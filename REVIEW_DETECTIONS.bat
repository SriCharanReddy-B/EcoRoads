@echo off
REM Review the frames where the model detected something, one by one.
REM   D = real pothole (removed)   K / Space = shadow (kept for training)   A = back   Q = quit
cd /d %~dp0ecoroads-edge
set PY=%~dp0ecoroads-edge\venv\Scripts\python.exe
if not exist hard_negatives (
  echo Finding the frames where the model fired on your recorded drives...
  "%PY%" training\hard_negatives.py collect --session all || (pause & exit /b 1)
)
"%PY%" training\review_detections.py
pause
