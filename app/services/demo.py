"""Demo mode: serve recorded Google API responses from fixtures/demo through a mock transport.

The adapters run unchanged, so demo mode exercises the same request and parsing code as
production. Fixtures are a fixed 48-hour window; the day profile maps them by clock hour.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx


def _load(directory: Path, name: str) -> Any:
    return json.loads((directory / name).read_text(encoding="utf-8"))


def demo_transport(fixtures_dir: Path) -> httpx.MockTransport:
    """An httpx transport that answers the four Maps endpoints from local fixtures."""
    air = _load(fixtures_dir, "air_quality.json")
    weather = _load(fixtures_dir, "weather.json")
    routes = _load(fixtures_dir, "routes.json")
    geocode = _load(fixtures_dir, "geocode.json")

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "airquality.googleapis.com":
            return httpx.Response(200, json=air)
        if host == "weather.googleapis.com":
            return httpx.Response(200, json=weather)
        if host == "maps.googleapis.com" and path.endswith("/geocode/json"):
            return httpx.Response(200, json=geocode)
        if host == "routes.googleapis.com":
            body = json.loads(request.content or b"{}")
            mode = body.get("travelMode", "DRIVE")
            if mode == "TRANSIT":
                kinds = body.get("transitPreferences", {}).get("allowedTravelModes", [])
                mode = "TRANSIT_BUS" if kinds == ["BUS"] else "TRANSIT_METRO"
            return httpx.Response(200, json=routes.get(mode, {"routes": []}))
        return httpx.Response(404, json={"error": "not a demo endpoint"})

    return httpx.MockTransport(handler)
