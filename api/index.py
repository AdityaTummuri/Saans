"""Vercel entrypoint: re-exports the ASGI app. vercel.json rewrites every path to it."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app

__all__ = ["app"]
