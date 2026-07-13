"""Configuration loading and the request-override merge logic.

Setback distances and the working CRS live in ``config.yaml`` so they can be
changed without touching code. Any of them can additionally be overridden on a
per-request basis (from the map UI) via the ``overrides`` field of the analyze
request, which is what makes the buffers interactively tunable.
"""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

FEET_TO_METERS = 0.3048


@lru_cache(maxsize=1)
def _load_yaml() -> dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def base_config() -> dict[str, Any]:
    """Return a deep copy of the on-disk configuration."""
    return copy.deepcopy(_load_yaml())


def merge_overrides(overrides: dict[str, Any] | None) -> dict[str, Any]:
    """Merge per-request overrides on top of the base config.

    Supported override keys (all optional):
      - working_crs: str
      - boundary_setback_ft: float
      - constraints: { <name>: { enabled?: bool, setback_ft?: float } }
    """
    cfg = base_config()
    if not overrides:
        return cfg

    if "working_crs" in overrides and overrides["working_crs"]:
        cfg["working_crs"] = overrides["working_crs"]

    if overrides.get("boundary_setback_ft") is not None:
        cfg["boundary_setback_ft"] = float(overrides["boundary_setback_ft"])

    for name, patch in (overrides.get("constraints") or {}).items():
        if name not in cfg["constraints"]:
            # Ignore unknown layers rather than 500 - keeps the API forgiving.
            continue
        if patch.get("enabled") is not None:
            cfg["constraints"][name]["enabled"] = bool(patch["enabled"])
        if patch.get("setback_ft") is not None:
            cfg["constraints"][name]["setback_ft"] = float(patch["setback_ft"])

    return cfg
