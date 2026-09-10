import unittest

import numpy as np

from app.voice.audio_features import dtw_distance
from app.voice.personalized_wake_word import transcript_contains_darwin


class PersonalizedWakeWordTests(unittest.TestCase):
    def test_common_darwin_transcriptions_are_accepted(self):
        for transcript in ("Hey Darwin", "Hello Darwen", "Darvin"):
            with self.subTest(transcript=transcript):
                self.assertTrue(transcript_contains_darwin(transcript))

    def test_unrelated_transcript_is_rejected(self):
        self.assertFalse(transcript_contains_darwin("The music is still playing"))

    def test_identical_templates_have_zero_distance(self):
        template = np.array(
            [[0.0, 1.0], [1.0, 0.0], [0.5, 0.5]],
            dtype=np.float32,
        )

        self.assertAlmostEqual(dtw_distance(template, template), 0.0)

    def test_time_warped_template_remains_close(self):
        template = np.array(
            [[0.0, 1.0], [1.0, 0.0], [0.5, 0.5]],
            dtype=np.float32,
        )
        stretched = np.repeat(template, 2, axis=0)

        self.assertAlmostEqual(dtw_distance(template, stretched), 0.0)


if __name__ == "__main__":
    unittest.main()
