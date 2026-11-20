"""Google Maps Platform Routes API client (duration and distance per travel mode)."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import httpx

from app.domain.models import Location, TravelMode, TripOption
from app.services.cache import TTLCache
from app.services.http import UpstreamError, request_json

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
SERVICE = "routes"
FIELD_MASK = "routes.duration,routes.distanceMeters"

# Auto-rickshaws share the road network with cars, so they use driving durations.
_ROUTES_MODE: dict[TravelMode, str] = {
    TravelMode.WALK: "WALK",
    TravelMode.CYCLE: "BICYCLE",
    TravelMode.TWO_WHEELER: "TWO_WHEELER",
    TravelMode.AUTO_RICKSHAW: "DRIVE",
    TravelMode.CAR: "DRIVE",
    TravelMode.BUS: "TRANSIT",
    TravelMode.METRO: "TRANSIT",
}
_TRANSIT_KINDS: dict[TravelMode, list[str]] = {
    TravelMode.BUS: ["BUS"],
    TravelMode.METRO: ["SUBWAY", "LIGHT_RAIL", "TRAIN"],
}


class RoutesProvider(Protocol):
    async def options(
        self, origin: Location, destination: Location, modes: list[TravelMode]
    ) -> list[TripOption]: ...


def request_body(origin: Location, destination: Location, mode: TravelMode) -> dict[str, Any]:
    """The computeRoutes body for one travel mode."""

    def waypoint(loc: Location) -> dict[str, Any]:
        return {"location": {"latLng": {"latitude": loc.lat, "longitude": loc.lon}}}

    body: dict[str, Any] = {
        "origin": waypoint(origin),
        "destination": waypoint(destination),
        "travelMode": _ROUTES_MODE[mode],
        "units": "METRIC",
    }
    if mode in (TravelMode.CAR, TravelMode.AUTO_RICKSHAW, TravelMode.TWO_WHEELER):
        body["routingPreference"] = "TRAFFIC_AWARE"
    if mode in _TRANSIT_KINDS:
        body["transitPreferences"] = {"allowedTravelModes": _TRANSIT_KINDS[mode]}
    return body


def parse_option(body: dict[str, Any], mode: TravelMode) -> TripOption:
    """Map a computeRoutes response to a TripOption."""
    routes = body.get("routes")
    if not isinstance(routes, list) or not routes:
        raise UpstreamError(SERVICE, "no route found")
    route = routes[0]
    try:
        seconds = float(str(route["duration"]).rstrip("s"))
        meters = float(route.get("distanceMeters", 0))
    except (KeyError, ValueError):
        raise UpstreamError(SERVICE, "malformed route") from None
    return TripOption(mode=mode, duration_min=max(seconds / 60, 0.1), distance_km=meters / 1000)


class RoutesClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        cache: TTLCache[TripOption],
        retries: int = 1,
    ) -> None:
        self._client = client
        self._key = api_key
        self._cache = cache
        self._retries = retries

    async def options(
        self, origin: Location, destination: Location, modes: list[TravelMode]
    ) -> list[TripOption]:
        """Fetch every requested mode in parallel; modes with no route are skipped."""
        results = await asyncio.gather(
            *(self._one(origin, destination, m) for m in modes), return_exceptions=True
        )
        options = [r for r in results if isinstance(r, TripOption)]
        if not options:
            raise UpstreamError(SERVICE, "no route found for any travel mode")
        return options

    async def _one(self, origin: Location, destination: Location, mode: TravelMode) -> TripOption:
        key = (SERVICE, origin.lat, origin.lon, destination.lat, destination.lon, mode)

        async def fetch() -> TripOption:
            data = await request_json(
                self._client,
                SERVICE,
                "POST",
                URL,
                retries=self._retries,
                headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": FIELD_MASK},
                json=request_body(origin, destination, mode),
            )
            return parse_option(data, mode)

        return await self._cache.get_or_set(key, fetch)
