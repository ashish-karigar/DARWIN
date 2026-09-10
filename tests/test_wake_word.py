import unittest
from unittest.mock import patch

from app.voice.wake_word import ACTIVATION_NAME, activation_backend_ready


class WakeWordTests(unittest.TestCase):
    def test_activation_name_is_darwin(self):
        self.assertEqual(ACTIVATION_NAME, "DARWIN")

    @patch("app.voice.wake_word.trained_wake_word_assets_ready", return_value=True)
    def test_installed_assets_are_discoverable(self, _ready):
        self.assertTrue(activation_backend_ready())


if __name__ == "__main__":
    unittest.main()
