"""Assemble one continuous series of daily weather for a farm."""

from datetime import date, timedelta
from pathlib import Path

import httpx

from engine.models import DailyInput, Farm
from engine.weather import fetch_archive, fetch_forecast


def daily_inputs_for(
    farm: Farm,
    today: date,
    backfill_from: date | None,
    client: httpx.Client,
    cache_dir: Path,
) -> list[DailyInput]:
    """Forecast window, or archive from backfill_from through yesterday.

    ERA5 lags about five days and the archive response ends in nulls. Those
    days are filled from the forecast API, which keeps seven past days. A
    longer hole is an error: the balance cannot skip a day.
    """
    if backfill_from is None:
        return fetch_forecast(
            farm.lat,
            farm.lon,
            today=today,
            client=client,
            cache_dir=cache_dir,
        )

    yesterday = today - timedelta(days=1)
    if backfill_from > yesterday:
        raise ValueError("--backfill-from must be on or before yesterday")

    archived = fetch_archive(
        farm.lat,
        farm.lon,
        backfill_from,
        yesterday,
        client=client,
        cache_dir=cache_dir,
    )
    archived = [day for day in archived if backfill_from <= day.date <= yesterday]
    if not archived or archived[0].date != backfill_from:
        raise ValueError(f"archive weather does not start on {backfill_from.isoformat()}")
    if archived[-1].date == yesterday:
        return archived

    gap_start = archived[-1].date + timedelta(days=1)
    recent = fetch_forecast(
        farm.lat,
        farm.lon,
        today=today,
        client=client,
        cache_dir=cache_dir,
    )
    filler = [day for day in recent if gap_start <= day.date <= yesterday]
    if not _covers(filler, gap_start, yesterday):
        raise ValueError(
            f"archive ends {archived[-1].date.isoformat()} and forecast weather does not "
            f"cover {gap_start.isoformat()} through {yesterday.isoformat()}"
        )
    return archived + filler




def _covers(days: list[DailyInput], start: date, end: date) -> bool:
    expected = (end - start).days + 1
    if len(days) != expected:
        return False
    return all(day.date == start + timedelta(days=index) for index, day in enumerate(days))


def full_window(
    farm: Farm,
    start: date,
    today: date,
    client: httpx.Client,
    cache_dir: Path,
) -> list[DailyInput]:
    """Observed weather from `start` through yesterday, then the forecast from today.

    This is what a real recommendation needs: the balance runs over the whole
    history so today's depletion is not a guess, and the forecast shows what's next.
    """
    if start > today:
        raise ValueError("start must be on or before today")
    forecast = fetch_forecast(farm.lat, farm.lon, today=today, client=client, cache_dir=cache_dir)
    yesterday = today - timedelta(days=1)
    if start <= yesterday and (yesterday - start).days >= 7:
        history = daily_inputs_for(farm, today, start, client, cache_dir)
    else:
        history = [day for day in forecast if start <= day.date <= yesterday]
        if start <= yesterday and not _covers(history, start, yesterday):
            raise ValueError(f"forecast weather does not cover {start.isoformat()} onwards")
    upcoming = [day for day in forecast if day.date >= today]
    if not upcoming or upcoming[0].date != today:
        raise ValueError(f"forecast weather does not include today ({today.isoformat()})")
    return history + upcoming
