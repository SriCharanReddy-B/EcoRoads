"""
Synthetic tree-shadow augmentation for the training set.

Our own drives give real shadow mistakes (hard_negatives.py), but only a few
hundred frames. This script makes the lesson stronger: it copies a share of the
training images and paints realistic dappled "tree canopy" shadows over them,
KEEPING THE SAME LABELS.

What the model learns from that:
  - the dark shadow blobs are NOT labelled, so predicting a pothole there is an error;
  - a real pothole stays a pothole even when it is half in shade.
So it has to rely on the pothole's shape, edges and texture, not on "dark patch".

    venv\\Scripts\\python training\\shadow_augment.py --data C:\\datasets\\potholes\\data.yaml
    venv\\Scripts\\python training\\shadow_augment.py --data ... --undo     # remove them again

How a shadow is drawn (all plain OpenCV/NumPy):
  1. random noise on a coarse grid, enlarged smoothly   -> soft, leafy blobs
  2. keep the darkest part of it (threshold)             -> canopy holes and patches
  3. optionally stretch it in a random direction         -> long shadows of a low sun
  4. blur the edges, then darken the image under it (a little bluish, like real shade)
"""

import argparse
import random
import shutil
from pathlib import Path

import cv2
import numpy as np

from hard_negatives import split_dirs

PREFIX = "shadow_"


def shadow_mask(h, w, rng):
    """Float mask 0..1 (1 = full shadow) shaped like dappled tree shade."""
    cell = rng.choice([12, 18, 26])                       # blob size: small leaves .. big branches
    gh, gw = max(2, h // cell), max(2, w // cell)
    noise = rng.random((gh, gw)).astype(np.float32)
    noise = cv2.resize(noise, (w, h), interpolation=cv2.INTER_CUBIC)
    noise = cv2.GaussianBlur(noise, (0, 0), sigmaX=max(1.0, w / 120))
    lo, hi = np.percentile(noise, 5), np.percentile(noise, 95)
    noise = (noise - lo) / max(hi - lo, 1e-6)
    cover = rng.uniform(0.25, 0.55)                       # share of the image in shade
    mask = (noise < cover).astype(np.float32)

    if rng.random() < 0.6:                                # low sun: stretch and shear the shadows
        angle = rng.uniform(-60, 60)
        scale = rng.uniform(1.0, 1.8)
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        m[:, :2] = m[:, :2] @ np.array([[scale, 0], [0, 1 / scale]], np.float32)
        mask = cv2.warpAffine(mask, m, (w, h), borderMode=cv2.BORDER_REFLECT)

    if rng.random() < 0.5:                                # shade only part of the road
        y0 = int(h * rng.uniform(0.0, 0.5))
        mask[:y0] = 0

    edge = max(1.0, w / rng.choice([60, 90, 140]))         # soft vs sharp shadow edges
    return np.clip(cv2.GaussianBlur(mask, (0, 0), sigmaX=edge), 0, 1)


def add_shadow(img, rng):
    h, w = img.shape[:2]
    mask = shadow_mask(h, w, rng)[..., None]
    darkness = rng.uniform(0.35, 0.65)                     # light kept inside the shadow
    tint = np.array([1.08, 1.0, 0.92], np.float32)         # BGR: shade looks slightly blue
    shaded = img.astype(np.float32) * darkness * tint
    out = img.astype(np.float32) * (1 - mask) + shaded * mask
    return np.clip(out, 0, 255).astype(np.uint8)


def augment(images, labels, share, max_n, seed):
    rng = np.random.default_rng(seed)
    pick = random.Random(seed)
    originals = [p for p in images.iterdir()
                 if p.suffix.lower() in (".jpg", ".jpeg", ".png")
                 and not p.name.startswith((PREFIX, "bg_"))]
    n = min(max_n, int(len(originals) * share))
    made = 0
    for src in pick.sample(originals, n):
        dst = images / f"{PREFIX}{src.stem}.jpg"
        if dst.exists():
            continue
        img = cv2.imread(str(src))
        if img is None:
            continue
        cv2.imwrite(str(dst), add_shadow(img, rng), [cv2.IMWRITE_JPEG_QUALITY, 92])
        lbl = labels / f"{src.stem}.txt"
        out_lbl = labels / f"{PREFIX}{src.stem}.txt"
        if lbl.exists():
            shutil.copy2(lbl, out_lbl)          # same potholes, same boxes
        else:
            out_lbl.write_text("")
        made += 1
    return made, len(originals)


def undo(images, labels):
    removed = 0
    for p in list(images.glob(f"{PREFIX}*")) + list(labels.glob(f"{PREFIX}*")):
        p.unlink()
        removed += 1
    return removed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", required=True, help="path to the dataset's data.yaml")
    ap.add_argument("--share", type=float, default=0.15, help="fraction of training images to copy")
    ap.add_argument("--max", type=int, default=600, help="at most this many shadowed copies")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--undo", action="store_true", help="delete all shadow_* images and labels")
    ap.add_argument("--preview", help="write one example image here and stop (to check the look)")
    args = ap.parse_args()

    images, labels = split_dirs(args.data, "train")
    if args.preview:
        src = next(p for p in sorted(images.iterdir()) if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        img = cv2.imread(str(src))
        cv2.imwrite(args.preview, np.hstack([img, add_shadow(img, np.random.default_rng(args.seed))]))
        print(f"Wrote before/after example to {args.preview}")
        return
    if args.undo:
        print(f"Removed {undo(images, labels)} shadow files.")
        return
    made, total = augment(images, labels, args.share, args.max, args.seed)
    print(f"Added {made} shadowed copies of training images ({total} originals).")


if __name__ == "__main__":
    main()
