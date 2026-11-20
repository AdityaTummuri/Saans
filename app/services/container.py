"""Wires settings to the Google adapters. Tests build their own fakes instead."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.config import Settings
from app.domain.forecast import AirForecast, WeatherForecast
from app.domain.models import Location, TripOption
from app.services.air_quality import AirQualityClient, AirQualityProvider
from app.services.cache import TTLCache
from app.services.demo import demo_transport
from app.services.geocoding import Geocoder, GeocodingClient
from app.services.http import build_client
from app.services.routes import RoutesClient, RoutesProvider
from app.services.weather import WeatherClient, WeatherProvider


class NotConfiguredError(RuntimeError):
    """Live mode was requested without a Maps API key."""


@dataclass
class Services:
    air: AirQualityProvider
    weather: WeatherProvider
    routes: RoutesProvider
    geocoder: Geocoder
    client: httpx.AsyncClient | None = None
    demo: bool = False

    async def aclose(self) -> None:
        if self.client is not None:
            await self.client.aclose()


def build_services(settings: Settings) -> Services:
    """Create the shared HTTP client and the four Maps adapters."""
    if settings.demo_mode:
        client = build_client(settings.http_timeout_s, demo_transport(settings.fixtures_dir))
        key = "demo"
    else:
        if settings.maps_api_key is None:
            raise NotConfiguredError("MAPS_API_KEY is not set")
        client = build_client(settings.http_timeout_s)
        key = settings.maps_api_key.get_secret_value()

    ttl, size, retries = settings.cache_ttl_s, settings.cache_max_entries, settings.http_retries
    return Services(
        air=AirQualityClient(
            client, key, TTLCache[AirForecast](ttl, size), settings.forecast_hours, retries
        ),
        weather=WeatherClient(
            client, key, TTLCache[WeatherForecast](ttl, size), settings.forecast_hours, retries
        ),
        routes=RoutesClient(client, key, TTLCache[TripOption](ttl, size), retries),
        geocoder=GeocodingClient(client, key, TTLCache[Location](ttl, size), retries),
        client=client,
        demo=settings.demo_mode,
    )
