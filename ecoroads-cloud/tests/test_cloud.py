"""
Cloud service tests — no internet needed (Overpass is faked).
Run from ecoroads-cloud:   python -m pytest tests -q
"""

import importlib
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

A_LAT, A_LON = 17.4075, 78.4775          # centre of ward_a
FAR = (17.5000, 78.6000)                 # outside every ward

PUBLIC_WAYS = [{"tags": {"highway": "residential"}}]
PRIVATE_WAYS = [{"tags": {"highway": "service", "access": "private"}}]


def fresh(tmp_path, monkeypatch, overpass=PUBLIC_WAYS):
    """Fresh DB + modules, with Overpass replaced by a fake."""
    monkeypatch.setenv("ECOROADS_DB", str(tmp_path / "test.db"))
    import db, road_registry, service, municipality_registry
    for m in (db, road_registry, municipality_registry, service):
        importlib.reload(m)
    _reset_postgres(db)
    db.init_db()
    calls = []

    def fake_overpass(lat, lon):
        calls.append((lat, lon))
        return overpass(lat, lon) if callable(overpass) else overpass

    monkeypatch.setattr(road_registry, "query_overpass", fake_overpass)
    road_registry.reset_breaker()
    municipality_registry.register_municipality("ward_a", "Ward A", A_LAT, A_LON, 300)
    municipality_registry.register_municipality("ward_b", "Ward B", 17.4110, 78.4805, 250)
    return service, calls


def hz(vehicle, ts, lat=A_LAT, lon=A_LON, sev=60.0):
    return {"vehicle_id": vehicle, "timestamp": ts, "lat": lat, "lon": lon, "severity_pct": sev}


# ---------------- registry ----------------
def test_locate_nearest_center_wins(tmp_path, monkeypatch):
    fresh(tmp_path, monkeypatch)
    from municipality_registry import locate_municipality
    assert locate_municipality(17.4076, 78.4776)["municipality_id"] == "ward_a"
    assert locate_municipality(17.4111, 78.4806)["municipality_id"] == "ward_b"
    assert locate_municipality(*FAR) is None


def test_reregistering_updates_circle(tmp_path, monkeypatch):
    fresh(tmp_path, monkeypatch)
    from municipality_registry import register_municipality, list_municipalities
    register_municipality("ward_a", "Ward A (renamed)", A_LAT, A_LON, 500)
    a = [m for m in list_municipalities() if m["municipality_id"] == "ward_a"][0]
    assert a["name"] == "Ward A (renamed)" and a["radius_m"] == 500
    assert len(list_municipalities()) == 2


# ---------------- ingest gates ----------------
def test_ingest_gates_and_persistence(tmp_path, monkeypatch):
    service, _ = fresh(tmp_path, monkeypatch)
    stats = service.ingest([
        hz("car_01", "2026-10-01T10:00:00+00:00"),
        hz("car_01", "2026-10-01T10:00:05+00:00", *FAR),
    ])
    assert stats["accepted"] == 1
    assert stats["rejected_no_municipality"] == 1
    # survives a "restart" (reload modules against the same file)
    import db, service as s2
    importlib.reload(db); importlib.reload(s2)
    assert s2.count_hazards() == 1


def test_private_road_rejected(tmp_path, monkeypatch):
    service, _ = fresh(tmp_path, monkeypatch, overpass=PRIVATE_WAYS)
    stats = service.ingest([hz("car_01", "2026-10-01T10:00:00Z")])
    assert stats["rejected_unregistered_road"] == 1 and stats["accepted"] == 0


def test_public_service_road_accepted(tmp_path, monkeypatch):
    service, _ = fresh(tmp_path, monkeypatch, overpass=[{"tags": {"highway": "service"}}])
    assert service.ingest([hz("car_01", "2026-10-01T10:00:00Z")])["accepted"] == 1


def test_duplicate_batch_is_idempotent(tmp_path, monkeypatch):
    service, _ = fresh(tmp_path, monkeypatch)
    batch = [hz("car_01", "2026-10-01T10:00:00Z")]
    service.ingest(batch)
    stats = service.ingest(batch)          # edge re-sends after a lost response
    assert stats["duplicates"] == 1 and stats["total_stored"] == 1


def test_road_cache_avoids_repeat_queries(tmp_path, monkeypatch):
    service, calls = fresh(tmp_path, monkeypatch)
    service.ingest([hz("car_01", f"2026-10-01T10:00:0{i}Z", A_LAT + i * 1e-6) for i in range(5)])
    assert len(calls) == 1


def test_overpass_down_fails_open_and_breaker_stops_retries(tmp_path, monkeypatch):
    service, calls = fresh(tmp_path, monkeypatch, overpass=None)
    stats = service.ingest([hz("car_01", f"2026-10-01T10:00:0{i}Z", A_LAT + i * 2e-4) for i in range(3)])
    assert stats["accepted"] == 3 and stats["road_unverified"] == 3
    assert len(calls) == 1                 # breaker opened after the first failure
    active, _ = service.municipality_hazards("ward_a")
    assert all(not h["road_verified"] for h in active)


# ---------------- clustering ----------------
def test_two_vehicles_same_pothole_get_boost(tmp_path, monkeypatch):
    service, _ = fresh(tmp_path, monkeypatch)
    service.ingest([
        hz("car_01", "2026-10-01T10:00:00Z", sev=68.4),
        hz("car_02", "2026-10-01T11:00:00Z", A_LAT + 0.00005, A_LON, sev=71.2),   # ~5.5 m away
        hz("car_01", "2026-10-01T10:01:00Z", A_LAT + 0.001, A_LON, sev=25.6),     # ~110 m away
    ])
    active, _ = service.municipality_hazards("ward_a")
    assert len(active) == 2
    top = active[0]
    assert top["confirmed_by_vehicles"] == ["car_01", "car_02"]
    assert top["severity_pct"] == 72.8          # avg 69.8 + 3 boost
    assert top["severity_tier"] == "High"
    assert top["first_seen"].startswith("2026-10-01T10:00")


def test_eps_is_metres_not_degrees(tmp_path, monkeypatch):
    service, _ = fresh(tmp_path, monkeypatch)
    # 0.00012 deg of longitude at 17.4 N ≈ 12.7 m -> same pothole
    service.ingest([hz("car_01", "2026-10-01T10:00:00Z"),
                    hz("car_02", "2026-10-01T10:00:00Z", A_LAT, A_LON + 0.00012)])
    assert len(service.municipality_hazards("ward_a")[0]) == 1


# ---------------- repairs ----------------
def test_repair_hides_old_detections_and_flags_reopened(tmp_path, monkeypatch):
    service, _ = fresh(tmp_path, monkeypatch)
    service.ingest([hz("car_01", "2026-10-01T10:00:00Z", sev=80)])
    service.mark_repaired("ward_a", A_LAT, A_LON, "patched", "2026-10-02T09:00:00Z")

    active, repaired = service.municipality_hazards("ward_a")
    assert active == [] and len(repaired) == 1

    # a vehicle hits the same pothole a week after the "repair"
    service.ingest([hz("car_02", "2026-10-09T10:00:00Z", A_LAT + 0.00003, A_LON, sev=75)])
    active, repaired = service.municipality_hazards("ward_a")
    assert len(active) == 1 and repaired == []
    assert active[0]["status"] == "reopened"
    assert active[0]["confirmed_by_vehicles"] == ["car_02"]   # only post-repair evidence
    assert active[0]["repaired_at"] == "2026-10-02T09:00:00Z"


def test_repair_for_unknown_municipality(tmp_path, monkeypatch):
    service, _ = fresh(tmp_path, monkeypatch)
    try:
        service.mark_repaired("nope", A_LAT, A_LON)
        assert False, "expected KeyError"
    except KeyError:
        pass


def _reset_postgres(db):
    """Tests normally use a throw-away SQLite file. To run them against a real
    PostgreSQL (DATABASE_URL), you must ALSO set ECOROADS_TEST_ALLOW_DROP=1 —
    the tables are dropped before each test, so never point this at real data."""
    if db.backend() != "postgres":
        return
    assert os.environ.get("ECOROADS_TEST_ALLOW_DROP") == "1", "refusing to drop tables in DATABASE_URL"
    with db.connect() as conn:
        conn.execute("DROP TABLE IF EXISTS hazards, repairs, road_cache, municipalities CASCADE")
