"""Farm files and the CLI table. Weather HTTP is mocked."""

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest

from engine.cli import (
    BlockPlan,
    daily_inputs_for,
    farm_today,
    format_report,
    format_runtime,
    load_farm,
    main,
    plan_block,
    simulate_plan,
)
from engine.models import Block, DailyInput, DailyResult, Farm, SystemParams

ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 10, 17)


def _potato() -> Block:
    return Block.model_validate(
        {
            "farm_id": "farm-1",
            "name": "Block 1",
            "area_ha": 1.0,
            "crop": "potato",
            "planting_date": date(2026, 3, 1),
            "soil_type": "loam",
            "system": "drip",
            "system_params": SystemParams(
                emitter_flow_lph=1.6,
                emitter_spacing_m=0.3,
                lateral_spacing_m=0.9,
            ),
        }
    )


def _farm() -> Farm:
    return Farm(
        name="Zahle potato",
        owner_whatsapp="+96170000000",
        lat=33.85,
        lon=35.90,
        timezone="Asia/Beirut",
    )


def _payload(start: date, et0: list[float | None]) -> dict[str, object]:
    days = [start + timedelta(days=offset) for offset in range(len(et0))]
    return {
        "daily": {
            "time": [day.isoformat() for day in days],
            "et0_fao_evapotranspiration": et0,
            "precipitation_sum": [0.0] * len(et0),
        }
    }


def _series(start: date, end: date, et0_mm: float) -> list[DailyInput]:
    count = (end - start).days + 1
    return [
        DailyInput(date=start + timedelta(days=offset), et0_mm=et0_mm, rain_mm=0.0)
        for offset in range(count)
    ]


def test_bekaa_potato_matches_the_prompt() -> None:
    config = load_farm(ROOT / "examples" / "bekaa_potato.yaml", today=TODAY)
    block = config.blocks[0]

    assert config.farm.name == "Zahle potato"
    assert config.farm.lat == pytest.approx(33.85)
    assert config.farm.lon == pytest.approx(35.90)
    assert config.farm.timezone == "Asia/Beirut"
    assert len(config.blocks) == 1
    assert block.crop == "potato"
    assert block.soil_type == "loam"
    assert block.system == "drip"
    assert block.planting_date == date(2026, 8, 18)
    assert block.system_params.emitter_flow_lph == pytest.approx(1.6)
    assert block.system_params.emitter_spacing_m == pytest.approx(0.3)
    assert block.system_params.lateral_spacing_m == pytest.approx(0.9)
    assert block.system_params.efficiency == pytest.approx(0.90)


def test_coast_citrus_is_a_micro_sprinkler_orchard() -> None:
    config = load_farm(ROOT / "examples" / "coast_citrus.yaml", today=TODAY)
    block = config.blocks[0]

    assert config.farm.timezone == "Asia/Beirut"
    assert 33.6 < config.farm.lat < 33.9
    assert 35.3 < config.farm.lon < 35.6
    assert block.crop == "citrus"
    assert block.soil_type == "sandy_loam"
    assert block.system == "micro_sprinkler"
    assert block.planting_date == date(2026, 1, 1)
    assert block.kr == pytest.approx(1.0)
    assert block.system_params.efficiency == pytest.approx(0.85)
    assert block.system_params.application_rate_mm_h == pytest.approx(2.8)


def test_farm_today_uses_the_farm_zone_not_the_laptop() -> None:
    # 00:30 in Sydney on 17 Oct is still 16 Oct in Beirut.
    now = datetime(2026, 10, 17, 0, 30, tzinfo=ZoneInfo("Australia/Sydney"))
    assert farm_today("Asia/Beirut", now=now) == date(2026, 10, 16)


def test_unknown_timezone_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown timezone"):
        farm_today("Not/AZone")


def test_planting_days_ago_and_planting_date_cannot_both_be_set(tmp_path: Path) -> None:
    path = tmp_path / "farm.yaml"
    path.write_text(
        """
name: Test
owner_whatsapp: "+96170000000"
lat: 33.85
lon: 35.90
timezone: Asia/Beirut
blocks:
  - farm_id: t
    name: Block 1
    area_ha: 1
    crop: potato
    planting_date: "2026-08-01"
    planting_days_ago: 60
    soil_type: loam
    system: drip
    system_params:
      emitter_flow_lph: 1.6
      emitter_spacing_m: 0.3
      lateral_spacing_m: 0.9
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="planting_date and planting_days_ago"):
        load_farm(path, today=TODAY)


def test_plan_carries_the_recommended_refill_into_the_next_day() -> None:
    # Day 0 RAW is 6.825 mm. ETc = 20 * 0.50 = 10 mm, so the day irrigates.
    # Applying that net returns the root zone to field capacity, so day 1
    # is another 10 mm depletion, not 20 mm.
    inputs = [
        DailyInput(date=date(2026, 3, 1), et0_mm=20.0, rain_mm=0.0),
        DailyInput(date=date(2026, 3, 2), et0_mm=20.0, rain_mm=0.0),
    ]
    results = simulate_plan(_potato(), inputs)

    assert results[0].irrigate is True
    assert results[0].dr_mm == pytest.approx(10.0)
    assert results[1].dr_mm == pytest.approx(10.0)


def test_days_before_planting_are_omitted() -> None:
    inputs = _series(date(2026, 10, 1), date(2026, 10, 3), et0_mm=1.0)
    block = _potato().model_copy(update={"planting_date": date(2026, 10, 3)})
    plan = plan_block(block, inputs)

    assert plan.skipped_days == 2
    assert [day.date for day in plan.inputs] == [date(2026, 10, 3)]


def test_table_flags_past_days_and_shows_rain() -> None:
    config = load_farm(ROOT / "examples" / "bekaa_potato.yaml", today=TODAY)
    inputs = [
        DailyInput(date=date(2026, 10, 16), et0_mm=4.0, rain_mm=4.0),
        DailyInput(date=date(2026, 10, 17), et0_mm=5.0, rain_mm=10.0),
    ]
    results = [
        DailyResult(
            date=date(2026, 10, 16),
            irrigate=False,
            net_mm=0.0,
            gross_mm=0.0,
            runtime_h=0.0,
            dr_mm=3.0,
            raw_mm=22.8,
            taw_mm=65.0,
            et0_mm=4.0,
            kc=1.10,
            etc_mm=4.4,
            peff_mm=0.0,
        ),
        DailyResult(
            date=date(2026, 10, 17),
            irrigate=True,
            net_mm=30.0,
            gross_mm=33.3,
            runtime_h=1.5,
            dr_mm=30.0,
            raw_mm=22.8,
            taw_mm=65.0,
            et0_mm=5.0,
            kc=1.12,
            etc_mm=5.6,
            peff_mm=8.0,
        ),
    ]
    plan = BlockPlan(config.blocks[0], inputs, results, skipped_days=1)
    text = format_report(config, [plan])
    observed, forecast = [line for line in text.splitlines() if line.startswith("2026-10-")]

    assert "Zahle potato - Block 1 (potato, loam, drip)" in text
    assert "1 day before planting (2026-08-18) is omitted" in text
    assert "observed" in observed
    assert "4.0" in observed
    assert "forecast" in forecast
    assert "10.0" in forecast
    assert "8.0" not in text
    assert "1:30" in forecast
    assert "yes" in forecast


def test_runtime_is_hours_and_minutes() -> None:
    assert format_runtime(0.0) == "0:00"
    assert format_runtime(1.5) == "1:30"
    assert format_runtime(5.625) == "5:38"


def test_backfill_fills_the_archive_lag_from_the_forecast(tmp_path: Path) -> None:
    start = date(2026, 10, 1)
    archive_et0: list[float | None] = []
    day = start
    while day <= date(2026, 10, 16):
        archive_et0.append(None if day >= date(2026, 10, 14) else 3.0)
        day += timedelta(days=1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "archive-api.open-meteo.com":
            return httpx.Response(200, json=_payload(start, archive_et0))
        return httpx.Response(200, json=_payload(date(2026, 10, 10), [4.0] * 14))

    days = daily_inputs_for(
        _farm(),
        TODAY,
        start,
        httpx.Client(transport=httpx.MockTransport(handler)),
        tmp_path,
    )

    assert days[0].date == start
    assert days[-1].date == date(2026, 10, 16)
    assert len(days) == 16
    assert days[12].date == date(2026, 10, 13)
    assert days[12].et0_mm == pytest.approx(3.0)
    assert days[13].et0_mm == pytest.approx(4.0)


def test_complete_archive_does_not_call_the_forecast(tmp_path: Path) -> None:
    start = date(2026, 10, 1)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host != "archive-api.open-meteo.com":
            raise AssertionError(request.url.host)
        return httpx.Response(200, json=_payload(start, [3.0] * 16))

    days = daily_inputs_for(
        _farm(),
        TODAY,
        start,
        httpx.Client(transport=httpx.MockTransport(handler)),
        tmp_path,
    )
    assert days[0].date == start
    assert days[-1].date == date(2026, 10, 16)


def test_a_gap_longer_than_the_forecast_past_is_an_error(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "archive-api.open-meteo.com":
            return httpx.Response(200, json=_payload(date(2026, 10, 1), [3.0]))
        return httpx.Response(200, json=_payload(date(2026, 10, 10), [4.0] * 14))

    with pytest.raises(ValueError, match="does not cover"):
        daily_inputs_for(
            _farm(),
            TODAY,
            date(2026, 10, 1),
            httpx.Client(transport=httpx.MockTransport(handler)),
            tmp_path,
        )


def test_backfill_from_after_yesterday_is_rejected(tmp_path: Path) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    with pytest.raises(ValueError, match="yesterday"):
        daily_inputs_for(_farm(), TODAY, TODAY, client, tmp_path)


def test_main_prints_the_example_farm(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("engine.cli.farm_today", lambda timezone, now=None: TODAY)

    def fake_forecast(
        lat: float,
        lon: float,
        *,
        today: date,
        client: httpx.Client,
        cache_dir: Path,
    ) -> list[DailyInput]:
        return [DailyInput(date=today, et0_mm=4.0, rain_mm=0.0)]

    monkeypatch.setattr("engine.cli.fetch_forecast", fake_forecast)
    code = main(["--farm", str(ROOT / "examples" / "bekaa_potato.yaml")])
    out = capsys.readouterr().out

    assert code == 0
    assert "Zahle potato - Block 1 (potato, loam, drip)" in out
    assert "2026-10-17" in out
    assert "forecast" in out


def test_main_backfill_prints_observed_days(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("engine.cli.farm_today", lambda timezone, now=None: TODAY)

    def fake_archive(
        lat: float,
        lon: float,
        start: date,
        end: date,
        *,
        client: httpx.Client,
        cache_dir: Path,
    ) -> list[DailyInput]:
        assert start == date(2026, 10, 1)
        assert end == date(2026, 10, 16)
        return _series(start, end, et0_mm=3.0)

    def fail_forecast(*args: object, **kwargs: object) -> list[DailyInput]:
        raise AssertionError("forecast should not be called when the archive is complete")

    monkeypatch.setattr("engine.cli.fetch_archive", fake_archive)
    monkeypatch.setattr("engine.cli.fetch_forecast", fail_forecast)
    code = main(
        [
            "--farm",
            str(ROOT / "examples" / "bekaa_potato.yaml"),
            "--backfill-from",
            "2026-10-01",
        ]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "observed" in out
    assert "forecast" not in out


def test_main_reports_a_missing_farm(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    missing = tmp_path / "missing.yaml"
    code = main(["--farm", str(missing)])
    assert code == 1
    assert "missing.yaml" in capsys.readouterr().err
