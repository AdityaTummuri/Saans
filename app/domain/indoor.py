"""Indoor PM2.5 physics: steady-state mass balance, purifier sizing, ventilation timing."""

from __future__ import annotations

import math

from app.domain import constants as c
from app.domain.exposure import naqi_category
from app.domain.models import (
    DayProfile,
    Room,
    RoomEstimate,
    SourceUse,
    VentilationWindow,
    WindowType,
)
from app.domain.stagnation import stagnation_index


def air_exchange_rate(windows: WindowType) -> float:
    """Air exchanges per hour for a window type."""
    if windows == WindowType.SEALED:
        return c.AIR_EXCHANGE_SEALED_PER_H
    return c.AIR_EXCHANGE_LEAKY_PER_H


def indoor_pm25(
    c_out: float,
    air_exchange: float,
    volume_m3: float,
    cadr_m3_per_h: float = 0.0,
    source_ug_per_h: float = 0.0,
    penetration: float = c.PENETRATION_FACTOR,
    deposition: float = c.DEPOSITION_RATE_PER_H,
) -> float:
    """Steady-state indoor PM2.5: C_in = (P a C_out + S/V) / (a + k + CADR/V)."""
    numerator = penetration * air_exchange * c_out + source_ug_per_h / volume_m3
    denominator = air_exchange + deposition + cadr_m3_per_h / volume_m3
    return numerator / denominator


def cadr_needed(
    c_out: float,
    air_exchange: float,
    volume_m3: float,
    target: float,
    source_ug_per_h: float = 0.0,
    penetration: float = c.PENETRATION_FACTOR,
    deposition: float = c.DEPOSITION_RATE_PER_H,
) -> float:
    """CADR in m^3/h to hold a room at `target`: V * ((P a C_out + S/V)/target - a - k), min 0."""
    raw = volume_m3 * (
        (penetration * air_exchange * c_out + source_ug_per_h / volume_m3) / target
        - air_exchange
        - deposition
    )
    return max(0.0, raw)


def round_up_cadr(cadr: float) -> float:
    """Round a CADR up to the next purchasable step."""
    if cadr <= 0:
        return 0.0
    return math.ceil(cadr / c.PURIFIER_CADR_STEP) * c.PURIFIER_CADR_STEP


def occupied_hours(room: Room) -> list[int]:
    """Clock hours during which the room is occupied (the range may wrap past midnight)."""
    start, end = room.occupied_from, room.occupied_to
    if start == end:
        return list(range(24))
    span = (end - start) % 24
    return [(start + i) % 24 for i in range(span)]


def mean_outdoor_when_occupied(profile: DayProfile, room: Room) -> float:
    """Mean outdoor PM2.5 over the hours the room is occupied."""
    hours = occupied_hours(room)
    return sum(profile.at(h).pm25 for h in hours) / len(hours)


def estimate_room(profile: DayProfile, room: Room) -> RoomEstimate:
    """Indoor estimates for one room: now, no purifier, with purifier, and purifier plus sealing."""
    c_out = mean_outdoor_when_occupied(profile, room)
    a = air_exchange_rate(room.windows)
    v = room.volume_m3
    now = indoor_pm25(c_out, a, v, room.purifier_cadr_m3_per_h)
    cadr_ref = room.purifier_cadr_m3_per_h or c.CR_BOX_CADR_M3_PER_H
    return RoomEstimate(
        room=room.name,
        outdoor_pm25=c_out,
        indoor_now=now,
        indoor_no_purifier=indoor_pm25(c_out, a, v),
        indoor_with_purifier=indoor_pm25(c_out, a, v, cadr_ref),
        indoor_purifier_sealed=indoor_pm25(c_out, c.AIR_EXCHANGE_SEALED_PER_H, v, cadr_ref),
        category_now=naqi_category(now),
        cadr_needed=cadr_needed(c_out, a, v, c.INDOOR_TARGET_PM25),
        purifier_cadr=room.purifier_cadr_m3_per_h,
    )


def source_indoor_increase(room: Room, source: SourceUse) -> float:
    """ug/m^3 a source adds to its room while in use (zero for sources that burn outdoors)."""
    strength = c.SOURCE_STRENGTH_UG_PER_H.get(source.kind)
    if strength is None:
        return 0.0
    a = air_exchange_rate(room.windows)
    v = room.volume_m3
    return strength / v / (a + c.DEPOSITION_RATE_PER_H + room.purifier_cadr_m3_per_h / v)


def ventilation_window(profile: DayProfile) -> VentilationWindow:
    """Best short window today to air out the house: the lowest-PM2.5 waking hour.

    Ties go to the less stagnant hour, then the earlier one.
    """
    hours = range(c.VENTILATION_FIRST_HOUR, c.VENTILATION_LAST_HOUR + 1)
    best = min(
        hours,
        key=lambda h: (round(profile.at(h).pm25, 6), stagnation_index(profile.at(h)), h),
    )
    mean = sum(profile.at(h).pm25 for h in hours) / len(hours)
    return VentilationWindow(
        best_hour=best,
        pm25_best=profile.at(best).pm25,
        pm25_waking_mean=mean,
        minutes=c.VENTILATION_MINUTES,
    )
