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
  GET/POST /api/municipalities/{id}/office    the municipality's one office (gets its tickets)
  GET  /api/municipalities/{id}/tickets       repair tickets, raised AUTOMATICALLY after N detections
  POST /api/municipalities/{id}/tickets       staff: regenerate the ticket of a pothole

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
  GEMINI_API_KEY / GEMINI_MODEL  Gemini repair-ticket drafting (template used if unset)
  ECOROADS_TICKET_MIN_DETECTIONS detections of one pothole before a ticket is raised (default 3)
  PORT                        set by hosts like Render; see the Dockerfile

The dashboard (ecoroads-dashboard/) is served from "/" by this same app,
so a deployment is ONE web address for both the API and the dashboard.
"""

import hmac
import os
from pathlib import Path
from typing import List, Optional

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import offices as offices_mod
import service
import ticketing
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


class OfficeIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    contact: Optional[str] = Field(default=None, max_length=200)


class TicketIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class RepairIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    note: Optional[str] = Field(default=None, max_length=500)
    repaired_at: Optional[str] = None   # defaults to now (UTC)


@app.get("/api/config")
def get_config():
    """Tells the dashboard which mode the server runs in."""
    return {"secure": secure_mode(),
            "edge_download_url": os.environ.get("ECOROADS_EDGE_DOWNLOAD_URL") or None,
            "ticket_generator": "gemini" if os.environ.get("GEMINI_API_KEY") else "template",
            "ticket_min_detections": service.TICKET_MIN_DETECTIONS}


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
def ingest_hazards(payload: IngestPayload, background: BackgroundTasks,
                   x_api_key: Optional[str] = Header(default=None)):
    expected = os.environ.get("ECOROADS_INGEST_KEY")
    if expected and not _same(x_api_key, expected):
        raise HTTPException(status_code=401, detail="invalid or missing X-API-Key")
    try:
        stats = service.ingest([h.model_dump() for h in payload.hazards])
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"bad timestamp: {e}")
    # Raise tickets AFTER replying: a Gemini call takes seconds and the vehicle
    # shouldn't wait for it. FastAPI runs background tasks once the response is sent.
    if stats["municipalities_updated"]:
        background.add_task(service.auto_tickets, stats["municipalities_updated"])
    return {"status": "ok", **stats}


@app.get("/api/municipalities/{municipality_id}/hazards")
def get_municipality_hazards(municipality_id: str):
    if get_municipality(municipality_id) is None:
        raise HTTPException(status_code=404, detail="Municipality not registered")
    active, repaired = service.municipality_hazards(municipality_id)
    return {"municipality_id": municipality_id, "count": len(active),
            "hazards": active, "repaired": repaired}


def require_municipality_staff(municipality_id, x_muni_token, x_admin_key):
    """Secure mode: only this municipality's staff (token) or the admin may change its data."""
    if get_municipality(municipality_id) is None:
        raise HTTPException(status_code=404, detail="Municipality not registered")
    if secure_mode() and not (check_token(municipality_id, x_muni_token)
                              or _same(x_admin_key, os.environ["ECOROADS_ADMIN_KEY"])):
        raise HTTPException(status_code=401, detail="this municipality's access token is required")


@app.get("/api/municipalities/{municipality_id}/office")
def get_office(municipality_id: str):
    office = offices_mod.get_office(municipality_id)
    if office is None:
        raise HTTPException(status_code=404, detail="Municipality not registered")
    return {"office": office}


@app.post("/api/municipalities/{municipality_id}/office")
def set_office(municipality_id: str, o: OfficeIn,
               x_muni_token: Optional[str] = Header(default=None),
               x_admin_key: Optional[str] = Header(default=None)):
    """Set (or move) the municipality's single office; all its tickets are addressed to it."""
    require_municipality_staff(municipality_id, x_muni_token, x_admin_key)
    return {"status": "saved",
            "office": offices_mod.set_office(municipality_id, o.name, o.lat, o.lon, o.contact)}


@app.post("/api/municipalities/{municipality_id}/tickets")
def regenerate_ticket(municipality_id: str, t: TicketIn,
                      x_muni_token: Optional[str] = Header(default=None),
                      x_admin_key: Optional[str] = Header(default=None)):
    """Staff: write a fresh draft for a pothole that has already reached the threshold."""
    require_municipality_staff(municipality_id, x_muni_token, x_admin_key)
    try:
        ticket = service.regenerate_ticket(municipality_id, t.lat, t.lon)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"status": "created", "ticket": ticket}


@app.get("/api/municipalities/{municipality_id}/tickets")
def get_tickets(municipality_id: str):
    if get_municipality(municipality_id) is None:
        raise HTTPException(status_code=404, detail="Municipality not registered")
    return {"tickets": ticketing.list_tickets(municipality_id)}


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
