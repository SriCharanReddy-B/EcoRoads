"""
Before/after test of the shadow retraining: old model vs new model on
  - SHADOWS : the shadow frames that went to the VALIDATION split (bg_*.jpg) - the
              model never trained on these, so this is a fair test. Fewer detections = better.
  - POTHOLES: the frames you marked as real potholes in the review app
              (hard_negatives/<drive>/_real_potholes/). Never used for training.
              More detections = better (we must not lose real potholes).

    venv\\Scripts\\python training\\compare_models.py
    venv\\Scripts\\python training\\compare_models.py --val      # also the full validation metrics

Writes runs/compare/summary.md and side-by-side pictures (old | new) in runs/compare/.
"""

import argparse
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

from hard_negatives import OUT, split_dirs

EDGE = Path(__file__).resolve().parent.parent
RES = EDGE / "runs" / "compare"


def detect(model, path, conf, classes):
    r = model.predict(str(path), conf=conf, verbose=False)[0]
    boxes = []
    for b in r.boxes:
        if str(r.names[int(b.cls[0])]).lower() in classes:
            boxes.append((list(map(int, b.xyxy[0].tolist())), float(b.conf[0])))
    return boxes


def draw(img, boxes, title, color):
    img = img.copy()
    for (x1, y1, x2, y2), c in boxes:
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
        cv2.putText(img, f"{c:.2f}", (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
    cv2.rectangle(img, (0, 0), (img.shape[1], 50), (30, 30, 30), -1)
    cv2.putText(img, title, (12, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    return img


def side_by_side(path, old_b, new_b, name):
    img = cv2.imread(str(path))
    if img is None:
        return
    a = draw(img, old_b, f"OLD: {len(old_b)} detection(s)", (0, 0, 255))
    b = draw(img, new_b, f"NEW: {len(new_b)} detection(s)", (0, 200, 0))
    pair = np.hstack([a, np.full((img.shape[0], 20, 3), 255, np.uint8), b])
    s = min(1.0, 1800 / pair.shape[1])
    cv2.imwrite(str(RES / name), cv2.resize(pair, None, fx=s, fy=s))


def run_set(label, paths, old, new, args, good_if_fired):
    rows = []
    for p in paths:
        o, n = detect(old, p, args.conf, args.classes), detect(new, p, args.conf, args.classes)
        rows.append((p, o, n))
    fired_old = sum(1 for _, o, _ in rows if o)
    fired_new = sum(1 for _, _, n in rows if n)
    # pictures of the most interesting cases: where the two models disagree
    changed = [r for r in rows if bool(r[1]) != bool(r[2])][: args.samples]
    for k, (p, o, n) in enumerate(changed):
        side_by_side(p, o, n, f"{label}_{k:02d}.jpg")
    return len(rows), fired_old, fired_new


def pct(a, b):
    return f"{100 * a / b:.1f}%" if b else "-"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--old", default=str(EDGE / "models" / "best_previous.pt"))
    ap.add_argument("--new", default=str(EDGE / "models" / "best.pt"))
    ap.add_argument("--data", default=r"C:\datasets\potholes\data.yaml")
    ap.add_argument("--conf", type=float, default=0.5, help="same threshold as the detector (config.json)")
    ap.add_argument("--classes", nargs="+", default=["pothole"])
    ap.add_argument("--samples", type=int, default=8, help="side-by-side pictures per set")
    ap.add_argument("--val", action="store_true", help="also run full validation for both models")
    args = ap.parse_args()
    args.classes = {c.lower() for c in args.classes}
    RES.mkdir(parents=True, exist_ok=True)

    val_img, _ = split_dirs(args.data, "val")
    shadows = sorted(val_img.glob("bg_*.jpg")) if val_img else []
    potholes = sorted(OUT.glob("*/_real_potholes/*.jpg"))
    if not shadows and not potholes:
        raise SystemExit("No test frames found. Run the review and RETRAIN_SHADOWS.bat first.")

    print("Loading both models...", flush=True)
    old, new = YOLO(args.old), YOLO(args.new)
    lines = ["# Shadow retraining: old vs new model", "",
             f"Confidence threshold {args.conf} (same as the detector).", "",
             "| Test set | Frames | Old model fires | New model fires | Better is |",
             "|---|---|---|---|---|"]
    if shadows:
        print(f"Shadow frames (held-out validation): {len(shadows)}", flush=True)
        n, fo, fn = run_set("shadow", shadows, old, new, args, good_if_fired=False)
        lines.append(f"| Shadows / stains (held out) | {n} | {fo} ({pct(fo, n)}) | {fn} ({pct(fn, n)}) | lower |")
    if potholes:
        print(f"Real pothole frames (your review): {len(potholes)}", flush=True)
        n, fo, fn = run_set("pothole", potholes, old, new, args, good_if_fired=True)
        lines.append(f"| Real potholes (your review) | {n} | {fo} ({pct(fo, n)}) | {fn} ({pct(fn, n)}) | higher |")

    if args.val:
        lines += ["", "| Validation set | Precision | Recall | mAP@0.5 | mAP@0.5:0.95 |", "|---|---|---|---|---|"]
        for name, path in (("Old", args.old), ("New", args.new)):
            m = YOLO(path).val(data=args.data, split="val", plots=False, verbose=False)
            p, r, a50, a = m.box.mean_results()
            lines.append(f"| {name} model | {p:.3f} | {r:.3f} | {a50:.3f} | {a:.3f} |")

    lines += ["", "Side-by-side pictures (old | new) of frames where the models disagree: runs/compare/*.jpg"]
    text = "\n".join(lines)
    (RES / "summary.md").write_text(text, encoding="utf-8")
    print("\n" + text)


if __name__ == "__main__":
    main()
