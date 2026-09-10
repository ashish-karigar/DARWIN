from types import MappingProxyType

from app.safety.models import ActionPolicy, RiskLevel


_POLICIES = {
    "knowledge.search": ActionPolicy(
        "knowledge.search", RiskLevel.READ_ONLY, "Search DARWIN knowledge"
    ),
    "tasks.list": ActionPolicy("tasks.list", RiskLevel.READ_ONLY, "Read the task list"),
    "weather.current": ActionPolicy(
        "weather.current", RiskLevel.READ_ONLY, "Read current weather"
    ),
    "diagnostics.performance": ActionPolicy(
        "diagnostics.performance", RiskLevel.READ_ONLY, "Read performance telemetry"
    ),
    "diagnostics.live": ActionPolicy(
        "diagnostics.live", RiskLevel.READ_ONLY, "Run non-destructive health probes"
    ),
    "music.play": ActionPolicy(
        "music.play", RiskLevel.LOW_IMPACT, "Start music playback"
    ),
    "music.control": ActionPolicy(
        "music.control", RiskLevel.LOW_IMPACT, "Control active music playback"
    ),
    "system.discover": ActionPolicy(
        "system.discover", RiskLevel.READ_ONLY, "Discover available system controls"
    ),
    "system.volume": ActionPolicy(
        "system.volume", RiskLevel.LOW_IMPACT, "Adjust system volume"
    ),
    "system.display_brightness": ActionPolicy(
        "system.display_brightness", RiskLevel.LOW_IMPACT, "Adjust display brightness"
    ),
    "system.keyboard_brightness": ActionPolicy(
        "system.keyboard_brightness", RiskLevel.LOW_IMPACT, "Adjust keyboard brightness"
    ),
}

POLICIES = MappingProxyType(_POLICIES)


def get_policy(action_key: str) -> ActionPolicy:
    """Resolve an allowlisted policy. Unknown actions fail closed."""
    try:
        return POLICIES[action_key]
    except KeyError as error:
        raise PermissionError(
            f"No safety policy exists for action: {action_key}"
        ) from error


def validate_policies() -> list[str]:
    errors = []
    for key, policy in POLICIES.items():
        if key != policy.key:
            errors.append(f"Policy key mismatch: {key}")
        if not policy.description.strip():
            errors.append(f"Policy description is empty: {key}")
    return errors
