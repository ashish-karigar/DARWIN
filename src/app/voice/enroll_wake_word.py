import argparse

from app.voice.personalized_wake_word import (
    SUPPORTED_WAKE_PHRASES,
    WAKE_SAMPLES_DIRECTORY,
    enroll_personalized_wake_word,
)
from app.voice.speech_to_text import record_until_silence


ENROLLMENT_PHRASES = SUPPORTED_WAKE_PHRASES * 2
SAMPLE_COUNT = len(ENROLLMENT_PHRASES)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enroll Ashish's personalized DARWIN wake phrase."
    )
    parser.add_argument(
        "--reuse-samples",
        action="store_true",
        help="Recalibrate from all existing wake-word recordings.",
    )
    args = parser.parse_args()

    WAKE_SAMPLES_DIRECTORY.mkdir(parents=True, exist_ok=True)
    samples = [
        WAKE_SAMPLES_DIRECTORY / f"sample_{index}.wav"
        for index in range(1, SAMPLE_COUNT + 1)
    ]

    if args.reuse_samples:
        missing = [str(path) for path in samples if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"Missing wake-word samples: {missing}")
    else:
        print(
            "Personalized wake-word enrollment. Record each supported DARWIN "
            "activation twice, using your normal speaking style."
        )
        for index, (path, phrase) in enumerate(
            zip(samples, ENROLLMENT_PHRASES), start=1
        ):
            input(
                f'\nSample {index} of {SAMPLE_COUNT}. Press Enter, then say: '
                f'"{phrase}".\n'
            )
            recorded = record_until_silence(
                path,
                start_timeout_seconds=10,
                silence_seconds=1.0,
                max_recording_seconds=5,
            )
            if recorded is None:
                raise RuntimeError(f"No speech detected for sample {index}.")

    print("Calibrating the wake phrase against your pronunciation...")
    profile = enroll_personalized_wake_word(samples, list(ENROLLMENT_PHRASES))
    print(
        "Enrollment complete. "
        f"Phrase threshold: {profile['distance_threshold']}; "
        f"average sample distance: {profile['average_nearest_distance']}; "
        f"wake-speaker threshold: {profile['wake_speaker_threshold']}."
    )
    print("Next run: python -m app.voice.test_wake_word")


if __name__ == "__main__":
    main()
