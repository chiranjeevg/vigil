"""API routes v2 - Database-backed endpoints for Vigil."""

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Optional

import requests as http_requests
import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from vigil.config import VigilConfig, load_config, save_config
from vigil.db import sqlite_read
from vigil.db.cache import get_cache
from vigil.db.repository import (
    BenchmarkRepository,
    IterationRepository,
    ProjectRepository,
    TaskRepository,
)
from vigil.db.session import get_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_orchestrator: Any = None
_config: VigilConfig | None = None


def set_context(orchestrator: Any, config: VigilConfig) -> None:
    global _orchestrator, _config
    _orchestrator = orchestrator
    _config = config


def _require_orchestrator():
    if _orchestrator is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    return _orchestrator


def _require_config():
    if _config is None:
        raise HTTPException(status_code=503, detail="Config not loaded")
    return _config


async def _load_config_for_project_path(project_path: str, db: AsyncSession) -> VigilConfig:
    """Load VigilConfig for a project directory (vigil.yaml or DB-stored JSON)."""
    repo = ProjectRepository(db)
    project = await repo.get_by_path(project_path)
    config_path = os.path.join(project_path, "vigil.yaml")
    if os.path.isfile(config_path):
        try:
            return load_config(config_path)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to load config: {e}")
    if project and project.config_json:
        try:
            return VigilConfig(**json.loads(project.config_json))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse stored config: {e}")
    raise HTTPException(status_code=404, detail="No vigil.yaml found and no stored config")


def _apply_config_to_orchestrator(project_path: str, new_config: VigilConfig) -> None:
    """Point the running orchestrator at a project (paused)."""
    global _config
    _config = new_config
    if _orchestrator is None:
        return
    _orchestrator._paused = True
    _orchestrator.config = new_config
    _orchestrator._current_iteration = 0
    _orchestrator._daily_count = 0
    _orchestrator._no_improve_streak = 0
    _orchestrator._current_task = None

    from vigil.core.benchmark import BenchmarkRunner
    from vigil.core.code_applier import CodeApplier
    from vigil.core.git_ops import GitManager
    from vigil.core.state import StateManager
    from vigil.core.task_planner import TaskPlanner

    _orchestrator.state = StateManager(project_path)
    _orchestrator.git = GitManager(project_path)
    _orchestrator.bench = BenchmarkRunner(new_config.benchmarks, project_path)
    _orchestrator.planner = TaskPlanner(_orchestrator.state, new_config)
    _orchestrator.applier = CodeApplier(project_path, new_config.project.read_only_paths)
    _orchestrator._paused = True


def _fallback_vigil_config_after_remove() -> None:
    """Load vigil.yaml from cwd or Vigil package parent when no projects remain."""
    global _config
    import vigil

    candidates = [
        Path(os.getcwd()) / "vigil.yaml",
        Path(vigil.__file__).resolve().parent.parent / "vigil.yaml",
    ]
    for p in candidates:
        if p.is_file():
            try:
                cfg = load_config(str(p))
                _apply_config_to_orchestrator(cfg.project.path, cfg)
                log.info("Fell back to config: %s", p)
                return
            except Exception as e:
                log.warning("Fallback config failed (%s): %s", p, e)
    log.warning("No fallback vigil.yaml after project removal")


async def reconcile_startup_project() -> None:
    """On DB-backed startup, switch the daemon to the last active project in the
    registry when the CLI-supplied config points at a path that is not active
    (e.g. it was removed before a restart)."""
    from vigil.db.session import get_db_manager

    mgr = get_db_manager()
    if mgr is None or _config is None:
        return

    cli_path = os.path.normpath(os.path.realpath(_config.project.path))

    async with mgr.session() as db:
        repo = ProjectRepository(db)

        cli_project = await repo.get_by_path(cli_path)
        if cli_project and cli_project.is_active:
            return  # CLI project is already active — nothing to do.

        active = await repo.get_all_active()
        if not active:
            return  # No active projects at all — keep CLI default.

        target = active[0]  # Most recently updated
        try:
            cfg = await _load_config_for_project_path(target.path, db)
        except Exception as e:
            log.warning("Could not load config for %s on startup: %s", target.path, e)
            return

    _apply_config_to_orchestrator(target.path, cfg)
    log.info(
        "Startup reconciliation: switched from %s to active project %s (%s)",
        cli_path,
        target.name,
        target.path,
    )


# ============================================================================
# Status & Control
# ============================================================================

@router.get("/status")
def get_status():
    orch = _require_orchestrator()
    return orch.get_status()


@router.get("/iterations/live")
def get_live_iteration():
    """Return the currently running iteration's live steps, or null if idle."""
    orch = _require_orchestrator()
    return {"live": orch.get_live_iteration()}


@router.post("/start")
def post_start():
    orch = _require_orchestrator()
    if orch._running:
        return {"message": "Already running"}
    import threading
    t = threading.Thread(target=orch.start, daemon=True)
    t.start()
    return {"message": "Started"}


@router.post("/stop")
def post_stop():
    orch = _require_orchestrator()
    orch.stop()
    return {"message": "Stop signal sent"}


@router.post("/pause")
def post_pause():
    orch = _require_orchestrator()
    orch.pause()
    return {"message": "Paused"}


@router.post("/resume")
def post_resume():
    orch = _require_orchestrator()
    orch.resume()
    return {"message": "Resumed"}


# ============================================================================
# Config Endpoints (needed by Settings + Tasks pages)
# ============================================================================

@router.get("/config")
def get_config_endpoint():
    config = _require_config()
    return config.model_dump(mode="json")


class ConfigUpdate(BaseModel):
    project: dict | None = None
    provider: dict | None = None
    tests: dict | None = None
    benchmarks: dict | None = None
    tasks: dict | None = None
    controls: dict | None = None
    notifications: dict | None = None
    api: dict | None = None
    pr: dict | None = None


@router.put("/config")
def update_config(update: ConfigUpdate):
    global _config
    config = _require_config()
    orch = _require_orchestrator()

    data = config.model_dump(mode="json")

    provider_changed = False
    for field in ("project", "provider", "tests", "benchmarks", "tasks", "controls", "notifications", "api", "pr"):
        patch = getattr(update, field, None)
        if patch:
            if field == "provider":
                provider_changed = True
            if field in data and isinstance(data[field], dict):
                data[field].update(patch)
            else:
                data[field] = patch

    try:
        new_config = VigilConfig(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid configuration: {e}")

    old_path = _resolve_project_path(config.project.path)
    new_path = _resolve_project_path(new_config.project.path)
    if old_path != new_path:
        # Saving a different project.path must re-point state/git/planner or the daemon
        # keeps running on the previous directory while vigil.yaml is written elsewhere.
        _apply_config_to_orchestrator(new_path, new_config)
    else:
        _config = new_config
        orch.config = new_config
        from vigil.core.task_planner import TaskPlanner

        orch.planner = TaskPlanner(orch.state, new_config)

    if provider_changed:
        from vigil.providers import create_provider
        try:
            orch.provider = create_provider(new_config.provider)
            log.info("Provider updated to %s", orch.provider.name())
        except Exception as e:
            log.error("Failed to update provider: %s", e)

    config_path = os.path.join(new_config.project.path, "vigil.yaml")
    try:
        save_config(new_config, config_path)
    except Exception:
        pass

    return {"message": "Config updated"}


# ============================================================================
# LLM Model Detection
# ============================================================================

@router.get("/models")
def get_available_models():
    """Auto-detect available LLM models from Ollama and other providers."""
    models = []

    # Detect Ollama models
    config = _config
    ollama_url = "http://localhost:11434"
    if config and config.provider.type == "ollama":
        ollama_url = config.provider.base_url

    try:
        resp = http_requests.get(f"{ollama_url}/api/tags", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            for m in data.get("models", []):
                name = m.get("name", "")
                size = m.get("size", 0)
                size_gb = round(size / (1024**3), 1) if size else None
                models.append({
                    "name": name,
                    "provider": "ollama",
                    "size_gb": size_gb,
                    "family": m.get("details", {}).get("family", ""),
                    "parameter_size": m.get("details", {}).get("parameter_size", ""),
                })
    except Exception:
        pass

    return {
        "models": models,
        "ollama_available": len(models) > 0,
    }


@router.get("/pr/status")
def get_pr_status():
    orch = _require_orchestrator()
    config = _require_config()

    status = {
        "enabled": config.pr.enabled,
        "pr_active": getattr(orch, "_pr_enabled", False),
        "push_enabled": getattr(orch, "_pr_push_enabled", False),
        "strategy": config.pr.strategy,
        "base_branch": config.pr.base_branch,
    }

    if config.pr.enabled and hasattr(orch, "pr_manager") and orch.pr_manager:
        ok, msg = orch.pr_manager.preflight_check()
        status["preflight_ok"] = ok
        status["preflight_message"] = msg
    else:
        status["preflight_ok"] = False
        status["preflight_message"] = "PR workflow not enabled"
        status["push_enabled"] = False

    return status


# ============================================================================
# Project Endpoints (async - database)
# ============================================================================

@router.get("/projects")
async def get_projects(
    scan_filesystem: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Get all active Vigil projects."""
    cache = get_cache()
    cache_key = f"projects:list:{scan_filesystem}"

    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    repo = ProjectRepository(db)

    if scan_filesystem:
        await _scan_and_import_projects(db, repo)

    projects = await repo.get_all_active()
    result = {
        "projects": [
            {
                "id": p.id,
                "name": p.name,
                "path": p.path,
                "language": p.language,
                "total_iterations": p.total_iterations,
                "successful_iterations": p.successful_iterations,
                "last_iteration_at": p.last_iteration_at.isoformat() if p.last_iteration_at else None,
                "is_active": p.is_active,
                "iteration_count": p.total_iterations,
                "has_config": True,
                "has_state": p.total_iterations > 0,
            }
            for p in projects
        ]
    }

    await cache.set(cache_key, result, ttl=10)
    return result


@router.get("/projects/remove")
async def remove_project_get_not_allowed():
    """GET is not supported; use POST or DELETE with JSON body {\"path\": \"...\"}."""
    raise HTTPException(
        status_code=400,
        detail="Removing a project requires POST or DELETE with JSON body "
        '{"path": "/absolute/path/to/project"}.',
    )


async def _scan_and_import_projects(db: AsyncSession, repo: ProjectRepository):
    """Scan common directories for vigil.yaml files and import them."""
    home = os.path.expanduser("~")
    dev_dirs = [
        os.path.join(home, "Developer"),
        os.path.join(home, "Projects"),
        os.path.join(home, "Code"),
        os.path.join(home, "repos"),
    ]

    for dev_dir in dev_dirs:
        if not os.path.isdir(dev_dir):
            continue
        try:
            for item in os.scandir(dev_dir):
                if item.name.startswith(".") or not item.is_dir(follow_symlinks=False):
                    continue
                if os.path.isfile(os.path.join(item.path, "vigil.yaml")):
                    await _check_and_import_project(item.path, db, repo)

                try:
                    for subitem in os.scandir(item.path):
                        if subitem.name.startswith(".") or not subitem.is_dir(follow_symlinks=False):
                            continue
                        if os.path.isfile(os.path.join(subitem.path, "vigil.yaml")):
                            await _check_and_import_project(subitem.path, db, repo)
                except (PermissionError, OSError):
                    pass
        except (PermissionError, OSError):
            pass


async def _check_and_import_project(project_path: str, db: AsyncSession, repo: ProjectRepository):
    """Check if a directory has vigil.yaml and import it."""
    import json as json_module

    if not os.path.isdir(project_path):
        return

    vigil_yaml = os.path.join(project_path, "vigil.yaml")
    if not os.path.exists(vigil_yaml):
        return

    existing = await repo.get_by_path(project_path)
    if existing:
        return

    try:
        with open(vigil_yaml) as f:
            config = yaml.safe_load(f)

        name = config.get("project", {}).get("name", os.path.basename(project_path))
        language = config.get("project", {}).get("language", "unknown")

        iterations_file = os.path.join(project_path, ".vigil-state", "iterations.json")
        iteration_count = 0
        if os.path.exists(iterations_file):
            try:
                with open(iterations_file) as f:
                    iterations = json_module.load(f)
                    iteration_count = len(iterations)
            except Exception:
                pass

        project = await repo.create(
            path=project_path,
            name=name,
            language=language,
            config_json=json_module.dumps(config),
        )
        project.total_iterations = iteration_count
        log.info("Imported project from filesystem: %s", project_path)
    except Exception as e:
        log.warning("Failed to import project %s: %s", project_path, e)


@router.get("/projects/{project_id}")
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)):
    """Get a specific project by ID."""
    repo = ProjectRepository(db)
    project = await repo.get_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "id": project.id,
        "name": project.name,
        "path": project.path,
        "language": project.language,
        "config": json.loads(project.config_json) if project.config_json else None,
        "total_iterations": project.total_iterations,
        "successful_iterations": project.successful_iterations,
        "last_iteration_at": project.last_iteration_at.isoformat() if project.last_iteration_at else None,
    }


class ProjectCreate(BaseModel):
    path: str
    name: str
    language: str = "unknown"
    config: Optional[dict] = None


@router.post("/projects")
async def create_project(req: ProjectCreate, db: AsyncSession = Depends(get_db)):
    """Create or update a project."""
    repo = ProjectRepository(db)
    config_json = json.dumps(req.config) if req.config else None
    project = await repo.upsert(req.path, req.name, req.language, config_json)
    return {"id": project.id, "path": project.path, "name": project.name}


# ============================================================================
# Iteration Endpoints (async - database)
# ============================================================================

@router.get("/projects/{project_id}/iterations")
async def get_iterations(
    project_id: int,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    repo = IterationRepository(db)
    iterations = await repo.get_recent(project_id, limit)
    return {
        "iterations": [
            {
                "id": it.id,
                "iteration": it.iteration_num,
                "task_type": it.task_type,
                "task_description": it.task_description,
                "status": it.status,
                "summary": it.summary,
                "created_at": it.created_at.isoformat(),
            }
            for it in iterations
        ]
    }


@router.get("/projects/{project_id}/iterations/{iteration_num}")
async def get_iteration_detail(
    project_id: int,
    iteration_num: int,
    db: AsyncSession = Depends(get_db),
):
    repo = IterationRepository(db)
    iteration = await repo.get_by_project_and_num(project_id, iteration_num)
    if not iteration:
        raise HTTPException(status_code=404, detail="Iteration not found")
    return {
        "id": iteration.id,
        "iteration": iteration.iteration_num,
        "task_type": iteration.task_type,
        "task_description": iteration.task_description,
        "status": iteration.status,
        "summary": iteration.summary,
        "files_changed": iteration.files_changed or [],
        "diff": iteration.diff or "",
        "commit_hash": iteration.commit_hash or "",
        "llm_response_preview": (iteration.llm_response or "")[:2000],
        "benchmark_data": iteration.benchmark_data or {},
        "duration_seconds": iteration.duration_seconds,
        "created_at": iteration.created_at.isoformat(),
    }


@router.get("/projects/{project_id}/stats")
async def get_project_stats(project_id: int, db: AsyncSession = Depends(get_db)):
    repo = IterationRepository(db)
    return await repo.get_stats(project_id)


# ============================================================================
# Benchmark Endpoints (async - database)
# ============================================================================

@router.get("/projects/{project_id}/benchmarks")
async def get_benchmarks(
    project_id: int,
    name: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
):
    repo = BenchmarkRepository(db)
    benchmarks = await repo.get_recent(project_id, name, limit)
    return {
        "benchmarks": [
            {
                "id": b.id,
                "name": b.name,
                "value": b.value,
                "unit": b.unit,
                "delta_pct": b.delta_pct,
                "is_baseline": b.is_baseline,
                "created_at": b.created_at.isoformat(),
            }
            for b in benchmarks
        ]
    }


# ============================================================================
# Task Endpoints (async - database)
# ============================================================================

@router.get("/projects/{project_id}/tasks")
async def get_tasks(project_id: int, db: AsyncSession = Depends(get_db)):
    repo = TaskRepository(db)
    tasks = await repo.get_pending(project_id)
    return {
        "tasks": [
            {
                "id": t.id,
                "type": t.task_type,
                "description": t.description,
                "target_files": t.target_files or [],
                "priority": t.priority,
                "attempts": t.attempts,
            }
            for t in tasks
        ]
    }


# ============================================================================
# Legacy compatibility (for existing frontend that uses /api/tasks etc.)
# ============================================================================

@router.get("/tasks")
def get_tasks_legacy():
    orch = _require_orchestrator()
    return {"tasks": orch.planner.get_queue()}


class ProjectConfigRequest(BaseModel):
    path: str


@router.post("/config/by-project")
async def get_config_by_project(
    req: ProjectConfigRequest,
    db: AsyncSession = Depends(get_db),
):
    """Load a project's config: vigil.yaml on disk, or DB-stored JSON (same as orchestrator)."""
    path = os.path.normpath(req.path)
    cfg = await _load_config_for_project_path(path, db)
    return cfg.model_dump(mode="json")


@router.put("/config/by-project")
async def update_config_by_project(
    project_path: str,
    update: ConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Merge updates into a project's config; save to vigil.yaml when present and always sync DB row."""
    norm = os.path.normpath(project_path)
    try:
        cfg = await _load_config_for_project_path(norm, db)
    except HTTPException:
        raise

    data = cfg.model_dump(mode="json")
    for field in ("project", "provider", "tests", "benchmarks", "tasks", "controls", "notifications", "api", "pr"):
        patch = getattr(update, field, None)
        if patch:
            if field in data and isinstance(data[field], dict):
                data[field].update(patch)
            else:
                data[field] = patch

    try:
        new_config = VigilConfig(**data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid configuration: {e}")

    yaml_path = os.path.join(norm, "vigil.yaml")
    if os.path.isfile(yaml_path):
        try:
            save_config(new_config, yaml_path)
        except Exception as e:
            log.warning("Failed to save vigil.yaml: %s", e)

    repo = ProjectRepository(db)
    project = await repo.get_by_path(norm)
    if project:
        project.config_json = json.dumps(new_config.model_dump(mode="json"))
        await db.flush()

    global _config
    is_active = _config is not None and os.path.normpath(_config.project.path) == norm
    if is_active and _orchestrator:
        _config = new_config
        _orchestrator.config = new_config
        from vigil.core.task_planner import TaskPlanner

        _orchestrator.planner = TaskPlanner(_orchestrator.state, new_config)

    return {"message": "Config updated", "active": is_active}


@router.get("/git/log")
def get_git_log(n: int = 20):
    orch = _require_orchestrator()
    return {"commits": orch.git.get_log(n=n)}


# ============================================================================
# Setup Endpoints
# ============================================================================

class BrowseRequest(BaseModel):
    path: str | None = None


@router.post("/setup/browse")
def browse_directory(req: BrowseRequest):
    """Browse filesystem for project selection."""
    base = req.path or os.path.expanduser("~")
    expanded = os.path.expanduser(base)

    if not os.path.isdir(expanded):
        raise HTTPException(status_code=400, detail="Invalid directory")

    items = []
    try:
        for name in sorted(os.listdir(expanded)):
            if name.startswith("."):
                continue
            full_path = os.path.join(expanded, name)
            if os.path.isdir(full_path):
                is_git = os.path.isdir(os.path.join(full_path, ".git"))
                items.append({
                    "name": name,
                    "path": full_path,
                    "is_git_repo": is_git,
                })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    parent = os.path.dirname(expanded) if expanded != "/" else None

    return {
        "current": expanded,
        "parent": parent,
        "items": items[:100],
    }


@router.get("/setup/recent")
def get_recent_projects():
    """Get list of recent/common project directories."""
    from vigil.core.analyzer import list_recent_directories
    return {"projects": list_recent_directories()}


class AnalyzeRequest(BaseModel):
    path: str


@router.post("/setup/analyze")
def analyze_project_endpoint(req: AnalyzeRequest):
    """Analyze a project and return suggested configuration."""
    from vigil.core.analyzer import generate_default_config

    if not os.path.isdir(req.path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    try:
        config = generate_default_config(req.path)
        return {
            "config": config,
            "analysis": config.pop("_analysis", {}),
        }
    except Exception as e:
        log.error("Project analysis failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/setup/analyze-with-llm")
def analyze_with_llm_endpoint(req: AnalyzeRequest):
    """Analyze a project using LLM for smarter suggestions."""
    from vigil.core.analyzer import analyze_with_llm

    if not os.path.isdir(req.path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    try:
        return analyze_with_llm(req.path, _orchestrator.provider if _orchestrator else None)
    except Exception as e:
        log.error("LLM analysis failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/setup/suggest-tasks")
def suggest_tasks_endpoint(req: AnalyzeRequest):
    """Analyze a project and suggest prioritized tasks with rationale.

    When a provider is available, uses the deep 4-phase pipeline for
    project-specific, domain-aware suggestions. Falls back to the
    original single-prompt flow on failure.
    """
    if not os.path.isdir(req.path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    provider = _orchestrator.provider if _orchestrator else None

    if provider is not None:
        try:
            from vigil.core.deep_suggest import deep_suggest_tasks

            final: dict | None = None
            p_config = _config.provider if _config else None
            for event_type, data in deep_suggest_tasks(req.path, provider, provider_config=p_config):
                if event_type == "done":
                    final = data
            if final is not None:
                return final
            log.warning("Deep suggest pipeline returned no result, falling back to basic")
        except Exception as e:
            log.warning("Deep suggest failed, falling back to basic: %s", e)

    from vigil.core.analyzer import suggest_tasks_for_project

    try:
        return suggest_tasks_for_project(req.path, provider)
    except Exception as e:
        log.error("Task suggestion failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/setup/analyze-stream")
def analyze_stream_endpoint(req: AnalyzeRequest):
    """SSE stream of analysis progress — logs, scan results, config, task suggestions, LLM output."""
    from vigil.core.analyzer import analyze_project_streaming

    if not os.path.isdir(req.path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    provider = _orchestrator.provider if _orchestrator else None

    def event_generator():
        for event_type, data in analyze_project_streaming(req.path, provider):
            payload = json.dumps({"type": event_type, "data": data})
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/setup/deep-suggest-stream")
def deep_suggest_stream_endpoint(req: AnalyzeRequest):
    """SSE stream of deep analysis progress — 4-phase pipeline with live updates."""
    from vigil.core.deep_suggest import deep_suggest_tasks

    if not os.path.isdir(req.path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    provider = _orchestrator.provider if _orchestrator else None
    if provider is None:
        raise HTTPException(status_code=400, detail="No LLM provider configured — deep analysis requires one")

    p_config = _config.provider if _config else None

    def event_generator():
        for event_type, data in deep_suggest_tasks(req.path, provider, provider_config=p_config):
            payload = json.dumps({"type": event_type, "data": data})
            yield f"data: {payload}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


class ProjectSwitchRequest(BaseModel):
    path: str


@router.post("/projects/switch")
async def switch_project(req: ProjectSwitchRequest, db: AsyncSession = Depends(get_db)):
    """Fast project switch — loads existing config, skips analysis."""
    project_path = req.path
    if not os.path.isdir(project_path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    try:
        new_config = await _load_config_for_project_path(project_path, db)
        _apply_config_to_orchestrator(project_path, new_config)
    except HTTPException:
        raise
    except Exception as e:
        log.error("Failed to switch project: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to switch: {e}")

    log.info("Switched to project: %s", project_path)

    cache = get_cache()
    cache.invalidate_pattern("projects")

    return {
        "message": "Switched",
        "project_name": new_config.project.name,
        "project_path": project_path,
    }


@router.post("/projects/remove")
@router.delete("/projects/remove")
async def remove_project(req: ProjectSwitchRequest, db: AsyncSession = Depends(get_db)):
    """Remove a project from Vigil (soft-delete in DB). Does not delete files on disk."""
    global _orchestrator

    path = os.path.normpath(req.path)
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    repo = ProjectRepository(db)
    project = await repo.get_by_path(path)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found in Vigil")
    if not project.is_active:
        raise HTTPException(status_code=400, detail="Project already removed")

    was_current = _config is not None and os.path.normpath(_config.project.path) == path

    await repo.deactivate_by_path(path)

    cache = get_cache()
    cache.invalidate_pattern("projects")

    if was_current and _orchestrator is not None:
        _orchestrator._running = False
        _orchestrator._paused = True

        remaining = await repo.get_all_active()
        if remaining:
            nxt = remaining[0]
            try:
                cfg = await _load_config_for_project_path(nxt.path, db)
                _apply_config_to_orchestrator(nxt.path, cfg)
                log.info("After remove, switched to: %s", nxt.path)
            except HTTPException as e:
                log.warning("Could not switch to next project: %s", e.detail)
                _fallback_vigil_config_after_remove()
        else:
            _fallback_vigil_config_after_remove()

    return {
        "message": "Removed",
        "path": path,
        "switched_to": _config.project.path if _config else None,
    }


class SetupApply(BaseModel):
    config: dict
    save_to_project: bool = True


@router.post("/setup/apply")
async def apply_setup(req: SetupApply, db: AsyncSession = Depends(get_db)):
    """Apply configuration and switch to a project."""
    global _config, _orchestrator

    try:
        new_config = VigilConfig(**req.config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid configuration: {e}")

    project_path = new_config.project.path

    # Initialize git if needed
    git_dir = os.path.join(project_path, ".git")
    if not os.path.isdir(git_dir):
        log.info("Initializing git repository in %s", project_path)
        try:
            subprocess.run(["git", "init"], cwd=project_path, check=True, capture_output=True)
            subprocess.run(["git", "add", "-A"], cwd=project_path, check=False, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", "Initial commit (Vigil setup)"],
                cwd=project_path, check=False, capture_output=True,
            )
        except Exception as e:
            log.warning("Failed to initialize git: %s", e)

    # Save config to project
    if req.save_to_project:
        config_path = os.path.join(project_path, "vigil.yaml")
        try:
            save_config(new_config, config_path)
            log.info("Saved config to %s", config_path)
        except Exception as e:
            log.warning("Failed to save config: %s", e)

    # Upsert project in database
    repo = ProjectRepository(db)
    project = await repo.upsert(
        path=project_path,
        name=new_config.project.name,
        language=new_config.project.language,
        config_json=json.dumps(req.config),
    )

    _config = new_config

    # Reinitialize orchestrator - pause instead of stop to prevent process exit
    if _orchestrator is not None:
        _orchestrator._paused = True
        import time
        time.sleep(0.3)

        _orchestrator.config = new_config
        _orchestrator._current_iteration = 0
        _orchestrator._daily_count = 0
        _orchestrator._no_improve_streak = 0
        _orchestrator._current_task = None

        from vigil.core.benchmark import BenchmarkRunner
        from vigil.core.code_applier import CodeApplier
        from vigil.core.git_ops import GitManager
        from vigil.core.state import StateManager
        from vigil.core.task_planner import TaskPlanner

        try:
            _orchestrator.state = StateManager(project_path)
            _orchestrator.git = GitManager(project_path)
            _orchestrator.bench = BenchmarkRunner(new_config.benchmarks, project_path)
            _orchestrator.planner = TaskPlanner(_orchestrator.state, new_config)
            _orchestrator.applier = CodeApplier(project_path, new_config.project.read_only_paths)
            _orchestrator._paused = True
            log.info("Orchestrator reinitialized for project: %s", project_path)
        except Exception as e:
            log.error("Failed to reinitialize orchestrator: %s", e)
            raise HTTPException(status_code=500, detail=f"Failed to initialize project: {e}")

    # Invalidate cache
    cache = get_cache()
    cache.invalidate_pattern("projects")

    return {
        "message": "Configuration applied",
        "project_id": project.id,
        "path": project_path,
    }


@router.get("/setup/defaults")
def get_default_config():
    """Get default configuration values for reference."""
    from vigil.config import (
        BenchmarksConfig,
        ControlsConfig,
        ProjectConfig,
        ProviderConfig,
        TasksConfig,
        TestsConfig,
    )
    return {
        "project": ProjectConfig(path="/path/to/project").model_dump(),
        "provider": ProviderConfig().model_dump(),
        "tests": TestsConfig().model_dump(),
        "benchmarks": BenchmarksConfig().model_dump(),
        "tasks": TasksConfig().model_dump(),
        "controls": ControlsConfig().model_dump(),
    }


# ============================================================================
# Iteration/stats endpoints — StateManager (file) with SQLite fallback
# ============================================================================

def _resolve_project_path(path: str) -> str:
    """Normalize path so UI project picks match .vigil-state and DB projects.path."""
    p = os.path.normpath(os.path.expanduser(path))
    if os.path.isdir(p):
        try:
            return os.path.realpath(p)
        except OSError:
            pass
    return p


def _get_state_manager(project_path: str | None = None):
    from vigil.core.state import StateManager

    path = project_path or (_config.project.path if _config else None)
    if not path:
        return None
    return StateManager(_resolve_project_path(path))


def _resolved_path_for_db(project_path: str | None) -> str | None:
    if project_path:
        return _resolve_project_path(project_path)
    if _config:
        return _resolve_project_path(_config.project.path)
    return None


@router.get("/iterations")
def get_iterations_endpoint(
    limit: int = 25,
    offset: int = 0,
    status: str | None = None,
    project_path: str | None = None,
    order: str = "desc",
):
    """Paginated iteration summaries. File state first; SQLite fallback if empty (path mismatch / DB-only)."""
    lim = max(1, min(100, limit))
    off = max(0, offset)
    status_filter = None
    if status in ("success", "failed"):
        status_filter = status
    sort_order = "asc" if order == "asc" else "desc"

    sm = _get_state_manager(project_path)
    summaries: list = []
    total = 0
    if sm:
        summaries, total = sm.iteration_summaries_page(off, lim, status_filter, sort_order)

    if total > 0:
        return {
            "iterations": summaries,
            "total": total,
            "offset": off,
            "limit": lim,
            "has_more": off + len(summaries) < total,
        }

    resolved = _resolved_path_for_db(project_path)
    if resolved:
        db_page = sqlite_read.iteration_summaries_page(
            resolved, off, lim, status_filter, sort_order
        )
        if db_page is not None:
            summaries, total = db_page
            return {
                "iterations": summaries,
                "total": total,
                "offset": off,
                "limit": lim,
                "has_more": off + len(summaries) < total,
            }

    return {
        "iterations": [],
        "total": 0,
        "offset": off,
        "limit": lim,
        "has_more": False,
    }


@router.get("/iterations/{iteration_num}")
def get_iteration_detail_endpoint(iteration_num: int, project_path: str | None = None):
    it = None
    sm = _get_state_manager(project_path)
    if sm:
        it = sm.get_iteration(iteration_num)
    if not it:
        resolved = _resolved_path_for_db(project_path)
        if resolved:
            it = sqlite_read.iteration_detail(resolved, iteration_num)

    if not it:
        raise HTTPException(status_code=404, detail="Iteration not found")

    return {
        "iteration": it.get("iteration"),
        "task_type": it.get("task_type", ""),
        "task_description": it.get("task_description", ""),
        "status": it.get("status", ""),
        "summary": it.get("summary", ""),
        "benchmark_data": it.get("benchmark_data", {}),
        "timestamp": it.get("timestamp", ""),
        "duration_ms": it.get("duration_ms", 0),
        "steps": it.get("steps", []),
        "files_changed": it.get("files_changed", []),
        "diff": it.get("diff", ""),
        "commit_hash": it.get("commit_hash", ""),
        "llm_response": it.get("llm_response", it.get("llm_response_preview", "")),
        "llm_prompt_system": it.get("llm_prompt_system", ""),
        "llm_prompt_user": it.get("llm_prompt_user", ""),
        "llm_tokens": it.get("llm_tokens", 0),
        "llm_duration_s": it.get("llm_duration_s", 0),
        "changes_detail": it.get("changes_detail", []),
        "test_output": it.get("test_output", ""),
        "branch_name": it.get("branch_name", ""),
        "provider_name": it.get("provider_name", ""),
    }


@router.get("/stats")
def get_stats_endpoint(project_path: str | None = None):
    sm = _get_state_manager(project_path)
    if sm:
        st = sm.get_stats()
        if st.get("total_iterations", 0) > 0:
            return st

    resolved = _resolved_path_for_db(project_path)
    if resolved:
        db_stats = sqlite_read.stats_for_project(resolved)
        if db_stats and db_stats.get("total_iterations", 0) > 0:
            return db_stats

    if sm:
        return sm.get_stats()
    return {
        "total_iterations": 0,
        "successes": 0,
        "failures": 0,
        "success_rate": 0,
        "coverage_trend": [],
        "llm_tokens_total": 0,
        "duration_ms_total": 0,
    }
