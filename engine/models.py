"""Inputs and outputs for one farm block. Numbers are computed elsewhere."""

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

SystemName = Literal["drip", "micro_sprinkler", "sprinkler", "pivot", "surface"]


class Farm(BaseModel):
    """A farm. Recommendations are still computed per block."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    owner_whatsapp: str = Field(min_length=1)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    timezone: str = Field(min_length=1)


class SystemParams(BaseModel):
    """Drip emitters, or a mm/h rate for sprinkler, pivot, micro-sprinkler and surface.

    Leave efficiency empty to use the SPEC default for that system.
    """

    model_config = ConfigDict(extra="forbid")

    efficiency: float | None = Field(default=None, gt=0, le=1)
    emitter_flow_lph: float | None = Field(default=None, gt=0)
    emitter_spacing_m: float | None = Field(default=None, gt=0)
    lateral_spacing_m: float | None = Field(default=None, gt=0)
    application_rate_mm_h: float | None = Field(default=None, gt=0)
    max_runtime_h: float | None = Field(default=None, gt=0)


class Boundary(BaseModel):
    """Field outline as a GeoJSON Polygon in lon/lat (WGS84), e.g. drawn on geojson.io."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]]

    @model_validator(mode="after")
    def _closed_ring(self) -> Self:
        if not self.coordinates:
            raise ValueError("boundary needs at least one ring")
        ring = self.coordinates[0]
        if len(ring) < 4 or ring[0] != ring[-1]:
            raise ValueError("boundary ring must be closed and have at least 3 corners")
        for lon, lat in ring:
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise ValueError("boundary coordinates must be [lon, lat] in degrees")
        return self


class Block(BaseModel):
    """One irrigated crop area. planting_date is season start for perennials."""

    model_config = ConfigDict(extra="forbid")

    farm_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    area_ha: float = Field(gt=0)
    crop: str = Field(min_length=1)
    planting_date: date
    soil_type: str = Field(min_length=1)
    system: SystemName
    system_params: SystemParams
    kr: float = Field(default=1.0, ge=0)
    boundary: Boundary | None = None

    @model_validator(mode="after")
    def _resolve_system(self) -> Self:
        # Imported here so model definitions do not load the yaml catalog at import time.
        from engine.catalog import load_systems

        params = self.system_params
        efficiency = params.efficiency
        if efficiency is None:
            record = load_systems().get(self.system)
            if record is None:
                raise ValueError(f"efficiency is required for system {self.system!r}")
            params = params.model_copy(update={"efficiency": record.efficiency})
            self.system_params = params
        if params.max_runtime_h is None:
            record = load_systems().get(self.system)
            if record is not None and record.max_runtime_h is not None:
                params = params.model_copy(update={"max_runtime_h": record.max_runtime_h})
                self.system_params = params

        if self.system == "drip":
            missing = [
                name
                for name, value in (
                    ("emitter_flow_lph", params.emitter_flow_lph),
                    ("emitter_spacing_m", params.emitter_spacing_m),
                    ("lateral_spacing_m", params.lateral_spacing_m),
                )
                if value is None
            ]
            if missing:
                raise ValueError("drip requires " + ", ".join(missing))
        elif params.application_rate_mm_h is None:
            raise ValueError(f"{self.system} requires application_rate_mm_h")
        return self


class DailyInput(BaseModel):
    """Weather and the irrigation that was actually applied on one date."""

    model_config = ConfigDict(extra="forbid")

    date: date
    et0_mm: float = Field(ge=0)
    rain_mm: float = Field(ge=0)
    irrigation_applied_mm: float = Field(default=0.0, ge=0)


class DailyResult(BaseModel):
    """One day's recommendation and the water-balance terms that explain it."""

    model_config = ConfigDict(extra="forbid")

    date: date
    irrigate: bool
    net_mm: float
    gross_mm: float
    runtime_h: float
    dr_mm: float
    raw_mm: float
    taw_mm: float
    et0_mm: float
    kc: float
    etc_mm: float
    peff_mm: float


class CropRecord(BaseModel):
    """One crop from engine/data/crops.yaml."""

    model_config = ConfigDict(extra="forbid")

    verify: bool
    perennial: bool
    kc_ini: float = Field(ge=0)
    kc_mid: float = Field(ge=0)
    kc_end: float = Field(ge=0)
    zr_min_m: float = Field(gt=0)
    zr_max_m: float = Field(gt=0)
    p: float = Field(gt=0, le=1)
    l_ini: int = Field(ge=0)
    l_dev: int = Field(ge=0)
    l_mid: int = Field(ge=0)
    l_late: int = Field(ge=0)

    @model_validator(mode="after")
    def _root_bounds(self) -> Self:
        if self.zr_min_m > self.zr_max_m:
            raise ValueError("zr_min_m cannot exceed zr_max_m")
        return self


class SystemRecord(BaseModel):
    """One irrigation system from engine/data/systems.yaml."""

    model_config = ConfigDict(extra="forbid")

    verify: bool
    efficiency: float = Field(gt=0, le=1)
    max_runtime_h: float | None = Field(default=None, gt=0)


class SoilRecord(BaseModel):
    """One soil from engine/data/soils.yaml. Water contents are volumetric."""

    model_config = ConfigDict(extra="forbid")

    verify: bool
    theta_fc: float = Field(gt=0, lt=1)
    theta_wp: float = Field(gt=0, lt=1)

    @model_validator(mode="after")
    def _field_capacity_above_wilting(self) -> Self:
        if self.theta_fc <= self.theta_wp:
            raise ValueError("theta_fc must exceed theta_wp")
        return self


class PlanDay(DailyResult):
    """One day of a farm plan: the recommendation plus what the balance assumed was applied.

    dr_mm is depletion before any irrigation that day (compare it with RAW).
    dr_end_mm is depletion after the applied depth. capped means the recommendation
    was cut to the block's max runtime and the rest carries to the next day.
    """

    rain_mm: float
    observed: bool
    capped: bool
    applied_net_mm: float
    applied_source: Literal["logged", "assumed"]
    logged_gross_mm: float | None
    logged_runtime_h: float | None
    dr_end_mm: float
