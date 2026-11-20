"""Placeholder grounding: the guard that keeps invented numbers away from users.

The model writes text with placeholders such as {{a2.dose_cut_pct}} and never writes digits.
The server checks the text, then fills the placeholders from engine facts. Text that contains a
raw digit (Python's \\d also matches Devanagari and other Unicode digits), an unknown placeholder
or stray braces is rejected, and deterministic template text is used instead.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

PLACEHOLDER = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")
_DIGIT = re.compile(r"\d")
MAX_TEXT_CHARS = 1200


class GroundingError(ValueError):
    """The text cannot be shown. `reason` is a short machine-readable code."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class GroundedText:
    text: str
    grounded: bool  # False when the deterministic fallback was used
    reason: str | None = None  # why the model text was rejected, if it was


def check(text: str, values: Mapping[str, str]) -> None:
    """Raise GroundingError unless `text` is safe to fill."""
    if not text.strip():
        raise GroundingError("empty")
    if len(text) > MAX_TEXT_CHARS:
        raise GroundingError("too_long")
    names = PLACEHOLDER.findall(text)
    unknown = [n for n in names if n not in values]
    if unknown:
        raise GroundingError("unknown_placeholder")
    remainder = PLACEHOLDER.sub("", text)
    if "{" in remainder or "}" in remainder:
        raise GroundingError("malformed_placeholder")
    if _DIGIT.search(remainder):
        raise GroundingError("raw_digit")


def fill(text: str, values: Mapping[str, str]) -> str:
    """Validate and fill placeholders in a single pass (filled values are never re-scanned)."""
    check(text, values)
    return PLACEHOLDER.sub(lambda m: values[m.group(1)], text)


def ground(text: str | None, values: Mapping[str, str], fallback: str) -> GroundedText:
    """Fill model text if it passes the guard; otherwise fill the deterministic fallback.

    The fallback is built from the same placeholder syntax, so it passes through the same code.
    """
    if text is not None:
        try:
            return GroundedText(fill(text, values), grounded=True)
        except GroundingError as err:
            reason = err.reason
    else:
        reason = "no_model_text"
    return GroundedText(fill(fallback, values), grounded=False, reason=reason)
