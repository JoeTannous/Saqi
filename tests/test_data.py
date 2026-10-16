"""The yaml files hold the SPEC reference values, each still marked verify: true."""

import pytest

from engine.catalog import get_crop, get_soil, load_crops, load_soils, load_systems

# name, perennial, Kc ini/mid/end, Zr min/max, p, L ini/dev/mid/late
_CROPS = [
    ("potato", False, 0.50, 1.15, 0.75, 0.15, 0.50, 0.35, 30, 35, 50, 30),
    ("tomato", False, 0.60, 1.15, 0.80, 0.15, 1.00, 0.40, 30, 40, 45, 30),
    ("wheat", False, 0.30, 1.15, 0.30, 0.15, 1.20, 0.55, 30, 140, 40, 30),
    ("table_grapes", True, 0.30, 0.85, 0.45, 1.50, 1.50, 0.35, 20, 50, 75, 60),
    ("citrus", True, 0.70, 0.65, 0.70, 1.20, 1.20, 0.50, 60, 90, 120, 95),
    ("olive", True, 0.65, 0.70, 0.70, 1.50, 1.50, 0.65, 30, 90, 60, 90),
    ("avocado", True, 0.60, 0.85, 0.75, 0.70, 0.70, 0.70, 60, 90, 120, 95),
    ("apple", True, 0.60, 0.95, 0.75, 1.20, 1.20, 0.50, 30, 50, 130, 30),
]

_SOILS = [
    ("sand", 0.12, 0.04),
    ("loamy_sand", 0.14, 0.06),
    ("sandy_loam", 0.23, 0.10),
    ("loam", 0.25, 0.12),
    ("silt_loam", 0.29, 0.15),
    ("clay_loam", 0.32, 0.20),
    ("clay", 0.36, 0.22),
]


@pytest.mark.parametrize(
    (
        "name",
        "perennial",
        "kc_ini",
        "kc_mid",
        "kc_end",
        "zr_min",
        "zr_max",
        "p",
        "l_ini",
        "l_dev",
        "l_mid",
        "l_late",
    ),
    _CROPS,
)
def test_crop_reference_values(
    name: str,
    perennial: bool,
    kc_ini: float,
    kc_mid: float,
    kc_end: float,
    zr_min: float,
    zr_max: float,
    p: float,
    l_ini: int,
    l_dev: int,
    l_mid: int,
    l_late: int,
) -> None:
    crop = get_crop(name)
    assert crop.verify is True
    assert crop.perennial is perennial
    assert crop.kc_ini == pytest.approx(kc_ini)
    assert crop.kc_mid == pytest.approx(kc_mid)
    assert crop.kc_end == pytest.approx(kc_end)
    assert crop.zr_min_m == pytest.approx(zr_min)
    assert crop.zr_max_m == pytest.approx(zr_max)
    assert crop.p == pytest.approx(p)
    assert (crop.l_ini, crop.l_dev, crop.l_mid, crop.l_late) == (l_ini, l_dev, l_mid, l_late)


@pytest.mark.parametrize(("name", "theta_fc", "theta_wp"), _SOILS)
def test_soil_reference_values(name: str, theta_fc: float, theta_wp: float) -> None:
    soil = get_soil(name)
    assert soil.verify is True
    assert soil.theta_fc == pytest.approx(theta_fc)
    assert soil.theta_wp == pytest.approx(theta_wp)


def test_system_efficiency_defaults() -> None:
    # SPEC defaults. micro_sprinkler is absent, so a block must set its own.
    systems = load_systems()
    assert systems["drip"].efficiency == pytest.approx(0.90)
    assert systems["sprinkler"].efficiency == pytest.approx(0.75)
    assert systems["pivot"].efficiency == pytest.approx(0.85)
    assert systems["surface"].efficiency == pytest.approx(0.60)
    assert all(record.verify is True for record in systems.values())
    assert "micro_sprinkler" not in systems


def test_catalog_covers_the_spec_lists_only() -> None:
    assert set(load_crops()) == {row[0] for row in _CROPS}
    assert set(load_soils()) == {row[0] for row in _SOILS}


def test_unknown_names_are_rejected() -> None:
    with pytest.raises(KeyError, match="Unknown crop"):
        get_crop("banana")
    with pytest.raises(KeyError, match="Unknown soil"):
        get_soil("peat")
