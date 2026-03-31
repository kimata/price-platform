"""Local liveness-file helpers."""

from __future__ import annotations

from pathlib import Path


def update(path: str | Path) -> None:
    footprint = Path(path)
    footprint.parent.mkdir(parents=True, exist_ok=True)
    footprint.touch()
