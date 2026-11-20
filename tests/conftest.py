from __future__ import annotations

import pytest

from app.demo import demo_household, demo_profile
from app.domain.models import DayProfile, HourlyConditions, Household


def make_profile(pm25: list[float] | float = 100.0, daylight: range = range(7, 18)) -> DayProfile:
    """Build a 24-hour profile from one value or a list of 24 values."""
    values = [pm25] * 24 if isinstance(pm25, float | int) else list(pm25)
    return DayProfile(
        hours=[
            HourlyConditions(hour=h, pm25=float(values[h]), is_daytime=h in daylight)
            for h in range(24)
        ]
    )


@pytest.fixture
def household() -> Household:
    return demo_household()


@pytest.fixture
def profile() -> DayProfile:
    return demo_profile()
