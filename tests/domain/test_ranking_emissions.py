from __future__ import annotations

import pytest

from app.domain.emissions import source_daily_co2_kg, trip_co2_kg, trip_pm25_g
from app.domain.models import ActionKind, BudgetTier, HomeSource, MemberDelta, TravelMode
from app.domain.ranking import build_entry, impact_score, rank_actions

WEIGHTS = {"a": 1.0, "b": 2.0}


def entry(entry_id: str, tier: int, before: float, after: float, co2: float = 0.0, who: str = "a"):
    return build_entry(
        entry_id=entry_id,
        kind=ActionKind.SHIFT_ACTIVITY,
        subject=entry_id,
        effort_tier=tier,
        deltas=[MemberDelta(member_id=who, dose_before_ug=before, dose_after_ug=after)],
        weights=WEIGHTS,
        co2_avoided_kg=co2,
    )


def test_build_entry_aggregates() -> None:
    e = build_entry(
        entry_id="x",
        kind=ActionKind.MASK,
        subject="x",
        effort_tier=2,
        deltas=[
            MemberDelta(member_id="a", dose_before_ug=100, dose_after_ug=40),
            MemberDelta(member_id="b", dose_before_ug=50, dose_after_ug=20),
        ],
        weights=WEIGHTS,
    )
    assert e.avoided_ug == 90
    assert e.weighted_avoided_ug == 60 + 2 * 30
    assert e.pct_change == pytest.approx(60.0)
    assert e.score == pytest.approx(120 / 2)


def test_score_divides_by_effort_tier() -> None:
    assert impact_score(100, 4) == 25


def test_cheap_action_outranks_expensive_one_with_same_saving() -> None:
    ranked = rank_actions([entry("buy", 4, 100, 0), entry("free", 1, 100, 0)], BudgetTier.HIGH)
    assert [e.id for e in ranked] == ["free", "buy"]


def test_vulnerable_member_counts_double() -> None:
    ranked = rank_actions(
        [entry("adult", 1, 100, 50, who="a"), entry("copd", 1, 100, 50, who="b")], BudgetTier.HIGH
    )
    assert ranked[0].id == "copd"


def test_low_budget_filters_purchases() -> None:
    items = [entry("purchase", 4, 100, 0), entry("diy", 3, 100, 90), entry("shift", 1, 100, 90)]
    low = rank_actions(items, BudgetTier.LOW)
    assert {e.id for e in low} == {"diy", "shift"}
    assert "purchase" in {e.id for e in rank_actions(items, BudgetTier.MEDIUM)}


def test_co2_breaks_score_ties() -> None:
    ranked = rank_actions(
        [entry("a", 1, 100, 50, co2=0.1), entry("b", 1, 100, 50, co2=2.0)], BudgetTier.HIGH
    )
    assert ranked[0].id == "b"


def test_trip_emissions_scale_with_distance_and_travellers() -> None:
    assert trip_co2_kg(TravelMode.CAR, 10, 1) == pytest.approx(1.7)
    assert trip_co2_kg(TravelMode.CAR, 10, 2) == pytest.approx(3.4)
    assert trip_co2_kg(TravelMode.WALK, 10) == 0.0
    assert trip_pm25_g(TravelMode.METRO, 10) == 0.0  # no representative factor


def test_burning_sources_have_daily_footprint() -> None:
    assert source_daily_co2_kg(HomeSource.WASTE_BURNING, 0.5) == pytest.approx(2.25)
    assert source_daily_co2_kg(HomeSource.INCENSE, 1) == 0.0
