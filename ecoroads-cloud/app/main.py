"""
CLOUD SERVICE — receives hazard data from all vehicles' edge nodes and
routes each hazard to its responsible municipality.

Endpoints:
  POST /api/municipalities                    register / update a coverage circle
  GET  /api/municipalities                    list registered municipalities
  POST /api/ingest                            edge nodes push {vehicle_id, timestamp, lat, lon, severity_pct}
  GET  /api/municipalities/{id}/hazards       clustered, road-filtered, severity-sorted hazards
  POST /api/municipalities/{id}/repairs       mark a hazard spot as repaired
  GET  /api/health                            liveness + counts (edge sync worker probes this)

Run (from ecoroads-cloud/app):  uvicorn main:app --port 9000
Interactive API docs:           http://localhost:9000/docs

Security (all optional, so local demos keep working with no setup):
  ECOROADS_INGEST_KEY  only edge nodes sending this in X-API-Key can ingest
  ECOROADS_ADMIN_KEY   "public deployment" mode:
                         - registering a municipality needs X-Admin-Key
                         - each municipality gets its own access token (returned once
                           at registration); marking repairs needs X-Muni-Token
                       Reading hazards stays public — it's civic data.
Other settings:
  DATABASE_URL                PostgreSQL (deployed) instead of the local SQLite file
  ECOROADS_EDGE_DOWNLOAD_URL  link shown on the dashboard to download the edge node
  PORT                        set by hosts like Render; see the Dockerfile

The dashboard (ecoroads-dashboard/) is served from "/" by this same app,
so a deployment is ONE web address for both the API and the dashboard.
"""

import hmac
import os
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import service
from db import init_db
from municipality_registry import (check_token, get_municipality, list_municipalities,
                                   register_municipality)

app = FastAPI(title="EcoRoads Cloud")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("ECOROADS_CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()

DASHBOARD_DIR = Path(os.environ.get("ECOROADS_DASHBOARD_DIR",
                                    Path(__file__).resolve().parent.parent.parent / "ecoroads-dashboard"))


def _same(a, b):
    return bool(a) and bool(b) and hmac.compare_digest(a, b)


def secure_mode():
    return bool(os.environ.get("ECOROADS_ADMIN_KEY"))


def require_admin(x_admin_key):
    if secure_mode() and not _same(x_admin_key, os.environ["ECOROADS_ADMIN_KEY"]):
        raise HTTPException(status_code=401, detail="admin key required to register municipalities")


class MunicipalityIn(BaseModel):
    municipality_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$")
    name: str = Field(min_length=1, max_length=120)
    center_lat: float = Field(ge=-90, le=90)
    center_lon: float = Field(ge=-180, le=180)
    radius_m: float = Field(gt=0, le=50000)


class HazardIn(BaseModel):
    vehicle_id: str = Field(min_length=1, max_length=64)
    timestamp: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    severity_pct: float = Field(ge=0, le=100)


class IngestPayload(BaseModel):
    hazards: List[HazardIn] = Field(max_length=500)


class RepairIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    note: Optional[str] = Field(default=None, max_length=500)
    repaired_at: Optional[str] = None   # defaults to now (UTC)


@app.get("/api/config")
def get_config():
    """Tells the dashboard which mode the server runs in."""
    return {"secure": secure_mode(),
            "edge_download_url": os.environ.get("ECOROADS_EDGE_DOWNLOAD_URL") or None}


@app.post("/api/municipalities")
def create_municipality(m: MunicipalityIn, x_admin_key: Optional[str] = Header(default=None)):
    """A municipality registers (or updates) its own coverage circle through the dashboard.
    The response contains its access token — shown ONCE, only a hash is stored."""
    require_admin(x_admin_key)
    result, token = register_municipality(m.municipality_id, m.name, m.center_lat, m.center_lon,
                                          m.radius_m)
    return {"status": "registered", "municipality": result, "access_token": token}


@app.get("/api/municipalities")
def get_municipalities():
    return {"municipalities": list_municipalities()}


@app.post("/api/ingest")
def ingest_hazards(payload: IngestPayload, x_api_key: Optional[str] = Header(default=None)):
    expected = os.environ.get("ECOROADS_INGEST_KEY")
    if expected and not _same(x_api_key, expected):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
    try:
        stats = service.ingest([h.model_dump() for h in payload.hazards])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"bad timestamp: {e}")
    return {"status": "ok", **stats}


@app.get("/api/municipalities/{municipality_id}/hazards")
def get_municipality_hazards(municipality_id: str):
    if get_municipality(municipality_id) is None:
        raise HTTPException(status_code=404, detail="Municipality not registered")
    active, repaired = service.municipality_hazards(municipality_id)
    return {"municipality_id": municipality_id, "count": len(active),
            "hazards": active, "repaired": repaired}


@app.post("/api/municipalities/{municipality_id}/repairs")
def create_repair(municipality_id: str, r: RepairIn,
                  x_muni_token: Optional[str] = Header(default=None),
                  x_admin_key: Optional[str] = Header(default=None)):
    if secure_mode() and not (check_token(municipality_id, x_muni_token)
                              or _same(x_admin_key, os.environ["ECOROADS_ADMIN_KEY"])):
        raise HTTPException(status_code=401, detail="this municipality's access token is required")
    try:
        repair = service.mark_repaired(municipality_id, r.lat, r.lon, r.note, r.repaired_at)
    except KeyError:
        raise HTTPException(status_code=404, detail="Municipality not registered")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"bad repaired_at: {e}")
    return {"status": "recorded", "repair": repair}


@app.get("/api/ping")
def ping():
    """Liveness only — doesn't touch the database. Render's health checks use this,
    so they don't keep a free Neon database awake (and burning its monthly hours)."""
    return {"status": "ok"}


@app.get("/api/health")
def health():
    return {"status": "ok", "raw_hazard_count": service.count_hazards(),
            "municipality_count": len(list_municipalities())}


# Dashboard at "/" — mounted last so it never shadows the /api routes.
if DASHBOARD_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(DASHBOARD_DIR), html=True), name="dashboard")
