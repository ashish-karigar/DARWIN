from app.agents.base import build_agent
from app.services.location import get_current_location
from app.tools.weather import get_current_weather


WEATHER_PROMPT = """
You are DARWIN's weather specialist.

Always use the weather tool for current conditions.
Never invent live weather data.
Report the resolved location, condition, temperature,
feels-like temperature, and useful precipitation or wind details.
Keep the response brief and conversational.

When no location is stated, call the weather tool without a location so it uses the Mac's cached current location.
Never ask for a location when none is provided.
Call get_current_weather with no location so it uses the cached Mac location.
"""

weather_agent = build_agent(
    system_prompt=WEATHER_PROMPT,
    tools=[get_current_weather],
)


def run_weather_agent(query: str) -> str:
    result = weather_agent.invoke(
        {"messages": [{"role": "user", "content": query}]}
    )
    response = result["messages"][-1].content

    # The location cache is authoritative. Do not make the user repeat a
    # location that DARWIN successfully discovered during startup.
    asks_for_location = any(
        phrase in response.casefold()
        for phrase in (
            "which city",
            "which location",
            "what city",
            "what location",
            "city or region",
        )
    )
    if asks_for_location and get_current_location() is not None:
        return get_current_weather.invoke({})

    return response
