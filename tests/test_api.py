from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.ratelimit import TokenBucketLimiter
from app.config import Settings
from app.demo import demo_household
from app.domain.forecast import AirForecast
from app.main import create_app
from app.services.container import Services, build_services
from app.services.gemini import LLMError
from app.services.http import UpstreamError
from app.services.intake import IntakeDraft
from tests.test_gemini import FakeBackend


def settings(**kw: Any) -> Settings:
    return Settings(demo_mode=True, _env_file=None, **kw)  # type: ignore[call-arg]


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(settings())) as c:
        yield c


def household_json() -> dict[str, Any]:
    return json.loads(demo_household().model_dump_json())


# ----------------------------------------------------------------------- basics


def test_healthz_reports_mode(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok", "mode": "demo", "gemini": False}


def test_demo_household_endpoint(client: TestClient) -> None:
    body = client.get("/api/demo?language=hi").json()
    assert body["language"] == "hi" and len(body["members"]) == 4


def test_plan_in_demo_mode_without_gemini(client: TestClient) -> None:
    res = client.post("/api/plan", json={"household": household_json()})
    assert res.status_code == 200
    body = res.json()
    assert body["demo"] is True and body["narrated_by_model"] is False
    assert body["plan"]["actions"] and "{{" not in body["summary"]
    for action in body["plan"]["actions"]:
        assert "{{" not in body["action_text"][action["id"]]
    football = next(t for t in body["plan"]["timeline"] if t["activity_id"] == "football")
    assert football["shifted"] and football["pm25_before"] == 240
    assert body["recommendations"]["elderly"]
    assert len(body["plan"]["hours"]) == 24


def test_plan_with_model_narration() -> None:
    reply = json.dumps({"summary": "Air peaks around {{peak_time}}.", "actions": []})
    with TestClient(
        create_app(settings(), backend=FakeBackend(reply), services=build_services(settings()))
    ) as c:
        body = c.post("/api/plan", json={"household": household_json()}).json()
    assert body["narrated_by_model"] is True
    assert body["summary"].startswith("Air peaks around ") and "{{" not in body["summary"]


def test_ask_keyless_answers_from_engine(client: TestClient) -> None:
    res = client.post(
        "/api/ask", json={"household": household_json(), "question": "Is incense okay tonight?"}
    )
    body = res.json()
    assert res.status_code == 200 and not body["grounded"]
    assert "µg/m³" in body["answer"] and body["tools_used"] == ["indoor_estimate"]


# ----------------------------------------------------------------------- validation


def test_invalid_input_returns_generic_422_without_echo(client: TestClient) -> None:
    data = household_json()
    data["location"]["lat"] = 123.0
    data["members"][0]["name"] = "SENSITIVE-NAME"
    res = client.post("/api/plan", json={"household": data})
    assert res.status_code == 422
    assert res.json()["error"] == "invalid_request"
    assert "SENSITIVE-NAME" not in res.text and "123" not in res.text


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["location"].update(lon=-181),
        lambda d: d["members"].extend(d["members"] * 3),  # more than 10 members
        lambda d: d["activities"][0].update(duration_h=25),
        lambda d: d["activities"][0].update(duration_h=0),
        lambda d: d.update(unexpected_field=1),
    ],
)
def test_bounds_are_enforced(client: TestClient, mutate: Any) -> None:
    data = household_json()
    mutate(data)
    assert client.post("/api/plan", json={"household": data}).status_code == 422


def test_question_length_is_bounded(client: TestClient) -> None:
    body = {"household": household_json(), "question": "x" * 2001}
    assert client.post("/api/ask", json=body).status_code == 422
    body["question"] = ""
    assert client.post("/api/ask", json=body).status_code == 422


def test_oversized_body_is_rejected() -> None:
    with TestClient(create_app(settings(max_request_bytes=500))) as c:
        res = c.post(
            "/api/plan",
            content=b"{" + b" " * 2000 + b"}",
            headers={"content-type": "application/json"},
        )
    assert res.status_code == 413 and res.json()["error"] == "payload_too_large"
    assert res.headers["x-content-type-options"] == "nosniff"


# ----------------------------------------------------------------------- headers and errors


def test_security_headers_on_every_response(client: TestClient) -> None:
    for path in ("/healthz", "/api/demo", "/", "/missing"):
        h = client.get(path).headers
        assert "default-src 'self'" in h["content-security-policy"]
        assert "https://fonts.googleapis.com" in h["content-security-policy"]
        assert "frame-ancestors 'none'" in h["content-security-policy"]
        assert h["x-content-type-options"] == "nosniff"
        assert h["referrer-policy"] == "no-referrer"
        assert "geolocation=(self)" in h["permissions-policy"]
    assert client.get("/api/demo").headers["cache-control"] == "no-store"


def test_unknown_route_is_a_generic_404(client: TestClient) -> None:
    res = client.get("/api/nope")
    assert res.status_code in (404, 405)
    assert "Traceback" not in res.text


class BrokenAir:
    async def forecast(self, lat: float, lon: float, language: str = "en") -> AirForecast:
        raise UpstreamError("air_quality", "status 500 secret-url")


class CrashingAir:
    async def forecast(self, lat: float, lon: float, language: str = "en") -> AirForecast:
        raise RuntimeError("private health detail")


def _services_with(air: Any) -> Services:
    real = build_services(settings())
    real.air = air
    return real


def test_upstream_failure_is_a_generic_502() -> None:
    with TestClient(create_app(settings(), services=_services_with(BrokenAir()))) as c:
        res = c.post("/api/plan", json={"household": household_json()})
    assert res.status_code == 502 and res.json()["error"] == "upstream_unavailable"
    assert "secret-url" not in res.text


def test_unexpected_error_never_leaks_details() -> None:
    with TestClient(
        create_app(settings(), services=_services_with(CrashingAir())),
        raise_server_exceptions=False,
    ) as c:
        res = c.post("/api/plan", json={"household": household_json()})
    assert res.status_code == 500 and res.json()["error"] == "internal_error"
    assert "private health detail" not in res.text and "Traceback" not in res.text


# ----------------------------------------------------------------------- rate limiting


def test_ask_is_rate_limited_per_ip() -> None:
    cfg = settings(rate_limit_burst=2, rate_limit_per_minute=1)
    with TestClient(create_app(cfg)) as c:
        body = {"household": household_json(), "question": "hello"}
        codes = [c.post("/api/ask", json=body).status_code for _ in range(4)]
        assert codes == [200, 200, 429, 429]
        limited = c.post("/api/ask", json=body)
        assert int(limited.headers["retry-after"]) >= 1
        assert limited.json()["error"] == "rate_limited"
        assert c.get("/healthz").status_code == 200  # other routes are unaffected


def test_proxy_header_is_only_trusted_when_enabled() -> None:
    cfg = settings(rate_limit_burst=1, rate_limit_per_minute=1, trust_proxy_headers=True)
    with TestClient(create_app(cfg)) as c:
        body = {"household": household_json(), "question": "hello"}
        a = c.post("/api/ask", json=body, headers={"x-forwarded-for": "9.9.9.9, 1.1.1.1"})
        b = c.post("/api/ask", json=body, headers={"x-forwarded-for": "9.9.9.9, 2.2.2.2"})
        again = c.post("/api/ask", json=body, headers={"x-forwarded-for": "spoof, 1.1.1.1"})
    assert (a.status_code, b.status_code, again.status_code) == (200, 200, 429)


def test_token_bucket_refills_over_time() -> None:
    now = [0.0]
    limiter = TokenBucketLimiter(per_minute=60, burst=2, clock=lambda: now[0])
    assert limiter.check("a") == 0 and limiter.check("a") == 0
    assert limiter.check("a") > 0
    now[0] = 1.0
    assert limiter.check("a") == 0
    assert limiter.check("b") == 0  # separate bucket


def test_limiter_bounds_memory() -> None:
    limiter = TokenBucketLimiter(per_minute=60, burst=1, max_clients=3)
    for i in range(10):
        limiter.check(f"client{i}")
    assert len(limiter._buckets) <= 3


# ----------------------------------------------------------------------- profile parse


def intake_reply() -> str:
    return IntakeDraft(
        address="Dwarka, Delhi",
        members=[{"name": "Asha", "age_band": "adult"}],  # type: ignore[list-item]
        trips=[
            {
                "name": "Office",
                "members": ["Asha"],
                "mode": "metro",
                "origin": "A",
                "destination": "B",
            }  # type: ignore[list-item]
        ],
    ).model_dump_json()


def test_parse_requires_gemini(client: TestClient) -> None:
    res = client.post("/api/profile/parse", json={"text": "We are a family"})
    assert res.status_code == 503 and res.json()["error"] == "intake_unavailable"


def test_parse_builds_a_confirmable_household() -> None:
    with TestClient(
        create_app(
            settings(), backend=FakeBackend(intake_reply()), services=build_services(settings())
        )
    ) as c:
        res = c.post("/api/profile/parse", json={"text": "Asha takes the metro", "language": "hi"})
    assert res.status_code == 200
    household = res.json()["household"]
    assert household["language"] == "hi"
    assert household["location"]["lat"] == 28.61  # geocoded and rounded
    trip = household["trips"][0]
    assert {o["mode"] for o in trip["options"]} >= {"metro", "car", "walk"}  # from Routes
    # the parsed profile can be planned straight away
    with TestClient(create_app(settings())) as c:
        assert c.post("/api/plan", json={"household": household}).status_code == 200


def test_parse_needs_an_address() -> None:
    reply = IntakeDraft(members=[{"name": "Asha"}]).model_dump_json()  # type: ignore[list-item]
    with TestClient(
        create_app(settings(), backend=FakeBackend(reply), services=build_services(settings()))
    ) as c:
        res = c.post("/api/profile/parse", json={"text": "just me"})
        assert res.status_code == 422 and res.json()["error"] == "address_needed"
        ok = c.post("/api/profile/parse", json={"text": "just me", "address": "Delhi"})
        assert ok.status_code == 200


def test_parse_model_failure_is_a_generic_502() -> None:
    with TestClient(
        create_app(
            settings(), backend=FakeBackend(LLMError("x")), services=build_services(settings())
        )
    ) as c:
        res = c.post("/api/profile/parse", json={"text": "hello"})
    assert res.status_code == 502 and res.json()["error"] == "model_unavailable"


def test_live_mode_without_key_disables_data_endpoints() -> None:
    with TestClient(create_app(Settings(demo_mode=False, _env_file=None))) as c:  # type: ignore[call-arg]
        assert c.get("/healthz").json()["mode"] == "live"
        res = c.post("/api/plan", json={"household": household_json()})
    assert res.status_code == 503 and res.json()["error"] == "not_configured"
