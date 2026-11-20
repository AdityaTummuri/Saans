"""Google Maps Platform Geocoding API client. Called server-side so no key reaches the browser."""

from __future__ import annotations

from typing import Protocol

import httpx

from app.domain.models import Location
from app.services.cache import TTLCache
from app.services.http import UpstreamError, request_json

URL = "https://maps.googleapis.com/maps/api/geocode/json"
SERVICE = "geocoding"


class Geocoder(Protocol):
    async def geocode(self, address: str) -> Location: ...


class GeocodingClient:
    def __init__(
        self,
        client: httpx.AsyncClient,
        api_key: str,
        cache: TTLCache[Location],
        retries: int = 1,
    ) -> None:
        self._client = client
        self._key = api_key
        self._cache = cache
        self._retries = retries

    async def geocode(self, address: str) -> Location:
        text = " ".join(address.split())
        if not text:
            raise UpstreamError(SERVICE, "empty address")
        return await self._cache.get_or_set((SERVICE, text.lower()), lambda: self._fetch(text))

    async def _fetch(self, text: str) -> Location:
        data = await request_json(
            self._client,
            SERVICE,
            "GET",
            URL,
            retries=self._retries,
            params={"address": text, "key": self._key},
        )
        results = data.get("results")
        if data.get("status") != "OK" or not isinstance(results, list) or not results:
            raise UpstreamError(SERVICE, "address not found")
        top = results[0]
        point = (top.get("geometry") or {}).get("location") or {}
        try:
            return Location(
                lat=float(point["lat"]),
                lon=float(point["lng"]),
                label=str(top.get("formatted_address", ""))[:120],
            )
        except (KeyError, TypeError, ValueError):
            raise UpstreamError(SERVICE, "malformed result") from None
