@echo off
REM Retrain the pothole model so it stops mistaking tree shadows for potholes.
REM   RETRAIN_SHADOWS.bat                       uses C:\datasets\potholes\data.yaml
REM   RETRAIN_SHADOWS.bat D:\my\data.yaml       another dataset
cd /d %~dp0ecoroads-edge
set PY=%~dp0ecoroads-edge\venv\Scripts\python.exe
set DATA=C:\datasets\potholes\data.yaml
if not "%~1"=="" set DATA=%~1
if not exist "%DATA%" (
  echo data.yaml not found at %DATA%
  pause & exit /b 1
)

echo.
echo === Step 1 of 4: find the frames where the model fired on your recorded drives ===
"%PY%" training\hard_negatives.py collect --session all || (pause & exit /b 1)

echo.
echo === Step 2 of 4: REVIEW (you) ===
echo  A window shows each detection. For every picture press:
echo    D = it is a REAL pothole (removed from the shadow set)
echo    K or Space = NOT a pothole (shadow, stain, patch) - kept for training
echo    A = back,  Q = quit (answers are saved; run again to continue)
"%PY%" training\review_detections.py --strict || (pause & exit /b 1)

echo.
echo === Step 3 of 4: add those mistakes + synthetic tree shadows to the dataset ===
"%PY%" training\hard_negatives.py add --data "%DATA%" || (pause & exit /b 1)
"%PY%" training\shadow_augment.py --data "%DATA%" || (pause & exit /b 1)

echo.
echo === Step 4 of 4: fine-tune the current model (about 15-25 minutes on the RTX 4060) ===
"%PY%" training\train.py --data "%DATA%" --base models\best.pt --epochs 30 --name pothole_shadows
echo.
echo Done. The new model is models\best.pt; the old one is kept as models\best_previous.pt.
echo Results and charts: ecoroads-edge\runs\pothole_shadows\
pause
