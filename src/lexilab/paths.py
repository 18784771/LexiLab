from __future__ import annotations

import os
from pathlib import Path


def project_root(start: Path | None = None) -> Path:
    """Return the nearest directory containing pyproject.toml, else start/cwd."""
    path = Path(start or Path.cwd()).resolve()
    for candidate in (path, *path.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return path


def default_data_dir() -> Path:
    env = os.environ.get("LEXILAB_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()
    root = project_root()
    if (root / "pyproject.toml").is_file():
        return root / "data"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "lexilab"
