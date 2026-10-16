"""API with fake weather: plan shape, the pilot log, and planned vs actual."""

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from engine.models import DailyInput, Farm

TODAY = date(2026, 10, 16)
FARM_YAML = """
name: Test farm
owner_whatsapp: "+961"
lat: 33.85
lon: 35.90
timezone: Asia/Beirut
blocks:
  - farm_id: test
    name: Block 1
    area_ha: 1.0
    crop: potato
    planting_days_ago: 20
    soil_type: loam
    system: drip
    system_params:
      emitter_flow_lph: 2.0
      emitter_spacing_m: 0.5
      lateral_spacing_m: 1.0
"""


def fake_weather(farm: Farm, start: date, today: date) -> list[DailyInput]:
    days = (today + timedelta(days=6) - start).days + 1
    return [
        DailyInput(date=start + timedelta(days=i), et0_mm=6.0, rain_mm=0.0) for i in range(days)
    ]


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    farms = tmp_path / "farms"
    farms.mkdir()
    (farms / "test.yaml").write_text(FARM_YAML, encoding="utf-8")
    app = create_app(
        farms_dir=farms,
        log_path=tmp_path / "log.csv",
        weather=fake_weather,
        today_fn=lambda tz: TODAY,
        web_dir=tmp_path / "no-web",
        chat_client=None,
    )
    return TestClient(app)


def test_list_farms(client: TestClient) -> None:
    farms = client.get("/api/farms").json()
    assert farms == [
        {
            "id": "test",
            "name": "Test farm",
            "lat": 33.85,
            "lon": 35.9,
            "blocks": [{"id": "block-1", "name": "Block 1", "crop": "potato"}],
        }
    ]


def test_plan_has_today_past_and_forecast(client: TestClient) -> None:
    body = client.get("/api/farms/test/plan").json()
    assert body["today"] == "2026-10-16"
    assert "owner_whatsapp" not in body["farm"]
    block = body["blocks"][0]
    assert block["today"]["date"] == "2026-10-16"
    assert len(block["past"]) == 7
    assert [d["date"] for d in block["forecast"]][0] == "2026-10-17"
    assert len(block["forecast"]) == 6
    # History runs from planting (20 days ago), not just the last week.
    assert block["history_from"] == "2026-09-26"
    # 2 L/h / (0.5 m * 1.0 m) = 4 mm/h. Drip defaults: 0.90 efficiency, 8 h cap.
    assert block["application_rate_mm_h"] == pytest.approx(4.0)
    assert block["max_runtime_h"] == pytest.approx(8.0)
    assert set(block["unverified"]) == {"crop", "soil", "system"}
    for key in ("et0_mm", "kc", "etc_mm", "peff_mm", "dr_mm", "raw_mm", "taw_mm"):
        assert key in block["today"]


def test_unknown_farm_is_404(client: TestClient) -> None:
    assert client.get("/api/farms/nope/plan").status_code == 404


def test_log_runtime_converts_to_depth_and_feeds_the_plan(client: TestClient) -> None:
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    # 2 h at 4 mm/h = 8 mm gross.
    res = client.post(
        "/api/farms/test/blocks/block-1/log",
        json={"date": yesterday, "runtime_h": 2, "note": "pump fault"},
    )
    assert res.status_code == 201
    assert float(res.json()["gross_mm"]) == pytest.approx(8.0)

    past = client.get("/api/farms/test/plan").json()["blocks"][0]["past"]
    day = next(d for d in past if d["date"] == yesterday)
    assert day["applied_source"] == "logged"
    assert day["logged_gross_mm"] == pytest.approx(8.0)
    assert day["applied_net_mm"] == pytest.approx(8.0 * 0.9)
    assert day["logged_runtime_h"] == pytest.approx(2.0)

    log = client.get("/api/farms/test/log").json()
    assert len(log) == 1
    assert log[0]["runtime_h"] == pytest.approx(2.0)
    assert log[0]["note"] == "pump fault"
    assert "recommended_gross_mm" in log[0]


def test_log_rejects_future_and_ambiguous_entries(client: TestClient) -> None:
    url = "/api/farms/test/blocks/block-1/log"
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    assert client.post(url, json={"date": tomorrow, "gross_mm": 5}).status_code == 422
    both = {"date": TODAY.isoformat(), "gross_mm": 5, "runtime_h": 1}
    assert client.post(url, json=both).status_code == 422
    assert client.post(url, json={"date": TODAY.isoformat()}).status_code == 422
    assert client.post("/api/farms/test/blocks/nope/log",
                       json={"date": TODAY.isoformat(), "gross_mm": 5}).status_code == 404


def test_empty_log(client: TestClient) -> None:
    assert client.get("/api/farms/test/log").json() == []


def test_web_page_is_served(tmp_path: Path) -> None:
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<title>Saqi</title>", encoding="utf-8")
    app = create_app(farms_dir=tmp_path, log_path=tmp_path / "l.csv", weather=fake_weather,
                     today_fn=lambda tz: TODAY, web_dir=web, chat_client=None)
    res = TestClient(app).get("/")
    assert res.status_code == 200
    assert "Saqi" in res.text
