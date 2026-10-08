"""
HTTP-level tests through FastAPI's TestClient (no server process needed).
Run from ecoroads-cloud:   python -m pytest tests -q
"""

import importlib
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from fastapi.testclient import TestClient  # noqa: E402


def client(tmp_path, monkeypatch, key=None, admin=None):
    monkeypatch.setenv("ECOROADS_DB", str(tmp_path / "api.db"))
    if key:
        monkeypatch.setenv("ECOROADS_INGEST_KEY", key)
    if admin:
        monkeypatch.setenv("ECOROADS_ADMIN_KEY", admin)
    import db, road_registry, municipality_registry, offices, ticketing, service
    for m in (db, road_registry, municipality_registry, offices, ticketing, service):
        importlib.reload(m)
    _reset_postgres(db)
    import main
    importlib.reload(main)
    monkeypatch.setattr(road_registry, "query_overpass",
                        lambda lat, lon: [{"tags": {"highway": "residential"}}])
    return TestClient(main.app)


WARD = {"municipality_id": "ward_a", "name": "Ward A", "center_lat": 17.4075,
        "center_lon": 78.4775, "radius_m": 300}
HAZ = {"vehicle_id": "car_01", "timestamp": "2026-10-01T10:00:00+00:00",
       "lat": 17.4076, "lon": 78.4776, "severity_pct": 70}


def test_full_flow(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.post("/api/municipalities", json=WARD).status_code == 200
    r = c.post("/api/ingest", json={"hazards": [HAZ]}).json()
    assert r["accepted"] == 1
    hz = c.get("/api/municipalities/ward_a/hazards").json()
    assert hz["count"] == 1 and hz["hazards"][0]["severity_tier"] == "High"
    rep = c.post("/api/municipalities/ward_a/repairs",
                 json={"lat": 17.4076, "lon": 78.4776, "repaired_at": "2026-10-02T00:00:00Z"})
    assert rep.status_code == 200
    hz = c.get("/api/municipalities/ward_a/hazards").json()
    assert hz["count"] == 0 and len(hz["repaired"]) == 1
    assert c.get("/api/health").json()["raw_hazard_count"] == 1


def test_validation_and_404(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    assert c.post("/api/municipalities", json={**WARD, "municipality_id": "bad id"}).status_code == 422
    assert c.post("/api/ingest", json={"hazards": [{**HAZ, "severity_pct": 150}]}).status_code == 422
    assert c.get("/api/municipalities/nope/hazards").status_code == 404
    assert c.post("/api/municipalities/nope/repairs", json={"lat": 1, "lon": 1}).status_code == 404


def test_api_key_enforced_when_configured(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch, key="s3cret")
    c.post("/api/municipalities", json=WARD)
    assert c.post("/api/ingest", json={"hazards": [HAZ]}).status_code == 401
    ok = c.post("/api/ingest", json={"hazards": [HAZ]}, headers={"X-API-Key": "s3cret"})
    assert ok.status_code == 200


def test_secure_mode_admin_key_and_municipality_tokens(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch, admin="adm1n")
    assert c.get("/api/config").json()["secure"] is True
    assert c.post("/api/municipalities", json=WARD).status_code == 401
    reg = c.post("/api/municipalities", json=WARD, headers={"X-Admin-Key": "adm1n"}).json()
    token = reg["access_token"]
    assert len(token) > 16 and "token_hash" not in reg["municipality"]
    assert all("token_hash" not in m for m in c.get("/api/municipalities").json()["municipalities"])

    c.post("/api/ingest", json={"hazards": [HAZ]})
    repair = {"lat": 17.4076, "lon": 78.4776}
    assert c.post("/api/municipalities/ward_a/repairs", json=repair).status_code == 401
    assert c.post("/api/municipalities/ward_a/repairs", json=repair,
                  headers={"X-Muni-Token": "wrong"}).status_code == 401
    assert c.post("/api/municipalities/ward_a/repairs", json=repair,
                  headers={"X-Muni-Token": token}).status_code == 200
    # reading stays public
    assert c.get("/api/municipalities/ward_a/hazards").status_code == 200


def test_open_mode_and_dashboard_served(tmp_path, monkeypatch):
    c = client(tmp_path, monkeypatch)
    cfg = c.get("/api/config").json()
    assert cfg["secure"] is False and cfg["edge_download_url"] is None
    page = c.get("/")
    assert page.status_code == 200 and "EcoRoads" in page.text


def _reset_postgres(db):
    """Tests normally use a throw-away SQLite file. To run them against a real
    PostgreSQL (DATABASE_URL), you must ALSO set ECOROADS_TEST_ALLOW_DROP=1 —
    the tables are dropped before each test, so never point this at real data."""
    if db.backend() != "postgres":
        return
    assert os.environ.get("ECOROADS_TEST_ALLOW_DROP") == "1", "refusing to drop tables in DATABASE_URL"
    with db.connect() as conn:
        conn.execute("DROP TABLE IF EXISTS hazards, repairs, road_cache, offices, tickets, "
                     "municipalities CASCADE")


def test_office_and_auto_tickets_api_secure(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("ECOROADS_TICKET_MIN_DETECTIONS", "2")
    c = client(tmp_path, monkeypatch, admin="adm1n")
    token = c.post("/api/municipalities", json=WARD, headers={"X-Admin-Key": "adm1n"}).json()["access_token"]
    assert c.get("/api/config").json()["ticket_min_detections"] == 2
    assert c.get("/api/municipalities/ward_a/office").json()["office"]["is_default"] is True
    office = {"name": "Ward A office", "lat": 17.4080, "lon": 78.4776}
    assert c.post("/api/municipalities/ward_a/office", json=office).status_code == 401
    assert c.post("/api/municipalities/ward_a/office", json=office,
                  headers={"X-Muni-Token": token}).status_code == 200
    assert c.get("/api/municipalities/ward_a/office").json()["office"]["name"] == "Ward A office"

    # 1st detection: below the threshold, no ticket
    c.post("/api/ingest", json={"hazards": [HAZ]})
    hz = c.get("/api/municipalities/ward_a/hazards").json()["hazards"][0]
    assert hz["office"] == "Ward A office" and hz["ticket"] is None
    spot = {"lat": hz["lat"], "lon": hz["lon"]}
    assert c.post("/api/municipalities/ward_a/tickets", json=spot,
                  headers={"X-Muni-Token": token}).status_code == 409

    # 2nd detection: the ingest's background task raises the ticket by itself
    r = c.post("/api/ingest", json={"hazards": [{**HAZ, "timestamp": "2026-10-03T11:00:00Z"}]})
    assert r.json()["municipalities_updated"] == ["ward_a"]
    tickets = c.get("/api/municipalities/ward_a/tickets").json()["tickets"]
    assert len(tickets) == 1 and "ASSIGNED TO: Ward A office" in tickets[0]["text"]
    assert c.get("/api/municipalities/ward_a/hazards").json()["hazards"][0]["ticket"] is not None

    # regenerate: staff only
    assert c.post("/api/municipalities/ward_a/tickets", json=spot).status_code == 401
    assert c.post("/api/municipalities/ward_a/tickets", json=spot,
                  headers={"X-Muni-Token": token}).status_code == 200
    assert len(c.get("/api/municipalities/ward_a/tickets").json()["tickets"]) == 2
