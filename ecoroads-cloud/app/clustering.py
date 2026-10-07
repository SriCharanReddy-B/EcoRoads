"""
CLOUD — Spatial deduplication (DBSCAN) + repair tracking.

Edge nodes already computed severity_pct locally per pothole event.
This module groups nearby events (the same real-world pothole seen by
multiple vehicles / passes) into one record, and combines their
severity_pct values — a pothole confirmed by more vehicles gets a small
boost on top of the average.

DBSCAN uses the haversine metric, so EPS is in real metres. (The MVP
used raw degrees: 0.00015° is ~17 m north-south but a different
distance east-west, because longitude lines converge towards the poles.)

Repair tracking (the "contractors can't fake repairs" idea from the
original pitch): when a municipality marks a spot repaired, detections
there from BEFORE the repair are retired. If vehicles keep detecting a
pothole there AFTER the repair date, the hazard comes back flagged
"reopened" — objective evidence that the repair failed or never happened.
"""

from datetime import datetime, timezone

import numpy as np
from sklearn.cluster import DBSCAN

EARTH_RADIUS_M = 6371000.0
DBSCAN_EPS_M = 15.0              # typical phone/GNSS error is 5-10 m
DBSCAN_MIN_SAMPLES = 1
REPAIR_MATCH_RADIUS_M = 20.0     # a repair mark applies to clusters this close


def _parse_ts(ts):
    # Python < 3.11 can't parse a trailing "Z"; timestamps without a zone are taken as UTC
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _dist_m(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lon2 - lon1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return float(2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a)))


def cluster_hazards(hazards, repairs=()):
    """
    hazards: dicts with lat, lon, severity_pct, vehicle_id, timestamp,
             municipality_id, road_status
    repairs: dicts with lat, lon, repaired_at
    Returns (active, repaired):
      active   - open + reopened hazards, severity-sorted descending
      repaired - spots marked repaired with no detections since
    """
    if not hazards:
        return [], []

    coords = np.radians([[h["lat"], h["lon"]] for h in hazards])
    labels = DBSCAN(eps=DBSCAN_EPS_M / EARTH_RADIUS_M, min_samples=DBSCAN_MIN_SAMPLES,
                    metric="haversine", algorithm="ball_tree").fit_predict(coords)

    groups = {}
    for h, label in zip(hazards, labels):
        groups.setdefault(label, []).append(h)

    active, repaired = [], []
    for group in groups.values():
        center_lat = float(np.mean([h["lat"] for h in group]))
        center_lon = float(np.mean([h["lon"] for h in group]))

        repair = _latest_repair_near(center_lat, center_lon, repairs)
        if repair is None:
            active.append(summarize_cluster(group, status="open"))
            continue

        cutoff = _parse_ts(repair["repaired_at"])
        after = [h for h in group if _parse_ts(h["timestamp"]) > cutoff]
        if after:
            s = summarize_cluster(after, status="reopened")
            s["repaired_at"] = repair["repaired_at"]
            active.append(s)
        else:
            s = summarize_cluster(group, status="repaired")
            s["repaired_at"] = repair["repaired_at"]
            repaired.append(s)

    active.sort(key=lambda c: c["severity_pct"], reverse=True)
    return active, repaired


def _latest_repair_near(lat, lon, repairs):
    near = [r for r in repairs if _dist_m(lat, lon, r["lat"], r["lon"]) <= REPAIR_MATCH_RADIUS_M]
    return max(near, key=lambda r: _parse_ts(r["repaired_at"])) if near else None


def summarize_cluster(group, status="open"):
    lats = [h["lat"] for h in group]
    lons = [h["lon"] for h in group]
    severities = [h["severity_pct"] for h in group]
    vehicle_ids = sorted(set(h.get("vehicle_id", "unknown") for h in group))
    timestamps = sorted(h["timestamp"] for h in group if h.get("timestamp"))

    avg_severity = float(np.mean(severities))
    # multi-vehicle confirmation nudges severity up slightly (more real,
    # more urgent) — capped so it can't push a low-severity report to 100
    confirmation_boost = min((len(vehicle_ids) - 1) * 3, 10)
    final_severity = round(min(avg_severity + confirmation_boost, 100.0), 1)
    lat, lon = float(np.mean(lats)), float(np.mean(lons))

    return {
        "hazard_key": f"{lat:.5f},{lon:.5f}",
        "lat": lat,
        "lon": lon,
        "municipality_id": group[0].get("municipality_id"),
        "detection_count": len(group),
        "confirmed_by_vehicles": vehicle_ids,
        "severity_pct": final_severity,
        "severity_tier": severity_tier(final_severity),
        "first_seen": timestamps[0] if timestamps else None,
        "last_seen": timestamps[-1] if timestamps else None,
        "road_verified": all(h.get("road_status", "public") == "public" for h in group),
        "status": status,
    }


def severity_tier(pct):
    if pct >= 75:
        return "Critical"
    elif pct >= 50:
        return "High"
    elif pct >= 25:
        return "Medium"
    return "Low"
