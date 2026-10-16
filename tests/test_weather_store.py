"""Stored weather: priority rules, the stored → live → stale fallback, and the sync job."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api import sync_weather
from api.main import create_app
from api.weatherstore import (
    ARCHIVE,
    FORECAST_FUTURE,
    FORECAST_PAST,
    MemoryWeatherStore,
    PostgresWeatherStore,
    StoredDay,
    layered_weather,
    stamp,
)
from engine.models import DailyInput, Farm
from tests.test_api import FARM_YAML, TODAY

FARM = Farm(name="F", owner_whatsapp="+1", lat=33.85, lon=35.9, timezone="Asia/Beirut")
NOW = datetime(2026, 10, 16, 9, 0, tzinfo=UTC)


def span(start: date, end: date, et0: float = 4.0) -> list[DailyInput]:
    n = (end - start).days + 1
    return [DailyInput(date=start + timedelta(days=i), et0_mm=et0, rain_mm=0.0) for i in range(n)]


def test_better_data_is_not_overwritten() -> None:
    store = MemoryWeatherStore()
    day = TODAY - timedelta(days=10)
    store.upsert(FARM.lat, FARM.lon, [StoredDay(day, 5.0, 0.0, ARCHIVE, NOW)])
    store.upsert(FARM.lat, FARM.lon, [StoredDay(day, 9.0, 0.0, FORECAST_PAST, NOW)])
    assert store.read(FARM.lat, FARM.lon, day, day)[0].et0_mm == 5.0
    # A newer forecast replaces an older forecast for the same day.
    future = TODAY + timedelta(days=2)
    store.upsert(FARM.lat, FARM.lon, [StoredDay(future, 3.0, 0.0, FORECAST_FUTURE, NOW)])
    store.upsert(FARM.lat, FARM.lon, [StoredDay(future, 3.5, 0.0, FORECAST_FUTURE, NOW)])
    assert store.read(FARM.lat, FARM.lon, future, future)[0].et0_mm == 3.5


def test_stamp_priorities() -> None:
    days = span(TODAY - timedelta(days=1), TODAY)
    assert [d.priority for d in stamp(days, TODAY, NOW)] == [FORECAST_PAST, FORECAST_FUTURE]
    assert {d.priority for d in stamp(days, TODAY, NOW, archive=True)} == {ARCHIVE}


def _filled(fetched_at: datetime) -> MemoryWeatherStore:
    store = MemoryWeatherStore()
    store.upsert(FARM.lat, FARM.lon,
                 stamp(span(TODAY - timedelta(days=20), TODAY + timedelta(days=6)), TODAY,
                       fetched_at))
    return store


def test_fresh_store_skips_live() -> None:
    def live(*_: object) -> list[DailyInput]:
        raise AssertionError("should not call Open-Meteo")

    fetch = layered_weather(_filled(NOW - timedelta(hours=2)), live, now=lambda: NOW)
    result = fetch(FARM, TODAY - timedelta(days=20), TODAY)
    assert result.days[0].date == TODAY - timedelta(days=20)
    assert result.days[-1].date == TODAY + timedelta(days=6)
    assert result.fetched_at == NOW - timedelta(hours=2)


def test_stale_store_tries_live_and_saves_it() -> None:
    store = _filled(NOW - timedelta(hours=30))
    calls = []

    def live(farm: Farm, start: date, today: date) -> list[DailyInput]:
        calls.append(start)
        return span(start, today + timedelta(days=6), et0=6.0)

    result = layered_weather(store, live, now=lambda: NOW)(FARM, TODAY - timedelta(days=3), TODAY)
    assert calls and result.fetched_at == NOW
    assert store.read(FARM.lat, FARM.lon, TODAY, TODAY)[0].et0_mm == 6.0


def test_live_failure_falls_back_to_stale_store() -> None:
    old = NOW - timedelta(hours=30)

    def live(*_: object) -> list[DailyInput]:
        raise ValueError("Open-Meteo returned HTTP 429")

    result = layered_weather(_filled(old), live, now=lambda: NOW)(
        FARM, TODAY - timedelta(days=5), TODAY)
    assert result.fetched_at == old
    assert result.days[-1].date == TODAY + timedelta(days=6)


def test_live_failure_without_coverage_raises() -> None:
    def live(*_: object) -> list[DailyInput]:
        raise ValueError("Open-Meteo returned HTTP 429")

    with pytest.raises(ValueError, match="429"):
        layered_weather(MemoryWeatherStore(), live, now=lambda: NOW)(
            FARM, TODAY - timedelta(days=5), TODAY)


def test_plan_reports_weather_age_and_survives_429(tmp_path: Path) -> None:
    farms = tmp_path / "farms"
    farms.mkdir()
    (farms / "test.yaml").write_text(FARM_YAML, encoding="utf-8")
    old = datetime.now(UTC) - timedelta(hours=30)
    store = MemoryWeatherStore()
    store.upsert(33.85, 35.90, stamp(span(TODAY - timedelta(days=25), TODAY + timedelta(days=6)),
                                     TODAY, old))

    def live(*_: object) -> list[DailyInput]:
        raise ValueError("Open-Meteo returned HTTP 429")

    app = create_app(farms_dir=farms, log_path=tmp_path / "l.csv", weather=live,
                     weather_store=store, today_fn=lambda tz: TODAY,
                     web_dir=tmp_path / "x", chat_client=None)
    res = TestClient(app).get("/api/farms/test/plan")
    assert res.status_code == 200
    assert res.json()["weather_fetched_at"].startswith(old.date().isoformat())


def test_sync_fetches_archive_once_then_only_forecast(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    farm_file = tmp_path / "test.yaml"
    farm_file.write_text(FARM_YAML, encoding="utf-8")
    monkeypatch.setattr("api.sync_weather.load_farm",
                        lambda p: __import__("engine.cli", fromlist=["load_farm"]).load_farm(
                            p, today=TODAY))
    archive_calls: list[tuple[date, date]] = []

    def fake_archive(lat, lon, start, end, client, cache_dir):  # type: ignore[no-untyped-def]
        archive_calls.append((start, end))
        return span(start, end, et0=5.0)

    monkeypatch.setattr("api.sync_weather.fetch_archive", fake_archive)
    monkeypatch.setattr("api.sync_weather.fetch_forecast",
                        lambda lat, lon, today, client, cache_dir: span(
                            today - timedelta(days=7), today + timedelta(days=6), et0=3.0))
    store = MemoryWeatherStore()
    sync_weather.sync_farm(farm_file, store, None, tmp_path, NOW)  # type: ignore[arg-type]
    # Planted 20 days ago; archive up to 6 days ago.
    assert archive_calls == [(TODAY - timedelta(days=20), TODAY - timedelta(days=6))]
    # Archive wins over forecast-past on overlapping days.
    week_ago = TODAY - timedelta(days=7)
    assert store.read(33.85, 35.9, week_ago, week_ago)[0].et0_mm == 5.0
    sync_weather.sync_farm(farm_file, store, None, tmp_path, NOW)  # type: ignore[arg-type]
    assert len(archive_calls) == 1


class FakeCursor:
    def __init__(self, sink: list[object]) -> None:
        self.sink = sink

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def executemany(self, sql: str, params: list[tuple[object, ...]]) -> None:
        self.sink.append((sql, params))


class FakeConn:
    def __init__(self, sink: list[object]) -> None:
        self.sink = sink

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, *_: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> "FakeConn":
        self.sink.append(sql)
        return self

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.sink)


def test_postgres_store_creates_table_with_rls_and_upserts() -> None:
    sink: list[object] = []
    store = PostgresWeatherStore("postgresql://x/y", connect=lambda: FakeConn(sink))
    store.upsert(33.85, 35.9, [StoredDay(TODAY, 4.0, 0.0, FORECAST_FUTURE, NOW)])
    sql_text = " ".join(str(x) for x in sink if isinstance(x, str))
    assert "CREATE TABLE IF NOT EXISTS weather_daily" in sql_text
    assert "ENABLE ROW LEVEL SECURITY" in sql_text
    upsert = next(x for x in sink if isinstance(x, tuple))
    assert "ON CONFLICT" in upsert[0] and "EXCLUDED.priority >= weather_daily.priority" in upsert[0]
    assert upsert[1] == [(338500, 359000, TODAY, 4.0, 0.0, FORECAST_FUTURE, NOW)]
