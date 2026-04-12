"""Stable per-project paths for Vigil state outside the git working tree."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

MIGRATED_MARKER = ".migrated_from_repo"


def stable_project_hash(project_path: str) -> str:
    """Short stable id for ~/.vigil/state/<hash>/ (not a security boundary)."""
    norm = os.path.normpath(os.path.abspath(project_path))
    return hashlib.sha256(norm.encode()).hexdigest()[:16]


def external_state_dir(project_path: str) -> Path:
    """~/.vigil/state/<hash>/ for iteration logs, task queue, etc."""
    return Path.home() / ".vigil" / "state" / stable_project_hash(project_path)


def migrate_legacy_vigil_state_if_needed(project_path: str, target: Path) -> None:
    """Copy <repo>/.vigil-state into target once, then rename legacy to .vigil-state.migrated."""
    legacy = Path(project_path) / ".vigil-state"
    migrated_marker = target / MIGRATED_MARKER
    if migrated_marker.exists():
        return
    if not legacy.exists() or not legacy.is_dir():
        return
    try:
        if not any(legacy.iterdir()):
            return
    except OSError:
        return

    # External state already populated (e.g. second machine) — do not overwrite
    it_file = target / "iterations.json"
    if it_file.exists():
        try:
            data = json.loads(it_file.read_text(encoding="utf-8"))
            if isinstance(data, list) and len(data) > 0:
                try:
                    migrated_marker.write_text(legacy.as_posix(), encoding="utf-8")
                except OSError:
                    pass
                return
        except (json.JSONDecodeError, OSError):
            pass

    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copytree(legacy, target, dirs_exist_ok=True)
        migrated_marker.write_text(legacy.as_posix(), encoding="utf-8")
        log.info("Migrated Vigil state from %s to %s", legacy, target)
        renamed = legacy.with_name(".vigil-state.migrated")
        try:
            legacy.rename(renamed)
            log.info("Renamed legacy state dir to %s", renamed)
        except OSError as e:
            log.warning("Could not rename legacy .vigil-state: %s", e)
    except OSError as e:
        log.warning("State migration failed (%s); using empty state at %s", e, target)
