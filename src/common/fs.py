from __future__ import annotations

import shutil
from pathlib import Path


def clear_directory(path: str | Path) -> Path:
    """Delete all contents of a directory, then recreate it empty."""
    directory = Path(path)
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)
    print(f"Cleared {directory}")
    return directory
