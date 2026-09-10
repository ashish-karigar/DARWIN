from collections.abc import Callable


_handler: Callable[[str], None] | None = None


def set_status_handler(handler: Callable[[str], None] | None) -> None:
    global _handler
    _handler = handler


def announce_status(message: str) -> None:
    if _handler is not None:
        _handler(message)
    else:
        print(f"DARWIN: {message}")
