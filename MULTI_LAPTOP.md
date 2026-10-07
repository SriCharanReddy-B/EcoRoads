# Three laptops: 1 detector + 2 municipalities

This is how the system would really be deployed: the vehicle, the central server, and each municipality's office are separate machines.

```
 Laptop 1: DETECTOR (in the car)        Laptop 2: WARD A  (+ hosts server)      Laptop 3: WARD B
 phone ─► capture_detect.py --phone     cloud API :9000  (routing, clustering)   just a browser:
          local SQLite (offline-first)  dashboard :8080                          dashboard locked
          sync_worker.py ──── HTTP ───► ① which ward's circle? ② public road?    to Ward B
                                        ③ store ─► Ward A dashboard  ◄── HTTP ──  sees ONLY Ward B
                                                    (locked to Ward A)            potholes
```

- **Laptop 2** does two jobs: it runs the shared server, and it is Ward A's office. The server could also run on a 4th machine; nothing changes.
- **Laptop 3** needs **nothing installed**. It just opens a link in a browser.
- **Routing happens on the server.** A pothole inside Ward A's circle shows up **only** on Ward A's laptop, and the same for Ward B. Neither dashboard filters anything itself.

## Setup (all three on the same Wi-Fi or phone hotspot)

**Laptop 2, the host:**

1. Run `SETUP.bat` once.
2. Run `HOST.bat`. It starts the server and prints the address the detector should use, plus one ready-made link per municipality.
3. Allow Python through Windows Firewall (Private **and** Public) when asked. Otherwise the other laptops can't connect.

**Municipal areas.** Choose one of two ways:
- **Let each municipality register itself (best story).** On Laptop 2 and Laptop 3, open the "Register a new municipality" link that HOST printed. Click the map to set your centre, enter an ID (`ward_a` / `ward_b`) and a radius, then click **Register Boundary**. HOST then prints a locked link for each one.
- **Automatic.** Run `HOST.bat --zones 2`. It splits the route of your latest recorded drive into Ward A (first half) and Ward B (second half).

**Locked links.** Open each ward's locked link on its own laptop, e.g.:
```
http://192.168.43.20:8080/index.html?api=http://192.168.43.20:9000&muni=ward_b&lock=1&refresh=3
```
In locked mode the dashboard:
- shows only that municipality's boundary and potholes
- has no switcher and no registration form
- shows the municipality's name in the title

**Laptop 1, the detector:**
- **Classroom (replay a recorded drive):** run `DEMO.bat --remote-cloud http://192.168.43.20:9000`.
- **Real drive:** set `"cloud_url": "http://192.168.43.20:9000"` in `ecoroads-edge\config.json`, then run `DETECTOR.bat`.

## Classroom demo with three laptops (about 5 minutes)

1. **Laptops 2 and 3 on the projector or side by side,** each showing its own locked dashboard. Both start empty.
2. **Laptop 1 runs the replay.** The detector window shows potholes being found. Within seconds, potholes from the first half of the route pop up on **Ward A only**, then the second half on **Ward B only**.
3. **Talking point:** *"The car doesn't know about municipalities. It just reports location and severity. The server decides who is responsible, and checks that the road is public, using OpenStreetMap."*
4. **Offline-first:** disconnect Laptop 1's Wi-Fi mid-replay. Its window shows `pending sync` growing. Reconnect it, and everything appears on the right laptops.
5. **Accountability:** Ward B clicks **Mark repaired** on a pothole. It disappears only from Ward B's list. If a vehicle detects it there again, it comes back as **REOPENED**.

## Real world: car on the road, municipalities in their offices

The car and the offices aren't on the same Wi-Fi. There are two ways to handle that.

**1. Offline-first (simplest, and it's the point of the design).**
- **During the drive:** the detector logs everything locally, without any server connection.
- **Afterwards:** when the detector laptop rejoins the network the host is on (e.g. campus Wi-Fi), `sync_worker` uploads the whole drive automatically. Both wards then see their potholes.

**2. Live over mobile data (optional).**
- Make the host reachable from the internet with a free tunnel, for example [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/). Run `cloudflared tunnel --url http://localhost:9000` on the host. It prints an `https://….trycloudflare.com` address.
- Put that address in the detector's `cloud_url`, and in the dashboards' `?api=` parameter.
- The free address changes every time the tunnel restarts.
- Use `HOST.bat --api-key SOMESECRET`, and set the same `api_key` in the detector's `config.json`, so only your vehicles can submit data.

## Troubleshooting

| Problem | Fix |
|---|---|
| Laptop 3 can't open the link | Same network? Firewall on Laptop 2 allows Python on Public networks? Try each IP that HOST printed. |
| Detector says "cloud unreachable" | Same check from Laptop 1: open `http://HOST_IP:9000/api/health` in its browser. Detections are kept safely until it works. |
| A pothole appears on the wrong ward | The circles overlap: the nearest centre wins. Re-register a ward with a smaller radius (same ID, it updates in place). |
| Potholes rejected as "outside every municipality" | Part of the route isn't inside any circle. Enlarge a radius or add a third ward. |
