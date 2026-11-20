from __future__ import annotations

import pytest

from app.domain.models import HourlyConditions
from app.domain.stagnation import hour_overlaps, stagnation_index
from tests.conftest import make_profile


def cond(**kw: float | bool) -> HourlyConditions:
    base: dict[str, float | bool | int] = {
        "hour": 0, "pm25": 100, "wind_kmh": 0, "humidity_pct": 100, "visibility_km": 0,
        "cloud_cover_pct": 0, "is_daytime": False,
    }  # fmt: skip
    base.update(kw)
    return HourlyConditions(**base)  # type: ignore[arg-type]


def test_worst_case_is_100() -> None:
    assert stagnation_index(cond()) == pytest.approx(100.0)


def test_clear_windy_day_is_only_the_daytime_inversion_term() -> None:
    day = cond(wind_kmh=30, humidity_pct=40, visibility_km=20, is_daytime=True)
    assert stagnation_index(day) == pytest.approx(100 * 0.25 * 0.3)


def test_cloud_cover_weakens_night_inversion() -> None:
    clear = stagnation_index(cond(cloud_cover_pct=0))
    cloudy = stagnation_index(cond(cloud_cover_pct=100))
    assert clear - cloudy == pytest.approx(25.0)


def test_mid_values_hand_computed() -> None:
    # W = 1 - 7.5/15 = 0.5, H = (75-50)/50 = 0.5, V = 1 - 5/10 = 0.5, N = 0.3 by day
    c = cond(wind_kmh=7.5, humidity_pct=75, visibility_km=5, is_daytime=True)
    assert stagnation_index(c) == pytest.approx(
        100 * (0.4 * 0.5 + 0.2 * 0.5 + 0.15 * 0.5 + 0.25 * 0.3)
    )


def test_hour_overlaps_split_across_hours_and_wrap() -> None:
    assert hour_overlaps(6.5, 1.0) == [(6, pytest.approx(0.5)), (7, pytest.approx(0.5))]
    assert [h for h, _ in hour_overlaps(23.5, 1.0)] == [23, 0]


def test_profile_must_be_24_ordered_hours() -> None:
    assert len(make_profile().hours) == 24
