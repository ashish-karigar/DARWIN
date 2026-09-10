import platform
from functools import lru_cache

from app.system.adapters.linux import LinuxController
from app.system.adapters.macos import MacOSController
from app.system.adapters.windows import WindowsController
from app.system.base import SystemController
from app.system.models import Capability


@lru_cache(maxsize=1)
def get_system_controller() -> SystemController:
    system = platform.system()
    if system == "Darwin":
        return MacOSController()
    if system == "Linux":
        return LinuxController()
    if system == "Windows":
        return WindowsController()
    raise RuntimeError(f"Unsupported operating system: {system}")


def discover_capabilities() -> list[Capability]:
    return get_system_controller().discover()


def capability_map() -> dict[str, Capability]:
    return {capability.key: capability for capability in discover_capabilities()}
