"""
Review tool: shows every frame where the model fired, one by one, so you can
remove the REAL potholes before training the model on shadows.

    venv\\Scripts\\python training\\review_detections.py

Keys (the window must be focused):
    D  or Delete          REAL POTHOLE -> removed from the shadow training set
    K  or Space or ->     NOT a pothole (shadow, stain, patch...) -> kept for training
    A  or <-              go back to the previous picture (you can change your answer)
    Z                     zoom in on the red box (press again to see the whole frame)
    Q  or Esc             stop; your answers are saved, run again to continue

Nothing is deleted from disk. A frame you mark as a real pothole is MOVED to
hard_negatives/<drive>/_real_potholes/, which hard_negatives.py 'add' ignores,
so a wrong answer can always be undone (press A and then K).

Why: the frames left in hard_negatives/<drive>/ are added to the training set as
"background" images (nothing to find here). A real pothole left among them would
teach the model to IGNORE potholes, so each one must be removed.
"""

import argparse
import json
import shutil
from pathlib import Path

import cv2
import numpy as np

EDGE = Path(__file__).resolve().parent.parent
OUT = EDGE / "hard_negatives"
WIN = "EcoRoads review  |  D = real pothole (remove)   K / Space = shadow (keep)   A = back   Q = quit"

# key codes from cv2.waitKeyEx (arrows / Delete differ by platform, so accept several)
DELETE_KEYS = {ord("d"), ord("D"), ord("p"), ord("P"), 3014656, 65535, 0x2E0000}
KEEP_KEYS = {ord("k"), ord("K"), ord(" "), 13, 10, 2555904, 65363, 0x270000}
BACK_KEYS = {ord("a"), ord("A"), 8, 2424832, 65361, 0x250000}
QUIT_KEYS = {ord("q"), ord("Q"), 27}
ZOOM_KEYS = {ord("z"), ord("Z")}


def zoom_on_boxes(img, margin=1.5):
    """Crop around the red detection boxes drawn in the preview (pure red pixels)."""
    b, g, r = img[..., 0], img[..., 1], img[..., 2]
    ys, xs = np.nonzero((r > 200) & (g < 60) & (b < 60))
    if len(xs) < 20:
        return img
    x1, x2, y1, y2 = xs.min(), xs.max(), ys.min(), ys.max()
    w, h = x2 - x1, y2 - y1
    side = int(max(w, h) * (1 + 2 * margin))
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    x1, y1 = max(0, cx - side // 2), max(0, cy - side // 2)
    return img[y1:min(img.shape[0], y1 + side), x1:min(img.shape[1], x1 + side)]


class Item:
    """One detection frame: the clean image (training) and its preview (with boxes)."""

    def __init__(self, drive, name):
        self.drive, self.name = drive, name

    @property
    def frame(self):
        return self.drive / self.name

    @property
    def removed(self):
        return self.drive / "_real_potholes" / self.name

    @property
    def preview(self):
        p = self.drive / "_preview" / self.name
        return p if p.exists() else (self.frame if self.frame.exists() else self.removed)

    def status(self, kept):
        if self.removed.exists():
            return "pothole"
        if str(self.frame) in kept:
            return "shadow"
        return "new"

    def mark_pothole(self, kept):
        if self.frame.exists():
            self.removed.parent.mkdir(exist_ok=True)
            shutil.move(str(self.frame), str(self.removed))
        kept.discard(str(self.frame))

    def mark_shadow(self, kept):
        if self.removed.exists():
            shutil.move(str(self.removed), str(self.frame))
        kept.add(str(self.frame))


def load_items(root):
    items = []
    for drive in sorted(d for d in root.iterdir() if d.is_dir()):
        names = {p.name for p in (drive / "_preview").glob("*.jpg")}
        names |= {p.name for p in drive.glob("*.jpg")}
        names |= {p.name for p in (drive / "_real_potholes").glob("*.jpg")}
        items += [Item(drive, n) for n in sorted(names)]
    return items


def load_state(root):
    f = root / "review.json"
    return set(json.loads(f.read_text())) if f.exists() else set()


def save_state(root, kept):
    (root / "review.json").write_text(json.dumps(sorted(kept), indent=0))


def window_size():
    """Current drawable size of the review window (falls back to 1280x850)."""
    try:
        _, _, w, h = cv2.getWindowImageRect(WIN)
        if w > 200 and h > 200:
            return w, h
    except cv2.error:
        pass
    return 1280, 850


def render(item, i, n, kept, size=(1280, 850), zoom=False):
    """Draw the picture LETTERBOXED into the window: same aspect ratio as the
    original frame, black bars around it, text drawn at the window's real size."""
    W, H = size
    bar_h = 70
    img = cv2.imread(str(item.preview))
    if img is None:
        img = np.zeros((480, 640, 3), np.uint8)
    if zoom:
        img = zoom_on_boxes(img)
    s = min(W / img.shape[1], (H - bar_h) / img.shape[0])   # fit, never stretch
    img = cv2.resize(img, (max(1, int(img.shape[1] * s)), max(1, int(img.shape[0] * s))),
                     interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    canvas = np.zeros((H, W, 3), np.uint8)
    x0, y0 = (W - img.shape[1]) // 2, bar_h + (H - bar_h - img.shape[0]) // 2
    canvas[y0:y0 + img.shape[0], x0:x0 + img.shape[1]] = img
    canvas[:bar_h] = 30
    st = item.status(kept)
    label, color = {"pothole": ("REAL POTHOLE - removed", (60, 60, 255)),
                    "shadow": ("NOT a pothole - kept for training", (80, 220, 80)),
                    "new": ("not reviewed yet", (200, 200, 200))}[st]
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(canvas, f"{i + 1}/{n}", (12, 28), font, 0.7, (240, 240, 240), 2, cv2.LINE_AA)
    cv2.putText(canvas, label, (12, 58), font, 0.75, color, 2, cv2.LINE_AA)
    hint = f"D = real pothole    K / Space = shadow    A = back    Z = zoom {'off' if zoom else 'on'}    Q = quit"
    (tw, _), _ = cv2.getTextSize(hint, font, 0.6, 1)
    cv2.putText(canvas, hint, (max(330, W - tw - 12), 58), font, 0.6, (190, 190, 190), 1, cv2.LINE_AA)
    cv2.putText(canvas, item.name, (max(330, W - cv2.getTextSize(item.name, font, 0.5, 1)[0][0] - 12), 26),
                font, 0.5, (150, 150, 150), 1, cv2.LINE_AA)
    return canvas


def review(root, show=cv2.imshow, wait=cv2.waitKeyEx, size=window_size, alive=lambda: True):
    items = load_items(root)
    if not items:
        print(f"No detection frames in {root}. Run first:\n"
              "  venv\\Scripts\\python training\\hard_negatives.py collect --session all")
        return
    kept = load_state(root)
    i = next((k for k, it in enumerate(items) if it.status(kept) == "new"), 0)
    print(f"{len(items)} frames to review. Start at {i + 1}.")
    zoom = False
    while 0 <= i < len(items):
        it = items[i]
        cur = size()
        show(WIN, render(it, i, len(items), kept, cur, zoom))
        key = -1
        while key == -1:                       # wait for a key; redraw if the window is resized
            key = wait(100)
            if not alive():
                key = ord("q")
            elif key == -1 and size() != cur:
                cur = size()
                show(WIN, render(it, i, len(items), kept, cur, zoom))
        if key in QUIT_KEYS:
            break
        if key in DELETE_KEYS:
            it.mark_pothole(kept); i += 1
        elif key in KEEP_KEYS:
            it.mark_shadow(kept); i += 1
        elif key in BACK_KEYS:
            i = max(0, i - 1)
        elif key in ZOOM_KEYS:
            zoom = not zoom                    # stays on for the next pictures too
        save_state(root, kept)
    save_state(root, kept)
    counts = {"pothole": 0, "shadow": 0, "new": 0}
    for it in items:
        counts[it.status(kept)] += 1
    print(f"\nReal potholes removed: {counts['pothole']}   kept as shadows: {counts['shadow']}   "
          f"not reviewed: {counts['new']}")
    if counts["new"]:
        print("Run the tool again to finish. Unreviewed frames would be used for training as-is.")
    return counts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", default=str(OUT), help="hard_negatives folder")
    ap.add_argument("--strict", action="store_true",
                    help="exit with an error if some frames are still unreviewed (used by RETRAIN_SHADOWS.bat)")
    args = ap.parse_args()
    root = Path(args.folder)
    if not root.exists():
        raise SystemExit(f"{root} not found. Run hard_negatives.py collect first.")
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, 1280, 850)
    alive = lambda: cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) >= 1   # closed with the X?
    try:
        counts = review(root, alive=alive)
    finally:
        cv2.destroyAllWindows()
    if args.strict and counts and counts["new"]:
        raise SystemExit("Stopped: review every frame before training (run RETRAIN_SHADOWS.bat again).")


if __name__ == "__main__":
    main()
