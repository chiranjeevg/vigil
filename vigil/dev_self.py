"""Detect when config targets the Vigil tool's own source tree (editable install).

The daemon should not default to the Vigil development repo when other projects
exist. Opt-in via ``VIGIL_ALLOW_SELF_PROJECT=1`` for contributors who run Vigil
on its own codebase.
"""

from __future__ import annotations

import os
from pathlib import Path

_ALLOW_SELF_ENV = "VIGIL_ALLOW_SELF_PROJECT"


def allow_vigil_self_project() -> bool:
    return os.getenv(_ALLOW_SELF_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def vigil_development_repo_root() -> str | None:
    """If ``vigil`` is imported from a source checkout, return that repository root.

    Returns ``None`` when the package is loaded from ``site-packages`` (normal
    installs), so user repos under ``~/Developer/...`` are never misclassified.
    """
    import vigil

    pkg_init = Path(vigil.__file__).resolve()
    if "site-packages" in pkg_init.parts:
        return None
    # .../vigil/__init__.py -> package dir is parent; repo root is one level up
    repo = pkg_init.parent.parent
    if not (repo / "pyproject.toml").is_file():
        return None
    try:
        return str(repo.resolve())
    except OSError:
        return None


def is_vigil_source_repo_path(path: str) -> bool:
    """True if ``path`` is the Vigil development checkout (editable install)."""
    root = vigil_development_repo_root()
    if not root:
        return False
    try:
        a = os.path.normpath(os.path.realpath(path))
        b = os.path.normpath(os.path.realpath(root))
    except OSError:
        return False
    return a == b
