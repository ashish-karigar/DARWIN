"""Collect personalized wake-word examples under real media playback."""

from datetime import datetime
from pathlib import Path

import sounddevice as sd
from scipy.io.wavfile import write


SAMPLE_RATE = 16_000
RECORDING_SECONDS = 2.5
POSITIVE_SAMPLE_COUNT = 12
NEGATIVE_PHRASES = (
    "What's the weather today?",
    "Play some music.",
    "Give me a status report.",
    "What time is it?",
    "Pause the current track.",
    "Tell me about my tasks.",
    "Turn the volume down.",
    "Thank you, that works.",
)
MUSIC_ONLY_SAMPLE_COUNT = 8
PROFILE_ROOT = Path("data/voice_profiles/ashish/darwin_media")


def _record(path: Path) -> None:
    print("Recording now...")
    audio = sd.rec(
        int(RECORDING_SECONDS * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="int16",
    )
    sd.wait()
    path.parent.mkdir(parents=True, exist_ok=True)
    write(path, SAMPLE_RATE, audio)


def main() -> None:
    session = datetime.now().strftime("%Y%m%d_%H%M%S")
    output = PROFILE_ROOT / session

    print("DARWIN media wake-word enrollment.")
    print("Keep Spotify playing at your normal listening volume throughout.")

    for index in range(1, POSITIVE_SAMPLE_COUNT + 1):
        input(
            f'\nPositive sample {index} of {POSITIVE_SAMPLE_COUNT}. '
            'Press Enter, then naturally say "DARWIN" once.\n'
        )
        _record(output / "positive" / f"sample_{index:02d}.wav")

    for index, phrase in enumerate(NEGATIVE_PHRASES, start=1):
        input(
            f'\nNon-wake sample {index} of {len(NEGATIVE_PHRASES)}. '
            f'Press Enter, then say: "{phrase}"\n'
        )
        _record(output / "negative_speech" / f"sample_{index:02d}.wav")

    input(
        "\nNext are music-only samples. Do not speak. "
        "Press Enter to begin.\n"
    )
    for index in range(1, MUSIC_ONLY_SAMPLE_COUNT + 1):
        print(f"Music-only sample {index} of {MUSIC_ONLY_SAMPLE_COUNT}.")
        _record(output / "negative_music" / f"sample_{index:02d}.wav")

    print(f"\nEnrollment recordings saved to {output}.")
    print("Music can be paused now.")


if __name__ == "__main__":
    main()
