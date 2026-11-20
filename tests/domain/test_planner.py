from __future__ import annotations

import re

import pytest

from app.demo import demo_household
from app.domain.labels import ACTION_TEMPLATES, SUMMARY_TEMPLATES
from app.domain.models import (
    ActionKind,
    BudgetTier,
    DayProfile,
    Household,
    Language,
    Member,
)
from app.domain.planner import (
    CONSTANT_TERMS,
    build_plan,
    fallback_action_text,
    format_time,
    render_template,
)

PLACEHOLDER = re.compile(r"\{\{([a-z0-9_.]+)\}\}")


def test_demo_plan_shifts_football_to_a_cleaner_daylight_hour(
    household: Household, profile: DayProfile
) -> None:
    plan = build_plan(household, profile)
    football = next(t for t in plan.timeline if t.activity_id == "football")
    assert football.shifted
    assert football.original_start == 16.0
    assert football.planned_start in (13.0, 14.0)  # 140 ug/m3 plateau
    assert football.pm25_before == 240.0 and football.pm25_after == 140.0
    assert football.dose_cut_pct == pytest.approx(100 * (240 - 140) / 240)


def test_plan_reduces_every_members_dose(household: Household, profile: DayProfile) -> None:
    plan = build_plan(household, profile)
    for m in plan.members:
        assert m.dose_plan_ug < m.dose_baseline_ug
        assert 0 < m.pct_change <= 100


def test_actions_are_sorted_by_score_and_ids_follow_rank(
    household: Household, profile: DayProfile
) -> None:
    plan = build_plan(household, profile)
    scores = [a.score for a in plan.actions]
    assert scores == sorted(scores, reverse=True)
    assert [a.id for a in plan.actions] == [f"a{i}" for i in range(1, len(plan.actions) + 1)]


def test_low_budget_plan_has_no_purchases(household: Household, profile: DayProfile) -> None:
    household.budget = BudgetTier.LOW
    plan = build_plan(household, profile)
    assert all(a.effort_tier <= 3 for a in plan.actions)
    assert not any(a.kind == ActionKind.PURIFIER for a in plan.actions)
    assert any(a.kind == ActionKind.CR_BOX for a in plan.actions)


def test_medium_budget_recommends_a_sized_purifier(
    household: Household, profile: DayProfile
) -> None:
    plan = build_plan(household, profile)
    purifiers = [a for a in plan.actions if a.kind == ActionKind.PURIFIER]
    assert purifiers
    for p in purifiers:
        assert float(p.details["cadr"]) % 50 == 0
        assert float(p.details["indoor_after"]) < float(p.details["indoor_before"])


def test_infants_never_get_mask_advice(household: Household, profile: DayProfile) -> None:
    household.members.append(Member(id="baby", name="Baby", age_band="infant"))  # type: ignore[arg-type]
    household.trips[1].member_ids.append("baby")
    plan = build_plan(household, profile)
    for a in plan.actions:
        if a.kind == ActionKind.MASK:
            assert "baby" not in [m.member_id for m in a.members]


def test_car_trip_gets_recirculation_and_mode_comparison(
    household: Household, profile: DayProfile
) -> None:
    plan = build_plan(household, profile)
    assert any(a.kind == ActionKind.RECIRCULATION for a in plan.actions)
    office = next(c for c in plan.commute if c.trip_id == "office")
    assert sum(o.current for o in office.options) == 1
    metro = next(o for o in office.options if o.mode == "metro")
    auto = next(o for o in office.options if o.current)
    assert metro.co2_kg < auto.co2_kg and metro.dose_ug < auto.dose_ug


def test_mode_switch_reports_co2_avoided(household: Household, profile: DayProfile) -> None:
    plan = build_plan(household, profile)
    switch = next(a for a in plan.actions if a.kind == ActionKind.MODE_SWITCH)
    assert switch.co2_avoided_kg > 0


def test_sources_are_flagged(household: Household, profile: DayProfile) -> None:
    plan = build_plan(household, profile)
    kinds = {s.kind.value: s for s in plan.sources}
    assert kinds["incense"].indoor_increase > 0 and not kinds["incense"].neighbourhood
    assert kinds["waste_burning"].neighbourhood
    assert any(a.kind == ActionKind.STOP_BURNING for a in plan.actions)


def test_facts_cover_every_action_and_are_pre_formatted(
    household: Household, profile: DayProfile
) -> None:
    plan = build_plan(household, profile)
    for a in plan.actions:
        assert f"{a.id}.subject" in plan.facts.values
        assert f"{a.id}.dose_cut_pct" in plan.facts.numeric
    assert plan.facts.values["pm"] == "PM2.5"


@pytest.mark.parametrize("language", list(Language))
def test_fallback_text_is_digit_free_and_fully_fillable(
    language: Language, profile: DayProfile
) -> None:
    plan = build_plan(demo_household(language), profile)
    texts = [fallback_action_text(a, language) for a in plan.actions]
    texts.append(SUMMARY_TEMPLATES[language])
    for text in texts:
        assert not re.search(r"\d", PLACEHOLDER.sub("", text)), text
        for key in PLACEHOLDER.findall(text):
            assert key in plan.facts.values, key


def test_all_templates_exist_in_both_languages() -> None:
    for kind in ActionKind:
        for language in Language:
            assert kind in ACTION_TEMPLATES[language]


def test_render_template_prefix() -> None:
    assert render_template("{{.x}} and {{y}}", "a3") == "{{a3.x}} and {{y}}"


def test_format_time() -> None:
    assert format_time(12.5, Language.EN) == "12:30 pm"
    assert format_time(0, Language.EN) == "12:00 am"
    assert format_time(16, Language.HI) == "शाम 4:00 pm"
    assert format_time(6.75, Language.EN) == "6:45 am"


def test_constant_terms_stay_in_facts(household: Household, profile: DayProfile) -> None:
    plan = build_plan(household, profile)
    for key, text in CONSTANT_TERMS.items():
        assert plan.facts.values[key] == text


def test_household_validation_rejects_unknown_member() -> None:
    data = demo_household().model_dump(mode="json")
    data["activities"][0]["member_ids"] = ["ghost"]
    with pytest.raises(ValueError, match="unknown member ids"):
        Household.model_validate(data)


def test_coordinates_are_rounded_for_privacy() -> None:
    data = demo_household().model_dump(mode="json")
    data["location"].update(lat=28.613939, lon=77.209021)
    loc = Household.model_validate(data).location
    assert (loc.lat, loc.lon) == (28.61, 77.21)
