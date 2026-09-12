import os

from app.voice.microphone import create_microphone
from app.voice.speaker_identity import is_enrolled, verify
from app.voice.speech_to_text import AUDIO_PATH, listen
from app.voice.wake_word import ACTIVATION_NAME, wait_for_wake_word


class ContinuousConversation:
    """Wake-gated conversation with speaker verification and follow-up turns."""

    def __init__(self) -> None:
        if not is_enrolled():
            raise RuntimeError(
                "Speaker profile missing. Run: python -m app.voice.enroll"
            )
        self._follow_up_seconds = float(os.getenv("DARWIN_FOLLOW_UP_SECONDS", "8"))
        self._follow_up_open = False
        self._microphone = create_microphone()
        self._microphone.start()

    def next_message(self) -> str:
        while True:
            if self._follow_up_open:
                print("Listening for a follow-up...")
                message = listen(
                    start_timeout_seconds=self._follow_up_seconds,
                    silence_seconds=0.8,
                    max_recording_seconds=8,
                    input_stream=self._microphone,
                )
                self._follow_up_open = False
                if not message:
                    continue
            else:
                print(f"Waiting for activation: {ACTIVATION_NAME}...")
                wait_for_wake_word(input_stream=self._microphone)
                print(f"{ACTIVATION_NAME} detected. Listening...")
                message = listen(
                    start_timeout_seconds=5,
                    input_stream=self._microphone,
                )
                if not message:
                    continue

            verification = verify(AUDIO_PATH)
            if verification.accepted:
                return message

            print(
                "Speaker not recognized "
                f"({verification.similarity:.2f} below {verification.threshold:.2f})."
            )

    def response_completed(self) -> None:
        self._microphone.clear()
        self._microphone.resume()
        self._follow_up_open = True

    def response_started(self) -> None:
        self._microphone.suspend()

    def close(self) -> None:
        self._microphone.close()
