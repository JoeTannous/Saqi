"""Fill weather_daily for every farm. Run by a GitHub Action every 3 hours.

    DATABASE_URL=... python -m api.sync_weather

Fetching from GitHub's runners instead of Render avoids Open-Meteo's per-IP limit
on Render's shared IPs. Archive days are fetched once and kept; the forecast
window (past 7 + next 7 days) is refreshed every run.
"""

import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from api.weatherstore import (
    ARCHIVE,
    PostgresWeatherStore,
    WeatherStore,
    stamp,
)
from engine.cli import load_farm
from engine.plan import history_start
from engine.weather import fetch_archive, fetch_forecast

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_LAG_DAYS = 6  # ERA5 is usually complete up to about 5 days ago


def farm_files() -> list[Path]:
    farms = sorted((ROOT / "farms").glob("*.yaml"))
    return farms or sorted((ROOT / "examples").glob("*.yaml"))


def sync_farm(path: Path, store: WeatherStore, client: httpx.Client, cache_dir: Path,
              now: datetime) -> str:
    config = load_farm(path)
    farm, today = config.farm, config.today
    start = min(history_start(block, today) for block in config.blocks)
    archive_end = today - timedelta(days=ARCHIVE_LAG_DAYS)

    have = {d.date for d in store.read(farm.lat, farm.lon, start, archive_end)
            if d.priority >= ARCHIVE}
    missing = [start + timedelta(days=i) for i in range((archive_end - start).days + 1)
               if start + timedelta(days=i) not in have]
    archived = 0
    if missing:
        days = fetch_archive(farm.lat, farm.lon, missing[0], archive_end,
                             client=client, cache_dir=cache_dir)
        store.upsert(farm.lat, farm.lon, stamp(days, today, now, archive=True))
        archived = len(days)

    forecast = fetch_forecast(farm.lat, farm.lon, today=today, client=client,
                              cache_dir=cache_dir)
    store.upsert(farm.lat, farm.lon, stamp(forecast, today, now))
    return f"{path.stem}: {archived} archive days, {len(forecast)} forecast days"


def main() -> int:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 1
    store = PostgresWeatherStore(url)
    store.ensure_schema()
    now = datetime.now(UTC)
    failures = 0
    with tempfile.TemporaryDirectory() as tmp, httpx.Client(
        timeout=60.0, headers={"User-Agent": "saqi-sync/0.1"}
    ) as client:
        for path in farm_files():
            try:
                print(sync_farm(path, store, client, Path(tmp), now))
            except Exception as exc:  # keep going so one farm can't block the rest
                failures += 1
                print(f"{path.stem}: FAILED {exc}", file=sys.stderr)
    return 1 if failures else 0



if __name__ == "__main__":
    raise SystemExit(main())
