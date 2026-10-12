"""Fast shared context that is available to every conversation."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime
from time import monotonic

from app.services.location import get_current_location, initialize_location
from app.tools.weather import _fetch_current_weather


@dataclass(frozen=True)
class AmbientSnapshot:
    location: str | None
    weather: dict[str, object] | None
    weather_age_seconds: float | None


_LOCK = threading.RLock()
_WEATHER: dict[str, object] | None = None
_WEATHER_UPDATED_AT: float | None = None
_REFRESH_THREAD: threading.Thread | None = None
_REFRESH_INTERVAL_SECONDS = 600.0


def snapshot() -> AmbientSnapshot:
    location = get_current_location()
    with _LOCK:
        weather = dict(_WEATHER) if _WEATHER is not None else None
        updated_at = _WEATHER_UPDATED_AT
    return AmbientSnapshot(
        location=location.label if location is not None else None,
        weather=weather,
        weather_age_seconds=(
            max(0.0, monotonic() - updated_at) if updated_at is not None else None
        ),
    )


def cached_weather_json(max_age_seconds: float = _REFRESH_INTERVAL_SECONDS) -> str | None:
    """Return fresh cached weather without performing I/O."""
    current = snapshot()
    if (
        current.weather is None
        or current.weather_age_seconds is None
        or current.weather_age_seconds > max(0.0, max_age_seconds)
    ):
        return None
    return json.dumps(current.weather)


def ambient_context_prompt() -> str:
    """Build a compact prompt using memory only; this never performs network I/O."""
    now = datetime.now().astimezone()
    current = snapshot()
    lines = [
        "Current ambient context (trusted local state):",
        f"- Local date and time: {now.isoformat(timespec='seconds')}",
        f"- Time zone: {now.tzname() or str(now.tzinfo)}",
        f"- Current location: {current.location or 'unavailable'}",
    ]
    if current.weather:
        weather = current.weather
        lines.extend(
            [
                "- Cached current weather: "
                f"{weather.get('temperature_f')} degrees Fahrenheit, "
                f"{weather.get('condition', 'unknown conditions')} in "
                f"{weather.get('location', current.location or 'the current location')}",
                f"- Weather cache age: {round(current.weather_age_seconds or 0)} seconds",
            ]
        )
    else:
        lines.append("- Cached current weather: unavailable")
    lines.append(
        "Use this context directly for ordinary conversation. For live weather, "
        "use the weather path rather than assuming cached conditions are current."
    )
    return "\n".join(lines)


def refresh_once() -> AmbientSnapshot:
    """Refresh location and weather; call from a background worker."""
    global _WEATHER, _WEATHER_UPDATED_AT
    if get_current_location() is None:
        initialize_location()
    if get_current_location() is not None:
        try:
            weather = json.loads(_fetch_current_weather())
        except (json.JSONDecodeError, TypeError):
            weather = None
        if weather and "error" not in weather:
            with _LOCK:
                _WEATHER = weather
                _WEATHER_UPDATED_AT = monotonic()
    return snapshot()


def start_background_refresh() -> None:
    """Start one daemon refresher without delaying backend readiness."""
    global _REFRESH_THREAD
    with _LOCK:
        if _REFRESH_THREAD is not None and _REFRESH_THREAD.is_alive():
            return

        def refresh_loop() -> None:
            while True:
                try:
                    refresh_once()
                except Exception:
                    pass
                threading.Event().wait(_REFRESH_INTERVAL_SECONDS)

        _REFRESH_THREAD = threading.Thread(
            target=refresh_loop,
            name="darwin-ambient-context",
            daemon=True,
        )
        _REFRESH_THREAD.start()
