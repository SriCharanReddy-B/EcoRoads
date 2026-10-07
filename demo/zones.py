"""Shared helpers: compute municipality circles that cover a drive route."""

import csv
import math
from pathlib import Path

LETTERS = "abcdefghij"


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(a))


def circle_covering(points, margin_m=60, min_radius=150):
    lat = sum(p[0] for p in points) / len(points)
    lon = sum(p[1] for p in points) / len(points)
    r = max(haversine_m(lat, lon, *p) for p in points) + margin_m
    return lat, lon, max(r, min_radius)


def split_route(points, n):
    """
    Cut the route into n consecutive stretches and return one circle per stretch:
    [{"municipality_id": "ward_a", "name": "Ward A Municipality", center_lat, center_lon, radius_m}, ...]

    Circles may overlap a little at the borders; the cloud then gives each
    pothole to the municipality whose CENTRE is nearest — the same rule a
    real overlap would use.
    """
    n = max(1, min(n, len(points), len(LETTERS)))
    size = math.ceil(len(points) / n)
    zones = []
    for i in range(n):
        chunk = points[i * size:(i + 1) * size]
        if not chunk:
            break
        lat, lon, r = circle_covering(chunk)
        zones.append({"municipality_id": f"ward_{LETTERS[i]}", "name": f"Ward {LETTERS[i].upper()} Municipality",
                      "center_lat": lat, "center_lon": lon, "radius_m": round(r)})
    return zones


def route_from_session(session_dir):
    with open(Path(session_dir) / "gps.csv", newline="") as f:
        return [(float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)]
