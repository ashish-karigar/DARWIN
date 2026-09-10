import shutil
import subprocess

from app.system.base import SystemController
from app.system.models import Capability


class WindowsController(SystemController):
    def __init__(self) -> None:
        self._powershell = shutil.which("powershell") or shutil.which("pwsh")

    def discover(self) -> list[Capability]:
        return [
            Capability(
                "system.volume",
                False,
                "none",
                "Install a supported Windows audio backend to enable volume control.",
            ),
            Capability(
                "system.display_brightness",
                bool(self._powershell),
                "Windows WMI",
                "Built-in display brightness control is available."
                if self._powershell
                else "PowerShell is unavailable.",
            ),
            Capability(
                "system.keyboard_brightness",
                False,
                "none",
                "Keyboard backlight control depends on the hardware vendor.",
            ),
            Capability(
                "audio_focus.apple_music",
                False,
                "none",
                "Apple Music audio focus is not configured on Windows.",
            ),
        ]

    def get_volume(self) -> int:
        raise NotImplementedError("Windows volume backend is unavailable")

    def set_volume(self, percent: int) -> None:
        raise NotImplementedError("Windows volume backend is unavailable")

    def get_display_brightness(self) -> int:
        if not self._powershell:
            raise NotImplementedError("PowerShell is unavailable")
        command = "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness).CurrentBrightness"
        result = subprocess.run(
            [self._powershell, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return int(result.stdout.strip().splitlines()[0])

    def set_display_brightness(self, percent: int) -> None:
        if not self._powershell:
            raise NotImplementedError("PowerShell is unavailable")
        command = (
            "$m=Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods;"
            f"Invoke-CimMethod -InputObject $m -MethodName WmiSetBrightness -Arguments @{{Timeout=0;Brightness={percent}}}"
        )
        subprocess.run(
            [self._powershell, "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )

    def get_keyboard_brightness(self) -> int:
        raise NotImplementedError("Keyboard brightness backend is unavailable")

    def set_keyboard_brightness(self, percent: int) -> None:
        raise NotImplementedError("Keyboard brightness backend is unavailable")
