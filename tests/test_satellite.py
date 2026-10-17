"""Copernicus client (mocked HTTP), field store rules, and the satellite sync job."""

import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from api.fieldstore import MemoryFieldStore, PostgresFieldStore
from api.satellite import (
    PROCESS_URL,
    STATS_URL,
    TOKEN_URL,
    SentinelHub,
    map_request,
    map_size,
    parse_stats,
    stats_request,
)
from api.sync_satellite import sync_block
from engine.fieldhealth import Observation
from engine.models import Boundary

TODAY = date(2026, 10, 16)
NOW = datetime(2026, 10, 16, 6, 0, tzinfo=UTC)
# About 200 m x 100 m near Zahle.
FIELD = Boundary(type="Polygon", coordinates=[[
    (35.9000, 33.8500), (35.9022, 33.8500), (35.9022, 33.8509), (35.9000, 33.8509),
    (35.9000, 33.8500),
]])


def stats_item(day: str, ndvi: object, ndmi: object, samples: int = 200,
               nodata: int = 20) -> dict[str, object]:
    def band(mean: object) -> dict[str, object]:
        return {"bands": {"B0": {"stats": {"mean": mean, "stDev": 0.04,
                                           "sampleCount": samples, "noDataCount": nodata}}}}

    return {"interval": {"from": f"{day}T00:00:00Z", "to": "x"},
            "outputs": {"ndvi": band(ndvi), "ndmi": band(ndmi)}}


def test_parse_stats_keeps_clear_days_only() -> None:
    payload = {"data": [
        stats_item("2026-10-01", 0.61, 0.21),
        stats_item("2026-10-02", "NaN", "NaN"),                    # no pass that day
        stats_item("2026-10-06", 0.62, 0.22, samples=200, nodata=200),  # fully cloudy
        stats_item("2026-10-11", 0.63, 0.20),
    ], "status": "OK"}
    out = parse_stats(payload)
    assert [o.date for o in out] == [date(2026, 10, 1), date(2026, 10, 11)]
    assert out[0].valid_pixels == 180
    assert out[1].ndvi == pytest.approx(0.63)


def test_requests_use_the_field_outline_and_crs84() -> None:
    body = stats_request(FIELD, date(2026, 9, 1), TODAY)
    assert body["input"]["bounds"]["geometry"]["type"] == "Polygon"
    assert body["input"]["bounds"]["properties"]["crs"].endswith("CRS84")
    assert body["aggregation"]["timeRange"] == {"from": "2026-09-01T00:00:00Z",
                                                "to": "2026-10-17T00:00:00Z"}
    assert body["aggregation"]["aggregationInterval"] == {"of": "P1D"}
    assert "SCL" in body["aggregation"]["evalscript"]
    m = map_request(FIELD, TODAY)
    assert m["output"]["responses"][0]["format"]["type"] == "image/png"
    assert m["input"]["data"][0]["dataFilter"]["timeRange"]["from"] == "2026-10-16T00:00:00Z"


def test_map_size_keeps_proportions() -> None:
    # 0.0022 deg lon * cos(33.85 deg) = 0.00183 wide vs 0.0009 tall -> about 2:1.
    w, h = map_size(FIELD)
    assert w == 320
    assert h == pytest.approx(320 * 0.0009 / (0.0022 * 0.8306), abs=2)


def test_client_gets_a_token_once_and_calls_both_apis() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url == TOKEN_URL:
            assert b"grant_type=client_credentials" in request.content
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 600})
        assert request.headers["Authorization"] == "Bearer tok"
        if url == STATS_URL:
            return httpx.Response(200, json={"data": [stats_item("2026-10-11", 0.6, 0.2)]})
        if url == PROCESS_URL:
            return httpx.Response(200, content=b"\x89PNG fake")
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        hub = SentinelHub("id", "secret", http)
        assert hub.observations(FIELD, TODAY - timedelta(days=10), TODAY)[0].ndvi == 0.6
        assert hub.ndvi_png(FIELD, TODAY).startswith(b"\x89PNG")
    assert calls.count(TOKEN_URL) == 1


def test_from_env_needs_both_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SH_CLIENT_ID", raising=False)
    monkeypatch.setenv("SH_CLIENT_SECRET", "s")
    with httpx.Client() as http:
        assert SentinelHub.from_env(http) is None


class FakeHub:
    def __init__(self, passes: list[Observation]) -> None:
        self.passes = passes
        self.stat_calls: list[tuple[date, date]] = []
        self.map_calls: list[date] = []

    def observations(self, boundary: Boundary, start: date, end: date) -> list[Observation]:
        self.stat_calls.append((start, end))
        return [p for p in self.passes if start <= p.date <= end]

    def ndvi_png(self, boundary: Boundary, day: date) -> bytes:
        self.map_calls.append(day)
        return b"png-" + day.isoformat().encode()


def o(day: date, ndvi: float = 0.6) -> Observation:
    return Observation(day, ndvi, 0.04, 0.2, 0.03, 180)


def test_sync_backfills_then_only_rereads_recent_days() -> None:
    store = MemoryFieldStore()
    hub = FakeHub([o(TODAY - timedelta(days=30)), o(TODAY - timedelta(days=5))])
    sync_block("farm", "block-1", FIELD, TODAY, store, hub, NOW)  # type: ignore[arg-type]
    assert hub.stat_calls[0] == (TODAY - timedelta(days=120), TODAY)
    assert hub.map_calls == [TODAY - timedelta(days=5)]
    assert store.latest_map("farm", "block-1").png == b"png-2026-10-11"  # type: ignore[union-attr]

    # Second run: starts 15 days before the last stored pass, no new map (nothing newer).
    sync_block("farm", "block-1", FIELD, TODAY, store, hub, NOW)  # type: ignore[arg-type]
    assert hub.stat_calls[1] == (TODAY - timedelta(days=20), TODAY)
    assert len(hub.map_calls) == 1


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

    def cursor(self) -> "FakeConn":
        return self

    def executemany(self, sql: str, params: list[tuple[object, ...]]) -> None:
        self.sink.append((sql, params))


def test_postgres_field_store_schema_has_rls() -> None:
    sink: list[object] = []
    store = PostgresFieldStore("postgresql://x/y", connect=lambda: FakeConn(sink))
    store.save_observations("f", "b", [o(TODAY)], NOW)
    text = json.dumps([x for x in sink if isinstance(x, str)])
    assert "CREATE TABLE IF NOT EXISTS field_index" in text
    assert "CREATE TABLE IF NOT EXISTS field_map" in text
    assert text.count("ENABLE ROW LEVEL SECURITY") == 2


# --- API and chat ------------------------------------------------------------

def _app(tmp_path, store, chat=None):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from api.main import create_app
    from tests.test_api import FARM_YAML, fake_weather

    farms = tmp_path / "farms"
    farms.mkdir(exist_ok=True)
    outline = (
        "    boundary:\n      type: Polygon\n      coordinates:\n"
        "        - [[35.9, 33.85], [35.9022, 33.85], [35.9022, 33.8509], [35.9, 33.8509],"
        " [35.9, 33.85]]\n"
    )
    (farms / "test.yaml").write_text(FARM_YAML + outline, encoding="utf-8")
    app = create_app(farms_dir=farms, log_path=tmp_path / "l.csv", weather=fake_weather,
                     today_fn=lambda tz: TODAY, web_dir=tmp_path / "x", chat_client=chat,
                     field_store=store)
    return TestClient(app)


def test_plan_includes_field_health_and_map(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = MemoryFieldStore()
    store.save_observations("test", "block-1", [
        o(TODAY - timedelta(days=20), 0.70), o(TODAY - timedelta(days=12), 0.70),
        o(TODAY - timedelta(days=2), 0.58),
    ], NOW)
    store.save_map("test", "block-1", TODAY - timedelta(days=2), b"\x89PNGmap", NOW)
    client = _app(tmp_path, store)
    field = client.get("/api/farms/test/plan").json()["blocks"][0]["field"]
    assert field["status"] == "ok"
    assert field["date"] == (TODAY - timedelta(days=2)).isoformat()
    assert field["ndvi_change"] == pytest.approx(-0.12)
    assert "vigour_drop" in field["flags"]
    assert field["map_date"] == field["date"]
    assert len(field["series"]) == 3
    png = client.get("/api/farms/test/blocks/block-1/ndvi.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"


def test_block_without_data_says_so(tmp_path) -> None:  # type: ignore[no-untyped-def]
    client = _app(tmp_path, MemoryFieldStore())
    field = client.get("/api/farms/test/plan").json()["blocks"][0]["field"]
    assert field["status"] == "no_data"
    assert client.get("/api/farms/test/blocks/block-1/ndvi.png").status_code == 404


def test_chat_tool_returns_field_health(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from tests.test_assistant import FakeClient, reply, text, tool

    store = MemoryFieldStore()
    store.save_observations("test", "block-1", [o(TODAY - timedelta(days=3), 0.5)], NOW)
    fake = FakeClient([
        reply(tool("t1", "get_field_health", {"block_id": "block-1"}), stop="tool_use"),
        reply(text("Your crop looks fine.")),
    ])
    client = _app(tmp_path, store, chat=fake)
    res = client.post("/api/farms/test/chat",
                      json={"messages": [{"role": "user", "content": "how is my field?"}]})
    assert res.json()["tool_calls"] == ["get_field_health"]
    result = json.loads(fake.messages.calls[1]["messages"][-1]["content"][0]["content"])
    assert result["ndvi"] == 0.5
    # Engine Kc today and the experimental satellite estimate sit side by side.
    assert result["engine_kc_today"] == pytest.approx(0.5)
    assert result["kc_estimate"] == pytest.approx(0.9)
    assert len(result["recent_passes"]) == 1
