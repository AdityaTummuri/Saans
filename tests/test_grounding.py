from __future__ import annotations

import pytest

from app.services.grounding import GroundingError, check, fill, ground

VALUES = {"a1.dose_cut_pct": "42", "a1.subject": "Football 2", "pm": "PM2.5"}


def test_fills_known_placeholders() -> None:
    text = "Dose falls {{a1.dose_cut_pct}}% for {{pm}}."
    assert fill(text, VALUES) == "Dose falls 42% for PM2.5."


def test_whitespace_inside_braces_is_allowed() -> None:
    assert fill("{{ a1.dose_cut_pct }}%", VALUES) == "42%"


@pytest.mark.parametrize(
    "text",
    [
        "Dose falls 42% this afternoon",  # invented number
        "Dose falls {{a1.dose_cut_pct}}% by 3 pm",  # digit next to a valid placeholder
        "बारह के बजाय १२ बजे",  # Devanagari digits
        "Value is ٤٢",  # Arabic-Indic digits
        "Fullwidth \uff14\uff12",  # fullwidth digits
    ],
)
def test_raw_digits_are_rejected(text: str) -> None:
    with pytest.raises(GroundingError) as err:
        check(text, VALUES)
    assert err.value.reason == "raw_digit"


def test_unknown_placeholder_is_rejected() -> None:
    with pytest.raises(GroundingError) as err:
        check("Saves {{a9.dose_cut_pct}}", VALUES)
    assert err.value.reason == "unknown_placeholder"


@pytest.mark.parametrize("text", ["Broken {{a1.dose_cut_pct", "Extra } brace", "{ {x} }"])
def test_malformed_braces_are_rejected(text: str) -> None:
    with pytest.raises(GroundingError):
        check(text, VALUES)


def test_empty_and_overlong_text_is_rejected() -> None:
    with pytest.raises(GroundingError, match="empty"):
        check("   ", VALUES)
    with pytest.raises(GroundingError, match="too_long"):
        check("x" * 2000, VALUES)


def test_filled_values_are_not_rescanned_for_injection() -> None:
    values = {"a1.subject": "{{a1.evil}}", "a1.evil": "pwned"}
    assert fill("Move {{a1.subject}}", values) == "Move {{a1.evil}}"


def test_ground_uses_model_text_when_valid() -> None:
    res = ground("Cuts {{a1.dose_cut_pct}}%.", VALUES, "fallback {{a1.dose_cut_pct}}")
    assert res.grounded and res.text == "Cuts 42%." and res.reason is None


def test_ground_falls_back_on_invented_number() -> None:
    res = ground("Cuts 77%.", VALUES, "Fallback {{a1.dose_cut_pct}}%.")
    assert not res.grounded and res.text == "Fallback 42%." and res.reason == "raw_digit"


def test_ground_falls_back_when_there_is_no_model_text() -> None:
    res = ground(None, VALUES, "Fallback {{pm}}.")
    assert not res.grounded and res.text == "Fallback PM2.5." and res.reason == "no_model_text"
