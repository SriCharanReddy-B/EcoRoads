"""
Builds a guaranteed-to-work classroom demo clip from pothole photos —
for when you don't have a recorded drive yet (or the projector laptop
has no internet / no car outside the classroom).

It takes images (best: the validation images of the dataset you trained
on, e.g. datasets/<name>/valid/images) and makes a "driving" video:
each photo slowly zooms in, as if the car is approaching the pothole,
separated by a few seconds of blurred "plain road" so the detector logs
each pothole as a separate event.

    python demo\\make_demo_video.py ecoroads-edge\\datasets\\potholes\\valid\\images
    python demo\\make_demo_video.py PHOTO_FOLDER --count 12 --out demo\\demo_clip.mp4

Then:  python demo\\run_demo.py --video demo\\demo_clip.mp4
"""

import argparse
import random
from pathlib import Path

import cv2

W, H, FPS = 1280, 720, 30


def cover(img, zoom):
    """Resize/crop img to fill W x H, zoomed in by `zoom` around the lower centre (where the road is)."""
    h, w = img.shape[:2]
    scale = max(W / w, H / h) * zoom
    img = cv2.resize(img, (int(w * scale) + 1, int(h * scale) + 1))
    h, w = img.shape[:2]
    x = (w - W) // 2
    y = min(h - H, int((h - H) * 0.75))   # bias towards the bottom of the photo
    return img[y:y + H, x:x + W]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", help="folder with pothole images (.jpg/.png)")
    ap.add_argument("--count", type=int, default=10, help="how many potholes in the clip")
    ap.add_argument("--seconds-each", type=float, default=2.5)
    ap.add_argument("--gap-seconds", type=float, default=2.5, help="plain road between potholes")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "demo_clip.mp4"))
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    files = sorted(p for p in Path(a.folder).iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not files:
        raise SystemExit(f"No images in {a.folder}")
    random.Random(a.seed).shuffle(files)
    files = files[:a.count]

    out = cv2.VideoWriter(a.out, cv2.VideoWriter_fourcc(*"mp4v"), FPS, (W, H))
    n_on, n_gap = int(a.seconds_each * FPS), int(a.gap_seconds * FPS)
    for i, f in enumerate(files):
        img = cv2.imread(str(f))
        if img is None:
            continue
        road = cv2.GaussianBlur(cover(img, 1.0), (0, 0), 35)   # unrecognisable "plain road"
        for _ in range(n_gap):
            out.write(road)
        for k in range(n_on):                                  # approach: zoom 1.0 -> 1.35
            out.write(cover(img, 1.0 + 0.35 * k / n_on))
        print(f"  {i + 1}/{len(files)}  {f.name}")
    out.write(road)
    out.release()
    total = len(files) * (a.seconds_each + a.gap_seconds)
    print(f"\nWrote {a.out}  ({len(files)} potholes, ~{total:.0f} s)")
    print(f"Run the demo:  python demo\\run_demo.py --video \"{a.out}\"")


if __name__ == "__main__":
    main()
