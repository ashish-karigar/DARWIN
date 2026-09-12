import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

from app.voice.microphone import (
    FRAME_SIZE,
    AppleVoiceProcessedMicrophone,
    PersistentMicrophone,
    create_microphone,
)


class FakeStream:
    def __init__(self, **options) -> None:
        self.callback = options["callback"]
        self.active = False
        self.closed = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def close(self):
        self.closed = True


class PersistentMicrophoneTests(unittest.TestCase):
    def setUp(self):
        self.stream = None

        def factory(**options):
            self.stream = FakeStream(**options)
            return self.stream

        self.microphone = PersistentMicrophone(stream_factory=factory)

    def tearDown(self):
        self.microphone.close()

    def test_stream_starts_once_and_returns_callback_audio(self):
        self.microphone.start()
        frame = np.ones((FRAME_SIZE, 1), dtype=np.int16)
        self.stream.callback(frame, FRAME_SIZE, None, None)

        captured, overflowed = self.microphone.read(FRAME_SIZE)

        np.testing.assert_array_equal(captured, frame)
        self.assertFalse(overflowed)

    def test_clear_discards_buffered_audio(self):
        frame = np.ones((FRAME_SIZE, 1), dtype=np.int16)
        self.stream.callback(frame, FRAME_SIZE, None, None)

        self.microphone.clear()

        self.assertTrue(self.microphone._frames.empty())

    def test_close_is_idempotent(self):
        self.microphone.start()

        self.microphone.close()
        self.microphone.close()

        self.assertTrue(self.stream.closed)

    def test_suspend_and_resume_release_and_restart_stream(self):
        self.microphone.start()
        self.microphone.suspend()
        self.assertFalse(self.stream.active)

        self.microphone.resume()

        self.assertTrue(self.stream.active)


class FakeProcess:
    def __init__(self, audio: bytes, diagnostics: bytes = b"ready\n") -> None:
        self.stdout = BytesIO(audio)
        self.stderr = BytesIO(diagnostics)
        self.return_code = None
        self.terminated = False

    def poll(self):
        return self.return_code

    def terminate(self):
        self.terminated = True
        self.return_code = 0

    def wait(self, timeout=None):
        return self.return_code

    def kill(self):
        self.return_code = -9


class AppleVoiceProcessedMicrophoneTests(unittest.TestCase):
    def test_reads_one_exact_pcm_frame_from_helper(self):
        expected = np.arange(FRAME_SIZE, dtype=np.int16).reshape(-1, 1)
        process = FakeProcess(expected.astype("<i2").tobytes())
        with TemporaryDirectory() as directory:
            helper = Path(directory) / "capture"
            helper.touch()
            microphone = AppleVoiceProcessedMicrophone(
                helper_path=helper,
                process_factory=lambda *args, **kwargs: process,
            )
            with patch("app.voice.microphone.sys.platform", "darwin"):
                microphone.start()
                captured, overflowed = microphone.read(FRAME_SIZE)
            microphone.close()

        np.testing.assert_array_equal(captured, expected)
        self.assertFalse(overflowed)
        self.assertTrue(process.terminated)

    def test_suspend_releases_helper_and_resume_starts_a_new_process(self):
        processes = [FakeProcess(b""), FakeProcess(b"")]
        launches = []

        def factory(*args, **kwargs):
            launches.append(args)
            return processes[len(launches) - 1]

        with TemporaryDirectory() as directory:
            helper = Path(directory) / "capture"
            helper.touch()
            microphone = AppleVoiceProcessedMicrophone(
                helper_path=helper,
                process_factory=factory,
            )
            with patch("app.voice.microphone.sys.platform", "darwin"):
                microphone.start()
                microphone.suspend()
                microphone.resume()
            microphone.close()

        self.assertEqual(len(launches), 2)
        self.assertTrue(processes[0].terminated)
        self.assertTrue(processes[1].terminated)

    def test_apple_backend_requires_built_helper(self):
        with patch(
            "app.voice.microphone.DEFAULT_APPLE_HELPER",
            Path("/definitely/missing/darwin-voice-capture"),
        ), patch("app.voice.microphone.sys.platform", "darwin"):
            with self.assertRaises(FileNotFoundError):
                create_microphone("apple")

    def test_auto_backend_falls_back_to_portaudio(self):
        fallback = object()
        with patch("app.voice.microphone.sys.platform", "linux"), patch(
            "app.voice.microphone.PersistentMicrophone", return_value=fallback
        ) as portaudio:
            microphone = create_microphone("auto")
        self.assertIs(microphone, fallback)
        portaudio.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
