@echo off
REM Classroom demo. Examples:
REM   DEMO.bat                          replay your latest recorded drive
REM   DEMO.bat --cloud-delay 30         ...and show offline-first buffering
REM   DEMO.bat --video demo\demo_clip.mp4
REM   DEMO.bat --phone                  live phone camera in the room
REM   DEMO.bat --simulate               no model / camera needed (backup plan)
cd /d %~dp0
ecoroads-edge\venv\Scripts\python demo\run_demo.py %*
pause
