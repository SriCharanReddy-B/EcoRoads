@echo off
REM Multi-laptop: run on the laptop in the car. Uses "cloud_url" from ecoroads-edge\config.json
REM (set it to the address HOST.bat printed, e.g. http://192.168.43.20:9000).
cd /d %~dp0
set PY=%~dp0ecoroads-edge\venv\Scripts\python.exe
start "EcoRoads sync" /D "%~dp0ecoroads-edge\src" "%PY%" sync_worker.py
cd /d "%~dp0ecoroads-edge\src"
"%PY%" capture_detect.py --phone %*
echo.
echo Drive recorded in ecoroads-edge\sessions\. Leave the sync window open until "nothing to sync".
pause
