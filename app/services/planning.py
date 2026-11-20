"""Glue between the forecast adapters, the domain planner and the narrator."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.domain.forecast import build_day_profile
from app.domain.models import DayProfile, Household, Plan
from app.domain.planner import build_plan
from app.services.container import Services


@dataclass
class PlanBundle:
    profile: DayProfile
    plan: Plan
    recommendations: dict[str, str]


async def compute_plan(services: Services, household: Household) -> PlanBundle:
    """Fetch the forecast (cached), merge it into a day profile and build the plan."""
    loc = household.location
    air, weather = await asyncio.gather(
        services.air.forecast(loc.lat, loc.lon, household.language.value),
        services.weather.forecast(loc.lat, loc.lon),
    )
    profile = build_day_profile(air, weather)
    return PlanBundle(profile, build_plan(household, profile), air.recommendations)
