"""A block's plan: one continuous balance with logged irrigation and a runtime cap.

Each day the engine recommends a depth from the depletion carried in from the
day before. The balance then moves on with what was actually applied: the
farmer's logged irrigation when there is a log entry, otherwise the
recommendation (assumed followed).

A recommendation longer than the block's max_runtime_h is cut to that runtime.
The rest of the refill carries to the next day, which keeps irrigating until
the root zone is back at field capacity.
"""

from collections.abc import Iterator, Mapping
from datetime import date, timedelta

from engine.balance import application_rate_mm_h, gross_depth_mm, runtime_h
from engine.catalog import get_crop
from engine.models import Block, DailyInput, PlanDay
from engine.simulate import simulate

MAX_HISTORY_DAYS = 365


def history_start(block: Block, today: date) -> date:
    """First day of the balance: planting (or season start), at most a year back."""
    earliest = today - timedelta(days=MAX_HISTORY_DAYS)
    return max(block.planting_date, earliest)


def plan_days(
    block: Block,
    daily_inputs: list[DailyInput],
    *,
    today: date,
    logged_gross_mm: Mapping[date, float] | None = None,
) -> Iterator[PlanDay]:
    """Run the balance from field capacity on the first input day.

    logged_gross_mm maps a date to the gross depth the farmer applied (summed
    if they logged more than once). Gross is converted to net with the block's
    efficiency before it enters the balance.
    """
    logged = logged_gross_mm or {}
    efficiency = block.system_params.efficiency
    if efficiency is None:
        raise ValueError("system efficiency is missing")
    rate = application_rate_mm_h(block)
    max_hours = block.system_params.max_runtime_h
    cap_net_mm = max_hours * rate * efficiency if max_hours is not None else None
    get_crop(block.crop)  # fail early on an unknown crop

    dr_mm = 0.0
    refilling = False
    for day in daily_inputs:
        dry = day.model_copy(update={"irrigation_applied_mm": 0.0})
        base = simulate(block, [dry], dr_start_mm=dr_mm)[0]
        dr_before_mm = base.dr_mm  # depletion if nothing is applied today

        net_mm = base.net_mm
        if net_mm == 0.0 and refilling and dr_before_mm > 0.0:
            net_mm = dr_before_mm
        capped = cap_net_mm is not None and net_mm > cap_net_mm
        if capped:
            assert cap_net_mm is not None
            net_mm = cap_net_mm
        refilling = capped

        gross_mm = gross_depth_mm(net_mm, efficiency)
        hours = runtime_h(gross_mm, rate)

        if day.date in logged:
            logged_mm: float | None = logged[day.date]
            applied_net_mm = logged[day.date] * efficiency
            source = "logged"
        else:
            logged_mm = None
            applied_net_mm = net_mm
            source = "assumed"

        wet = day.model_copy(update={"irrigation_applied_mm": applied_net_mm})
        dr_end_mm = simulate(block, [wet], dr_start_mm=dr_mm)[0].dr_mm

        yield PlanDay(
            **base.model_dump(
                exclude={"irrigate", "net_mm", "gross_mm", "runtime_h", "dr_mm"}
            ),
            irrigate=net_mm > 0.0,
            net_mm=net_mm,
            gross_mm=gross_mm,
            runtime_h=hours,
            dr_mm=dr_before_mm,
            rain_mm=day.rain_mm,
            observed=day.date < today,
            capped=capped,
            applied_net_mm=applied_net_mm,
            applied_source=source,
            logged_gross_mm=logged_mm,
            logged_runtime_h=runtime_h(logged_mm, rate) if logged_mm is not None else None,
            dr_end_mm=dr_end_mm,
            volume_m3=gross_mm * block.area_ha * 10.0,
        )
        dr_mm = dr_end_mm
