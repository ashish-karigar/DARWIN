import platform
import subprocess
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol


class MediaVolumeController(Protocol):
    name: str

    def capture_volume(self) -> int | None: ...

    def set_volume(self, percent: int) -> None: ...


@dataclass(frozen=True)
class VolumeSnapshot:
    controller: MediaVolumeController
    original_percent: int
    ducked_percent: int


class AppleMusicVolumeController:
    name = "Apple Music"

    def capture_volume(self) -> int | None:
        running = subprocess.run(
            ["pgrep", "-x", "Music"],
            capture_output=True,
            timeout=2,
        )
        if running.returncode != 0:
            return None

        result = subprocess.run(
            [
                "osascript",
                "-e",
                'tell application "Music" to return (player state as text) & "|" & (sound volume as text)',
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )
        state, volume = result.stdout.strip().split("|", maxsplit=1)
        return int(volume) if state == "playing" else None

    def set_volume(self, percent: int) -> None:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'tell application "Music" to set sound volume to {percent}',
            ],
            capture_output=True,
            text=True,
            timeout=3,
            check=True,
        )


class AudioFocusManager:
    """Smoothly duck active media and reliably restore its prior volume."""

    def __init__(
        self,
        controllers: list[MediaVolumeController],
        duck_ratio: float = 0.08,
        minimum_percent: int = 8,
        fade_steps: int = 5,
        step_delay_seconds: float = 0.03,
    ) -> None:
        self._controllers = controllers
        self._duck_ratio = duck_ratio
        self._minimum_percent = minimum_percent
        self._fade_steps = fade_steps
        self._step_delay_seconds = step_delay_seconds
        self._lock = threading.RLock()
        self._depth = 0
        self._snapshots: list[VolumeSnapshot] = []

    def _capture(self) -> list[VolumeSnapshot]:
        snapshots = []
        for controller in self._controllers:
            try:
                original = controller.capture_volume()
                if original is None:
                    continue
                ducked = max(
                    self._minimum_percent,
                    round(original * self._duck_ratio),
                )
                snapshots.append(VolumeSnapshot(controller, original, ducked))
            except Exception:
                continue
        return snapshots

    def _fade(self, snapshots: list[VolumeSnapshot], restoring: bool) -> None:
        for step in range(1, self._fade_steps + 1):
            progress = step / self._fade_steps
            for snapshot in snapshots:
                start = (
                    snapshot.ducked_percent if restoring else snapshot.original_percent
                )
                end = (
                    snapshot.original_percent if restoring else snapshot.ducked_percent
                )
                value = round(start + (end - start) * progress)
                try:
                    snapshot.controller.set_volume(value)
                except Exception:
                    continue
            if self._step_delay_seconds:
                time.sleep(self._step_delay_seconds)

    @contextmanager
    def duck(self) -> Iterator[None]:
        with self._lock:
            if self._depth == 0:
                self._snapshots = self._capture()
                self._fade(self._snapshots, restoring=False)
            self._depth += 1

        try:
            yield
        finally:
            with self._lock:
                self._depth -= 1
                if self._depth == 0:
                    self._fade(self._snapshots, restoring=True)
                    self._snapshots = []


@lru_cache(maxsize=1)
def get_audio_focus_manager() -> AudioFocusManager:
    controllers: list[MediaVolumeController] = []
    if platform.system() == "Darwin":
        controllers.append(AppleMusicVolumeController())
    return AudioFocusManager(controllers)
