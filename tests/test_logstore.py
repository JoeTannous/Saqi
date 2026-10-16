"""Pilot log stores: CSV on disk, and Postgres against an in-memory fake connection."""

from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.logstore import CREATE_SQL, CsvLogStore, PostgresLogStore
from api.main import create_app
from tests.test_api import FARM_YAML, TODAY, fake_weather

ROW = {
    "logged_at": "2026-10-16T08:00:00+00:00",
    "farm_id": "test",
    "block_id": "block-1",
    "date": "2026-10-15",
    "gross_mm": "8.00",
    "runtime_h": "2.000",
    "note": "pump, fault",
}


class FakeDB:
    def __init__(self) -> None:
        self.sql: list[str] = []
        self.rows: list[tuple[object, ...]] = []


class FakeConn:
    """The slice of a psycopg connection PostgresLogStore actually uses."""

    def __init__(self, db: FakeDB) -> None:
        self.db = db
        self._result: list[tuple[object, ...]] = []

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> "FakeConn":
        self.db.sql.append(sql)
        kind = sql.lstrip().split(None, 1)[0].upper()
        if kind == "CREATE":
            return self
        if kind == "INSERT":
            self.db.rows.append(tuple(params))
            return self
        if kind == "SELECT":
            farm_id = params[0]
            self._result = [row for row in self.db.rows if row[1] == farm_id]
            return self
        raise AssertionError(sql)

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._result)


def test_csv_store_keeps_the_file_format(tmp_path: Path) -> None:
    path = tmp_path / "data" / "pilot_log.csv"
    store = CsvLogStore(path)
    store.ensure_schema()
    assert not path.exists()
    store.append(ROW)
    store.append({**ROW, "farm_id": "other", "note": "elsewhere"})
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "logged_at,farm_id,block_id,date,gross_mm,runtime_h,note"
    assert len(lines) == 3
    assert store.read("test") == [ROW]
    assert store.read("other")[0]["note"] == "elsewhere"
    assert store.read("missing") == []


def test_postgres_store_roundtrip_on_a_fake_connection() -> None:
    db = FakeDB()
    store = PostgresLogStore("postgresql://example.invalid/saqi", connect=lambda: FakeConn(db))
    store.ensure_schema()
    schema = " ".join(" ".join(CREATE_SQL.split()).split()).lower()
    recorded = " ".join(" ".join(sql.split()) for sql in db.sql).lower()
    assert schema in recorded
    for column in (
        "id serial",
        "logged_at timestamptz",
        "farm_id text",
        "block_id text",
        "date date",
        "gross_mm real",
        "runtime_h real",
        "note text",
    ):
        assert column in recorded
    store.append(ROW)
    store.append({**ROW, "farm_id": "other", "note": "elsewhere"})
    assert store.read("test") == [ROW]
    assert store.read("other") == [{**ROW, "farm_id": "other", "note": "elsewhere"}]
    assert store.read("missing") == []


def test_api_log_through_the_postgres_store(tmp_path: Path) -> None:
    db = FakeDB()
    store = PostgresLogStore("postgresql://example.invalid/saqi", connect=lambda: FakeConn(db))
    farms = tmp_path / "farms"
    farms.mkdir()
    (farms / "test.yaml").write_text(FARM_YAML, encoding="utf-8")
    app = create_app(
        farms_dir=farms,
        log_store=store,
        weather=fake_weather,
        today_fn=lambda tz: TODAY,
        web_dir=tmp_path / "no-web",
        chat_client=None,
    )
    client = TestClient(app)
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    res = client.post(
        "/api/farms/test/blocks/block-1/log",
        json={"date": yesterday, "runtime_h": 2, "note": "pump fault"},
    )
    assert res.status_code == 201
    assert float(res.json()["gross_mm"]) == pytest.approx(8.0)
    assert res.json()["runtime_h"] == "2.000"

    past = client.get("/api/farms/test/plan").json()["blocks"][0]["past"]
    day = next(item for item in past if item["date"] == yesterday)
    assert day["applied_source"] == "logged"
    assert day["logged_gross_mm"] == pytest.approx(8.0)

    log = client.get("/api/farms/test/log").json()
    assert len(log) == 1
    assert log[0]["runtime_h"] == pytest.approx(2.0)
    assert log[0]["gross_mm"] == pytest.approx(8.0)
    assert log[0]["note"] == "pump fault"
    assert log[0]["date"] == yesterday
    assert "recommended_gross_mm" in log[0]
    assert "id" not in log[0]
