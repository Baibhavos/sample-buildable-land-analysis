"""Generate a small, realistic, intentionally-messy sample dataset.

The app is designed to run on real TNRIS parcels + USFWS wetlands (see
``fetch_real_data.py`` and the README), but so it also runs from a *clean
checkout with no downloads*, we ship a synthetic dataset that mimics the shape
of real data:

  - parcels of varying size (20-90 acres), including one MULTIPOLYGON,
  - a wetland blob and a self-intersecting ("bowtie") wetland that must be
    repaired with buffer(0) - exactly the kind of invalidity real NWI data has,
  - a diagonal floodplain corridor (a creek),
  - a transmission line crossing the area,
  - building footprints inside several parcels.

Geometry is built in metres (UTM 14N, central Texas ~ Bastrop County) and
written out as GeoJSON in EPSG:4326, which is what GeoJSON expects.

Run:  python scripts/generate_sample_data.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

from pyproj import Transformer
from shapely.affinity import rotate, translate
from shapely.geometry import (
    LineString,
    MultiPolygon,
    Polygon,
    box,
    mapping,
)
from shapely.ops import transform as shapely_transform

random.seed(4827)  # reproducible

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
UTM14N = "EPSG:32614"
WGS84 = "EPSG:4326"

# Base location: central Texas (Bastrop County-ish) in UTM 14N metres.
BASE_E = 660_000.0
BASE_N = 3_333_000.0

_to_wgs84 = Transformer.from_crs(UTM14N, WGS84, always_xy=True)


def to_wgs84(geom):
    return shapely_transform(lambda x, y, z=None: _to_wgs84.transform(x, y), geom)


def jitter(poly: Polygon, amp: float = 12.0) -> Polygon:
    """Nudge vertices so parcels aren't perfect rectangles (like real data)."""
    coords = []
    for x, y in poly.exterior.coords[:-1]:
        coords.append((x + random.uniform(-amp, amp), y + random.uniform(-amp, amp)))
    return Polygon(coords)


def build_parcels():
    """A 5x2 grid of parcels with road gaps; one is a multipolygon."""
    features = []
    cols, rows = 5, 2
    cell_w, cell_h = 460.0, 640.0
    road = 30.0
    pid = 1
    for r in range(rows):
        for c in range(cols):
            x0 = BASE_E + c * (cell_w + road)
            y0 = BASE_N + r * (cell_h + road)
            # vary height a bit so acreage differs
            h = cell_h * random.uniform(0.7, 1.0)
            poly = box(x0, y0, x0 + cell_w, y0 + h)
            poly = jitter(poly)
            if not poly.is_valid:
                poly = poly.buffer(0)
            geom = poly

            # Make parcel #7 a MULTIPOLYGON (a detached triangular remnant).
            if pid == 7:
                remnant = Polygon(
                    [
                        (x0 + cell_w + road, y0 + 40),
                        (x0 + cell_w + road + 150, y0 + 40),
                        (x0 + cell_w + road, y0 + 220),
                    ]
                )
                geom = MultiPolygon([poly, remnant])

            features.append(
                feature(
                    geom,
                    {
                        "parcel_id": f"P-{pid:03d}",
                        "owner": random.choice(
                            ["Lone Star Holdings", "Colorado River LP", "BX Ranch", "City Trust"]
                        ),
                        "zoning": random.choice(["AG", "R-1", "PD", "I-1"]),
                    },
                )
            )
            pid += 1
    return features


def build_wetlands():
    """Two wetlands: one clean blob, one self-intersecting bowtie (invalid)."""
    features = []

    # Clean-ish organic blob overlapping parcels P-002/P-003.
    cx, cy = BASE_E + 1_050, BASE_N + 430
    ring = []
    for i in range(24):
        ang = (i / 24) * 2 * 3.14159265
        rad = 150 + 55 * random.uniform(-1, 1)
        ring.append((cx + rad * _cos(ang), cy + rad * _sin(ang)))
    blob = Polygon(ring)
    if not blob.is_valid:
        blob = blob.buffer(0)
    features.append(feature(blob, {"nwi_code": "PEM1C", "wetland_type": "Freshwater Emergent"}))

    # Deliberately INVALID self-intersecting "bowtie" near P-008 (real NWI
    # data contains these). We store it invalid on purpose; the backend repairs
    # it with buffer(0) at load time.
    bx, by = BASE_E + 1_600, BASE_N + 780
    bowtie = Polygon(
        [(bx, by), (bx + 220, by + 180), (bx + 220, by), (bx, by + 180), (bx, by)]
    )
    features.append(
        feature(bowtie, {"nwi_code": "PFO1A", "wetland_type": "Freshwater Forested", "note": "self-intersecting"})
    )
    return features


def build_floodplain():
    """A diagonal creek corridor buffered into a floodplain band."""
    creek = LineString(
        [
            (BASE_E - 100, BASE_N - 50),
            (BASE_E + 700, BASE_N + 500),
            (BASE_E + 1_500, BASE_N + 700),
            (BASE_E + 2_500, BASE_N + 1_400),
        ]
    )
    band = creek.buffer(120, cap_style=2)
    return [feature(band, {"fema_zone": "AE", "source": "sample floodplain"})]


def build_transmission():
    """A near-vertical transmission line crossing the parcels."""
    line = LineString(
        [
            (BASE_E + 1_350, BASE_N - 100),
            (BASE_E + 1_380, BASE_N + 700),
            (BASE_E + 1_420, BASE_N + 1_450),
        ]
    )
    return [feature(line, {"voltage_kv": 138, "operator": "Sample Electric"})]


def build_buildings():
    """Small building footprints inside several parcels."""
    features = []
    spots = [
        (BASE_E + 120, BASE_N + 120, 45, 30, 15),
        (BASE_E + 600, BASE_N + 200, 30, 60, -20),
        (BASE_E + 1_950, BASE_N + 150, 55, 40, 0),
        (BASE_E + 250, BASE_N + 820, 40, 40, 30),
        (BASE_E + 2_050, BASE_N + 900, 60, 35, 10),
    ]
    for i, (x, y, w, h, ang) in enumerate(spots, 1):
        b = rotate(box(x, y, x + w, y + h), ang, use_radians=False)
        features.append(feature(b, {"bldg_id": f"B-{i:03d}", "use": "structure"}))
    return features


def _cos(a):
    import math

    return math.cos(a)


def _sin(a):
    import math

    return math.sin(a)


def feature(geom_utm, props):
    return {
        "type": "Feature",
        "properties": props,
        "geometry": mapping(to_wgs84(geom_utm)),
    }


def write(name, features):
    fc = {"type": "FeatureCollection", "features": features}
    path = DATA_DIR / f"{name}.geojson"
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(fc, fh)
    print(f"wrote {path}  ({len(features)} features)")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    write("parcels", build_parcels())
    write("wetlands", build_wetlands())
    write("floodplain", build_floodplain())
    write("transmission_lines", build_transmission())
    write("buildings", build_buildings())


if __name__ == "__main__":
    main()
