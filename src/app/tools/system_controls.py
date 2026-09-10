import json

from langchain_core.tools import tool

from app.safety import execute_guarded
from app.system.discovery import (
    capability_map,
    discover_capabilities,
    get_system_controller,
)


def _bounded_percent(percent: int) -> int:
    if not 0 <= percent <= 100:
        raise ValueError("Percentage must be between zero and one hundred")
    return percent


@tool
def list_system_controls() -> str:
    """Discover volume, display, keyboard, and audio-focus capabilities."""
    execution = execute_guarded(
        "system.discover",
        "Discover available system controls",
        lambda: [capability.to_dict() for capability in discover_capabilities()],
    )
    return json.dumps(
        execution.value
        if execution.succeeded
        else [{"available": False, "detail": "Capability discovery failed."}]
    )


def _set_control(
    *,
    action_key: str,
    percent: int,
    setter,
    getter,
) -> str:
    percent = _bounded_percent(percent)
    capability = capability_map()[action_key]
    execution = execute_guarded(
        action_key,
        f"Set {action_key.replace('_', ' ').replace('.', ' ')} to {percent} percent",
        lambda: (setter(percent), getter())[1],
        metadata={"target_percent": str(percent)},
    )
    if execution.succeeded:
        return json.dumps(
            {
                "success": True,
                "control": action_key,
                "value_percent": execution.value,
            }
        )
    return json.dumps(
        {
            "success": False,
            "control": action_key,
            "available": capability.available,
            "detail": capability.detail,
        }
    )


@tool
def set_system_volume(percent: int) -> str:
    """Set system output volume from zero to one hundred percent."""
    controller = get_system_controller()
    return _set_control(
        action_key="system.volume",
        percent=percent,
        setter=controller.set_volume,
        getter=controller.get_volume,
    )


@tool
def set_display_brightness(percent: int) -> str:
    """Set display brightness from zero to one hundred percent when supported."""
    controller = get_system_controller()
    return _set_control(
        action_key="system.display_brightness",
        percent=percent,
        setter=controller.set_display_brightness,
        getter=controller.get_display_brightness,
    )


@tool
def set_keyboard_brightness(percent: int) -> str:
    """Set keyboard brightness from zero to one hundred percent when supported."""
    controller = get_system_controller()
    return _set_control(
        action_key="system.keyboard_brightness",
        percent=percent,
        setter=controller.set_keyboard_brightness,
        getter=controller.get_keyboard_brightness,
    )


SYSTEM_CONTROL_TOOLS = [
    list_system_controls,
    set_system_volume,
    set_display_brightness,
    set_keyboard_brightness,
]
