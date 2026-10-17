"""FastAPI app: farm plans, the pilot log, and the web page.

Farms load from farms/*.yaml if that folder has any, else examples/*.yaml.
The pilot log is a CSV (data/pilot_log.csv) unless DATABASE_URL is set, in which
case it is a Postgres table created on startup. If SAQI_ACCESS_CODE is set, every
/api route requires that code; GET /healthz stays open for uptime pings.

Run: uvicorn api.main:app --reload   then open http://127.0.0.1:8000
"""

import hmac
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx
import yaml
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from starlette.middleware.base import BaseHTTPMiddleware

from api.assistant import (
    FarmTools,
    compact_day,
    make_client,
    run_chat,
    system_prompt,
)
from api.fieldstore import FieldStore, MemoryFieldStore, PostgresFieldStore
from api.ids import slug
from api.logstore import CsvLogStore, LogStore, PostgresLogStore
from api.weatherstore import (
    PostgresWeatherStore,
    WeatherResult,
    WeatherStore,
    layered_weather,
)
from engine.balance import application_rate_mm_h
from engine.catalog import get_crop, get_soil, load_systems
from engine.cli import FarmConfig, farm_today, load_farm
from engine.fieldhealth import FieldHealth, assess
from engine.inputs import full_window
from engine.models import Block, DailyInput, Farm, PlanDay
from engine.plan import history_start, plan_days

ROOT = Path(__file__).resolve().parent.parent
WeatherFn = Callable[[Farm, date, date], "list[DailyInput] | WeatherResult"]
PAST_DAYS = 7
SATELLITE_DAYS = 90
COOKIE_NAME = "saqi_code"


def load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=value lines). Real environment variables win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=2000)


class ChatIn(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    lang: Literal["ar", "fr", "en"] = "en"


class LoginIn(BaseModel):
    code: str = Field(min_length=1, max_length=200)


def codes_match(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


def code_from(request: Request, expected: str) -> bool:
    given = [request.headers.get("x-saqi-code"), request.cookies.get(COOKIE_NAME)]
    return any(item is not None and codes_match(item, expected) for item in given)


class AccessCodeMiddleware(BaseHTTPMiddleware):
    """Require SAQI_ACCESS_CODE on /api, via header X-Saqi-Code or the login cookie."""

    def __init__(self, app: Any, code: str) -> None:
        super().__init__(app)
        self._code = code

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        path = request.url.path
        if (
            request.method != "OPTIONS"
            and path.startswith("/api")
            and path != "/api/login"
            and not code_from(request, self._code)
        ):
            return JSONResponse({"detail": "Access code required"}, status_code=401)
        return await call_next(request)


class LogEntryIn(BaseModel):
    """What the farmer reports: a depth or a runtime, not both."""

    date: date
    gross_mm: float | None = Field(default=None, gt=0, le=500)
    runtime_h: float | None = Field(default=None, gt=0, le=48)
    note: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _one_amount(self) -> "LogEntryIn":
        if (self.gross_mm is None) == (self.runtime_h is None):
            raise ValueError("give either gross_mm or runtime_h")
        return self


def default_farms_dir() -> Path:
    farms = ROOT / "farms"
    if farms.is_dir() and any(farms.glob("*.yaml")):
        return farms
    return ROOT / "examples"


def open_meteo_weather(cache_dir: Path) -> WeatherFn:
    def fetch(farm: Farm, start: date, today: date) -> list[DailyInput]:
        with httpx.Client(timeout=30.0, headers={"User-Agent": "saqi/0.1"}) as client:
            return full_window(farm, start, today, client, cache_dir)

    return fetch


def create_app(
    farms_dir: Path | None = None,
    log_path: Path | None = None,
    log_store: LogStore | None = None,
    weather: WeatherFn | None = None,
    today_fn: Callable[[str], date] | None = None,
    web_dir: Path | None = None,
    chat_client: Any = "auto",
    access_code: str | None = None,
    weather_store: WeatherStore | None = None,
    field_store: FieldStore | None = None,
) -> FastAPI:
    farms_root = farms_dir or default_farms_dir()
    if field_store is None:
        field_url = os.environ.get("DATABASE_URL", "").strip()
        field_store = PostgresFieldStore(field_url) if field_url else MemoryFieldStore()
    fields: FieldStore = field_store
    if weather_store is None and weather is None:
        weather_url = os.environ.get("DATABASE_URL", "").strip()
        if weather_url:
            weather_store = PostgresWeatherStore(weather_url)
    live_weather = weather or open_meteo_weather(ROOT / ".cache")
    get_weather: WeatherFn = (
        layered_weather(weather_store, live_weather)  # type: ignore[arg-type]
        if weather_store is not None
        else live_weather
    )
    local_today = today_fn or farm_today
    static_dir = web_dir if web_dir is not None else ROOT / "web"
    if chat_client == "auto":
        load_dotenv(ROOT / ".env")
        chat_client = make_client()
    if log_store is not None:
        store = log_store
    elif log_path is not None:
        store = CsvLogStore(log_path)
    else:
        database_url = os.environ.get("DATABASE_URL", "").strip()
        store = (
            PostgresLogStore(database_url)
            if database_url
            else CsvLogStore(ROOT / "data" / "pilot_log.csv")
        )
    code = access_code if access_code is not None else os.environ.get("SAQI_ACCESS_CODE", "")
    code = code.strip()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        store.ensure_schema()
        if weather_store is not None:
            weather_store.ensure_schema()
        fields.ensure_schema()
        yield

    app = FastAPI(title="Saqi", version="0.1.0", lifespan=lifespan)
    # The last middleware added is the outermost. CORS stays outside the access
    # check so a 401 still carries the CORS headers.
    if code:
        app.add_middleware(AccessCodeMiddleware, code=code)
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def farm_paths() -> dict[str, Path]:
        return {path.stem: path for path in sorted(farms_root.glob("*.yaml"))}

    def load(farm_id: str) -> FarmConfig:
        path = farm_paths().get(farm_id)
        if path is None:
            raise HTTPException(404, f"No farm called {farm_id!r}")
        with path.open(encoding="utf-8") as handle:
            tz = (yaml.safe_load(handle) or {}).get("timezone", "UTC")
        return load_farm(path, today=local_today(tz))

    def find_block(config: FarmConfig, block_id: str) -> Block:
        for block in config.blocks:
            if slug(block.name) == block_id:
                return block
        raise HTTPException(404, f"No block called {block_id!r}")

    def read_log(farm_id: str) -> list[dict[str, str]]:
        return store.read(farm_id)

    def logged_gross(rows: list[dict[str, str]], block_id: str) -> dict[date, float]:
        totals: dict[date, float] = {}
        for row in rows:
            if row["block_id"] == block_id:
                day = date.fromisoformat(row["date"])
                totals[day] = totals.get(day, 0.0) + float(row["gross_mm"])
        return totals

    def block_plans(
        config: FarmConfig, farm_id: str, meta: dict[str, Any] | None = None
    ) -> list[tuple[Block, list[PlanDay]]]:
        today = config.today
        start = min(history_start(block, today) for block in config.blocks)
        try:
            fetched = get_weather(config.farm, start, today)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(502, f"Weather is unavailable: {exc}") from exc
        if isinstance(fetched, WeatherResult):
            inputs, fetched_at = fetched.days, fetched.fetched_at
        else:
            inputs, fetched_at = fetched, None
        if meta is not None:
            meta["weather_fetched_at"] = fetched_at
        rows = read_log(farm_id)
        plans = []
        for block in config.blocks:
            own_start = history_start(block, today)
            usable = [day for day in inputs if day.date >= own_start]
            days = list(
                plan_days(
                    block,
                    usable,
                    today=today,
                    logged_gross_mm=logged_gross(rows, slug(block.name)),
                )
            )
            plans.append((block, days))
        return plans

    def field_health(farm_id: str, block: Block, today: date) -> FieldHealth | None:
        if block.boundary is None:
            return None
        since = today - timedelta(days=SATELLITE_DAYS)
        observations = fields.observations(farm_id, slug(block.name), since)
        crop = get_crop(block.crop)
        return assess(observations, today, kc_mid=crop.kc_mid, cut_crop=crop.cut_crop)

    def field_summary(farm_id: str, block: Block, today: date) -> dict[str, Any] | None:
        health = field_health(farm_id, block, today)
        if health is None:
            return None
        latest = health.latest
        mapped = fields.latest_map(farm_id, slug(block.name)) if latest else None
        return {
            "status": health.status,
            "date": latest.date if latest else None,
            "age_days": health.age_days,
            "ndvi": _r(latest.ndvi, 2) if latest else None,
            "ndmi": _r(latest.ndmi, 2) if latest else None,
            "ndvi_change": _r(health.ndvi_change, 2),
            "ndmi_change": _r(health.ndmi_change, 2),
            "vigour_trend": health.vigour_trend,
            "moisture_trend": health.moisture_trend,
            "evenness": health.evenness,
            "flags": health.flags,
            "cut_date": health.cut_date,
            "kc_estimate": _r(health.kc_estimate, 2),
            "valid_pixels": latest.valid_pixels if latest else None,
            "map_date": mapped.date if mapped else None,
            "series": [
                {"date": o.date, "ndvi": _r(o.ndvi, 3), "ndmi": _r(o.ndmi, 3)}
                for o in health.series
            ],
        }

    @app.get("/api/farms/{farm_id}/blocks/{block_id}/ndvi.png")
    def ndvi_map(farm_id: str, block_id: str) -> Response:
        config = load(farm_id)
        find_block(config, block_id)
        mapped = fields.latest_map(farm_id, block_id)
        if mapped is None:
            raise HTTPException(404, "No satellite map for this block yet")
        return Response(
            mapped.png,
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/api/login")
    def login(body: LoginIn, request: Request, response: Response) -> dict[str, bool]:
        if not code:
            raise HTTPException(404, "No access code is set")
        if not codes_match(body.code, code):
            raise HTTPException(401, "Wrong access code")
        response.set_cookie(
            key=COOKIE_NAME,
            value=code,
            httponly=True,
            samesite="lax",
            secure=request.url.scheme == "https",
            max_age=60 * 60 * 24 * 180,
            path="/",
        )
        return {"ok": True}

    @app.get("/api/farms")
    def list_farms() -> list[dict[str, Any]]:
        out = []
        for farm_id in farm_paths():
            config = load(farm_id)
            out.append(
                {
                    "id": farm_id,
                    "name": config.farm.name,
                    "lat": config.farm.lat,
                    "lon": config.farm.lon,
                    "blocks": [
                        {"id": slug(b.name), "name": b.name, "crop": b.crop} for b in config.blocks
                    ],
                }
            )
        return out

    @app.get("/api/farms/{farm_id}/plan")
    def farm_plan(farm_id: str) -> dict[str, Any]:
        config = load(farm_id)
        today = config.today
        blocks_out = []
        meta: dict[str, Any] = {}
        for block, days in block_plans(config, farm_id, meta):
            by_date = {day.date: day for day in days}
            week_ago = today - timedelta(days=PAST_DAYS)
            if today not in by_date:
                raise HTTPException(502, "Weather has no row for today")
            blocks_out.append(
                {
                    **block_info(block),
                    "today": by_date[today],
                    "past": [d for d in days if week_ago <= d.date < today],
                    "forecast": [d for d in days if d.date > today],
                    "history_from": days[0].date if days else None,
                    "field": field_summary(farm_id, block, today),
                }
            )
        return {
            "farm": {"id": farm_id, **config.farm.model_dump(exclude={"owner_whatsapp"})},
            "today": today,
            "weather_fetched_at": meta.get("weather_fetched_at"),
            "blocks": blocks_out,
        }

    def write_log(config: FarmConfig, farm_id: str, block_id: str, entry: LogEntryIn) -> dict:
        block = find_block(config, block_id)
        if entry.date > config.today:
            raise HTTPException(422, "Can't log irrigation for a future date")
        if entry.date < block.planting_date:
            raise HTTPException(422, "That date is before the block was planted")
        rate = application_rate_mm_h(block)
        if entry.gross_mm is not None:
            gross = entry.gross_mm
            hours = gross / rate
        else:
            assert entry.runtime_h is not None
            hours = entry.runtime_h
            gross = hours * rate
        row = {
            "logged_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "farm_id": farm_id,
            "block_id": block_id,
            "date": entry.date.isoformat(),
            "gross_mm": f"{gross:.2f}",
            "runtime_h": f"{hours:.3f}",
            "note": entry.note.strip(),
        }
        store.append(row)
        return row

    @app.post("/api/farms/{farm_id}/blocks/{block_id}/log", status_code=201)
    def add_log(farm_id: str, block_id: str, entry: LogEntryIn) -> dict[str, Any]:
        return write_log(load(farm_id), farm_id, block_id, entry)

    def farm_tools(config: FarmConfig, farm_id: str) -> FarmTools:
        # One chat turn can call several tools; compute the farm plan once per turn
        # and only again after a log changes it.
        cache: dict[str, list[tuple[Block, list[PlanDay]]]] = {}

        def plans() -> list[tuple[Block, list[PlanDay]]]:
            if "plans" not in cache:
                cache["plans"] = block_plans(config, farm_id)
            return cache["plans"]

        def days_for(block_id: str) -> tuple[Block, list[PlanDay]]:
            for block, days in plans():
                if slug(block.name) == block_id:
                    return block, days
            raise HTTPException(404, f"No block called {block_id!r}")

        def get_plan(block_id: str) -> dict[str, Any]:
            block, days = days_for(block_id)
            today = config.today
            info = block_info(block)
            return {
                "block": {k: info[k] for k in ("id", "name", "crop", "soil_type", "system",
                                                "area_ha", "application_rate_mm_h",
                                                "emitter_flow_lph", "max_runtime_h",
                                                "unverified")},
                "today": next(compact_day(d) for d in days if d.date == today),
                "past_7_days": [
                    compact_day(d) for d in days
                    if today - timedelta(days=PAST_DAYS) <= d.date < today
                ],
                "next_days": [compact_day(d) for d in days if d.date > today],
                "note": "Past days without a log are assumed to have followed the plan.",
            }

        def get_history(block_id: str, n: int) -> dict[str, Any]:
            _, days = days_for(block_id)
            start = config.today - timedelta(days=n)
            return {
                "days": [compact_day(d) for d in days if start <= d.date <= config.today],
            }

        def log_irrigation(args: dict[str, Any]) -> dict[str, Any]:
            entry = LogEntryIn(
                date=args["date"],
                runtime_h=args.get("runtime_h"),
                gross_mm=args.get("gross_mm"),
                note=str(args.get("note", ""))[:500],
            )
            row = write_log(config, farm_id, str(args["block_id"]), entry)
            cache.clear()
            return row

        def get_field_health(block_id: str) -> dict[str, Any]:
            block = find_block(config, block_id)
            summary = field_summary(farm_id, block, config.today)
            if summary is None:
                return {"status": "no_boundary",
                        "note": "This block has no field outline, so there is no satellite data."}
            series = summary.pop("series")
            summary["recent_passes"] = series[-8:]
            summary["engine_kc_today"] = next(
                (_r(d.kc, 2) for b, days in plans()
                 if slug(b.name) == block_id for d in days if d.date == config.today),
                None,
            )
            summary["notes"] = (
                "Sentinel-2, 10 m pixels, a pass every few days; cloudy passes are skipped. "
                "ndvi = crop vigour/greenness (bare soil ~0.1-0.2, dense crop ~0.8). "
                "ndmi = canopy water content. Changes compare the latest pass with passes "
                "7-28 days earlier. kc_estimate is experimental, from NDVI, not used for "
                "irrigation amounts."
            )
            return summary

        return FarmTools(get_plan=get_plan, get_history=get_history,
                         log_irrigation=log_irrigation, get_field_health=get_field_health)

    @app.get("/api/assistant")
    def assistant_status() -> dict[str, Any]:
        return {"enabled": chat_client is not None}

    @app.post("/api/farms/{farm_id}/chat")
    def chat(farm_id: str, body: ChatIn) -> dict[str, Any]:
        if chat_client is None:
            raise HTTPException(
                503, "Chat is off: set ANTHROPIC_API_KEY or OPENAI_API_KEY in .env"
            )
        if body.messages[-1].role != "user":
            raise HTTPException(422, "The last message must be from the user")
        config = load(farm_id)
        farm_info = {"id": farm_id, "name": config.farm.name}
        system = system_prompt(farm_info, [block_info(b) for b in config.blocks],
                               config.today, body.lang)
        try:
            result = run_chat(
                chat_client,
                farm_tools(config, farm_id),
                system,
                [m.model_dump() for m in body.messages],
            )
        except HTTPException:
            raise
        except Exception as exc:  # provider API errors and network failures
            raise HTTPException(502, f"The assistant is unavailable: {exc}") from exc
        return {"reply": result.reply, "logged": result.logged, "tool_calls": result.tool_calls}

    @app.get("/api/farms/{farm_id}/log")
    def farm_log(farm_id: str) -> list[dict[str, Any]]:
        config = load(farm_id)
        rows = read_log(farm_id)
        if not rows:
            return []
        plans = {slug(block.name): days for block, days in block_plans(config, farm_id)}
        out = []
        for row in rows:
            day = date.fromisoformat(row["date"])
            planned = next((d for d in plans.get(row["block_id"], []) if d.date == day), None)
            out.append(
                {
                    **row,
                    "gross_mm": float(row["gross_mm"]),
                    "runtime_h": float(row["runtime_h"]),
                    "recommended_gross_mm": planned.gross_mm if planned else None,
                    "recommended_runtime_h": planned.runtime_h if planned else None,
                }
            )
        return sorted(out, key=lambda r: (r["date"], r["logged_at"]), reverse=True)

    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="web")
    return app


def _r(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def block_info(block: Block) -> dict[str, Any]:
    crop = get_crop(block.crop)
    soil = get_soil(block.soil_type)
    system = load_systems().get(block.system)
    params = block.system_params
    return {
        "id": slug(block.name),
        "name": block.name,
        "crop": block.crop,
        "soil_type": block.soil_type,
        "system": block.system,
        "area_ha": block.area_ha,
        "planting_date": block.planting_date,
        "perennial": crop.perennial,
        "efficiency": params.efficiency,
        "application_rate_mm_h": application_rate_mm_h(block),
        "emitter_flow_lph": params.emitter_flow_lph,
        "max_runtime_h": params.max_runtime_h,
        "unverified": [
            name
            for name, flag in (
                ("crop", crop.verify),
                ("soil", soil.verify),
                ("system", system.verify if system else False),
            )
            if flag
        ],
    }


app = create_app()
