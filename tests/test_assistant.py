"""Claude layer with a scripted fake client: tool loop, logging, guardrails."""

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.assistant import runtime_text
from api.main import create_app
from tests.test_api import FARM_YAML, TODAY, fake_weather


def text(t: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=t)


def tool(id_: str, name: str, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=args)


class FakeMessages:
    def __init__(self, script: list[SimpleNamespace]) -> None:
        self.script = script
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(json.loads(json.dumps(kwargs, default=str)))
        return self.script.pop(0)


class FakeClient:
    def __init__(self, script: list[SimpleNamespace]) -> None:
        self.messages = FakeMessages(script)


def reply(*blocks: SimpleNamespace, stop: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(content=list(blocks), stop_reason=stop)


def make(tmp_path: Path, script: list[SimpleNamespace]) -> tuple[TestClient, FakeClient, Path]:
    farms = tmp_path / "farms"
    farms.mkdir()
    (farms / "test.yaml").write_text(FARM_YAML, encoding="utf-8")
    fake = FakeClient(script)
    log = tmp_path / "log.csv"
    app = create_app(farms_dir=farms, log_path=log, weather=fake_weather,
                     today_fn=lambda tz: TODAY, web_dir=tmp_path / "x", chat_client=fake)
    return TestClient(app), fake, log


def test_farmer_report_is_logged_then_plan_is_read(tmp_path: Path) -> None:
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    client, fake, log = make(tmp_path, [
        reply(tool("t1", "log_irrigation",
                   {"block_id": "block-1", "date": yesterday, "runtime_h": 2}), stop="tool_use"),
        reply(tool("t2", "get_plan", {"block_id": "block-1"}), stop="tool_use"),
        reply(text("Logged 2 h for yesterday. No irrigation needed today.")),
    ])
    res = client.post("/api/farms/test/chat",
                      json={"messages": [{"role": "user", "content": "سقيت ساعتين مبارح"}],
                            "lang": "ar"})
    assert res.status_code == 200
    body = res.json()
    assert body["reply"].startswith("Logged 2 h")
    assert body["tool_calls"] == ["log_irrigation", "get_plan"]
    # 2 h at 4 mm/h = 8 mm gross, written to the pilot log.
    assert float(body["logged"][0]["gross_mm"]) == pytest.approx(8.0)
    assert log.is_file()

    first = fake.messages.calls[0]
    assert "Test farm" in first["system"][0]["text"]
    assert TODAY.isoformat() in first["system"][0]["text"]
    assert {t["name"] for t in first["tools"]} == {"get_plan", "get_history", "log_irrigation"}

    # The plan tool result reached the model with the logged day and engine fields.
    plan_result = fake.messages.calls[2]["messages"][-1]["content"][0]
    plan = json.loads(plan_result["content"])
    day = next(d for d in plan["past_7_days"] if d["date"] == yesterday)
    assert day["applied"] == "logged"
    assert day["logged_runtime_text"] == "2 h"
    assert "stress_threshold_raw_mm" in plan["today"]


def test_tool_error_goes_back_to_the_model(tmp_path: Path) -> None:
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    client, fake, log = make(tmp_path, [
        reply(tool("t1", "log_irrigation",
                   {"block_id": "block-1", "date": tomorrow, "runtime_h": 1}), stop="tool_use"),
        reply(text("I can only log irrigation that already happened.")),
    ])
    res = client.post("/api/farms/test/chat",
                      json={"messages": [{"role": "user", "content": "log 1h tomorrow"}]})
    assert res.status_code == 200
    assert res.json()["logged"] == []
    result = fake.messages.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert "future" in result["content"]
    assert not log.exists()


def test_history_tool_is_capped_at_60_days(tmp_path: Path) -> None:
    client, fake, _ = make(tmp_path, [
        reply(tool("t1", "get_history", {"block_id": "block-1", "days": 400}), stop="tool_use"),
        reply(text("ok")),
    ])
    client.post("/api/farms/test/chat", json={"messages": [{"role": "user", "content": "x"}]})
    days = json.loads(fake.messages.calls[1]["messages"][-1]["content"][0]["content"])["days"]
    # Planted 20 days ago, so all 21 days up to today are returned (well under 60).
    assert days[0]["date"] == (TODAY - timedelta(days=20)).isoformat()
    assert days[-1]["date"] == TODAY.isoformat()


def test_chat_off_without_key(tmp_path: Path) -> None:
    farms = tmp_path / "farms"
    farms.mkdir()
    (farms / "test.yaml").write_text(FARM_YAML, encoding="utf-8")
    app = create_app(farms_dir=farms, log_path=tmp_path / "l.csv", weather=fake_weather,
                     today_fn=lambda tz: TODAY, web_dir=tmp_path / "x", chat_client=None)
    c = TestClient(app)
    assert c.get("/api/assistant").json() == {"enabled": False}
    res = c.post("/api/farms/test/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert res.status_code == 503


def test_last_message_must_be_from_user(tmp_path: Path) -> None:
    client, _, _ = make(tmp_path, [])
    res = client.post("/api/farms/test/chat",
                      json={"messages": [{"role": "assistant", "content": "hi"}]})
    assert res.status_code == 422


def test_runtime_text_rounds_to_five_minutes() -> None:
    assert runtime_text(4.42) == "4 h 25 min"
    assert runtime_text(2.0) == "2 h"
    assert runtime_text(0.01) == "5 min"
    assert runtime_text(0.5) == "30 min"


