"""TAW, RAW, and root growth. Expected values are written out in the comments."""

import pytest

from engine.soil import raw_mm, root_depth_m, taw_mm


def test_taw_loam_at_40_cm() -> None:
    # TAW = 1000 * (0.25 - 0.12) * 0.40 = 52 mm.
    assert taw_mm(0.25, 0.12, 0.40) == pytest.approx(52.0)


def test_raw_is_p_times_taw() -> None:
    # RAW = 0.40 * 52 = 20.8 mm.
    assert raw_mm(0.40, 52.0) == pytest.approx(20.8)


def test_root_depth_day_zero_is_minimum() -> None:
    # Day 0 is planting. End of development is day (4 + 6 - 1) = 9.
    assert root_depth_m(0.15, 0.50, 4, 6, 0, perennial=False) == pytest.approx(0.15)


def test_root_depth_grows_linearly_until_end_of_development() -> None:
    # Day 3 of a 9-day climb: 0.15 + (3/9) * (0.50 - 0.15) = 0.2666... m.
    depth = root_depth_m(0.15, 0.50, 4, 6, 3, perennial=False)
    assert depth == pytest.approx(0.15 + (3 / 9) * 0.35)


def test_root_depth_reaches_maximum_at_end_of_development() -> None:
    # Day 9 is the last development day, and day 10 is already mid-season.
    assert root_depth_m(0.15, 0.50, 4, 6, 9, perennial=False) == pytest.approx(0.50)
    assert root_depth_m(0.15, 0.50, 4, 6, 10, perennial=False) == pytest.approx(0.50)


def test_perennial_root_depth_does_not_grow() -> None:
    # Established trees stay at Zr_max on day 0 and deep into the season.
    assert root_depth_m(0.15, 1.20, 30, 50, 0, perennial=True) == pytest.approx(1.20)
    assert root_depth_m(0.15, 1.20, 30, 50, 80, perennial=True) == pytest.approx(1.20)


def test_root_depth_rejects_negative_day() -> None:
    with pytest.raises(ValueError, match="day must be >= 0"):
        root_depth_m(0.15, 0.50, 4, 6, -1, perennial=False)
