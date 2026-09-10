import unittest
from unittest.mock import patch

import numpy as np

from app.voice.openwakeword_detector import DEFAULT_THRESHOLD, OpenWakeWordDetector


class FakeRuntime:
    def __init__(self, scores: list[float]) -> None:
        self.scores = iter(scores)
        self.received: list[np.ndarray] = []
        self.was_reset = False

    def predict(self, samples: np.ndarray) -> dict[str, float]:
        self.received.append(samples)
        return {"darwin_v1": next(self.scores)}

    def reset(self) -> None:
        self.was_reset = True


class OpenWakeWordDetectorTests(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_default_threshold_prioritizes_real_world_recall(self):
        detector = OpenWakeWordDetector(runtime=FakeRuntime([0.0]))

        self.assertEqual(detector.threshold, DEFAULT_THRESHOLD)

    def test_score_at_threshold_triggers(self):
        detector = OpenWakeWordDetector(
            threshold=0.5,
            runtime=FakeRuntime([0.5]),
        )

        result = detector.process(np.zeros(1280, dtype=np.int16))

        self.assertTrue(result.triggered)
        self.assertEqual(result.score, 0.5)

    def test_score_below_threshold_does_not_trigger(self):
        detector = OpenWakeWordDetector(
            threshold=0.5,
            runtime=FakeRuntime([0.49]),
        )

        result = detector.process(np.zeros(1280, dtype=np.int16))

        self.assertFalse(result.triggered)

    def test_float_audio_is_converted_to_pcm(self):
        runtime = FakeRuntime([0.0])
        detector = OpenWakeWordDetector(threshold=0.5, runtime=runtime)

        detector.process(np.array([-1.0, 0.0, 1.0], dtype=np.float32))

        self.assertEqual(runtime.received[0].dtype, np.int16)
        np.testing.assert_array_equal(
            runtime.received[0],
            np.array([-32767, 0, 32767], dtype=np.int16),
        )

    def test_reset_clears_runtime_state(self):
        runtime = FakeRuntime([0.0])
        detector = OpenWakeWordDetector(threshold=0.5, runtime=runtime)

        detector.reset()

        self.assertTrue(runtime.was_reset)


if __name__ == "__main__":
    unittest.main()
