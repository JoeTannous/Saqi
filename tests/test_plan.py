"""Continuous plan: runtime cap carry-over, logged irrigation, history window.

Potato on loam, drip 2 L/h at 0.5 m x 1.0 m -> 4 mm/h, efficiency 0.90.
Day 0: Zr 0.15 m, TAW = 1000 * 0.13 * 0.15 = 19.5 mm, RAW = 0.35 * 19.5 = 6.825 mm.
Kc_ini = 0.50, so ETc = 0.5 * ET0.
"""

from datetime import date, timedelta

import pytest

from engine.inputs import full_window
from engine.models import Block, DailyInput, Farm, SystemParams
from engine.plan import history_start, plan_days

PLANTED = date(2026, 3, 1)


def _block(max_runtime_h: float | None, crop: str = "potato") -> Block:
    return Block(
        farm_id="farm-1",
        name="North",
        area_ha=1.0,
        crop=crop,
        planting_date=PLANTED,
        soil_type="loam",
        system="drip",
        system_params=SystemParams(
            emitter_flow_lph=2.0,
            emitter_spacing_m=0.5,
            lateral_spacing_m=1.0,
            max_runtime_h=max_runtime_h,
        ),
    )


def _days(et0s: list[float]) -> list[DailyInput]:
    return [
        DailyInput(date=PLANTED + timedelta(days=i), et0_mm=et0, rain_mm=0.0)
        for i, et0 in enumerate(et0s)
    ]


def test_capped_refill_carries_to_following_days() -> None:
    # Cap 1 h -> gross 4 mm -> net 3.6 mm.
    # Day 0: ETc = 8 mm, Dr = 8 >= RAW 6.825 -> net 8, capped to 3.6. Dr end = 4.4.
    # Day 1: ETc 0, Dr = 4.4 < RAW but refill continues -> net 4.4, capped 3.6. Dr end 0.8.
    # Day 2: Dr 0.8 -> net 0.8, gross 0.8 / 0.9 = 0.889, runtime 0.222 h. Dr end 0.
    # Day 3: Dr 0 -> nothing.
    plan = list(plan_days(_block(1.0), _days([16, 0, 0, 0]), today=PLANTED))
    assert [d.capped for d in plan] == [True, True, False, False]
    assert plan[0].dr_mm == pytest.approx(8.0)
    assert plan[0].net_mm == pytest.approx(3.6)
    assert plan[0].runtime_h == pytest.approx(1.0)
    assert plan[0].dr_end_mm == pytest.approx(4.4)
    assert plan[1].irrigate is True
    assert plan[1].net_mm == pytest.approx(3.6)
    assert plan[1].dr_end_mm == pytest.approx(0.8)
    assert plan[2].net_mm == pytest.approx(0.8)
    assert plan[2].gross_mm == pytest.approx(0.8 / 0.9)
    assert plan[2].runtime_h == pytest.approx(0.8 / 0.9 / 4)
    assert plan[2].dr_end_mm == pytest.approx(0.0)
    assert plan[3].irrigate is False


def test_no_cap_refills_in_one_day() -> None:
    plan = list(plan_days(_block(None), _days([16, 0]), today=PLANTED))
    assert plan[0].capped is False
    assert plan[0].net_mm == pytest.approx(8.0)
    assert plan[0].runtime_h == pytest.approx(8.0 / 0.9 / 4)
    assert plan[1].irrigate is False


def test_logged_irrigation_replaces_the_assumption() -> None:
    # Day 0 recommends net 8 mm. The farmer logged 4.5 mm gross -> net 4.05 mm.
    # Dr end = 8 - 4.05 = 3.95 mm.
    logged = {PLANTED: 4.5}
    plan = list(
        plan_days(_block(None), _days([16, 0]), today=PLANTED + timedelta(days=1),
                  logged_gross_mm=logged)
    )
    assert plan[0].net_mm == pytest.approx(8.0)
    assert plan[0].applied_source == "logged"
    assert plan[0].logged_gross_mm == pytest.approx(4.5)
    assert plan[0].applied_net_mm == pytest.approx(4.05)
    assert plan[0].dr_end_mm == pytest.approx(3.95)
    assert plan[1].applied_source == "assumed"


def test_observed_flag_splits_on_today() -> None:
    plan = list(plan_days(_block(None), _days([1, 1, 1]), today=PLANTED + timedelta(days=1)))
    assert [d.observed for d in plan] == [True, False, False]


def test_history_start_is_planting_or_a_year_back() -> None:
    today = date(2026, 10, 16)
    assert history_start(_block(None), today) == PLANTED
    old = _block(None, crop="citrus").model_copy(update={"planting_date": date(2025, 1, 1)})
    assert history_start(old, today) == date(2025, 10, 16)


FARM = Farm(name="F", owner_whatsapp="+1", lat=33.85, lon=35.9, timezone="Asia/Beirut")
TODAY = date(2026, 10, 16)


def _span(start: date, end: date) -> list[DailyInput]:
    n = (end - start).days + 1
    return [DailyInput(date=start + timedelta(days=i), et0_mm=4.0, rain_mm=0.0) for i in range(n)]


def test_full_window_joins_archive_and_forecast(monkeypatch: pytest.MonkeyPatch) -> None:
    # Archive 1 Sep..15 Oct, forecast 9 Oct..22 Oct -> one series 1 Sep..22 Oct.
    monkeypatch.setattr(
        "engine.inputs.fetch_archive",
        lambda lat, lon, start, end, client, cache_dir: _span(start, end),
    )
    monkeypatch.setattr(
        "engine.inputs.fetch_forecast",
        lambda lat, lon, today, client, cache_dir: _span(today - timedelta(days=7),
                                                         today + timedelta(days=6)),
    )
    days = full_window(FARM, date(2026, 9, 1), TODAY, None, None)  # type: ignore[arg-type]
    assert days[0].date == date(2026, 9, 1)
    assert days[-1].date == date(2026, 10, 22)
    assert all(b.date - a.date == timedelta(days=1) for a, b in zip(days, days[1:], strict=False))


def test_full_window_short_history_uses_forecast_past_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_archive(*args: object, **kwargs: object) -> list[DailyInput]:
        raise AssertionError("archive should not be called for a 3-day history")

    monkeypatch.setattr("engine.inputs.fetch_archive", no_archive)
    monkeypatch.setattr(
        "engine.inputs.fetch_forecast",
        lambda lat, lon, today, client, cache_dir: _span(today - timedelta(days=7),
                                                         today + timedelta(days=6)),
    )
    days = full_window(FARM, TODAY - timedelta(days=3), TODAY, None, None)  # type: ignore[arg-type]
    assert days[0].date == TODAY - timedelta(days=3)
    assert len(days) == 3 + 7


def test_full_window_needs_today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "engine.inputs.fetch_forecast",
        lambda lat, lon, today, client, cache_dir: _span(today - timedelta(days=7),
                                                         today - timedelta(days=1)),
    )
    with pytest.raises(ValueError, match="does not include today"):
        full_window(FARM, TODAY - timedelta(days=2), TODAY, None, None)  # type: ignore[arg-type]


def test_volume_is_gross_depth_over_the_block() -> None:
    # Day 0 refills 8 mm net -> 8 / 0.9 = 8.889 mm gross; 1 mm on 1 ha = 10 m3 -> 88.89 m3.
    plan = list(plan_days(_block(None), _days([16]), today=PLANTED))
    assert plan[0].volume_m3 == pytest.approx(8.0 / 0.9 * 1.0 * 10)
