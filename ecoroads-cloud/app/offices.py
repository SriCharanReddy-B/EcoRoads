"""
CLOUD — the municipal office of each municipality (one per municipality).

Routing a pothole is two steps:
  1. JURISDICTION: which municipality owns the pothole — the one whose
     registered circle contains it (nearest centre wins on overlap).
     municipality_registry.locate_municipality, using the Haversine distance.
  2. OFFICE: that municipality has exactly ONE office, which receives the
     ticket. The Haversine distance from the pothole to the office is put
     on the ticket so staff know how far the crew has to travel:

        d = 2R · atan2(√a, √(1−a)),  a = sin²(Δφ/2) + cos φ1 · cos φ2 · sin²(Δλ/2)

If staff haven't set the office yet, the centre of the municipality's
circle is used as "<Name> Municipal Office", so a ticket always has an
addressee.
"""

from db import connect, now_iso
from municipality_registry import get_municipality, haversine_m


def set_office(municipality_id, name, lat, lon, contact=None):
    """Create or replace THE office of this municipality."""
    with connect() as conn:
        conn.execute("DELETE FROM offices WHERE municipality_id = ?", (municipality_id,))
        conn.execute(
            """INSERT INTO offices (municipality_id, name, lat, lon, contact, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (municipality_id, name, lat, lon, contact, now_iso()),
        )
    return get_office(municipality_id)


def get_office(municipality_id):
    """The municipality's office, or a default at the circle centre. None if no municipality."""
    with connect() as conn:
        row = conn.execute(
            """SELECT name, lat, lon, contact FROM offices WHERE municipality_id = ?
               ORDER BY id DESC LIMIT 1""", (municipality_id,)).fetchone()
    if row:
        return {**dict(row), "municipality_id": municipality_id, "is_default": False}
    muni = get_municipality(municipality_id)
    if muni is None:
        return None
    return {"municipality_id": municipality_id, "name": f"{muni['name']} Municipal Office",
            "lat": muni["center_lat"], "lon": muni["center_lon"], "contact": None,
            "is_default": True}


def distance_to_office_m(lat, lon, office):
    """Haversine distance (metres) from a pothole to the office."""
    return round(haversine_m(lat, lon, office["lat"], office["lon"]), 1)
