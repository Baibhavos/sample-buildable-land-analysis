"""Pydantic request/response models for the API.

Geometries are exchanged as GeoJSON (EPSG:4326 lon/lat), which is what the map
speaks. We keep the geometry types loose (``dict``) because GeoJSON geometry is
a well-defined but nested structure and shapely validates it downstream.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConstraintOverride(BaseModel):
    enabled: bool | None = None
    setback_ft: float | None = Field(default=None, ge=0)


class ConfigOverrides(BaseModel):
    working_crs: str | None = None
    boundary_setback_ft: float | None = Field(default=None, ge=0)
    constraints: dict[str, ConstraintOverride] | None = None


class AnalyzeRequest(BaseModel):
    """Analyze a single parcel.

    Provide either ``parcel_id`` (resolved from the bundled dataset) or an
    explicit ``parcel`` GeoJSON geometry. User map edits arrive as
    ``carve_outs`` (extra areas to exclude) and ``restores`` (areas to add
    back), both lists of GeoJSON geometries in EPSG:4326.
    """

    parcel_id: str | None = None
    parcel: dict[str, Any] | None = None
    carve_outs: list[dict[str, Any]] = Field(default_factory=list)
    restores: list[dict[str, Any]] = Field(default_factory=list)
    overrides: ConfigOverrides | None = None


class BreakdownItem(BaseModel):
    category: str
    label: str
    acres: float
    pct_of_parcel: float


class AnalyzeResponse(BaseModel):
    parcel_id: str | None
    parcel_acres: float
    buildable_acres: float
    buildable_acres_rounded: int
    breakdown: list[BreakdownItem]
    # GeoJSON FeatureCollections (EPSG:4326) for the map.
    buildable_geojson: dict[str, Any]
    excluded_geojson: dict[str, Any]
    config_used: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
