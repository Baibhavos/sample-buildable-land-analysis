# Buildable Land Analysis

Given a land parcel and a set of constraint layers (wetlands, floodplain,
transmission-line easements, existing buildings, and a regulatory property-line
setback), this app computes the **buildable area** — with a breakdown of what
was removed and why — draws it on an interactive map, and lets you adjust it by
hand (carve out areas, add areas back) with the totals updating live.

- **Backend:** Python + FastAPI + Shapely + pyproj (no GDAL needed).
- **Frontend:** Next.js 16 (React 19) + MapLibre GL.
- **Data:** a small, realistic, intentionally-messy Texas sample dataset ships
  in the repo so it runs from a clean checkout with **no downloads**. Scripts
  are included to pull real USFWS / FEMA layers and to bring in TNRIS parcels.

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
        "parcel_id": "P-002",
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

The bundled sample lives in `backend/data/*.geojson` (EPSG:4326):

| Layer                | Source it stands in for                          |
| -------------------- | ------------------------------------------------ |
| `parcels`            | TNRIS county parcels (<https://data.tnris.org>)  |
| `wetlands`           | USFWS National Wetlands Inventory                |
| `floodplain`         | FEMA National Flood Hazard Layer (Zone A/AE)     |
| `transmission_lines` | Utility transmission ROW/easements               |
| `buildings`          | Existing building footprints                     |

### Use real data

```bash
cd backend
source .venv/bin/activate
# Pulls live USFWS wetlands + FEMA floodplain for a bbox (minLon minLat maxLon maxLat):
python scripts/fetch_real_data.py --bbox -97.35 30.08 -97.28 30.14
```

Parcels come from TNRIS as a bulk county download (shapefile/GeoPackage).
Grab a county with a manageable parcel count, convert to GeoJSON in EPSG:4326
(`ogr2ogr -t_srs EPSG:4326 -f GeoJSON parcels.geojson <county>.shp`), and save
it as `backend/data/parcels.geojson`. Restart the backend.

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
  data/*.geojson   bundled sample layers
  scripts/         sample-data generator + real-data fetcher
frontend/
  src/app/         Next.js app-router page + layout
  src/components/  BuildableApp.tsx (map + controls + results)
  src/lib/api.ts   typed backend client
```
