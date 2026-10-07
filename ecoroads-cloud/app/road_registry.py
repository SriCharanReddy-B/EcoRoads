"""
CLOUD — Road registry filter.

Requirement: only show potholes on "registered roads" — public roads
actually under municipal maintenance jurisdiction — and exclude private
driveways/tracks and unpaved roads that no municipality is responsible
for repairing.

APPROACH: ask OpenStreetMap (free Overpass API, no key) which roads lie
within SEARCH_RADIUS_M of the hazard. OSM tags every road with a
`highway` type and often an `access` tag — exactly the public/private
and paved/unpaved distinction we need.

  - PUBLIC (accepted): residential, primary, secondary, tertiary,
    unclassified, living_street, service (unless private), *_link roads,
    trunk
  - EXCLUDED: track (unpaved/farm), path, footway, cycleway, bridleway,
    steps, pedestrian, and anything tagged access=private / access=no

`service` roads are accepted unless marked private: in Indian cities
many public lanes and colony roads are mapped as `service`.

Returns one of three answers:
  "public"      -> on a public road, accept
  "not_public"  -> only private/unpaved/non-vehicle ways nearby, reject
  "unverified"  -> Overpass unreachable; accepted (FAIL-OPEN) but stored
                   with road_status='unverified' so the dashboard can show it

Robustness:
  - Results are cached in SQLite per ~11 m grid cell (survives restarts),
    so repeat detections near the same spot never re-query Overpass.
  - Circuit breaker: after an Overpass failure we stop calling it for
    BREAKER_COOLDOWN_S. Without this, a batch of 25 hazards during an
    Overpass outage would wait 25 x timeout seconds.
"""

import time

import requests

from db import connect, now_iso

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
SEARCH_RADIUS_M = 25
REQUEST_TIMEOUT = 8
BREAKER_COOLDOWN_S = 60

PUBLIC = "public"
NOT_PUBLIC = "not_public"
UNVERIFIED = "unverified"

ALLOWED_HIGHWAY_TYPES = {
    "residential", "primary", "secondary", "tertiary", "unclassified",
    "living_street", "service", "trunk",
    "primary_link", "secondary_link", "tertiary_link", "trunk_link",
}
EXCLUDED_HIGHWAY_TYPES = {
    "track", "path", "footway", "cycleway", "bridleway", "steps", "pedestrian",
}

_breaker_open_until = 0.0


def _cell_key(lat, lon):
    return f"{round(lat, 4)},{round(lon, 4)}"   # 0.0001 deg ≈ 11 m


def check_road(lat, lon):
    """Classify the road at a point: PUBLIC, NOT_PUBLIC or UNVERIFIED."""
    global _breaker_open_until
    key = _cell_key(lat, lon)

    with connect() as conn:
        row = conn.execute("SELECT is_public FROM road_cache WHERE cell_key = ?", (key,)).fetchone()
    if row is not None:
        return PUBLIC if row["is_public"] else NOT_PUBLIC

    if time.monotonic() < _breaker_open_until:
        return UNVERIFIED

    elements = query_overpass(lat, lon)
    if elements is None:
        _breaker_open_until = time.monotonic() + BREAKER_COOLDOWN_S
        return UNVERIFIED    # fail-open, and NOT cached so it is retried later

    is_public = classify_elements(elements)
    with connect() as conn:
        conn.execute("""INSERT INTO road_cache (cell_key, is_public, checked_at) VALUES (?, ?, ?)
                        ON CONFLICT(cell_key) DO UPDATE SET
                          is_public=excluded.is_public, checked_at=excluded.checked_at""",
                     (key, int(is_public), now_iso()))
    return PUBLIC if is_public else NOT_PUBLIC


def query_overpass(lat, lon):
    """List of OSM ways near the point, or None if Overpass can't be reached."""
    query = f"""
    [out:json][timeout:{REQUEST_TIMEOUT}];
    way(around:{SEARCH_RADIUS_M},{lat},{lon})["highway"];
    out tags;
    """
    try:
        resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return resp.json().get("elements", [])
    except (requests.RequestException, ValueError):
        return None


def classify_elements(elements):
    """True if at least one nearby way is a public, vehicle, municipal-type road."""
    for el in elements:
        tags = el.get("tags", {})
        highway = tags.get("highway", "")
        access = tags.get("access", "")
        if access in ("private", "no"):
            continue
        if highway in EXCLUDED_HIGHWAY_TYPES:
            continue
        if highway in ALLOWED_HIGHWAY_TYPES:
            return True
    # nothing found nearby, or only private/unpaved ways
    return False


def reset_breaker():
    global _breaker_open_until
    _breaker_open_until = 0.0


if __name__ == "__main__":
    # Needs real internet access to overpass-api.de; otherwise prints "unverified".
    from db import init_db
    init_db()
    lat, lon = 17.4075, 78.4775
    print(f"({lat}, {lon}) -> {check_road(lat, lon)}")
