import json

from app.services.diagnostics import run_live_health_checks
from app.services.location import initialize_location


def main() -> None:
    initialize_location()
    print(json.dumps(run_live_health_checks(), indent=2))


if __name__ == "__main__":
    main()
