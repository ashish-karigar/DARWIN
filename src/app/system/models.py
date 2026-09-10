from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Capability:
    key: str
    available: bool
    provider: str
    detail: str
    permission: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
