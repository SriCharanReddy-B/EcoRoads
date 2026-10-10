"""
Train the EcoRoads pothole detector (YOLOv8-nano) and install it as
models/best.pt for the edge node.

Two ways to supply a dataset (YOLOv8 format, i.e. a folder containing
data.yaml + train/ valid/ images and labels):

  A) Roboflow Universe (free account, needs an API key):
       set ROBOFLOW_API_KEY=your_key            (Windows cmd)
       $env:ROBOFLOW_API_KEY="your_key"         (PowerShell)
       python train.py --roboflow WORKSPACE PROJECT VERSION

     WORKSPACE / PROJECT / VERSION come from the dataset's URL, e.g.
     https://universe.roboflow.com/<workspace>/<project>/dataset/<version>

  B) A dataset you already downloaded and unzipped (Roboflow "YOLOv8"
     export, Kaggle, etc.):
       python train.py --data path/to/dataset/data.yaml

Detection AND segmentation pothole datasets both work: Ultralytics
converts polygon labels to bounding boxes automatically when training
a detection model.

Run from the ecoroads-edge folder with the venv active:
    python training/train.py --data datasets/potholes/data.yaml
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

EDGE_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = EDGE_ROOT / "models"
DATASETS_DIR = EDGE_ROOT / "datasets"
RUNS_DIR = EDGE_ROOT / "runs"


def download_from_roboflow(workspace, project, version):
    api_key = os.environ.get("ROBOFLOW_API_KEY")
    if not api_key:
        sys.exit("ROBOFLOW_API_KEY is not set. Get it from roboflow.com -> Settings -> API Keys.")
    try:
        from roboflow import Roboflow
    except ImportError:
        sys.exit("Install the Roboflow client first:  pip install roboflow")

    rf = Roboflow(api_key=api_key)
    dataset = (rf.workspace(workspace).project(project).version(int(version))
               .download("yolov8", location=str(DATASETS_DIR / project)))
    data_yaml = Path(dataset.location) / "data.yaml"
    print(f"Dataset downloaded to {dataset.location}")
    return data_yaml


def pick_device():
    import torch
    if torch.cuda.is_available():
        print(f"GPU found: {torch.cuda.get_device_name(0)} -> training on CUDA")
        return 0
    print("WARNING: no CUDA GPU visible to PyTorch -> training on CPU (very slow).")
    print("         Run  python check_env.py  to diagnose.")
    return "cpu"


def main():
    p = argparse.ArgumentParser(description="Train the EcoRoads pothole model")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--data", help="path to an existing data.yaml")
    src.add_argument("--roboflow", nargs=3, metavar=("WORKSPACE", "PROJECT", "VERSION"))
    p.add_argument("--epochs", type=int, default=60)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=16,
                   help="16 fits an 8 GB RTX 4060; lower to 8 if you get CUDA out-of-memory")
    p.add_argument("--base", default="yolov8n.pt", help="starting weights (nano = fastest at the edge); "
                   "use models/best.pt to fine-tune the current model")
    p.add_argument("--name", default="pothole", help="run folder under runs/ (a new name keeps old results)")
    args = p.parse_args()

    data_yaml = Path(args.data) if args.data else download_from_roboflow(*args.roboflow)
    if not data_yaml.exists():
        sys.exit(f"data.yaml not found at {data_yaml}")

    from ultralytics import YOLO

    device = pick_device()
    model = YOLO(args.base)  # downloads the COCO-pretrained nano weights on first run
    model.train(
        data=str(data_yaml.resolve()),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=device,
        project=str(RUNS_DIR),
        name=args.name,
        exist_ok=True,
        patience=15,       # stop early if validation mAP stops improving
        workers=2,         # Windows dataloaders are happier with few workers
    )

    best = RUNS_DIR / args.name / "weights" / "best.pt"
    if not best.exists():
        sys.exit(f"Training finished but {best} is missing — check the log above.")

    MODELS_DIR.mkdir(exist_ok=True)
    installed = MODELS_DIR / "best.pt"
    if installed.exists():                       # never lose the previous model
        backup = MODELS_DIR / "best_previous.pt"
        shutil.copy2(installed, backup)
        print(f"Previous model kept as {backup}")
    shutil.copy2(best, installed)
    print(f"\nInstalled model -> {MODELS_DIR / 'best.pt'}")

    # Final validation numbers, worth quoting in your report next to the
    # base paper's 93.5% recall / 97.6% precision.
    metrics = YOLO(str(MODELS_DIR / "best.pt")).val(data=str(data_yaml.resolve()), device=device)
    print("\n=== Validation summary ===")
    print(f"precision : {metrics.box.mp:.3f}")
    print(f"recall    : {metrics.box.mr:.3f}")
    print(f"mAP@50    : {metrics.box.map50:.3f}")
    print(f"mAP@50-95 : {metrics.box.map:.3f}")


if __name__ == "__main__":
    main()
