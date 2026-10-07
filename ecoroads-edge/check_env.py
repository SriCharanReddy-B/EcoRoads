"""
One-shot health check for the edge node's environment.
Run from ecoroads-edge with the venv active:   python check_env.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ok = True


def report(label, good, detail=""):
    global ok
    ok &= good
    print(f"[{'OK ' if good else 'FAIL'}] {label}{' — ' + detail if detail else ''}")


report("Python", True, sys.version.split()[0])

try:
    import torch
    cuda = torch.cuda.is_available()
    detail = f"torch {torch.__version__}"
    if cuda:
        detail += f", GPU: {torch.cuda.get_device_name(0)}"
    else:
        detail += " (CPU only — '+cpu' build or driver problem; see README)"
    report("PyTorch + CUDA", cuda, detail)
except ImportError:
    report("PyTorch", False, "not installed")

try:
    import ultralytics
    report("Ultralytics", True, ultralytics.__version__)
except ImportError:
    report("Ultralytics", False, "pip install -r requirements.txt")

try:
    import cv2
    cap = cv2.VideoCapture(0)
    opened = cap.isOpened() and cap.read()[0]
    cap.release()
    report("OpenCV + webcam 0", bool(opened), cv2.__version__ if opened else "webcam index 0 not readable")
except ImportError:
    report("OpenCV", False, "not installed")

model = ROOT / "models" / "best.pt"
report("Trained model", model.exists(),
       str(model) if model.exists() else "missing — run training/train.py")

try:
    import serial  # noqa: F401
    report("pyserial (Arduino accelerometer)", True)
except ImportError:
    report("pyserial", False, "only needed for the accelerometer: pip install pyserial")

print("\nAll good — ready to run." if ok else "\nFix the FAIL lines above, then re-run.")
