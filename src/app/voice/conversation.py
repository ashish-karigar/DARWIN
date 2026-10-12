import os
from collections.abc import Callable

from app.voice.microphone import create_microphone
from app.voice.speaker_identity import is_enrolled, verify
from app.voice.speech_to_text import AUDIO_PATH, listen, warm_stt_model
from app.voice.wake_word import ACTIVATION_NAME, wait_for_wake_word


class ContinuousConversation:
    """Wake-gated conversation with speaker verification and follow-up turns."""

    def __init__(self, on_state: Callable[[str], None] | None = None) -> None:
        if not is_enrolled():
            raise RuntimeError(
                "Speaker profile missing. Run: python -m app.voice.enroll"
            )
        self._follow_up_seconds = float(os.getenv("DARWIN_FOLLOW_UP_SECONDS", "8"))
        self._follow_up_open = False
        self._on_state = on_state or (lambda _state: None)
        warm_stt_model()
        self._microphone = create_microphone()
        self._microphone.start()

    def next_message(self) -> str:
        while True:
            if self._follow_up_open:
                self._on_state("listening")
                print("Listening for a follow-up...")
                message = listen(
                    start_timeout_seconds=self._follow_up_seconds,
                    silence_seconds=0.8,
                    max_recording_seconds=8,
                    input_stream=self._microphone,
                )
                self._follow_up_open = False
                if not message:
                    self._on_state("idle")
                    continue
            else:
                self._on_state("idle")
                print(f"Waiting for activation: {ACTIVATION_NAME}...")
                wait_for_wake_word(input_stream=self._microphone)
                self._on_state("listening")
                print(f"{ACTIVATION_NAME} detected. Listening...")
                message = listen(
                    start_timeout_seconds=5,
                    input_stream=self._microphone,
                )
                if not message:
                    self._on_state("idle")
                    continue

            self._on_state("transcribing")
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
