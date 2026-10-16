"""Kc by day. Hand checks use FAO-56 equation 66 with tomato stages 30/40/45/30."""

import pytest

from engine.kc import kc_on_day

# Tomato: Kc 0.60 / 1.15 / 0.80. Day 0 is planting, so FAO day i = day + 1.


def _tomato(day: int) -> float:
    return kc_on_day(0.60, 1.15, 0.80, 30, 40, 45, 30, day)


def test_kc_day_zero_is_initial() -> None:
    # i = 1 is inside L_ini, so Kc stays at Kc_ini.
    assert _tomato(0) == pytest.approx(0.60)


def test_kc_last_initial_day() -> None:
    # i = 30 = L_ini, still the initial stage.
    assert _tomato(29) == pytest.approx(0.60)


def test_kc_first_development_day_interpolates() -> None:
    # i = 31. Fraction = (31 - 30) / 40 = 1/40.
    # Kc = 0.60 + (1/40) * (1.15 - 0.60) = 0.61375.
    assert _tomato(30) == pytest.approx(0.60 + (1.15 - 0.60) / 40)


def test_kc_midpoint_of_development() -> None:
    # i = 50. Fraction = (50 - 30) / 40 = 0.5.
    # Kc = 0.60 + 0.5 * 0.55 = 0.875.
    assert _tomato(49) == pytest.approx(0.875)


def test_kc_last_development_day_reaches_mid() -> None:
    # i = 70 = L_ini + L_dev. Fraction = 40/40, so Kc = Kc_mid.
    assert _tomato(69) == pytest.approx(1.15)


def test_kc_mid_season_is_flat() -> None:
    # i = 71 is the first mid day. i = 115 = 30 + 40 + 45 is the last.
    assert _tomato(70) == pytest.approx(1.15)
    assert _tomato(114) == pytest.approx(1.15)


def test_kc_first_late_day_interpolates() -> None:
    # i = 116. Fraction = (116 - 115) / 30 = 1/30.
    # Kc = 1.15 + (1/30) * (0.80 - 1.15) = 1.15 - 0.35/30.
    assert _tomato(115) == pytest.approx(1.15 - 0.35 / 30)


def test_kc_midpoint_of_late_season() -> None:
    # i = 130. Fraction = (130 - 115) / 30 = 0.5.
    # Kc = 1.15 + 0.5 * (0.80 - 1.15) = 0.975.
    assert _tomato(129) == pytest.approx(0.975)


def test_kc_end_of_season() -> None:
    # Season length 145. Day 144 is i = 145, the last day, so Kc = Kc_end.
    assert _tomato(144) == pytest.approx(0.80)


def test_kc_after_season_stays_at_end() -> None:
    # Day 145 is past the 145-day season and does not extrapolate.
    assert _tomato(145) == pytest.approx(0.80)


def test_kc_rejects_negative_day() -> None:
    with pytest.raises(ValueError, match="day must be >= 0"):
        _tomato(-1)
