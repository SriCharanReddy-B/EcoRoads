@echo off
REM Start the EcoRoads cloud service on port 9000 (run from ecoroads-cloud)
call venv\Scripts\activate
cd app
uvicorn main:app --host 0.0.0.0 --port 9000
