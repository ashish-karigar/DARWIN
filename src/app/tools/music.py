import os
from typing import Callable, Literal

from dotenv import load_dotenv
from langchain_core.tools import tool

from app.integrations.music import apple_music, spotify
from app.safety import execute_guarded


load_dotenv()

MusicProvider = Literal["auto", "spotify", "apple_music"]
PlaybackAction = Literal["pause", "resume", "stop", "next", "previous"]

_active_provider: str | None = None


def _normalized_playback_action(action: PlaybackAction) -> str:
    return "pause" if action == "stop" else action


def _provider_order(provider: MusicProvider) -> list[str]:
    """Return providers in the order they should be attempted."""

    if provider != "auto":
        return [provider]

    default = os.getenv(
        "DEFAULT_MUSIC_PROVIDER",
        "spotify",
    ).strip().lower()

    if default == "apple_music":
        return ["apple_music", "spotify"]

    return ["spotify", "apple_music"]


def _provider_is_ready(provider: str) -> bool:
    if provider == "spotify":
        return spotify.is_configured() and spotify.is_authorized()

    if provider == "apple_music":
        return apple_music.is_available()

    return False


def _play_handler(provider: str) -> Callable[[str, str], str]:
    handlers = {
        "spotify": spotify.play,
        "apple_music": apple_music.play,
    }

    try:
        return handlers[provider]
    except KeyError as exc:
        raise ValueError(f"Unsupported music provider: {provider}") from exc


def _control_handler(
    provider: str,
) -> Callable[[PlaybackAction], str]:
    handlers = {
        "spotify": spotify.control,
        "apple_music": apple_music.control,
    }

    try:
        return handlers[provider]
    except KeyError as exc:
        raise ValueError(f"Unsupported music provider: {provider}") from exc


def _play_with_fallback(
    song: str,
    artist: str,
    requested_provider: MusicProvider,
) -> str:
    """Play through the preferred provider, falling back in auto mode."""

    global _active_provider

    failures: list[str] = []

    for provider in _provider_order(requested_provider):
        if not _provider_is_ready(provider):
            failures.append(f"{provider} is not available")
            continue

        try:
            result = _play_handler(provider)(song, artist)
            _active_provider = provider
            return result
        except (
            spotify.SpotifyUnavailableError,
            apple_music.AppleMusicUnavailableError,
        ) as exc:
            failures.append(f"{provider}: {exc}")

            if requested_provider != "auto":
                raise

    details = "; ".join(failures)
    raise RuntimeError(
        f"No music provider could play the request. {details}"
    )


def _control_with_fallback(
    action: PlaybackAction,
    requested_provider: MusicProvider,
) -> str:
    """Control the active provider, with fallback when appropriate."""

    global _active_provider

    if requested_provider == "auto" and _active_provider:
        providers = [_active_provider]
        providers.extend(
            provider
            for provider in _provider_order("auto")
            if provider != _active_provider
        )
    else:
        providers = _provider_order(requested_provider)

    failures: list[str] = []

    for provider in providers:
        if not _provider_is_ready(provider):
            failures.append(f"{provider} is not available")
            continue

        try:
            result = _control_handler(provider)(action)
            _active_provider = provider
            return result
        except (
            spotify.SpotifyUnavailableError,
            apple_music.AppleMusicUnavailableError,
        ) as exc:
            failures.append(f"{provider}: {exc}")

            if requested_provider != "auto":
                raise

    details = "; ".join(failures)
    raise RuntimeError(
        f"No music provider could perform the action. {details}"
    )


@tool
def play_music(
    song: str,
    artist: str = "",
    provider: MusicProvider = "auto",
) -> str:
    """Play a song using Spotify first, with Apple Music fallback."""

    query = f"{song} by {artist}" if artist else song

    execution = execute_guarded(
        "music.play",
        f"Play {query}",
        lambda: _play_with_fallback(song, artist, provider),
        metadata={
            "provider": provider,
            "song": song,
            "artist": artist,
        },
    )

    if execution.succeeded:
        return execution.value or "Music playback started."

    if execution.error_type:
        return "Music playback failed safely."

    return "Music playback was cancelled."


@tool
def control_music(
    action: PlaybackAction,
    provider: MusicProvider = "auto",
) -> str:
    """Pause, resume, stop, skip, or return to a previous track."""

    normalized_action = _normalized_playback_action(action)

    execution = execute_guarded(
        "music.control",
        f"{normalized_action.title()} music playback",
        lambda: _control_with_fallback(action, provider),
        metadata={
            "provider": provider,
            "action": normalized_action,
        },
    )

    if execution.succeeded:
        return execution.value or "Music playback updated."

    if execution.error_type:
        return "Music control failed safely."

    return "Music control was cancelled."


MUSIC_TOOLS = [play_music, control_music]