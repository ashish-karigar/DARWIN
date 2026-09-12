import platform
from functools import lru_cache

from app.system.adapters.linux import LinuxController
from app.system.adapters.macos import MacOSController
from app.system.adapters.windows import WindowsController
from app.system.base import SystemController
from app.system.models import Capability


@lru_cache(maxsize=1)
def get_system_controller() -> SystemController:
    system = platform.system()
    if system == "Darwin":
        return MacOSController()
    if system == "Linux":
        return LinuxController()
    if system == "Windows":
        return WindowsController()
    raise RuntimeError(f"Unsupported operating system: {system}")


def discover_capabilities() -> list[Capability]:
    capabilities = get_system_controller().discover()
    try:
        from app.integrations.music.spotify import is_authorized, is_configured

        configured = is_configured()
        authorized = configured and is_authorized()
        capabilities.append(
            Capability(
                key="audio_focus.spotify",
                available=authorized,
                provider="Spotify Web API",
                detail=(
                    "Spotify playback ducking is available."
                    if authorized
                    else "Authorize Spotify to enable playback ducking."
                ),
                permission=None if authorized else "Spotify playback authorization",
            )
        )
    except Exception:
        capabilities.append(
            Capability(
                key="audio_focus.spotify",
                available=False,
                provider="Spotify Web API",
                detail="Spotify capability discovery failed safely.",
            )
        )
    return capabilities


def available_capability_names() -> list[str]:
    """Return concise names suitable for the startup status line."""
    labels = {
        "system.volume": "volume",
        "system.display_brightness": "display brightness",
        "system.keyboard_brightness": "keyboard brightness",
        "audio_focus.spotify": "Spotify audio focus",
        "audio_focus.apple_music": "Apple Music audio focus",
    }
    return [
        labels.get(capability.key, capability.key)
        for capability in discover_capabilities()
        if capability.available
    ]


def capability_map() -> dict[str, Capability]:
    return {capability.key: capability for capability in discover_capabilities()}
