"""Orchestrates the domain functions into a Plan and a flat facts payload.

Member totals are a routine-exposure estimate: outdoor activities, trips and the hours spent in
rooms with a known occupant list. Indoor-source actions are advisory and are not part of the
member totals. Each ledger action is evaluated on its own against the current routine, so the
sum of action savings can differ slightly from the planned total (which stacks the chosen ones).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain import constants as c
from app.domain.emissions import (
    source_daily_co2_kg,
    source_daily_pm25_g,
    trip_co2_kg,
    trip_pm25_g,
)
from app.domain.exposure import (
    avoid_exertion,
    breathing_rate,
    cigarettes,
    inhaled_dose,
    is_sensitive,
    location_mef,
    mean_pm25,
    naqi_category,
    schedule_activity,
    vulnerability_weight,
)
from app.domain.indoor import (
    air_exchange_rate,
    cadr_needed,
    estimate_room,
    indoor_pm25,
    mean_outdoor_when_occupied,
    occupied_hours,
    round_up_cadr,
    source_indoor_increase,
    ventilation_window,
)
from app.domain.labels import (
    ACTION_TEMPLATES,
    CATEGORY_LABELS,
    DAYPART_PREFIX,
    MODE_LABELS,
    SOURCE_LABELS,
    SUMMARY_TEMPLATES,
)
from app.domain.models import (
    ActionKind,
    Activity,
    BudgetTier,
    CommuteComparison,
    CommuteOption,
    DayProfile,
    FactsPayload,
    HomeSource,
    HourSummary,
    Household,
    Intensity,
    Language,
    LedgerEntry,
    LocationType,
    Member,
    MemberDelta,
    MemberSummary,
    Plan,
    Room,
    SourceFlag,
    TimelineItem,
    TravelMode,
    Trip,
    TripOption,
)
from app.domain.ranking import build_entry, rank_actions
from app.domain.stagnation import mean_stagnation, stagnation_index

DEPARTURE_STEP_H = 0.5

# Terms that contain digits but are fixed names, so narrated text can use them as placeholders
# and stay free of raw digits.
CONSTANT_TERMS: dict[str, str] = {"pm": "PM2.5", "n95": "N95"}


# ------------------------------------------------------------------------------------------
# Small helpers
# ------------------------------------------------------------------------------------------


def format_time(hour: float, language: Language) -> str:
    """12-hour clock text, with a Hindi day-part prefix when needed."""
    total_minutes = round(hour * 60) % (24 * 60)
    h24, minute = divmod(total_minutes, 60)
    h12 = h24 % 12 or 12
    suffix = "am" if h24 < 12 else "pm"
    text = f"{h12}:{minute:02d} {suffix}"
    if language == Language.HI:
        prefixes = DAYPART_PREFIX[Language.HI]
        part = 0 if 4 <= h24 < 12 else 1 if 12 <= h24 < 16 else 2 if 16 <= h24 < 20 else 3
        return f"{prefixes[part]}{text}"
    return text


def _fmt(value: float, decimals: int = 0) -> str:
    return f"{value:.{decimals}f}"


def _join_names(names: list[str], language: Language) -> str:
    if len(names) <= 1:
        return "".join(names)
    joiner = " और " if language == Language.HI else " and "
    return ", ".join(names[:-1]) + joiner + names[-1]


def _members(household: Household, ids: list[str]) -> list[Member]:
    return [household.member(i) for i in ids]


def _can_wear_mask(member: Member) -> bool:
    return member.age_band not in c.MASK_EXCLUDED_AGE_BANDS


# ------------------------------------------------------------------------------------------
# Trips
# ------------------------------------------------------------------------------------------


def trip_mef(mode: TravelMode, recirculation: bool = False) -> float:
    if recirculation and mode == TravelMode.CAR:
        return c.MEF_CAR_RECIRCULATION
    return c.MEF_BY_MODE[mode]


def trip_member_dose(
    profile: DayProfile,
    member: Member,
    option: TripOption,
    depart: float,
    mask: bool = False,
    recirculation: bool = False,
) -> float:
    """Dose for one member over a trip in a given mode."""
    return inhaled_dose(
        profile,
        depart,
        option.duration_min / 60,
        member.age_band,
        c.INTENSITY_BY_MODE[option.mode],
        trip_mef(option.mode, recirculation),
        c.MASK_FACTOR if mask else 1.0,
    )


def _trip_weighted(
    profile: DayProfile,
    members: list[Member],
    option: TripOption,
    depart: float,
    mask: bool = False,
    recirculation: bool = False,
) -> float:
    return sum(
        vulnerability_weight(m) * trip_member_dose(profile, m, option, depart, mask, recirculation)
        for m in members
    )


# ------------------------------------------------------------------------------------------
# Plan assembly
# ------------------------------------------------------------------------------------------


@dataclass
class _Totals:
    baseline: dict[str, float]
    plan: dict[str, float]
    cigarettes: dict[str, float]

    @classmethod
    def empty(cls, household: Household) -> _Totals:
        ids = [m.id for m in household.members]
        return cls({i: 0.0 for i in ids}, {i: 0.0 for i in ids}, {i: 0.0 for i in ids})


def _deltas(
    household: Household,
    ids: list[str],
    before: dict[str, float],
    after: dict[str, float],
    intensity_for: dict[str, Intensity],
) -> list[MemberDelta]:
    out: list[MemberDelta] = []
    for mid in ids:
        member = household.member(mid)
        avoided = before[mid] - after[mid]
        out.append(
            MemberDelta(
                member_id=mid,
                dose_before_ug=before[mid],
                dose_after_ug=after[mid],
                cigarettes_avoided=cigarettes(avoided, member.age_band, intensity_for[mid]),
            )
        )
    return out


def _plan_activities(
    profile: DayProfile,
    household: Household,
    weights: dict[str, float],
    totals: _Totals,
    entries: list[LedgerEntry],
) -> list[TimelineItem]:
    timeline: list[TimelineItem] = []
    for act in household.activities:
        members = _members(household, act.member_ids)
        res = schedule_activity(profile, act, members)
        mef = location_mef(act.location)

        def dose(
            m: Member, start: float, mask: bool, act: Activity = act, mef: float = mef
        ) -> float:
            return inhaled_dose(
                profile,
                start,
                act.duration_h,
                m.age_band,
                act.intensity,
                mef,
                c.MASK_FACTOR if mask else 1.0,
            )

        before = {m.id: dose(m, act.start_hour, act.mask) for m in members}
        after = {m.id: dose(m, res.chosen_start, act.mask) for m in members}
        intens = {m.id: act.intensity for m in members}

        if res.shifted:
            entries.append(
                build_entry(
                    entry_id=f"shift_{act.id}",
                    kind=ActionKind.SHIFT_ACTIVITY,
                    subject=act.name,
                    effort_tier=c.TIER_FREE,
                    deltas=_deltas(household, act.member_ids, before, after, intens),
                    weights=weights,
                    details={
                        "old_start": act.start_hour,
                        "new_start": res.chosen_start,
                        "pm_before": res.pm25_before,
                        "pm_after": res.pm25_after,
                        "ssi_before": res.ssi_before,
                        "ssi_after": res.ssi_after,
                    },
                )
            )
        elif (
            act.location != LocationType.INDOOR
            and not act.mask
            and act.intensity != Intensity.VIGOROUS
            and res.pm25_before >= c.MASK_MIN_PM25
        ):
            maskers = [m for m in members if _can_wear_mask(m)]
            if maskers:
                mask_after = {m.id: dose(m, act.start_hour, True) for m in maskers}
                mask_before = {m.id: before[m.id] for m in maskers}
                entries.append(
                    build_entry(
                        entry_id=f"mask_{act.id}",
                        kind=ActionKind.MASK,
                        subject=act.name,
                        effort_tier=c.TIER_HABIT,
                        deltas=_deltas(
                            household, [m.id for m in maskers], mask_before, mask_after, intens
                        ),
                        weights=weights,
                        details={"pm_before": res.pm25_before},
                    )
                )
                after = {**after, **mask_after}

        for m in members:
            totals.baseline[m.id] += before[m.id]
            totals.plan[m.id] += after[m.id]
            totals.cigarettes[m.id] += cigarettes(
                before[m.id] - after[m.id], m.age_band, act.intensity
            )
        timeline.append(
            TimelineItem(
                activity_id=act.id,
                name=act.name,
                member_ids=act.member_ids,
                original_start=act.start_hour,
                planned_start=res.chosen_start,
                duration_h=act.duration_h,
                shifted=res.shifted,
                reason=res.reason,
                pm25_before=res.pm25_before,
                pm25_after=res.pm25_after,
                ssi_before=res.ssi_before,
                ssi_after=res.ssi_after,
                dose_cut_pct=res.pct_cut,
            )
        )
    timeline.sort(key=lambda t: t.planned_start)
    return timeline


def _departure_candidates(trip: Trip) -> list[float]:
    steps = round(trip.depart_flex_h / DEPARTURE_STEP_H)
    out = [trip.depart_hour + k * DEPARTURE_STEP_H for k in range(-steps, steps + 1)]
    return [t for t in out if 0 <= t < 24]


def _plan_trips(
    profile: DayProfile,
    household: Household,
    weights: dict[str, float],
    totals: _Totals,
    entries: list[LedgerEntry],
) -> list[CommuteComparison]:
    comparisons: list[CommuteComparison] = []
    for trip in household.trips:
        members = _members(household, trip.member_ids)
        n = len(members)
        cur = trip.option(trip.mode)
        intens = {m.id: c.INTENSITY_BY_MODE[trip.mode] for m in members}

        def per_member(
            option: TripOption,
            depart: float,
            mask: bool,
            recirc: bool = False,
            members: list[Member] = members,
        ) -> dict[str, float]:
            return {
                m.id: trip_member_dose(profile, m, option, depart, mask, recirc) for m in members
            }

        def weighted(d: dict[str, float]) -> float:
            return sum(weights[k] * v for k, v in d.items())

        base = per_member(cur, trip.depart_hour, trip.mask)
        base_w = weighted(base)
        base_co2 = trip_co2_kg(trip.mode, cur.distance_km, n)
        base_pm_g = trip_pm25_g(trip.mode, cur.distance_km, n)
        avg_pm = mean_pm25(profile, trip.depart_hour, cur.duration_min / 60)

        comparisons.append(
            CommuteComparison(
                trip_id=trip.id,
                name=trip.name,
                options=[
                    CommuteOption(
                        mode=o.mode,
                        duration_min=o.duration_min,
                        distance_km=o.distance_km,
                        dose_ug=sum(per_member(o, trip.depart_hour, False).values()),
                        co2_kg=trip_co2_kg(o.mode, o.distance_km, n),
                        current=o.mode == trip.mode,
                    )
                    for o in trip.options
                ],
            )
        )

        best_dose = dict(base)  # best non-mask option for the plan
        best_w = base_w

        # Car recirculation
        if trip.mode == TravelMode.CAR:
            recirc = per_member(cur, trip.depart_hour, trip.mask, True)
            if weighted(recirc) < base_w:
                entries.append(
                    build_entry(
                        entry_id=f"recirc_{trip.id}",
                        kind=ActionKind.RECIRCULATION,
                        subject=trip.name,
                        effort_tier=c.TIER_FREE,
                        deltas=_deltas(household, trip.member_ids, base, recirc, intens),
                        weights=weights,
                    )
                )
                if weighted(recirc) < best_w:
                    best_dose, best_w = recirc, weighted(recirc)

        # Departure shift
        if trip.depart_flex_h > 0:
            cands = _departure_candidates(trip)
            best_t = min(
                cands,
                key=lambda t: (
                    round(weighted(per_member(cur, t, trip.mask)), 6),
                    abs(t - trip.depart_hour),
                ),
            )
            shifted = per_member(cur, best_t, trip.mask)
            if base_w > 0 and (base_w - weighted(shifted)) / base_w >= c.MIN_SAVING_FRACTION:
                entries.append(
                    build_entry(
                        entry_id=f"depart_{trip.id}",
                        kind=ActionKind.DEPARTURE_SHIFT,
                        subject=trip.name,
                        effort_tier=c.TIER_FREE,
                        deltas=_deltas(household, trip.member_ids, base, shifted, intens),
                        weights=weights,
                        details={"old_start": trip.depart_hour, "new_start": best_t},
                    )
                )
                if weighted(shifted) < best_w:
                    best_dose, best_w = shifted, weighted(shifted)

        # Mode switches: the best exposure cut, and the lowest-emission alternative
        alternatives: list[tuple[TripOption, dict[str, float]]] = [
            (o, per_member(o, trip.depart_hour, trip.mask))
            for o in trip.options
            if o.mode != trip.mode
        ]
        dose_winners = [
            (o, d)
            for o, d in alternatives
            if base_w > 0 and (base_w - weighted(d)) / base_w >= c.MIN_SAVING_FRACTION
        ]
        picks: list[tuple[TripOption, dict[str, float], bool]] = []
        if dose_winners:
            o, d = min(dose_winners, key=lambda od: weighted(od[1]))
            picks.append((o, d, False))
        green = [
            (o, d)
            for o, d in alternatives
            if trip_co2_kg(o.mode, o.distance_km, n) < base_co2
            and weighted(d) <= base_w * 1.15
            and not any(o.mode == p[0].mode for p in picks)
        ]
        if green:
            o, d = min(green, key=lambda od: trip_co2_kg(od[0].mode, od[0].distance_km, n))
            picks.append((o, d, weighted(d) > base_w))
        for o, d, is_tradeoff in picks:
            entries.append(
                build_entry(
                    entry_id=f"mode_{trip.id}_{o.mode.value}",
                    kind=ActionKind.MODE_SWITCH,
                    subject=trip.name,
                    effort_tier=c.TIER_HABIT,
                    deltas=_deltas(household, trip.member_ids, base, d, intens),
                    weights=weights,
                    co2_avoided_kg=base_co2 - trip_co2_kg(o.mode, o.distance_km, n),
                    pm25_avoided_g=base_pm_g - trip_pm25_g(o.mode, o.distance_km, n),
                    tradeoff=is_tradeoff,
                    details={"mode_old": trip.mode.value, "mode_new": o.mode.value},
                )
            )
        if dose_winners:
            o, d, _ = picks[0]
            if weighted(d) < best_w:
                best_dose, best_w = d, weighted(d)

        # Mask on top of the best option
        planned = dict(best_dose)
        if not trip.mask and avg_pm >= c.MASK_MIN_PM25:
            maskers = [m for m in members if _can_wear_mask(m)]
            if maskers:
                masked_before = {m.id: base[m.id] for m in maskers}
                masked_after = {m.id: base[m.id] * c.MASK_FACTOR for m in maskers}
                entries.append(
                    build_entry(
                        entry_id=f"mask_{trip.id}",
                        kind=ActionKind.MASK,
                        subject=trip.name,
                        effort_tier=c.TIER_HABIT,
                        deltas=_deltas(
                            household, [m.id for m in maskers], masked_before, masked_after, intens
                        ),
                        weights=weights,
                        details={"pm_before": avg_pm},
                    )
                )
                for m in maskers:
                    planned[m.id] = best_dose[m.id] * c.MASK_FACTOR

        for m in members:
            totals.baseline[m.id] += base[m.id]
            totals.plan[m.id] += planned[m.id]
            totals.cigarettes[m.id] += cigarettes(
                base[m.id] - planned[m.id], m.age_band, c.INTENSITY_BY_MODE[trip.mode]
            )
    return comparisons


def _room_dose(
    household: Household, room: Room, profile: DayProfile, a: float, cadr: float
) -> dict[str, float]:
    """Dose for each occupant over the room's occupied hours at given air exchange and CADR."""
    c_out = mean_outdoor_when_occupied(profile, room)
    c_in = indoor_pm25(c_out, a, room.volume_m3, cadr)
    hours = len(occupied_hours(room))
    return {
        mid: breathing_rate(household.member(mid).age_band, Intensity.REST) * c_in * hours
        for mid in room.occupant_ids
    }


def _plan_home(
    profile: DayProfile,
    household: Household,
    weights: dict[str, float],
    totals: _Totals,
    entries: list[LedgerEntry],
) -> None:
    low = household.budget == BudgetTier.LOW
    rest = {m.id: Intensity.REST for m in household.members}  # rest breathing
    for room in household.home.rooms:
        if not room.occupant_ids:
            continue
        a = air_exchange_rate(room.windows)
        cadr0 = room.purifier_cadr_m3_per_h
        base = _room_dose(household, room, profile, a, cadr0)
        c_out = mean_outdoor_when_occupied(profile, room)
        c_now = indoor_pm25(c_out, a, room.volume_m3, cadr0)

        def add(
            kind: ActionKind,
            tier: int,
            a2: float,
            cadr2: float,
            details: dict[str, str | float],
            room: Room = room,
            a: float = a,
            base: dict[str, float] = base,
            c_out: float = c_out,
            c_now: float = c_now,
        ) -> None:
            after = _room_dose(household, room, profile, a2, cadr2)
            if sum(base.values()) - sum(after.values()) <= 0:
                return
            c_after = indoor_pm25(c_out, a2, room.volume_m3, cadr2)
            entries.append(
                build_entry(
                    entry_id=f"{kind.value}_{room.name}",
                    kind=kind,
                    subject=room.name,
                    effort_tier=tier,
                    deltas=_deltas(household, room.occupant_ids, base, after, rest),
                    weights=weights,
                    details={"indoor_before": c_now, "indoor_after": c_after, **details},
                )
            )

        sealed_a = c.AIR_EXCHANGE_SEALED_PER_H
        if cadr0 <= 0:
            need = round_up_cadr(cadr_needed(c_out, a, room.volume_m3, c.INDOOR_TARGET_PM25))
            if need > 0:
                add(ActionKind.PURIFIER, c.TIER_PURCHASE, a, need, {"cadr": need})
            add(
                ActionKind.CR_BOX,
                c.TIER_DIY,
                a,
                c.CR_BOX_CADR_M3_PER_H,
                {"cadr": c.CR_BOX_CADR_M3_PER_H},
            )
        if a > sealed_a:
            add(ActionKind.SEAL_GAPS, c.TIER_DIY, sealed_a, cadr0, {})

        # Planned setup: sealed gaps plus purifier (or a CR box on a low budget)
        plan_cadr = cadr0 or (
            c.CR_BOX_CADR_M3_PER_H
            if low
            else round_up_cadr(cadr_needed(c_out, a, room.volume_m3, c.INDOOR_TARGET_PM25))
            or c.CR_BOX_CADR_M3_PER_H
        )
        plan_a = min(a, sealed_a)
        planned = _room_dose(household, room, profile, plan_a, plan_cadr)
        for mid, d in base.items():
            member = household.member(mid)
            totals.baseline[mid] += d
            totals.plan[mid] += planned[mid]
            totals.cigarettes[mid] += cigarettes(d - planned[mid], member.age_band, rest[mid])


def _plan_sources(
    household: Household,
    weights: dict[str, float],
    entries: list[LedgerEntry],
) -> list[SourceFlag]:
    flags: list[SourceFlag] = []
    rooms = {r.name: r for r in household.home.rooms}
    for idx, use in enumerate(household.home.sources):
        room = rooms.get(use.room) if use.room else household.home.rooms[0]
        room = room or household.home.rooms[0]
        increase = source_indoor_increase(room, use)
        outdoor = use.kind in c.OUTDOOR_SOURCES or use.kind == HomeSource.WOOD_COOKING
        co2 = source_daily_co2_kg(use.kind, use.hours_per_day)
        pm_g = source_daily_pm25_g(use.kind, use.hours_per_day)
        flags.append(
            SourceFlag(
                kind=use.kind,
                room=room.name if increase > 0 else None,
                indoor_increase=increase,
                neighbourhood=outdoor,
                co2_kg_per_day=co2,
                pm25_g_per_day=pm_g,
            )
        )
        if increase > 0 and room.occupant_ids:
            hours = min(use.hours_per_day, 24.0)
            before = {
                mid: breathing_rate(household.member(mid).age_band, Intensity.REST)
                * increase
                * hours
                for mid in room.occupant_ids
            }
            after = dict.fromkeys(before, 0.0)
            rest = {mid: Intensity.REST for mid in before}
            entries.append(
                build_entry(
                    entry_id=f"source_{idx}",
                    kind=ActionKind.SKIP_SOURCE,
                    subject=use.kind.value,
                    effort_tier=c.TIER_FREE,
                    deltas=_deltas(household, room.occupant_ids, before, after, rest),
                    weights=weights,
                    co2_avoided_kg=co2,
                    pm25_avoided_g=pm_g,
                    details={
                        "indoor_increase": increase,
                        "room": room.name,
                        "source_kind": use.kind.value,
                    },
                )
            )
        elif use.kind in c.OUTDOOR_SOURCES:
            entries.append(
                build_entry(
                    entry_id=f"source_{idx}",
                    kind=ActionKind.STOP_BURNING,
                    subject=use.kind.value,
                    effort_tier=c.TIER_FREE,
                    deltas=[],
                    weights=weights,
                    co2_avoided_kg=co2,
                    pm25_avoided_g=pm_g,
                    details={"source_kind": use.kind.value, "pm_g": pm_g},
                )
            )
    return flags


# ------------------------------------------------------------------------------------------
# Facts
# ------------------------------------------------------------------------------------------


def _action_facts(
    household: Household,
    entry: LedgerEntry,
    language: Language,
    values: dict[str, str],
    numeric: dict[str, float],
) -> None:
    p = entry.id
    names = [household.member(d.member_id).name for d in entry.members]
    d = entry.details
    subject = entry.subject
    if entry.kind in (ActionKind.SKIP_SOURCE, ActionKind.STOP_BURNING):
        subject = SOURCE_LABELS[language].get(str(d.get("source_kind", subject)), subject)
    values[f"{p}.kind"] = entry.kind.value
    values[f"{p}.subject"] = subject
    values[f"{p}.members"] = _join_names(names, language)
    numbers: dict[str, tuple[float, int]] = {
        "dose_cut_pct": (abs(entry.pct_change), 0),
        "avoided_ug": (entry.avoided_ug, 0),
        "cigarettes": (entry.cigarettes_avoided, 1),
        "co2": (entry.co2_avoided_kg, 1),
    }
    for key in (
        "pm_before",
        "pm_after",
        "indoor_before",
        "indoor_after",
        "cadr",
        "indoor_increase",
        "pm_g",
    ):
        if key in d:
            numbers[key] = (float(d[key]), 0)
    for key, (val, dec) in numbers.items():
        values[f"{p}.{key}"] = _fmt(val, dec)
        numeric[f"{p}.{key}"] = val
    for key in ("old_start", "new_start"):
        if key in d:
            values[f"{p}.{key}"] = format_time(float(d[key]), language)
            numeric[f"{p}.{key}"] = float(d[key])
    for key in ("mode_old", "mode_new"):
        if key in d:
            values[f"{p}.{key}"] = MODE_LABELS[language][str(d[key])]
    if "room" in d:
        values[f"{p}.room"] = str(d["room"])


def render_template(template: str, prefix: str) -> str:
    """Rewrite `{{.key}}` shorthand to `{{prefix.key}}`."""
    return template.replace("{{.", "{{" + prefix + ".")


def fallback_action_text(entry: LedgerEntry, language: Language) -> str:
    """Deterministic placeholder text for an action (used when the narrator is unavailable)."""
    return render_template(ACTION_TEMPLATES[language][entry.kind], entry.id)


def build_facts(
    household: Household,
    profile: DayProfile,
    actions: list[LedgerEntry],
    members: list[MemberSummary],
) -> FactsPayload:
    language = household.language
    values: dict[str, str] = dict(CONSTANT_TERMS)
    numeric: dict[str, float] = {}
    for entry in actions:
        _action_facts(household, entry, language, values, numeric)
    peak = max(profile.hours, key=lambda h: h.pm25)
    best_h = ventilation_window(profile)
    labels = CATEGORY_LABELS[language]
    household_before = sum(m.dose_baseline_ug for m in members)
    household_after = sum(m.dose_plan_ug for m in members)
    cut = 100 * (household_before - household_after) / household_before if household_before else 0
    globals_: dict[str, tuple[str, float]] = {
        "peak_time": (format_time(peak.hour, language), float(peak.hour)),
        "peak_pm25": (_fmt(peak.pm25), peak.pm25),
        "peak_category": (labels[naqi_category(peak.pm25)], 0.0),
        "best_time": (format_time(best_h.best_hour, language), float(best_h.best_hour)),
        "best_pm25": (_fmt(best_h.pm25_best), best_h.pm25_best),
        "household_cut_pct": (_fmt(cut), cut),
    }
    for key, (text, num) in globals_.items():
        values[key] = text
        numeric[key] = num
    return FactsPayload(language=language, values=values, numeric=numeric)


def summary_text(language: Language) -> str:
    """Deterministic fallback summary with placeholders."""
    return SUMMARY_TEMPLATES[language]


# ------------------------------------------------------------------------------------------
# Public entry point
# ------------------------------------------------------------------------------------------


def build_plan(household: Household, profile: DayProfile) -> Plan:
    """Build the full plan for a household and a 24-hour forecast profile."""
    weights = {m.id: vulnerability_weight(m) for m in household.members}
    totals = _Totals.empty(household)
    entries: list[LedgerEntry] = []

    timeline = _plan_activities(profile, household, weights, totals, entries)
    commute = _plan_trips(profile, household, weights, totals, entries)
    _plan_home(profile, household, weights, totals, entries)
    sources = _plan_sources(household, weights, entries)

    ranked = [
        e.model_copy(update={"id": f"a{i}"})
        for i, e in enumerate(rank_actions(entries, household.budget), start=1)
    ]

    summaries: list[MemberSummary] = []
    for m in household.members:
        base, plan = totals.baseline[m.id], totals.plan[m.id]
        sensitive = is_sensitive(m)
        summaries.append(
            MemberSummary(
                member_id=m.id,
                name=m.name,
                weight=weights[m.id],
                dose_baseline_ug=base,
                dose_plan_ug=plan,
                pct_change=100 * (base - plan) / base if base > 0 else 0.0,
                cigarettes_avoided=totals.cigarettes[m.id],
                avoid_exertion_hours=[
                    h.hour for h in profile.hours if avoid_exertion(h.pm25, sensitive)
                ],
            )
        )

    hours = [
        HourSummary(
            hour=h.hour,
            pm25=h.pm25,
            category=naqi_category(h.pm25),
            ssi=stagnation_index(h),
            is_daytime=h.is_daytime,
        )
        for h in profile.hours
    ]
    return Plan(
        hours=hours,
        timeline=timeline,
        actions=ranked,
        commute=commute,
        members=summaries,
        rooms=[estimate_room(profile, r) for r in household.home.rooms],
        ventilation=ventilation_window(profile),
        sources=sources,
        facts=build_facts(household, profile, ranked, summaries),
        budget=household.budget,
    )


__all__ = [
    "build_plan",
    "fallback_action_text",
    "format_time",
    "mean_stagnation",
    "render_template",
    "summary_text",
    "trip_member_dose",
]
