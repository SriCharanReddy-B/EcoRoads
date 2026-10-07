# Phone on the windscreen → laptop: real-world setup

The phone does the sensing: rear camera, GPS and accelerometer. The laptop on the passenger seat does everything else: YOLO detection on the RTX 4060, severity scoring, local logging, syncing and the dashboard.

There's **no app to install**. The phone opens a web page that the laptop serves itself.

```
 phone (windscreen)                       laptop (passenger seat)
 Chrome/Safari page  ── hotspot Wi-Fi ──► capture_detect.py --phone
  camera 15 fps JPEG        (local link,   ├─ YOLOv8 + severity + debouncer
  GPS 1 Hz                   no data used) ├─ jolt fusion (phone accelerometer)
  motion 60 Hz                             ├─ local SQLite  ─► sync_worker ─► cloud
                                           └─ records the drive to sessions/
```

## One-time setup (at home)

1. **Laptop:** double-click `SETUP.bat`. It installs everything, downloads the map library for offline use, and runs the environment check.
2. **Model:** train it if you haven't (`ecoroads-edge\training\train.py`, see the edge README).
3. **Config:** copy `ecoroads-edge\config.example.json` to `ecoroads-edge\config.json` and set:
   - `"source": "phone"`
   - `"vehicle_id"`: unique per car, e.g. `car_01`
   - `"camera_lookahead_m"`: how far ahead of the bonnet the bottom of the video frame is (measure it once mounted, usually 4–8 m)
4. **Windows Firewall:** the first time `REAL_DRIVE.bat` runs, Windows asks whether Python may use the network. Tick **both Private and Public**, because phone hotspots usually count as "Public". If you missed it: Windows Security → Firewall → Allow an app → Python → tick both.

## Before every drive (2 minutes)

1. Turn on the **phone's hotspot** and connect the laptop to it. Mobile data can be on or off; detection works either way.
2. Run `REAL_DRIVE.bat` on the laptop. It prints an address such as `https://192.168.43.57:8443`.
3. On the phone, open that address in **Chrome** (Android) or **Safari** (iPhone):
   - First time only, you'll see a certificate warning. On Chrome tap **Advanced → Proceed**; on Safari tap **Show Details → visit this website**. The certificate was made by your own laptop (`certs.py`).
   - Tap **Start streaming** and allow **camera**, **location** and, on iPhone, **motion**.
4. Check the four tiles turn green:
   - Camera shows a resolution
   - Sent shows more than 5 fps
   - GPS shows accuracy of ±15 m or better (wait outdoors ~30 s)
   - Motion shows "live"
   - The laptop line shows "receiving … fps"
5. **Mount the phone:**
   - Landscape, low and centred on the windscreen, lens below the wiper sweep.
   - Aim at the road so the bottom of the picture is just past the bonnet and the horizon sits around the top third.
   - A firm suction or dash mount. A wobbly arm shakes the image and adds fake "jolts".
6. **Keep the phone charging** and the page on screen. Browsers pause the camera if you switch apps or the screen locks. The page asks the phone to keep the screen awake.

## During the drive

- Drive 20–40 km/h. Above that, potholes are in view for less than a second.
- Driver drives only. The passenger watches the laptop preview: boxes on potholes, the `logged` counter and `pending sync`.
- To demonstrate offline-first, turn mobile data off for part of the route. `pending sync` grows, nothing is lost, and it all syncs once data is back.
- Press **q** in the preview window (or Ctrl+C) to finish. The drive is saved in `ecoroads-edge\sessions\<date>_<vehicle>\` as video, GPS log, motion log and metadata.

## After the drive

- See the results on the dashboard at `http://localhost:8080`, under your municipality.
- Score the drive against the potholes you scouted:
  ```
  python tools\drive_report.py --ground-truth my_route.csv
  ```
- Re-run detection on exactly the same drive (new model, new thresholds):
  ```
  cd ecoroads-edge\src
  python capture_detect.py --replay latest
  ```
- That recording is also your **classroom demo** (see `DEMO_GUIDE.md`).

## Calibrating the phone's jolt sensor (once)

A phone in a windscreen holder feels bumps differently from an Arduino bolted to the chassis. To calibrate it:

1. Replay a drive with a known big pothole and a known small one.
2. Look at the `jolt X.XX g` values printed for each.
3. Set `jolt_min_g` just above normal road vibration, and `jolt_max_g` at the big pothole's value, in `config.json`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Phone can't open the page | Laptop and phone on the same hotspot? Firewall "Public" ticked? Try every address the laptop printed. |
| "This page must be opened over https://" | Use the `https://` address, not `http://`. |
| Camera "blocked" | Phone settings → browser → Camera/Location → Allow; reload the page. |
| GPS "searching…" or ±50 m | Go outdoors with a clear sky; give it 30–60 s. Fixes worse than ±30 m are ignored (`max_gps_accuracy_m`). |
| Low fps | Lower `phone_width` to 640 or `phone_max_fps` to 10 in `config.json`; keep the phone close to the laptop. |
| Laptop IP changed → certificate warning again | Normal: a new certificate is made for the new IP. Proceed once more. |

## Alternative: IP Webcam app (Android, camera only)

If you'd rather use an app, the "IP Webcam" app streams video at `http://PHONE_IP:8080/video`. Run:

```
python capture_detect.py --source http://PHONE_IP:8080/video
```

GPS then falls back to `gps_mode` in `config.json` (simulated or NMEA), and there's no phone jolt sensing. The browser page is the better option because one page gives camera, GPS and motion on the same clock.
