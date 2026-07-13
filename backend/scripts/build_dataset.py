"""Build the working dataset from REAL public data (with graceful fallback).

This replaces the old fully-synthetic sample with real parcel boundaries so the
map shows actual land parcels you can click and analyze:

  - parcels    : REAL  - Travis Central Appraisal District (TCAD) via the
                          Travis County public ArcGIS FeatureServer.
  - wetlands   : REAL  - USFWS National Wetlands Inventory (falls back to a
                          synthetic blob if the service is unreachable).
  - floodplain : FEMA National Flood Hazard Layer if reachable, else a
                          synthetic creek corridor anchored to the parcel area.
  - transmission_lines / buildings : synthesized and anchored to the real
                          parcels (no simple free county-wide source; buildings
                          are placed inside real parcels so setbacks apply).

Everything is written as GeoJSON in EPSG:4326.

Run:  python scripts/build_dataset.py
      python scripts/build_dataset.py --bbox -97.66 30.21 -97.645 30.225
"""

from __future__ import annotations

import argparse
import json
import math
import random
import urllib.parse
import urllib.request
from pathlib import Path

from pyproj import Transformer
from shapely.geometry import LineString, box, mapping, shape
from shapely.ops import transform as shp_transform
from shapely.ops import unary_union

random.seed(4827)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UTM14N = "EPSG:32614"
WGS84 = "EPSG:4326"

# Default study area: Volente, near Lake Travis (NW Travis County, TX) - ~38
# real parcels, a clean mix of ~1-30 acre lots plus one large tract, real
# irregular boundaries and Polygon/MultiPolygon, no municipal ROW junk.
DEFAULT_BBOX = (-97.87, 30.43, -97.855, 30.445)

# Parcels whose bounding box spans more than this (degrees, ~3.3 km) are almost
# always municipal right-of-way / aggregated multipolygons, not real lots. We
# drop them so the map isn't dominated by a single sprawling ROW parcel.
MAX_PARCEL_SPAN_DEG = 0.03

PARCELS_URL = (
    "https://services1.arcgis.com/HGcSYZ5bvjRswoCb/ArcGIS/rest/services/"
    "TCAD_Parcels_Dec_2025/FeatureServer/0/query"
)
WETLANDS_URL = (
    "https://fwspublicservices.wim.usgs.gov/wetlandsmapservice/rest/services/"
    "Wetlands/MapServer/0/query"
)
FEMA_URL = "https://hazards.fema.gov/gis/nfhl/rest/services/public/NFHL/MapServer/28/query"

_to_utm = Transformer.from_crs(WGS84, UTM14N, always_xy=True)
_to_wgs = Transformer.from_crs(UTM14N, WGS84, always_xy=True)


def to_utm(geom):
    return shp_transform(lambda x, y, z=None: _to_utm.transform(x, y), geom)


def to_wgs(geom):
    return shp_transform(lambda x, y, z=None: _to_wgs.transform(x, y), geom)


def esri_query(url: str, bbox, out_fields: str = "*", timeout: int = 60) -> dict:
    params = {
        "where": "1=1",
        "geometry": ",".join(str(v) for v in bbox),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "outSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": out_fields,
        "returnGeometry": "true",
        "f": "geojson",
    }
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "buildable-land-analysis/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (public gov service)
        return json.load(resp)


def save(name: str, features: list[dict]) -> None:
    fc = {"type": "FeatureCollection", "features": features}
    path = DATA_DIR / f"{name}.geojson"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(fc, fh)
    print(f"  wrote {name}.geojson ({len(features)} features)")


def feature_utm(geom_utm, props) -> dict:
    return {"type": "Feature", "properties": props, "geometry": mapping(to_wgs(geom_utm))}


# --- real layers -----------------------------------------------------------

def fetch_parcels(bbox) -> list[dict]:
    print("parcels: TCAD (real)…")
    gj = esri_query(PARCELS_URL, bbox, "geo_id,py_owner_name,tcad_acres,situs_address")
    feats = []
    dropped = 0
    for i, f in enumerate(gj.get("features", [])):
        if not f.get("geometry"):
            continue
        geom = shape(f["geometry"])
        minx, miny, maxx, maxy = geom.bounds
        if (maxx - minx) > MAX_PARCEL_SPAN_DEG or (maxy - miny) > MAX_PARCEL_SPAN_DEG:
            dropped += 1  # sprawling ROW / degenerate multipolygon
            continue
        p = f.get("properties") or {}
        p["parcel_id"] = str(p.get("geo_id") or f"P-{i:04d}")
        feats.append({"type": "Feature", "properties": p, "geometry": f["geometry"]})
    print(f"  {len(feats)} real parcels (dropped {dropped} ROW/oversized)")
    return feats


def fetch_wetlands(bbox) -> list[dict] | None:
    try:
        print("wetlands: USFWS NWI (real)…")
        # The NWI layer is a join, so fields come back prefixed (Wetlands.*).
        # Request all fields, then slim to the useful ones.
        gj = esri_query(WETLANDS_URL, bbox, "*")
        feats = []
        for f in gj.get("features", []):
            if not f.get("geometry"):
                continue
            p = f.get("properties") or {}
            feats.append(
                {
                    "type": "Feature",
                    "properties": {
                        "nwi_code": p.get("Wetlands.ATTRIBUTE") or p.get("ATTRIBUTE"),
                        "wetland_type": p.get("Wetlands.WETLAND_TYPE") or p.get("WETLAND_TYPE"),
                        "acres": p.get("Wetlands.ACRES") or p.get("ACRES"),
                    },
                    "geometry": f["geometry"],
                }
            )
        if feats:
            print(f"  {len(feats)} real wetland features")
            return feats
        print("  no wetlands returned; will synthesize")
    except Exception as exc:  # noqa: BLE001
        print(f"  USFWS unreachable ({exc}); will synthesize")
    return None


def fetch_floodplain(bbox) -> list[dict] | None:
    try:
        print("floodplain: FEMA NFHL (real)…")
        gj = esri_query(FEMA_URL, bbox, "FLD_ZONE,ZONE_SUBTY", timeout=30)
        feats = [f for f in gj.get("features", []) if f.get("geometry")]
        if feats:
            print(f"  {len(feats)} real FEMA flood features")
            return feats
        print("  no FEMA features returned; will synthesize")
    except Exception as exc:  # noqa: BLE001
        print(f"  FEMA unreachable ({exc}); will synthesize")
    return None


# --- synthetic fallbacks (anchored to the real parcel area) ----------------

def _bounds_utm(parcels: list[dict]):
    geoms = [to_utm(shape(f["geometry"])) for f in parcels]
    u = unary_union(geoms)
    return u  # union of all parcels in UTM


def synth_floodplain(parcels: list[dict]) -> list[dict]:
    u = _bounds_utm(parcels)
    minx, miny, maxx, maxy = u.bounds
    # A creek corridor cutting diagonally across the parcel block.
    creek = LineString(
        [
            (minx - 50, miny + (maxy - miny) * 0.25),
            (minx + (maxx - minx) * 0.5, miny + (maxy - miny) * 0.55),
            (maxx + 50, miny + (maxy - miny) * 0.85),
        ]
    )
    band = creek.buffer(70, cap_style=2)
    return [feature_utm(band, {"fema_zone": "AE (synthetic)", "source": "synthesized corridor"})]


def synth_wetlands(parcels: list[dict]) -> list[dict]:
    u = _bounds_utm(parcels)
    cx, cy = u.centroid.x, u.centroid.y
    ring = []
    for i in range(22):
        ang = (i / 22) * 2 * math.pi
        rad = 90 + 35 * random.uniform(-1, 1)
        ring.append((cx + rad * math.cos(ang), cy + rad * math.sin(ang)))
    from shapely.geometry import Polygon

    blob = Polygon(ring).buffer(0)
    return [feature_utm(blob, {"wetland_type": "Freshwater Emergent (synthetic)"})]


def synth_transmission(parcels: list[dict]) -> list[dict]:
    u = _bounds_utm(parcels)
    minx, miny, maxx, maxy = u.bounds
    x = minx + (maxx - minx) * 0.6
    line = LineString([(x, miny - 60), (x + 40, (miny + maxy) / 2), (x + 90, maxy + 60)])
    return [feature_utm(line, {"voltage_kv": 138, "operator": "Synthesized ROW"})]


def synth_buildings(parcels: list[dict]) -> list[dict]:
    feats = []
    # Put a footprint near the centroid of the larger parcels.
    sized = sorted(
        parcels,
        key=lambda f: to_utm(shape(f["geometry"])).area,
        reverse=True,
    )
    for i, f in enumerate(sized[:6], 1):
        g = to_utm(shape(f["geometry"]))
        c = g.centroid
        w, h = 40, 28
        b = box(c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2)
        if b.intersects(g):
            feats.append(feature_utm(b.intersection(g), {"bldg_id": f"B-{i:03d}", "use": "structure"}))
    return feats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bbox", nargs=4, type=float, default=list(DEFAULT_BBOX),
                    metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    args = ap.parse_args()
    bbox = tuple(args.bbox)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    parcels = fetch_parcels(bbox)
    if not parcels:
        raise SystemExit("No parcels fetched - aborting.")
    save("parcels", parcels)

    wetlands = fetch_wetlands(bbox) or synth_wetlands(parcels)
    save("wetlands", wetlands)

    floodplain = fetch_floodplain(bbox) or synth_floodplain(parcels)
    save("floodplain", floodplain)

    save("transmission_lines", synth_transmission(parcels))
    save("buildings", synth_buildings(parcels))
    print("done.")


if __name__ == "__main__":
    main()
