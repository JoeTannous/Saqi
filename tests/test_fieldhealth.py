"""Field health from satellite passes. Thresholds from engine/data/satellite.yaml."""

from datetime import date, timedelta

import pytest

from engine.fieldhealth import Observation, assess, kc_from_ndvi, usable
from engine.models import Boundary

TODAY = date(2026, 10, 16)


def obs(days_ago: int, ndvi: float, ndmi: float = 0.2, std: float = 0.05,
        pixels: int = 100) -> Observation:
    return Observation(TODAY - timedelta(days=days_ago), ndvi, std, ndmi, 0.03, pixels)


def test_no_passes_is_no_data() -> None:
    assert assess([], TODAY).status == "no_data"


def test_cloudy_passes_are_dropped() -> None:
    # Best pass sees 100 pixels; 70% floor = 70. A 40-pixel (cloudy) pass is dropped.
    kept = usable([obs(10, 0.6), obs(5, 0.2, pixels=40), obs(2, 0.62)])
    assert [o.ndvi for o in kept] == [0.6, 0.62]


def test_steady_even_field() -> None:
    # Latest 0.62 vs median of passes 7-28 days earlier (0.60, 0.61) = 0.605 -> +0.015 steady.
    h = assess([obs(20, 0.60), obs(12, 0.61), obs(2, 0.62)], TODAY)
    assert h.status == "ok" and h.age_days == 2
    assert h.ndvi_change == pytest.approx(0.015)
    assert h.vigour_trend == "steady"
    assert h.evenness == "even"  # cv = 0.05 / 0.62 = 0.08
    assert h.flags == []


def test_vigour_drop_and_drying_are_flagged() -> None:
    # NDVI 0.70 -> 0.58 (-0.12 <= -0.08), NDMI 0.30 -> 0.18 (-0.12).
    h = assess([obs(18, 0.70, 0.30), obs(10, 0.70, 0.30), obs(1, 0.58, 0.18)], TODAY)
    assert h.vigour_trend == "falling"
    assert h.moisture_trend == "falling"
    assert set(h.flags) == {"vigour_drop", "canopy_drying"}


def test_patchy_field_is_flagged() -> None:
    # cv = 0.2 / 0.5 = 0.4 > 0.30.
    h = assess([obs(1, 0.5, std=0.2)], TODAY)
    assert h.evenness == "patchy" and "patchy" in h.flags
    assert h.vigour_trend is None  # no baseline yet


def test_stale_and_small_plot() -> None:
    h = assess([obs(20, 0.5, pixels=12)], TODAY)
    assert h.status == "stale"
    assert set(h.flags) == {"stale", "small_plot"}


def test_kc_estimate() -> None:
    # fc = (0.50 - 0.15) / 0.70 = 0.5; Kd = min(1, 1.5 * 0.5) = 0.75;
    # Kc = 0.15 + (1.15 - 0.15) * 0.75 = 0.90.
    assert kc_from_ndvi(0.50, 1.15) == pytest.approx(0.90)
    assert kc_from_ndvi(0.95, 1.15) == pytest.approx(1.15)  # full cover caps at Kc_mid
    assert kc_from_ndvi(0.10, 1.15) == pytest.approx(0.15)  # bare soil


def test_boundary_must_be_a_closed_lon_lat_ring() -> None:
    ok = Boundary(type="Polygon", coordinates=[[(35.9, 33.85), (35.901, 33.85),
                                                (35.901, 33.851), (35.9, 33.85)]])
    assert ok.coordinates[0][0] == (35.9, 33.85)
    with pytest.raises(ValueError):
        Boundary(type="Polygon", coordinates=[[(35.9, 33.85), (35.901, 33.85), (35.9, 33.86)]])
    with pytest.raises(ValueError):
        Boundary(type="Polygon", coordinates=[[(200, 33.85), (35.9, 33.86), (35.8, 33.8),
                                               (200, 33.85)]])
