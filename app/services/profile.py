"""Build a Household from the family's own words: Gemini intake, geocoding and Routes."""

from __future__ import annotations

import asyncio

from app.config import Settings
from app.domain.models import Household, Location, TravelMode, TripOption
from app.services.container import Services
from app.services.gemini import LLMBackend, parse_household
from app.services.http import UpstreamError
from app.services.intake import IntakeDraft, to_household

ALL_MODES = list(TravelMode)


async def _trip_options(services: Services, draft: IntakeDraft) -> dict[int, list[TripOption]]:
    """Routes API options for every trip that names an origin and a destination."""

    async def one(index: int) -> tuple[int, list[TripOption]]:
        trip = draft.trips[index]
        if not (trip.origin.strip() and trip.destination.strip()):
            return index, []
        try:
            origin, dest = await asyncio.gather(
                services.geocoder.geocode(trip.origin), services.geocoder.geocode(trip.destination)
            )
            return index, await services.routes.options(origin, dest, ALL_MODES)
        except UpstreamError:
            return index, []  # keep the profile usable; to_household adds a default option

    pairs = await asyncio.gather(*(one(i) for i in range(min(len(draft.trips), 10))))
    return dict(pairs)


async def build_household(
    services: Services,
    backend: LLMBackend,
    settings: Settings,
    text: str,
    address: str | None,
) -> Household:
    """Parse text into a validated household for the user to confirm."""
    draft = await parse_household(backend, settings, text)
    place = (address or draft.address).strip()
    if not place:
        raise ValueError("address needed")
    location: Location = await services.geocoder.geocode(place)
    options = await _trip_options(services, draft)
    return to_household(draft, location, options)
