from pathlib import Path

from app.voice.personalized_wake_word import (
    SUPPORTED_WAKE_PHRASES,
    evaluate_wake_word,
)
from app.voice.speech_to_text import record_until_silence


TEST_AUDIO_DIRECTORY = Path("data/voice_profiles/ashish/darwin_wake_word/tests")
TRIAL_COUNT = len(SUPPORTED_WAKE_PHRASES)


def main() -> None:
    TEST_AUDIO_DIRECTORY.mkdir(parents=True, exist_ok=True)
    print("Personalized wake-word test. Each supported phrase will be tested once.")
    accepted_count = 0

    for index, phrase in enumerate(SUPPORTED_WAKE_PHRASES, start=1):
        print(f'\nTrial {index} of {TRIAL_COUNT}: say "{phrase}" now.')
        test_audio_path = TEST_AUDIO_DIRECTORY / f"trial_{index}.wav"
        recorded = record_until_silence(
            test_audio_path,
            start_timeout_seconds=10,
            silence_seconds=1.0,
            max_recording_seconds=5,
        )
        if recorded is None:
            print("Result: no speech detected.")
            continue

        result = evaluate_wake_word(recorded)
        accepted_count += int(result.accepted)
        print(
            f"Result: {'TRIGGERED' if result.accepted else 'REJECTED'} | "
            f"phrase {result.phrase_distance:.3f}/{result.phrase_threshold:.3f} | "
            f"voice {result.speaker.similarity:.3f}/{result.speaker.threshold:.3f}"
        )

    print(f"\nWake-word reliability: {accepted_count} of {TRIAL_COUNT} trials.")


if __name__ == "__main__":
    main()
