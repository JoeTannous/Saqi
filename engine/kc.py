"""Single crop coefficient by day after planting. FAO-56 equation 66."""


def kc_on_day(
    kc_ini: float,
    kc_mid: float,
    kc_end: float,
    l_ini: int,
    l_dev: int,
    l_mid: int,
    l_late: int,
    day: int,
) -> float:
    """Kc on `day`, where day 0 is the planting date (or season start).

    FAO-56 numbers the season from i = 1, so i = day + 1. The initial and
    mid-season stages are flat. Development interpolates Kc_ini → Kc_mid and
    reaches Kc_mid on its last day. Late season interpolates Kc_mid → Kc_end
    and reaches Kc_end on the last day of the season. After that, Kc stays
    at Kc_end.
    """
    if day < 0:
        raise ValueError("day must be >= 0")
    for name, length in (
        ("l_ini", l_ini),
        ("l_dev", l_dev),
        ("l_mid", l_mid),
        ("l_late", l_late),
    ):
        if length < 0:
            raise ValueError(f"{name} must be >= 0")

    i = day + 1
    if l_ini > 0 and i <= l_ini:
        return kc_ini

    dev_end = l_ini + l_dev
    if l_dev > 0 and i <= dev_end:
        fraction = (i - l_ini) / l_dev
        return kc_ini + fraction * (kc_mid - kc_ini)

    mid_end = dev_end + l_mid
    if i <= mid_end:
        return kc_mid

    season_end = mid_end + l_late
    if l_late <= 0 or i >= season_end:
        return kc_end

    fraction = (i - mid_end) / l_late
    return kc_mid + fraction * (kc_end - kc_mid)
