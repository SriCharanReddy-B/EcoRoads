@echo off
REM Real-world drive: phone on the windscreen -> this laptop.
REM Opens cloud, dashboard and sync worker in their own windows, then the detector here.
cd /d %~dp0
set PY=%~dp0ecoroads-edge\venv\Scripts\python.exe
start "EcoRoads cloud" /D "%~dp0ecoroads-cloud\app" "%PY%" -m uvicorn main:app --host 0.0.0.0 --port 9000
start "EcoRoads dashboard" /D "%~dp0ecoroads-dashboard" "%PY%" -m http.server 8080
start "EcoRoads sync" /D "%~dp0ecoroads-edge\src" "%PY%" sync_worker.py
timeout /t 3 >nul
start "" "http://localhost:8080/index.html"
cd /d "%~dp0ecoroads-edge\src"
"%PY%" capture_detect.py --phone %*
echo.
echo Drive finished and recorded in ecoroads-edge\sessions\. Close the other windows when done.
pause
