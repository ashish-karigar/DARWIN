"""Fast request-level progress wording, independent of individual tools."""
import re


def acknowledgement_for(message: str) -> str | None:
    text = message.casefold()
    if re.search(r'\b(abilities|capabilities|tools|arsenal|artillery)\b|\bwhat can you do\b', text):
        return None
    if not re.search(r'\b(what|whats|how|when|where|which|check|show|tell|give|fetch|look|search|research|find|add|create|remove|delete|schedule|remind|run|summari[sz]e|can you|could you|please)\b|\?', text):
        return None
    for pattern, wording in (
        (r'\b(calendar|calender|schedule|appointments?|meetings?)\b', 'Checking your calendar.'),
        (r'\b(reminders?|remind me)\b', 'Checking your reminders.'),
        (r'\b(weather|forecast|temperature)\b', 'Checking the weather.'),
        (r'\b(tasks?|to.do list)\b', 'Checking your tasks.'),
        (r'\b(diagnostics?|health check)\b', 'Checking DARWIN.'),
        (r'\b(search|look up|research|find out)\b', 'Looking into that.'),
    ):
        if re.search(pattern, text):
            return wording
    return None
