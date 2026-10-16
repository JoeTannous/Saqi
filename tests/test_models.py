"""Farm and block validation, including the SPEC efficiency defaults."""

from datetime import date

import pytest
from pydantic import ValidationError

from engine.models import Block, Farm, SystemParams


def _block(system: str, params: SystemParams, **overrides: object) -> Block:
    data: dict[str, object] = {
        "farm_id": "farm-1",
        "name": "North",
        "area_ha": 1.5,
        "crop": "potato",
        "planting_date": date(2026, 3, 1),
        "soil_type": "loam",
        "system": system,
        "system_params": params,
    }
    data.update(overrides)
    return Block.model_validate(data)


def test_farm_accepts_a_bekaa_contact() -> None:
    farm = Farm(
        name="Bekaa pilot",
        owner_whatsapp="+96170000000",
        lat=33.85,
        lon=35.90,
        timezone="Asia/Beirut",
    )
    assert farm.lat == pytest.approx(33.85)


def test_farm_rejects_a_latitude_past_the_pole() -> None:
    with pytest.raises(ValidationError):
        Farm(
            name="Bekaa pilot",
            owner_whatsapp="+96170000000",
            lat=91.0,
            lon=35.90,
            timezone="Asia/Beirut",
        )


def test_efficiency_defaults_from_the_spec() -> None:
    drip = _block(
        "drip",
        SystemParams(emitter_flow_lph=2.0, emitter_spacing_m=0.4, lateral_spacing_m=1.0),
    )
    sprinkler = _block("sprinkler", SystemParams(application_rate_mm_h=5.0))
    pivot = _block("pivot", SystemParams(application_rate_mm_h=8.0))
    surface = _block("surface", SystemParams(application_rate_mm_h=6.0))

    assert drip.system_params.efficiency == pytest.approx(0.90)
    assert sprinkler.system_params.efficiency == pytest.approx(0.75)
    assert pivot.system_params.efficiency == pytest.approx(0.85)
    assert surface.system_params.efficiency == pytest.approx(0.60)


def test_explicit_efficiency_is_kept() -> None:
    block = _block(
        "drip",
        SystemParams(
            emitter_flow_lph=2.0,
            emitter_spacing_m=0.4,
            lateral_spacing_m=1.0,
            efficiency=0.80,
        ),
    )
    assert block.system_params.efficiency == pytest.approx(0.80)


def test_micro_sprinkler_requires_an_efficiency() -> None:
    with pytest.raises(ValidationError, match="efficiency is required"):
        _block("micro_sprinkler", SystemParams(application_rate_mm_h=4.0))


def test_drip_requires_emitter_layout() -> None:
    with pytest.raises(ValidationError, match="emitter_flow_lph"):
        _block("drip", SystemParams())


def test_sprinkler_requires_a_rate() -> None:
    with pytest.raises(ValidationError, match="application_rate_mm_h"):
        _block("sprinkler", SystemParams(efficiency=0.75))
