"""Loading, indexing and reprojecting the geospatial layers.

We deliberately avoid GDAL/geopandas/fiona: the dataset is GeoJSON, so we read
it with the stdlib ``json`` module, build shapely geometries with
``shapely.geometry.shape``, and reproject with ``pyproj`` + ``shapely.ops``.
This keeps the install light (shapely + pyproj wheels only) and reproducible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform
from shapely.strtree import STRtree

from .config import DATA_DIR

WGS84 = "EPSG:4326"

# Layer name -> file. Parcels are the subject; the rest are constraints.
LAYER_FILES = {
    "parcels": "parcels.geojson",
    "wetlands": "wetlands.geojson",
    "floodplain": "floodplain.geojson",
    "transmission_lines": "transmission_lines.geojson",
    "buildings": "buildings.geojson",
}


@dataclass
class Feature:
    geometry: BaseGeometry
    properties: dict[str, Any]


@dataclass
class Layer:
    name: str
    features: list[Feature] = field(default_factory=list)
    _tree: STRtree | None = None
    _geoms: list[BaseGeometry] = field(default_factory=list)

    def build_index(self) -> None:
        self._geoms = [f.geometry for f in self.features]
        self._tree = STRtree(self._geoms) if self._geoms else None

    def query(self, geom: BaseGeometry) -> list[Feature]:
        """Return features whose bbox intersects ``geom`` (broad phase)."""
        if self._tree is None:
            return []
        idx = self._tree.query(geom)
        return [self.features[i] for i in idx]


def _clean(geom: BaseGeometry) -> BaseGeometry:
    """Repair invalid geometry (self-intersections etc.) as real data has."""
    if geom.is_valid:
        return geom
    fixed = geom.buffer(0)
    return fixed


def _read_geojson(path: Path) -> list[Feature]:
    with open(path, "r", encoding="utf-8") as fh:
        gj = json.load(fh)
    feats: list[Feature] = []
    for f in gj.get("features", []):
        geom_json = f.get("geometry")
        if not geom_json:
            continue
        try:
            geom = _clean(shape(geom_json))
        except Exception:
            continue
        if geom.is_empty:
            continue
        feats.append(Feature(geometry=geom, properties=f.get("properties") or {}))
    return feats


@lru_cache(maxsize=1)
def load_layers() -> dict[str, Layer]:
    layers: dict[str, Layer] = {}
    for name, filename in LAYER_FILES.items():
        path = DATA_DIR / filename
        feats = _read_geojson(path) if path.exists() else []
        layer = Layer(name=name, features=feats)
        layer.build_index()
        layers[name] = layer
    return layers


def _parcel_id(props: dict[str, Any], fallback: int) -> str:
    for key in ("parcel_id", "id", "PARCEL_ID", "GEO_ID", "OBJECTID"):
        if key in props and props[key] not in (None, ""):
            return str(props[key])
    return f"parcel-{fallback}"


def list_parcels() -> list[dict[str, Any]]:
    """Lightweight parcel list for the UI (id, area, centroid, bbox)."""
    parcels = load_layers()["parcels"]
    out = []
    for i, f in enumerate(parcels.features):
        pid = _parcel_id(f.properties, i)
        c = f.geometry.centroid
        out.append(
            {
                "parcel_id": pid,
                "properties": f.properties,
                "centroid": [c.x, c.y],
                "bbox": list(f.geometry.bounds),
            }
        )
    return out


def parcels_feature_collection() -> dict[str, Any]:
    parcels = load_layers()["parcels"]
    features = []
    for i, f in enumerate(parcels.features):
        pid = _parcel_id(f.properties, i)
        features.append(
            {
                "type": "Feature",
                "properties": {**f.properties, "parcel_id": pid},
                "geometry": mapping(f.geometry),
            }
        )
    return {"type": "FeatureCollection", "features": features}


def get_parcel(parcel_id: str) -> Feature | None:
    parcels = load_layers()["parcels"]
    for i, f in enumerate(parcels.features):
        if _parcel_id(f.properties, i) == parcel_id:
            return f
    return None


# --- projection helpers ----------------------------------------------------

@lru_cache(maxsize=16)
def _transformer(src: str, dst: str) -> Transformer:
    return Transformer.from_crs(src, dst, always_xy=True)


def project(geom: BaseGeometry, src: str, dst: str) -> BaseGeometry:
    if src == dst:
        return geom
    tf = _transformer(src, dst)
    return shapely_transform(lambda x, y, z=None: tf.transform(x, y), geom)


def to_working(geom: BaseGeometry, working_crs: str) -> BaseGeometry:
    return project(geom, WGS84, working_crs)


def to_wgs84(geom: BaseGeometry, working_crs: str) -> BaseGeometry:
    return project(geom, working_crs, WGS84)
