"""Lenient intake draft produced by Gemini, and its conversion into a validated Household.

Gemini fills in this loose shape from the family's own words. The draft is then coerced into the
strict domain models (unknown values dropped or defaulted, numbers clamped) and validated, and
the UI shows the result for the user to confirm and edit.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.domain.models import (
    Activity,
    AgeBand,
    BudgetTier,
    Condition,
    CookingFuel,
    Home,
    HomeSource,
    Household,
    Intensity,
    Language,
    Location,
    LocationType,
    Member,
    Room,
    SourceUse,
    TravelMode,
    Trip,
    TripOption,
    WindowType,
)

DEFAULT_TRIP_MINUTES = 30.0
DEFAULT_TRIP_KM = 8.0


class DraftMember(BaseModel):
    name: str
    age_band: str = "adult"
    conditions: list[str] = Field(default_factory=list)


class DraftActivity(BaseModel):
    name: str
    members: list[str] = Field(default_factory=list)
    duration_h: float = 1.0
    intensity: str = "light"
    location: str = "outdoor"
    start_hour: float = 16.0
    window_start: float | None = None
    window_end: float | None = None


class DraftTrip(BaseModel):
    name: str
    members: list[str] = Field(default_factory=list)
    mode: str = "car"
    depart_hour: float = 8.0
    depart_flex_h: float = 0.0
    origin: str = ""
    destination: str = ""
    duration_min: float | None = None
    distance_km: float | None = None


class DraftRoom(BaseModel):
    name: str
    volume_m3: float = 30.0
    windows: str = "leaky"
    purifier_cadr: float = 0.0
    occupants: list[str] = Field(default_factory=list)


class DraftSource(BaseModel):
    kind: str
    hours_per_day: float = 1.0
    room: str | None = None


class IntakeDraft(BaseModel):
    address: str = ""
    members: list[DraftMember] = Field(default_factory=list)
    activities: list[DraftActivity] = Field(default_factory=list)
    trips: list[DraftTrip] = Field(default_factory=list)
    rooms: list[DraftRoom] = Field(default_factory=list)
    sources: list[DraftSource] = Field(default_factory=list)
    cooking_fuel: str = "lpg"
    budget: str = "medium"
    language: str = "en"


def slug(text: str, taken: set[str], fallback: str) -> str:
    """A unique id matching ^[a-z][a-z0-9_]{0,15}$."""
    base = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:12]
    if not base or not base[0].isalpha():
        base = f"{fallback}_{base}".strip("_")[:12]
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base[:12]}_{n}"
        n += 1
    taken.add(candidate)
    return candidate


def _enum[
    E: (
        AgeBand,
        Condition,
        Intensity,
        LocationType,
        TravelMode,
        WindowType,
        CookingFuel,
        HomeSource,
        BudgetTier,
        Language,
    )
](cls: type[E], value: str, default: E | None) -> E | None:
    try:
        return cls(value.strip().lower())
    except ValueError:
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def to_household(
    draft: IntakeDraft,
    location: Location,
    trip_options: dict[int, list[TripOption]] | None = None,
) -> Household:
    """Coerce a draft into a validated Household.

    `trip_options` maps a trip's index in the draft to Routes API options. Trips without
    options fall back to one option for the stated mode (user-given or default duration).
    """
    trip_options = trip_options or {}
    taken: set[str] = set()
    members: list[Member] = []
    ids: dict[str, str] = {}
    for dm in draft.members[:10]:
        mid = slug(dm.name, taken, "m")
        ids[dm.name.strip().lower()] = mid
        conditions = [
            cond for raw in dm.conditions if (cond := _enum(Condition, raw, None)) is not None
        ]
        members.append(
            Member(
                id=mid,
                name=dm.name.strip()[:60] or "Member",
                age_band=_enum(AgeBand, dm.age_band, AgeBand.ADULT) or AgeBand.ADULT,
                conditions=list(dict.fromkeys(conditions)),
            )
        )
    if not members:
        raise ValueError("no household members found")
    everyone = [m.id for m in members]

    def resolve(names: list[str]) -> list[str]:
        found = [ids[n.strip().lower()] for n in names if n.strip().lower() in ids]
        return list(dict.fromkeys(found)) or everyone

    activities: list[Activity] = []
    act_ids: set[str] = set()
    for da in draft.activities[:20]:
        duration = _clamp(da.duration_h, 0.25, 12)
        window: dict[str, Any] = {}
        if da.window_start is not None and da.window_end is not None:
            start = _clamp(da.window_start, 0, 24)
            end = _clamp(da.window_end, 0, 24)
            if end - start >= duration:
                window = {"window_start": start, "window_end": end}
        activities.append(
            Activity(
                id=slug(da.name, act_ids, "act"),
                name=da.name.strip()[:60] or "Activity",
                member_ids=resolve(da.members),
                duration_h=duration,
                intensity=_enum(Intensity, da.intensity, Intensity.LIGHT) or Intensity.LIGHT,
                location=_enum(LocationType, da.location, LocationType.OUTDOOR)
                or LocationType.OUTDOOR,
                start_hour=_clamp(da.start_hour, 0, 23.99),
                **window,
            )
        )

    trips: list[Trip] = []
    trip_ids: set[str] = set()
    for index, dt in enumerate(draft.trips[:10]):
        mode = _enum(TravelMode, dt.mode, TravelMode.CAR) or TravelMode.CAR
        options = list(trip_options.get(index, []))
        if mode not in {o.mode for o in options}:
            options.append(
                TripOption(
                    mode=mode,
                    duration_min=_clamp(dt.duration_min or DEFAULT_TRIP_MINUTES, 1, 600),
                    distance_km=_clamp(dt.distance_km or DEFAULT_TRIP_KM, 0, 500),
                )
            )
        trips.append(
            Trip(
                id=slug(dt.name, trip_ids, "trip"),
                name=dt.name.strip()[:60] or "Trip",
                member_ids=resolve(dt.members),
                mode=mode,
                depart_hour=_clamp(dt.depart_hour, 0, 23.99),
                depart_flex_h=_clamp(dt.depart_flex_h, 0, 6),
                options=options,
            )
        )

    rooms = [
        Room(
            name=dr.name.strip()[:60] or "Room",
            volume_m3=_clamp(dr.volume_m3, 2, 1000),
            windows=_enum(WindowType, dr.windows, WindowType.LEAKY) or WindowType.LEAKY,
            purifier_cadr_m3_per_h=_clamp(dr.purifier_cadr, 0, 2000),
            occupant_ids=[ids[o.strip().lower()] for o in dr.occupants if o.strip().lower() in ids],
        )
        for dr in draft.rooms[:10]
    ] or [Room(name="Living room", volume_m3=40, occupant_ids=everyone)]

    room_names = {r.name.lower(): r.name for r in rooms}
    sources = []
    for ds in draft.sources[:10]:
        kind = _enum(HomeSource, ds.kind, None)
        if kind is None:
            continue
        sources.append(
            SourceUse(
                kind=kind,
                hours_per_day=_clamp(ds.hours_per_day, 0.05, 24),
                room=room_names.get((ds.room or "").lower()),
            )
        )

    return Household(
        location=location,
        members=members,
        activities=activities,
        trips=trips,
        home=Home(
            rooms=rooms,
            cooking_fuel=_enum(CookingFuel, draft.cooking_fuel, CookingFuel.LPG) or CookingFuel.LPG,
            sources=sources,
        ),
        budget=_enum(BudgetTier, draft.budget, BudgetTier.MEDIUM) or BudgetTier.MEDIUM,
        language=_enum(Language, draft.language, Language.EN) or Language.EN,
    )
