"""Google Maps Platform Weather API client (hourly forecast)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

import httpx

from app.domain.forecast import WeatherForecast, WeatherHour
from app.services.cache import TTLCache
from app.services.http import UpstreamError, request_json

URL = "https://weather.googleapis.com/v1/forecast/hours:lookup"
SERVICE = "weather"
_KM_PER_UNIT = {
    "KILOMETERS": 1.0,
    "MILES": 1.609344,
    "KILOMETERS_PER_HOUR": 1.0,
    "MILES_PER_HOUR": 1.609344,
}


class WeatherProvider(Protocol):
    async def forecast(self, lat: float, lon: float) -> WeatherForecast: ...


def _measure(node: Any, value_key: str) -> float | None:
    """Read `{value_key: n, unit: ...}` and convert to kilometres or km/h."""
    if not isinstance(node, dict):
        return None
    value = node.get(value_key)
    if not isinstance(value, int | float):
        return None
    return float(value) * _KM_PER_UNIT.get(str(node.get("unit", "")), 1.0)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def parse_forecast(body: dict[str, Any]) -> WeatherForecast:
    """Map a Weather `forecast/hours:lookup` response into domain objects."""
    raw = body.get("forecastHours")
    if not isinstance(raw, list) or not raw:
        raise UpstreamError(SERVICE, "no forecast in response")
    zone = (body.get("timeZone") or {}).get("id") or "UTC"
    hours: list[WeatherHour] = []
    for entry in raw:
        try:
            when = datetime.fromisoformat(
                str(entry["interval"]["startTime"]).replace("Z", "+00:00")
            )
        except (KeyError, TypeError, ValueError):
            continue
        wind = entry.get("wind") or {}
        hours.append(
            WeatherHour(
                time=when,
                wind_kmh=_measure(wind.get("speed"), "value"),
                humidity_pct=_number(entry.get("relativeHumidity")),
                visibility_km=_measure(entry.get("visibility"), "distance"),
                cloud_cover_pct=_number(entry.get("cloudCover")),
                is_daytime=entry.get("isDaytime")
                if isinstance(entry.get("isDaytime"), bool)
                else None,
            )
        )
    if not hours:
        raise UpstreamError(SERVICE, "no usable hours in response")
    return WeatherForecast(timezone=str(zone), hours=hours)


class WeatherClient:
    """Fetches 48 hours of wind, humidity, visibility, cloud cover and day/night."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        cache: TTLCache[WeatherForecast],
        forecast_hours: int = 48,
        retries: int = 1,
    ) -> None:
        self._client = client
        self._key = api_key
        self._cache = cache
        self._hours = forecast_hours
        self._retries = retries

    async def forecast(self, lat: float, lon: float) -> WeatherForecast:
        bucket = datetime.now().replace(minute=0, second=0, microsecond=0)
        key = (SERVICE, round(lat, 2), round(lon, 2), bucket)
        return await self._cache.get_or_set(key, lambda: self._fetch(lat, lon))

    async def _fetch(self, lat: float, lon: float) -> WeatherForecast:
        data = await request_json(
            self._client,
            SERVICE,
            "GET",
            URL,
            retries=self._retries,
            params={
                "key": self._key,
                "location.latitude": round(lat, 2),
                "location.longitude": round(lon, 2),
                "hours": self._hours,
                "pageSize": self._hours,
            },
        )
        return parse_forecast(data)
