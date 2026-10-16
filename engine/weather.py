"""Daily ET0 and rain from Open-Meteo, cached under .cache/ by lat, lon, and dates."""

import json
from datetime import date, timedelta
from pathlib import Path

import httpx

from engine.models import DailyInput

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
PAST_DAYS = 7
FORECAST_DAYS = 7
# temperature_* matches the docs/SPEC.md URL. Only ET0 and rain are used.
DAILY_VARIABLES = (
    "et0_fao_evapotranspiration",
    "precipitation_sum",
    "temperature_2m_max",
    "temperature_2m_min",
)


def forecast_span(today: date) -> tuple[date, date]:
    """Inclusive dates for past_days=7 and forecast_days=7.

    Open-Meteo counts forecast_days from today, so 7 forecast days end on
    today+6. The cache key uses this span. Parsing returns the days the API
    actually sent.
    """
    start = today - timedelta(days=PAST_DAYS)
    end = today + timedelta(days=FORECAST_DAYS - 1)
    return start, end


def cache_path(
    cache_dir: Path,
    source: str,
    lat: float,
    lon: float,
    start: date,
    end: date,
) -> Path:
    """File name is the API plus lat/lon to 4 decimals plus the date range."""
    name = f"{source}_{lat:.4f}_{lon:.4f}_{start.isoformat()}_{end.isoformat()}.json"
    return cache_dir / name


def fetch_forecast(
    lat: float,
    lon: float,
    *,
    today: date,
    client: httpx.Client,
    cache_dir: Path,
) -> list[DailyInput]:
    """Forecast API: 7 past days and 7 forecast days, including today."""
    start, end = forecast_span(today)
    return _cached_daily(
        url=FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": ",".join(DAILY_VARIABLES),
            "timezone": "auto",
            "past_days": PAST_DAYS,
            "forecast_days": FORECAST_DAYS,
        },
        cache_file=cache_path(cache_dir, "forecast", lat, lon, start, end),
        client=client,
    )


def fetch_archive(
    lat: float,
    lon: float,
    start: date,
    end: date,
    *,
    client: httpx.Client,
    cache_dir: Path,
) -> list[DailyInput]:
    """Archive API for one inclusive date range. ERA5 lags a few days."""
    if end < start:
        raise ValueError("archive end date is before the start date")
    return _cached_daily(
        url=ARCHIVE_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "daily": ",".join(DAILY_VARIABLES),
            "timezone": "auto",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
        },
        cache_file=cache_path(cache_dir, "archive", lat, lon, start, end),
        client=client,
    )


def parse_daily_inputs(payload: dict[str, object]) -> list[DailyInput]:
    """Read ET0 and rain. A null tail is dropped; a null in the middle is an error.

    The archive often pads days it does not have yet with null. Dropping only
    that tail lets the caller fill the gap. A hole earlier in the series would
    skip a day in the water balance, so it is rejected.
    """
    daily = payload.get("daily")
    if not isinstance(daily, dict):
        raise ValueError("Open-Meteo response has no daily object")

    times = daily.get("time")
    et0_values = daily.get("et0_fao_evapotranspiration")
    rain_values = daily.get("precipitation_sum")
    series = (times, et0_values, rain_values)
    if any(not isinstance(values, list) for values in series):
        raise ValueError("Open-Meteo daily series are missing")
    assert isinstance(times, list)
    assert isinstance(et0_values, list)
    assert isinstance(rain_values, list)
    if len(times) != len(et0_values) or len(et0_values) != len(rain_values):
        raise ValueError("Open-Meteo daily series have different lengths")

    days = [_as_date(item) for item in times]
    et0_optional = [_optional_float(item) for item in et0_values]
    rain_optional = [_optional_float(item) for item in rain_values]
    days, et0_optional, rain_optional = _drop_trailing_missing(days, et0_optional, rain_optional)
    if not days:
        raise ValueError("Open-Meteo returned no daily weather")

    inputs: list[DailyInput] = []
    previous: date | None = None
    for day, et0, rain in zip(days, et0_optional, rain_optional, strict=True):
        if et0 is None or rain is None:
            raise ValueError(f"Open-Meteo is missing ET0 or rain for {day.isoformat()}")
        if et0 < 0.0 or rain < 0.0:
            raise ValueError(f"Open-Meteo ET0 or rain is negative for {day.isoformat()}")
        if previous is not None and day != previous + timedelta(days=1):
            raise ValueError(
                f"Open-Meteo days skip from {previous.isoformat()} to {day.isoformat()}"
            )
        previous = day
        inputs.append(DailyInput(date=day, et0_mm=et0, rain_mm=rain))
    return inputs


def _drop_trailing_missing(
    days: list[date],
    et0: list[float | None],
    rain: list[float | None],
) -> tuple[list[date], list[float | None], list[float | None]]:
    end = len(days)
    while end > 0 and (et0[end - 1] is None or rain[end - 1] is None):
        end -= 1
    return days[:end], et0[:end], rain[:end]


def _as_date(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("Open-Meteo daily time must be YYYY-MM-DD strings")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Open-Meteo date {value!r} is not YYYY-MM-DD") from exc


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Open-Meteo daily values must be numbers")
    return float(value)


def _read_cache(path: Path) -> dict[str, object] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    try:
        parse_daily_inputs(loaded)
    except ValueError:
        return None
    return loaded


def _cached_daily(
    *,
    url: str,
    params: dict[str, str | int | float],
    cache_file: Path,
    client: httpx.Client,
) -> list[DailyInput]:
    cached = _read_cache(cache_file)
    if cached is not None:
        return parse_daily_inputs(cached)

    try:
        response = client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise ValueError(f"Open-Meteo request failed: {exc}") from exc

    if response.status_code != 200:
        detail = response.text.strip().replace("\n", " ")[:200]
        raise ValueError(f"Open-Meteo returned HTTP {response.status_code}: {detail}")

    try:
        loaded = response.json()
    except json.JSONDecodeError as exc:
        raise ValueError("Open-Meteo returned invalid JSON") from exc
    if not isinstance(loaded, dict):
        raise ValueError("Open-Meteo returned a non-object JSON body")

    days = parse_daily_inputs(loaded)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(loaded), encoding="utf-8")
    return days
