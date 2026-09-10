import numpy as np
import soundfile as sf
from kokoro import KPipeline


def main() -> None:
    """Manual local voice smoke test; intentionally excluded from unit execution."""
    pipeline = KPipeline(lang_code="b")
    audio_chunks = [
        audio
        for _, _, audio in pipeline(
            "Good evening, sir. DARWIN is online, and all systems are operating normally.",
            voice="bm_george",
            speed=1.25,
        )
    ]
    audio = np.concatenate(audio_chunks)
    sf.write("data/kokoro_test.wav", audio, 24_000)
    print("Created data/kokoro_test.wav")


if __name__ == "__main__":
    main()
