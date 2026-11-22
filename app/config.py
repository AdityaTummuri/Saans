"""Application settings. Everything tunable lives here; nothing is hard-coded elsewhere."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Credentials (never logged)
    maps_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None

    @field_validator("maps_api_key", "gemini_api_key", "google_cloud_project", mode="before")
    @classmethod
    def _blank_means_unset(cls, value: object) -> object:
        """`KEY=` in a .env file means "not set", not an empty secret."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    # Gemini
    use_vertex: bool = False
    google_cloud_project: str | None = None
    google_cloud_location: str = "global"
    gemini_model: str = "gemini-3.7-flash"
    gemini_lite_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_s: float = 20.0
    gemini_max_output_tokens: int = 1024
    gemini_max_tool_rounds: int = 4

    # Demo mode serves recorded fixtures and needs no keys.
    demo_mode: bool = False
    fixtures_dir: Path = REPO_ROOT / "fixtures" / "demo"

    # Upstream HTTP
    http_timeout_s: float = 8.0
    http_retries: int = 1
    forecast_hours: int = 48

    # Cache
    cache_ttl_s: float = 3600.0
    cache_max_entries: int = 512

    # Limits
    max_request_bytes: int = 64 * 1024
    max_text_chars: int = 2000
    rate_limit_per_minute: int = 10
    rate_limit_burst: int = 5
    # Proxy headers are trusted only on hosts known to set them: Cloud Run (K_SERVICE) appends the
    # real client as the last X-Forwarded-For hop; Vercel (VERCEL) overwrites the header, so the
    # client is the first entry. Anywhere else the socket address is used.
    trust_proxy_headers: bool = Field(
        default_factory=lambda: "K_SERVICE" in os.environ or "VERCEL" in os.environ
    )
    proxy_client_hop: Literal["first", "last"] = Field(
        default_factory=lambda: "first" if "VERCEL" in os.environ else "last"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
