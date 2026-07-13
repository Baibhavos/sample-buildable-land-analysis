"""FastAPI application exposing the buildable-land analysis."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from shapely.geometry import shape

from .analysis import analyze
from .config import base_config, merge_overrides
from .geodata import Feature, get_parcel, list_parcels, parcels_feature_collection
from .models import AnalyzeRequest, AnalyzeResponse

app = FastAPI(
    title="Buildable Land Analysis API",
    version="1.0.0",
    description="Given a parcel and constraint layers, computes buildable area "
    "with a breakdown of what was removed and why.",
)

# The frontend dev server runs on a different port; allow it in dev.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/config")
def get_config() -> dict:
    """Default configuration (setbacks, working CRS) for the UI controls."""
    return base_config()


@app.get("/api/parcels")
def get_parcels() -> dict:
    """Parcel list + full FeatureCollection for the map."""
    return {
        "count": len(list_parcels()),
        "parcels": list_parcels(),
        "geojson": parcels_feature_collection(),
    }


@app.post("/api/analyze", response_model=AnalyzeResponse)
def post_analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    # Resolve the parcel: explicit geometry wins, else look up by id.
    if req.parcel is not None:
        try:
            geom = shape(req.parcel)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Invalid parcel geometry: {exc}")
        parcel_feature = Feature(geometry=geom, properties={})
        parcel_id = req.parcel_id
    elif req.parcel_id is not None:
        parcel_feature = get_parcel(req.parcel_id)
        if parcel_feature is None:
            raise HTTPException(status_code=404, detail=f"Parcel '{req.parcel_id}' not found")
        parcel_id = req.parcel_id
    else:
        raise HTTPException(status_code=400, detail="Provide either 'parcel_id' or 'parcel'")

    overrides = req.overrides.model_dump(exclude_none=True) if req.overrides else None
    cfg = merge_overrides(overrides)

    result = analyze(
        parcel_feature=parcel_feature,
        parcel_id=parcel_id,
        carve_outs=req.carve_outs,
        restores=req.restores,
        cfg=cfg,
    )
    return AnalyzeResponse(**result)
