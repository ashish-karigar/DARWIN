"""Deterministic, low-latency weather path for conversational turns."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from app.services.location import get_current_location
from app.services.ambient_context import cached_weather_json
from app.tools.weather import _fetch_current_weather


_WEATHER_PATTERN = re.compile(
    r"\b(weather|forecast|temperature|rain(?:ing)?|snow(?:ing)?)\b",
    re.IGNORECASE,
)
_LOCATION_PATTERNS = (
    re.compile(r"\b(?:weather|forecast)\s+(?:in|for|at)\s+(.+?)[?.!]*$", re.I),
    re.compile(r"\b(?:in|for|at)\s+([^?.!]+)[?.!]*$", re.I),
)
_CORRECTION_PREFIX = re.compile(
    r"^(?:no[,.]?\s*)?(?:i\s+meant\s+|use\s+|try\s+)?(.+?)[?.!]*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WeatherIntent:
    location: str | None
    acknowledgement: str


def is_weather_request(message: str) -> bool:
    return bool(_WEATHER_PATTERN.search(message))


def correction_location(message: str) -> str | None:
    """Return a corrected place from a short follow-up such as 'No, Harrisburg'."""
    compact = " ".join(message.strip().split())
    if not compact or len(compact) > 100:
        return None
    match = _CORRECTION_PREFIX.match(compact)
    if not match:
        return None
    candidate = match.group(1).strip(" ,")
    if not candidate or _WEATHER_PATTERN.search(candidate):
        return None
    # Avoid turning normal conversational sentences into locations.
    if len(candidate.split()) > 6:
        return None
    return candidate


def resolve_weather_intent(
    message: str,
    *,
    corrected_location: str | None = None,
    default_location: str | None = None,
) -> WeatherIntent:
    location = corrected_location or _explicit_location(message)
    if location:
        return WeatherIntent(location, f"Checking {location} now.")

    current = get_current_location()
    if current is not None:
        return WeatherIntent(None, f"Checking {current.label} now.")
    if default_location:
        return WeatherIntent(default_location, f"Checking {default_location} now.")
    return WeatherIntent(None, "Checking the weather now.")


def fetch_weather_response(
    intent: WeatherIntent,
    *,
    fetcher: Callable[[str | None], str] | None = None,
) -> str:
    if fetcher is None:
        cached = cached_weather_json() if intent.location is None else None
        fetcher = (lambda _location: cached) if cached is not None else _fetch_current_weather
    try:
        payload = json.loads(fetcher(intent.location))
    except (json.JSONDecodeError, TypeError):
        return "I couldn't read the weather service response."

    if error := payload.get("error"):
        if "location is unavailable" in str(error).casefold():
            return "Which town should I use?"
        return "The weather service is unavailable right now."

    location = payload.get("location") or intent.location or "your area"
    condition = payload.get("condition", "unknown conditions")
    temperature = _number(payload.get("temperature_f"))
    feels_like = _number(payload.get("feels_like_f"))
    precipitation = payload.get("precipitation_inches")
    wind = _number(payload.get("wind_mph"))

    response = f"In {location}, it's {temperature} degrees and {condition}"
    if feels_like != temperature:
        response += f", and it feels like {feels_like}"
    response += "."
    if isinstance(precipitation, (int, float)) and precipitation > 0:
        response += f" Precipitation is {precipitation:g} inches."
    elif isinstance(wind, str) and wind not in {"0", "0.0"}:
        response += f" Winds are around {wind} miles per hour."
    return response


def _explicit_location(message: str) -> str | None:
    compact = " ".join(message.strip().split())
    for pattern in _LOCATION_PATTERNS:
        if match := pattern.search(compact):
            candidate = match.group(1).strip(" ,")
            if candidate and candidate.casefold() not in {"today", "now", "outside"}:
                return candidate
    return None


def _number(value: object) -> str:
    if isinstance(value, (int, float)):
        return f"{value:g}"
    return str(value)
