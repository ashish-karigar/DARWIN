import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentLocation:
    latitude: float
    longitude: float
    label: str


_current_location: CurrentLocation | None = None


def initialize_location() -> CurrentLocation | None:
    global _current_location

    try:
        result = subprocess.run(
            ["CoreLocationCLI", "--json"],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )

        data = json.loads(result.stdout)

        label_parts = [
            data.get("locality"),
            data.get("administrativeArea"),
            data.get("country"),
        ]

        _current_location = CurrentLocation(
            latitude=float(data["latitude"]),
            longitude=float(data["longitude"]),
            label=", ".join(
                part for part in label_parts if part
            ),
        )

    except (subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError):
        _current_location = None

    return _current_location


def get_current_location() -> CurrentLocation | None:
    return _current_location