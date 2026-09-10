import unittest

from app.system.audio_focus import AudioFocusManager
from app.tools.system_controls import _bounded_percent


class FakeMediaController:
    name = "fake"

    def __init__(self, volume: int | None = 80):
        self.volume = volume
        self.values = []

    def capture_volume(self) -> int | None:
        return self.volume

    def set_volume(self, percent: int) -> None:
        self.values.append(percent)


class AudioFocusTests(unittest.TestCase):
    def test_ducks_and_restores_media_volume(self):
        controller = FakeMediaController(80)
        manager = AudioFocusManager(
            [controller],
            duck_ratio=0.25,
            fade_steps=2,
            step_delay_seconds=0,
        )
        with manager.duck():
            self.assertEqual(controller.values[-1], 20)
        self.assertEqual(controller.values[-1], 80)

    def test_nested_focus_only_restores_at_outer_exit(self):
        controller = FakeMediaController(80)
        manager = AudioFocusManager([controller], fade_steps=1, step_delay_seconds=0)
        with manager.duck():
            with manager.duck():
                self.assertEqual(len(controller.values), 1)
            self.assertEqual(len(controller.values), 1)
        self.assertEqual(len(controller.values), 2)

    def test_percent_validation(self):
        self.assertEqual(_bounded_percent(50), 50)
        with self.assertRaises(ValueError):
            _bounded_percent(101)


if __name__ == "__main__":
    unittest.main()
