from app.agents.supervisor import run_supervisor
from app.voice.speech_to_text import get_last_input_timing, listen
from app.voice.text_to_speech import speak
from app.voice.conversation import ContinuousConversation
from app.services.location import initialize_location
from app.services.telemetry import record_interaction
from app.services.status import set_status_handler
from app.safety import action_context, set_confirmation_handler
from app.safety.models import ActionRequest, RiskLevel
from time import perf_counter


def main() -> None:
    print("DARWIN online.")

    location = initialize_location()

    if location:
        print(f"Location ready: {location.label}")
    else:
        print("Location unavailable; weather requests will require a city.")

    thread_id = input("Session ID [default]: ").strip() or "default"
    mode = input("Mode [continuous/voice/text]: ").strip() or "continuous"
    continuous = ContinuousConversation() if mode == "continuous" else None

    def report_status(message: str) -> None:
        print(f"\nDARWIN: {message}")
        if mode in {"voice", "continuous"}:
            speak(message)

    set_status_handler(report_status)

    def confirm_action(request: ActionRequest) -> bool:
        risk_label = request.policy.risk.value.replace("_", " ")
        prompt = f"{request.summary}. This is a {risk_label} action."
        print(f"\nConfirmation required: {prompt}")

        if mode in {"voice", "continuous"}:
            speak(f"{prompt} Say confirm to proceed, or cancel.")
            answer = listen()
            print(f"Confirmation response: {answer}")
        else:
            answer = input("Allow? [y/N]: ").strip()

        normalized = answer.casefold().strip(" .,!?")
        if request.policy.risk is RiskLevel.DESTRUCTIVE:
            return normalized == "confirm destructive action"
        if request.policy.risk is RiskLevel.REVERSIBLE_WRITE:
            return normalized in {"y", "yes", "confirm", "conform", "proceed", "allow"}
        return normalized == "confirm"

    set_confirmation_handler(confirm_action)

    while True:
        if mode == "continuous":
            user_message = continuous.next_message()
            transcription_finished = perf_counter()
            input_timing = get_last_input_timing()
            input_total = sum(
                value or 0.0
                for value in (
                    input_timing.get("recording_seconds"),
                    input_timing.get("whisper_seconds"),
                )
            )
            print(f"You: {user_message}")

        elif mode == "voice":
            command = input("\nPress Enter to speak, or type 'exit' to quit: ").strip()
            if command.lower() == "exit":
                break

            started = perf_counter()
            user_message = listen()
            transcription_finished = perf_counter()
            input_timing = get_last_input_timing()
            input_total = transcription_finished - started
            print(f"You: {user_message}")

        else:
            user_message = input("You: ").strip()
            input_timing = {}

        normalized_message = user_message.lower().strip(" \t\n.,!?")

        if normalized_message in {"exit", "quit"}:
            print("DARWIN: Goodbye!")
            break

        if not user_message:
            print("i did not hear anything.")
            continue

        reasoning_started = perf_counter()
        with action_context(thread_id):
            response = run_supervisor(
                user_message,
                thread_id=thread_id,
            )
        reasoning_finished = perf_counter()

        print(f"\nDARWIN: {response}")

        speech_timing = {}
        if mode in {"voice", "continuous"}:
            speech_timing = speak(response)
            print(
                "Latency: "
                f"input total {input_total:.1f}s, "
                f"reasoning {reasoning_finished - reasoning_started:.1f}s, "
                f"first audio {speech_timing['first_audio']:.1f}s, "
                f"playback {speech_timing['playback']:.1f}s"
            )
            if continuous is not None:
                continuous.response_completed()

        record_interaction(
            session_id=thread_id,
            mode=mode,
            recording_seconds=input_timing.get("recording_seconds"),
            whisper_seconds=input_timing.get("whisper_seconds"),
            reasoning_seconds=reasoning_finished - reasoning_started,
            first_audio_seconds=speech_timing.get("first_audio"),
            playback_seconds=speech_timing.get("playback"),
            response_characters=len(response),
            success=True,
        )

    print("DARWIN offline.")


if __name__ == "__main__":
    main()
