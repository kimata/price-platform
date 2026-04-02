"""Local liveness-file helpers."""

from __future__ import annotations

from pathlib import Path

import my_lib.footprint


def update(path: str | Path) -> None:
    my_lib.footprint.update(path)
