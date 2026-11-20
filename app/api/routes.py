"""HTTP routes: /api/profile/parse, /api/plan, /api/ask, /api/demo, /healthz."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.ratelimit import TokenBucketLimiter, enforce
from app.api.schemas import (
    AskRequest,
    AskResponse,
    Health,
    ParseRequest,
    ParseResponse,
    PlanRequest,
    PlanResponse,
)
from app.config import Settings
from app.demo import demo_household
from app.domain.models import Household, Language
from app.services.container import Services
from app.services.gemini import LLMBackend, LLMError, ask, narrate_plan
from app.services.planning import compute_plan
from app.services.profile import build_household
from app.services.tools import ToolContext

router = APIRouter()


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_services(request: Request) -> Services:
    services: Services | None = request.app.state.services
    if services is None:
        raise HTTPException(status_code=503, detail="not_configured")
    return services


def get_backend(request: Request) -> LLMBackend | None:
    backend: LLMBackend | None = request.app.state.backend
    return backend


def limited(request: Request) -> None:
    limiter: TokenBucketLimiter = request.app.state.limiter
    settings: Settings = request.app.state.settings
    enforce(limiter, request, settings.trust_proxy_headers)


SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ServicesDep = Annotated[Services, Depends(get_services)]
BackendDep = Annotated[LLMBackend | None, Depends(get_backend)]


@router.get("/healthz", response_model=Health)
async def healthz(request: Request, settings: SettingsDep) -> Health:
    return Health(
        status="ok",
        mode="demo" if settings.demo_mode else "live",
        gemini=request.app.state.backend is not None,
    )


@router.get("/api/demo", response_model=Household)
async def demo(language: Language = Language.EN) -> Household:
    """The one-click demo household (a Delhi family of four)."""
    return demo_household(language)


@router.post("/api/profile/parse", response_model=ParseResponse, dependencies=[Depends(limited)])
async def parse_profile(
    body: ParseRequest, services: ServicesDep, backend: BackendDep, settings: SettingsDep
) -> ParseResponse:
    if backend is None:
        raise HTTPException(status_code=503, detail="intake_unavailable")
    try:
        household = await build_household(services, backend, settings, body.text, body.address)
    except LLMError:
        raise HTTPException(status_code=502, detail="model_unavailable") from None
    except ValueError as err:
        message = "address_needed" if str(err) == "address needed" else "profile_incomplete"
        raise HTTPException(status_code=422, detail=message) from None
    household.language = body.language
    return ParseResponse(household=household)


@router.post("/api/plan", response_model=PlanResponse)
async def make_plan(
    body: PlanRequest, services: ServicesDep, backend: BackendDep, settings: SettingsDep
) -> PlanResponse:
    household = body.household
    bundle = await compute_plan(services, household)
    narration = await narrate_plan(
        backend, settings, bundle.plan, household.language, bundle.recommendations
    )
    return PlanResponse(
        plan=bundle.plan,
        summary=narration.summary.text,
        action_text={k: v.text for k, v in narration.actions.items()},
        narrated_by_model=narration.used_model,
        recommendations=bundle.recommendations,
        demo=services.demo,
        location=household.location.label,
    )


@router.post("/api/ask", response_model=AskResponse, dependencies=[Depends(limited)])
async def ask_saans(
    body: AskRequest, services: ServicesDep, backend: BackendDep, settings: SettingsDep
) -> AskResponse:
    bundle = await compute_plan(services, body.household)
    ctx = ToolContext(body.household, bundle.profile, bundle.plan)
    answer = await ask(backend, settings, body.household, ctx, body.question)
    return AskResponse(answer=answer.text, grounded=answer.grounded, tools_used=answer.tools_used)
