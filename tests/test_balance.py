"""Rain, depletion, trigger, gross depth, and runtime."""

import pytest

from engine.balance import (
    application_rate_mm_h,
    depletion_mm,
    drip_application_rate_mm_h,
    effective_rain_mm,
    gross_depth_mm,
    runtime_h,
    trigger_irrigation,
)
from engine.models import Block, SystemParams


def test_effective_rain_threshold() -> None:
    # P < 5 mm → 0. P = 5 mm → 0.8 * 5 = 4 mm. P = 10 mm → 8 mm.
    assert effective_rain_mm(0.0) == 0.0
    assert effective_rain_mm(4.9) == 0.0
    assert effective_rain_mm(5.0) == pytest.approx(4.0)
    assert effective_rain_mm(10.0) == pytest.approx(8.0)


def test_depletion_rain_larger_than_deficit_clamps_at_zero() -> None:
    # Dr = clamp(10 - 20 - 0 + 3, 0, 100) = clamp(-7, 0, 100) = 0.
    assert depletion_mm(10, 20, 0, 3, 100) == 0.0


def test_depletion_rain_and_irrigation_both_exceed_deficit() -> None:
    # Dr = clamp(5 - 30 - 10 + 2, 0, 100) = clamp(-33, 0, 100) = 0.
    assert depletion_mm(5, 30, 10, 2, 100) == 0.0


def test_depletion_clamps_at_taw() -> None:
    # Dr = clamp(90 - 0 - 0 + 20, 0, 100) = clamp(110, 0, 100) = 100.
    assert depletion_mm(90, 0, 0, 20, 100) == 100.0


def test_depletion_ordinary_day() -> None:
    # Dr = 40 - 8 - 10 + 5 = 27 mm, inside (0, TAW).
    assert depletion_mm(40, 8, 10, 5, 100) == pytest.approx(27.0)


def test_trigger_at_exact_raw_refills_to_field_capacity() -> None:
    # Forecast Dr == RAW (22 mm) → irrigate. Net depth is 22 mm.
    irrigate, net_mm = trigger_irrigation(22.0, 22.0)
    assert irrigate is True
    assert net_mm == pytest.approx(22.0)


def test_trigger_just_below_raw_does_not_irrigate() -> None:
    irrigate, net_mm = trigger_irrigation(21.9, 22.0)
    assert irrigate is False
    assert net_mm == 0.0


def test_drip_rate_gross_and_runtime() -> None:
    # rate = 1.6 L/h / (0.40 m * 1.00 m) = 4 mm/h.
    # gross = 18 mm / 0.90 = 20 mm. runtime = 20 / 4 = 5 h.
    rate = drip_application_rate_mm_h(1.6, 0.40, 1.00)
    assert rate == pytest.approx(4.0)
    assert gross_depth_mm(18.0, 0.90) == pytest.approx(20.0)
    assert runtime_h(20.0, 4.0) == pytest.approx(5.0)


def test_sprinkler_gross_and_runtime() -> None:
    # gross = 15 mm / 0.75 = 20 mm. runtime = 20 mm / 8 mm/h = 2.5 h.
    assert gross_depth_mm(15.0, 0.75) == pytest.approx(20.0)
    assert runtime_h(20.0, 8.0) == pytest.approx(2.5)


def test_zero_depth_has_no_runtime() -> None:
    assert gross_depth_mm(0.0, 0.90) == 0.0
    assert runtime_h(0.0, 4.0) == 0.0


def test_application_rate_for_drip_and_pivot() -> None:
    drip = Block(
        farm_id="farm-1",
        name="North",
        area_ha=1.0,
        crop="potato",
        planting_date="2026-03-01",
        soil_type="loam",
        system="drip",
        system_params=SystemParams(
            emitter_flow_lph=2.0,
            emitter_spacing_m=0.5,
            lateral_spacing_m=1.0,
        ),
    )
    # 2 L/h / (0.5 m * 1.0 m) = 4 mm/h.
    assert application_rate_mm_h(drip) == pytest.approx(4.0)

    pivot = Block(
        farm_id="farm-1",
        name="North",
        area_ha=1.0,
        crop="potato",
        planting_date="2026-03-01",
        soil_type="loam",
        system="pivot",
        system_params=SystemParams(application_rate_mm_h=8.0),
    )
    assert application_rate_mm_h(pivot) == pytest.approx(8.0)
