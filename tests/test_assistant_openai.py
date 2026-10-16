"""OpenAI-compatible chat with a scripted fake client: tool loop and errors."""

import json
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from api.assistant import make_client
from api.main import create_app
from tests.test_api import FARM_YAML, TODAY, fake_weather


def call(id_: str, name: str, args: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        id=id_, type="function", function=SimpleNamespace(name=name, arguments=json.dumps(args))
    )


def reply(
    content: str | None = None, *calls: SimpleNamespace, finish: str = "stop"
) -> SimpleNamespace:
    message = SimpleNamespace(
        role="assistant", content=content, tool_calls=list(calls) or None
    )
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)])


class FakeCompletions:
    def __init__(self, script: list[SimpleNamespace]) -> None:
        self.script = script
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(json.loads(json.dumps(kwargs, default=str)))
        return self.script.pop(0)


class FakeChat:
    def __init__(self, script: list[SimpleNamespace]) -> None:
        self.completions = FakeCompletions(script)


class FakeOpenAI:
    def __init__(self, script: list[SimpleNamespace]) -> None:
        self.chat = FakeChat(script)


def make(tmp_path: Path, script: list[SimpleNamespace]) -> tuple[TestClient, FakeOpenAI, Path]:
    farms = tmp_path / "farms"
    farms.mkdir()
    (farms / "test.yaml").write_text(FARM_YAML, encoding="utf-8")
    fake = FakeOpenAI(script)
    log = tmp_path / "log.csv"
    app = create_app(
        farms_dir=farms,
        log_path=log,
        weather=fake_weather,
        today_fn=lambda tz: TODAY,
        web_dir=tmp_path / "x",
        chat_client=fake,
    )
    return TestClient(app), fake, log


def test_farmer_report_is_logged_then_plan_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SAQI_MODEL", "gemini-3.8-flash")
    yesterday = (TODAY - timedelta(days=1)).isoformat()
    client, fake, log = make(
        tmp_path,
        [
            reply(
                None,
                call("t1", "log_irrigation",
                     {"block_id": "block-1", "date": yesterday, "runtime_h": 2}),
                finish="tool_calls",
            ),
            reply(None, call("t2", "get_plan", {"block_id": "block-1"}), finish="tool_calls"),
            reply("Logged 2 h for yesterday. No irrigation needed today."),
        ],
    )
    assert client.get("/api/assistant").json() == {"enabled": True}
    res = client.post(
        "/api/farms/test/chat",
        json={"messages": [{"role": "user", "content": "سقيت ساعتين مبارح"}], "lang": "ar"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["reply"].startswith("Logged 2 h")
    assert body["tool_calls"] == ["log_irrigation", "get_plan"]
    # 2 h at 4 mm/h = 8 mm gross, written to the pilot log.
    assert float(body["logged"][0]["gross_mm"]) == pytest.approx(8.0)
    assert log.is_file()

    first = fake.chat.completions.calls[0]
    assert first["model"] == "gemini-3.8-flash"
    assert first["max_tokens"] == 700
    assert "system" not in first
    assert first["messages"][0]["role"] == "system"
    assert "Test farm" in first["messages"][0]["content"]
    assert TODAY.isoformat() in first["messages"][0]["content"]
    assert first["messages"][1] == {"role": "user", "content": "سقيت ساعتين مبارح"}
    assert {t["function"]["name"] for t in first["tools"]} == {
        "get_plan",
        "get_history",
        "log_irrigation",
    }
    log_tool = next(t for t in first["tools"] if t["function"]["name"] == "log_irrigation")
    assert log_tool["type"] == "function"
    assert "cache_control" not in log_tool["function"]
    assert log_tool["function"]["parameters"]["required"] == ["block_id", "date"]

    plan_msg = fake.chat.completions.calls[2]["messages"][-1]
    assert plan_msg["role"] == "tool"
    assert plan_msg["tool_call_id"] == "t2"
    plan = json.loads(plan_msg["content"])
    day = next(d for d in plan["past_7_days"] if d["date"] == yesterday)
    assert day["applied"] == "logged"
    assert day["logged_runtime_text"] == "2 h"
    assert "stress_threshold_raw_mm" in plan["today"]
    assistant_plan = fake.chat.completions.calls[2]["messages"][-2]
    assert assistant_plan["tool_calls"][0]["function"]["name"] == "get_plan"


def test_tool_error_goes_back_to_the_model(tmp_path: Path) -> None:
    tomorrow = (TODAY + timedelta(days=1)).isoformat()
    client, fake, log = make(
        tmp_path,
        [
            reply(
                None,
                call("t1", "log_irrigation",
                     {"block_id": "block-1", "date": tomorrow, "runtime_h": 1}),
                finish="tool_calls",
            ),
            reply("I can only log irrigation that already happened."),
        ],
    )
    res = client.post(
        "/api/farms/test/chat",
        json={"messages": [{"role": "user", "content": "log 1h tomorrow"}]},
    )
    assert res.status_code == 200
    assert res.json()["logged"] == []
    result = fake.chat.completions.calls[1]["messages"][-1]
    assert result["role"] == "tool"
    assert result["tool_call_id"] == "t1"
    assert "future" in result["content"]
    assert not log.exists()


def test_make_client_uses_openai_when_provider_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAQI_PROVIDER", "OpenAI")
    monkeypatch.setenv("OPENAI_API_KEY", "test-gemini-key")
    monkeypatch.setenv(
        "OPENAI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/"
    )
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-be-used")
    client = make_client()
    assert client is not None
    assert type(client).__module__.startswith("openai")
    assert client.api_key == "test-gemini-key"
    assert str(client.base_url).startswith("https://generativelanguage.googleapis.com/v1beta/openai")


def test_make_client_openai_without_key_stays_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAQI_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert make_client() is None


def test_make_client_defaults_to_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SAQI_PROVIDER", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "should-not-be-used")
    client = make_client()
    assert client is not None
    assert type(client).__module__.startswith("anthropic")


def test_busy_model_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import assistant

    class Busy(Exception):
        status_code = 503

    calls: list[str] = []

    class Completions:
        def create(self, model: str, **kwargs: object) -> object:
            calls.append(model)
            if model == "main":
                raise Busy()
            return "ok"

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setenv("SAQI_FALLBACK_MODEL", "backup")
    monkeypatch.setattr(assistant, "RETRY_DELAYS_S", (0.0,))
    assert assistant._create_with_fallback(client, "main") == "ok"
    assert calls == ["main", "backup"]


def test_all_busy_raises_assistant_busy(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import assistant

    class Busy(Exception):
        status_code = 429

    class Completions:
        def create(self, model: str, **kwargs: object) -> object:
            raise Busy()

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.delenv("SAQI_FALLBACK_MODEL", raising=False)
    monkeypatch.setattr(assistant, "RETRY_DELAYS_S", (0.0,))
    with pytest.raises(assistant.AssistantBusy):
        assistant._create_with_fallback(client, "main")


def test_missing_fallback_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    from api import assistant

    class Err(Exception):
        def __init__(self, code: int) -> None:
            self.status_code = code

    calls: list[str] = []

    class Completions:
        def create(self, model: str, **kwargs: object) -> object:
            calls.append(model)
            if model == "main":
                raise Err(503)
            if model == "gone":
                raise Err(404)
            return "ok"

    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    monkeypatch.setenv("SAQI_FALLBACK_MODEL", "gone, backup")
    monkeypatch.setattr(assistant, "RETRY_DELAYS_S", (0.0,))
    assert assistant._create_with_fallback(client, "main") == "ok"
    assert calls == ["main", "gone", "backup"]


def test_thought_signature_is_sent_back() -> None:
    from api.assistant import _openai_assistant_message

    sig = {"google": {"thought_signature": "abc123"}}
    call = SimpleNamespace(
        id="c1",
        type="function",
        function=SimpleNamespace(name="get_plan", arguments='{"block_id": "block-1"}'),
        extra_content=sig,
    )
    message = SimpleNamespace(content=None, tool_calls=[call])
    out = _openai_assistant_message(message, [call])
    assert out["tool_calls"][0]["extra_content"] == sig
    assert out["tool_calls"][0]["function"]["arguments"] == '{"block_id": "block-1"}'


def test_sdk_extra_fields_are_preserved() -> None:
    from openai.types.chat import ChatCompletionMessage

    message = ChatCompletionMessage.model_validate(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "get_plan", "arguments": "{}"},
                    "extra_content": {"google": {"thought_signature": "sig"}},
                }
            ],
        }
    )
    from api.assistant import _openai_assistant_message

    out = _openai_assistant_message(message, list(message.tool_calls or []))
    assert out["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "sig"}}
