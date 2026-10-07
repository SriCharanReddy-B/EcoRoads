# Deploying EcoRoads: step-by-step

**What you'll have at the end:** one public address, for example `https://ecoroads-ab12.onrender.com`.

| Address | What it is |
|---|---|
| `/` | Municipal dashboard: register wards, view potholes, mark repairs |
| `/api/…` | Where vehicle laptops upload. Interactive docs at `/docs` |
| `/downloads/EcoRoads-Edge.zip` | Installer for vehicle laptops |

```
 vehicle laptops ── HTTPS ──► Render (free)  ── SQL ──►  Neon (free PostgreSQL)
 municipal staff ── browser ─► same address              data survives restarts
```

**Cost:** ₹0. Neither service needs a card.

**Time:** about 45 minutes the first time.

**Accounts you'll create:** GitHub, Neon and Render. You can sign up for Neon and Render using your GitHub account.

**Write these down as you go** (a notes file, *not* inside the project folder):

| Name | Example | Comes from |
|---|---|---|
| Neon connection string | `postgresql://neondb_owner:…@ep-…neon.tech/neondb?sslmode=require` | Step 2 |
| App address | `https://ecoroads-ab12.onrender.com` | Step 3 |
| Admin key | long random text | Step 3 (keep secret: only you) |
| Vehicle key | long random text | Step 3 (give to vehicle laptops) |
| Ward private links | `https://…/?muni=ward_a&lock=1#token=…` | Step 5 (one per ward) |

---

## Step 0: Check the project is ready (2 min)

1. Open the `EcoRoads` folder in File Explorer. These must exist:
   - `render.yaml`
   - `.gitignore`
   - `ecoroads-cloud\Dockerfile`
   - `ecoroads-dashboard\index.html`
2. Make sure there is no `config.json` containing a real API key that you'd want kept private. It's git-ignored anyway.

## Step 1: Put the project on GitHub (10 min)

Render deploys from a GitHub repository. GitHub Desktop is the easiest way to get it there.

1. Create a GitHub account at **github.com** if you don't have one. Use your personal email, not your college one.
2. Download **GitHub Desktop** from **desktop.github.com**, install it, and sign in: *File → Options → Accounts → Sign in*.
3. Click **File → Add local repository…**, then **Choose…** and select `C:\Users\HP\OneDrive\Desktop\EcoRoads`. Click **Add repository**.
4. It says *"This directory does not appear to be a Git repository."* Click the blue **create a repository** link in that message.
5. In the *Create a New Repository* window:
   - **Name:** `EcoRoads`
   - **Git ignore:** **None**. The project already has its own `.gitignore`; choosing a template would overwrite it.
   - **License:** None
   - Click **Create repository**.
6. Check the **Changes** list on the left:
   - **Should appear:** `render.yaml`, `ecoroads-cloud/…`, `ecoroads-dashboard/…`, `ecoroads-edge/src/…`
   - **Must NOT appear:** `venv`, `.db` files, `sessions`, `certs`, `datasets`, `runs`, `.pt` files. If any of these do appear, stop and tell me.
7. Bottom-left: in **Summary**, type `Initial commit`, then click **Commit to main**.
8. Click **Publish repository** at the top. Tick **Keep this code private** if you like; Render works with private repositories. Click **Publish repository**.
9. **Check:** click *Repository → View on GitHub*. You should see the folders in your browser.

## Step 2: Create the database on Neon (5 min)

1. Go to **neon.com** → **Sign up** → **Continue with GitHub**.
2. Create a project:
   - **Project name:** `ecoroads`
   - **Postgres version:** leave the default
   - **Region:** **AWS Asia Pacific 1 (Singapore)**, the same region as the server in Step 3
   - Click **Create project**.
3. On the project dashboard, click **Connect** (top right).
4. In the *Connect to your database* window:
   - Branch `production` (or `main`), database `neondb`, role `neondb_owner`.
   - The **Connection pooling** toggle can stay on or off; the app works with both.
   - Click **Show password**, then **Copy snippet**. Paste it into your notes as the **Neon connection string**.
   - It must start with `postgresql://` and contain `sslmode=require`.

You don't need to create any tables. The app creates them itself on first start.

## Step 3: Deploy on Render (10 min + ~6 min build)

1. Go to **render.com** → **Get Started** → **GitHub**, and authorise Render.
2. In the Render dashboard, click **+ New** (top right), then **Blueprint**.
3. Under *Connect a repository*:
   - If EcoRoads isn't listed, click **Configure GitHub** (or *Connect account*).
   - On GitHub's page, choose **Only select repositories → EcoRoads → Install / Save**.
   - Back on Render, click **Connect** next to **EcoRoads**.
4. On the blueprint page:
   - **Blueprint Name:** `ecoroads`. **Branch:** `main`.
   - Render lists the service from `render.yaml`: **ecoroads**, *Web Service, Docker, Free, Singapore*.
   - In the **DATABASE_URL** box, paste the Neon connection string.
   - Click **Deploy Blueprint** (or **Apply**).
5. Click the **ecoroads** service, then **Events** or **Logs**, and watch the build. It takes ~5–8 minutes. It's done when you see:
   ```
   Application startup complete.
   ==> Your service is live 🎉
   ```
6. At the top of the service page is its address, e.g. `https://ecoroads-ab12.onrender.com`. Save it as your **App address**.
7. Open **Environment** in the left menu. You'll see `ECOROADS_ADMIN_KEY` and `ECOROADS_INGEST_KEY`, which Render generated:
   - Click the **eye** icon on each and copy the value.
   - Save them as **Admin key** and **Vehicle key**.

> **Is it normal that the free service sleeps?** Yes. It sleeps after 15 minutes with no visitors, and the next visit takes about a minute to wake it. Vehicles simply keep their potholes and retry, so nothing is lost.

## Step 4: Verify the deployment (2 min)

1. In a browser, open `https://<your-app>.onrender.com/api/health`. You should see something like `{"status":"ok","raw_hazard_count":0,"municipality_count":0}`.
2. For the full automatic check, run this on your laptop from the `EcoRoads` folder:
   ```
   ecoroads-edge\venv\Scripts\python tools\deploy_check.py https://<your-app>.onrender.com --api-key <Vehicle key>
   ```
   Every line should say **PASS**. The edge node download shows WARN until Step 6, which is expected.

## Step 5: Register the municipalities (3 min each)

1. Open `https://<your-app>.onrender.com/`. The map loads, and the left panel shows *Register your municipality* with an **Admin key** field.
2. Fill in the form for Ward A:
   - Click on the map at the centre of Ward A's area. A dashed circle appears.
   - **Municipality ID:** `ward_a`. Letters, digits, `_` and `-` only.
   - **Display name:** e.g. `Ward A Municipality`.
   - **Radius:** e.g. `300` metres. The circle grows as you type.
   - **Admin key:** paste it.
   - Click **Register Boundary**.
3. A green box shows **Your municipality's private link**:
   - Click **Copy link** and save it in your notes. It's shown **only once**.
   - Send it to Ward A's staff, or open it on Ward A's laptop. It opens their locked dashboard, showing only their area, and lets them **Mark repaired**.
4. Repeat for **ward_b**, in a different area.

**If a link is lost:** register the same ID again with the same details. That creates a new link, and the old one stops working.

## Step 6: Publish the edge node download (5 min, after training)

This step needs your trained model at `ecoroads-edge\models\best.pt`.

1. On your laptop, from the `EcoRoads` folder:
   ```
   ecoroads-edge\venv\Scripts\python tools\build_edge_package.py --cloud-url https://<your-app>.onrender.com
   ```
   You should see `Built ...\ecoroads-dashboard\downloads\EcoRoads-Edge.zip (~10 MB)` with no WARNING about the model.
2. In GitHub Desktop, the changes list shows `ecoroads-dashboard/downloads/EcoRoads-Edge.zip`. Type the summary `Publish edge node`, click **Commit to main**, then **Push origin**.
3. Render notices the push and redeploys automatically (~5 min, watch **Events**).
4. Reload the dashboard. **⬇ Edge node** now appears in the header. Run `deploy_check.py` again: everything should PASS.

**When you retrain the model or change the edge code:** repeat 1–2.

## Step 7: Set up a vehicle laptop (20 min, mostly downloading)

On any Windows laptop that will ride in a car:

1. Install **Python 3.12** from **python.org/downloads**. On the first installer screen, tick **"Add python.exe to PATH"**.
2. Open your app address, click **⬇ Edge node**, and save **EcoRoads-Edge.zip**. Right-click it → **Extract All…** to e.g. `C:\EcoRoads-Edge`. Keep it outside OneDrive.
3. Double-click **INSTALL.bat** and answer the questions:
   - **Vehicle ID:** unique per car, e.g. `bus_12`.
   - **Server address:** already filled in. Just press Enter.
   - **Vehicle API key:** paste the **Vehicle key**.
   - It finishes with a **check_env** report. You want to see GPU OK if the laptop has an NVIDIA card; CPU also works, just slower.
4. Every drive:
   - Connect the laptop to the phone's hotspot.
   - Run **START_DRIVE.bat**.
   - On the phone, open the `https://…:8443` address it prints and tap **Start streaming**. Full details are in `PHONE_SETUP.md`, which is inside the zip.
   - Allow Python through Windows Firewall, ticking **Private and Public**.
5. The sync window shows `synced N hazard(s)`. The potholes appear on the right ward's dashboard within seconds, or a minute if the server was asleep.

## Step 8: Day-to-day

- **Change server code:** edit, commit and push in GitHub Desktop. Render redeploys by itself, and the database is untouched.
- **See server errors:** Render → ecoroads → **Logs**.
- **Look at the data directly:** Neon → **Tables** (or the **SQL Editor**: `SELECT * FROM hazards ORDER BY id DESC LIMIT 20;`).
- **Demo data on the live server, optional:**
  ```
  python tools\simulate_fleet.py --cloud https://<your-app>.onrender.com --admin-key <Admin key> --api-key <Vehicle key>
  ```
  This creates `ward_a`/`ward_b`/`ward_c` and **gives them new links**. So run it **before** Step 5, or only on a separate test deployment.
- **A key leaked?** Render → Environment → edit the key → **Save, rebuild and deploy**. Then re-run `setup_config.py` on vehicles with the new vehicle key.

## Troubleshooting

| What you see | Cause and fix |
|---|---|
| Render build log: `failed to read dockerfile` | The blueprint needs `dockerfilePath: ./ecoroads-cloud/Dockerfile` and `dockerContext: .`. Make sure `render.yaml` was pushed. |
| Logs: `connection ... failed` / `password authentication failed` | DATABASE_URL is wrong. Copy it again from Neon (with **Show password** on), then Render → Environment → edit → save. |
| Logs: `SSL ... required` | The URL is missing `?sslmode=require`. Use Neon's full string. |
| `/api/health` keeps loading for ~1 min | The service was asleep. That's normal on the free plan. |
| Dashboard: "Not registered: admin key required" | Wrong admin key. Copy it again from Render → Environment. |
| Vehicle sync window: `cloud rejected our API key` | Wrong vehicle key. Run `ecoroads-edge\venv\Scripts\python ecoroads-edge\setup_config.py` in the EcoRoads-Edge folder. |
| Vehicle sync: `[offline] cloud unreachable` for a minute, then OK | The server was waking up. Nothing is lost. |
| "Mark repaired" asks for a token | You opened the plain address, not the ward's private link. Use the link with `#token=`, or paste the token. |
| No **⬇ Edge node** link | The zip wasn't pushed, or Render hasn't finished redeploying. Check GitHub for `ecoroads-dashboard/downloads/EcoRoads-Edge.zip`. |

## Running the same container elsewhere (optional)

The Render setup is just a Docker container, so it runs on any machine with Docker.

- **On your laptop:** run `docker compose up --build`, then open `http://localhost:9000`.
- **On any VM:** from the repo root, run:
  ```
  docker build -f ecoroads-cloud/Dockerfile -t ecoroads .
  docker run -p 9000:9000 -e DATABASE_URL=... -e ECOROADS_ADMIN_KEY=... -e ECOROADS_INGEST_KEY=... ecoroads
  ```
