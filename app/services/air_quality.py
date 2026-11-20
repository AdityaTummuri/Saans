"""Google Maps Platform Air Quality API client (hourly forecast)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx

from app.domain.forecast import AirForecast, AirHour
from app.services.cache import TTLCache
from app.services.http import UpstreamError, request_json

URL = "https://airquality.googleapis.com/v1/forecast:lookup"
SERVICE = "air_quality"
RECOMMENDATION_KEYS = (
    "generalPopulation",
    "elderly",
    "lungDiseasePopulation",
    "heartDiseasePopulation",
    "athletes",
    "pregnantWomen",
    "children",
)


class AirQualityProvider(Protocol):
    async def forecast(self, lat: float, lon: float, language: str = "en") -> AirForecast: ...


def _local_index(entry: dict[str, Any]) -> tuple[int | None, str | None]:
    """Pick the local (India CPCB) index when present, else the first index."""
    indexes = [i for i in entry.get("indexes", []) if isinstance(i, dict)]
    local = next((i for i in indexes if i.get("code") != "uaqi"), None)
    chosen = local or (indexes[0] if indexes else None)
    if chosen is None:
        return None, None
    aqi = chosen.get("aqi")
    return (int(aqi) if isinstance(aqi, int | float) else None), chosen.get("category")


def _pm25(entry: dict[str, Any]) -> float | None:
    for pollutant in entry.get("pollutants", []):
        if pollutant.get("code") == "pm25":
            value = (pollutant.get("concentration") or {}).get("value")
            return float(value) if isinstance(value, int | float) else None
    return None


def parse_forecast(body: dict[str, Any]) -> AirForecast:
    """Map an Air Quality `forecast:lookup` response into domain objects."""
    raw = body.get("hourlyForecasts")
    if not isinstance(raw, list) or not raw:
        raise UpstreamError(SERVICE, "no forecast in response")
    hours: list[AirHour] = []
    recommendations: dict[str, str] = {}
    for entry in raw:
        try:
            when = datetime.fromisoformat(str(entry["dateTime"]).replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        aqi, category = _local_index(entry)
        hours.append(AirHour(time=when, pm25=_pm25(entry), local_aqi=aqi, local_category=category))
        if not recommendations:
            advice = entry.get("healthRecommendations") or {}
            recommendations = {
                k: advice[k] for k in RECOMMENDATION_KEYS if isinstance(advice.get(k), str)
            }
    if not hours:
        raise UpstreamError(SERVICE, "no usable hours in response")
    return AirForecast(hours=hours, recommendations=recommendations)


class AirQualityClient:
    """Fetches a 48-hour forecast with the local index, health advice and concentrations."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        cache: TTLCache[AirForecast],
        forecast_hours: int = 48,
        retries: int = 1,
    ) -> None:
        self._client = client
        self._key = api_key
        self._cache = cache
        self._hours = forecast_hours
        self._retries = retries

    async def forecast(self, lat: float, lon: float, language: str = "en") -> AirForecast:
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        key = (SERVICE, round(lat, 2), round(lon, 2), language, now)
        return await self._cache.get_or_set(key, lambda: self._fetch(lat, lon, language, now))

    async def _fetch(self, lat: float, lon: float, language: str, start: datetime) -> AirForecast:
        end = start + timedelta(hours=self._hours)
        body = {
            "location": {"latitude": round(lat, 2), "longitude": round(lon, 2)},
            "period": {
                "startTime": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            "pageSize": self._hours,
            "extraComputations": [
                "LOCAL_AQI",
                "HEALTH_RECOMMENDATIONS",
                "POLLUTANT_CONCENTRATION",
                "DOMINANT_POLLUTANT_CONCENTRATION",
            ],
            "languageCode": language,
        }
        data = await request_json(
            self._client,
            SERVICE,
            "POST",
            URL,
            retries=self._retries,
            params={"key": self._key},
            json=body,
        )
        return parse_forecast(data)
