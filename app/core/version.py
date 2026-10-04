"""Application version lookup.

``pyproject.toml`` is the single official version source. This module only
*reads* it — it never defines a version of its own:

1. In a source checkout, ``pyproject.toml`` next to the ``app`` package is
   authoritative (avoids stale metadata from an older editable install).
2. In an installed distribution, the package metadata generated from
   ``pyproject.toml`` is used.
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

_DISTRIBUTION_NAME = "netsentinel"
_UNKNOWN_VERSION = "0.0.0+unknown"
_PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _version_from_pyproject(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    project = data.get("project", {})
    if project.get("name") != _DISTRIBUTION_NAME:
        return None
    value = project.get("version")
    return value if isinstance(value, str) and value else None


@lru_cache(maxsize=1)
def get_version() -> str:
    """Return the NetSentinel version declared in ``pyproject.toml``."""
    from_source = _version_from_pyproject(_PYPROJECT_PATH)
    if from_source is not None:
        return from_source
    try:
        return version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return _UNKNOWN_VERSION
