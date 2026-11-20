from __future__ import annotations

from pathlib import Path

from app.config import REPO_ROOT, Settings
from app.services.gemini import build_backend


def test_blank_values_in_env_example_mean_unset() -> None:
    settings = Settings(_env_file=REPO_ROOT / ".env.example")  # type: ignore[call-arg]
    assert settings.maps_api_key is None and settings.gemini_api_key is None
    assert settings.google_cloud_project is None
    assert settings.demo_mode is True
    assert settings.gemini_model == "gemini-3.7-flash"
    assert settings.gemini_lite_model == "gemini-3.5-flash-lite"
    assert build_backend(settings) is None


def test_env_example_lists_only_variable_names() -> None:
    for line in Path(REPO_ROOT / ".env.example").read_text().splitlines():
        if line and not line.startswith("#"):
            name, _, value = line.partition("=")
            assert (name.isupper() and "KEY" not in name) or value == "", line


def test_secrets_are_not_printed() -> None:
    settings = Settings(maps_api_key="super-secret", _env_file=None)  # type: ignore[arg-type,call-arg]
    assert "super-secret" not in repr(settings) and "super-secret" not in str(settings)
