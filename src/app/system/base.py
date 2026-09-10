from abc import ABC, abstractmethod

from app.system.models import Capability


class SystemController(ABC):
    @abstractmethod
    def discover(self) -> list[Capability]:
        raise NotImplementedError

    @abstractmethod
    def get_volume(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def set_volume(self, percent: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_display_brightness(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def set_display_brightness(self, percent: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_keyboard_brightness(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def set_keyboard_brightness(self, percent: int) -> None:
        raise NotImplementedError
