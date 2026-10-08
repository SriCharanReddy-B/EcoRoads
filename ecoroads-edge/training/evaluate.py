"""
Model results for the report: per-class Precision / Recall / mAP and speed.

    venv\Scripts\python training\evaluate.py
    venv\Scripts\python training\evaluate.py --data C:\datasets\potholes\data.yaml --samples 8

Writes:
  runs/eval/results.md         table you can paste into the paper / slides
  runs/eval/*.png              PR curve, confusion matrix (made by Ultralytics)
  runs/eval/samples/*.jpg      a few validation images with predicted boxes

Why a separate script: training prints the per-class table only once in the
console; this re-computes it from models/best.pt any time.
"""
import argparse
from pathlib import Path

from ultralytics import YOLO

EDGE = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(EDGE / "models" / "best.pt"))
    ap.add_argument("--data", default=r"C:\datasets\potholes\data.yaml")
    ap.add_argument("--split", default="val", help="val or test")
    ap.add_argument("--samples", type=int, default=6, help="annotated example images to save")
    args = ap.parse_args()

    out = EDGE / "runs" / "eval"
    model = YOLO(args.model)
    m = model.val(data=args.data, split=args.split, imgsz=640, batch=16,
                  project=str(out.parent), name=out.name, exist_ok=True, plots=True)

    rows = ["| Class | Precision | Recall | F1 | mAP@0.5 | mAP@0.5:0.95 |",
            "|---|---|---|---|---|---|"]

    def row(name, p, r, ap50, ap):
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        rows.append(f"| {name} | {p:.3f} | {r:.3f} | {f1:.3f} | {ap50:.3f} | {ap:.3f} |")

    row("All classes", *m.box.mean_results())
    for i, c in enumerate(m.box.ap_class_index):
        row(m.names[int(c)], *m.box.class_result(i))

    sp = m.speed  # milliseconds per image
    total = sum(sp.values())
    text = "\n".join(rows) + (
        f"\n\nSpeed per image: preprocess {sp['preprocess']:.1f} ms, inference {sp['inference']:.1f} ms, "
        f"postprocess {sp['postprocess']:.1f} ms -> about {1000 / total:.0f} images/s on this machine.\n")
    print("\n" + text)
    (out / "results.md").write_text(text, encoding="utf-8")

    # a few validation images with the model's boxes, for screenshots
    img_dir = Path(args.data).parent / ("valid" if args.split == "val" else args.split) / "images"
    imgs = sorted(img_dir.glob("*.jpg"))[: args.samples] if img_dir.exists() else []
    if imgs:
        model.predict([str(p) for p in imgs], conf=0.4, save=True,
                      project=str(out), name="samples", exist_ok=True, verbose=False)
    print(f"Saved results in {out}")


if __name__ == "__main__":
    main()
