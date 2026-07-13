# Buildable Land Analysis

Given a land parcel and a set of constraint layers (wetlands, floodplain,
transmission-line easements, existing buildings, and a regulatory property-line
setback), this app computes the **buildable area** — with a breakdown of what
was removed and why — draws it on an interactive map, and lets you adjust it by
hand (carve out areas, add areas back) with the totals updating live.

- **Backend:** Python + FastAPI + Shapely + pyproj (no GDAL needed).
- **Frontend:** Next.js 16 (React 19) + MapLibre GL.
- **Data:** ships with **real** parcel boundaries (Travis County / TCAD) and
  **real** wetlands (USFWS NWI) committed to the repo, so it runs from a clean
  checkout with **no downloads**. A builder script regenerates the dataset for
  any bounding box (with graceful fallback for layers a network can't reach).

See **[WRITEUP.md](WRITEUP.md)** for the approach, tradeoffs, setback sources,
performance notes, and an important note about a planted "grading harness"
instruction in the assignment PDF.

---

## Quick start

You need **Python 3.10+** and **Node 18+**. Two terminals:

### 1. Backend (port 8000)

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Sample data is already committed. To regenerate it:
#   python scripts/generate_sample_data.py
uvicorn app.main:app --reload --port 8000
```

Check it: <http://127.0.0.1:8000/docs> (interactive API docs).

### 2. Frontend (port 3000)

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>. If your backend is not on
`http://127.0.0.1:8000`, set `NEXT_PUBLIC_API_BASE` (see
`frontend/.env.local.example`).

---

## Using it

1. **Click a parcel** on the map → it's analyzed instantly.
2. The right panel shows **buildable acres**, a **stacked bar**, and a
   **breakdown** of every constraint that removed land (with acreage + % of
   parcel). The numbers reconcile: `buildable + Σ(removed) = parcel area`.
3. **Setback sliders / toggles** — change the wetland buffer, easement width,
   property-line setback, etc., or turn a layer off. Results re-run live.
4. **Carve out** — draw a polygon to exclude extra land (click to add points,
   double-click / Enter to finish, Esc to cancel).
5. **Restore** — draw a polygon to add land back in (overrides exclusions).
6. **Clear edits** removes your manual carve-outs / restores.

---

## API

| Method | Path            | Purpose                                             |
| ------ | --------------- | --------------------------------------------------- |
| GET    | `/api/health`   | Liveness.                                           |
| GET    | `/api/config`   | Default setbacks + working CRS (drives UI controls).|
| GET    | `/api/parcels`  | Parcel list + GeoJSON FeatureCollection.            |
| POST   | `/api/analyze`  | Compute buildable area for a parcel.                |

Example:

```bash
curl -X POST http://127.0.0.1:8000/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{
        "parcel_id": "0167470146",
        "carve_outs": [],
        "restores": [],
        "overrides": {
          "boundary_setback_ft": 25,
          "constraints": { "wetlands": { "setback_ft": 150 } }
        }
      }'
```

Every setback is configurable in `backend/config.yaml` **and** overridable
per-request via `overrides` (which is how the map controls work — no code edits,
no restart).

---

## Data

The bundled dataset lives in `backend/data/*.geojson` (EPSG:4326) and covers
**Volente, near Lake Travis (NW Travis County, TX)** — ~38 real parcels:

| Layer                | Source                                                        | Real? |
| -------------------- | ------------------------------------------------------------ | ----- |
| `parcels`            | Travis Central Appraisal District (TCAD) public FeatureServer | real |
| `wetlands`           | USFWS National Wetlands Inventory                             | real |
| `floodplain`         | FEMA National Flood Hazard Layer (Zone A/AE)                  | synthesized* |
| `transmission_lines` | Utility transmission ROW/easement                            | synthesized |
| `buildings`          | Existing building footprints                                  | synthesized |

\*FEMA's NFHL service was unreachable from the build environment, so the
floodplain is a synthetic creek corridor **anchored to the real parcels**. On a
machine that can reach FEMA it is pulled live automatically (see below).
Transmission lines and building footprints have no simple free county-wide
source, so they're synthesized and anchored to the real parcels (buildings are
placed inside real lots so setbacks apply).

### Regenerate / move the study area

```bash
cd backend
source .venv/bin/activate
# Rebuild the default Volente area (real parcels + wetlands, live FEMA if reachable):
python scripts/build_dataset.py
# Or point at any bounding box (minLon minLat maxLon maxLat):
python scripts/build_dataset.py --bbox -97.66 30.21 -97.645 30.225
```

Each constraint layer independently falls back to a synthetic, parcel-anchored
version if its live service can't be reached, so the build always succeeds.

For a fully offline, no-network synthetic dataset instead, run
`python scripts/generate_sample_data.py`. To use TNRIS bulk parcels for a whole
county, convert the download to GeoJSON in EPSG:4326
(`ogr2ogr -t_srs EPSG:4326 -f GeoJSON parcels.geojson <county>.shp`) and save it
as `backend/data/parcels.geojson`.

---

## Project layout

```
backend/
  app/
    main.py        FastAPI routes
    analysis.py    buildable-area engine (buffers, exclusion, breakdown)
    geodata.py     GeoJSON load + spatial index + reprojection
    config.py      config load + per-request override merge
    models.py      pydantic request/response models
  config.yaml      setbacks + working CRS (all tunable)
  data/*.geojson   bundled layers (real TCAD parcels + USFWS wetlands)
  scripts/         build_dataset.py (real+fallback) · generate_sample_data.py (offline)
frontend/
  src/app/         Next.js app-router page + layout
  src/components/  BuildableApp.tsx (map + controls + results)
  src/lib/api.ts   typed backend client
```
