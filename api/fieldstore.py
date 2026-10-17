"""Satellite readings per block, kept in Postgres (filled by api/sync_satellite.py).

field_index: one row per block per clear Sentinel-2 pass (NDVI / NDMI statistics).
field_map:   the latest NDVI colour map per block (a small PNG).
Both have RLS on, like the other tables, so Supabase's public REST API can't reach them.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Protocol

from engine.fieldhealth import Observation

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS field_index (
    farm_id text NOT NULL,
    block_id text NOT NULL,
    date date NOT NULL,
    ndvi real NOT NULL,
    ndvi_std real NOT NULL,
    ndmi real NOT NULL,
    ndmi_std real NOT NULL,
    valid_pixels integer NOT NULL,
    fetched_at timestamptz NOT NULL,
    PRIMARY KEY (farm_id, block_id, date)
);
ALTER TABLE field_index ENABLE ROW LEVEL SECURITY;
CREATE TABLE IF NOT EXISTS field_map (
    farm_id text NOT NULL,
    block_id text NOT NULL,
    date date NOT NULL,
    png bytea NOT NULL,
    fetched_at timestamptz NOT NULL,
    PRIMARY KEY (farm_id, block_id)
);
ALTER TABLE field_map ENABLE ROW LEVEL SECURITY
"""

UPSERT_INDEX = """
INSERT INTO field_index (farm_id, block_id, date, ndvi, ndvi_std, ndmi, ndmi_std,
                         valid_pixels, fetched_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (farm_id, block_id, date) DO UPDATE
SET ndvi = EXCLUDED.ndvi, ndvi_std = EXCLUDED.ndvi_std, ndmi = EXCLUDED.ndmi,
    ndmi_std = EXCLUDED.ndmi_std, valid_pixels = EXCLUDED.valid_pixels,
    fetched_at = EXCLUDED.fetched_at
"""

SELECT_INDEX = """
SELECT date, ndvi, ndvi_std, ndmi, ndmi_std, valid_pixels FROM field_index
WHERE farm_id = %s AND block_id = %s AND date >= %s ORDER BY date
"""

UPSERT_MAP = """
INSERT INTO field_map (farm_id, block_id, date, png, fetched_at) VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (farm_id, block_id) DO UPDATE
SET date = EXCLUDED.date, png = EXCLUDED.png, fetched_at = EXCLUDED.fetched_at
"""

SELECT_MAP = "SELECT date, png FROM field_map WHERE farm_id = %s AND block_id = %s"


@dataclass(frozen=True)
class FieldMap:
    date: date
    png: bytes


class FieldStore(Protocol):
    def ensure_schema(self) -> None: ...

    def observations(self, farm_id: str, block_id: str, since: date) -> list[Observation]: ...

    def save_observations(self, farm_id: str, block_id: str,
                          observations: Iterable[Observation], fetched_at: datetime) -> None: ...

    def latest_map(self, farm_id: str, block_id: str) -> FieldMap | None: ...

    def save_map(self, farm_id: str, block_id: str, day: date, png: bytes,
                 fetched_at: datetime) -> None: ...


class MemoryFieldStore:
    def __init__(self) -> None:
        self.index: dict[tuple[str, str, date], Observation] = {}
        self.maps: dict[tuple[str, str], FieldMap] = {}

    def ensure_schema(self) -> None:
        return None

    def observations(self, farm_id: str, block_id: str, since: date) -> list[Observation]:
        found = [o for (f, b, d), o in self.index.items()
                 if f == farm_id and b == block_id and d >= since]
        return sorted(found, key=lambda o: o.date)

    def save_observations(self, farm_id: str, block_id: str,
                          observations: Iterable[Observation], fetched_at: datetime) -> None:
        for o in observations:
            self.index[(farm_id, block_id, o.date)] = o

    def latest_map(self, farm_id: str, block_id: str) -> FieldMap | None:
        return self.maps.get((farm_id, block_id))

    def save_map(self, farm_id: str, block_id: str, day: date, png: bytes,
                 fetched_at: datetime) -> None:
        self.maps[(farm_id, block_id)] = FieldMap(day, png)


class PostgresFieldStore:
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

    def observations(self, farm_id: str, block_id: str, since: date) -> list[Observation]:
        self.ensure_schema()
        with self._connect() as conn:
            rows = conn.execute(SELECT_INDEX, (farm_id, block_id, since)).fetchall()
        return [
            Observation(d.date() if isinstance(d, datetime) else d, float(a), float(b),
                        float(c), float(e), int(n))
            for d, a, b, c, e, n in rows
        ]

    def save_observations(self, farm_id: str, block_id: str,
                          observations: Iterable[Observation], fetched_at: datetime) -> None:
        self.ensure_schema()
        params = [
            (farm_id, block_id, o.date, o.ndvi, o.ndvi_std, o.ndmi, o.ndmi_std,
             o.valid_pixels, fetched_at)
            for o in observations
        ]
        if not params:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(UPSERT_INDEX, params)

    def latest_map(self, farm_id: str, block_id: str) -> FieldMap | None:
        self.ensure_schema()
        with self._connect() as conn:
            row = conn.execute(SELECT_MAP, (farm_id, block_id)).fetchone()
        if row is None:
            return None
        day, png = row
        return FieldMap(day.date() if isinstance(day, datetime) else day, bytes(png))

    def save_map(self, farm_id: str, block_id: str, day: date, png: bytes,
                 fetched_at: datetime) -> None:
        self.ensure_schema()
        with self._connect() as conn:
            conn.execute(UPSERT_MAP, (farm_id, block_id, day, png,
                                      fetched_at.astimezone(UTC)))
