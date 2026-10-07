# Classroom demo guide

**Goal:** in about 5 minutes, show the whole pipeline live on one laptop: video, detection, offline buffering, sync, municipality routing, the map, and repair accountability.

## Which demo to run

| Situation | Command | Needs |
|---|---|---|
| **Best: you've done a real drive** | `DEMO.bat` | trained model + one recorded drive |
| No drive yet | `DEMO.bat --video demo\demo_clip.mp4` | trained model + clip (see below) |
| Wow factor: live phone in the room | `DEMO.bat --phone` | model + phone on the same hotspot |
| Everything else failed | `DEMO.bat --simulate` | nothing |

Add `--cloud-delay 30` to any of the first three to demonstrate **offline-first**.

**Have three laptops?** Use the multi-laptop demo in [MULTI_LAPTOP.md](MULTI_LAPTOP.md): one detector and two municipalities, each seeing only its own area. It shows the routing far more clearly than one screen.

**Make a clip without a car:** this turns the dataset's validation photos into a "driving" video that the model reliably detects.
```
ecoroads-edge\venv\Scripts\python demo\make_demo_video.py ecoroads-edge\datasets\<your dataset>\valid\images
```

## Day before

- [ ] Run `SETUP.bat` at home with internet. This saves Leaflet locally so the dashboard loads even if college Wi-Fi blocks CDNs.
- [ ] Do a full dry run with the exact command you'll use, on the projector laptop.
- [ ] Keep `DEMO.bat --simulate` ready as a fallback.
- [ ] Charge the phone. Map tiles need internet, so plan to share the phone's hotspot if the room has none.

## Suggested 5-minute script

1. **Problem (30 s).** Potholes cause deaths, reporting is manual and slow, and the worst roads have no signal.
2. **Start (`DEMO.bat --cloud-delay 30`).** The browser opens the municipality dashboard, already zoomed to its zone, and the detector window shows the road.
3. **Edge detection (60 s).** Point at the boxes in the detector window, then the terminal:
   - Each pothole is logged **once**, with its severity.
   - With a recording, it also shows the jolt from the accelerometer.
   - Say: *"Detection, scoring and storage all run on the vehicle. No internet is needed."*
4. **Offline-first (30 s).** For the first 30 s the cloud is offline. Point out `pending sync` growing in the detector window.
5. **Sync + routing (60 s).** When the cloud comes back, the potholes appear on the map within seconds. Explain the two checks the cloud makes:
   - Is the pothole inside this municipality's boundary?
   - Is it on a public road, according to OpenStreetMap?
   Then mention that only 5 numbers leave the car: no images.
6. **Clustering (30 s).** Open a hazard card: the detection count, the vehicles that confirmed it, and the severity tier.
7. **Accountability (45 s).** Click **Mark repaired** on a hazard. It moves to the Repaired list. Explain that if any vehicle detects it there again, it comes back as **REOPENED**: that's evidence the contractor's repair failed. For a live reopened example, run `python tools\simulate_fleet.py --repair-demo` in another terminal.
8. **Close (15 s).** Mention the real-drive results from `drive_report.md`: recall, GPS error, false positives.

## Likely questions, with short answers

- **Why not send video to the cloud?** Bandwidth, privacy, and dead zones. A severity number and a location are enough for the municipality to act.
- **What if two cars see the same pothole?** DBSCAN with haversine distance (15 m) merges them, and confirmation by several vehicles slightly raises the severity.
- **How do you match a jolt to a pothole?**
  - All data shares one clock: the phone's timestamps are mapped to the laptop's clock (`timesync.py`).
  - The wheel reaches the pothole `lookahead / speed` seconds after the camera sees it.
  - `fusion.py` looks for a jolt in that window.
- **What if GPS is bad?** Fixes worse than ±30 m are ignored, and a detection without a position is skipped, not guessed.
