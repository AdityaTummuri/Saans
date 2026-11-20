"""Forecast value objects and the merge of air-quality and weather data into a DayProfile.

Air Quality API timestamps are UTC; they are converted to local clock hours using the time zone
that the Weather API returns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, BaseModel

from app.domain.models import DayProfile, HourlyConditions


class ForecastUnavailable(Exception):
    """Not enough forecast data to cover a day."""


class AirHour(BaseModel):
    time: AwareDatetime
    pm25: float | None
    local_aqi: int | None = None
    local_category: str | None = None


class AirForecast(BaseModel):
    hours: list[AirHour]
    # Health advice from the Air Quality API, keyed by group (for example "elderly").
    recommendations: dict[str, str] = {}


class WeatherHour(BaseModel):
    time: AwareDatetime
    wind_kmh: float | None = None
    humidity_pct: float | None = None
    visibility_km: float | None = None
    cloud_cover_pct: float | None = None
    is_daytime: bool | None = None


class WeatherForecast(BaseModel):
    timezone: str
    hours: list[WeatherHour]


def zone_for(name: str) -> ZoneInfo:
    """Resolve a time-zone id, falling back to UTC when it is unknown."""
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _first_per_local_hour[T](items: list[tuple[datetime, T]], tz: ZoneInfo) -> dict[int, T]:
    """Keep the earliest entry for each local clock hour, in forecast order."""
    out: dict[int, T] = {}
    for when, value in sorted(items, key=lambda item: item[0]):
        out.setdefault(when.astimezone(tz).hour, value)
    return out


def _nearest(values: dict[int, float], hour: int) -> float:
    """Value at the circularly nearest known hour."""
    best = min(values, key=lambda h: (min((h - hour) % 24, (hour - h) % 24), h))
    return values[best]


def build_day_profile(
    air: AirForecast, weather: WeatherForecast, min_hours: int = 12
) -> DayProfile:
    """Merge forecasts into 24 local clock hours (the next occurrence of each hour)."""
    tz = zone_for(weather.timezone)
    pm = _first_per_local_hour([(h.time, h.pm25) for h in air.hours if h.pm25 is not None], tz)
    if len(pm) < min_hours:
        raise ForecastUnavailable("air quality forecast covers too few hours")
    wx = _first_per_local_hour([(h.time, h) for h in weather.hours], tz)

    hours: list[HourlyConditions] = []
    for hour in range(24):
        w = wx.get(hour)
        defaults = HourlyConditions(hour=hour, pm25=0.0)
        hours.append(
            HourlyConditions(
                hour=hour,
                pm25=pm[hour] if hour in pm else _nearest(pm, hour),
                wind_kmh=_pick(w.wind_kmh if w else None, defaults.wind_kmh),
                humidity_pct=_pick(w.humidity_pct if w else None, defaults.humidity_pct),
                visibility_km=_pick(w.visibility_km if w else None, defaults.visibility_km),
                cloud_cover_pct=_pick(w.cloud_cover_pct if w else None, defaults.cloud_cover_pct),
                is_daytime=_daytime(w.is_daytime if w else None, hour),
            )
        )
    return DayProfile(hours=hours)


def _pick(value: float | None, default: float) -> float:
    return default if value is None else value


def _daytime(value: bool | None, hour: int) -> bool:
    """Use the API's day/night flag; without one, assume roughly 6 am to 6 pm."""
    return value if value is not None else 6 <= hour < 18


def utc_now() -> datetime:
    return datetime.now(UTC)
