"""Resolve daemon ``VigilConfig`` when ``project.path`` is omitted (UI / DB registry)."""

from __future__ import annotations

import logging
import os

from vigil.config import VigilConfig
from vigil.db.repository import ProjectRepository
from vigil.db.session import get_db_manager, init_db
from vigil.dev_self import allow_vigil_self_project, is_vigil_source_repo_path
from vigil.project_config_loader import load_vigil_config_for_project_path

log = logging.getLogger(__name__)


def merge_daemon_overlay(base: VigilConfig, project: VigilConfig) -> VigilConfig:
    """Apply global daemon settings from minimal ``base`` YAML over loaded project config.

    Keeps ``provider``, ``api``, and ``notifications`` from the file next to the
    daemon so users can run one ``vigil.yaml`` for LLM/API settings while
    selecting the working repo in the dashboard.
    """
    return project.model_copy(
        update={
            "provider": base.provider,
            "api": base.api,
            "notifications": base.notifications,
        }
    )


async def resolve_daemon_config_if_empty_project_path(config: VigilConfig) -> VigilConfig:
    """If ``project.path`` is empty, load the first suitable project from the DB registry."""
    if (config.project.path or "").strip():
        return config
    if os.getenv("VIGIL_USE_DATABASE", "false").lower() != "true":
        raise ValueError(
            "vigil.yaml has no project.path. Set it to your repository root, or set "
            "VIGIL_USE_DATABASE=true and register projects in the dashboard, then "
            "select a project there."
        )
    await init_db()
    mgr = get_db_manager()
    if mgr is None:
        raise RuntimeError("Database failed to initialize")

    async with mgr.session() as db:
        repo = ProjectRepository(db)
        active = await repo.get_all_active()
        if not active:
            raise ValueError(
                "No project.path in vigil.yaml and no registered projects in the database. "
                "Open the Vigil dashboard (Setup) to add a project, or set project.path."
            )
        allow_self = allow_vigil_self_project()
        preferred = [p for p in active if not is_vigil_source_repo_path(p.path)]
        if not preferred and allow_self:
            preferred = list(active)
        if not preferred:
            raise ValueError(
                "Only the Vigil tool source repo is registered. Add another project in "
                "the UI, or set VIGIL_ALLOW_SELF_PROJECT=1."
            )
        target = preferred[0]
        try:
            cfg = await load_vigil_config_for_project_path(target.path, db)
        except ValueError as e:
            raise ValueError(f"Could not load project config: {e}") from e

    merged = merge_daemon_overlay(config, cfg)
    log.info(
        "Resolved empty project.path from daemon YAML to registered project %s (%s)",
        target.name,
        target.path,
    )
    return merged
