"""Typed domain models. Pure data with validation bounds; no I/O."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AgeBand(StrEnum):
    INFANT = "infant"  # 0 to 2 years
    CHILD = "child"  # 3 to 12
    TEEN = "teen"  # 13 to 17
    ADULT = "adult"  # 18 to 64
    OLDER = "older"  # 65 and over


class Condition(StrEnum):
    ASTHMA = "asthma"
    COPD = "copd"
    HEART_DISEASE = "heart_disease"
    PREGNANCY = "pregnancy"


class Intensity(StrEnum):
    REST = "rest"
    LIGHT = "light"
    MODERATE = "moderate"
    VIGOROUS = "vigorous"


class LocationType(StrEnum):
    OUTDOOR = "outdoor"
    ROADSIDE = "roadside"
    INDOOR = "indoor"


class TravelMode(StrEnum):
    WALK = "walk"
    CYCLE = "cycle"
    TWO_WHEELER = "two_wheeler"
    AUTO_RICKSHAW = "auto_rickshaw"
    CAR = "car"
    BUS = "bus"
    METRO = "metro"


class WindowType(StrEnum):
    LEAKY = "leaky"
    SEALED = "sealed"


class CookingFuel(StrEnum):
    LPG = "lpg"
    ELECTRIC = "electric"
    WOOD = "wood"
    COAL = "coal"


class HomeSource(StrEnum):
    INCENSE = "incense"
    MOSQUITO_COIL = "mosquito_coil"
    FRYING = "frying"
    DIYA = "diya"
    WOOD_COOKING = "wood_cooking"
    WASTE_BURNING = "waste_burning"
    COAL_HEATING = "coal_heating"
    FIRECRACKERS = "firecrackers"


class BudgetTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Language(StrEnum):
    EN = "en"
    HI = "hi"


class ActionKind(StrEnum):
    SHIFT_ACTIVITY = "shift_activity"
    MASK = "mask"
    MODE_SWITCH = "mode_switch"
    DEPARTURE_SHIFT = "departure_shift"
    RECIRCULATION = "recirculation"
    PURIFIER = "purifier"
    CR_BOX = "cr_box"
    SEAL_GAPS = "seal_gaps"
    SKIP_SOURCE = "skip_source"
    STOP_BURNING = "stop_burning"


Name = Annotated[str, Field(min_length=1, max_length=60)]
Hour = Annotated[int, Field(ge=0, le=23)]
Duration = Annotated[float, Field(gt=0, le=24)]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class Location(_Strict):
    lat: Annotated[float, Field(ge=-90, le=90)]
    lon: Annotated[float, Field(ge=-180, le=180)]
    label: Annotated[str, Field(max_length=120)] = ""

    @model_validator(mode="after")
    def _round_for_privacy(self) -> Self:
        self.lat = round(self.lat, 2)
        self.lon = round(self.lon, 2)
        return self


class Member(_Strict):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,15}$")]
    name: Name
    age_band: AgeBand
    conditions: list[Condition] = Field(default_factory=list, max_length=4)


class Activity(_Strict):
    """A routine activity. It is shiftable when a window is given."""

    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,15}$")]
    name: Name
    member_ids: Annotated[list[str], Field(min_length=1, max_length=10)]
    duration_h: Duration
    intensity: Intensity
    location: LocationType
    start_hour: Annotated[float, Field(ge=0, lt=24)]
    window_start: Annotated[float, Field(ge=0, le=24)] | None = None
    window_end: Annotated[float, Field(ge=0, le=24)] | None = None
    mask: bool = False

    @model_validator(mode="after")
    def _window_is_consistent(self) -> Self:
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("window_start and window_end must be given together")
        if (
            self.window_start is not None
            and self.window_end is not None
            and self.window_end - self.window_start < self.duration_h
        ):
            raise ValueError("window is shorter than the activity")
        return self

    @property
    def shiftable(self) -> bool:
        return self.window_start is not None and self.window_end is not None


class TripOption(_Strict):
    """Duration and distance for one travel mode, as returned by the Routes API."""

    mode: TravelMode
    duration_min: Annotated[float, Field(gt=0, le=1440)]
    distance_km: Annotated[float, Field(ge=0, le=2000)]


class Trip(_Strict):
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,15}$")]
    name: Name
    member_ids: Annotated[list[str], Field(min_length=1, max_length=10)]
    mode: TravelMode
    depart_hour: Annotated[float, Field(ge=0, lt=24)]
    depart_flex_h: Annotated[float, Field(ge=0, le=6)] = 0.0
    mask: bool = False
    options: Annotated[list[TripOption], Field(min_length=1, max_length=10)]

    @model_validator(mode="after")
    def _current_mode_has_option(self) -> Self:
        if self.mode not in {o.mode for o in self.options}:
            raise ValueError("current mode must appear in options")
        return self

    def option(self, mode: TravelMode) -> TripOption:
        for opt in self.options:
            if opt.mode == mode:
                return opt
        raise KeyError(mode)


class Room(_Strict):
    name: Name
    volume_m3: Annotated[float, Field(gt=1, le=1000)]
    windows: WindowType = WindowType.LEAKY
    purifier_cadr_m3_per_h: Annotated[float, Field(ge=0, le=2000)] = 0.0
    occupant_ids: Annotated[list[str], Field(max_length=10)] = Field(default_factory=list)
    occupied_from: Annotated[int, Field(ge=0, le=23)] = 22
    occupied_to: Annotated[int, Field(ge=0, le=23)] = 6


class SourceUse(_Strict):
    kind: HomeSource
    hours_per_day: Annotated[float, Field(gt=0, le=24)] = 1.0
    room: str | None = None


class Home(_Strict):
    rooms: Annotated[list[Room], Field(min_length=1, max_length=10)]
    cooking_fuel: CookingFuel = CookingFuel.LPG
    sources: Annotated[list[SourceUse], Field(max_length=10)] = Field(default_factory=list)


class Household(_Strict):
    location: Location
    members: Annotated[list[Member], Field(min_length=1, max_length=10)]
    activities: Annotated[list[Activity], Field(max_length=20)] = Field(default_factory=list)
    trips: Annotated[list[Trip], Field(max_length=10)] = Field(default_factory=list)
    home: Home
    budget: BudgetTier = BudgetTier.MEDIUM
    language: Language = Language.EN

    @model_validator(mode="after")
    def _references_resolve(self) -> Self:
        ids = [m.id for m in self.members]
        if len(set(ids)) != len(ids):
            raise ValueError("member ids must be unique")
        known = set(ids)
        referenced = [i for a in self.activities for i in a.member_ids]
        referenced += [i for t in self.trips for i in t.member_ids]
        referenced += [i for r in self.home.rooms for i in r.occupant_ids]
        missing = set(referenced) - known
        if missing:
            raise ValueError(f"unknown member ids: {sorted(missing)}")
        return self

    def member(self, member_id: str) -> Member:
        for m in self.members:
            if m.id == member_id:
                return m
        raise KeyError(member_id)


# ------------------------------------------------------------------------------------------
# Forecast inputs
# ------------------------------------------------------------------------------------------


class HourlyConditions(_Strict):
    """One local clock hour of forecast data."""

    hour: Hour
    pm25: Annotated[float, Field(ge=0, le=2000)]
    wind_kmh: Annotated[float, Field(ge=0, le=400)] = 5.0
    humidity_pct: Annotated[float, Field(ge=0, le=100)] = 50.0
    visibility_km: Annotated[float, Field(ge=0, le=100)] = 10.0
    cloud_cover_pct: Annotated[float, Field(ge=0, le=100)] = 50.0
    is_daytime: bool = True


class DayProfile(_Strict):
    """Exactly 24 hours of conditions indexed by local clock hour."""

    hours: Annotated[list[HourlyConditions], Field(min_length=24, max_length=24)]

    @model_validator(mode="after")
    def _indexed_by_hour(self) -> Self:
        if [h.hour for h in self.hours] != list(range(24)):
            raise ValueError("hours must be ordered 0..23")
        return self

    def at(self, hour: int) -> HourlyConditions:
        return self.hours[hour % 24]


# ------------------------------------------------------------------------------------------
# Plan outputs
# ------------------------------------------------------------------------------------------


class MemberDelta(_Strict):
    member_id: str
    dose_before_ug: float
    dose_after_ug: float
    cigarettes_avoided: float = 0.0

    @property
    def avoided_ug(self) -> float:
        return self.dose_before_ug - self.dose_after_ug


class LedgerEntry(_Strict):
    """One quantified action in the Exposure Ledger."""

    id: str
    kind: ActionKind
    subject: str  # activity, trip, room or source this action applies to
    effort_tier: Annotated[int, Field(ge=1, le=4)]
    members: list[MemberDelta]
    avoided_ug: float
    weighted_avoided_ug: float
    pct_change: float  # percentage drop of the affected members' dose, positive = better
    cigarettes_avoided: float
    co2_avoided_kg: float
    pm25_avoided_g: float = 0.0
    score: float = 0.0
    tradeoff: bool = False  # True when exposure rises slightly in exchange for lower emissions
    details: dict[str, str | float] = Field(default_factory=dict)


class TimelineItem(_Strict):
    activity_id: str
    name: str
    member_ids: list[str]
    original_start: float
    planned_start: float
    duration_h: float
    shifted: bool
    reason: str  # reason key, e.g. "cleaner_air", "no_better_window", "fixed"
    pm25_before: float
    pm25_after: float
    ssi_before: float
    ssi_after: float
    dose_cut_pct: float


class CommuteOption(_Strict):
    mode: TravelMode
    duration_min: float
    distance_km: float
    dose_ug: float  # weighted-free: sum over travelling members
    co2_kg: float
    current: bool


class CommuteComparison(_Strict):
    trip_id: str
    name: str
    options: list[CommuteOption]


class RoomEstimate(_Strict):
    room: str
    outdoor_pm25: float
    indoor_now: float
    indoor_no_purifier: float
    indoor_with_purifier: float
    indoor_purifier_sealed: float
    category_now: str
    cadr_needed: float
    purifier_cadr: float


class VentilationWindow(_Strict):
    best_hour: Hour
    pm25_best: float
    pm25_waking_mean: float
    minutes: int


class SourceFlag(_Strict):
    kind: HomeSource
    room: str | None
    indoor_increase: float  # ug/m^3 added in the room while in use; 0 for outdoor sources
    neighbourhood: bool
    co2_kg_per_day: float
    pm25_g_per_day: float


class MemberSummary(_Strict):
    member_id: str
    name: str
    weight: float
    dose_baseline_ug: float
    dose_plan_ug: float
    pct_change: float
    cigarettes_avoided: float
    avoid_exertion_hours: list[int]


class HourSummary(_Strict):
    hour: Hour
    pm25: float
    category: str
    ssi: float
    is_daytime: bool


class FactsPayload(_Strict):
    """Flat, pre-formatted named facts used by the narrator and the grounding guard."""

    language: Language
    values: dict[str, str]
    numeric: dict[str, float]


class Plan(_Strict):
    hours: list[HourSummary]
    timeline: list[TimelineItem]
    actions: list[LedgerEntry]
    commute: list[CommuteComparison]
    members: list[MemberSummary]
    rooms: list[RoomEstimate]
    ventilation: VentilationWindow
    sources: list[SourceFlag]
    facts: FactsPayload
    budget: BudgetTier
