"""Deterministic responses for ambient facts that do not need an LLM."""

from __future__ import annotations

import re
from datetime import datetime

from app.services.ambient_context import snapshot


_TIME = re.compile(r"\b(?:what(?:'s| is) the )?(?:current )?time\b", re.I)
_LOCATION = re.compile(
    r"\b(?:where am i|what(?:'s| is) my (?:current )?location|current location)\b",
    re.I,
)


def ambient_intent(message: str) -> str | None:
    if _TIME.search(message):
        return "time"
    if _LOCATION.search(message):
        return "location"
    return None


def ambient_response(intent: str) -> str:
    if intent == "time":
        now = datetime.now().astimezone()
        spoken = now.strftime("%-I:%M %p")
        return f"It's {spoken} {now.tzname() or ''}.".replace("  ", " ")
    current = snapshot()
    if current.location:
        return f"Your current location is {current.location}."
    return "Current location is unavailable because no location is cached yet."
