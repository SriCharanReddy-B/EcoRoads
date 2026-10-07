"""
Builds the downloadable edge node: EcoRoads-Edge.zip

What a new vehicle operator gets:
    EcoRoads-Edge/
      INSTALL.bat          one-time: Python env, PyTorch (GPU or CPU auto-detected), questions
      START_DRIVE.bat      phone on the windscreen -> detect, record, sync
      REPLAY_LAST_DRIVE.bat
      CHECK_SETUP.bat
      README_FIRST.txt
      ecoroads-edge/       the code + trained model (if models/best.pt exists)

Default output is ecoroads-dashboard/downloads/EcoRoads-Edge.zip, so once
you push the repo the deployed dashboard shows a "⬇ Edge node" link and
serves the file itself — no separate file hosting needed.

    python tools\\build_edge_package.py --cloud-url https://ecoroads.onrender.com
    python tools\\build_edge_package.py --cloud-url URL --out dist\\EcoRoads-Edge.zip

The vehicle API key is NOT put in the zip (the zip is public); INSTALL.bat asks for it.
"""

import argparse
import json
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EDGE = ROOT / "ecoroads-edge"
TOP = "EcoRoads-Edge"

INCLUDE = ["src", "phone", "arduino", "training", "tests", "check_env.py", "setup_config.py",
           "requirements.txt", "config.example.json", "README.md"]
SKIP_PARTS = {"__pycache__", ".pytest_cache"}


def bat(text):
    return text.strip("\n").replace("\n", "\r\n") + "\r\n"


INSTALL = bat(r"""
@echo off
setlocal
cd /d %~dp0
echo ============================================================
echo   EcoRoads edge node - installer (one time, ~3 GB download)
echo ============================================================
where py >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Install Python 3.12 from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH"^), then run INSTALL.bat again.
  pause & exit /b 1
)
set PYV=-3.12
py -3.12 -c "pass" >nul 2>nul || set PYV=-3
if not exist ecoroads-edge\venv\Scripts\python.exe (
  echo Creating Python environment...
  py %PYV% -m venv ecoroads-edge\venv || goto fail
)
set PY=ecoroads-edge\venv\Scripts\python.exe
%PY% -m pip install --upgrade pip || goto fail
where nvidia-smi >nul 2>nul
if errorlevel 1 (
  echo No NVIDIA GPU found - installing CPU PyTorch ^(works, but detection is slower^).
  set TORCH_INDEX=https://download.pytorch.org/whl/cpu
) else (
  echo NVIDIA GPU found - installing CUDA PyTorch.
  set TORCH_INDEX=https://download.pytorch.org/whl/cu128
)
%PY% -m pip install torch torchvision --index-url %TORCH_INDEX% || goto fail
%PY% -m pip install -r ecoroads-edge\requirements.txt || goto fail
%PY% ecoroads-edge\setup_config.py || goto fail
%PY% ecoroads-edge\check_env.py
echo.
echo Installed. Next: read README_FIRST.txt, then run START_DRIVE.bat.
pause
exit /b 0
:fail
echo.
echo Installation failed - see the messages above. Check your internet connection and run INSTALL.bat again.
pause
exit /b 1
""")

START = bat(r"""
@echo off
cd /d %~dp0
if not exist ecoroads-edge\venv\Scripts\python.exe (echo Run INSTALL.bat first. & pause & exit /b 1)
set PY=%~dp0ecoroads-edge\venv\Scripts\python.exe
start "EcoRoads sync (leave open)" /D "%~dp0ecoroads-edge\src" "%PY%" sync_worker.py
cd /d "%~dp0ecoroads-edge\src"
"%PY%" capture_detect.py --phone %*
echo.
echo Drive saved in ecoroads-edge\sessions\. Leave the sync window open until it says "nothing to sync".
pause
""")

REPLAY = bat(r"""
@echo off
cd /d %~dp0ecoroads-edge\src
"%~dp0ecoroads-edge\venv\Scripts\python.exe" capture_detect.py --replay latest %*
pause
""")

CHECK = bat(r"""
@echo off
cd /d %~dp0
ecoroads-edge\venv\Scripts\python.exe ecoroads-edge\check_env.py
echo.
echo To change vehicle ID / server / API key:  ecoroads-edge\venv\Scripts\python.exe ecoroads-edge\setup_config.py
pause
""")

README = """EcoRoads edge node  (version {version})
=====================================================

This laptop rides in the vehicle. A phone on the windscreen sends camera,
GPS and motion to it; it detects potholes on its own GPU/CPU, stores them
locally (works with no internet), and uploads them to the EcoRoads server
whenever it can reach it:

    {cloud}

1. INSTALL (once)       double-click INSTALL.bat
                        - needs Python 3.12 (python.org, tick "Add to PATH")
                        - asks for: vehicle ID, server address, vehicle API key
                          (get the key from whoever runs the server)
2. EVERY DRIVE          - laptop joins the phone's hotspot
                        - double-click START_DRIVE.bat
                        - on the phone open the https://... address it prints
                          (first time: "Advanced" -> "Proceed"), tap Start streaming
                        - allow Python through Windows Firewall (Private AND Public)
3. AFTER THE DRIVE      leave the sync window open until "nothing to sync"
                        REPLAY_LAST_DRIVE.bat  re-runs detection on the recorded drive
                        CHECK_SETUP.bat        checks GPU, camera, model

Model included: {model}
Full guide: ecoroads-edge\\README.md and PHONE_SETUP.md in the project repository.
"""


def build(cloud_url, out, version):
    model = EDGE / "models" / "best.pt"
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for name in INCLUDE:
            p = EDGE / name
            files = [p] if p.is_file() else sorted(f for f in p.rglob("*") if f.is_file())
            for f in files:
                if SKIP_PARTS & set(f.parts):
                    continue
                z.write(f, f"{TOP}/ecoroads-edge/{f.relative_to(EDGE).as_posix()}")
        if model.exists():
            z.write(model, f"{TOP}/ecoroads-edge/models/best.pt")
        else:
            z.writestr(f"{TOP}/ecoroads-edge/models/PUT_best.pt_HERE.txt",
                       "Copy the trained model here as best.pt (see training/train.py).\n")
        z.writestr(f"{TOP}/ecoroads-edge/package_defaults.json",
                   json.dumps({"cloud_url": cloud_url, "version": version}, indent=2))
        phone_guide = ROOT / "PHONE_SETUP.md"
        if phone_guide.exists():
            z.write(phone_guide, f"{TOP}/PHONE_SETUP.md")
        z.writestr(f"{TOP}/INSTALL.bat", INSTALL)
        z.writestr(f"{TOP}/START_DRIVE.bat", START)
        z.writestr(f"{TOP}/REPLAY_LAST_DRIVE.bat", REPLAY)
        z.writestr(f"{TOP}/CHECK_SETUP.bat", CHECK)
        z.writestr(f"{TOP}/README_FIRST.txt",
                   README.format(version=version, cloud=cloud_url,
                                 model="yes" if model.exists() else
                                 "NO - copy best.pt into ecoroads-edge\\models\\").replace("\n", "\r\n"))
    return model.exists()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cloud-url", required=True, help="your deployed server, e.g. https://ecoroads.onrender.com")
    ap.add_argument("--out", default=str(ROOT / "ecoroads-dashboard" / "downloads" / "EcoRoads-Edge.zip"))
    ap.add_argument("--version", default=date.today().isoformat())
    a = ap.parse_args()
    out = Path(a.out)
    has_model = build(a.cloud_url.rstrip("/"), out, a.version)
    print(f"Built {out}  ({out.stat().st_size / 1e6:.1f} MB)")
    if not has_model:
        print("WARNING: models/best.pt not found — the package has no trained model. "
              "Train first, then rebuild.")


if __name__ == "__main__":
    main()
