"""Inhaled dose and the activity scheduler.

Dose = sum over hours of C_out(h) * MEF * MF * VE * dt  (ug of PM2.5 inhaled).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain import constants as c
from app.domain.models import (
    Activity,
    AgeBand,
    DayProfile,
    Intensity,
    LocationType,
    Member,
)
from app.domain.stagnation import hour_overlaps, mean_stagnation


def naqi_category(pm25: float) -> str:
    """Map a PM2.5 value (ug/m^3) to its NAQI category key."""
    for upper, name in c.NAQI_PM25_BANDS:
        if pm25 <= upper:
            return name
    return c.NAQI_ORDER[-1]


def breathing_rate(age_band: AgeBand, intensity: Intensity) -> float:
    """Ventilation rate VE in m^3/h."""
    return c.BREATHING_RATE_M3_PER_H[age_band][intensity]


def vulnerability_weight(member: Member) -> float:
    """Highest weight among the member's age band and conditions. Used for ranking only."""
    weights = [c.VULNERABILITY_BASE[member.age_band]]
    weights += [c.VULNERABILITY_CONDITION[cond] for cond in member.conditions]
    return max(weights)


def is_sensitive(member: Member) -> bool:
    """Members who get stricter alert thresholds."""
    return vulnerability_weight(member) > 1.0


def avoid_exertion(pm25: float, sensitive: bool) -> bool:
    """True when strenuous activity should be avoided at this PM2.5 level."""
    level = c.NAQI_ORDER.index(naqi_category(pm25))
    threshold = c.NAQI_ORDER.index(c.AVOID_EXERTION_FROM) - (1 if sensitive else 0)
    return level >= threshold


def location_mef(location: LocationType) -> float:
    """Microenvironment factor for an activity location."""
    return {
        LocationType.OUTDOOR: c.MEF_OUTDOOR,
        LocationType.ROADSIDE: c.MEF_ROADSIDE,
        LocationType.INDOOR: c.MEF_INDOOR_DEFAULT,
    }[location]


def mean_pm25(profile: DayProfile, start: float, duration_h: float) -> float:
    """Duration-weighted mean outdoor PM2.5 over [start, start + duration)."""
    total = weight = 0.0
    for hour, frac in hour_overlaps(start, duration_h):
        total += profile.at(hour).pm25 * frac
        weight += frac
    return total / weight if weight else 0.0


def concentration_hours(
    profile: DayProfile, start: float, duration_h: float, mef: float, mask_factor: float = 1.0
) -> float:
    """Effective exposure in ug/m^3 * h (what the cigarette heuristic is based on)."""
    return sum(
        profile.at(hour).pm25 * frac * mef * mask_factor
        for hour, frac in hour_overlaps(start, duration_h)
    )


def inhaled_dose(
    profile: DayProfile,
    start: float,
    duration_h: float,
    age_band: AgeBand,
    intensity: Intensity,
    mef: float,
    mask_factor: float = 1.0,
) -> float:
    """Inhaled PM2.5 in ug for one person over [start, start + duration)."""
    ve = breathing_rate(age_band, intensity)
    return ve * concentration_hours(profile, start, duration_h, mef, mask_factor)


def cigarettes(dose_ug: float, age_band: AgeBand, intensity: Intensity) -> float:
    """Cigarette-equivalent of an inhaled-dose difference (communication heuristic)."""
    ve = breathing_rate(age_band, intensity)
    return dose_ug / ve / c.CIGARETTE_UG_M3_HOURS


def activity_dose(
    profile: DayProfile,
    activity: Activity,
    member: Member,
    start: float | None = None,
    mask: bool | None = None,
) -> float:
    """Dose for one member doing an activity, optionally at a different start or with a mask."""
    use_mask = activity.mask if mask is None else mask
    return inhaled_dose(
        profile,
        activity.start_hour if start is None else start,
        activity.duration_h,
        member.age_band,
        activity.intensity,
        location_mef(activity.location),
        c.MASK_FACTOR if use_mask else 1.0,
    )


def weighted_activity_dose(
    profile: DayProfile, activity: Activity, members: list[Member], start: float | None = None
) -> float:
    """Vulnerability-weighted dose summed over the members doing the activity."""
    return sum(
        vulnerability_weight(m) * activity_dose(profile, activity, m, start) for m in members
    )


@dataclass(frozen=True)
class ScheduleResult:
    original_start: float
    chosen_start: float
    shifted: bool
    reason: str
    weighted_before: float
    weighted_after: float
    pm25_before: float
    pm25_after: float
    ssi_before: float
    ssi_after: float

    @property
    def pct_cut(self) -> float:
        if self.weighted_before <= 0:
            return 0.0
        return 100 * (self.weighted_before - self.weighted_after) / self.weighted_before


def _needs_daylight(activity: Activity, members: list[Member]) -> bool:
    return activity.location != LocationType.INDOOR and any(
        m.age_band in c.DAYLIGHT_ONLY_AGE_BANDS for m in members
    )


def _all_daylight(profile: DayProfile, start: float, duration_h: float) -> bool:
    return all(profile.at(h).is_daytime for h, _ in hour_overlaps(start, duration_h))


def candidate_starts(activity: Activity, members: list[Member], profile: DayProfile) -> list[float]:
    """Every whole-hour start inside the activity's window (daylight only for young children)."""
    if activity.window_start is None or activity.window_end is None:
        return []
    first = math.ceil(activity.window_start - 1e-9)
    last = math.floor(activity.window_end - activity.duration_h + 1e-9)
    starts = [float(s) for s in range(first, last + 1)]
    if _needs_daylight(activity, members):
        starts = [s for s in starts if _all_daylight(profile, s, activity.duration_h)]
    return starts


def schedule_activity(
    profile: DayProfile, activity: Activity, members: list[Member]
) -> ScheduleResult:
    """Pick the start hour with the lowest vulnerability-weighted dose.

    Ties on dose are broken by lower stagnation, then by closeness to the original time. If the
    best saving is under 10% the original time is kept.
    """
    original = activity.start_hour
    before = weighted_activity_dose(profile, activity, members)
    dur = activity.duration_h

    def result(start: float, shifted: bool, reason: str, after: float) -> ScheduleResult:
        return ScheduleResult(
            original_start=original,
            chosen_start=start,
            shifted=shifted,
            reason=reason,
            weighted_before=before,
            weighted_after=after,
            pm25_before=mean_pm25(profile, original, dur),
            pm25_after=mean_pm25(profile, start, dur),
            ssi_before=mean_stagnation(profile, original, dur),
            ssi_after=mean_stagnation(profile, start, dur),
        )

    if not activity.shiftable:
        return result(original, False, "fixed", before)

    candidates = candidate_starts(activity, members, profile)
    if not candidates:
        return result(original, False, "no_better_window", before)

    def key(start: float) -> tuple[float, float, float]:
        dose = weighted_activity_dose(profile, activity, members, start)
        return (
            round(dose, 6),
            round(mean_stagnation(profile, start, dur), 6),
            abs(start - original),
        )

    best = min(candidates, key=key)
    best_dose = weighted_activity_dose(profile, activity, members, best)
    saving = (before - best_dose) / before if before > 0 else 0.0
    if saving < c.MIN_SAVING_FRACTION or best == original:
        return result(original, False, "no_better_window", before)
    return result(best, True, "cleaner_air", best_dose)
