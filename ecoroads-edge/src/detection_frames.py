"""
Saves a picture of every pothole the detector decides about, so you can SEE
what was logged (and what was thrown away as a likely shadow).

    <drive folder>/detections/001_logged_64pct.jpg
    <drive folder>/detections/skipped/002_skipped_41pct.jpg
    <drive folder>/detections/index.csv      time, GPS, severity, frames, reason

The picture is the event's worst frame with the red box drawn on it. Pictures
stay on this laptop: the cloud still only receives the 5 numbers per pothole.
"""

import csv
from pathlib import Path

import cv2


class DetectionSaver:
    def __init__(self, folder):
        self.folder = Path(folder)
        (self.folder / "skipped").mkdir(parents=True, exist_ok=True)
        self.index = self.folder / "index.csv"
        self.n = 0
        with open(self.index, "w", newline="") as f:
            csv.writer(f).writerow(["n", "status", "time_utc", "lat", "lon", "severity_pct",
                                    "frames", "max_conf", "reason", "file"])

    def save(self, ev, severity, status, reason=""):
        """status: 'logged' or 'skipped'. Returns the picture's path (or None without a picture)."""
        self.n += 1
        path = None
        if ev.snapshot is not None:
            sub = self.folder if status == "logged" else self.folder / "skipped"
            path = sub / f"{self.n:03d}_{status}_{round(severity)}pct.jpg"
            cv2.imwrite(str(path), ev.snapshot, [cv2.IMWRITE_JPEG_QUALITY, 85])
        with open(self.index, "a", newline="") as f:
            csv.writer(f).writerow([self.n, status, ev.wall_time_iso, f"{ev.lat:.6f}", f"{ev.lon:.6f}",
                                    severity, ev.frames, f"{ev.max_conf:.2f}", reason,
                                    path.relative_to(self.folder).as_posix() if path else ""])
        return path


def draw_boxes(frame, boxes):
    """A copy of the frame with the hazard boxes and confidences drawn on it."""
    img = frame.copy()
    for (x1, y1, x2, y2), conf in boxes:
        cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 3)
        cv2.putText(img, f"{conf:.2f}", (int(x1), max(20, int(y1) - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    return img
