"""Deterministic answers for the Ask agent when Gemini is unavailable or its text is rejected.

A small keyword router picks an engine tool, runs it, and fills a template, so the demo works
without any key and every number still comes from the engine.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.domain.models import Language
from app.domain.planner import fallback_action_text
from app.services.grounding import fill

if TYPE_CHECKING:
    from app.services.tools import ToolContext

SOURCE_WORDS = {
    "incense": ("incense", "agarbatti", "अगरबत्ती", "dhoop", "धूप"),
    "diya": ("diya", "deepak", "दीया", "दीपक", "lamp", "puja", "pooja", "पूजा"),
    "mosquito_coil": ("coil", "मच्छर", "mosquito"),
    "frying": ("fry", "frying", "तल", "pakora", "पकौड़"),
}
PURIFIER_WORDS = ("purifier", "cadr", "प्यूरीफ", "प्यूरीफ़", "air cleaner", "filter")
COMMUTE_WORDS = ("commute", "metro", "auto", "bus", "office", "school run", "मेट्रो", "ऑफिस", "सफर")
FORECAST_WORDS = ("when", "forecast", "aqi", "best time", "ventilat", "window", "कब", "हवा")

TEMPLATES: dict[Language, dict[str, str]] = {
    Language.EN: {
        "source": (
            "Using {{t.source}} in {{t.room}} would raise indoor {{pm}} from {{t.before}} to "
            "{{t.after}} µg/m³ ({{t.after_category}}) while it burns. Ventilate when outdoor air "
            "is cleanest, around {{best_time}}."
        ),
        "purifier": (
            "To bring {{t.room}} down to about {{t.target}} µg/m³ you need a purifier rated "
            "around {{t.cadr}} m³/h."
        ),
        "forecast": (
            "Outdoor {{pm}} peaks around {{t.peak_time}} at {{t.peak_pm25}} µg/m³ "
            "({{t.peak_category}}) and is lowest around {{t.best_time}} at {{t.best_pm25}} µg/m³."
        ),
        "commute_row": (
            "{{r.mode}}: {{r.minutes}} min, {{r.dose_ug}} µg inhaled, {{r.co2_kg}} kg CO₂"
        ),
        "top": "These are the highest-impact steps today:",
        "none": "I can only answer questions about air quality and your household's plan.",
    },
    Language.HI: {
        "source": (
            "{{t.room}} में {{t.source}} जलाने पर अंदर का {{pm}} {{t.before}} से बढ़कर {{t.after}} "
            "µg/m³ ({{t.after_category}}) हो जाता है। जब बाहर की हवा सबसे साफ़ हो, यानी "
            "{{best_time}} के आसपास, तब खिड़कियाँ खोलें।"
        ),
        "purifier": (
            "{{t.room}} को लगभग {{t.target}} µg/m³ तक लाने के लिए करीब {{t.cadr}} m³/h क्षमता "
            "का प्यूरीफ़ायर चाहिए।"
        ),
        "forecast": (
            "बाहर का {{pm}} {{t.peak_time}} के आसपास सबसे ज़्यादा ({{t.peak_pm25}} µg/m³, "
            "{{t.peak_category}}) और {{t.best_time}} के आसपास सबसे कम ({{t.best_pm25}} µg/m³) रहेगा।"
        ),
        "commute_row": (
            "{{r.mode}}: {{r.minutes}} मिनट, {{r.dose_ug}} µg साँस में, {{r.co2_kg}} किग्रा CO₂"
        ),
        "top": "आज के सबसे असरदार कदम:",
        "none": "मैं केवल वायु गुणवत्ता और आपके घर की योजना से जुड़े सवालों के जवाब दे सकता हूँ।",
    },
}


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def _room_for(ctx: ToolContext, kind: str) -> str:
    """The room where this source is already used, else the most-occupied room."""
    for use in ctx.household.home.sources:
        if use.kind.value == kind and use.room:
            return use.room
    return max(ctx.household.home.rooms, key=lambda r: len(r.occupant_ids)).name


def _rewrite(template: str, prefix: str) -> str:
    return re.sub(r"\{\{t\.", "{{" + prefix + ".", template)


def fallback_answer(question: str, ctx: ToolContext, language: Language) -> str:
    """Pick a tool by keyword, run it, and fill a template from the registered facts."""
    q = question.lower()
    t = TEMPLATES[language]
    source = next((k for k, words in SOURCE_WORDS.items() if _has(q, words)), None)
    if source:
        ctx.indoor_estimate(room=_room_for(ctx, source), source=source)
        return fill(_rewrite(t["source"], f"t{len(ctx.calls)}"), ctx.values)
    if _has(q, PURIFIER_WORDS):
        room = next((r.name for r in ctx.household.home.rooms if r.name.lower() in q), None)
        ctx.size_purifier(room or ctx.household.home.rooms[0].name)
        return fill(_rewrite(t["purifier"], f"t{len(ctx.calls)}"), ctx.values)
    if _has(q, COMMUTE_WORDS) and ctx.household.trips:
        result = ctx.compare_commute(ctx.household.trips[0].id)
        prefix = f"t{len(ctx.calls)}"
        rows = [
            fill(t["commute_row"].replace("{{r.", "{{" + f"{prefix}_{i}."), ctx.values)
            for i in range(len(result.get("options", [])))
        ]
        if rows:
            return f"{result['trip']}: " + "; ".join(rows)
    if _has(q, FORECAST_WORDS):
        ctx.get_forecast()
        return fill(_rewrite(t["forecast"], f"t{len(ctx.calls)}"), ctx.values)
    if ctx.plan.actions:
        lines = [fill(fallback_action_text(a, language), ctx.values) for a in ctx.plan.actions[:3]]
        return t["top"] + " " + " ".join(lines)
    return t["none"]


__all__ = ["fallback_answer"]
