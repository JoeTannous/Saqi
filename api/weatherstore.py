"""Daily weather kept in Postgres so the app doesn't depend on live Open-Meteo calls.

Open-Meteo rate-limits per IP and Render's free tier shares outbound IPs, so the
deployed app can be refused for a whole day. A GitHub Action (api/sync_weather.py)
fills this table every few hours; the API reads it first and only calls Open-Meteo
live as a backup.

Rows carry a priority so better data is never overwritten by worse:
archive (ERA5 reanalysis) 3 > forecast-API past days 2 > forecast future days 1.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from engine.models import DailyInput, Farm

ARCHIVE = 3
FORECAST_PAST = 2
FORECAST_FUTURE = 1
FRESH_FOR = timedelta(hours=12)

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS weather_daily (
    lat_e4 integer NOT NULL,
    lon_e4 integer NOT NULL,
    date date NOT NULL,
    et0_mm real NOT NULL,
    rain_mm real NOT NULL,
    priority smallint NOT NULL,
    fetched_at timestamptz NOT NULL,
    PRIMARY KEY (lat_e4, lon_e4, date)
);
ALTER TABLE weather_daily ENABLE ROW LEVEL SECURITY
"""

UPSERT_SQL = """
INSERT INTO weather_daily (lat_e4, lon_e4, date, et0_mm, rain_mm, priority, fetched_at)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (lat_e4, lon_e4, date) DO UPDATE
SET et0_mm = EXCLUDED.et0_mm, rain_mm = EXCLUDED.rain_mm,
    priority = EXCLUDED.priority, fetched_at = EXCLUDED.fetched_at
WHERE EXCLUDED.priority >= weather_daily.priority
"""

SELECT_SQL = """
SELECT date, et0_mm, rain_mm, priority, fetched_at FROM weather_daily
WHERE lat_e4 = %s AND lon_e4 = %s AND date BETWEEN %s AND %s
ORDER BY date
"""


def key(lat: float, lon: float) -> tuple[int, int]:
    """Coordinates to 4 decimals (about 11 m), as integers so equality is exact."""
    return round(lat * 10_000), round(lon * 10_000)


@dataclass(frozen=True)
class StoredDay:
    date: date
    et0_mm: float
    rain_mm: float
    priority: int
    fetched_at: datetime

    def as_input(self) -> DailyInput:
        return DailyInput(date=self.date, et0_mm=self.et0_mm, rain_mm=self.rain_mm)


class WeatherStore(Protocol):
    def ensure_schema(self) -> None: ...

    def read(self, lat: float, lon: float, start: date, end: date) -> list[StoredDay]: ...

    def upsert(
        self, lat: float, lon: float, days: Iterable[StoredDay]
    ) -> None: ...


def stamp(days: Iterable[DailyInput], today: date, fetched_at: datetime, *,
          archive: bool = False) -> list[StoredDay]:
    """Tag fetched days with their priority. Past days are archive or forecast-past."""
    out = []
    for day in days:
        if archive:
            priority = ARCHIVE
        else:
            priority = FORECAST_PAST if day.date < today else FORECAST_FUTURE
        out.append(StoredDay(day.date, day.et0_mm, day.rain_mm, priority, fetched_at))
    return out


class MemoryWeatherStore:
    """Same rules as Postgres, in a dict. Used in tests and as a model of the SQL."""

    def __init__(self) -> None:
        self.rows: dict[tuple[int, int, date], StoredDay] = {}

    def ensure_schema(self) -> None:
        return None

    def read(self, lat: float, lon: float, start: date, end: date) -> list[StoredDay]:
        k = key(lat, lon)
        found = [d for (a, b, _), d in self.rows.items() if (a, b) == k and start <= d.date <= end]
        return sorted(found, key=lambda d: d.date)

    def upsert(self, lat: float, lon: float, days: Iterable[StoredDay]) -> None:
        a, b = key(lat, lon)
        for day in days:
            old = self.rows.get((a, b, day.date))
            if old is None or day.priority >= old.priority:
                self.rows[(a, b, day.date)] = day


class PostgresWeatherStore:
    def __init__(self, database_url: str, *, connect: Callable[[], Any] | None = None) -> None:
        self._database_url = database_url
        self._connect = connect or self._default_connect
        self._ready = False

    def _default_connect(self) -> Any:
        import psycopg

        # prepare_threshold=None: Supabase's pooler (PgBouncer) rejects prepared statements.
        return psycopg.connect(self._database_url, prepare_threshold=None)

    def ensure_schema(self) -> None:
        if self._ready:
            return
        with self._connect() as conn:
            for statement in CREATE_SQL.split(";"):
                if statement.strip():
                    conn.execute(statement)
        self._ready = True

    def read(self, lat: float, lon: float, start: date, end: date) -> list[StoredDay]:
        self.ensure_schema()
        a, b = key(lat, lon)
        with self._connect() as conn:
            found = conn.execute(SELECT_SQL, (a, b, start, end)).fetchall()
        return [
            StoredDay(_as_date(d), float(et0), float(rain), int(p), _as_utc(f))
            for d, et0, rain, p, f in found
        ]

    def upsert(self, lat: float, lon: float, days: Iterable[StoredDay]) -> None:
        self.ensure_schema()
        a, b = key(lat, lon)
        params = [
            (a, b, d.date, d.et0_mm, d.rain_mm, d.priority, d.fetched_at) for d in days
        ]
        if not params:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(UPSERT_SQL, params)


def _as_date(value: Any) -> date:
    return value.date() if isinstance(value, datetime) else value


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class WeatherResult:
    days: list[DailyInput]
    fetched_at: datetime | None  # oldest forecast fetch behind today's numbers


def covers(days: list[StoredDay], start: date, end: date) -> bool:
    have = {d.date for d in days}
    span = (end - start).days + 1
    return span > 0 and all(start + timedelta(days=i) in have for i in range(span))


def layered_weather(
    store: WeatherStore,
    live: Callable[[Farm, date, date], list[DailyInput]],
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Callable[[Farm, date, date], WeatherResult]:
    """Stored weather first, live Open-Meteo second, stale stored weather last."""

    def fetch(farm: Farm, start: date, today: date) -> WeatherResult:
        horizon = today + timedelta(days=6)
        stored = store.read(farm.lat, farm.lon, start, horizon)
        current = now()
        today_row = next((d for d in stored if d.date == today), None)
        if (
            covers(stored, start, today)
            and today_row is not None
            and current - today_row.fetched_at <= FRESH_FOR
        ):
            return WeatherResult([d.as_input() for d in stored], today_row.fetched_at)

        try:
            days = live(farm, start, today)
        except Exception:
            if covers(stored, start, today):
                assert today_row is not None
                return WeatherResult([d.as_input() for d in stored], today_row.fetched_at)
            raise
        try:
            store.upsert(farm.lat, farm.lon, stamp(days, today, current))
        except Exception:  # a store hiccup must not hide good live weather
            pass
        return WeatherResult(days, current)

    return fetch
