@echo off
REM Multi-laptop: run on the laptop that hosts the server (cloud API + dashboards).
REM   HOST.bat                  municipalities register themselves on their own laptops
REM   HOST.bat --zones 2        split your latest recorded drive into Ward A + Ward B
REM   HOST.bat --zones 2 --fresh   ...on an empty demo database
cd /d %~dp0
ecoroads-edge\venv\Scripts\python demo\host_cloud.py %*
pause
