"""Emission footprints for trips and household sources."""

from __future__ import annotations

from app.domain import constants as c
from app.domain.models import HomeSource, TravelMode


def trip_co2_kg(mode: TravelMode, distance_km: float, travellers: int = 1) -> float:
    """kg of CO2 for a trip, using per-passenger-km factors."""
    return c.CO2_KG_PER_PASSENGER_KM[mode] * distance_km * travellers


def trip_pm25_g(mode: TravelMode, distance_km: float, travellers: int = 1) -> float:
    """g of tailpipe PM2.5 for a trip; zero where no representative factor exists."""
    return c.PM25_G_PER_PASSENGER_KM.get(mode, 0.0) * distance_km * travellers


def source_daily_co2_kg(kind: HomeSource, hours_per_day: float) -> float:
    return c.SOURCE_CO2_KG_PER_H.get(kind, 0.0) * hours_per_day


def source_daily_pm25_g(kind: HomeSource, hours_per_day: float) -> float:
    return c.SOURCE_PM25_G_PER_H.get(kind, 0.0) * hours_per_day
