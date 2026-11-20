"""Request and response models with strict bounds."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models import Household, Language, Plan

MAX_TEXT = 2000


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParseRequest(_Request):
    text: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]
    address: Annotated[str, Field(max_length=200)] | None = None
    language: Language = Language.EN


class ParseResponse(BaseModel):
    household: Household


class PlanRequest(_Request):
    household: Household


class AskRequest(_Request):
    household: Household
    question: Annotated[str, Field(min_length=1, max_length=MAX_TEXT)]


class PlanResponse(BaseModel):
    plan: Plan
    summary: str
    action_text: dict[str, str]
    narrated_by_model: bool
    recommendations: dict[str, str]
    demo: bool
    location: str


class AskResponse(BaseModel):
    answer: str
    grounded: bool
    tools_used: list[str]


class Health(BaseModel):
    status: str
    mode: str
    gemini: bool


class ErrorBody(BaseModel):
    error: str
    message: str
