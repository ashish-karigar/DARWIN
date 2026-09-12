import unittest
from unittest.mock import patch

from app.system.audio_focus import AudioFocusManager, SpotifyVolumeController
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


class FakeSpotifyClient:
    def __init__(self, playback):
        self.playback = playback
        self.values = []

    def current_playback(self):
        return self.playback

    def volume(self, percent, device_id=None):
        self.values.append((percent, device_id))


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

    def test_spotify_ducks_configured_active_computer(self):
        client = FakeSpotifyClient(
            {
                "is_playing": True,
                "device": {
                    "id": "macbook",
                    "name": "Ashish's MacBook Pro",
                    "type": "Computer",
                    "supports_volume": True,
                    "volume_percent": 70,
                },
            }
        )
        controller = SpotifyVolumeController(client_factory=lambda: client)
        manager = AudioFocusManager(
            [controller],
            duck_ratio=0.1,
            minimum_percent=5,
            fade_steps=1,
            step_delay_seconds=0,
        )

        with patch.dict(
            "os.environ",
            {"SPOTIFY_DEVICE_NAME": "Ashish's MacBook Pro"},
        ):
            with manager.duck():
                self.assertEqual(client.values[-1], (7, "macbook"))

        self.assertEqual(client.values[-1], (70, "macbook"))

    def test_spotify_ignores_remote_speaker(self):
        client = FakeSpotifyClient(
            {
                "is_playing": True,
                "device": {
                    "id": "echo",
                    "name": "Echo",
                    "type": "Speaker",
                    "supports_volume": True,
                    "volume_percent": 70,
                },
            }
        )
        controller = SpotifyVolumeController(client_factory=lambda: client)

        self.assertIsNone(controller.capture_volume())


if __name__ == "__main__":
    unittest.main()
