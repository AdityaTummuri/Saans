from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import pytest

from app.config import Settings
from app.demo import demo_household, demo_profile
from app.domain.models import Language, Location
from app.domain.planner import build_plan
from app.services.gemini import (
    LLMError,
    ask,
    build_backend,
    narrate_plan,
    narrator_prompt,
    parse_household,
)
from app.services.intake import IntakeDraft, to_household
from app.services.tools import TOOL_SPECS, ToolContext, ToolSpec

SETTINGS = Settings(demo_mode=True, _env_file=None)  # type: ignore[call-arg]


class FakeBackend:
    """Scripted stand-in for the Gemini backend."""

    def __init__(
        self,
        json_reply: str | Exception = "",
        tool_script: Callable[[Callable[[str, dict[str, Any]], dict[str, Any]]], str] | None = None,
    ) -> None:
        self.json_reply = json_reply
        self.tool_script = tool_script
        self.json_calls: list[dict[str, Any]] = []

    async def generate_json(
        self, *, model: str, system: str, prompt: str, schema: dict[str, Any]
    ) -> str:
        self.json_calls.append({"model": model, "system": system, "prompt": prompt})
        if isinstance(self.json_reply, Exception):
            raise self.json_reply
        return self.json_reply

    async def run_tools(
        self,
        *,
        model: str,
        system: str,
        prompt: str,
        tools: list[ToolSpec],
        call: Callable[[str, dict[str, Any]], dict[str, Any]],
    ) -> str:
        if self.tool_script is None:
            raise LLMError("no script")
        return self.tool_script(call)


@pytest.fixture
def plan_and_household():
    household = demo_household()
    return household, build_plan(household, demo_profile())


# ------------------------------------------------------------------ narration


async def test_narration_uses_one_call_and_fills_placeholders(plan_and_household) -> None:
    _household, plan = plan_and_household
    first = plan.actions[0]
    reply = json.dumps(
        {
            "summary": (
                "Air peaks around {{peak_time}} and the plan cuts exposure by "
                "{{household_cut_pct}}%."
            ),
            "actions": [
                {
                    "id": first.id,
                    "text": f"Do this: it cuts the dose {{{{{first.id}.dose_cut_pct}}}}%.",
                }
            ],
        }
    )
    backend = FakeBackend(reply)
    result = await narrate_plan(backend, SETTINGS, plan, Language.EN, {"elderly": "Stay in."})
    assert len(backend.json_calls) == 1  # exactly one model call per plan
    assert result.used_model and result.summary.grounded
    assert plan.facts.values["peak_time"] in result.summary.text
    assert result.actions[first.id].grounded
    assert result.actions[first.id].text == (
        f"Do this: it cuts the dose {plan.facts.values[f'{first.id}.dose_cut_pct']}%."
    )
    # Actions the model skipped fall back to templates, not to nothing.
    second = plan.actions[1]
    assert not result.actions[second.id].grounded and result.actions[second.id].text


async def test_narration_rejects_invented_numbers(plan_and_household) -> None:
    _household, plan = plan_and_household
    a = plan.actions[0]
    reply = json.dumps(
        {
            "summary": "Exposure drops by 55% today.",
            "actions": [{"id": a.id, "text": "This saves about 80 micrograms."}],
        }
    )
    result = await narrate_plan(FakeBackend(reply), SETTINGS, plan, Language.EN, {})
    assert not result.summary.grounded and result.summary.reason == "raw_digit"
    assert "55" not in result.summary.text
    assert not result.actions[a.id].grounded
    assert "80 micrograms" not in result.actions[a.id].text


async def test_narration_falls_back_on_unknown_placeholder(plan_and_household) -> None:
    _, plan = plan_and_household
    reply = json.dumps({"summary": "Cuts {{made_up}}.", "actions": []})
    result = await narrate_plan(FakeBackend(reply), SETTINGS, plan, Language.EN, {})
    assert result.summary.reason == "unknown_placeholder"


@pytest.mark.parametrize("reply", [LLMError("boom"), "not json", json.dumps({"summary": 3})])
async def test_narration_falls_back_when_model_fails(plan_and_household, reply) -> None:
    _, plan = plan_and_household
    result = await narrate_plan(FakeBackend(reply), SETTINGS, plan, Language.EN, {})
    assert not result.used_model
    assert result.summary.text and not result.summary.grounded
    assert set(result.actions) == {a.id for a in plan.actions}


async def test_narration_without_backend_is_deterministic(plan_and_household) -> None:
    _household, plan = plan_and_household
    result = await narrate_plan(None, SETTINGS, plan, Language.EN, {})
    assert not result.used_model
    first = plan.actions[0]
    assert plan.facts.values[f"{first.id}.dose_cut_pct"] in result.actions[first.id].text
    assert "{{" not in result.summary.text


async def test_hindi_fallback_has_no_leftover_placeholders() -> None:
    household = demo_household(Language.HI)
    plan = build_plan(household, demo_profile())
    result = await narrate_plan(None, SETTINGS, plan, Language.HI, {})
    for text in [result.summary.text, *(g.text for g in result.actions.values())]:
        assert "{{" not in text and re.search(r"[ऀ-ॿ]", text)


def test_narrator_prompt_contains_no_user_text(plan_and_household) -> None:
    household, plan = plan_and_household
    prompt = narrator_prompt(plan, {"elderly": "Stay in."})
    for member in household.members:
        assert member.name not in prompt
    for room in household.home.rooms:
        assert room.name not in prompt
    for activity in household.activities:
        assert activity.name not in prompt
    assert "{{a1.dose_cut_pct}}" in prompt


# ------------------------------------------------------------------ ask agent


def _ctx(plan_and_household) -> ToolContext:
    household, plan = plan_and_household
    return ToolContext(household, demo_profile(), plan)


async def test_ask_accepts_answers_built_from_tool_placeholders(plan_and_household) -> None:
    household, _ = plan_and_household
    ctx = _ctx(plan_and_household)

    def script(call):
        result = call("indoor_estimate", {"room": "Living room", "source": "incense"})
        after = result["after"]["placeholder"]
        return f"Incense would take the room to {after} micrograms per cubic metre."

    answer = await ask(FakeBackend(tool_script=script), SETTINGS, household, ctx, "Is incense ok?")
    assert answer.grounded and answer.tools_used == ["indoor_estimate"]
    assert "{{" not in answer.text and re.search(r"\d", answer.text)


async def test_ask_rejects_numbers_the_model_made_up(plan_and_household) -> None:
    household, _ = plan_and_household
    ctx = _ctx(plan_and_household)

    def script(call):
        call("indoor_estimate", {"source": "incense"})
        return "It will be about 45 micrograms, which is fine."

    answer = await ask(FakeBackend(tool_script=script), SETTINGS, household, ctx, "Is incense ok?")
    assert not answer.grounded and answer.reason == "raw_digit"
    assert "45 micrograms" not in answer.text
    assert re.search(r"\d", answer.text)  # the deterministic answer still has engine numbers


async def test_ask_falls_back_when_model_errors(plan_and_household) -> None:
    household, _ = plan_and_household
    answer = await ask(
        FakeBackend(), SETTINGS, household, _ctx(plan_and_household), "Is a diya ok tonight?"
    )
    assert not answer.grounded and answer.reason == "model_error"
    assert "Living room" in answer.text and "µg/m³" in answer.text


@pytest.mark.parametrize(
    ("question", "needle"),
    [
        ("Is a diya and incense for puja okay tonight?", "indoor"),
        ("What purifier do I need for the Kids' room?", "m³/h"),
        ("Should Meera take the metro?", "metro"),
        ("When is the best time to open windows?", "peaks"),
        ("hello", "highest-impact"),
    ],
)
async def test_keyless_ask_routes_questions_to_engine_tools(
    plan_and_household, question, needle
) -> None:
    household, _ = plan_and_household
    answer = await ask(None, SETTINGS, household, _ctx(plan_and_household), question)
    assert not answer.grounded and needle in answer.text
    assert "{{" not in answer.text


def test_tool_registry_marks_every_number_with_a_placeholder(plan_and_household) -> None:
    ctx = _ctx(plan_and_household)
    out = ctx.get_forecast(hour=13)
    for key in ("peak_pm25", "best_pm25", "hour_pm25"):
        name = out[key]["placeholder"].strip("{}")
        assert ctx.values[name] and name in ctx.numeric
    assert ctx.numeric["t1.hour_pm25"] == 140.0


def test_compute_dose_tool_matches_engine(plan_and_household) -> None:
    ctx = _ctx(plan_and_household)
    out = ctx.compute_dose("aarav", 16, 1, "vigorous", "outdoor", 12, 18)
    # child vigorous 2.4 m3/h x 240 ug/m3 x 1 h
    assert ctx.numeric["t1.dose_ug"] == pytest.approx(2.4 * 240)
    assert "best_start" in out and ctx.numeric["t1.dose_cut_pct"] == pytest.approx(100 * 100 / 240)


def test_tool_errors_are_generic(plan_and_household) -> None:
    ctx = _ctx(plan_and_household)
    assert ctx.call("nope", {}) == {"error": "unknown tool"}
    assert ctx.call("compute_dose", {"member_id": "ghost", "start_hour": 1, "duration_h": 1}) == {
        "error": "invalid arguments"
    }
    assert ctx.call("get_forecast", {"bogus": 1}) == {"error": "invalid arguments"}
    assert {s.name for s in TOOL_SPECS} == {
        "get_forecast",
        "compute_dose",
        "indoor_estimate",
        "size_purifier",
        "compare_commute",
    }


def test_size_purifier_and_commute_tools(plan_and_household) -> None:
    ctx = _ctx(plan_and_household)
    ctx.size_purifier("Parents' bedroom")
    assert ctx.numeric["t1.cadr"] % 50 == 0 and ctx.numeric["t1.cadr"] > 0
    out = ctx.compare_commute("office")
    assert len(out["options"]) == 4 and sum(o["current"] for o in out["options"]) == 1


# ------------------------------------------------------------------ intake + backend


async def test_intake_parses_structured_output() -> None:
    reply = IntakeDraft(
        address="Dwarka, Delhi",
        members=[
            {"name": "Aarav", "age_band": "child"},
            {"name": "Dadaji", "age_band": "older", "conditions": ["copd", "bogus"]},
        ],  # type: ignore[list-item]
        activities=[
            {
                "name": "Football",
                "members": ["aarav"],
                "duration_h": 1,
                "intensity": "vigorous",
                "start_hour": 16,
                "window_start": 12,
                "window_end": 18,
            }
        ],  # type: ignore[list-item]
        trips=[{"name": "Office", "members": ["Dadaji"], "mode": "spaceship"}],  # type: ignore[list-item]
        sources=[{"kind": "incense"}, {"kind": "unknown"}],  # type: ignore[list-item]
    ).model_dump_json()
    backend = FakeBackend(reply)
    draft = await parse_household(backend, SETTINGS, "my family...")
    assert backend.json_calls[0]["model"] == SETTINGS.gemini_lite_model
    household = to_household(draft, Location(lat=28.61, lon=77.21))
    assert [m.id for m in household.members] == ["aarav", "dadaji"]
    assert [c.value for c in household.members[1].conditions] == ["copd"]
    assert household.activities[0].shiftable and household.activities[0].member_ids == ["aarav"]
    assert household.trips[0].mode.value == "car"  # unknown mode defaults
    assert len(household.home.sources) == 1  # unknown source dropped
    assert household.home.rooms  # a default room is created


async def test_intake_rejects_malformed_output() -> None:
    with pytest.raises(LLMError):
        await parse_household(FakeBackend("{not json"), SETTINGS, "x")


def test_intake_needs_at_least_one_member() -> None:
    with pytest.raises(ValueError, match="no household members"):
        to_household(IntakeDraft(), Location(lat=1, lon=1))


def test_no_backend_without_credentials() -> None:
    assert build_backend(Settings(demo_mode=True, _env_file=None)) is None  # type: ignore[call-arg]
    assert build_backend(Settings(demo_mode=False, _env_file=None)) is None  # type: ignore[call-arg]


def test_backend_builds_with_an_api_key() -> None:
    settings = Settings(gemini_api_key="local-dev-key", _env_file=None)  # type: ignore[arg-type,call-arg]
    assert build_backend(settings) is not None
