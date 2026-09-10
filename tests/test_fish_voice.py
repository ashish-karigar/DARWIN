import os
from pathlib import Path

from dotenv import load_dotenv
from fishaudio import FishAudio


def main() -> None:
    """Manual network smoke test; intentionally excluded from unit execution."""
    load_dotenv()
    client = FishAudio()
    audio = client.tts.convert(
        text=(
            "[calm] Good evening, sir. DARWIN is online. "
            "All systems are operating normally."
        ),
        model=os.getenv("FISH_TTS_MODEL", "s2.1-pro-free"),
        reference_id=os.getenv("FISH_VOICE_ID"),
        format="wav",
        latency="balanced",
        speed=1.25,
    )
    output_path = Path("data/fish_test.wav")
    output_path.write_bytes(audio)
    print(f"Created {output_path}")


if __name__ == "__main__":
    main()
