import re
import shutil
import subprocess

from app.system.base import SystemController
from app.system.models import Capability


class LinuxController(SystemController):
    def __init__(self) -> None:
        self._volume_command = shutil.which("wpctl")
        self._brightness_command = shutil.which("brightnessctl")

    def discover(self) -> list[Capability]:
        return [
            Capability(
                "system.volume",
                bool(self._volume_command),
                "WirePlumber wpctl",
                "Install wpctl to enable volume control."
                if not self._volume_command
                else "Default audio-sink control is available.",
            ),
            Capability(
                "system.display_brightness",
                bool(self._brightness_command),
                "brightnessctl",
                "Install brightnessctl to enable display control."
                if not self._brightness_command
                else "Display brightness control is available.",
                "Backlight-device access may require a system group or udev rule.",
            ),
            Capability(
                "system.keyboard_brightness",
                False,
                "brightnessctl",
                "A keyboard-backlight device must be discovered at runtime.",
            ),
            Capability(
                "audio_focus.apple_music",
                False,
                "none",
                "Apple Music audio focus is unavailable on Linux.",
            ),
        ]

    def get_volume(self) -> int:
        if not self._volume_command:
            raise NotImplementedError("Volume backend is unavailable")
        result = subprocess.run(
            [self._volume_command, "get-volume", "@DEFAULT_AUDIO_SINK@"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        match = re.search(r"([0-9.]+)", result.stdout)
        if not match:
            raise RuntimeError("Unable to read volume")
        return round(float(match.group(1)) * 100)

    def set_volume(self, percent: int) -> None:
        if not self._volume_command:
            raise NotImplementedError("Volume backend is unavailable")
        subprocess.run(
            [self._volume_command, "set-volume", "@DEFAULT_AUDIO_SINK@", f"{percent}%"],
            timeout=3,
            check=True,
        )

    def get_display_brightness(self) -> int:
        if not self._brightness_command:
            raise NotImplementedError("Display brightness backend is unavailable")
        result = subprocess.run(
            [self._brightness_command, "-m"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        match = re.search(r"(\d+)%", result.stdout)
        if not match:
            raise RuntimeError("Unable to read display brightness")
        return int(match.group(1))

    def set_display_brightness(self, percent: int) -> None:
        if not self._brightness_command:
            raise NotImplementedError("Display brightness backend is unavailable")
        subprocess.run(
            [self._brightness_command, "set", f"{percent}%"],
            timeout=3,
            check=True,
        )

    def get_keyboard_brightness(self) -> int:
        raise NotImplementedError(
            "Keyboard brightness device discovery is not implemented"
        )

    def set_keyboard_brightness(self, percent: int) -> None:
        raise NotImplementedError(
            "Keyboard brightness device discovery is not implemented"
        )
