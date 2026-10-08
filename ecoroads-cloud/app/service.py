"""
CLOUD — business logic, kept separate from the HTTP layer (main.py).

main.py only translates HTTP <-> Python; everything that decides
anything lives here. That keeps the rules testable without a web server
and is the piece you'd port first if this becomes a Spring Boot service.
"""

import os
import threading
from datetime import datetime, timezone

from clustering import REPAIR_MATCH_RADIUS_M, _parse_ts, cluster_hazards
from db import connect, now_iso
from municipality_registry import (get_municipality, haversine_m, list_municipalities,
                                   locate_municipality)
from offices import distance_to_office_m, get_office
from road_registry import NOT_PUBLIC, check_road
import ticketing

# A repair ticket is raised automatically once a pothole has been detected this
# many times (all vehicles together). One sighting can be a false positive; several
# independent detections at the same spot make it worth sending to the municipality.
TICKET_MIN_DETECTIONS = int(os.environ.get("ECOROADS_TICKET_MIN_DETECTIONS", "3"))

# Two sync batches arriving at the same moment must not both raise a ticket for the
# same pothole, so automatic ticketing runs one municipality-scan at a time.
_ticket_lock = threading.Lock()


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
    touched = set()   # municipalities that received new detections

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
        touched.add(muni["municipality_id"])
        if road != "public":
            stats["road_unverified"] += 1

    stats["total_stored"] = count_hazards()
    stats["municipalities_updated"] = sorted(touched)
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
    office = get_office(municipality_id)
    tickets = ticketing.list_tickets(municipality_id)
    for i, c in enumerate(active, start=1):
        c["cluster_id"] = i   # display number only; use hazard_key to refer to a spot
        c["office"] = office["name"] if office else None
        c["office_distance_m"] = distance_to_office_m(c["lat"], c["lon"], office) if office else None
        c["detections_needed"] = TICKET_MIN_DETECTIONS
        t = _current_ticket(c, tickets)
        c["ticket"] = {"id": t["id"], "created_at": t["created_at"],
                       "generator": t["generator"]} if t else None
    return active, repaired


def _current_ticket(hazard, tickets):
    """
    The latest ticket raised for this spot (tickets are listed newest first).
    For a REOPENED pothole only tickets raised after the repair count: the old
    ticket was for the old (repaired) pothole, so a failed repair gets a new one.
    """
    since = hazard.get("repaired_at") if hazard.get("status") == "reopened" else None
    for t in tickets:
        if haversine_m(hazard["lat"], hazard["lon"], t["lat"], t["lon"]) > REPAIR_MATCH_RADIUS_M:
            continue
        if since and _parse_ts(t["created_at"]) <= _parse_ts(since):
            continue
        return t
    return None


def _raise_ticket(municipality_id, hazard):
    """Facts -> Gemini (or template) -> stored ticket for the municipality's office."""
    muni = get_municipality(municipality_id)
    office = get_office(municipality_id)
    dist = distance_to_office_m(hazard["lat"], hazard["lon"], office)
    facts = ticketing.ticket_facts(hazard, muni, office, dist, TICKET_MIN_DETECTIONS)
    text, generator = ticketing.draft_ticket(facts)
    return ticketing.save_ticket(municipality_id, hazard, office, dist, text, generator)


def auto_tickets(municipality_ids):
    """
    Called after every accepted sync batch. For each pothole of these
    municipalities that has reached TICKET_MIN_DETECTIONS and has no current
    ticket, raise one. Returns the tickets created.
    """
    created = []
    with _ticket_lock:
        for mid in municipality_ids:
            if get_municipality(mid) is None:
                continue
            active, _ = municipality_hazards(mid)
            for h in active:
                if h["detection_count"] >= TICKET_MIN_DETECTIONS and h["ticket"] is None:
                    created.append(_raise_ticket(mid, h))
    return created


def regenerate_ticket(municipality_id, lat, lon):
    """
    Staff ask for a fresh draft (e.g. after setting the office or a Gemini key).
    Only for potholes that have already reached the detection threshold.
    Raises KeyError (unknown municipality), LookupError (no pothole there),
    ValueError (not enough detections yet).
    """
    if get_municipality(municipality_id) is None:
        raise KeyError(municipality_id)
    active, _ = municipality_hazards(municipality_id)
    near = [(haversine_m(lat, lon, h["lat"], h["lon"]), h) for h in active]
    near = [x for x in near if x[0] <= REPAIR_MATCH_RADIUS_M]
    if not near:
        raise LookupError("no open pothole at that location")
    hazard = min(near, key=lambda x: x[0])[1]
    if hazard["detection_count"] < TICKET_MIN_DETECTIONS:
        raise ValueError(f"a ticket is raised after {TICKET_MIN_DETECTIONS} detections; "
                         f"this pothole has {hazard['detection_count']}")
    return _raise_ticket(municipality_id, hazard)


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
