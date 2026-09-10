import unittest

from app.voice.speech_to_text import AdaptiveSpeechGate


class AdaptiveSpeechGateTests(unittest.TestCase):
    def test_first_loud_block_is_detected_without_calibration(self):
        gate = AdaptiveSpeechGate()

        self.assertTrue(gate.observe(1_000.0))

    def test_quiet_blocks_adapt_without_triggering(self):
        gate = AdaptiveSpeechGate()

        for volume in (90.0, 100.0, 110.0):
            self.assertFalse(gate.observe(volume))

        self.assertGreaterEqual(gate.threshold, 250.0)


if __name__ == "__main__":
    unittest.main()
