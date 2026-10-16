"""Open-Meteo parsing and the file cache. HTTP is mocked; nothing here uses the network."""

from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from engine.weather import (
    cache_path,
    fetch_archive,
    fetch_forecast,
    parse_daily_inputs,
)


def _payload(
    start: date,
    et0: list[float | None],
    rain: list[float | None] | None = None,
) -> dict[str, object]:
    if rain is None:
        rain = [0.0] * len(et0)
    days = [start + timedelta(days=offset) for offset in range(len(et0))]
    return {
        "daily": {
            "time": [day.isoformat() for day in days],
            "et0_fao_evapotranspiration": et0,
            "precipitation_sum": rain,
        }
    }


def _client(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_parse_reads_et0_and_rain() -> None:
    start = date(2026, 10, 10)
    days = parse_daily_inputs(_payload(start, [1.5, 2.0], [0.0, 4.25]))

    assert [day.date for day in days] == [start, start + timedelta(days=1)]
    assert days[0].et0_mm == pytest.approx(1.5)
    assert days[1].rain_mm == pytest.approx(4.25)
    assert days[0].irrigation_applied_mm == 0.0


def test_parse_drops_a_null_tail_and_rejects_a_hole() -> None:
    start = date(2026, 10, 1)
    trimmed = parse_daily_inputs(_payload(start, [3.0, 3.5, None, None]))
    assert [day.date for day in trimmed] == [start, start + timedelta(days=1)]

    with pytest.raises(ValueError, match="missing ET0 or rain"):
        parse_daily_inputs(_payload(start, [3.0, None, 3.5]))


def test_parse_rejects_a_gap_in_the_dates() -> None:
    payload = _payload(date(2026, 10, 1), [1.0, 1.0])
    daily = payload["daily"]
    assert isinstance(daily, dict)
    daily["time"] = ["2026-10-01", "2026-10-03"]

    with pytest.raises(ValueError, match="skip"):
        parse_daily_inputs(payload)


def test_parse_rejects_negative_et0() -> None:
    with pytest.raises(ValueError, match="negative"):
        parse_daily_inputs(_payload(date(2026, 10, 1), [-0.1]))


def test_cache_file_is_keyed_by_source_lat_lon_and_dates() -> None:
    path = cache_path(
        Path(".cache"),
        "archive",
        33.85,
        35.9,
        date(2026, 7, 1),
        date(2026, 7, 2),
    )
    assert path.name == "archive_33.8500_35.9000_2026-07-01_2026-07-02.json"

    other = cache_path(
        Path(".cache"),
        "forecast",
        33.86,
        35.9,
        date(2026, 7, 1),
        date(2026, 7, 2),
    )
    assert other != path


def test_forecast_request_matches_the_spec_and_is_cached(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    today = date(2026, 10, 17)
    body = _payload(today - timedelta(days=7), [3.0] * 14)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=body)

    client = _client(handler)
    first = fetch_forecast(33.85, 35.90, today=today, client=client, cache_dir=tmp_path)
    second = fetch_forecast(33.85, 35.90, today=today, client=client, cache_dir=tmp_path)

    assert len(calls) == 1
    assert first == second
    assert first[0].date == date(2026, 10, 10)
    assert first[-1].date == date(2026, 10, 23)

    query = parse_qs(calls[0].url.query.decode())
    assert calls[0].url.host == "api.open-meteo.com"
    assert calls[0].url.path == "/v1/forecast"
    assert float(query["latitude"][0]) == pytest.approx(33.85)
    assert float(query["longitude"][0]) == pytest.approx(35.90)
    assert query["past_days"] == ["7"]
    assert query["forecast_days"] == ["7"]
    assert query["timezone"] == ["auto"]
    assert "et0_fao_evapotranspiration" in query["daily"][0]
    assert "precipitation_sum" in query["daily"][0]
    cached = list(tmp_path.glob("*.json"))
    assert len(cached) == 1
    assert cached[0].name.startswith("forecast_33.8500_35.9000_")


def test_archive_request_uses_the_date_range(tmp_path: Path) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_payload(date(2026, 7, 1), [2.0, 2.5]))

    fetch_archive(
        33.73,
        35.45,
        date(2026, 7, 1),
        date(2026, 7, 2),
        client=_client(handler),
        cache_dir=tmp_path,
    )

    query = parse_qs(seen[0].url.query.decode())
    assert seen[0].url.host == "archive-api.open-meteo.com"
    assert seen[0].url.path == "/v1/archive"
    assert query["start_date"] == ["2026-07-01"]
    assert query["end_date"] == ["2026-07-02"]
    assert "past_days" not in query


def test_http_error_is_not_cached(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="nope")

    with pytest.raises(ValueError, match="HTTP 500"):
        fetch_forecast(
            33.85,
            35.90,
            today=date(2026, 10, 17),
            client=_client(handler),
            cache_dir=tmp_path,
        )
    assert list(tmp_path.glob("*.json")) == []


def test_corrupt_cache_is_fetched_again(tmp_path: Path) -> None:
    today = date(2026, 10, 17)
    start = today - timedelta(days=7)
    end = today + timedelta(days=6)
    stale = cache_path(tmp_path, "forecast", 33.85, 35.90, start, end)
    stale.write_text("{", encoding="utf-8")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=_payload(start, [1.0] * 14))

    days = fetch_forecast(
        33.85,
        35.90,
        today=today,
        client=_client(handler),
        cache_dir=tmp_path,
    )
    assert calls["n"] == 1
    assert len(days) == 14
