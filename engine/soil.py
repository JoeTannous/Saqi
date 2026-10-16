"""Root-zone storage: TAW, RAW, and root depth. FAO-56 equations 82 and 83."""


def taw_mm(theta_fc: float, theta_wp: float, zr_m: float) -> float:
    """Total available water, mm. TAW = 1000 × (θFC − θWP) × Zr."""
    return 1000.0 * (theta_fc - theta_wp) * zr_m


def raw_mm(p: float, taw: float) -> float:
    """Readily available water, mm. RAW = p × TAW."""
    return p * taw


def root_depth_m(
    zr_min_m: float,
    zr_max_m: float,
    l_ini: int,
    l_dev: int,
    day: int,
    *,
    perennial: bool,
) -> float:
    """Root depth on `day` (0 = planting).

    Annuals grow linearly from Zr_min at planting to Zr_max on the last day
    of the development stage, then stay at Zr_max. Perennials stay at Zr_max.
    """
    if day < 0:
        raise ValueError("day must be >= 0")
    if perennial:
        return zr_max_m

    end_dev_day = l_ini + l_dev - 1
    if day <= 0 or end_dev_day <= 0:
        return zr_min_m if day <= 0 else zr_max_m
    if day >= end_dev_day:
        return zr_max_m
    fraction = day / end_dev_day
    return zr_min_m + fraction * (zr_max_m - zr_min_m)
