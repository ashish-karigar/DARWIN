import argparse
from pathlib import Path

from app.voice.speaker_identity import PROFILE_DIRECTORY, enroll
from app.voice.speech_to_text import record_until_silence


PROMPTS = [
    "DARWIN, give me a concise status report.",
    "Please check the weather and read my pending tasks.",
    "Turn the music down and set the screen brightness.",
    "The quick brown fox jumps over the lazy dog.",
    "My voice authorizes conversational attention, not sensitive actions.",
]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enroll the local DARWIN speaker profile."
    )
    parser.add_argument(
        "--reuse-samples",
        action="store_true",
        help="Build the voiceprint from the five existing sample files.",
    )
    args = parser.parse_args()

    sample_directory = PROFILE_DIRECTORY / "samples"
    sample_directory.mkdir(parents=True, exist_ok=True)
    samples = [
        sample_directory / f"sample_{index}.wav" for index in range(1, len(PROMPTS) + 1)
    ]

    if args.reuse_samples:
        missing = [str(path) for path in samples if not path.exists()]
        if missing:
            raise FileNotFoundError(f"Missing enrollment samples: {missing}")
    else:
        print("DARWIN speaker enrollment. Record five natural voice samples.")
        for index, (prompt, path) in enumerate(zip(PROMPTS, samples), start=1):
            input(
                f"\nSample {index} of {len(PROMPTS)}. Press Enter, then say:\n"
                f"{prompt}\n"
            )
            recorded = record_until_silence(
                path,
                start_timeout_seconds=10,
                silence_seconds=1.5,
                max_recording_seconds=30,
            )
            if recorded is None:
                raise RuntimeError(f"No speech detected for sample {index}")

    print("Building the local voiceprint. The speaker model may download once.")
    profile = enroll(samples)
    print(
        "Enrollment complete. "
        f"Average similarity: {profile['average_enrollment_similarity']}; "
        f"verification threshold: {profile['threshold']}."
    )


if __name__ == "__main__":
    main()
