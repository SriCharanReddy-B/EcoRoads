# Test-drive checklist

## Before any drive (at your desk)

- [ ] In `ecoroads-edge`, `python check_env.py` shows all OK: CUDA, webcam, model.
- [ ] In `ecoroads-edge` and `ecoroads-cloud`, `python -m pytest tests -q` passes.
- [ ] `python src\capture_detect.py --source <a pothole video>` draws boxes and logs a few potholes, not hundreds.
- [ ] Phone link works at your desk: `REAL_DRIVE.bat`, open the printed address on the phone, all tiles green.
- [ ] The cloud is running with `--host 0.0.0.0` and the dashboard shows "cloud connected".
- [ ] Each vehicle laptop's `config.json` has a unique `vehicle_id` and `cloud_url` set to the server's IP.

## Drive 1: single vehicle, one zone (Week 2)

1. Pre-scout 3–5 real potholes. Note each one's GPS position (Google Maps long-press) and judge its size as S, M or L. This is your **ground truth**.
2. Register one zone (about 300 m radius) in the dashboard that covers them.
3. Set up the car by following `PHONE_SETUP.md`:
   - phone on the windscreen, streaming to the laptop
   - all four tiles on the phone page green
   - `camera_lookahead_m` measured and set in `config.json`
4. Drive at a steady 20–30 km/h over each pothole. Turn the phone's mobile data **off** for the first pass: rows should pile up as "pending sync" with no errors. That's the offline-first proof.
5. Turn data back on. Within 15 s the sync worker should report "synced N".
6. Back home, run `python tools\drive_report.py --ground-truth my_route.csv`. It fills in this table for your report automatically:

| Pothole | Ground-truth size | Detected? | Camera % | Jolt (g) | Final % | GPS error (m) |
|---|---|---|---|---|---|---|

GPS error is the distance between the dashboard marker and your scouted point.

## Drive 2: multiple vehicles, multiple zones (Week 3)

1. Register 2–3 zones, each with a separate dashboard tab or person.
2. Give each laptop a different `vehicle_id` and run 2–3 vehicles over the same route at different times.
3. Expected results:
   - Each pothole shows once, confirmed by several vehicles, with a higher severity.
   - Each zone's dashboard only shows its own potholes.
   - Potholes on private lanes or outside the zones don't appear at all.
4. Mark one pothole repaired without fixing it, then drive over it again. It should come back as **REOPENED**.

## Safety

The driver only drives. A second person watches the laptop, and no one touches the laptop while the car is moving.
