"""Process-local now-playing event bus shared by music providers and the UI API."""

from collections.abc import Callable
from threading import Lock
from typing import Any

MediaListener = Callable[[dict[str, Any]], None]
_lock = Lock()
_listeners: set[MediaListener] = set()


def publish_now_playing(payload: dict[str, Any]) -> None:
    with _lock:
        listeners = tuple(_listeners)
    for listener in listeners:
        listener(payload)


def subscribe_now_playing(listener: MediaListener) -> Callable[[], None]:
    with _lock:
        _listeners.add(listener)

    def unsubscribe() -> None:
        with _lock:
            _listeners.discard(listener)

    return unsubscribe
