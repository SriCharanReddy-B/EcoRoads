@echo off
REM Pictures of every pothole the detector logged (and skipped) on a recorded drive.
REM New drives save them automatically in ecoroads-edge\sessions\<drive>\detections\.
REM This re-runs detection on an OLD drive to make them: DETECTION_PICTURES.bat [drive folder]
REM It uses a throw-away database, so nothing is uploaded to the cloud again.
cd /d %~dp0
set PY=%~dp0ecoroads-edge\venv\Scripts\python.exe
set DRIVE=%~1
if "%DRIVE%"=="" set DRIVE=latest
set ECOROADS_EDGE_DB=%TEMP%\ecoroads_pictures_only.db
if exist "%ECOROADS_EDGE_DB%" del "%ECOROADS_EDGE_DB%"
cd /d "%~dp0ecoroads-edge\src"
if "%DRIVE%"=="latest" (
  for /f "usebackq delims=" %%d in (`call "%PY%" -c "from session import latest_session;print(latest_session() or '')"`) do set DRIVE=%%d
)
echo Re-running detection on drive: %DRIVE%
echo A long drive takes a while - the preview window shows progress. Press q to stop early.
"%PY%" capture_detect.py --replay "%DRIVE%" --fast
if exist "%DRIVE%\detections_replay" start "" "%DRIVE%\detections_replay"
pause
