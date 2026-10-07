"""
CLOUD — Municipality boundary registry.

Municipalities register their own coverage area as a CIRCLE (center
lat/lon + radius in meters) rather than a hand-coded polygon — this
matches the actual test setup (200-500m radius zones) and, more
importantly, means municipalities self-register through the dashboard
instead of you hardcoding their boundaries in source code.

If you later need irregular-shaped boundaries (a municipality's real
ward isn't a circle), this can be swapped for polygon storage without
changing anything else downstream — locate_municipality() is the only
function that would need to change.

Persisted through db.py (SQLite locally, PostgreSQL when deployed).
"""

import hashlib
import hmac
import math
import secrets
from typing import Optional

from db import connect, now_iso

PUBLIC_COLS = "municipality_id, name, center_lat, center_lon, radius_m, created_at"


def _hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def register_municipality(municipality_id, name, center_lat, center_lon, radius_m):
    """
    Create, or update if the ID already exists (lets a municipality fix its circle).
    Returns (municipality, access_token). The token lets that municipality's
    staff mark repairs; only its SHA-256 hash is stored, so a leaked database
    doesn't leak usable tokens. Re-registering issues a new token (rotation).
    """
    token = secrets.token_urlsafe(18)
    with connect() as conn:
        conn.execute(
            """INSERT INTO municipalities
                 (municipality_id, name, center_lat, center_lon, radius_m, created_at, token_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(municipality_id) DO UPDATE SET
                 name=excluded.name, center_lat=excluded.center_lat,
                 center_lon=excluded.center_lon, radius_m=excluded.radius_m,
                 token_hash=excluded.token_hash""",
            (municipality_id, name, center_lat, center_lon, radius_m, now_iso(), _hash(token)),
        )
    return get_municipality(municipality_id), token


def check_token(municipality_id, token) -> bool:
    if not token:
        return False
    with connect() as conn:
        row = conn.execute("SELECT token_hash FROM municipalities WHERE municipality_id = ?",
                           (municipality_id,)).fetchone()
    return bool(row and row["token_hash"]) and hmac.compare_digest(row["token_hash"], _hash(token))


def get_municipality(municipality_id) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute(f"SELECT {PUBLIC_COLS} FROM municipalities WHERE municipality_id = ?",
                           (municipality_id,)).fetchone()
    return dict(row) if row else None


def list_municipalities():
    with connect() as conn:
        rows = conn.execute(f"SELECT {PUBLIC_COLS} FROM municipalities ORDER BY name").fetchall()
    return [dict(r) for r in rows]


def haversine_m(lat1, lon1, lat2, lon2):
    """Distance in meters between two lat/lon points."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def locate_municipality(lat, lon, municipalities=None) -> Optional[dict]:
    """
    Returns the municipality whose circle contains this point, or None
    if it falls outside every registered zone. If a point falls inside
    multiple overlapping circles, returns the one whose center is closest
    (i.e. most likely the "true" owner).

    Pass `municipalities` (from list_municipalities()) when locating many
    points in a row, to avoid one DB read per point.
    """
    candidates = []
    for m in municipalities if municipalities is not None else list_municipalities():
        dist = haversine_m(lat, lon, m["center_lat"], m["center_lon"])
        if dist <= m["radius_m"]:
            candidates.append((dist, m))

    if not candidates:
        return None
    candidates.sort(key=lambda c: c[0])
    return candidates[0][1]
