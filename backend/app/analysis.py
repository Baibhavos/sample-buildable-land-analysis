"""Buildable-area computation.

Pipeline (all geometry ops happen in the metric ``working_crs`` so buffer
distances in feet->metres and areas are both accurate):

  1. Project the parcel and every relevant constraint feature.
  2. Buffer each constraint by its configured setback and clip to the parcel.
  3. Hold a regulatory setback in from the parcel boundary.
  4. Apply the user's manual carve-outs (exclude) and restores (add back).
  5. buildable = (parcel - all exclusions) + restores(within parcel)
  6. Attribute the removed area to each category with NO double counting,
     so that:  buildable + sum(removed_by_category) == parcel_area.

The area figures are computed with a planar formula in the LOCAL metric CRS
(UTM 14N by default), which is accurate to <0.1% for a single county.
"""

from __future__ import annotations

from typing import Any

from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .config import FEET_TO_METERS
from .geodata import Feature, load_layers, to_wgs84, to_working

SQM_PER_ACRE = 4046.8564224

# Order matters: overlapping exclusions are attributed to whichever category
# comes first, so the breakdown never double-counts overlapping layers.
CONSTRAINT_ORDER = ["wetlands", "floodplain", "transmission_lines", "buildings"]


def _safe(geom: BaseGeometry) -> BaseGeometry:
    if geom.is_empty:
        return geom
    if not geom.is_valid:
        geom = geom.buffer(0)
    return geom


def acres(geom: BaseGeometry) -> float:
    """Planar area (in the working CRS, i.e. square metres) -> acres.

    The caller guarantees ``geom`` is already in a local metric projection
    (UTM/Albers), so ``geom.area`` is square metres. We convert to acres.
    Web Mercator is intentionally never used here (it would inflate areas by
    ~1/cos(lat)^2). See WRITEUP.md.
    """
    if geom.is_empty:
        return 0.0
    return geom.area / SQM_PER_ACRE


def _load_user_geoms(geojson_list: list[dict[str, Any]], working_crs: str) -> BaseGeometry | None:
    geoms = []
    for gj in geojson_list:
        try:
            g = shape(gj)
        except Exception:
            continue
        g = _safe(g)
        if g.is_empty:
            continue
        geoms.append(to_working(g, working_crs))
    if not geoms:
        return None
    return _safe(unary_union(geoms))


def _constraint_exclusion(
    name: str,
    parcel_w: BaseGeometry,
    setback_m: float,
    working_crs: str,
) -> BaseGeometry | None:
    """Union of one constraint layer, buffered and clipped to the parcel."""
    layer = load_layers().get(name)
    if layer is None:
        return None
    candidates = layer.query(parcel_w_wgs84_bbox(parcel_w, working_crs))
    if not candidates:
        return None
    buffered = []
    for feat in candidates:
        gw = to_working(feat.geometry, working_crs)
        gw = _safe(gw)
        if setback_m > 0:
            gw = gw.buffer(setback_m)
        buffered.append(gw)
    if not buffered:
        return None
    union = _safe(unary_union(buffered))
    clipped = _safe(union.intersection(parcel_w))
    return None if clipped.is_empty else clipped


def parcel_w_wgs84_bbox(parcel_w: BaseGeometry, working_crs: str) -> BaseGeometry:
    """Return the parcel as a WGS84 geometry for spatial-index querying.

    The STRtree indexes are built in WGS84 (the source data CRS), so we query
    with the parcel reprojected back to WGS84.
    """
    return to_wgs84(parcel_w, working_crs)


def _feature(geom_wgs84: BaseGeometry, props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "properties": props, "geometry": mapping(geom_wgs84)}


def analyze(
    parcel_feature: Feature,
    parcel_id: str | None,
    carve_outs: list[dict[str, Any]],
    restores: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    warnings: list[str] = []
    working_crs = cfg["working_crs"]

    parcel_w = _safe(to_working(parcel_feature.geometry, working_crs))
    parcel_area = acres(parcel_w)

    # 1. Constraint exclusions (buffered, clipped to parcel), keyed by category.
    exclusions: dict[str, BaseGeometry] = {}
    labels: dict[str, str] = {}
    for name in CONSTRAINT_ORDER:
        ccfg = cfg["constraints"].get(name)
        if not ccfg or not ccfg.get("enabled", True):
            continue
        labels[name] = ccfg.get("label", name)
        setback_m = float(ccfg.get("setback_ft", 0.0)) * FEET_TO_METERS
        geom = _constraint_exclusion(name, parcel_w, setback_m, working_crs)
        if geom is not None and not geom.is_empty:
            exclusions[name] = geom

    # 2. Regulatory setback held in from the parcel boundary.
    boundary_setback_m = float(cfg.get("boundary_setback_ft", 0.0)) * FEET_TO_METERS
    if boundary_setback_m > 0:
        inner = _safe(parcel_w.buffer(-boundary_setback_m))
        ring = _safe(parcel_w.difference(inner)) if not inner.is_empty else parcel_w
        if not ring.is_empty:
            exclusions["boundary_setback"] = ring
            labels["boundary_setback"] = f"Property-line setback ({cfg.get('boundary_setback_ft')} ft)"

    # 3. Manual carve-outs (user-drawn areas to exclude), clipped to parcel.
    manual = _load_user_geoms(carve_outs, working_crs)
    if manual is not None:
        manual = _safe(manual.intersection(parcel_w))
        if not manual.is_empty:
            exclusions["manual_carveout"] = manual
            labels["manual_carveout"] = "Manual carve-out (user)"

    # 4. Restores (user-drawn add-backs) win over exclusions, clipped to parcel.
    restore = _load_user_geoms(restores, working_crs)
    restore = _safe(restore.intersection(parcel_w)) if restore is not None else None

    # 5. Buildable geometry.
    all_excl = _safe(unary_union(list(exclusions.values()))) if exclusions else None
    buildable = parcel_w if all_excl is None else _safe(parcel_w.difference(all_excl))
    if restore is not None and not restore.is_empty:
        buildable = _safe(buildable.union(restore))
        buildable = _safe(buildable.intersection(parcel_w))

    buildable_area = acres(buildable)

    # 6. Disjoint attribution of the removed area (no double counting).
    #    Walk categories in a fixed priority; each gets only the part not
    #    already claimed by an earlier category and not restored.
    removed_region = _safe(parcel_w.difference(buildable))
    remaining = removed_region
    order = CONSTRAINT_ORDER + ["boundary_setback", "manual_carveout"]
    breakdown = []
    for name in order:
        excl = exclusions.get(name)
        if excl is None or remaining.is_empty:
            continue
        piece = _safe(excl.intersection(remaining))
        a = acres(piece)
        if a <= 1e-9:
            continue
        breakdown.append(
            {
                "category": name,
                "label": labels.get(name, name),
                "acres": round(a, 4),
                "pct_of_parcel": round(100.0 * a / parcel_area, 2) if parcel_area else 0.0,
            }
        )
        remaining = _safe(remaining.difference(piece))

    # Anything removed but unattributed (numerical slivers / overlaps).
    leftover = acres(remaining)
    if leftover > 0.01:
        breakdown.append(
            {
                "category": "other",
                "label": "Other / unclassified",
                "acres": round(leftover, 4),
                "pct_of_parcel": round(100.0 * leftover / parcel_area, 2) if parcel_area else 0.0,
            }
        )

    # --- assemble GeoJSON output (back to WGS84 for the map) ---------------
    buildable_fc = {
        "type": "FeatureCollection",
        "features": [
            _feature(
                to_wgs84(buildable, working_crs),
                {"kind": "buildable", "acres": round(buildable_area, 2)},
            )
        ]
        if not buildable.is_empty
        else [],
    }

    excluded_features = []
    for name in order:
        excl = exclusions.get(name)
        if excl is None or excl.is_empty:
            continue
        excluded_features.append(
            _feature(
                to_wgs84(excl, working_crs),
                {"kind": "excluded", "category": name, "label": labels.get(name, name)},
            )
        )
    excluded_fc = {"type": "FeatureCollection", "features": excluded_features}

    total_check = buildable_area + sum(b["acres"] for b in breakdown)
    if abs(total_check - parcel_area) > 0.5:
        warnings.append(
            f"Totals check: buildable+removed={total_check:.2f} ac vs parcel={parcel_area:.2f} ac"
        )

    return {
        "parcel_id": parcel_id,
        "parcel_acres": round(parcel_area, 2),
        "buildable_acres": round(buildable_area, 2),
        "buildable_acres_rounded": _round_up_acre(buildable_area),
        "breakdown": breakdown,
        "buildable_geojson": buildable_fc,
        "excluded_geojson": excluded_fc,
        "config_used": cfg,
        "warnings": warnings,
    }


def _round_up_acre(a: float) -> int:
    """Headline whole-acre figure, rounded to the nearest whole acre.

    We expose BOTH the precise ``buildable_acres`` (2 dp) and this rounded
    integer. Nearest-acre rounding is the neutral reporting choice; the precise
    value is always available for anyone who needs it.
    """
    return int(round(a))
