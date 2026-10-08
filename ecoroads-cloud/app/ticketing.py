"""
CLOUD — repair-ticket generation with Google Gemini.

The language model is used ONLY to turn a structured, already-verified
pothole record into readable text for municipal staff. It never sees
images, never decides location / severity / office (those come from the
detector, DBSCAN and the municipality's office), and its output is a DRAFT
that staff review. That keeps an LLM's known weakness — inventing facts —
away from anything that matters.

Tickets are raised AUTOMATICALLY (service.auto_tickets) once a pothole has
been detected ECOROADS_TICKET_MIN_DETECTIONS times, and go to the single
office of the municipality that owns the road.

If GEMINI_API_KEY is not set, or Gemini fails / times out, a deterministic
template produces the ticket instead, so the system never depends on an
external AI service to work.

Environment:
  GEMINI_API_KEY   key from Google AI Studio (aistudio.google.com) — free tier is enough
  GEMINI_MODEL     model id (default below); change it if Google renames models
"""

import os

import requests

from db import connect, now_iso

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3.6-flash"
TIMEOUT_S = 30

PRIORITY = {"Critical": "P1 - repair within 48 hours", "High": "P2 - repair within 7 days",
            "Medium": "P3 - repair within 30 days", "Low": "P4 - inspect and schedule"}


def ticket_facts(hazard, municipality, office, distance_m, min_detections=None):
    """The ONLY information the model is given — all of it computed by the system."""
    return {
        "municipality": municipality["name"],
        "assigned_office": office["name"] if office else f"{municipality['name']} Municipal Office",
        "office_contact": (office or {}).get("contact") or "",
        "raised_because": (f"detected {hazard['detection_count']} times "
                           f"(threshold {min_detections})") if min_detections else None,
        "distance_to_office_km": round(distance_m / 1000, 2) if distance_m is not None else None,
        "latitude": round(hazard["lat"], 6),
        "longitude": round(hazard["lon"], 6),
        "map_link": f"https://www.openstreetmap.org/?mlat={hazard['lat']:.6f}&mlon={hazard['lon']:.6f}#map=19/{hazard['lat']:.6f}/{hazard['lon']:.6f}",
        "severity_percent": hazard["severity_pct"],
        "severity_tier": hazard["severity_tier"],
        "priority": PRIORITY.get(hazard["severity_tier"], "P3"),
        "detections": hazard["detection_count"],
        "confirming_vehicles": len(hazard["confirmed_by_vehicles"]),
        "first_seen_utc": hazard.get("first_seen"),
        "last_seen_utc": hazard.get("last_seen"),
        "reopened_after_repair_on": hazard.get("repaired_at") if hazard.get("status") == "reopened" else None,
        "road_verified_public": hazard.get("road_verified", True),
    }


def build_prompt(facts):
    lines = "\n".join(f"- {k}: {v}" for k, v in facts.items() if v not in (None, ""))
    return (
        "You write pothole repair work orders for an Indian municipal engineering office.\n"
        "Write a concise, formal repair ticket using ONLY the facts below. Do not invent "
        "road names, measurements, causes or people. If something is unknown, leave it out.\n\n"
        "Format exactly:\n"
        "SUBJECT: <one line>\n"
        "PRIORITY: <use the given priority>\n"
        "ASSIGNED TO: <assigned_office>\n"
        "LOCATION: <coordinates and map link>\n"
        "DESCRIPTION: <2-3 sentences: severity, how many detections/vehicles, dates, why the "
        "ticket was raised (raised_because); "
        "if reopened_after_repair_on is present, state clearly that the earlier repair failed>\n"
        "RECOMMENDED ACTION: <2-3 short bullet points appropriate to the severity tier>\n\n"
        f"FACTS:\n{lines}\n"
    )


def template_ticket(f):
    reopened = (f"\nNOTE: This location was marked repaired on {f['reopened_after_repair_on']} "
                "but potholes are still being detected; the earlier repair appears to have failed.")\
        if f.get("reopened_after_repair_on") else ""
    actions = {
        "Critical": "- Barricade/mark the hazard immediately\n- Full-depth patch repair\n- Re-inspect after 7 days",
        "High": "- Mark the hazard\n- Patch repair (cold or hot mix)\n- Re-inspect after 14 days",
        "Medium": "- Schedule patching in the next maintenance cycle\n- Monitor for growth",
    }.get(f["severity_tier"], "- Inspect on site and schedule if needed")
    return (
        f"SUBJECT: {f['severity_tier']} pothole reported in {f['municipality']}\n"
        f"PRIORITY: {f['priority']}\n"
        f"ASSIGNED TO: {f['assigned_office']}"
        + (f" ({f['distance_to_office_km']} km away)" if f.get("distance_to_office_km") is not None else "") + "\n"
        f"LOCATION: {f['latitude']}, {f['longitude']} - {f['map_link']}\n"
        f"DESCRIPTION: Automated road monitoring detected a pothole with severity "
        f"{f['severity_percent']}% ({f['severity_tier']}), based on {f['detections']} detection(s) "
        f"from {f['confirming_vehicles']} vehicle(s) between {f['first_seen_utc']} and {f['last_seen_utc']} (UTC)."
        + (f" Ticket raised automatically: {f['raised_because']}." if f.get("raised_because") else "")
        + f"{reopened}\n"
        f"RECOMMENDED ACTION:\n{actions}"
    )


def call_gemini(prompt, api_key, model):
    resp = requests.post(
        GEMINI_URL.format(model=model),
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json={"contents": [{"parts": [{"text": prompt}]}],
              # Gemini 3 models "think" before answering, and those thinking tokens count
              # against maxOutputTokens — so leave plenty of room or the ticket gets cut off.
              "generationConfig": {"temperature": 0.2, "maxOutputTokens": 2048}},
        timeout=TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json()
    cand = data["candidates"][0]
    if cand.get("finishReason") == "MAX_TOKENS":
        raise ValueError("ticket was cut off (MAX_TOKENS)")
    # skip any "thought" parts; keep only the answer text
    text = "".join(p.get("text", "") for p in cand["content"]["parts"]
                   if not p.get("thought")).strip()
    if not text:
        raise ValueError("empty response")
    return text


def draft_ticket(facts):
    """Returns (text, generator). Falls back to the template on any Gemini problem."""
    api_key = os.environ.get("GEMINI_API_KEY")
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    if api_key:
        try:
            return call_gemini(build_prompt(facts), api_key, model), f"gemini:{model}"
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            print(f"[ticketing] Gemini failed ({type(e).__name__}: {e}) — using template")
    return template_ticket(facts), "template"


def save_ticket(municipality_id, hazard, office, distance_m, text, generator):
    row = {"municipality_id": municipality_id, "lat": hazard["lat"], "lon": hazard["lon"],
           "office_name": office["name"] if office else None, "distance_m": distance_m,
           "severity_pct": hazard["severity_pct"], "severity_tier": hazard["severity_tier"],
           "text": text, "generator": generator, "created_at": now_iso()}
    with connect() as conn:
        conn.execute(
            """INSERT INTO tickets (municipality_id, lat, lon, office_name, distance_m, severity_pct,
                                    severity_tier, text, generator, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            tuple(row[k] for k in ("municipality_id", "lat", "lon", "office_name", "distance_m",
                                   "severity_pct", "severity_tier", "text", "generator", "created_at")))
    return row


def list_tickets(municipality_id):
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, lat, lon, office_name, distance_m, severity_pct, severity_tier, text,
                      generator, created_at FROM tickets WHERE municipality_id = ?
               ORDER BY id DESC""", (municipality_id,)).fetchall()
    return [dict(r) for r in rows]
