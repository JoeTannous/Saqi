"""Run the daily root-zone balance for one block."""

from engine.balance import (
    application_rate_mm_h,
    depletion_mm,
    effective_rain_mm,
    gross_depth_mm,
    runtime_h,
    trigger_irrigation,
)
from engine.catalog import get_crop, get_soil
from engine.kc import kc_on_day
from engine.models import Block, DailyInput, DailyResult
from engine.soil import raw_mm, root_depth_m, taw_mm


def simulate(
    block: Block,
    daily_inputs: list[DailyInput],
    dr_start_mm: float = 0.0,
) -> list[DailyResult]:
    """Recommend irrigation for each day and update depletion from what was applied.

    The recommendation ignores irrigation_applied_mm: it is the depth to apply
    today if nothing has been applied yet. Depletion carried to the next day
    uses irrigation_applied_mm, so a plan that assumes the farmer follows the
    advice must pass that net depth back in.

    dr_start_mm is the depletion at the end of the day before the first input.
    0 means the root zone starts at field capacity.
    """
    if dr_start_mm < 0.0:
        raise ValueError("dr_start_mm must be >= 0")

    crop = get_crop(block.crop)
    soil = get_soil(block.soil_type)
    efficiency = block.system_params.efficiency
    if efficiency is None:
        raise ValueError("system efficiency is missing")
    rate = application_rate_mm_h(block)

    dr_prev = dr_start_mm
    results: list[DailyResult] = []
    previous_date = None

    for day_input in daily_inputs:
        if previous_date is not None and day_input.date <= previous_date:
            raise ValueError("daily inputs must be in increasing date order")
        previous_date = day_input.date

        day = (day_input.date - block.planting_date).days
        if day < 0:
            raise ValueError(
                f"{day_input.date.isoformat()} is before planting date "
                f"{block.planting_date.isoformat()}"
            )

        kc = kc_on_day(
            crop.kc_ini,
            crop.kc_mid,
            crop.kc_end,
            crop.l_ini,
            crop.l_dev,
            crop.l_mid,
            crop.l_late,
            day,
        )
        etc_mm = day_input.et0_mm * kc * block.kr
        peff_mm = effective_rain_mm(day_input.rain_mm)
        zr_m = root_depth_m(
            crop.zr_min_m,
            crop.zr_max_m,
            crop.l_ini,
            crop.l_dev,
            day,
            perennial=crop.perennial,
        )
        taw = taw_mm(soil.theta_fc, soil.theta_wp, zr_m)
        raw = raw_mm(crop.p, taw)

        dr_forecast = depletion_mm(dr_prev, peff_mm, 0.0, etc_mm, taw)
        irrigate, net_mm = trigger_irrigation(dr_forecast, raw)
        gross_mm = gross_depth_mm(net_mm, efficiency)
        hours = runtime_h(gross_mm, rate)
        dr_prev = depletion_mm(dr_prev, peff_mm, day_input.irrigation_applied_mm, etc_mm, taw)

        results.append(
            DailyResult(
                date=day_input.date,
                irrigate=irrigate,
                net_mm=net_mm,
                gross_mm=gross_mm,
                runtime_h=hours,
                dr_mm=dr_prev,
                raw_mm=raw,
                taw_mm=taw,
                et0_mm=day_input.et0_mm,
                kc=kc,
                etc_mm=etc_mm,
                peff_mm=peff_mm,
            )
        )

    return results
