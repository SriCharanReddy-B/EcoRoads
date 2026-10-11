@echo off
REM Real-world drive: phone on the windscreen -> this laptop.
REM Reads cloud_url from ecoroads-edge\config.json:
REM   - a deployed server (e.g. https://ecoroads.onrender.com): no local cloud is started,
REM     the sync worker uploads there. No browser is opened.
REM   - http://localhost:9000 (offline / classroom): starts the local cloud + dashboard too
cd /d %~dp0
set PY=%~dp0ecoroads-edge\venv\Scripts\python.exe
set CLOUD=
for /f "usebackq delims=" %%u in (`call "%PY%" -c "import json;print(json.load(open(r'ecoroads-edge\config.json')).get('cloud_url','http://localhost:9000').rstrip('/'))" 2^>nul`) do set CLOUD=%%u
if "%CLOUD%"=="" set CLOUD=http://localhost:9000
echo Cloud server: %CLOUD%

echo %CLOUD% | findstr /i "localhost 127.0.0.1" >nul
if errorlevel 1 (
  echo Potholes will be uploaded to %CLOUD% - open it in a browser whenever you want to see them.
) else (
  start "EcoRoads cloud" /D "%~dp0ecoroads-cloud\app" "%PY%" -m uvicorn main:app --host 0.0.0.0 --port 9000
  start "EcoRoads dashboard" /D "%~dp0ecoroads-dashboard" "%PY%" -m http.server 8080
  echo Local dashboard: http://localhost:8080/index.html
)
start "EcoRoads sync (leave open)" /D "%~dp0ecoroads-edge\src" "%PY%" sync_worker.py
cd /d "%~dp0ecoroads-edge\src"
"%PY%" capture_detect.py --phone %*
echo.
echo Drive finished and recorded in ecoroads-edge\sessions\.
echo Leave the sync window open until it says "nothing to sync", then see the results at %CLOUD%
pause
