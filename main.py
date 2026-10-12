from app.runtime import AssistantRuntime
from app.voice.speech_to_text import get_last_input_timing, listen
from app.voice.text_to_speech import partial_speech_enabled, speak
from app.voice.conversation import ContinuousConversation
from app.services.location import initialize_location
from app.services.ambient_context import start_background_refresh
from app.services.telemetry import record_interaction
from app.services.performance_log import VoicePerformanceTrace
from app.services.status import set_status_handler
from app.safety import set_confirmation_handler
from app.safety.models import ActionRequest, RiskLevel
from app.system.discovery import available_capability_names
from time import perf_counter
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor


def speak_with_audio_priority(
    message: str,
    continuous: ContinuousConversation | None,
) -> dict[str, float]:
    """Keep Apple capture from attenuating TTS while media is ducked by speak()."""
    if continuous is not None:
        continuous.response_started()
    try:
        return speak(message)
    finally:
        if continuous is not None:
            continuous.response_completed()


def main() -> None:
    print("DARWIN online.")

    location = initialize_location()
    start_background_refresh()

    if location:
        print(f"Location ready: {location.label}")
    else:
        print("Location unavailable; weather requests will require a city.")

    capabilities = available_capability_names()
    if capabilities:
        print(f"System controls ready: {', '.join(capabilities)}")

    thread_id = input("Session ID [default]: ").strip() or "default"
    mode = input("Mode [continuous/voice/text]: ").strip() or "continuous"
    continuous = ContinuousConversation() if mode == "continuous" else None
    runtime = AssistantRuntime(session_id=thread_id)

    def report_status(message: str) -> None:
        print(f"\nDARWIN: {message}")
        if mode in {"voice", "continuous"}:
            speak_with_audio_priority(message, continuous)

    set_status_handler(report_status)
    progress_speaker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='darwin-progress')
    progress_futures = []

    def on_progress(event) -> None:
        if (
            partial_speech_enabled()
            and event.kind == 'response'
            and event.final is False
            and event.content
        ):
            progress_futures.append(progress_speaker.submit(report_status, event.content))

    unsubscribe_progress = runtime.subscribe(on_progress)

    def confirm_action(request: ActionRequest) -> bool:
        risk_label = request.policy.risk.value.replace("_", " ")
        prompt = f"{request.summary}. This is a {risk_label} action."
        print(f"\nConfirmation required: {prompt}")

        if mode in {"voice", "continuous"}:
            speak_with_audio_priority(
                f"{prompt} Say confirm to proceed, or cancel.",
                continuous,
            )
            answer = continuous.next_message() if continuous is not None else listen()
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

        voice_trace = None
        request_id = None
        if mode in {"voice", "continuous"}:
            request_id = str(uuid4())
            voice_trace = VoicePerformanceTrace(
                user_message, request_id, thread_id, input_timing
            )
        result = (
            runtime.submit(user_message, request_id)
            if request_id is not None
            else runtime.submit(user_message)
        )
        if voice_trace is not None:
            voice_trace.set_reasoning(result.reasoning_seconds)
        for progress in progress_futures:
            progress.result()
        progress_futures.clear()
        response = result.content

        print(f"\nDARWIN: {response}")

        speech_timing = {}
        if mode in {"voice", "continuous"}:
            tts_requested_at = perf_counter()
            speech_timing = speak_with_audio_priority(response, continuous)
            if voice_trace is not None:
                voice_trace.add_tts(
                    speech_timing, requested_at=tts_requested_at
                )
                voice_trace.finish()
            print(
                "Latency: "
                f"input total {input_total:.1f}s, "
                f"reasoning {result.reasoning_seconds:.1f}s, "
                f"first audio {speech_timing['first_audio']:.1f}s, "
                f"playback {speech_timing['playback']:.1f}s"
            )
        record_interaction(
            session_id=thread_id,
            mode=mode,
            recording_seconds=input_timing.get("recording_seconds"),
            whisper_seconds=input_timing.get("whisper_seconds"),
            reasoning_seconds=result.reasoning_seconds,
            first_audio_seconds=speech_timing.get("first_audio"),
            playback_seconds=speech_timing.get("playback"),
            response_characters=len(response),
            success=True,
        )

    unsubscribe_progress()
    progress_speaker.shutdown(wait=True)
    if continuous is not None:
        continuous.close()
    print("DARWIN offline.")


if __name__ == "__main__":
    main()
