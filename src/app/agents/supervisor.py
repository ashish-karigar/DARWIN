import sqlite3
import re
import json

from langgraph.checkpoint.sqlite import SqliteSaver

from app.agents.base import build_agent
from app.agents.response_quality import clean_response
from app.agents.supervisor_tools import SUPERVISOR_TOOLS, ask_diagnostics_specialist, ask_productivity_specialist
from app.tools.capabilities import capability_summary
from app.agents.productivity_agent import _LAST_SCHEDULE_DAY
from app.tools.apps import installed_apps, control_app
from app.tools.camera import control_camera
from app.runtime_events import raise_if_cancelled


SUPERVISOR_PROMPT = """
You are DARWIN: Distributed Agentic Reasoning and Workflow Intelligence Network.
You were created by Ashish and act as his personal operations assistant.

Speak calmly, concisely, and with understated wit.
Address Ashish as "sir" naturally, but do not overuse it.
Never use generic customer-service closings or emojis.

Conversation discipline:
- If Ashish merely shares an observation, fact, possession, or status, acknowledge it naturally in one short sentence.
- Do not give advice, reorganize, explain, or propose next steps unless he asks.
- An inventory such as "I have these items on my desk" is a statement, not a request to organize the desk.
- For an inventory statement, acknowledge and remember it. Do not list the items back unless asked.
- Match the requested depth. If no depth is requested, prefer one or two short sentences.
- Ask a follow-up only when it is genuinely required to complete an explicit request.
- When a required detail is missing, ask only one direct question. Do not preface it
  with filler such as "sure", "certainly", or "let me".

Use "sir" sparingly, only for occasional greetings or command acknowledgements.
Do not begin ordinary informational answers with "sir".
Never use it in consecutive responses.

Your role is to understand intent and delegate specialist work:
- Delegate factual or research questions likely covered by indexed documents,
  questions about DARWIN, Ashish's stored knowledge, project architecture,
  and explicit requests to search sources or the vector database to the
  knowledge specialist.
- Answer identity questions directly. For capabilities, call discover_tools and use
  the current registry, including specialist tools and installed UI apps. Do not
  confuse app installation with data access. Never invent unsupported operations.
- You can control DARWIN's Camera app. Its supported actions are opening and closing
  the camera, taking a picture, switching cameras, starting and stopping object
  detection, and enabling, disabling, or toggling mirroring. Never say that you
  cannot control the camera.
- Answer casual general knowledge, explanations, conversation, and arithmetic
  directly only when source-backed retrieval is unnecessary.
- Delegate calendar, schedule, appointments, reminders, tasks and scheduling
  follow-up answers to the productivity specialist. Preserve its clarification
  question verbatim; never invent a missing date/time or turn a question into success.
- For an explicit camera command, call control_camera directly. Delegate broader
  camera questions and music, volume, display, keyboard, and system-control
  requests to the Mac specialist.
- When the conversation concerns playing music, interpret "stop it" or "pause it"
  as playback control, never as a system-volume request.
- You may handle greetings and ordinary conversation directly.
- For requests spanning multiple domains, call every relevant specialist.
- Call at most one specialist at a time. After receiving its result, produce one final answer.
- Never invent specialist data or silently answer from assumptions.
- Treat a grounded knowledge result as authoritative. Preserve its facts and
  citation markers without substituting parametric knowledge.
- Combine specialist results into one concise final response.
- Delegate current weather questions to the weather specialist.
- Never answer live-weather questions without consulting that specialist.
- Delegate DARWIN health, diagnostics, failures, and latency questions to the diagnostics specialist.
- Never invent health, latency, or accuracy numbers; use measured diagnostics only.
- Tool safety decisions are authoritative. Never claim a denied or failed action succeeded.
- If confirmation is denied, acknowledge cancellation once and do not retry the action.

Speech-first output:
- Every final response may be spoken aloud.
- Keep ordinary answers under forty spoken words unless Ashish explicitly requests detail or a list.
- Use plain conversational sentences only.
- Never output Markdown tables, headings, bullets, numbered lists, code fences, or emojis.
- Never read or expose raw JSON returned by specialists.
- Never present yourself as a specialist. Specialist output is private evidence that you rewrite in DARWIN's voice.
- Summarize status naturally by category and count.
- When details are requested, connect items with phrases such as "First", "Next", and "Finally".
- Avoid symbols and abbreviations that sound unnatural when spoken.
- End after delivering the answer; do not append generic offers of further assistance.
- Never repeat an answer or append a second conflicting answer.
"""

connection = sqlite3.connect(
    "data/conversation_memory.sqlite",
    check_same_thread=False,
)

supervisor = build_agent(
    system_prompt=SUPERVISOR_PROMPT,
    tools=SUPERVISOR_TOOLS,
    checkpointer=SqliteSaver(connection),
)


def _camera_action(message: str) -> str | None:
    """Resolve unambiguous camera commands without depending on an LLM route."""
    text = re.sub(r"\s+", " ", message.strip().casefold())
    if re.search(r"\b(take|snap|capture)\b.*\b(photo|picture|image)\b", text):
        return "capture"
    if "camera" not in text and "detection" not in text and "mirroring" not in text:
        return None
    if re.search(r"\b(stop|disable|turn off)\b.*\b(object )?detection\b", text):
        return "stop_detection"
    if re.search(r"\b(start|enable|turn on)\b.*\b(object )?detection\b", text):
        return "start_detection"
    if re.search(r"\b(previous|back)\b.*\bcamera\b", text):
        return "previous_camera"
    if re.search(r"\b(switch|change|next)\b.*\bcamera\b", text):
        return "next_camera"
    if re.search(
        r"(?:\b(turn off|disable)\b.*\bmirror(?:ing)?\b|\bmirror(?:ing)?\b.*\boff\b)",
        text,
    ):
        return "mirror_off"
    if re.search(
        r"(?:\b(turn on|enable)\b.*\bmirror(?:ing)?\b|\bmirror(?:ing)?\b.*\bon\b)",
        text,
    ):
        return "mirror_on"
    if re.search(r"\b(toggle)\b.*\bmirror(?:ing)?\b", text):
        return "toggle_mirror"
    if re.search(r"\b(close|quit|exit|hide)\b.*\bcamera\b", text):
        return "close"
    if re.search(r"\b(open|launch|show|start)\b.*\bcamera\b", text):
        return "open"
    return None


_CAMERA_CONFIRMATIONS = {
    "open": "Opening the camera.",
    "close": "Closing the camera.",
    "capture": "Taking a picture.",
    "next_camera": "Switching cameras.",
    "previous_camera": "Switching to the previous camera.",
    "start_detection": "Starting object detection.",
    "stop_detection": "Stopping object detection.",
    "mirror_on": "Turning camera mirroring on.",
    "mirror_off": "Turning camera mirroring off.",
    "toggle_mirror": "Toggling camera mirroring.",
}

_PRODUCTIVITY_FOLLOWUP: set[str] = set()


def _remove_consecutive_duplicate_sentences(text: str) -> str:
    """Remove exact adjacent sentence duplication occasionally emitted by models."""
    import re

    compact = text.strip()
    midpoint = len(compact) // 2
    if len(compact) % 2 == 0 and compact[:midpoint] == compact[midpoint:]:
        return compact[:midpoint].strip()

    sentence_pattern = re.compile(r".*?(?:[.!?](?=\s|[A-Z]|$)|$)", re.DOTALL)
    sentences = [match.group(0).strip() for match in sentence_pattern.finditer(compact)]
    sentences = [sentence for sentence in sentences if sentence]

    cleaned: list[str] = []
    for sentence in sentences:
        normalized = re.sub(r"\s+", " ", sentence).casefold()
        previous = re.sub(r"\s+", " ", cleaned[-1]).casefold() if cleaned else None
        if normalized != previous:
            cleaned.append(sentence)

    return " ".join(cleaned)


def run_supervisor(
    user_message: str,
    thread_id: str = "default",
) -> str:
    raise_if_cancelled()
    normalized = user_message.casefold()
    if re.search(r"\b(what|which|list|tell|show)\b.*\b(abilities|capabilities|tools|arsenal|artillery)\b|\bwhat can you do\b", normalized):
        return capability_summary()
    if normalized.strip().rstrip('.!') in {'never mind', 'nevermind', 'forget it', 'cancel that'} and thread_id in _PRODUCTIVITY_FOLLOWUP:
        _PRODUCTIVITY_FOLLOWUP.discard(thread_id)
        return "Cancelled."
    app_action = re.search(r'\b(open|launch|close|quit)\b', normalized)
    if app_action:
        for app in installed_apps():
            if re.search(r'\b' + re.escape(app['name'].casefold()) + r'\b', normalized):
                action = 'close' if app_action.group(0) in {'close', 'quit'} else 'open'
                result = json.loads(control_app.invoke({'app_name': app['id'], 'action': action}))
                return f"{'Opening' if action == 'open' else 'Closing'} {app['name']}." if result.get('ok') else "I couldn't control that app from this session."
    productivity_request = re.search(r"\b(calendar|schedule|appointments?|reminders?|remind me|meetings?)\b", normalized) or (thread_id in _LAST_SCHEDULE_DAY and re.search(r'\b(summary|summari[sz]e|overview)\b', normalized))
    unrelated_domain = re.search(r'\b(camera|music|weather|diagnostics?|volume)\b', normalized)
    if productivity_request or (thread_id in _PRODUCTIVITY_FOLLOWUP and not unrelated_domain):
        response = ask_productivity_specialist.invoke({"query": user_message})
        if response.strip().endswith("?"):
            _PRODUCTIVITY_FOLLOWUP.add(thread_id)
        else:
            _PRODUCTIVITY_FOLLOWUP.discard(thread_id)
        return clean_response(response)
    camera_action = _camera_action(user_message)
    if camera_action:
        raise_if_cancelled()
        control_camera.invoke({"action": camera_action})
        raise_if_cancelled()
        return _CAMERA_CONFIRMATIONS[camera_action]
    normalized = user_message.casefold()
    if re.search(r"\bdiagnostics?\b|\bhealth check\b", normalized):
        response = ask_diagnostics_specialist.invoke({"query": user_message})
        cleaned = clean_response(response)
        if not cleaned:
            raise RuntimeError("The diagnostics specialist returned an empty response.")
        return cleaned
    if "camera" in normalized and any(
        phrase in normalized
        for phrase in ("can you", "are you able", "what can", "do you support")
    ):
        return (
            "I can open and close the camera, take pictures, switch cameras, "
            "control object detection, and change mirroring."
        )
    result = supervisor.invoke(
        {"messages": [{"role": "user", "content": user_message}]},
        {"configurable": {"thread_id": thread_id}},
    )
    raise_if_cancelled()
    response = clean_response(
        _remove_consecutive_duplicate_sentences(
            result["messages"][-1].content.strip()
        )
    )

    if not response:
        raise RuntimeError("The supervisor returned an empty response.")

    return response
