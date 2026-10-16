"""Daily simulation. Potato on loam, planted 2026-03-01, unless a test says otherwise.

Day 0 root zone: Zr = 0.15 m.
TAW = 1000 * (0.25 - 0.12) * 0.15 = 19.5 mm.
RAW = 0.35 * 19.5 = 6.825 mm.
Kc_ini = 0.50 until day 29.
"""

from datetime import date, timedelta

import pytest

from engine.models import Block, DailyInput, SystemParams
from engine.simulate import simulate


def _potato(**overrides: object) -> Block:
    system = str(overrides.pop("system", "drip"))
    params = overrides.pop("system_params", None)
    if params is None:
        if system == "drip":
            params = SystemParams(
                emitter_flow_lph=2.0,
                emitter_spacing_m=0.5,
                lateral_spacing_m=1.0,
            )
        else:
            params = SystemParams(application_rate_mm_h=5.0)
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


def _day(
    offset: int,
    et0_mm: float,
    rain_mm: float = 0.0,
    irrigation_applied_mm: float = 0.0,
) -> DailyInput:
    return DailyInput(
        date=date(2026, 3, 1) + timedelta(days=offset),
        et0_mm=et0_mm,
        rain_mm=rain_mm,
        irrigation_applied_mm=irrigation_applied_mm,
    )


def test_day_zero_below_raw_does_not_irrigate() -> None:
    # ETc = 4 * 0.50 * 1 = 2 mm. Forecast Dr = 0 - 0 + 2 = 2 mm.
    # 2 < 6.825, so no irrigation, and the day ends at 2 mm depletion.
    result = simulate(_potato(), [_day(0, et0_mm=4.0)])[0]

    assert result.kc == pytest.approx(0.50)
    assert result.etc_mm == pytest.approx(2.0)
    assert result.peff_mm == 0.0
    assert result.taw_mm == pytest.approx(19.5)
    assert result.raw_mm == pytest.approx(6.825)
    assert result.irrigate is False
    assert result.net_mm == 0.0
    assert result.gross_mm == 0.0
    assert result.runtime_h == 0.0
    assert result.dr_mm == pytest.approx(2.0)


def test_depletion_carries_forward_and_roots_grow() -> None:
    # Day 0 ends at 2 mm, from the test above.
    # Day 1: end of development is day 30 + 35 - 1 = 64.
    # Zr = 0.15 + (1/64) * (0.50 - 0.15) = 0.15546875 m.
    # TAW = 1000 * (0.25 - 0.12) * 0.15546875 = 20.2109375 mm.
    # RAW = 0.35 * 20.2109375 = 7.073828125 mm.
    # ETc = 2 mm. Forecast = 2 + 2 = 4 mm, still under RAW, so Dr ends at 4 mm.
    results = simulate(_potato(), [_day(0, et0_mm=4.0), _day(1, et0_mm=4.0)])
    day1 = results[1]

    assert day1.taw_mm == pytest.approx(20.2109375)
    assert day1.raw_mm == pytest.approx(7.073828125)
    assert day1.irrigate is False
    assert day1.dr_mm == pytest.approx(4.0)


def test_rain_larger_than_depletion_returns_to_field_capacity() -> None:
    # Start at 8 mm. Rain 20 mm → Peff = 16 mm. ETc = 4 * 0.50 = 2 mm.
    # Dr = clamp(8 - 16 - 0 + 2, 0, 19.5) = clamp(-6, 0, 19.5) = 0.
    result = simulate(_potato(), [_day(0, et0_mm=4.0, rain_mm=20.0)], dr_start_mm=8.0)[0]

    assert result.peff_mm == pytest.approx(16.0)
    assert result.irrigate is False
    assert result.dr_mm == 0.0


def test_depletion_clamps_at_taw_when_etc_exceeds_storage() -> None:
    # Start at 18 mm. ETc = 40 * 0.50 = 20 mm. No rain, nothing applied.
    # Unclamped Dr = 18 + 20 = 38 mm, which is cut back to TAW = 19.5 mm.
    # Forecast is also 19.5 >= 6.825, so the refill depth is 19.5 mm.
    result = simulate(_potato(), [_day(0, et0_mm=40.0)], dr_start_mm=18.0)[0]

    assert result.taw_mm == pytest.approx(19.5)
    assert result.irrigate is True
    assert result.net_mm == pytest.approx(19.5)
    assert result.dr_mm == pytest.approx(19.5)


def test_drip_refill_sets_runtime_and_clears_depletion_when_applied() -> None:
    # Start at 10 mm. ETc = 8 * 0.50 = 4 mm. Forecast = 14 mm.
    # 14 >= 6.825 and 14 < 19.5, so net = 14 mm.
    # Gross = 14 / 0.90 mm. Rate = 2 / (0.5 * 1) = 4 mm/h.
    # Runtime = (14 / 0.90) / 4 h.
    # Applied 14 mm → Dr = 10 - 0 - 14 + 4 = 0.
    result = simulate(
        _potato(),
        [_day(0, et0_mm=8.0, irrigation_applied_mm=14.0)],
        dr_start_mm=10.0,
    )[0]

    assert result.irrigate is True
    assert result.net_mm == pytest.approx(14.0)
    assert result.gross_mm == pytest.approx(14.0 / 0.90)
    assert result.runtime_h == pytest.approx((14.0 / 0.90) / 4.0)
    assert result.dr_mm == 0.0


def test_sprinkler_runtime_uses_rate_and_default_efficiency() -> None:
    # Same 14 mm net as the drip refill. Efficiency default 0.75, rate 5 mm/h.
    # Gross = 14 / 0.75 mm. Runtime = gross / 5 h.
    block = _potato(
        system="sprinkler",
        system_params=SystemParams(application_rate_mm_h=5.0),
    )
    result = simulate(
        block,
        [_day(0, et0_mm=8.0)],
        dr_start_mm=10.0,
    )[0]

    assert block.system_params.efficiency == pytest.approx(0.75)
    assert result.net_mm == pytest.approx(14.0)
    assert result.gross_mm == pytest.approx(14.0 / 0.75)
    assert result.runtime_h == pytest.approx((14.0 / 0.75) / 5.0)


def test_pivot_uses_its_default_efficiency() -> None:
    # Net 14 mm, pivot efficiency 0.85, rate 10 mm/h.
    # Gross = 14 / 0.85. Runtime = gross / 10.
    block = _potato(
        system="pivot",
        system_params=SystemParams(application_rate_mm_h=10.0),
    )
    result = simulate(block, [_day(0, et0_mm=8.0)], dr_start_mm=10.0)[0]

    assert result.gross_mm == pytest.approx(14.0 / 0.85)
    assert result.runtime_h == pytest.approx((14.0 / 0.85) / 10.0)


def test_kr_scales_etc() -> None:
    # ETc = 4 * 0.50 * 0.50 = 1.0 mm. Forecast stays under RAW.
    result = simulate(_potato(kr=0.5), [_day(0, et0_mm=4.0)])[0]
    assert result.etc_mm == pytest.approx(1.0)
    assert result.dr_mm == pytest.approx(1.0)
    assert result.irrigate is False


def test_end_of_season_uses_kc_end_and_full_roots() -> None:
    # Potato season is 30 + 35 + 50 + 30 = 145 days. Day 144 is the last day.
    # Kc_end = 0.75. Roots reached Zr_max on day 64, so Zr = 0.50 m.
    # TAW = 1000 * (0.25 - 0.12) * 0.50 = 65 mm. RAW = 0.35 * 65 = 22.75 mm.
    # ETc = 4 * 0.75 = 3 mm, under RAW, so Dr ends at 3 mm.
    result = simulate(_potato(), [_day(144, et0_mm=4.0)])[0]

    assert result.date == date(2026, 3, 1) + timedelta(days=144)
    assert result.kc == pytest.approx(0.75)
    assert result.taw_mm == pytest.approx(65.0)
    assert result.raw_mm == pytest.approx(22.75)
    assert result.etc_mm == pytest.approx(3.0)
    assert result.irrigate is False
    assert result.dr_mm == pytest.approx(3.0)


def test_date_before_planting_is_rejected() -> None:
    early = DailyInput(date=date(2026, 2, 28), et0_mm=4.0, rain_mm=0.0)
    with pytest.raises(ValueError, match="before planting"):
        simulate(_potato(), [early])


def test_dates_must_increase() -> None:
    with pytest.raises(ValueError, match="increasing date order"):
        simulate(_potato(), [_day(1, et0_mm=4.0), _day(1, et0_mm=4.0)])
