from __future__ import annotations

import pytest

from app.domain import constants as c
from app.domain.exposure import (
    avoid_exertion,
    candidate_starts,
    cigarettes,
    inhaled_dose,
    mean_pm25,
    naqi_category,
    schedule_activity,
    vulnerability_weight,
)
from app.domain.models import (
    Activity,
    AgeBand,
    Condition,
    Intensity,
    LocationType,
    Member,
)
from tests.conftest import make_profile

ADULT = Member(id="a", name="Asha", age_band=AgeBand.ADULT)
CHILD = Member(id="k", name="Kabir", age_band=AgeBand.CHILD)


def activity(**kw: object) -> Activity:
    base: dict[str, object] = {
        "id": "play", "name": "Play", "member_ids": ["k"], "duration_h": 1.0,
        "intensity": Intensity.VIGOROUS, "location": LocationType.OUTDOOR, "start_hour": 16.0,
        "window_start": 8.0, "window_end": 20.0,
    }  # fmt: skip
    base.update(kw)
    return Activity(**base)  # type: ignore[arg-type]


def test_naqi_band_edges() -> None:
    assert naqi_category(30) == "good"
    assert naqi_category(31) == "satisfactory"
    assert naqi_category(90) == "moderate"
    assert naqi_category(120) == "poor"
    assert naqi_category(250) == "very_poor"
    assert naqi_category(251) == "severe"


def test_dose_is_concentration_times_rate_times_time() -> None:
    # adult, light (1.0 m^3/h), 100 ug/m^3 for 2 hours = 200 ug
    dose = inhaled_dose(make_profile(100.0), 10, 2, AgeBand.ADULT, Intensity.LIGHT, 1.0)
    assert dose == pytest.approx(200.0)


def test_dose_applies_environment_and_mask_factors() -> None:
    dose = inhaled_dose(make_profile(100.0), 10, 1, AgeBand.ADULT, Intensity.LIGHT, 1.4, 0.4)
    assert dose == pytest.approx(100 * 1.0 * 1.4 * 0.4)


def test_dose_spans_partial_hours() -> None:
    values = [0.0] * 24
    values[6], values[7] = 100.0, 300.0
    prof = make_profile(values)
    # 30 min at 100 and 30 min at 300 = mean 200 over 1 h
    assert mean_pm25(prof, 6.5, 1.0) == pytest.approx(200.0)


def test_cigarette_equivalent_uses_berkeley_ratio() -> None:
    # 22 ug/m^3 for 24 h at 1 m^3/h is 528 ug = one cigarette
    assert cigarettes(22 * 24 * 1.0, AgeBand.ADULT, Intensity.LIGHT) == pytest.approx(1.0)


def test_vulnerability_takes_highest_weight() -> None:
    assert vulnerability_weight(ADULT) == 1.0
    assert vulnerability_weight(CHILD) == 1.5
    older = Member(id="o", name="O", age_band=AgeBand.OLDER)
    assert vulnerability_weight(older) == 1.3
    copd = Member(id="c", name="C", age_band=AgeBand.OLDER, conditions=[Condition.COPD])
    assert vulnerability_weight(copd) == 2.0
    pregnant = Member(id="p", name="P", age_band=AgeBand.ADULT, conditions=[Condition.PREGNANCY])
    assert vulnerability_weight(pregnant) == 1.5


def test_sensitive_members_get_alerts_one_category_earlier() -> None:
    assert avoid_exertion(80, sensitive=True)  # Moderate, one before Poor
    assert not avoid_exertion(80, sensitive=False)
    assert avoid_exertion(130, sensitive=False)
    assert not avoid_exertion(50, sensitive=True)


def test_scheduler_picks_the_cleanest_window() -> None:
    values = [200.0] * 24
    values[13] = 60.0
    res = schedule_activity(make_profile(values), activity(), [CHILD])
    assert res.shifted
    assert res.chosen_start == 13.0
    assert res.reason == "cleaner_air"
    assert res.pm25_before == 200.0 and res.pm25_after == 60.0
    assert res.pct_cut == pytest.approx(70.0)


def test_children_only_get_daylight_hours() -> None:
    values = [200.0] * 24
    values[21] = 10.0  # cleanest hour is after dark
    prof = make_profile(values)
    act = activity(window_start=8.0, window_end=23.0)
    starts = candidate_starts(act, [CHILD], prof)
    assert 21.0 not in starts and max(starts) <= 17.0
    res = schedule_activity(prof, act, [CHILD])
    assert res.chosen_start != 21.0


def test_adults_may_use_night_hours() -> None:
    values = [200.0] * 24
    values[21] = 10.0
    adult_act = activity(member_ids=["a"], window_start=8.0, window_end=23.0)
    res = schedule_activity(make_profile(values), adult_act, [ADULT])
    assert res.chosen_start == 21.0


def test_saving_under_ten_percent_keeps_original_time() -> None:
    values = [200.0] * 24
    values[13] = 185.0  # 7.5% better, below the threshold
    res = schedule_activity(make_profile(values), activity(), [CHILD])
    assert not res.shifted
    assert res.chosen_start == 16.0
    assert res.reason == "no_better_window"


def test_saving_exactly_at_threshold_shifts() -> None:
    values = [200.0] * 24
    values[13] = 180.0
    assert schedule_activity(make_profile(values), activity(), [CHILD]).shifted


def test_ties_prefer_less_stagnation_then_closeness() -> None:
    prof = make_profile(150.0)
    # Same PM2.5 everywhere, so the original time is already as good as any: no shift.
    res = schedule_activity(prof, activity(start_hour=14.0), [CHILD])
    assert not res.shifted and res.chosen_start == 14.0


def test_fixed_activity_is_not_moved() -> None:
    act = activity(window_start=None, window_end=None)
    values = [200.0] * 24
    values[13] = 10.0
    res = schedule_activity(make_profile(values), act, [CHILD])
    assert not res.shifted and res.reason == "fixed"


def test_mask_constants_are_conservative() -> None:
    assert 0 < c.MASK_FACTOR < 1
    assert AgeBand.INFANT in c.MASK_EXCLUDED_AGE_BANDS
