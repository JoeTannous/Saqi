"""Command line plan: one table per block, from Open-Meteo weather and the engine."""

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import yaml

from engine.models import Block, DailyInput, DailyResult, Farm

__all__ = ["daily_inputs_for", "simulate_plan", "plan_block", "load_farm", "run", "main"]
from engine.inputs import daily_inputs_for
from engine.plan import plan_days

_COLUMNS = (
    "{date:<10}  {source:<8}  {et0:>5}  {rain:>5}  {kc:>4}  "
    "{etc:>5}  {dr:>6}  {raw:>6}  {irrigate:>9}  {gross:>8}  {runtime:>7}"
)
_HEADER = _COLUMNS.format(
    date="date",
    source="source",
    et0="ET0",
    rain="rain",
    kc="Kc",
    etc="ETc",
    dr="Dr",
    raw="RAW",
    irrigate="irrigate?",
    gross="gross mm",
    runtime="runtime",
)


@dataclass(frozen=True)
class FarmConfig:
    """A farm file plus the local date used to resolve relative planting dates."""

    farm: Farm
    blocks: list[Block]
    today: date


@dataclass(frozen=True)
class BlockPlan:
    """One block's weather, the engine results, and days dropped before planting."""

    block: Block
    inputs: list[DailyInput]
    results: list[DailyResult]
    skipped_days: int


def farm_today(timezone: str, now: datetime | None = None) -> date:
    """Calendar date on the farm. The laptop clock is not the farm clock."""
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone {timezone!r}") from exc
    if now is None:
        return datetime.now(zone).date()
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(zone).date()


def load_farm(path: Path, today: date | None = None) -> FarmConfig:
    """Load a farm yaml. planting_days_ago is counted back from `today`."""
    with path.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must be a farm mapping")

    raw = dict(loaded)
    blocks_raw = raw.pop("blocks", None)
    if not isinstance(blocks_raw, list) or len(blocks_raw) == 0:
        raise ValueError(f"{path} needs at least one block")

    farm = Farm.model_validate(raw)
    if today is None:
        today = farm_today(farm.timezone)
    blocks = [_load_block(item, today, index) for index, item in enumerate(blocks_raw, start=1)]
    return FarmConfig(farm=farm, blocks=blocks, today=today)


def simulate_plan(block: Block, daily_inputs: list[DailyInput]) -> list[DailyResult]:
    """Recommend each day and assume the farmer applied it. See engine.plan.plan_days."""
    today = daily_inputs[-1].date + timedelta(days=1) if daily_inputs else date.today()
    return list(plan_days(block, daily_inputs, today=today))


def plan_block(block: Block, daily_inputs: list[DailyInput]) -> BlockPlan:
    """Drop days before planting. Depletion then starts at field capacity."""
    usable = [day for day in daily_inputs if day.date >= block.planting_date]
    return BlockPlan(
        block=block,
        inputs=usable,
        results=simulate_plan(block, usable),
        skipped_days=len(daily_inputs) - len(usable),
    )


def format_runtime(hours: float) -> str:
    """Hours as h:mm. Half a minute rounds to the nearest minute."""
    minutes = int(round(hours * 60))
    if minutes < 0:
        raise ValueError("runtime cannot be negative")
    whole, mins = divmod(minutes, 60)
    return f"{whole}:{mins:02d}"


def format_report(config: FarmConfig, plans: list[BlockPlan]) -> str:
    """One aligned table per block. Past dates are observed; today and after are forecast."""
    sections = [_format_block(config, plan) for plan in plans]
    return "\n\n".join(sections) + "\n"


def run(
    path: Path,
    backfill_from: date | None = None,
    *,
    client: httpx.Client | None = None,
    cache_dir: Path = Path(".cache"),
    today: date | None = None,
) -> str:
    """Load the farm, fetch weather, and return the tables."""
    config = load_farm(path, today=today)
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=30.0, headers={"User-Agent": "saqi/0.1"})
    try:
        inputs = daily_inputs_for(
            config.farm,
            config.today,
            backfill_from,
            client,
            cache_dir,
        )
        plans = [plan_block(block, inputs) for block in config.blocks]
    finally:
        if owns_client:
            client.close()
    return format_report(config, plans)


def main(argv: list[str] | None = None) -> int:
    """`python -m engine.cli --farm examples/bekaa_potato.yaml [--backfill-from YYYY-MM-DD]`."""
    parser = argparse.ArgumentParser(
        description="Print a per-block irrigation plan from the FAO-56 engine.",
    )
    parser.add_argument("--farm", required=True, type=Path, help="Path to a farm yaml file.")
    parser.add_argument(
        "--backfill-from",
        type=date.fromisoformat,
        default=None,
        help="Archive weather from this date through yesterday.",
    )
    args = parser.parse_args(argv)
    try:
        report = run(args.farm, args.backfill_from)
    except (OSError, ValueError, KeyError) as exc:
        print(exc, file=sys.stderr)
        return 1
    sys.stdout.write(report)
    return 0


def _load_block(item: object, today: date, index: int) -> Block:
    if not isinstance(item, dict):
        raise ValueError(f"block {index} must be a mapping")
    data = dict(item)
    days_ago = data.pop("planting_days_ago", None)
    has_date = "planting_date" in data
    if days_ago is not None and has_date:
        raise ValueError(f"block {index} sets planting_date and planting_days_ago")
    if days_ago is None and not has_date:
        raise ValueError(f"block {index} needs planting_date or planting_days_ago")
    if days_ago is not None:
        if isinstance(days_ago, bool) or not isinstance(days_ago, int):
            raise ValueError(f"block {index} planting_days_ago must be a whole number of days")
        if days_ago < 0:
            raise ValueError(f"block {index} planting_days_ago must be >= 0")
        data["planting_date"] = today - timedelta(days=days_ago)
    return Block.model_validate(data)


def _format_block(config: FarmConfig, plan: BlockPlan) -> str:
    block = plan.block
    lines = [
        f"{config.farm.name} - {block.name} ({block.crop}, {block.soil_type}, {block.system})"
    ]
    if plan.skipped_days == 1:
        lines.append(f"1 day before planting ({block.planting_date.isoformat()}) is omitted")
    elif plan.skipped_days > 1:
        planted = block.planting_date.isoformat()
        lines.append(f"{plan.skipped_days} days before planting ({planted}) are omitted")
    if not plan.results:
        lines.append(f"no days on or after planting ({block.planting_date.isoformat()})")
        return "\n".join(lines)

    lines.append(_HEADER)
    for day_input, result in zip(plan.inputs, plan.results, strict=True):
        source = "observed" if result.date < config.today else "forecast"
        lines.append(
            _COLUMNS.format(
                date=result.date.isoformat(),
                source=source,
                et0=f"{result.et0_mm:.1f}",
                rain=f"{day_input.rain_mm:.1f}",
                kc=f"{result.kc:.2f}",
                etc=f"{result.etc_mm:.1f}",
                dr=f"{result.dr_mm:.1f}",
                raw=f"{result.raw_mm:.1f}",
                irrigate="yes" if result.irrigate else "no",
                gross=f"{result.gross_mm:.1f}",
                runtime=format_runtime(result.runtime_h),
            )
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
