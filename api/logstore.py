"""Pilot log: append and read back. CSV on disk, or Postgres when DATABASE_URL is set.

Both stores return the same string rows the CSV file has always returned, so the
API response shapes stay the same. The engine never reads this module.
"""

import csv
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol

LOG_FIELDS = ["logged_at", "farm_id", "block_id", "date", "gross_mm", "runtime_h", "note"]

# Supabase exposes public tables through its REST API. RLS with no policies blocks
# that route. Saqi connects directly as the table owner, so it is not affected.
CREATE_SQL = """
CREATE TABLE IF NOT EXISTS pilot_log (
    id serial PRIMARY KEY,
    logged_at timestamptz NOT NULL,
    farm_id text NOT NULL,
    block_id text NOT NULL,
    date date NOT NULL,
    gross_mm real NOT NULL,
    runtime_h real NOT NULL,
    note text NOT NULL DEFAULT ''
);
ALTER TABLE pilot_log ENABLE ROW LEVEL SECURITY;
"""

INSERT_SQL = """
INSERT INTO pilot_log (logged_at, farm_id, block_id, date, gross_mm, runtime_h, note)
VALUES (%s, %s, %s, %s, %s, %s, %s)
"""

SELECT_SQL = """
SELECT logged_at, farm_id, block_id, date, gross_mm, runtime_h, note
FROM pilot_log
WHERE farm_id = %s
ORDER BY date, logged_at, id
"""


class LogStore(Protocol):
    def ensure_schema(self) -> None:
        """Create the backing store if it is missing. CSV has nothing to create."""

    def read(self, farm_id: str) -> list[dict[str, str]]:
        """Rows for one farm, oldest first. Values are strings, as in the CSV."""

    def append(self, row: dict[str, str]) -> None:
        """Add one row. Keys match LOG_FIELDS."""


class CsvLogStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def ensure_schema(self) -> None:
        return None

    def read(self, farm_id: str) -> list[dict[str, str]]:
        if not self.path.is_file():
            return []
        with self.path.open(encoding="utf-8", newline="") as handle:
            return [row for row in csv.DictReader(handle) if row["farm_id"] == farm_id]

    def append(self, row: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not self.path.is_file()
        with self.path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=LOG_FIELDS)
            if new_file:
                writer.writeheader()
            writer.writerow({key: row[key] for key in LOG_FIELDS})


class PostgresLogStore:
    """psycopg 3. The table is created on startup (and again if a request arrives first)."""

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

    def read(self, farm_id: str) -> list[dict[str, str]]:
        self.ensure_schema()
        with self._connect() as conn:
            found = conn.execute(SELECT_SQL, (farm_id,)).fetchall()
        return [_row_out(*item) for item in found]

    def append(self, row: dict[str, str]) -> None:
        self.ensure_schema()
        logged_at = datetime.fromisoformat(row["logged_at"])
        if logged_at.tzinfo is None:
            logged_at = logged_at.replace(tzinfo=UTC)
        with self._connect() as conn:
            conn.execute(
                INSERT_SQL,
                (
                    logged_at,
                    row["farm_id"],
                    row["block_id"],
                    date.fromisoformat(row["date"]),
                    float(row["gross_mm"]),
                    float(row["runtime_h"]),
                    row["note"],
                ),
            )


def _as_logged_at(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).isoformat(timespec="seconds")
    return str(value)


def _as_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _row_out(
    logged_at: Any,
    farm_id: Any,
    block_id: Any,
    day: Any,
    gross_mm: Any,
    runtime_h: Any,
    note: Any,
) -> dict[str, str]:
    return {
        "logged_at": _as_logged_at(logged_at),
        "farm_id": str(farm_id),
        "block_id": str(block_id),
        "date": _as_date(day),
        "gross_mm": f"{float(gross_mm):.2f}",
        "runtime_h": f"{float(runtime_h):.3f}",
        "note": "" if note is None else str(note),
    }
