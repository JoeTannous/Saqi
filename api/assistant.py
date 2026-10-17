"""Farm chat: explains engine numbers and logs irrigation.

The model never computes irrigation values. It can only read them through tools
that call the engine, and it writes to the pilot log through one tool.
SAQI_PROVIDER=openai uses the OpenAI SDK (Gemini or any OpenAI-format API).
Otherwise this talks to Anthropic, unchanged.
"""

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol

DEFAULT_MODEL = "claude-sonnet-5-5"
# Free-tier Gemini flash, used only when SAQI_PROVIDER=openai and SAQI_MODEL is unset.
DEFAULT_OPENAI_MODEL = "gemini-3.8-flash"
MAX_TOOL_ROUNDS = 6
MAX_TOKENS = 700


class _AnthropicClient(Protocol):
    """The slice of anthropic.Anthropic used here, so tests can pass a fake."""

    @property
    def messages(self) -> Any: ...


class _OpenAIClient(Protocol):
    """The slice of openai.OpenAI used here, so tests can pass a fake."""

    @property
    def chat(self) -> Any: ...


ChatClient = _AnthropicClient | _OpenAIClient


@dataclass
class FarmTools:
    """Engine-backed tool implementations for one farm, built by the API."""

    get_plan: Callable[[str], dict[str, Any]]
    get_history: Callable[[str, int], dict[str, Any]]
    log_irrigation: Callable[[dict[str, Any]], dict[str, Any]]
    get_field_health: Callable[[str], dict[str, Any]] | None = None


@dataclass
class ChatResult:
    reply: str
    logged: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)


TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_plan",
        "description": (
            "Today's irrigation recommendation for one block, the previous 7 days and the "
            "next 6 days, with every term of the FAO-56 water balance (ET0, Kc, ETc, rain, "
            "effective rain, depletion Dr, RAW, TAW). Use this before saying anything about "
            "whether or how long to irrigate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"block_id": {"type": "string", "description": "Block id, e.g. block-1"}},
            "required": ["block_id"],
        },
    },
    {
        "name": "get_history",
        "description": (
            "Daily balance for one block over the last N days (max 60): what was recommended, "
            "what was logged or assumed applied, rain and depletion. Use for questions about "
            "the past, totals, or comparing plan with what the farmer did."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_id": {"type": "string"},
                "days": {"type": "integer", "minimum": 1, "maximum": 60},
            },
            "required": ["block_id", "days"],
        },
    },
    {
        "name": "log_irrigation",
        "description": (
            "Record irrigation the farmer says they actually applied. Give exactly one of "
            "runtime_h (hours, decimals allowed: 2 h 30 min = 2.5) or gross_mm. Only call when "
            "the farmer clearly reports irrigation already done, with a block, a date and an "
            "amount. Do not call for plans or hypotheticals. Date cannot be in the future."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "block_id": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "runtime_h": {"type": "number"},
                "gross_mm": {"type": "number"},
                "note": {"type": "string"},
            },
            "required": ["block_id", "date"],
        },
    },
    {
        "name": "get_field_health",
        "description": (
            "Satellite view of one block from Sentinel-2: crop vigour (NDVI), canopy moisture "
            "(NDMI), their change over the last weeks, how even the field is, warning flags, "
            "and the date of the image. Use for questions like 'how is my field', 'is the "
            "crop healthy', 'compare the two plots'. Never use it for irrigation amounts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"block_id": {"type": "string"}},
            "required": ["block_id"],
        },
        "cache_control": {"type": "ephemeral"},
    },
]

_LANG_NAMES = {"ar": "Arabic", "fr": "French", "en": "English"}


def system_prompt(
    farm: dict[str, Any], blocks: list[dict[str, Any]], today: date, lang: str
) -> str:
    block_lines = "\n".join(
        f"- {b['id']}: {b['name']}, {b['crop']} on {b['soil_type']}, {b['system']}, "
        f"{b['area_ha']} ha, planted/season start {b['planting_date']}"
        + (f"; unverified textbook values: {', '.join(b['unverified'])}" if b["unverified"] else "")
        for b in blocks
    )
    return f"""You are Saqi, the irrigation assistant for the farm "{farm['name']}" in Lebanon.
You talk with the farmer, the farm manager or their irrigation specialist, usually on a phone.
Today on the farm is {today.isoformat()} ({today.strftime('%A')}).

Blocks on this farm:
{block_lines}

How Saqi works: a deterministic FAO-56 water-balance engine computes every recommendation from
weather (Open-Meteo), crop coefficients, soil and irrigation-system data. You explain its results
and record what the farmer did. You are not the calculator.

Rules:
1. Every irrigation number you state (mm, hours, minutes, which day to irrigate, percentages of
   soil water) must come from a tool result in this conversation. Never estimate, extrapolate or
   compute a new irrigation amount yourself, even if asked "roughly". If a tool doesn't give the
   number, say Saqi doesn't calculate that yet.
2. Call get_plan before answering any question about today or the coming days.
3. Give durations as "X h Y min" using runtime_text or logged_runtime_text from tool results
   (never "2.0 hours"), always with the depth and the system's rate so the farmer knows the
   intensity: "4 h 25 min (26 mm at 5.9 mm/h)". For drip, you may add the dripper flow
   (emitter_flow_lph) and the block volume (volume_m3). Round mm to one decimal.
4. When the farmer reports irrigation already done ("I ran 2 hours", "سقيت ساعتين", "j'ai arrosé
   3 h hier"), call log_irrigation. If the block, date or amount is unclear, ask one short
   question first. If the farm has one block, use it. "Today" and "yesterday" are relative to the
   farm date above. Call get_plan only after log_irrigation has returned, never in the same
   step. After logging, confirm what was recorded and give the updated advice from
   get_plan. Compare what they applied with what that day's plan recommended: if they watered
   on a day with no recommendation, or clearly more or less than recommended, say so kindly in
   one sentence (extra water is wasted water and energy; too little means irrigating sooner) and
   say when the next irrigation is now due.
5. If the farmer reports something the engine can't see (a broken pump, a different rain gauge
   reading, wet or dry soil by hand, wilting), don't change the numbers. Say what the plan
   assumes, suggest they trust what they see in the field, and log any irrigation they did.
6. Pests, diseases, fertiliser, pesticide doses, yields and prices are outside Saqi for now.
   Say so briefly and suggest asking their agronomist.
7. When a block has unverified textbook values and the question depends on them, say once that
   the values haven't been checked for this farm yet. Don't repeat it every message.
8. Write for a farmer on a phone: 1 to 4 short sentences, plain words, no headings, no tables,
   no markdown. Explain the water balance in everyday terms ("the soil has used up X mm of the
   water the roots can reach") unless the person uses technical terms first.
9. Satellite (get_field_health): Sentinel-2 images every few days at 10 m. Say "crop
   vigour" for NDVI and "leaf moisture" for NDMI, and give the image date. A vigour drop or
   drying leaves can mean water stress (blocked emitters, a leak, pump trouble), pests or
   disease: suggest walking the field, especially the weaker parts, and checking the
   emitters. "patchy" means parts of the field look much weaker than others. "likely_cut"
   (alfalfa and other cut crops) means the drop is a harvest around cut_date, not stress:
   say regrowth is expected. "slow_regrowth" means the crop hasn't recovered weeks after a
   cut: suggest checking water and the crop. A satellite
   reading never changes the irrigation amount: amounts come only from get_plan. If there is
   no outline or no clear image yet, say so. Mention kc_estimate only if asked, as
   experimental.
10. Reply in the language the person writes in. If they write in Lebanese Arabic, reply in simple
   Lebanese-friendly Arabic. If unclear, use {_LANG_NAMES.get(lang, 'English')}.
"""


def to_openai_tools(tools: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Anthropic tool definitions as OpenAI function tools. Drops cache_control."""
    converted: list[dict[str, Any]] = []
    for tool in TOOLS if tools is None else tools:
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": dict(tool["input_schema"]),
                },
            }
        )
    return converted


def run_chat(
    client: ChatClient,
    tools: FarmTools,
    system: str,
    history: list[dict[str, str]],
    *,
    model: str | None = None,
) -> ChatResult:
    """One user turn: call the model, run any tools it asks for, return the final text."""
    if _is_openai_client(client):
        return _run_openai_chat(client, tools, system, history, model=model)
    messages: list[dict[str, Any]] = [
        {"role": m["role"], "content": m["content"]} for m in history if m.get("content")
    ]
    result = ChatResult(reply="")
    use_model = model or os.environ.get("SAQI_MODEL", DEFAULT_MODEL)

    for _ in range(MAX_TOOL_ROUNDS + 1):
        response = client.messages.create(
            model=use_model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            tools=TOOLS,
            messages=messages,
        )
        content = [_block_to_dict(b) for b in response.content]
        messages.append({"role": "assistant", "content": content})

        if response.stop_reason != "tool_use":
            result.reply = "".join(b["text"] for b in content if b["type"] == "text").strip()
            return result

        uses = [b for b in content if b["type"] == "tool_use"]
        outputs: dict[str, tuple[dict[str, Any], bool]] = {}
        for block in writes_first(uses, key=lambda b: b["name"]):
            result.tool_calls.append(block["name"])
            outputs[block["id"]] = _run_tool(tools, block["name"], block["input"], result)
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": block["id"],
                "content": json.dumps(outputs[block["id"]][0], ensure_ascii=False, default=str),
                "is_error": outputs[block["id"]][1],
            }
            for block in uses
        ]
        messages.append({"role": "user", "content": tool_results})

    result.reply = "Sorry, that took too many steps. Please ask again more simply."
    return result


def _is_openai_client(client: Any) -> bool:
    """True when the client speaks the OpenAI chat-completions API."""
    completions = getattr(getattr(client, "chat", None), "completions", None)
    return callable(getattr(completions, "create", None))


def _run_openai_chat(
    client: Any,
    tools: FarmTools,
    system: str,
    history: list[dict[str, str]],
    *,
    model: str | None,
) -> ChatResult:
    """Same loop as the Anthropic path: function calls, then a final reply."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages.extend(
        {"role": item["role"], "content": item["content"]}
        for item in history
        if item.get("content")
    )
    result = ChatResult(reply="")
    use_model = model or os.environ.get("SAQI_MODEL", DEFAULT_OPENAI_MODEL)

    for _ in range(MAX_TOOL_ROUNDS + 1):
        response = _create_with_fallback(
            client,
            use_model,
            max_tokens=MAX_TOKENS,
            messages=messages,
            tools=to_openai_tools(),
            tool_choice="auto",
        )
        message = response.choices[0].message
        calls = list(message.tool_calls or [])
        messages.append(_openai_assistant_message(message, calls))
        if not calls:
            result.reply = message.content.strip() if isinstance(message.content, str) else ""
            return result

        outputs_o: dict[str, dict[str, Any]] = {}
        for call in writes_first(calls, key=lambda c: str(c.function.name)):
            name = str(call.function.name)
            result.tool_calls.append(name)
            outputs_o[call.id] = _openai_tool_output(tools, name, call.function.arguments, result)
        for call in calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(outputs_o[call.id], ensure_ascii=False, default=str),
                }
            )

    result.reply = "Sorry, that took too many steps. Please ask again more simply."
    return result


RETRY_DELAYS_S = (1.5, 4.0)
# Less "thinking" = faster replies; the engine does the maths, so little reasoning is needed.
_NO_EFFORT: set[bool] = set()


def _is_busy(exc: Exception) -> bool:
    """429 / 5xx from the provider: overloaded or rate-limited, worth retrying."""
    status = getattr(exc, "status_code", None)
    return isinstance(status, int) and (status == 429 or status >= 500)


def _create_with_fallback(client: Any, model: str, **kwargs: Any) -> Any:
    """Retry a busy model briefly, then the fallbacks in SAQI_FALLBACK_MODEL (comma-separated).

    A fallback that doesn't exist for this account (404) is skipped, not fatal.
    """
    effort = os.environ.get("SAQI_REASONING_EFFORT", "low").strip()
    if effort and "reasoning_effort" not in kwargs and not _NO_EFFORT:
        kwargs = {**kwargs, "reasoning_effort": effort}
    raw = os.environ.get("SAQI_FALLBACK_MODEL", "")
    fallbacks = [m.strip() for m in raw.split(",") if m.strip() and m.strip() != model]
    models = [model, *fallbacks]
    last: Exception | None = None
    for delay in (0.0, *RETRY_DELAYS_S):
        if delay:
            time.sleep(delay)
        for name in list(models):
            try:
                return client.chat.completions.create(model=name, **kwargs)
            except Exception as exc:  # provider SDK errors
                status = getattr(exc, "status_code", None)
                rejected = status == 400 and "reasoning" in str(exc).lower()
                if rejected and "reasoning_effort" in kwargs:
                    # This provider/model doesn't take reasoning_effort: drop it for good.
                    _NO_EFFORT.add(True)
                    kwargs = {k: v for k, v in kwargs.items() if k != "reasoning_effort"}
                    return client.chat.completions.create(model=name, **kwargs)
                if name != model and status == 404:
                    models.remove(name)
                    continue
                if not _is_busy(exc):
                    raise
                last = exc
    raise AssistantBusy() from last


class AssistantBusy(Exception):
    """Every model we tried is overloaded or rate-limited right now."""


def _openai_assistant_message(message: Any, calls: list[Any]) -> dict[str, Any]:
    """Echo the assistant turn back exactly, including provider extras.

    Gemini 3 puts a thought signature on each tool call
    (extra_content.google.thought_signature) and rejects the next request if it
    is missing, so tool calls are copied as returned, not rebuilt.
    """
    content = message.content if isinstance(message.content, str) else None
    out: dict[str, Any] = {"role": "assistant", "content": content}
    extra = _extras(message, {"role", "content", "tool_calls", "refusal", "audio",
                              "function_call", "annotations"})
    out.update(extra)
    if not calls:
        return out
    out["tool_calls"] = [_tool_call_dict(call) for call in calls]
    return out


def _extras(obj: Any, known: set[str]) -> dict[str, Any]:
    """Fields the SDK kept but doesn't model (pydantic extra), e.g. extra_content."""
    extra = getattr(obj, "model_extra", None)
    if isinstance(extra, dict):
        return {k: v for k, v in extra.items() if k not in known and v is not None}
    value = getattr(obj, "extra_content", None)
    return {"extra_content": value} if value is not None else {}


def _tool_call_dict(call: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": call.id,
        "type": getattr(call, "type", None) or "function",
        "function": {
            "name": call.function.name,
            "arguments": _arguments_text(call.function.arguments),
        },
    }
    out.update(_extras(call, {"id", "type", "function", "index"}))
    return out


def _arguments_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    return json.dumps({} if raw is None else raw, ensure_ascii=False)


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if raw is None or raw == "":
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must be a JSON object")
    return parsed


def _openai_tool_output(
    tools: FarmTools, name: str, raw_args: Any, result: ChatResult
) -> dict[str, Any]:
    try:
        args = _parse_tool_args(raw_args)
    except (ValueError, TypeError) as exc:
        return {"error": str(exc)}
    output, _is_error = _run_tool(tools, name, args, result)
    return output


WRITE_TOOLS = {"log_irrigation"}


def writes_first(items: list[Any], key: Callable[[Any], str]) -> list[Any]:
    """Run logging before reads in the same step, so a plan read sees the new log."""
    return sorted(items, key=lambda item: key(item) not in WRITE_TOOLS)


def _run_tool(
    tools: FarmTools, name: str, args: dict[str, Any], result: ChatResult
) -> tuple[dict[str, Any], bool]:
    try:
        if name == "get_plan":
            return tools.get_plan(str(args["block_id"])), False
        if name == "get_history":
            days = max(1, min(int(args.get("days", 7)), 60))
            return tools.get_history(str(args["block_id"]), days), False
        if name == "get_field_health":
            if tools.get_field_health is None:
                return {"error": "satellite data is not available"}, True
            return tools.get_field_health(str(args["block_id"])), False
        if name == "log_irrigation":
            row = tools.log_irrigation(args)
            result.logged.append(row)
            hours = float(row.get("runtime_h", 0) or 0)
            return {"logged": row, "runtime_text": runtime_text(hours)}, False
        return {"error": f"unknown tool {name}"}, True
    except (KeyError, ValueError, TypeError) as exc:
        return {"error": str(exc)}, True
    except Exception as exc:  # HTTPException from the API layer, kept generic here
        detail = getattr(exc, "detail", None) or str(exc)
        return {"error": str(detail)}, True


def _block_to_dict(block: Any) -> dict[str, Any]:
    kind = getattr(block, "type", None)
    if kind == "text":
        return {"type": "text", "text": block.text}
    if kind == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return {"type": "text", "text": ""}


def runtime_text(hours: float) -> str:
    """Hours to 'X h Y min', rounded to 5 minutes, never rounding a real set to zero."""
    minutes = int(round(hours * 60 / 5) * 5)
    if hours > 0 and minutes == 0:
        minutes = 5
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} h {m} min"
    return f"{h} h" if h else f"{m} min"


def compact_day(day: Any) -> dict[str, Any]:
    """A PlanDay trimmed and rounded for the model: fewer tokens, nothing to recompute."""
    out = {
        "date": day.date.isoformat(),
        "observed": day.observed,
        "irrigate": day.irrigate,
        "gross_mm": round(day.gross_mm, 1),
        "runtime_text": runtime_text(day.runtime_h) if day.irrigate else "",
        "volume_m3": round(day.volume_m3) if day.irrigate else 0,
        "et0_mm": round(day.et0_mm, 1),
        "kc": round(day.kc, 2),
        "etc_mm": round(day.etc_mm, 1),
        "rain_mm": round(day.rain_mm, 1),
        "effective_rain_mm": round(day.peff_mm, 1),
        "depletion_mm": round(day.dr_mm, 1),
        "stress_threshold_raw_mm": round(day.raw_mm, 1),
        "root_zone_total_taw_mm": round(day.taw_mm, 1),
        "soil_water_left_pct": round(100 * (1 - day.dr_mm / day.taw_mm)) if day.taw_mm else None,
    }
    if day.capped:
        out["capped_to_max_runtime"] = True
    if day.observed:
        out["applied"] = day.applied_source
    if day.logged_gross_mm is not None:
        # Logged days (today included): what the farmer did vs. the recommendation above.
        out["applied"] = "logged"
        out["logged_gross_mm"] = round(day.logged_gross_mm, 1)
        out["logged_runtime_text"] = runtime_text(day.logged_runtime_h or 0.0)
        out["depletion_after_logged_mm"] = round(day.dr_end_mm, 1)
    return out


def make_client() -> ChatClient | None:
    """LLM client from the environment, or None when chat is off.

    SAQI_PROVIDER=openai uses the OpenAI SDK with OPENAI_API_KEY and, when set,
    OPENAI_BASE_URL. The model name is SAQI_MODEL. Any other value keeps the
    Anthropic client, which reads ANTHROPIC_API_KEY (and ANTHROPIC_BASE_URL) itself.
    """
    if os.environ.get("SAQI_PROVIDER", "").strip().lower() == "openai":
        api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not api_key:
            return None
        from openai import OpenAI

        kwargs: dict[str, Any] = {"api_key": api_key}
        base_url = os.environ.get("OPENAI_BASE_URL", "").strip()
        if base_url:
            kwargs["base_url"] = base_url
        return OpenAI(**kwargs)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic

    return anthropic.Anthropic()
