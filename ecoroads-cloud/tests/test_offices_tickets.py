"""
One office per municipality, and repair tickets raised AUTOMATICALLY once a
pothole has been detected ECOROADS_TICKET_MIN_DETECTIONS times (default 3).
Gemini is never really called here: it is faked, so tests need no API key or internet.
Run from ecoroads-cloud:   python -m pytest tests -q
"""

import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

A_LAT, A_LON = 17.4075, 78.4775


def fresh(tmp_path, monkeypatch, min_detections="3"):
    monkeypatch.setenv("ECOROADS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("ECOROADS_TICKET_MIN_DETECTIONS", min_detections)
    import db, road_registry, municipality_registry, offices, ticketing, service
    for m in (db, road_registry, municipality_registry, offices, ticketing, service):
        importlib.reload(m)
    if db.backend() == "postgres":
        assert os.environ.get("ECOROADS_TEST_ALLOW_DROP") == "1"
        with db.connect() as conn:
            conn.execute("DROP TABLE IF EXISTS hazards, repairs, road_cache, offices, tickets, "
                         "municipalities CASCADE")
    db.init_db()
    monkeypatch.setattr(road_registry, "query_overpass",
                        lambda lat, lon: [{"tags": {"highway": "residential"}}])
    municipality_registry.register_municipality("ward_a", "Ward A", A_LAT, A_LON, 2000)
    return service, offices, ticketing


def hz(ts, lat=A_LAT, lon=A_LON, sev=80.0, v="car_01"):
    return {"vehicle_id": v, "timestamp": ts, "lat": lat, "lon": lon, "severity_pct": sev}


def detect(service, n, day=1, v="car_01"):
    """n detections of the same pothole (different times), then run auto-ticketing."""
    stats = service.ingest([hz(f"2026-10-{day:02d}T10:{i:02d}:00Z", v=v) for i in range(n)])
    return service.auto_tickets(stats["municipalities_updated"])


# ---------------------------------------------------------------- office

def test_default_office_is_the_municipality_centre(tmp_path, monkeypatch):
    _, offices, _ = fresh(tmp_path, monkeypatch)
    o = offices.get_office("ward_a")
    assert o["name"] == "Ward A Municipal Office" and o["is_default"]
    assert (o["lat"], o["lon"]) == (A_LAT, A_LON)
    assert offices.get_office("nope") is None


def test_one_office_per_municipality(tmp_path, monkeypatch):
    _, offices, _ = fresh(tmp_path, monkeypatch)
    offices.set_office("ward_a", "Old office", A_LAT, A_LON)
    offices.set_office("ward_a", "New office", A_LAT + 0.009, A_LON, "ae@example.gov")  # replaces
    o = offices.get_office("ward_a")
    assert o["name"] == "New office" and o["contact"] == "ae@example.gov" and not o["is_default"]


def test_haversine_distance_to_office(tmp_path, monkeypatch):
    service, offices, _ = fresh(tmp_path, monkeypatch)
    offices.set_office("ward_a", "Ward A office", A_LAT + 0.009, A_LON)   # ~1.0 km north
    service.ingest([hz("2026-10-01T10:00:00Z")])
    h = service.municipality_hazards("ward_a")[0][0]
    assert h["office"] == "Ward A office"
    assert 990 < h["office_distance_m"] < 1010


# ---------------------------------------------------------------- automatic tickets

def test_no_ticket_below_threshold(tmp_path, monkeypatch):
    service, _, ticketing = fresh(tmp_path, monkeypatch)
    assert detect(service, 2) == []
    h = service.municipality_hazards("ward_a")[0][0]
    assert h["ticket"] is None and h["detections_needed"] == 3
    assert ticketing.list_tickets("ward_a") == []


def test_ticket_raised_at_threshold_only_once(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    service, offices, ticketing = fresh(tmp_path, monkeypatch)
    offices.set_office("ward_a", "Zone 3 Engineering", A_LAT + 0.001, A_LON, "ae.zone3@example.gov")
    created = detect(service, 3)
    assert len(created) == 1
    t = created[0]
    assert t["generator"] == "template"
    assert "ASSIGNED TO: Zone 3 Engineering" in t["text"]
    assert "detected 3 times (threshold 3)" in t["text"]
    assert "PRIORITY: P1" in t["text"]                      # 80% = Critical
    assert detect(service, 2, day=2) == []                  # more detections: no duplicate
    assert len(ticketing.list_tickets("ward_a")) == 1
    assert service.municipality_hazards("ward_a")[0][0]["ticket"]["generator"] == "template"


def test_threshold_is_configurable(tmp_path, monkeypatch):
    service, _, _ = fresh(tmp_path, monkeypatch, min_detections="1")
    assert len(detect(service, 1)) == 1


def test_ticket_uses_gemini_with_only_system_facts(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    service, offices, ticketing = fresh(tmp_path, monkeypatch)
    offices.set_office("ward_a", "Ward A office", A_LAT, A_LON + 0.002)
    seen = {}

    def fake_call(prompt, api_key, model):
        seen.update(prompt=prompt, key=api_key, model=model)
        return "SUBJECT: Critical pothole\nPRIORITY: P1"

    monkeypatch.setattr(ticketing, "call_gemini", fake_call)
    t = detect(service, 3)[0]
    assert t["generator"] == "gemini:gemini-test" and t["text"].startswith("SUBJECT")
    assert seen["key"] == "fake-key"
    assert "assigned_office: Ward A office" in seen["prompt"]
    assert "raised_because: detected 3 times" in seen["prompt"]
    assert "Do not invent" in seen["prompt"]


def test_gemini_failure_falls_back_to_template(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    service, _, ticketing = fresh(tmp_path, monkeypatch)
    import requests

    def boom(*a, **k):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(ticketing, "call_gemini", boom)
    assert detect(service, 3)[0]["generator"] == "template"


def test_reopened_pothole_gets_a_new_ticket_after_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    service, _, ticketing = fresh(tmp_path, monkeypatch)
    clock = {"now": "2026-10-01T11:00:00+00:00"}           # tickets are stamped by this clock
    monkeypatch.setattr(ticketing, "now_iso", lambda: clock["now"])
    assert len(detect(service, 3, day=1)) == 1
    service.mark_repaired("ward_a", A_LAT, A_LON, "patched", "2026-10-02T00:00:00Z")
    clock["now"] = "2026-10-06T11:00:00+00:00"
    assert detect(service, 2, day=5, v="bus_9") == []        # 2 new sightings: not yet
    created = detect(service, 1, day=6, v="bus_9")           # 3rd after the repair
    assert len(created) == 1
    assert "earlier repair appears to have failed" in created[0]["text"]
    assert len(ticketing.list_tickets("ward_a")) == 2


def test_regenerate_rules(tmp_path, monkeypatch):
    service, _, _ = fresh(tmp_path, monkeypatch)
    detect(service, 2)
    with pytest.raises(ValueError):                         # below the threshold
        service.regenerate_ticket("ward_a", A_LAT, A_LON)
    with pytest.raises(LookupError):                        # ~1 km away: no pothole
        service.regenerate_ticket("ward_a", A_LAT + 0.01, A_LON)
    detect(service, 1, day=2)
    assert service.regenerate_ticket("ward_a", A_LAT, A_LON)["text"]
