"""
Teach the model what is NOT a pothole (tree shadows, stains, patches) — "hard negatives".

Step 1 — collect: run the model on a recorded drive and save every frame where it
fired, as plain images (no boxes drawn):

    venv\\Scripts\\python training\\hard_negatives.py collect --session all

  -> ecoroads-edge\\hard_negatives\\<session>\\*.jpg   (+ a _preview folder with boxes)

Step 2 — review: open that folder and DELETE the frames that really show a pothole.
What is left are the model's mistakes (shadows etc.).

Step 3 — add: copy the remaining frames into the training set as BACKGROUND images,
i.e. an image with an EMPTY label file ("there is nothing to find here"):

    venv\\Scripts\\python training\\hard_negatives.py add --data C:\\datasets\\potholes\\data.yaml

Step 4 — retrain (same as before):

    venv\\Scripts\\python training\\train.py --data C:\\datasets\\potholes\\data.yaml

Why this works: during training, every box the model predicts on a background image
is counted as a false positive and penalised, so it learns that shadow-shaped dark
areas are not potholes. Ultralytics recommends background images make up roughly
0-10% of the training set, so a few hundred frames is plenty.
"""

import argparse
import shutil
import sys
from pathlib import Path

import cv2
import yaml
from ultralytics import YOLO

EDGE = Path(__file__).resolve().parent.parent
SESSIONS = EDGE / "sessions"
OUT = EDGE / "hard_negatives"


def find_session(name):
    if name == "latest":
        dirs = sorted(d for d in SESSIONS.iterdir() if (d / "video.mp4").exists())
        if not dirs:
            sys.exit(f"No recorded drives with video in {SESSIONS}")
        return dirs[-1]
    p = Path(name)
    return p if p.is_absolute() else SESSIONS / name


def collect(args):
    if args.session == "all":
        sessions = sorted(d for d in SESSIONS.iterdir() if (d / "video.mp4").exists())
        if not sessions:
            sys.exit(f"No recorded drives with video in {SESSIONS}")
    else:
        sessions = [find_session(args.session)]
    todo = [s for s in sessions
            if args.force or not any((OUT / s.name / "_preview").glob("*.jpg"))]
    for s in sessions:
        if s not in todo:
            print(f"{s.name}: already collected - skipped (use --force to scan it again)")
    if not todo:
        print("Nothing new to scan.")
        return
    print("Loading the model...", flush=True)
    model = YOLO(args.model)
    for session in todo:
        collect_one(session, model, args)
    print("\nNow REVIEW them: venv\\Scripts\\python training\\review_detections.py  (or REVIEW_DETECTIONS.bat)\n"
          "or by hand: open ecoroads-edge\\hard_negatives\\<drive>\\_preview to see what fired.\n"
          "In the folder ABOVE _preview, delete every frame that shows a REAL pothole\n"
          "(including pothole photos you pointed the phone at). Keep only the mistakes:\n"
          "tree shadows, stains, patches, road markings. Then run 'add'.")


def collect_one(session, model, args):
    video = session / "video.mp4"
    out = OUT / session.name
    preview = out / "_preview"
    preview.mkdir(parents=True, exist_ok=True)
    hazard = {c.lower() for c in args.classes}
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 15
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    print(f"{session.name}: scanning {total or '?'} frames (this takes a few minutes for a long drive)...",
          flush=True)
    every = max(1, int(round(fps * args.every_s)))   # don't save 15 near-identical frames per second
    n = saved = 0
    last_saved = -every
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        n += 1
        if n % 300 == 0:                                    # progress, so it never looks stuck
            pct = f" ({100 * n // total}%)" if total else ""
            print(f"  frame {n}/{total or '?'}{pct}, {saved} saved", flush=True)
        if n - last_saved < every:
            continue
        r = model.predict(frame, conf=args.conf, verbose=False)[0]
        boxes = [b for b in r.boxes if str(r.names[int(b.cls[0])]).lower() in hazard]
        if not boxes:
            continue
        name = f"{session.name}_f{n:06d}.jpg"
        if (out / "_real_potholes" / name).exists():
            continue                                        # already reviewed as a real pothole
        cv2.imwrite(str(out / name), frame)                 # clean image for training
        for b in boxes:                                     # copy with boxes, for reviewing
            x1, y1, x2, y2 = map(int, b.xyxy[0].tolist())
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
            cv2.putText(frame, f"{float(b.conf[0]):.2f}", (x1, y1 - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.imwrite(str(preview / name), frame)
        saved += 1
        last_saved = n
    cap.release()
    print(f"{session.name}: checked {n} frames, saved {saved} where the model fired -> {out}")


def split_dirs(data_yaml, split="train"):
    """images/ and labels/ folders of a split ("train" or "val") named in data.yaml."""
    data_yaml = Path(data_yaml)
    cfg = yaml.safe_load(data_yaml.read_text(encoding="utf-8"))
    if split not in cfg:
        return None, None
    base = Path(cfg.get("path") or data_yaml.parent)
    if not base.is_absolute():
        base = data_yaml.parent / base
    rel = str(cfg[split])
    images = Path(rel) if Path(rel).is_absolute() else base / rel
    if not images.exists() and rel.startswith("../"):       # Roboflow-style "../train/images"
        images = base / rel[3:]
    if not images.exists():
        if split == "train":
            sys.exit(f"Training images folder not found: {images}")
        return None, None
    labels = images.parent / "labels"
    labels.mkdir(exist_ok=True)
    return images, labels


def add(args):
    train_img, train_lbl = split_dirs(args.data, "train")
    val_img, val_lbl = split_dirs(args.data, "val")
    sources = sorted(OUT.glob("*/*.jpg"))      # the reviewed frames (not the _preview copies)
    if not sources:
        sys.exit(f"No frames in {OUT}\\<drive>\\ - run 'collect' and review them first.")
    added = {"train": 0, "val": 0}
    for i, src in enumerate(sources):
        # every 5th frame goes to validation, so the scores also measure shadow mistakes
        split = "val" if (val_img is not None and i % 5 == 4) else "train"
        images, labels = (val_img, val_lbl) if split == "val" else (train_img, train_lbl)
        dst = images / f"bg_{src.name}"
        if dst.exists():
            continue
        shutil.copy2(src, dst)
        (labels / f"bg_{src.stem}.txt").write_text("")      # empty label = background image
        added[split] += 1
    total = len(list(train_img.glob("*")))
    print(f"Added {added['train']} background images to training and {added['val']} to validation "
          f"({total} training images in total).")
    if added["train"] > 0.1 * total:
        print("Note: that is more than ~10% of the training set; consider keeping fewer.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("collect", help="save frames where the model fired on a recorded drive")
    c.add_argument("--session", default="latest", help="session folder name, 'latest' or 'all'")
    c.add_argument("--model", default=str(EDGE / "models" / "best.pt"))
    c.add_argument("--conf", type=float, default=0.25, help="low on purpose: catch near-misses too")
    c.add_argument("--every-s", type=float, default=0.5, help="at most one frame per this many seconds")
    c.add_argument("--classes", nargs="+", default=["pothole"])
    c.add_argument("--force", action="store_true", help="scan drives that were already collected again")
    a = sub.add_parser("add", help="copy the reviewed frames into the training set as backgrounds")
    a.add_argument("--data", required=True, help="path to the dataset's data.yaml")
    args = p.parse_args()
    collect(args) if args.cmd == "collect" else add(args)


if __name__ == "__main__":
    main()
