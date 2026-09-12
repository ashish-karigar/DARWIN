import unittest

import numpy as np

from app.voice.speech_activity import SpeechActivityDetector


class FakeVad:
    def __init__(self, score: float) -> None:
        self.score = score
        self.was_reset = False

    def predict(self, samples, frame_size=640):
        return self.score

    def reset_states(self):
        self.was_reset = True


class SpeechActivityDetectorTests(unittest.TestCase):
    def test_probability_at_threshold_is_speech(self):
        detector = SpeechActivityDetector(threshold=0.5, runtime=FakeVad(0.5))

        result = detector.process(np.zeros(1280, dtype=np.int16))

        self.assertTrue(result.is_speech)

    def test_probability_below_threshold_is_not_speech(self):
        detector = SpeechActivityDetector(threshold=0.5, runtime=FakeVad(0.49))

        result = detector.process(np.zeros(1280, dtype=np.int16))

        self.assertFalse(result.is_speech)

    def test_reset_clears_runtime_state(self):
        runtime = FakeVad(0.0)
        detector = SpeechActivityDetector(runtime=runtime)

        detector.reset()

        self.assertTrue(runtime.was_reset)


if __name__ == "__main__":
    unittest.main()
