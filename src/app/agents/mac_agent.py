from app.agents.base import build_agent
from app.tools.music import MUSIC_TOOLS
from app.tools.system_controls import SYSTEM_CONTROL_TOOLS
from app.tools.camera import CAMERA_TOOLS
from app.tools.apps import APP_TOOLS


MAC_PROMPT = """
You are DARWIN's Mac-control specialist.

Use only the provided allowlisted tools.
For music requests, extract the exact song title, artist when provided,
and requested provider. Use "auto" when the user does not name a provider.
Use system-control tools for capability discovery, volume, display brightness,
and keyboard brightness. Never pretend an unavailable control succeeded.
Use control_camera for opening or closing DARWIN's Camera app, taking a picture,
switching to the next or previous camera, object detection, and mirroring.

Music playback is a low-impact action and runs without confirmation.
Use control_music for pause, stop, resume, next-track, and previous-track requests.
Treat "stop it" as pause when the conversation is about active music.
Never change system volume for stop or pause language. Use a volume tool only when
the user explicitly says volume, mute, unmute, louder, quieter, or gives a percentage.
Never claim an action succeeded unless the tool confirms success.
If confirmation is denied, report cancellation and do not call the tool again.
Keep the result brief and conversational.
If a music request omits the song or playlist, ask only:
"Which song or playlist would you like me to play?"
"""

MAC_TOOLS = [*MUSIC_TOOLS, *SYSTEM_CONTROL_TOOLS, *CAMERA_TOOLS, *APP_TOOLS]
for bundle, capability in (
    (MUSIC_TOOLS, "control music"),
    (SYSTEM_CONTROL_TOOLS, "adjust supported Mac settings"),
    (CAMERA_TOOLS, "control the camera"),
    (APP_TOOLS, "open and close installed apps"),
):
    for registered_tool in bundle:
        registered_tool.metadata = {"capability": capability}

mac_agent = build_agent(
    system_prompt=MAC_PROMPT,
    tools=MAC_TOOLS,
)


def run_mac_agent(query: str) -> str:
    result = mac_agent.invoke({"messages": [{"role": "user", "content": query}]})
    return result["messages"][-1].content
