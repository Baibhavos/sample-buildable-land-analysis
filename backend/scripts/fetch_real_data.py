"""Fetch REAL public constraint layers for a bounding box and write GeoJSON.

This pulls live data from public ArcGIS REST services (no API key, no paid
data) so you can point the app at a real area instead of the bundled sample:

  - Wetlands       : USFWS National Wetlands Inventory MapServer
  - Floodplain     : FEMA National Flood Hazard Layer (S_FLD_HAZ_AR)

Parcels come from TNRIS (https://data.tnris.org) as a bulk county download.
TNRIS is a download portal (shapefile/GeoPackage), not a live query service,
so grab a county with a manageable parcel count, export/convert it to GeoJSON
in EPSG:4326, and save it as ``backend/data/parcels.geojson``. (ogr2ogr:
``ogr2ogr -t_srs EPSG:4326 -f GeoJSON parcels.geojson <county>.shp``)

Usage:
    python scripts/fetch_real_data.py --bbox -97.35 30.08 -97.28 30.14

The --bbox is minLon minLat maxLon maxLat (WGS84). Keep it small; these
services page results and a large bbox can be slow or truncated.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SERVICES = {
    "wetlands": "https://www.fws.gov/wetlandsmapservice/rest/services/Wetlands/MapServer/0/query",
    "floodplain": "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query",
}


def fetch_layer(url: str, bbox: tuple[float, float, float, float]) -> dict:
    params = {
        "where": "1=1",
        "geometry": ",".join(str(v) for v in bbox),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "f": "geojson",
    }
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "buildable-land-analysis/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:  # noqa: S310 (public gov service)
        return json.load(resp)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bbox", nargs=4, type=float, required=True,
                    metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    ap.add_argument("--layers", nargs="*", default=list(SERVICES), choices=list(SERVICES))
    args = ap.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    bbox = tuple(args.bbox)
    for name in args.layers:
        try:
            gj = fetch_layer(SERVICES[name], bbox)
            n = len(gj.get("features", []))
            out = DATA_DIR / f"{name}.geojson"
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(gj, fh)
            print(f"{name}: wrote {n} features -> {out}")
        except Exception as exc:  # noqa: BLE001
            print(f"{name}: FAILED ({exc}). Service may be down or bbox too large.")

    print("\nParcels: download a county from https://data.tnris.org and convert to")
    print("  backend/data/parcels.geojson (EPSG:4326). See this script's docstring.")


if __name__ == "__main__":
    main()
