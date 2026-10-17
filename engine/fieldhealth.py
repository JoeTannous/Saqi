"""Read a block's satellite record: vigour, canopy moisture, trend, evenness, flags.

Inputs are Sentinel-2 passes already reduced to per-block statistics (mean and
standard deviation of NDVI and NDMI over cloud-free 10 m pixels). Everything here is
deterministic so the page and the chat show the same numbers. Thresholds live in
engine/data/satellite.yaml and are rules of thumb awaiting local calibration.

The Kc estimate is for comparison with the engine's textbook Kc only. The water
balance does not use it.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from statistics import median
from typing import Any

import yaml

_DATA = Path(__file__).resolve().parent / "data" / "satellite.yaml"


@lru_cache(maxsize=1)
def thresholds() -> dict[str, Any]:
    with _DATA.open(encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError("satellite.yaml must be a mapping")
    return loaded


@dataclass(frozen=True)
class Observation:
    """One Sentinel-2 pass over one block."""

    date: date
    ndvi: float
    ndvi_std: float
    ndmi: float
    ndmi_std: float
    valid_pixels: int


@dataclass
class FieldHealth:
    status: str  # "ok" | "no_data" | "stale"
    latest: Observation | None = None
    age_days: int | None = None
    ndvi_change: float | None = None
    ndmi_change: float | None = None
    vigour_trend: str | None = None  # rising | steady | falling
    moisture_trend: str | None = None
    evenness: str | None = None  # even | uneven | patchy
    ndvi_cv: float | None = None
    kc_estimate: float | None = None
    flags: list[str] = field(default_factory=list)
    series: list[Observation] = field(default_factory=list)
    cut_date: date | None = None  # cut crops: first pass after the latest likely cut


def usable(observations: list[Observation]) -> list[Observation]:
    """Drop cloudy or partial passes, oldest first."""
    t = thresholds()
    if not observations:
        return []
    best = max(o.valid_pixels for o in observations)
    floor = max(t["min_valid_pixels"], t["valid_fraction_of_best"] * best)
    return sorted((o for o in observations if o.valid_pixels >= floor), key=lambda o: o.date)


def kc_from_ndvi(ndvi: float, kc_mid: float) -> float:
    t = thresholds()
    fc = (ndvi - t["ndvi_bare"]) / (t["ndvi_full"] - t["ndvi_bare"])
    fc = min(max(fc, 0.0), 1.0)
    kd = min(1.0, t["ml"] * fc)
    return t["kc_min"] + (kc_mid - t["kc_min"]) * kd


def _trend(change: float | None) -> str | None:
    if change is None:
        return None
    step = thresholds()["trend_step"]
    if change >= step:
        return "rising"
    if change <= -step:
        return "falling"
    return "steady"


def last_cut(series: list[Observation], latest: Observation) -> tuple[date, float] | None:
    """Most recent cut: a pass >= cut_drop below a preceding peak >= cut_peak_ndvi.

    Returns (first pass after the cut, peak NDVI before it), or None.
    """
    t = thresholds()
    for i in range(len(series) - 1, 0, -1):
        before = [o for o in series[:i]
                  if series[i].date - o.date <= timedelta(days=t["cut_lookback_days"])]
        if not before:
            continue
        peak = max(o.ndvi for o in before)
        if peak >= t["cut_peak_ndvi"] and series[i].ndvi <= peak - t["cut_drop"]:
            # Walk back to the first low pass of this cut.
            j = i
            while j > 0 and series[j - 1].ndvi <= peak - t["cut_drop"]:
                j -= 1
            return series[j].date, peak
    return None


def assess(
    observations: list[Observation], today: date, kc_mid: float | None = None,
    *, cut_crop: bool = False,
) -> FieldHealth:
    t = thresholds()
    series = usable(observations)
    if not series:
        return FieldHealth(status="no_data")

    latest = series[-1]
    age = (today - latest.date).days
    window = [
        o for o in series
        if latest.date - timedelta(days=t["baseline_from_days"]) <= o.date
        <= latest.date - timedelta(days=t["baseline_to_days"])
    ]
    ndvi_change = latest.ndvi - median(o.ndvi for o in window) if window else None
    ndmi_change = latest.ndmi - median(o.ndmi for o in window) if window else None
    # On bare soil (low NDVI) pixel-to-pixel noise is not crop unevenness.
    cv = latest.ndvi_std / latest.ndvi if latest.ndvi >= t["min_ndvi_for_evenness"] else None
    if cv is None:
        evenness = None
    elif cv > t["patchy_cv"]:
        evenness = "patchy"
    elif cv > t["uneven_cv"]:
        evenness = "uneven"
    else:
        evenness = "even"

    flags = []
    if ndvi_change is not None and ndvi_change <= -t["drop_alert"]:
        flags.append("vigour_drop")
    if ndmi_change is not None and ndmi_change <= -t["drop_alert"]:
        flags.append("canopy_drying")
    if evenness == "patchy":
        flags.append("patchy")
    cut_date = None
    if cut_crop:
        cut = last_cut(series, latest)
        if cut is not None:
            cut_date, peak = cut
            since_cut = (latest.date - cut_date).days
            if since_cut <= t["cut_lookback_days"]:
                # A recent cut explains the drop: say so instead of raising stress alarms.
                flags = [f for f in flags if f not in ("vigour_drop", "canopy_drying")]
                flags.append("likely_cut")
            elif since_cut >= t["regrowth_days"] and latest.ndvi <= peak - t["cut_drop"]:
                flags.append("slow_regrowth")
    if age > t["stale_days"]:
        flags.append("stale")
    if latest.valid_pixels < t["small_plot_pixels"]:
        flags.append("small_plot")

    return FieldHealth(
        status="stale" if age > t["stale_days"] else "ok",
        latest=latest,
        age_days=age,
        ndvi_change=ndvi_change,
        ndmi_change=ndmi_change,
        vigour_trend=_trend(ndvi_change),
        moisture_trend=_trend(ndmi_change),
        evenness=evenness,
        ndvi_cv=cv,
        kc_estimate=kc_from_ndvi(latest.ndvi, kc_mid) if kc_mid is not None else None,
        flags=flags,
        series=series,
        cut_date=cut_date,
    )
