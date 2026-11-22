"""Serverless hosting: lifespan-less start-up, the Vercel entrypoint and client IPs on Vercel."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from api.index import app as vercel_app
from app.api.ratelimit import client_ip
from app.config import Settings
from app.demo import demo_household
from app.main import app as main_app
from app.main import create_app
from app.security import SECURITY_HEADERS


def settings(**kw: Any) -> Settings:
    return Settings(demo_mode=True, _env_file=None, **kw)  # type: ignore[call-arg]


def household_json() -> dict[str, Any]:
    return json.loads(demo_household().model_dump_json())


def request_with(headers: dict[str, str], host: str = "10.0.0.1") -> Request:
    scope = {
        "type": "http",
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
        "client": (host, 1234),
    }
    return Request(scope)


# ----------------------------------------------------------------------- entrypoint


def test_vercel_entrypoint_exports_the_app() -> None:
    assert vercel_app is main_app


async def test_entrypoint_serves_without_lifespan() -> None:
    transport = httpx.ASGITransport(app=vercel_app)  # does not run the ASGI lifespan
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        health = await c.get("/healthz")
    assert health.status_code == 200 and health.json()["status"] == "ok"
    assert vercel_app.state.ready is True


async def test_demo_plan_without_lifespan() -> None:
    app = create_app(settings())
    assert not hasattr(app.state, "limiter")  # nothing set up until a request arrives
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        index = await c.get("/")
        plan = await c.post("/api/plan", json={"household": household_json()})
    assert index.status_code == 200 and "text/html" in index.headers["content-type"]
    assert (
        plan.status_code == 200 and plan.json()["demo"] is True and plan.json()["plan"]["actions"]
    )
    for name in SECURITY_HEADERS:
        assert name in plan.headers and name in index.headers


async def test_lazy_state_is_set_once_and_lifespan_keeps_it() -> None:
    app = create_app(settings())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        await c.get("/healthz")
        first = app.state.limiter
        await c.get("/healthz")
        assert app.state.limiter is first
    with TestClient(app) as tc:  # the lifespan finds the state ready and leaves it alone
        assert app.state.limiter is first
        assert tc.get("/healthz").status_code == 200
    assert app.state.ready is False  # shutdown resets it so a restart initialises again


# ----------------------------------------------------------------------- client address


def test_proxy_defaults_per_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("K_SERVICE", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    local = Settings(_env_file=None)  # type: ignore[call-arg]
    assert local.trust_proxy_headers is False and local.proxy_client_hop == "last"
    monkeypatch.setenv("K_SERVICE", "saans")
    run = Settings(_env_file=None)  # type: ignore[call-arg]
    assert run.trust_proxy_headers is True and run.proxy_client_hop == "last"
    monkeypatch.delenv("K_SERVICE")
    monkeypatch.setenv("VERCEL", "1")
    vercel = Settings(_env_file=None)  # type: ignore[call-arg]
    assert vercel.trust_proxy_headers is True and vercel.proxy_client_hop == "first"


def test_client_ip_picks_the_right_hop() -> None:
    req = request_with({"x-forwarded-for": "1.1.1.1, 2.2.2.2"})
    assert client_ip(req, True, "last") == "2.2.2.2"
    assert client_ip(req, True, "first") == "1.1.1.1"
    assert client_ip(req, False, "first") == "10.0.0.1"  # headers ignored unless trusted


def test_client_ip_falls_back_to_real_ip_then_socket() -> None:
    only_real = request_with({"x-real-ip": "3.3.3.3"})
    assert client_ip(only_real, True, "first") == "3.3.3.3"
    assert client_ip(only_real, True, "last") == "10.0.0.1"  # Cloud Run path never reads it
    assert client_ip(request_with({}), True, "first") == "10.0.0.1"


def test_rate_limit_keys_on_first_hop_for_vercel() -> None:
    cfg = settings(
        rate_limit_burst=1,
        rate_limit_per_minute=1,
        trust_proxy_headers=True,
        proxy_client_hop="first",
    )
    with TestClient(create_app(cfg)) as c:
        body = {"household": household_json(), "question": "hello"}
        a = c.post("/api/ask", json=body, headers={"x-forwarded-for": "1.1.1.1, 9.9.9.9"})
        same = c.post("/api/ask", json=body, headers={"x-forwarded-for": "1.1.1.1, 8.8.8.8"})
        other = c.post("/api/ask", json=body, headers={"x-forwarded-for": "2.2.2.2"})
        real = c.post("/api/ask", json=body, headers={"x-real-ip": "4.4.4.4"})
    assert [r.status_code for r in (a, same, other, real)] == [200, 429, 200, 200]


def test_proxy_headers_cannot_be_spoofed_when_untrusted() -> None:
    cfg = settings(rate_limit_burst=1, rate_limit_per_minute=1, trust_proxy_headers=False)
    with TestClient(create_app(cfg)) as c:
        body = {"household": household_json(), "question": "hello"}
        a = c.post("/api/ask", json=body, headers={"x-forwarded-for": "1.1.1.1"})
        b = c.post("/api/ask", json=body, headers={"x-forwarded-for": "2.2.2.2", "x-real-ip": "3"})
    assert (a.status_code, b.status_code) == (200, 429)
