# Deploying EcoRoads (free) + the downloadable edge node

The result is a single web address, for example `https://ecoroads-xxxx.onrender.com`:

| Address | What it is |
|---|---|
| `https://…onrender.com/` | the municipal dashboard: register, view, mark repairs |
| `https://…onrender.com/api/…` | the API vehicles sync to (docs at `/docs`) |
| `https://…onrender.com/downloads/EcoRoads-Edge.zip` | the edge node installer for vehicle laptops |

```
 vehicle laptops ── HTTPS ──►  Render (free web service, Docker)  ──►  Neon (free PostgreSQL)
 (EcoRoads-Edge.zip)            FastAPI + dashboard, one container       keeps data across restarts
 municipal staff ── browser ──►  same address, each with a private link
```

**Why two services?** Render's free web service wipes its disk whenever it restarts. The data therefore lives in a free Neon PostgreSQL database. The app switches to PostgreSQL automatically when `DATABASE_URL` is set; locally it keeps using SQLite.

**Free-tier facts worth knowing:**
- Render's free service **sleeps after 15 minutes idle** and takes about a minute to wake up. This doesn't break the edge node: it keeps detections locally and retries until the server is awake.
- Neon's free plan has 1 GB of storage, which is plenty: each pothole report is about 100 bytes.

## 1. Put the project on GitHub (5 min)

1. Install **GitHub Desktop** and sign in.
2. Choose File → *Add local repository…* and pick your `EcoRoads` folder. When it says "not a repository", click **create a repository** there.
3. Check the file list. `venv`, databases, `sessions`, `certs` and `*.pt` must **not** appear; `.gitignore` already excludes them.
4. Click **Commit to main**, then **Publish repository**. Private is fine.

## 2. Create the database on Neon (3 min)

1. Sign up at [neon.com](https://neon.com). No card is needed.
2. Create a project. Pick the region closest to you (e.g. *Asia Pacific – Singapore*).
3. Open **Connect** and copy the connection string. It looks like `postgresql://user:password@ep-xxx.ap-southeast-1.aws.neon.tech/neondb?sslmode=require`.

## 3. Deploy on Render (5 min + build time)

1. Sign up at [render.com](https://render.com) using your GitHub account.
2. Choose **New → Blueprint** and select your EcoRoads repository. Render reads `render.yaml`.
3. When it asks for values:
   - `DATABASE_URL`: paste the Neon string.
   - `ECOROADS_EDGE_DOWNLOAD_URL`: leave empty. The zip is served from the repo, see step 5.
4. Click **Apply** and wait for the build (~5 min), until the service shows **Live**.
5. Open the service → **Environment** and reveal the two keys Render generated:
   - `ECOROADS_ADMIN_KEY`: for you only. It's needed to register municipalities.
   - `ECOROADS_INGEST_KEY`: give it to vehicle operators.

**Check:** open `https://<your-app>.onrender.com/api/health`. It should show `{"status":"ok",…}`.

## 4. Register the municipalities (2 min each)

1. Open `https://<your-app>.onrender.com/` and fill the registration form:
   - click the map to set the centre
   - enter an ID (`ward_a`), a name and a radius
   - enter the **admin key**
2. Click **Register Boundary**. The page shows that municipality's **private link** (`…?muni=ward_a&lock=1#token=…`):
   - Send it to Ward A's staff. It opens their locked dashboard and lets them mark repairs.
   - The token is shown **only once**; the server stores just a hash of it.
   - If it's lost, register the same ID again: that issues a new token and the old one stops working.
3. Repeat for `ward_b`.

**Who can do what:**
- **Anyone** can view hazards; it's civic data.
- **Only the admin key** can register municipalities.
- **Only that municipality's token** can mark its repairs.
- **Only vehicles with the ingest key** can upload.

## 5. Publish the edge node download

After training (`models/best.pt` exists), on your laptop:

```
ecoroads-edge\venv\Scripts\python tools\build_edge_package.py --cloud-url https://<your-app>.onrender.com
```

This writes `ecoroads-dashboard\downloads\EcoRoads-Edge.zip`, which contains the code, your trained model, the installer and the server address. It does **not** contain the vehicle key, because the zip is public.

Commit and push it with GitHub Desktop. Render redeploys automatically, and the dashboard header shows **⬇ Edge node**.

Every time you retrain the model or change the edge code, run the same command again and push.

## 6. Set up a vehicle laptop (any Windows laptop)

1. Install **Python 3.12** from python.org and tick *Add python.exe to PATH*.
2. Download **EcoRoads-Edge.zip** from the dashboard, then extract it.
3. Double-click **INSTALL.bat**, about 3 GB of downloads:
   - It detects an NVIDIA GPU automatically: CUDA build if there is one, CPU build if not.
   - It asks for a vehicle ID (e.g. `bus_12`). The server address is already filled in.
   - It asks for the vehicle key, which is the `ECOROADS_INGEST_KEY`.
4. On every drive, run **START_DRIVE.bat** and connect the phone as described in `PHONE_SETUP.md`, which is included in the zip.

## Updating the server

Push to GitHub and Render redeploys on its own. The data in Neon is untouched.

## Running the same container elsewhere

- **Locally:** `docker compose up --build`.
- **Any VM:** run the following from the repo root, then open port 9000.
  ```
  docker build -f ecoroads-cloud/Dockerfile -t ecoroads .
  docker run -p 9000:9000 -e DATABASE_URL=… -e ECOROADS_ADMIN_KEY=… ecoroads
  ```

## Troubleshooting

| Problem | Fix |
|---|---|
| Render build fails on `psycopg` | Make sure `ecoroads-cloud/requirements.txt` has `psycopg[binary]`. Check the build log. |
| `/api/health` errors with "connection refused / SSL" | The `DATABASE_URL` must be the full Neon string including `?sslmode=require`. |
| First page load takes ~1 minute | The free service was asleep. That's normal. |
| Vehicle sync says 401 | The vehicle key is wrong. Re-run `ecoroads-edge\venv\Scripts\python ecoroads-edge\setup_config.py`. |
| Want demo data on the live server? | `python tools\simulate_fleet.py --cloud https://<your-app>.onrender.com --admin-key … --api-key …`. Note it (re)registers `ward_a`/`ward_b`/`ward_c`, which issues them new tokens, so use it before handing out real ward links. |
| "Mark repaired" asks for a token | Open the municipality's private link (with `#token=`), or paste the token when asked. |
