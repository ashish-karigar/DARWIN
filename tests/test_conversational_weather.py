import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.runtime import AssistantCancelledError, AssistantRuntime
from app.services.conversational_weather import (
    WeatherIntent,
    correction_location,
    fetch_weather_response,
    is_weather_request,
    resolve_weather_intent,
)


def test_weather_intent_extracts_an_explicit_location() -> None:
    intent = resolve_weather_intent("What's the weather in Harrisburg, Pennsylvania?")

    assert intent.location == "Harrisburg, Pennsylvania"
    assert intent.acknowledgement == "Checking Harrisburg, Pennsylvania now."
    assert is_weather_request("Will it rain today?")
    assert correction_location("No, Middletown, Pennsylvania") == (
        "Middletown, Pennsylvania"
    )


def test_weather_response_is_formatted_without_an_llm() -> None:
    response = fetch_weather_response(
        WeatherIntent("Middletown, Pennsylvania", "Checking Middletown now."),
        fetcher=lambda _location: json.dumps(
            {
                "location": "Middletown, Pennsylvania, United States",
                "condition": "partly cloudy",
                "temperature_f": 72,
                "feels_like_f": 71,
                "precipitation_inches": 0,
                "wind_mph": 6,
            }
        ),
    )

    assert response == (
        "In Middletown, Pennsylvania, United States, it's 72 degrees and partly "
        "cloudy, and it feels like 71. Winds are around 6 miles per hour."
    )


def test_current_location_weather_reuses_fresh_cache(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.conversational_weather.cached_weather_json",
        lambda: json.dumps(
            {
                "location": "Middletown, Pennsylvania",
                "condition": "clear",
                "temperature_f": 72,
                "feels_like_f": 72,
                "precipitation_inches": 0,
                "wind_mph": 3,
            }
        ),
    )
    monkeypatch.setattr(
        "app.services.conversational_weather._fetch_current_weather",
        lambda _location: (_ for _ in ()).throw(AssertionError("network called")),
    )

    response = fetch_weather_response(WeatherIntent(None, "Checking now."))

    assert response.startswith("In Middletown, Pennsylvania, it's 72 degrees")


def test_weather_fast_path_acknowledges_before_lookup_completes(monkeypatch) -> None:
    lookup_started = Event()
    release_lookup = Event()
    observed = []

    def fetch(_intent):
        lookup_started.set()
        assert release_lookup.wait(timeout=1)
        return "It is 72 degrees."

    monkeypatch.setattr("app.runtime.fetch_weather_response", fetch)
    runtime = AssistantRuntime(
        supervisor_runner=lambda _message, _session: "should not run",
        enable_fast_paths=True,
        activity_publisher=lambda _state: True,
    )
    runtime.subscribe(observed.append)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(runtime.submit, "What's the weather today?")
        assert lookup_started.wait(timeout=1)
        acknowledgement = next(
            event for event in observed if event.kind == "response"
        )
        assert acknowledgement.final is False
        assert acknowledgement.content.startswith("Checking ")
        release_lookup.set()
        result = future.result(timeout=1)

    assert result.content == "It is 72 degrees."
    responses = [event for event in observed if event.kind == "response"]
    assert [event.final for event in responses] == [False, True]


def test_weather_correction_supersedes_stale_result(monkeypatch) -> None:
    first_started = Event()
    release_first = Event()
    observed = []

    def fetch(intent):
        if intent.location is None:
            first_started.set()
            assert release_first.wait(timeout=1)
            return "Stale weather."
        return f"Weather for {intent.location}."

    monkeypatch.setattr("app.runtime.fetch_weather_response", fetch)
    runtime = AssistantRuntime(
        supervisor_runner=lambda _message, _session: "should not run",
        enable_fast_paths=True,
        activity_publisher=lambda _state: True,
    )
    runtime.subscribe(observed.append)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(runtime.submit, "What's the weather today?")
        assert first_started.wait(timeout=1)
        corrected = executor.submit(runtime.submit, "No, Harrisburg")
        assert corrected.result(timeout=1).content == "Weather for Harrisburg."
        release_first.set()
        with pytest.raises(AssistantCancelledError, match="superseded"):
            first.result(timeout=1)

    final_responses = [
        event.content
        for event in observed
        if event.kind == "response" and event.final is True
    ]
    assert final_responses == ["Weather for Harrisburg."]


def test_location_answer_continues_weather_turn_and_becomes_session_default(
    monkeypatch,
) -> None:
    calls = []

    def fetch(intent):
        calls.append(intent.location)
        if len(calls) == 1:
            return "Which town should I use?"
        return f"Weather for {intent.location}."

    monkeypatch.setattr("app.runtime.fetch_weather_response", fetch)
    runtime = AssistantRuntime(
        supervisor_runner=lambda _message, _session: "should not run",
        enable_fast_paths=True,
        activity_publisher=lambda _state: True,
    )

    assert runtime.submit("What's the weather today?").content == (
        "Which town should I use?"
    )
    assert runtime.submit("Middletown, Pennsylvania").content == (
        "Weather for Middletown, Pennsylvania."
    )
    assert calls[-1] == "Middletown, Pennsylvania"
