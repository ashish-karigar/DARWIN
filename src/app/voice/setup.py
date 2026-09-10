from app.voice.wake_word import ACTIVATION_NAME, activation_backend_ready


def main() -> None:
    if not activation_backend_ready():
        raise RuntimeError(
            "The personalized activation profile is unavailable. "
            "Run: python -m app.voice.enroll_wake_word"
        )
    print(f"Personalized activation ready. Say one of the enrolled {ACTIVATION_NAME} phrases.")


if __name__ == "__main__":
    main()
