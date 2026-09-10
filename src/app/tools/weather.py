import json

import httpx
from langchain_core.tools import tool

from app.services.location import get_current_location
from app.safety import execute_guarded


WEATHER_CODES = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy with frost",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "light rain showers",
    81: "rain showers",
    82: "heavy rain showers",
    95: "thunderstorms",
}


def _fetch_current_weather(
    location: str | None = None,
) -> str:
    current_location = get_current_location()

    if not location and not current_location:
        return json.dumps({"error": "Current location is unavailable."})

    try:
        with httpx.Client(timeout=15) as client:
            if location:
                geocoding_response = client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={
                        "name": location,
                        "count": 1,
                        "language": "en",
                        "format": "json",
                    },
                )
                geocoding_response.raise_for_status()

                results = geocoding_response.json().get(
                    "results",
                    [],
                )

                if not results:
                    return json.dumps({"error": (f"Location not found: {location}")})

                place = results[0]

                latitude = place["latitude"]
                longitude = place["longitude"]

                resolved_location = ", ".join(
                    part
                    for part in [
                        place.get("name"),
                        place.get("admin1"),
                        place.get("country"),
                    ]
                    if part
                )

            else:
                latitude = current_location.latitude
                longitude = current_location.longitude
                resolved_location = current_location.label

            weather_response = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "current": (
                        "temperature_2m,"
                        "apparent_temperature,"
                        "precipitation,"
                        "weather_code,"
                        "wind_speed_10m"
                    ),
                    "temperature_unit": "fahrenheit",
                    "wind_speed_unit": "mph",
                    "precipitation_unit": "inch",
                    "timezone": "auto",
                },
            )
            weather_response.raise_for_status()
            current = weather_response.json()["current"]

    except httpx.HTTPError as error:
        return json.dumps({"error": f"Weather service unavailable: {error}"})

    return json.dumps(
        {
            "location": resolved_location,
            "condition": WEATHER_CODES.get(
                current["weather_code"],
                "unknown conditions",
            ),
            "temperature_f": current["temperature_2m"],
            "feels_like_f": current["apparent_temperature"],
            "precipitation_inches": current["precipitation"],
            "wind_mph": current["wind_speed_10m"],
            "observed_at": current["time"],
        }
    )


@tool
def get_current_weather(location: str | None = None) -> str:
    """Get live weather. Uses the Mac's cached location when none is provided."""
    execution = execute_guarded(
        "weather.current",
        "Retrieve current weather conditions",
        lambda: _fetch_current_weather(location),
        metadata={"location_source": "explicit" if location else "startup_cache"},
    )
    if execution.succeeded:
        return execution.value or json.dumps({"error": "Weather returned no data."})
    return json.dumps({"error": "Weather access was blocked or failed."})
