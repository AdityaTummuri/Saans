"""App factory: wiring, error handlers and static files. Security middleware is in security.py."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.ratelimit import TokenBucketLimiter
from app.api.routes import router
from app.config import Settings, get_settings
from app.domain.forecast import ForecastUnavailable
from app.security import install_security
from app.services.container import NotConfiguredError, Services, build_services
from app.services.gemini import LLMBackend, build_backend
from app.services.http import UpstreamError

log = logging.getLogger("saans")
WEB_DIR = Path(__file__).parent / "web"

MESSAGES = {
    "rate_limited": "Too many requests. Please wait a moment and try again.",
    "not_configured": "This server is not configured for live data.",
    "intake_unavailable": "Describing your family in words needs Gemini, which is not configured.",
    "model_unavailable": "The assistant is unavailable right now. Please try again.",
    "address_needed": "Please add the address or neighbourhood where the family lives.",
    "profile_incomplete": "Could not build a profile from that text. Add who is in the family.",
    "upstream_unavailable": "A Google service did not respond. Please try again shortly.",
    "forecast_unavailable": "The air quality forecast is not available for this location.",
    "invalid_request": "The request was not valid.",
    "payload_too_large": "The request is too large.",
    "not_found": "Not found.",
    "internal_error": "Something went wrong.",
}


def error_response(status: int, code: str, headers: dict[str, str] | None = None) -> JSONResponse:
    """A generic error body: a stable code and message, never a stack trace or user data."""
    return JSONResponse(
        {"error": code, "message": MESSAGES.get(code, MESSAGES["internal_error"])},
        status_code=status,
        headers=headers,
    )


def create_app(
    settings: Settings | None = None,
    services: Services | None = None,
    backend: LLMBackend | None = None,
) -> FastAPI:
    """Build the app. Tests pass fakes for `services` and `backend`."""
    settings = settings or get_settings()
    inject = services is not None or backend is not None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.limiter = TokenBucketLimiter(
            settings.rate_limit_per_minute, settings.rate_limit_burst
        )
        if inject:
            app.state.services, app.state.backend = services, backend
        else:
            try:
                app.state.services = build_services(settings)
            except NotConfiguredError:
                log.warning("MAPS_API_KEY is not set; live endpoints are disabled")
                app.state.services = None
            app.state.backend = build_backend(settings)
        yield
        if app.state.services is not None and not inject:
            await app.state.services.aclose()

    app = FastAPI(title="Saans", lifespan=lifespan, docs_url=None, redoc_url=None)
    install_security(app, settings)
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, __: RequestValidationError) -> JSONResponse:
        return error_response(422, "invalid_request")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = exc.detail if isinstance(exc.detail, str) and exc.detail in MESSAGES else None
        if code is None:
            code = "not_found" if exc.status_code == 404 else "invalid_request"
        return error_response(exc.status_code, code, dict(exc.headers or {}))

    @app.exception_handler(UpstreamError)
    async def _upstream(_: Request, exc: UpstreamError) -> JSONResponse:
        log.warning("upstream failure: %s", exc.service)
        return error_response(502, "upstream_unavailable")

    @app.exception_handler(ForecastUnavailable)
    async def _forecast(_: Request, __: ForecastUnavailable) -> JSONResponse:
        return error_response(503, "forecast_unavailable")

    @app.exception_handler(Exception)
    async def _unexpected(_: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error: %s", type(exc).__name__)  # type only: no data, no trace
        return error_response(500, "internal_error")

    if WEB_DIR.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
    return app


app = create_app()
