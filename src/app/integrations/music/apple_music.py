import platform
import subprocess
import tempfile
from typing import Literal


SHORTCUT_NAME = "DARWIN Play Music"

PlaybackAction = Literal[
    "pause",
    "resume",
    "stop",
    "next",
    "previous",
]


class AppleMusicUnavailableError(RuntimeError):
    """Raised when Apple Music cannot handle a request."""


def is_available() -> bool:
    """Return whether Apple Music integration can run on this system."""

    return platform.system() == "Darwin"


def play(song: str, artist: str = "") -> str:
    """Play music using the DARWIN Apple Music Shortcut."""

    if not is_available():
        raise AppleMusicUnavailableError(
            "Apple Music integration is only available on macOS."
        )

    query = f"{song} by {artist}" if artist else song

    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            encoding="utf-8",
        ) as input_file:
            input_file.write(query)
            input_file.flush()

            result = subprocess.run(
                [
                    "shortcuts",
                    "run",
                    SHORTCUT_NAME,
                    "--input-path",
                    input_file.name,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AppleMusicUnavailableError(
            "Apple Music playback could not be started."
        ) from exc

    if result.returncode != 0:
        error = result.stderr.strip() or "The Apple Music Shortcut failed."
        raise AppleMusicUnavailableError(error)

    return f"Playing {query} in Apple Music."


def play_from_library(song: str, artist: str = "") -> str:
    """Play an exact match from the user's local Apple Music library."""

    script = """
    on run argv
        set requestedSong to item 1 of argv
        set requestedArtist to item 2 of argv

        tell application "Music"
            activate
            set matches to search playlist "Library" for requestedSong only songs
            set selectedTrack to missing value

            repeat with candidate in matches
                set candidateName to name of candidate
                set candidateArtist to artist of candidate

                ignoring case
                    if candidateName is requestedSong then
                        if requestedArtist is "" or candidateArtist contains requestedArtist then
                            set selectedTrack to candidate
                            exit repeat
                        end if
                    end if
                end ignoring
            end repeat

            if selectedTrack is missing value then
                return "NO_MATCH"
            end if

            play selectedTrack
            return "Playing " & name of selectedTrack & " by " & artist of selectedTrack
        end tell
    end run
    """

    try:
        result = subprocess.run(
            ["osascript", "-e", script, song, artist],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AppleMusicUnavailableError(
            "The Apple Music library could not be searched."
        ) from exc

    if result.returncode != 0:
        raise AppleMusicUnavailableError(
            result.stderr.strip() or "Apple Music automation failed."
        )

    response = result.stdout.strip()

    if response == "NO_MATCH":
        description = f"{song} by {artist}" if artist else song
        raise AppleMusicUnavailableError(
            f'No exact Apple Music library match was found for "{description}".'
        )

    return response


def control(action: PlaybackAction) -> str:
    """Control playback in the Apple Music application."""

    if not is_available():
        raise AppleMusicUnavailableError(
            "Apple Music integration is only available on macOS."
        )

    normalized_action = "pause" if action == "stop" else action

    commands = {
        "pause": "pause",
        "resume": "play",
        "next": "next track",
        "previous": "previous track",
    }

    descriptions = {
        "pause": "Apple Music playback paused.",
        "resume": "Apple Music playback resumed.",
        "next": "Skipped to the next Apple Music track.",
        "previous": "Returned to the previous Apple Music track.",
    }

    command = commands.get(normalized_action)

    if command is None:
        raise ValueError(f"Unsupported playback action: {action}")

    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'tell application "Music" to {command}',
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AppleMusicUnavailableError(
            "Apple Music playback control failed."
        ) from exc

    return descriptions[normalized_action]
