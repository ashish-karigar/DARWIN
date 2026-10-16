"""Restore optional, pinned third-party training and benchmark workspaces."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "third_party" / "dependencies.json"


def run(*arguments: str, cwd: Path | None = None) -> None:
    subprocess.run(arguments, cwd=cwd, check=True)


def install(dependency: dict[str, str | None]) -> None:
    destination = PROJECT_ROOT / str(dependency["destination"])
    if destination.exists():
        raise RuntimeError(
            f"Refusing to overwrite existing path: {destination}. "
            "Move or remove it explicitly before restoring this dependency."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"Restoring {dependency['name']} at {dependency['commit']}")
    run("git", "clone", "--no-checkout", str(dependency["url"]), str(destination))
    run("git", "checkout", "--detach", str(dependency["commit"]), cwd=destination)

    patch = dependency.get("patch")
    if patch:
        patch_path = PROJECT_ROOT / str(patch)
        apply_arguments = (
            "git",
            "apply",
            "--ignore-space-change",
            "--ignore-whitespace",
        )
        run(*apply_arguments, "--check", str(patch_path), cwd=destination)
        run(*apply_arguments, str(patch_path), cwd=destination)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restore DARWIN's optional external development dependencies."
    )
    parser.add_argument(
        "group",
        choices=("wakeword", "rag", "all"),
        help="Dependency group to restore.",
    )
    arguments = parser.parse_args()

    manifest = json.loads(MANIFEST_PATH.read_text())
    selected = [
        dependency
        for dependency in manifest["dependencies"]
        if arguments.group == "all" or dependency["group"] == arguments.group
    ]
    for dependency in selected:
        install(dependency)


if __name__ == "__main__":
    main()
