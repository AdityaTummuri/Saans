"""Smog Stagnation Index (SSI): a 0 to 100 heuristic for how much the air is trapping smog.

Calm wind, high humidity, low visibility and clear calm nights (strong surface inversion) all
raise the score. The weights are a documented heuristic, not a measured quantity.
"""

from __future__ import annotations

from app.domain import constants as c
from app.domain.models import DayProfile, HourlyConditions


def clamp01(value: float) -> float:
    """Clamp a number into the closed interval [0, 1]."""
    return max(0.0, min(1.0, value))


def stagnation_index(cond: HourlyConditions) -> float:
    """SSI = 100 * (0.4 W + 0.2 H + 0.15 V + 0.25 N) for one hour."""
    wind = clamp01(1 - cond.wind_kmh / c.SSI_WIND_CALM_KMH)
    humidity = clamp01((cond.humidity_pct - c.SSI_HUMIDITY_FLOOR) / (100 - c.SSI_HUMIDITY_FLOOR))
    visibility = clamp01(1 - cond.visibility_km / c.SSI_VISIBILITY_CLEAR_KM)
    inversion = c.SSI_DAY_INVERSION if cond.is_daytime else clamp01(1 - cond.cloud_cover_pct / 100)
    w = c.SSI_WEIGHTS
    return 100 * (
        w["wind"] * wind
        + w["humidity"] * humidity
        + w["visibility"] * visibility
        + w["inversion"] * inversion
    )


def mean_stagnation(profile: DayProfile, start: float, duration_h: float) -> float:
    """Duration-weighted mean SSI over [start, start + duration)."""
    total = weight = 0.0
    for hour, frac in hour_overlaps(start, duration_h):
        total += stagnation_index(profile.at(hour)) * frac
        weight += frac
    return total / weight if weight else 0.0


def hour_overlaps(start: float, duration_h: float) -> list[tuple[int, float]]:
    """Split [start, start + duration) into (clock hour, hours inside that hour) pieces.

    Times wrap around midnight so a 23:30 departure touches hour 23 and then hour 0.
    """
    pieces: list[tuple[int, float]] = []
    t = start
    end = start + duration_h
    while t < end - 1e-9:
        hour_floor = int(t // 1)
        piece = min(end, hour_floor + 1) - t
        pieces.append((hour_floor % 24, piece))
        t = hour_floor + 1
    return pieces
