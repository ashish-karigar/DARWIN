from datetime import datetime
from unittest.mock import patch

from app.runtime import AssistantRuntime
from app.services.ambient_context import (
    AmbientSnapshot,
    ambient_context_prompt,
    cached_weather_json,
)
from app.services.conversational_context import ambient_intent


def test_ambient_prompt_contains_time_location_and_cached_weather() -> None:
    current = AmbientSnapshot(
        location="Middletown, Pennsylvania",
        weather={
            "location": "Middletown, Pennsylvania",
            "condition": "partly cloudy",
            "temperature_f": 72,
        },
        weather_age_seconds=12,
    )
    with patch("app.services.ambient_context.snapshot", return_value=current):
        prompt = ambient_context_prompt()

    assert "Local date and time:" in prompt
    assert "Time zone:" in prompt
    assert "Current location: Middletown, Pennsylvania" in prompt
    assert "72 degrees Fahrenheit, partly cloudy" in prompt
    assert "Weather cache age: 12 seconds" in prompt


def test_time_and_location_intents_are_narrow() -> None:
    assert ambient_intent("What time is it?") == "time"
    assert ambient_intent("Where am I?") == "location"
    assert ambient_intent("Give me a timeline") is None


def test_fresh_weather_cache_is_available_without_io() -> None:
    current = AmbientSnapshot(
        "Middletown, Pennsylvania",
        {"condition": "clear", "temperature_f": 72},
        15,
    )
    with patch("app.services.ambient_context.snapshot", return_value=current):
        cached = cached_weather_json(max_age_seconds=120)

    assert cached is not None
    assert '"temperature_f": 72' in cached


def test_stale_weather_cache_is_not_used() -> None:
    current = AmbientSnapshot(
        "Middletown, Pennsylvania",
        {"condition": "clear", "temperature_f": 72},
        121,
    )
    with patch("app.services.ambient_context.snapshot", return_value=current):
        assert cached_weather_json(max_age_seconds=120) is None


def test_current_time_uses_immediate_path_without_calling_model() -> None:
    model_calls = []
    runtime = AssistantRuntime(
        supervisor_runner=lambda message, _session: model_calls.append(message) or "slow",
        enable_fast_paths=True,
        activity_publisher=lambda _state: True,
    )

    result = runtime.submit("What is the current time?")

    assert result.content.startswith("It's ")
    assert datetime.now().strftime("%p") in result.content
    assert model_calls == []
    assert result.reasoning_seconds < 0.1


def test_current_location_uses_cached_context_without_calling_model() -> None:
    current = AmbientSnapshot("Middletown, Pennsylvania", None, None)
    with patch("app.services.conversational_context.snapshot", return_value=current):
        runtime = AssistantRuntime(
            supervisor_runner=lambda _message, _session: "slow",
            enable_fast_paths=True,
            activity_publisher=lambda _state: True,
        )
        result = runtime.submit("Where am I?")

    assert result.content == "Your current location is Middletown, Pennsylvania."
