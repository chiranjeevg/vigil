"""Load ``VigilConfig`` for a registered project (vigil.yaml on disk or DB JSON)."""

from __future__ import annotations

import json
import os

from sqlalchemy.ext.asyncio import AsyncSession

from vigil.config import VigilConfig, load_config
from vigil.db.models import Project
from vigil.db.repository import ProjectRepository


def _canonical_project_dir(project_path: str) -> str:
    """Stable absolute path for the repo root (used for vigil.yaml and project.path)."""
    expanded = os.path.normpath(os.path.expanduser(project_path))
    try:
        if os.path.isdir(expanded):
            return os.path.normpath(os.path.realpath(expanded))
    except OSError:
        pass
    return expanded


def _align_with_registry(cfg: VigilConfig, canonical_path: str, row: Project | None) -> VigilConfig:
    """Force ``project.path`` (and name/language from DB) to match the registry row.

    DB ``config_json`` or stale YAML can omit ``path`` or point at the wrong directory;
    the registry path is authoritative once a project is selected.
    """
    updates: dict = {"path": canonical_path}
    if row is not None:
        updates["name"] = row.name
        if row.language and row.language != "unknown":
            updates["language"] = row.language
    return cfg.model_copy(update={"project": cfg.project.model_copy(update=updates)})


async def load_vigil_config_for_project_path(project_path: str, db: AsyncSession) -> VigilConfig:
    """Load config for ``project_path`` from ``vigil.yaml`` or stored ``config_json``."""
    repo = ProjectRepository(db)
    canonical = _canonical_project_dir(project_path)
    expanded = os.path.normpath(os.path.expanduser(project_path))
    # Registry rows may use symlink-resolved paths or the user-typed path.
    project = await repo.get_by_path(canonical)
    if project is None:
        project = await repo.get_by_path(project_path)
    if project is None and expanded != canonical:
        project = await repo.get_by_path(expanded)

    yaml_path = os.path.join(canonical, "vigil.yaml")
    if os.path.isfile(yaml_path):
        cfg = load_config(yaml_path)
    elif project and project.config_json:
        cfg = VigilConfig(**json.loads(project.config_json))
    else:
        raise ValueError(f"No vigil.yaml or stored config for {project_path!r}")

    return _align_with_registry(cfg, canonical, project)
