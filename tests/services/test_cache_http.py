from __future__ import annotations

import httpx
import pytest
import respx

from app.services.cache import TTLCache
from app.services.http import UpstreamError, build_client, request_json


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_cache_expires_entries_after_ttl() -> None:
    clock = Clock()
    cache: TTLCache[int] = TTLCache(ttl_s=60, clock=clock)
    cache.set("k", 1)
    clock.now = 59
    assert cache.get("k") == 1
    clock.now = 60
    assert cache.get("k") is None
    assert len(cache) == 0


def test_cache_evicts_least_recently_used() -> None:
    cache: TTLCache[int] = TTLCache(ttl_s=60, max_entries=2)
    cache.set("a", 1)
    cache.set("b", 2)
    cache.get("a")
    cache.set("c", 3)
    assert cache.get("b") is None and cache.get("a") == 1 and cache.get("c") == 3


async def test_get_or_set_calls_factory_once() -> None:
    cache: TTLCache[int] = TTLCache(ttl_s=60)
    calls = 0

    async def factory() -> int:
        nonlocal calls
        calls += 1
        return 7

    assert await cache.get_or_set("k", factory) == 7
    assert await cache.get_or_set("k", factory) == 7
    assert calls == 1


@respx.mock
async def test_request_json_retries_once_on_server_error() -> None:
    route = respx.get("https://x.test/a").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    async with build_client() as client:
        data = await request_json(client, "svc", "GET", "https://x.test/a", backoff_s=0)
    assert data == {"ok": True} and route.call_count == 2


@respx.mock
async def test_request_json_gives_up_after_one_retry() -> None:
    route = respx.get("https://x.test/a").mock(return_value=httpx.Response(500))
    async with build_client() as client:
        with pytest.raises(UpstreamError, match="status 500"):
            await request_json(client, "svc", "GET", "https://x.test/a", backoff_s=0)
    assert route.call_count == 2


@respx.mock
async def test_request_json_does_not_retry_client_errors() -> None:
    route = respx.get("https://x.test/a").mock(return_value=httpx.Response(403))
    async with build_client() as client:
        with pytest.raises(UpstreamError, match="status 403"):
            await request_json(client, "svc", "GET", "https://x.test/a", backoff_s=0)
    assert route.call_count == 1


@respx.mock
async def test_timeout_is_reported_without_url_or_key() -> None:
    respx.get("https://x.test/a").mock(side_effect=httpx.ReadTimeout("slow"))
    async with build_client() as client:
        with pytest.raises(UpstreamError) as err:
            await request_json(
                client, "svc", "GET", "https://x.test/a", params={"key": "SECRET"}, backoff_s=0
            )
    assert str(err.value) == "svc: timed out"
    assert "SECRET" not in str(err.value) and "x.test" not in str(err.value)


@respx.mock
async def test_connection_error_and_bad_json() -> None:
    respx.get("https://x.test/c").mock(side_effect=httpx.ConnectError("no"))
    respx.get("https://x.test/j").mock(return_value=httpx.Response(200, text="not json"))
    respx.get("https://x.test/l").mock(return_value=httpx.Response(200, json=[1]))
    async with build_client() as client:
        with pytest.raises(UpstreamError, match="connection error"):
            await request_json(client, "svc", "GET", "https://x.test/c", backoff_s=0)
        with pytest.raises(UpstreamError, match="invalid JSON"):
            await request_json(client, "svc", "GET", "https://x.test/j")
        with pytest.raises(UpstreamError, match="unexpected response shape"):
            await request_json(client, "svc", "GET", "https://x.test/l")
