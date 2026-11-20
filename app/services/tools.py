"""Read-only engine tools for the Ask agent.

Every number a tool returns is registered under a placeholder (for example {{t1.pm25}}). The
model sees the value so it can reason, but it must write the placeholder; the grounding guard
then rejects any raw digit, so only engine numbers can reach the user.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.domain import constants as c
from app.domain.exposure import (
    activity_dose,
    cigarettes,
    mean_pm25,
    naqi_category,
    schedule_activity,
)
from app.domain.indoor import (
    air_exchange_rate,
    cadr_needed,
    indoor_pm25,
    mean_outdoor_when_occupied,
    round_up_cadr,
    ventilation_window,
)
from app.domain.labels import CATEGORY_LABELS, MODE_LABELS, SOURCE_LABELS
from app.domain.models import (
    Activity,
    DayProfile,
    HomeSource,
    Household,
    Intensity,
    LocationType,
    Plan,
    Room,
)
from app.domain.planner import format_time
from app.domain.stagnation import stagnation_index


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]


def _obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required or []}


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        "get_forecast",
        "Outdoor PM2.5 forecast for today: the worst hour, the cleanest waking hour and, "
        "optionally, one specific hour.",
        _obj({"hour": {"type": "integer", "description": "Clock hour 0 to 23 (optional)"}}),
    ),
    ToolSpec(
        "compute_dose",
        "Inhaled PM2.5 for a household member doing an activity, plus the cleanest start "
        "inside the given window.",
        _obj(
            {
                "member_id": {"type": "string"},
                "start_hour": {"type": "number"},
                "duration_h": {"type": "number"},
                "intensity": {"type": "string", "enum": [i.value for i in Intensity]},
                "location": {"type": "string", "enum": [lt.value for lt in LocationType]},
                "window_start": {"type": "number"},
                "window_end": {"type": "number"},
            },
            ["member_id", "start_hour", "duration_h", "intensity"],
        ),
    ),
    ToolSpec(
        "indoor_estimate",
        "Indoor PM2.5 for a room, optionally with an extra indoor source in use, a purifier "
        "CADR, or sealed windows.",
        _obj(
            {
                "room": {"type": "string"},
                "source": {"type": "string", "enum": [s.value for s in HomeSource]},
                "source_hours": {"type": "number"},
                "purifier_cadr": {"type": "number"},
                "sealed": {"type": "boolean"},
            }
        ),
    ),
    ToolSpec(
        "size_purifier",
        "The purifier CADR (m3/h) needed to bring a room to a target PM2.5.",
        _obj(
            {"room": {"type": "string"}, "target_pm25": {"type": "number"}},
            ["room"],
        ),
    ),
    ToolSpec(
        "compare_commute",
        "Compare travel modes for one trip on inhaled dose, duration and CO2.",
        _obj({"trip_id": {"type": "string"}}, ["trip_id"]),
    ),
]


@dataclass
class ToolContext:
    """Per-request state: the household, the day's forecast and the facts the tools produce."""

    household: Household
    profile: DayProfile
    plan: Plan
    values: dict[str, str] = field(default_factory=dict)
    numeric: dict[str, float] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.values.update(self.plan.facts.values)
        self.numeric.update(self.plan.facts.numeric)

    @property
    def language(self) -> Any:
        return self.household.language

    def _register(self, prefix: str, items: dict[str, tuple[float | str, int]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, (value, decimals) in items.items():
            name = f"{prefix}.{key}"
            if isinstance(value, str):
                self.values[name] = value
                out[key] = {"text": value, "placeholder": "{{" + name + "}}"}
            else:
                self.values[name] = f"{value:.{decimals}f}"
                self.numeric[name] = value
                out[key] = {"value": round(value, 2), "placeholder": "{{" + name + "}}"}
        return out

    def _prefix(self, tool: str) -> str:
        self.calls.append(tool)
        return f"t{len(self.calls)}"

    def _room(self, name: str | None) -> Room:
        rooms = self.household.home.rooms
        if name:
            for room in rooms:
                if room.name.lower() == name.lower():
                    return room
        return rooms[0]

    # ------------------------------------------------------------------ tools

    def get_forecast(self, hour: int | None = None) -> dict[str, Any]:
        p = self._prefix("get_forecast")
        cats = CATEGORY_LABELS[self.language]
        peak = max(self.profile.hours, key=lambda h: h.pm25)
        vent = ventilation_window(self.profile)
        items: dict[str, tuple[float | str, int]] = {
            "peak_time": (format_time(peak.hour, self.language), 0),
            "peak_pm25": (peak.pm25, 0),
            "peak_category": (cats[naqi_category(peak.pm25)], 0),
            "best_time": (format_time(vent.best_hour, self.language), 0),
            "best_pm25": (vent.pm25_best, 0),
        }
        if hour is not None and 0 <= hour <= 23:
            cond = self.profile.at(hour)
            items["hour_time"] = (format_time(hour, self.language), 0)
            items["hour_pm25"] = (cond.pm25, 0)
            items["hour_category"] = (cats[naqi_category(cond.pm25)], 0)
            items["hour_stagnation"] = (stagnation_index(cond), 0)
        return self._register(p, items)

    def compute_dose(
        self,
        member_id: str,
        start_hour: float,
        duration_h: float,
        intensity: str = "light",
        location: str = "outdoor",
        window_start: float | None = None,
        window_end: float | None = None,
    ) -> dict[str, Any]:
        p = self._prefix("compute_dose")
        member = self.household.member(member_id)
        window = (
            {"window_start": window_start, "window_end": window_end}
            if window_start is not None and window_end is not None
            else {}
        )
        activity = Activity(
            id="query",
            name="Query",
            member_ids=[member.id],
            duration_h=duration_h,
            intensity=Intensity(intensity),
            location=LocationType(location),
            start_hour=start_hour % 24,
            **window,
        )
        dose = activity_dose(self.profile, activity, member)
        items: dict[str, tuple[float | str, int]] = {
            "dose_ug": (dose, 0),
            "mean_pm25": (mean_pm25(self.profile, activity.start_hour, duration_h), 0),
            "cigarettes": (cigarettes(dose, member.age_band, activity.intensity), 1),
        }
        if activity.shiftable:
            res = schedule_activity(self.profile, activity, [member])
            items["best_start"] = (format_time(res.chosen_start, self.language), 0)
            items["dose_cut_pct"] = (res.pct_cut, 0)
        return self._register(p, items)

    def indoor_estimate(
        self,
        room: str | None = None,
        source: str | None = None,
        source_hours: float = 1.0,
        purifier_cadr: float | None = None,
        sealed: bool | None = None,
    ) -> dict[str, Any]:
        p = self._prefix("indoor_estimate")
        r = self._room(room)
        c_out = mean_outdoor_when_occupied(self.profile, r)
        a = air_exchange_rate(r.windows)
        v = r.volume_m3
        before = indoor_pm25(c_out, a, v, r.purifier_cadr_m3_per_h)
        a2 = c.AIR_EXCHANGE_SEALED_PER_H if sealed else a
        cadr2 = r.purifier_cadr_m3_per_h if purifier_cadr is None else purifier_cadr
        strength = 0.0
        label = ""
        if source:
            kind = HomeSource(source)
            strength = c.SOURCE_STRENGTH_UG_PER_H.get(kind, 0.0)
            label = SOURCE_LABELS[self.language][kind]
        after = indoor_pm25(c_out, a2, v, cadr2, strength)
        items: dict[str, tuple[float | str, int]] = {
            "room": (r.name, 0),
            "outdoor_pm25": (c_out, 0),
            "before": (before, 0),
            "after": (after, 0),
            "after_category": (CATEGORY_LABELS[self.language][naqi_category(after)], 0),
        }
        if label:
            items["source"] = (label, 0)
            items["increase"] = (max(after - indoor_pm25(c_out, a2, v, cadr2), 0.0), 0)
            items["hours"] = (source_hours, 1)
        return self._register(p, items)

    def size_purifier(self, room: str, target_pm25: float = c.INDOOR_TARGET_PM25) -> dict[str, Any]:
        p = self._prefix("size_purifier")
        r = self._room(room)
        c_out = mean_outdoor_when_occupied(self.profile, r)
        need = cadr_needed(c_out, air_exchange_rate(r.windows), r.volume_m3, max(target_pm25, 1.0))
        return self._register(
            p,
            {
                "room": (r.name, 0),
                "target": (max(target_pm25, 1.0), 0),
                "cadr": (round_up_cadr(need), 0),
            },
        )

    def compare_commute(self, trip_id: str) -> dict[str, Any]:
        p = self._prefix("compare_commute")
        comp = next((x for x in self.plan.commute if x.trip_id == trip_id), None)
        if comp is None and self.plan.commute:
            comp = self.plan.commute[0]
        if comp is None:
            return {"error": "no trips in this household"}
        labels = self.household.language
        out: dict[str, Any] = {"trip": comp.name, "options": []}
        for i, opt in enumerate(comp.options):
            reg = self._register(
                f"{p}_{i}",
                {
                    "mode": (MODE_LABELS[labels][opt.mode], 0),
                    "minutes": (opt.duration_min, 0),
                    "dose_ug": (opt.dose_ug, 0),
                    "co2_kg": (opt.co2_kg, 1),
                },
            )
            reg["current"] = opt.current
            out["options"].append(reg)
        return out

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a model-requested tool call; bad arguments become an error result."""
        handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "get_forecast": self.get_forecast,
            "compute_dose": self.compute_dose,
            "indoor_estimate": self.indoor_estimate,
            "size_purifier": self.size_purifier,
            "compare_commute": self.compare_commute,
        }
        handler = handlers.get(name)
        if handler is None:
            return {"error": "unknown tool"}
        try:
            return handler(**args)
        except (TypeError, ValueError, KeyError):
            return {"error": "invalid arguments"}
