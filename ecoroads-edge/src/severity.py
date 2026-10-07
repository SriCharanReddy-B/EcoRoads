"""
Computes a 0-100% severity score LOCALLY on the edge device, from the
raw YOLO detection (confidence + bounding box). This is the only
severity-related number that ever leaves this device — raw confidence,
bbox coordinates, and frame images stay on the laptop and are never
transmitted.

Why compute it here instead of the cloud: the whole point of this
being an edge node is that it's a self-contained sensor — it should
output a finished measurement (like a thermometer outputs °C, not raw
sensor voltage), not raw model internals. This also means the payload
sent to the cloud is tiny (just numbers), which matters when syncing
over patchy/low-bandwidth connections after being offline.
"""


def compute_severity_pct(confidence, bbox_area_pct):
    """
    confidence: YOLO detection confidence, 0.0-1.0
    bbox_area_pct: bounding box area as % of frame (0-100), a proxy for
                   apparent pothole size relative to camera distance

    Returns: severity as a 0-100 percentage (float, 1 decimal place).

    This is a per-detection score (single camera frame). The cloud side
    combines multiple detections/vehicles into a final cluster severity
    (see cloud clustering.py) — this function only handles the
    single-frame -> single-number step, which is what belongs on the edge.
    """
    confidence_component = confidence * 100        # 0-100
    size_component = min(bbox_area_pct * 8, 100)    # scaled + capped so one
                                                     # huge box doesn't saturate

    # weighted blend — confidence matters slightly more than raw size,
    # since a confident small detection is often more reliable than a
    # low-confidence large one (motion blur, false positive, etc.)
    severity = 0.55 * confidence_component + 0.45 * size_component

    return round(min(severity, 100.0), 1)


if __name__ == "__main__":
    # sanity checks
    print(compute_severity_pct(confidence=0.85, bbox_area_pct=6.0))   # high conf, decent size
    print(compute_severity_pct(confidence=0.40, bbox_area_pct=1.0))   # low conf, small
    print(compute_severity_pct(confidence=0.95, bbox_area_pct=15.0))  # should cap near 100
