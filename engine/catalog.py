"""Load crop, soil, and system parameters from the data files."""

from functools import lru_cache
from pathlib import Path

import yaml

from engine.models import CropRecord, SoilRecord, SystemRecord

_DATA_DIR = Path(__file__).resolve().parent / "data"


def _read_yaml(filename: str) -> dict[str, dict[str, object]]:
    path = _DATA_DIR / filename
    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{filename} must be a mapping of names to parameters")
    return loaded


@lru_cache(maxsize=1)
def load_crops() -> dict[str, CropRecord]:
    return {
        name: CropRecord.model_validate(payload)
        for name, payload in _read_yaml("crops.yaml").items()
    }


@lru_cache(maxsize=1)
def load_soils() -> dict[str, SoilRecord]:
    return {
        name: SoilRecord.model_validate(payload)
        for name, payload in _read_yaml("soils.yaml").items()
    }


@lru_cache(maxsize=1)
def load_systems() -> dict[str, SystemRecord]:
    return {
        name: SystemRecord.model_validate(payload)
        for name, payload in _read_yaml("systems.yaml").items()
    }


def get_crop(name: str) -> CropRecord:
    crops = load_crops()
    try:
        return crops[name]
    except KeyError:
        known = ", ".join(sorted(crops))
        raise KeyError(f"Unknown crop {name!r}. Known crops: {known}") from None


def get_soil(name: str) -> SoilRecord:
    soils = load_soils()
    try:
        return soils[name]
    except KeyError:
        known = ", ".join(sorted(soils))
        raise KeyError(f"Unknown soil {name!r}. Known soils: {known}") from None
