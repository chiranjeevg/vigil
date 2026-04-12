import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from vigil.config import VigilConfig, load_config, save_config

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_orchestrator: Any = None
_config: VigilConfig | None = None


class Context:
    def __init__(self, orchestrator: Any, config: VigilConfig):
        self.orchestrator = orchestrator
        self.config = config

_context: Context | None = None


def set_context(orchestrator: Any, config: VigilConfig) -> None:
    """Wire the running orchestrator into the API.

    Keep ``_orchestrator`` and ``_config`` in sync with ``_context`` so setup routes
    that read globals (e.g. ``/setup/llm-status``) match ``routes_v2`` behaviour.
    Previously only ``_context`` was set, leaving ``_orchestrator`` permanently None.
    """
    global _context, _orchestrator, _config
    _orchestrator = orchestrator
    _config = config
    _context = Context(orchestrator, config)


def get_orchestrator():
    if _context is None:
        raise HTTPException(status_code=503, detail="Orchestrator not initialized")
    return _context.orchestrator


def get_config():
    if _context is None:
        raise HTTPException(status_code=503, detail="Config not loaded")
    return _context.config


_require_orchestrator = get_orchestrator
_require_config = get_config


def _resolve_project_path(path: str) -> str:
    """Normalize path so UI picks match .vigil-state on disk."""
    p = os.path.normpath(os.path.expanduser(path))
    if os.path.isdir(p):
        try:
            return os.path.realpath(p)
        except OSError:
            pass
    return p


def _apply_config_to_orchestrator(project_path: str, new_config: VigilConfig) -> None:
    """Point the running orchestrator at a project directory (paused, counters reset)."""
    global _config
    _config = new_config
    if _context is None:
        return
    _context.config = new_config
    orch = _context.orchestrator
    orch._paused = True
    orch.config = new_config
    orch._current_iteration = 0
    orch._daily_count = 0
    orch._no_improve_streak = 0
    orch._current_task = None

    from vigil.core.benchmark import BenchmarkRunner
    from vigil.core.code_applier import CodeApplier
    from vigil.core.context_engine import ContextEngine
    from vigil.core.git_ops import GitManager
    from vigil.core.merge_queue import MergeQueue
    from vigil.core.state import StateManager
    from vigil.core.task_planner import TaskPlanner
    from vigil.core.worktree import WorktreeManager

    ro = getattr(new_config.project, "read_only_paths", None) or []
    orch.state = StateManager(project_path)
    orch.git = GitManager(project_path)
    orch.bench = BenchmarkRunner(new_config.benchmarks, project_path)
    orch.planner = TaskPlanner(orch.state, new_config)
    orch.applier = CodeApplier(project_path, ro)
    orch.context_engine = ContextEngine(new_config)
    orch.worktree_mgr = WorktreeManager(project_path)
    orch.merge_queue = MergeQueue(
        project_path,
        new_config.controls.work_branch,
        base_if_missing=new_config.pr.base_branch,
    )
    orch._paused = True
    orch.apply_pr_config_from_config()


def _normalize_project_key(path: str) -> str:
    """Stable key for comparing project paths (realpath when possible)."""
    try:
        return os.path.normpath(os.path.realpath(path))
    except OSError:
        return os.path.normpath(os.path.expanduser(path))


def _removed_projects_file() -> str:
    return os.path.join(os.path.expanduser("~"), ".vigil", "removed_projects.json")


def _load_removed_project_paths() -> set[str]:
    """Paths hidden from the sidebar when using file-backed API (no DB registry)."""
    fp = _removed_projects_file()
    if not os.path.isfile(fp):
        return set()
    try:
        data = json.loads(Path(fp).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            return set()
        return {_normalize_project_key(p) for p in data if isinstance(p, str)}
    except (OSError, json.JSONDecodeError, TypeError):
        return set()


def _save_removed_project_paths(paths: set[str]) -> None:
    d = os.path.dirname(_removed_projects_file())
    os.makedirs(d, mode=0o700, exist_ok=True)
    with open(_removed_projects_file(), "w", encoding="utf-8") as f:
        json.dump(sorted(paths), f, indent=2)


def _hide_project_path(path: str) -> None:
    key = _normalize_project_key(path)
    s = _load_removed_project_paths()
    s.add(key)
    _save_removed_project_paths(s)


def _fallback_vigil_config_after_remove() -> None:
    """Load ``vigil.yaml`` from cwd when no visible projects remain.

    Does not load the Vigil package tree's ``vigil.yaml`` (would bind the daemon
    to the tool source repo).
    """
    global _config
    from vigil.dev_self import allow_vigil_self_project, is_vigil_source_repo_path

    candidates = [Path(os.getcwd()) / "vigil.yaml"]
    for p in candidates:
        if p.is_file():
            try:
                cfg = load_config(str(p))
                if is_vigil_source_repo_path(cfg.project.path) and not allow_vigil_self_project():
                    log.warning(
                        "Skipping fallback %s — Vigil tool source repo; set VIGIL_ALLOW_SELF_PROJECT=1 to use it",
                        p,
                    )
                    continue
                _apply_config_to_orchestrator(cfg.project.path, cfg)
                log.info("Fell back to config after remove: %s", p)
                return
            except Exception as e:
                log.warning("Fallback config failed (%s): %s", p, e)
    log.warning("No fallback vigil.yaml after project removal")


@router.get("/status")
def get_status():
    orch = _require_orchestrator()
    return orch.get_status()


@router.get("/pr/status")
def get_pr_status():
    """Live PR / git / gh preflight (same as database-backed API)."""
    from vigil.api.pr_status import build_pr_status_payload

    orch = _require_orchestrator()
    config = get_config()
    return build_pr_status_payload(orch, config)


@router.get("/progress")
def get_progress(last_n: int = 20):
    orch = _require_orchestrator()
    return {"progress": orch.state.get_progress_summary(last_n=last_n)}


@router.get("/benchmarks")
def get_benchmarks(last_n: int = 10):
    orch = _require_orchestrator()
    return {"benchmarks": orch.state.get_recent_benchmarks(last_n=last_n)}


@router.get("/coverage")
def get_coverage():
    config = get_config()
    return {
        "enabled": config.tests.coverage.enabled,
        "target": config.tests.coverage.target,
        "format": config.tests.coverage.format,
    }


@router.get("/tasks")
def get_tasks():
    orch = _require_orchestrator()
    return {"tasks": orch.planner.get_queue()}


@router.get("/config")
def get_config_endpoint():
    config = get_config()
    return config.model_dump(mode="json")


class ProviderTestBody(BaseModel):
    provider: dict


@router.post("/provider/test-connection")
def test_provider_connection(body: ProviderTestBody):
    """Minimal LLM round-trip using the given provider block (e.g. unsaved Settings draft)."""
    from vigil.api.provider_test import run_provider_connectivity_test

    return run_provider_connectivity_test(body.provider)


@router.get("/models")
def get_available_models(
    ollama_base_url: str | None = None,
    openai_base_url: str | None = None,
):
    """List models from Ollama ``/api/tags`` and OpenAI-compatible ``/v1/models``.

    Optional query params let Settings use **draft** base URLs before save.
    """
    from vigil.api.models_discovery import collect_models_for_request

    return collect_models_for_request(_config, ollama_base_url, openai_base_url)


@router.get("/git/log")
def get_git_log(n: int = 20):
    orch = _require_orchestrator()
    return {"commits": orch.git.get_log(n=n)}


@router.get("/iterations/live")
def get_live_iteration():
    """Return the currently running iteration's live steps, or null if idle."""
    orch = _require_orchestrator()
    return {"live": orch.get_live_iteration()}


@router.get("/iterations")
def get_iterations(
    limit: int = 25,
    offset: int = 0,
    status: str | None = None,
    project_path: str | None = None,
    order: str = "desc",
):
    from vigil.core.state import StateManager

    config = _require_config()
    base = _resolve_project_path(config.project.path)
    target = _resolve_project_path(project_path) if project_path else base
    sm = StateManager(target)
    lim = max(1, min(100, limit))
    off = max(0, offset)
    status_filter = status if status in ("success", "failed") else None
    sort_order = "asc" if order == "asc" else "desc"
    summaries, total = sm.iteration_summaries_page(off, lim, status_filter, sort_order)
    return {
        "iterations": summaries,
        "total": total,
        "offset": off,
        "limit": lim,
        "has_more": off + len(summaries) < total,
    }


@router.get("/iterations/{iteration_num}")
def get_iteration_detail(iteration_num: int, project_path: str | None = None):
    """Get detailed information about a specific iteration."""
    from vigil.core.state import StateManager

    config = _require_config()
    base = _resolve_project_path(config.project.path)
    target = _resolve_project_path(project_path) if project_path else base
    sm = StateManager(target)
    iteration = sm.get_iteration(iteration_num)
    if not iteration:
        raise HTTPException(status_code=404, detail="Iteration not found")

    files_changed = iteration.get("files_changed", [])
    diff = iteration.get("diff", "")
    commit_hash = iteration.get("commit_hash", "")

    if commit_hash and not diff:
        try:
            from vigil.core.git_ops import GitManager

            git = GitManager(target)
            diff = git.get_commit_diff(commit_hash)
            files_changed = git.get_commit_files(commit_hash)
        except Exception as e:
            log.error(f"Error fetching commit details: {e}")

    return {
        **iteration,
        "files_changed": files_changed,
        "diff": diff,
        "commit_hash": commit_hash,
    }


@router.get("/stats")
def get_stats(project_path: str | None = None):
    from vigil.core.state import StateManager

    config = _require_config()
    base = _resolve_project_path(config.project.path)
    target = _resolve_project_path(project_path) if project_path else base
    sm = StateManager(target)
    return sm.get_stats()


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
    for field in (
        "project",
        "provider",
        "tests",
        "benchmarks",
        "tasks",
        "controls",
        "notifications",
        "api",
        "pr",
    ):
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
        raise HTTPException(status_code=400, detail=str(e))

    if not (new_config.project.path or "").strip():
        raise HTTPException(
            status_code=400,
            detail="project.path is empty. Select a project directory in Settings before saving.",
        )

    old_path = _resolve_project_path(config.project.path)
    new_path = _resolve_project_path(new_config.project.path)
    if old_path != new_path:
        _apply_config_to_orchestrator(new_path, new_config)
    else:
        _config = new_config
        if _context is not None:
            _context.config = new_config
        orch.config = new_config
        from vigil.core.task_planner import TaskPlanner

        orch.planner = TaskPlanner(orch.state, new_config)
        orch.apply_pr_config_from_config()

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


class ProjectPathBody(BaseModel):
    path: str


@router.post("/config/by-project")
def get_config_by_project(req: ProjectPathBody):
    """Load vigil.yaml for any registered project path (file-backed API)."""
    path = _resolve_project_path(req.path)
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Invalid directory")
    yaml_path = os.path.join(path, "vigil.yaml")
    if not os.path.isfile(yaml_path):
        raise HTTPException(status_code=404, detail="No vigil.yaml in project")
    try:
        cfg = load_config(yaml_path)
        return cfg.model_dump(mode="json")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/config/by-project")
def update_config_by_project(project_path: str, update: ConfigUpdate):
    """Update another project's vigil.yaml without switching the active daemon."""
    global _config
    norm = _resolve_project_path(project_path)
    yaml_path = os.path.join(norm, "vigil.yaml")
    if not os.path.isfile(yaml_path):
        raise HTTPException(status_code=404, detail="No vigil.yaml")
    try:
        cfg = load_config(yaml_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    data = cfg.model_dump(mode="json")
    provider_changed = False
    for field in (
        "project",
        "provider",
        "tests",
        "benchmarks",
        "tasks",
        "controls",
        "notifications",
        "api",
        "pr",
    ):
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
        raise HTTPException(status_code=400, detail=str(e))

    if not (new_config.project.path or "").strip():
        raise HTTPException(
            status_code=400,
            detail="project.path is empty. Select a project directory before saving.",
        )

    active = _require_config()
    is_active = _resolve_project_path(active.project.path) == norm

    if is_active:
        # Same as PUT /config
        orch = _require_orchestrator()
        old_path = _resolve_project_path(active.project.path)
        new_path = _resolve_project_path(new_config.project.path)
        if old_path != new_path:
            _apply_config_to_orchestrator(new_path, new_config)
        else:
            _config = new_config
            if _context is not None:
                _context.config = new_config
            orch.config = new_config
            from vigil.core.task_planner import TaskPlanner

            orch.planner = TaskPlanner(orch.state, new_config)
            orch.apply_pr_config_from_config()

        if provider_changed:
            from vigil.providers import create_provider

            try:
                orch.provider = create_provider(new_config.provider)
            except Exception as e:
                log.error("Failed to update provider: %s", e)

    try:
        save_config(new_config, yaml_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"message": "Config updated", "active": is_active}


@router.post("/projects/switch")
def switch_project(req: ProjectPathBody):
    """Point the daemon at another project (loads vigil.yaml from disk)."""
    path = _resolve_project_path(req.path)
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Invalid directory")
    yaml_path = os.path.join(path, "vigil.yaml")
    if not os.path.isfile(yaml_path):
        raise HTTPException(status_code=404, detail="No vigil.yaml")
    try:
        new_config = load_config(yaml_path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    _apply_config_to_orchestrator(path, new_config)
    if _context is not None:
        orch = _context.orchestrator
        from vigil.providers import create_provider

        try:
            orch.provider = create_provider(new_config.provider)
        except Exception as e:
            log.error("Failed to update provider: %s", e)

    try:
        save_config(new_config, yaml_path)
    except Exception:
        pass

    return {
        "message": "Switched",
        "project_name": new_config.project.name,
        "project_path": path,
    }


class TaskCreate(BaseModel):
    id: str
    description: str
    files: list[str] = []
    priority: int = 5
    instructions: str = ""


@router.post("/tasks")
def add_task(task: TaskCreate):
    orch = _require_orchestrator()
    orch.planner.add_task(task.model_dump())
    return {"message": "Task added", "task_id": task.id}


@router.delete("/tasks/{task_id}")
def remove_task(task_id: str):
    orch = _require_orchestrator()
    orch.planner.remove_task(task_id)
    return {"message": f"Task {task_id} removed"}


class TaskReorder(BaseModel):
    task_ids: list[str]


@router.put("/tasks/reorder")
def reorder_tasks(body: TaskReorder):
    orch = _require_orchestrator()
    orch.planner.reorder_tasks(body.task_ids)
    return {"message": "Tasks reordered"}


# ============================================================
# Project Setup / Wizard Endpoints
# ============================================================

class BrowseRequest(BaseModel):
    path: str | None = None


@router.post("/setup/browse")
def browse_directories(req: BrowseRequest):
    """Browse directories for project selection."""

    base = req.path or os.path.expanduser("~")

    if not os.path.isdir(base):
        raise HTTPException(status_code=400, detail="Invalid directory path")

    try:
        items = []
        for name in os.listdir(base):
            if name.startswith("."):
                continue
            full_path = os.path.join(base, name)
            if os.path.isdir(full_path):
                is_git = os.path.isdir(os.path.join(full_path, ".git"))
                items.append({
                    "name": name,
                    "path": full_path,
                    "is_git_repo": is_git,
                })

        items.sort(key=lambda x: x["name"])
        parent = os.path.dirname(base) if base != "/" else None

        return {
            "current": base,
            "parent": parent,
            "items": items[:100],
        }
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")


@router.get("/setup/recent")
def get_recent_projects():
    """Get list of recent/common project directories."""
    from vigil.core.analyzer import list_recent_directories
    return {"projects": list_recent_directories()}


@router.get("/projects")
def get_vigil_projects():
    """Get list of projects that have been configured with Vigil.

    When not using the DB registry, paths listed in ``~/.vigil/removed_projects.json``
    are hidden from this list (Remove from sidebar does not delete files).
    """
    removed = _load_removed_project_paths()
    projects = _discover_vigil_projects_list()
    filtered = [
        p for p in projects
        if _normalize_project_key(p["path"]) not in removed
    ]
    return {"projects": filtered}


class ProjectPathRequest(BaseModel):
    path: str


@router.get("/projects/remove")
def remove_project_get_not_allowed():
    """GET is not supported — use POST or DELETE with a JSON body."""
    raise HTTPException(
        status_code=405,
        detail='Use POST or DELETE with JSON body {"path": "/absolute/path/to/project"}',
    )


@router.post("/projects/remove")
@router.delete("/projects/remove")
def remove_project_from_sidebar(req: ProjectPathRequest):
    """Hide a project from the sidebar. Does not delete files on disk.

    File-backed mode stores hidden paths in ``~/.vigil/removed_projects.json``.
    If the removed project was the active daemon project, switches to another
    visible project or falls back to a local ``vigil.yaml``.
    """
    path = os.path.normpath(os.path.expanduser(req.path))
    if not os.path.isdir(path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    key = _normalize_project_key(path)
    _hide_project_path(path)

    was_current = (
        _config is not None
        and _normalize_project_key(_config.project.path) == key
    )

    if was_current and _context is not None:
        orch = _context.orchestrator
        orch._running = False
        orch._paused = True

        removed = _load_removed_project_paths()
        candidates = _discover_vigil_projects_list()
        filtered = [
            p for p in candidates
            if _normalize_project_key(p["path"]) not in removed
        ]
        for p in filtered:
            nxt = p["path"]
            yaml_path = os.path.join(nxt, "vigil.yaml")
            if not os.path.isfile(yaml_path):
                continue
            try:
                new_config = load_config(yaml_path)
                _apply_config_to_orchestrator(nxt, new_config)
                from vigil.providers import create_provider

                orch = _context.orchestrator
                orch.provider = create_provider(new_config.provider)
                log.info("After remove, switched daemon to: %s", nxt)
                return {
                    "message": "Removed",
                    "path": path,
                    "switched_to": nxt,
                }
            except Exception as e:
                log.warning("Could not switch to %s after remove: %s", nxt, e)

        _fallback_vigil_config_after_remove()
        if _context is not None and _config is not None:
            from vigil.providers import create_provider

            try:
                _context.orchestrator.provider = create_provider(_config.provider)
            except Exception as e:
                log.error("Failed to update provider after fallback: %s", e)

    return {
        "message": "Removed",
        "path": path,
        "switched_to": _config.project.path if _config else None,
    }


@lru_cache(maxsize=100)
def _check_project_cached(project_path: str, json_module: Any) -> dict | None:
    """Cached check for Vigil project status."""
    if not os.path.isdir(project_path):
        return None

    has_vigil_config = os.path.exists(os.path.join(project_path, "vigil.yaml"))
    has_vigil_state = os.path.isdir(os.path.join(project_path, ".vigil-state"))

    if not (has_vigil_config or has_vigil_state):
        return None

    iterations_file = os.path.join(project_path, ".vigil-state", "iterations.json")
    iteration_count = 0
    if os.path.exists(iterations_file):
        try:
            with open(iterations_file) as f:
                iterations = json_module.load(f)
                iteration_count = len(iterations)
        except Exception:
            pass

    return {
        "name": os.path.basename(project_path),
        "path": project_path,
        "has_config": has_vigil_config,
        "has_state": has_vigil_state,
        "iteration_count": iteration_count,
    }


def _discover_vigil_projects_list() -> list[dict]:
    """Scan well-known dev directories for Vigil projects (unfiltered)."""
    import json as json_module

    projects: list[dict] = []
    home = os.path.expanduser("~")
    dev_dirs = [
        os.path.join(home, "Developer"),
        os.path.join(home, "Projects"),
        os.path.join(home, "Code"),
        os.path.join(home, "repos"),
        os.path.join(home, "work"),
    ]

    for dev_dir in dev_dirs:
        if not os.path.isdir(dev_dir):
            continue
        try:
            for item in os.listdir(dev_dir):
                if item.startswith("."):
                    continue
                project_path = os.path.join(dev_dir, item)

                proj = _check_project_cached(project_path, json_module)
                if proj:
                    projects.append(proj)
                elif os.path.isdir(project_path):
                    try:
                        for subitem in os.listdir(project_path):
                            if subitem.startswith("."):
                                continue
                            sub_path = os.path.join(project_path, subitem)
                            sub_proj = _check_project_cached(sub_path, json_module)
                            if sub_proj:
                                projects.append(sub_proj)
                    except PermissionError:
                        pass
        except PermissionError:
            pass

    projects.sort(key=lambda p: p["iteration_count"], reverse=True)
    return projects


# ---------------------------------------------------------------------------
# Goals — CRUD for user-defined forward-work goals
# ---------------------------------------------------------------------------

class GoalCreate(BaseModel):
    id: str
    description: str
    priority: int = 1
    context_files: list[str] = []
    context_docs: list[str] = []
    issue_ref: str | None = None


@router.get("/goals")
def get_goals():
    """Return the current goals list from the active project's config."""
    cfg = _require_config()
    return {"goals": [g.model_dump() for g in cfg.goals.current]}


@router.post("/goals")
def add_goal(goal: GoalCreate):
    """Append a new goal to the active project's config and persist it."""
    cfg = _require_config()
    from vigil.config import GoalItem

    # Prevent duplicate ids
    existing_ids = {g.id for g in cfg.goals.current}
    if goal.id in existing_ids:
        raise HTTPException(
            status_code=409,
            detail=f"Goal with id '{goal.id}' already exists",
        )

    new_goal = GoalItem(**goal.model_dump())
    cfg.goals.current.append(new_goal)
    _persist_config(cfg)
    return {"goal": new_goal.model_dump()}


@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: str):
    """Remove a goal by id and persist the updated config."""
    cfg = _require_config()
    original = len(cfg.goals.current)
    cfg.goals.current = [g for g in cfg.goals.current if g.id != goal_id]
    if len(cfg.goals.current) == original:
        raise HTTPException(status_code=404, detail=f"Goal '{goal_id}' not found")
    _persist_config(cfg)
    return {"deleted": goal_id}


class GoalReorder(BaseModel):
    goal_ids: list[str]


@router.put("/goals/reorder")
def reorder_goals(req: GoalReorder):
    """Reorder goals to match the provided id sequence and persist."""
    cfg = _require_config()
    by_id = {g.id: g for g in cfg.goals.current}
    reordered = [by_id[gid] for gid in req.goal_ids if gid in by_id]
    remaining = [g for g in cfg.goals.current if g.id not in set(req.goal_ids)]
    cfg.goals.current = reordered + remaining
    _persist_config(cfg)
    return {"goals": [g.model_dump() for g in cfg.goals.current]}


# ---------------------------------------------------------------------------
# Work source status — read-only view of enabled sources and their item count
# ---------------------------------------------------------------------------

@router.get("/work-sources/status")
def get_work_source_status():
    """Return live status for all configured work sources."""
    orch = _require_orchestrator()
    return {"sources": orch.planner.get_work_source_status()}


# ---------------------------------------------------------------------------
# Internal helper — persist live config back to vigil.yaml
# ---------------------------------------------------------------------------

def _persist_config(cfg) -> None:
    """Save config to the project's vigil.yaml if it exists on disk."""
    import os as _os
    config_path = _os.path.join(cfg.project.path, "vigil.yaml")
    if _os.path.exists(config_path):
        from vigil.config import save_config as _sc
        try:
            _sc(cfg, config_path)
        except Exception as exc:
            log.warning("_persist_config: failed to save vigil.yaml — %s", exc)
    # Always update the in-process context so the running orchestrator sees changes
    if _context is not None:
        _context.config = cfg
        if hasattr(_context.orchestrator, "planner"):
            from vigil.core.task_planner import TaskPlanner
            _context.orchestrator.planner = TaskPlanner(
                _context.orchestrator.state, cfg
            )


class AnalyzeRequest(BaseModel):
    path: str


class SuggestTasksRequest(BaseModel):
    path: str
    require_llm: bool = False


def _setup_llm_status_payload() -> dict:
    """Whether the running server has an LLM provider (for Setup / dashboard)."""
    orch = _orchestrator
    if orch is None:
        return {
            "ready": False,
            "provider_name": None,
            "provider_type": None,
            "model": None,
            "message": "Orchestrator not initialized.",
        }
    prov = getattr(orch, "provider", None)
    if prov is None:
        return {
            "ready": False,
            "provider_name": None,
            "provider_type": None,
            "model": None,
            "message": "No LLM provider on the server. Set provider in vigil.yaml and restart Vigil, or use Settings.",
        }
    cfg_p = _config.provider if _config else None
    return {
        "ready": True,
        "provider_name": prov.name(),
        "provider_type": cfg_p.type if cfg_p else None,
        "model": cfg_p.model if cfg_p else None,
        "message": None,
    }


@router.get("/setup/llm-status")
def setup_llm_status():
    """Report whether an LLM provider is configured (Setup wizard, Refresh with AI)."""
    return _setup_llm_status_payload()


@router.post("/setup/analyze")
def analyze_project(req: AnalyzeRequest):
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
def analyze_project_with_llm(req: AnalyzeRequest):
    """Analyze a project using LLM for smarter suggestions."""
    from vigil.core.analyzer import analyze_with_llm

    if not os.path.isdir(req.path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    provider = _orchestrator.provider if _orchestrator else None
    if provider is None:
        raise HTTPException(status_code=503, detail="LLM provider not available")

    try:
        result = analyze_with_llm(req.path, provider)
        return result
    except Exception as e:
        log.error("LLM analysis failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/setup/suggest-tasks")
def suggest_tasks_endpoint(req: SuggestTasksRequest):
    """Analyze a project and suggest prioritized tasks with rationale.

    Uses the deep 4-phase pipeline when an LLM provider is configured on the orchestrator.
    If ``require_llm`` is true (Refresh with AI), static fallback is disabled — failures return 503.
    """
    if not os.path.isdir(req.path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    provider = getattr(_orchestrator, "provider", None) if _orchestrator else None

    if req.require_llm:
        if provider is None:
            raise HTTPException(
                status_code=503,
                detail=(
                    "LLM provider is not available. Configure provider in Settings or vigil.yaml "
                    "and restart Vigil."
                ),
            )
        try:
            from vigil.core.deep_suggest import deep_suggest_tasks

            final: dict | None = None
            p_config = _config.provider if _config else None
            for event_type, data in deep_suggest_tasks(req.path, provider, provider_config=p_config):
                if event_type == "done":
                    final = data
            if final is not None:
                return final
            raise HTTPException(
                status_code=503,
                detail=(
                    "AI task suggestions did not complete. Check that your LLM endpoint is "
                    "reachable and try again."
                ),
            )
        except HTTPException:
            raise
        except Exception as e:
            log.warning("Deep suggest failed (require_llm): %s", e)
            raise HTTPException(
                status_code=503,
                detail=f"AI task suggestions failed: {e!s}",
            ) from e

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
    """SSE stream of analysis progress (same behaviour as routes_v2 when DB mode is off)."""
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
    """SSE stream of deep analysis (4-phase pipeline). POST only — GET returns 405."""
    from vigil.core.deep_suggest import deep_suggest_tasks

    if not os.path.isdir(req.path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    provider = _orchestrator.provider if _orchestrator else None
    if provider is None:
        raise HTTPException(
            status_code=400,
            detail="No LLM provider configured — deep analysis requires one",
        )

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


class SetupConfig(BaseModel):
    config: dict
    save_to_project: bool = True


@router.post("/setup/apply")
def apply_setup(req: SetupConfig):
    """Apply configuration and optionally save to project directory."""
    global _config, _orchestrator
    import subprocess

    try:
        new_config = VigilConfig(**req.config)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid configuration: {e}")

    project_path = new_config.project.path

    # Initialize git repo if it doesn't exist
    git_dir = os.path.join(project_path, ".git")
    if not os.path.isdir(git_dir):
        log.info("Initializing git repository in %s", project_path)
        try:
            subprocess.run(
                ["git", "init"],
                cwd=project_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "add", "-A"],
                cwd=project_path,
                check=False,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial commit (Vigil setup)"],
                cwd=project_path,
                check=False,
                capture_output=True,
            )
        except Exception as e:
            log.warning("Failed to initialize git: %s", e)

    if req.save_to_project:
        config_path = os.path.join(project_path, "vigil.yaml")
        try:
            save_config(new_config, config_path)
            log.info("Saved config to %s", config_path)
        except Exception as e:
            log.warning("Failed to save config: %s", e)

    _config = new_config
    if _context is not None:
        _context.config = new_config

    if _orchestrator is not None:
        # Stop orchestrator if running
        if _orchestrator._running:
            _orchestrator.stop()
            import time
            time.sleep(0.3)

        _orchestrator.config = new_config
        _orchestrator._current_iteration = 0
        _orchestrator._daily_count = 0
        _orchestrator._no_improve_streak = 0
        _orchestrator._current_task = None
        _orchestrator._paused = False
        _orchestrator._running = False

        from vigil.core.benchmark import BenchmarkRunner
        from vigil.core.code_applier import CodeApplier
        from vigil.core.context_engine import ContextEngine
        from vigil.core.git_ops import GitManager
        from vigil.core.merge_queue import MergeQueue
        from vigil.core.state import StateManager
        from vigil.core.task_planner import TaskPlanner
        from vigil.core.worktree import WorktreeManager

        try:
            ro = getattr(new_config.project, "read_only_paths", None) or []
            _orchestrator.state = StateManager(project_path)
            _orchestrator.git = GitManager(project_path)
            _orchestrator.bench = BenchmarkRunner(new_config.benchmarks, project_path)
            _orchestrator.planner = TaskPlanner(_orchestrator.state, new_config)
            _orchestrator.applier = CodeApplier(project_path, ro)
            _orchestrator.context_engine = ContextEngine(new_config)
            _orchestrator.worktree_mgr = WorktreeManager(project_path)
            _orchestrator.merge_queue = MergeQueue(
                project_path,
                new_config.controls.work_branch,
                base_if_missing=new_config.pr.base_branch,
            )
            from vigil.providers import create_provider

            _orchestrator.provider = create_provider(new_config.provider)
            log.info("Orchestrator reinitialized for project: %s", project_path)
        except Exception as e:
            log.error("Failed to reinitialize orchestrator: %s", e)
            raise HTTPException(status_code=500, detail=f"Failed to initialize project: {e}")

    return {"message": "Configuration applied", "path": project_path}


@router.get("/setup/defaults")
def get_default_config():
    """Get default configuration values for reference."""
    from vigil.config import (
        ApiConfig,
        BenchmarksConfig,
        ControlsConfig,
        NotificationsConfig,
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
        "notifications": NotificationsConfig().model_dump(),
        "api": ApiConfig().model_dump(),
    }
