"""Shared httpx client, timeouts and a single retry. Keys are never logged or put in errors."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class UpstreamError(Exception):
    """A Google API call failed. The message never contains URLs, keys or payloads."""

    def __init__(self, service: str, reason: str) -> None:
        super().__init__(f"{service}: {reason}")
        self.service = service
        self.reason = reason


def build_client(
    timeout_s: float = 8.0, transport: httpx.AsyncBaseTransport | None = None
) -> httpx.AsyncClient:
    """One shared client for every Google adapter."""
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s),
        transport=transport,
        headers={"Accept": "application/json"},
    )


async def request_json(
    client: httpx.AsyncClient,
    service: str,
    method: str,
    url: str,
    *,
    retries: int = 1,
    backoff_s: float = 0.2,
    **kwargs: Any,
) -> dict[str, Any]:
    """Send a request, retrying once on timeouts, connection errors and 429/5xx responses."""
    last_reason = "request failed"
    for attempt in range(retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TimeoutException:
            last_reason = "timed out"
        except httpx.TransportError:
            last_reason = "connection error"
        else:
            if response.status_code in RETRY_STATUSES:
                last_reason = f"status {response.status_code}"
            elif response.status_code >= 400:
                raise UpstreamError(service, f"status {response.status_code}")
            else:
                try:
                    body = response.json()
                except ValueError:
                    raise UpstreamError(service, "invalid JSON") from None
                if not isinstance(body, dict):
                    raise UpstreamError(service, "unexpected response shape")
                return body
        if attempt < retries:
            await asyncio.sleep(backoff_s)
    raise UpstreamError(service, last_reason)
