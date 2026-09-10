import os
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Literal
import platform
import subprocess
import time

import spotipy
from dotenv import load_dotenv
from spotipy.cache_handler import CacheFileHandler
from spotipy.oauth2 import SpotifyPKCE

load_dotenv()

SCOPES = "user-read-playback-state user-modify-playback-state"
TOKEN_CACHE_PATH = Path("data/auth/spotify_token.json")

PlaybackAction = Literal["pause", "resume", "stop", "next", "previous"]


class SpotifyUnavailableError(RuntimeError):
    """Raised when Spotify cannot currently handle the request."""


class SpotifyNotConfiguredError(SpotifyUnavailableError):
    """Raised when required Spotify configuration is missing."""


class SpotifyPlaybackError(SpotifyUnavailableError):
    """Raised when Spotify playback or track lookup fails."""


def is_configured() -> bool:
    """Return whether the required Spotify settings are present."""

    return bool(
        os.getenv("SPOTIFY_CLIENT_ID")
        and os.getenv("SPOTIFY_REDIRECT_URI")
    )


def _auth_manager() -> SpotifyPKCE:
    client_id = os.getenv("SPOTIFY_CLIENT_ID")
    redirect_uri = os.getenv("SPOTIFY_REDIRECT_URI")

    if not client_id or not redirect_uri:
        raise SpotifyNotConfiguredError(
            "Spotify is not configured. Add SPOTIFY_CLIENT_ID and "
            "SPOTIFY_REDIRECT_URI to the .env file."
        )

    TOKEN_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    return SpotifyPKCE(
        client_id=client_id,
        redirect_uri=redirect_uri,
        scope=SCOPES,
        cache_handler=CacheFileHandler(
            cache_path=str(TOKEN_CACHE_PATH)
        ),
        open_browser=True,
        requests_timeout=10,
    )


@lru_cache(maxsize=1)
def get_client() -> spotipy.Spotify:
    """Create and reuse the authenticated Spotify client."""

    return spotipy.Spotify(
        auth_manager=_auth_manager(),
        requests_timeout=10,
    )


def authorize() -> str:
    """Run Spotify authorization and verify the signed-in account."""

    profile = get_client().current_user()
    account_name = profile.get("display_name") or profile.get("id", "unknown")

    return f"Spotify authorized for {account_name}."


def is_authorized() -> bool:
    """Check for a cached authorization without opening the browser."""

    if not is_configured() or not TOKEN_CACHE_PATH.exists():
        return False

    try:
        token = _auth_manager().get_cached_token()
        return token is not None
    except Exception:
        return False


def _normalize(value: str) -> str:
    """Normalize text for reliable title and artist comparisons."""

    value = unicodedata.normalize("NFKD", value).casefold()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _track_matches(
    track: dict,
    requested_song: str,
    requested_artist: str = "",
) -> bool:
    requested_title = _normalize(requested_song)
    actual_title = _normalize(track.get("name", ""))

    title_matches = (
        actual_title == requested_title
        or actual_title.startswith(f"{requested_title} ")
    )

    if not title_matches:
        return False

    if not requested_artist:
        return True

    expected_artist = _normalize(requested_artist)
    actual_artists = [
        _normalize(artist.get("name", ""))
        for artist in track.get("artists", [])
    ]

    return any(
        artist == expected_artist
        or artist in expected_artist
        or expected_artist in artist
        for artist in actual_artists
    )


def search_track(
    song: str,
    artist: str = "",
    client: spotipy.Spotify | None = None,
) -> dict:
    """Find a matching Spotify track without accepting unrelated results."""

    spotify = client or get_client()

    query = f'track:"{song}"'
    if artist:
        query += f' artist:"{artist}"'

    results = spotify.search(
        q=query,
        type="track",
        limit=10,
    )

    tracks = results.get("tracks", {}).get("items", [])

    for track in tracks:
        if _track_matches(track, song, artist):
            return track

    description = f"{song} by {artist}" if artist else song
    raise SpotifyPlaybackError(
        f'No reliable Spotify match was found for "{description}".'
    )


def _matching_devices(client: spotipy.Spotify) -> list[dict]:
    """Return safe playback devices matching the user's configuration."""

    configured_name = os.getenv("SPOTIFY_DEVICE_NAME", "").strip()

    devices = client.devices().get("devices", [])
    controllable = [
        device
        for device in devices
        if device.get("id") and not device.get("is_restricted")
    ]

    if configured_name:
        return [
            device
            for device in controllable
            if device.get("name", "").casefold()
            == configured_name.casefold()
        ]

    # Never select TVs or smart speakers automatically.
    return [
        device
        for device in controllable
        if device.get("type", "").casefold() == "computer"
    ]


def _launch_spotify() -> bool:
    """Launch the Spotify client on the current operating system."""

    system = platform.system()

    try:
        if system == "Darwin":
            result = subprocess.run(
                ["open", "-g", "-a", "Spotify"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0

        if system == "Windows":
            os.startfile("spotify:")  # type: ignore[attr-defined]
            return True

        if system == "Linux":
            subprocess.Popen(
                ["spotify"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True

    except (OSError, subprocess.SubprocessError):
        return False

    return False


def _wait_for_device(
    client: spotipy.Spotify,
    timeout_seconds: float = 10.0,
) -> list[dict]:
    """Wait briefly for the launched Spotify client to register."""

    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        devices = _matching_devices(client)

        if devices:
            return devices

        time.sleep(0.75)

    return []


def _select_device(client: spotipy.Spotify) -> dict:
    """Select the configured device, launching Spotify when necessary."""

    matching_devices = _matching_devices(client)

    if not matching_devices:
        if not _launch_spotify():
            raise SpotifyPlaybackError(
                "Spotify could not be launched on this computer."
            )

        matching_devices = _wait_for_device(client)

    if not matching_devices:
        raise SpotifyPlaybackError(
            "Spotify launched but no matching playback device became available."
        )

    selected = next(
        (
            device
            for device in matching_devices
            if device.get("is_active")
        ),
        matching_devices[0],
    )

    if not selected.get("is_active"):
        client.transfer_playback(
            device_id=selected["id"],
            force_play=False,
        )

    return selected


def play(song: str, artist: str = "") -> str:
    """Find and play a specific song through Spotify."""

    try:
        client = get_client()
        device = _select_device(client)
        track = search_track(song, artist, client)

        client.start_playback(
            device_id=device["id"],
            uris=[track["uri"]],
        )

        artists = ", ".join(
            item["name"] for item in track.get("artists", [])
        )

        return f"Playing {track['name']} by {artists} on Spotify."

    except SpotifyUnavailableError:
        raise
    except Exception as exc:
        raise SpotifyPlaybackError(
            f"Spotify could not start playback: {exc}"
        ) from exc


def control(action: PlaybackAction) -> str:
    """Control the currently active Spotify playback."""

    try:
        client = get_client()
        device = _select_device(client)
        device_id = device["id"]

        if action in {"pause", "stop"}:
            client.pause_playback(device_id=device_id)
            return "Spotify playback paused."

        if action == "resume":
            client.start_playback(device_id=device_id)
            return "Spotify playback resumed."

        if action == "next":
            client.next_track(device_id=device_id)
            return "Skipped to the next Spotify track."

        if action == "previous":
            client.previous_track(device_id=device_id)
            return "Returned to the previous Spotify track."

        raise ValueError(f"Unsupported playback action: {action}")

    except SpotifyUnavailableError:
        raise
    except Exception as exc:
        raise SpotifyPlaybackError(
            f"Spotify playback control failed: {exc}"
        ) from exc


def main() -> None:
    print("Opening Spotify authorization...")
    print(authorize())


if __name__ == "__main__":
    main()