"""
CLOUD — business logic, kept separate from the HTTP layer (main.py).

main.py only translates HTTP <-> Python; everything that decides
anything lives here. That keeps the rules testable without a web server
and is the piece you'd port first if this becomes a Spring Boot service.
"""

from datetime import datetime, timezone

from clustering import _parse_ts, cluster_hazards
from db import connect, now_iso
from municipality_registry import get_municipality, list_municipalities, locate_municipality
from road_registry import NOT_PUBLIC, check_road


def ingest(hazards):
    """
    hazards: list of dicts {vehicle_id, timestamp, lat, lon, severity_pct}
    Each one passes two gates before being stored:
      1. inside some registered municipality's circle
      2. on a public road (OpenStreetMap), fail-open if OSM is unreachable
    """
    municipalities = list_municipalities()
    stats = {"accepted": 0, "rejected_no_municipality": 0,
             "rejected_unregistered_road": 0, "duplicates": 0, "road_unverified": 0}

    for h in hazards:
        _parse_ts(h["timestamp"])  # raises ValueError on garbage -> 422 from main.py

        muni = locate_municipality(h["lat"], h["lon"], municipalities)
        if muni is None:
            stats["rejected_no_municipality"] += 1
            continue

        road = check_road(h["lat"], h["lon"])
        if road == NOT_PUBLIC:
            stats["rejected_unregistered_road"] += 1
            continue

        with connect() as conn:
            cur = conn.execute(
                """INSERT INTO hazards
                   (vehicle_id, timestamp, lat, lon, severity_pct, municipality_id, road_status, received_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT DO NOTHING""",
                (h["vehicle_id"], h["timestamp"], h["lat"], h["lon"], h["severity_pct"],
                 muni["municipality_id"], road, now_iso()),
            )
        if cur.rowcount == 0:
            stats["duplicates"] += 1
            continue
        stats["accepted"] += 1
        if road != "public":
            stats["road_unverified"] += 1

    stats["total_stored"] = count_hazards()
    return stats


def municipality_hazards(municipality_id):
    with connect() as conn:
        hazards = [dict(r) for r in conn.execute(
            """SELECT vehicle_id, timestamp, lat, lon, severity_pct, municipality_id, road_status
               FROM hazards WHERE municipality_id = ?""", (municipality_id,))]
        repairs = [dict(r) for r in conn.execute(
            "SELECT lat, lon, repaired_at, note FROM repairs WHERE municipality_id = ?",
            (municipality_id,))]
    active, repaired = cluster_hazards(hazards, repairs)
    for i, c in enumerate(active, start=1):
        c["cluster_id"] = i   # display number only; use hazard_key to refer to a spot
    return active, repaired


def mark_repaired(municipality_id, lat, lon, note=None, repaired_at=None):
    if get_municipality(municipality_id) is None:
        raise KeyError(municipality_id)
    ts = repaired_at or datetime.now(timezone.utc).isoformat()
    _parse_ts(ts)
    with connect() as conn:
        conn.execute(
            "INSERT INTO repairs (municipality_id, lat, lon, repaired_at, note) VALUES (?, ?, ?, ?, ?)",
            (municipality_id, lat, lon, ts, note),
        )
    return {"municipality_id": municipality_id, "lat": lat, "lon": lon,
            "repaired_at": ts, "note": note}


def count_hazards():
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM hazards").fetchone()["n"]
