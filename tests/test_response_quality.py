import unittest

from app.agents.response_quality import clean_response
from app.agents.supervisor import _remove_consecutive_duplicate_sentences
from app.voice.text_to_speech import clean_for_speech
from app.voice.text_to_speech import clean_for_speech


class ResponseQualityTests(unittest.TestCase):
    def test_duplicate_sentence_is_removed(self):
        self.assertEqual(
            _remove_consecutive_duplicate_sentences(
                "Weather is clear. Weather is clear."
            ),
            "Weather is clear.",
        )

    def test_decimal_is_spoken_digit_by_digit(self):
        self.assertIn("1 point 6", clean_for_speech("Latency is 1.6 seconds."))

    def test_punctuation_run_is_removed(self):
        response = "Sure, let me…............…  Which song would you like?"

        self.assertEqual(
            clean_response(response),
            "Which song would you like?",
        )


if __name__ == "__main__":
    unittest.main()
