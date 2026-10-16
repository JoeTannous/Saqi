"""Daily root-zone balance, the irrigation trigger, and system runtime."""

from engine.models import Block


def effective_rain_mm(rain_mm: float) -> float:
    """P < 5 mm is ignored. Otherwise Peff = 0.8 × P."""
    if rain_mm < 5.0:
        return 0.0
    return 0.8 * rain_mm


def depletion_mm(
    dr_prev_mm: float,
    peff_mm: float,
    irrigation_mm: float,
    etc_mm: float,
    taw: float,
) -> float:
    """End-of-day depletion. Dr = clamp(Dr_prev − Peff − I + ETc, 0, TAW)."""
    dr = dr_prev_mm - peff_mm - irrigation_mm + etc_mm
    if dr < 0.0:
        return 0.0
    if dr > taw:
        return taw
    return dr


def trigger_irrigation(dr_forecast_mm: float, raw: float) -> tuple[bool, float]:
    """Irrigate when today's forecast depletion reaches RAW.

    Net depth is that depletion, which refills the root zone to field capacity.
    """
    irrigate = dr_forecast_mm >= raw
    net_mm = dr_forecast_mm if irrigate else 0.0
    return irrigate, net_mm


def gross_depth_mm(net_mm: float, efficiency: float) -> float:
    """Gross depth = net / efficiency. Zero net stays zero."""
    if net_mm == 0.0:
        return 0.0
    return net_mm / efficiency


def drip_application_rate_mm_h(
    emitter_flow_lph: float,
    emitter_spacing_m: float,
    lateral_spacing_m: float,
) -> float:
    """mm/h = emitter flow (L/h) / (emitter spacing × lateral spacing), m²."""
    return emitter_flow_lph / (emitter_spacing_m * lateral_spacing_m)


def application_rate_mm_h(block: Block) -> float:
    """Drip rate from the emitter layout. Other systems use their mm/h rate."""
    params = block.system_params
    if block.system == "drip":
        flow = params.emitter_flow_lph
        spacing = params.emitter_spacing_m
        lateral = params.lateral_spacing_m
        if flow is None or spacing is None or lateral is None:
            raise ValueError("drip system is missing emitter flow or spacing")
        return drip_application_rate_mm_h(flow, spacing, lateral)

    rate = params.application_rate_mm_h
    if rate is None:
        raise ValueError(f"{block.system} system is missing application_rate_mm_h")
    return rate


def runtime_h(gross_mm: float, rate_mm_h: float) -> float:
    """Hours to apply gross_mm at rate_mm_h. Zero depth takes no time."""
    if gross_mm == 0.0:
        return 0.0
    return gross_mm / rate_mm_h
