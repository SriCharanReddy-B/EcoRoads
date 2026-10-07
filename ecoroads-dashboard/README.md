# EcoRoads — Municipality Dashboard

Standalone frontend. Two things a municipality does here:

1. **Register their boundary** — click a point on the map to set the
   center, set a radius (meters), give it an ID and name, hit
   "Register Boundary". This calls the cloud service's
   `POST /api/municipalities` — no boundaries are hardcoded anywhere.
2. **View their hazards** — select their municipality from the
   dropdown to see a severity-sorted map + list of potholes inside
   their registered boundary. Only hazards the cloud service already
   confirmed are on registered public roads appear here — private and
   unpaved roads are filtered out upstream, before this dashboard ever
   sees them.

## Setup

None — it's a single static HTML file with no build step. Just open it
in a browser:

```bash
open index.html
```
(or double-click it, or serve it with `python -m http.server` if your
browser blocks local file fetches to the cloud API — some browsers
restrict `file://` pages making network requests; if you hit CORS/
fetch issues, serve this folder instead: `python -m http.server 8080`
then visit `http://localhost:8080`)

**Requires the cloud service running** at `http://localhost:9000`
(change `CLOUD_URL` at the top of the `<script>` in `index.html` if
your cloud service is deployed elsewhere).

## Repairs and accountability

Every hazard card has a **Mark repaired** button. Once a spot is marked repaired, the hazard moves to the "Repaired" list. If vehicles detect a pothole there **after** the repair date, it comes back with a red **REOPENED** tag, showing the repair didn't hold or wasn't done.

Hazards tagged **road unverified** were accepted while OpenStreetMap was unreachable (the cloud's fail-open rule), so they deserve a quick manual check.

## Pointing at a different cloud server

No need to edit the file. Open `index.html?api=http://192.168.1.20:9000` instead.

## Multi-municipality setup

Each municipality's own staff opens this same `index.html` (or you
deploy one instance per municipality, doesn't matter — it's stateless)
and either:
- Registers their boundary once (first time), or
- Selects their already-registered municipality from the dropdown

All municipalities' boundary circles are drawn faintly on everyone's
map for context, but each dashboard's hazard list/stats only show data
for whichever municipality is selected.

## What you'll see if the cloud service isn't running

A "Could not reach cloud service" message in the sidebar instead of
hazard data — the map itself will still load (it just talks to
OpenStreetMap's public tiles directly), so you can confirm the page
loaded correctly independent of your backend status.
