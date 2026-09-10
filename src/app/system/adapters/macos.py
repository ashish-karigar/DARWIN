import re
import shutil
import subprocess

from app.system.base import SystemController
from app.system.models import Capability


class MacOSController(SystemController):
    def __init__(self) -> None:
        self._brightness_command = shutil.which("brightness")

    def discover(self) -> list[Capability]:
        return [
            Capability(
                key="system.volume",
                available=bool(shutil.which("osascript")),
                provider="macOS AppleScript",
                detail="Built-in output-volume control.",
            ),
            Capability(
                key="system.display_brightness",
                available=bool(self._brightness_command),
                provider="brightness CLI",
                detail=(
                    "Display brightness is available."
                    if self._brightness_command
                    else "Install the brightness CLI to enable display control."
                ),
            ),
            Capability(
                key="system.keyboard_brightness",
                available=False,
                provider="none",
                detail="No supported public keyboard-backlight backend was discovered.",
            ),
            Capability(
                key="audio_focus.apple_music",
                available=bool(shutil.which("osascript")),
                provider="Music AppleScript",
                detail="Per-application volume ducking is available.",
                permission="Automation access to Music",
            ),
        ]

    def get_volume(self) -> int:
        result = subprocess.run(
            ["osascript", "-e", "output volume of (get volume settings)"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        return int(result.stdout.strip())

    def set_volume(self, percent: int) -> None:
        subprocess.run(
            ["osascript", "-e", f"set volume output volume {percent}"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )

    def get_display_brightness(self) -> int:
        if not self._brightness_command:
            raise NotImplementedError("Display brightness backend is unavailable")
        result = subprocess.run(
            [self._brightness_command, "-l"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        matches = re.findall(r"brightness\s+([0-9.]+)", result.stdout)
        if not matches:
            raise RuntimeError("Unable to read display brightness")
        return round(float(matches[-1]) * 100)

    def set_display_brightness(self, percent: int) -> None:
        if not self._brightness_command:
            raise NotImplementedError("Display brightness backend is unavailable")
        subprocess.run(
            [self._brightness_command, f"{percent / 100:.2f}"],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )

    def get_keyboard_brightness(self) -> int:
        raise NotImplementedError("Keyboard brightness backend is unavailable")

    def set_keyboard_brightness(self, percent: int) -> None:
        raise NotImplementedError("Keyboard brightness backend is unavailable")
