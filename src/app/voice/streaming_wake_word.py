"""Interactive microphone test for DARWIN's trained wake-word model."""

from app.voice.openwakeword_detector import OpenWakeWordDetector


def main() -> None:
    detector = OpenWakeWordDetector()
    print(
        "Trained streaming detector ready. "
        f'Say "DARWIN" (threshold {detector.threshold:.2f}).'
    )

    try:
        while True:
            detection = detector.wait()
            print(
                "TRIGGERED: DARWIN | "
                f"score {detection.score:.3f}/{detection.threshold:.3f}"
            )
            print('Listening again. Say "DARWIN"...')
    except KeyboardInterrupt:
        print("\nStreaming wake-word test stopped.")


if __name__ == "__main__":
    main()
