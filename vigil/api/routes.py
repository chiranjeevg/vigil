import logging
import os
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vigil.config import VigilConfig, load_config, save_config

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api")

_orchestrator: Any = None
_config: VigilConfig | None = None
_provider: Any = None


class Context:
    def __init__(self, orchestrator: Any, config: VigilConfig):
        self.orchestrator = orchestrator
        self.config = config

_context: Context | None = None


def set_context(orchestrator: Any, config: VigilConfig) -> None:
    global _context
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
    from vigil.core.git_ops import GitManager
    from vigil.core.state import StateManager
    from vigil.core.task_planner import TaskPlanner

    ro = getattr(new_config.project, "read_only_paths", None) or []
    orch.state = StateManager(project_path)
    orch.git = GitManager(project_path)
    orch.bench = BenchmarkRunner(new_config.benchmarks, project_path)
    orch.planner = TaskPlanner(orch.state, new_config)
    orch.applier = CodeApplier(project_path, ro)
    orch._paused = True


@router.get("/status")
def get_status():
    orch = _require_orchestrator()
    return orch.get_status()


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
    """Get list of projects that have been configured with Vigil."""
    import json as json_module

    projects = []
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
    return {"projects": projects}


class ProjectPathRequest(BaseModel):
    path: str


@router.get("/projects/remove")
def remove_project_get_not_available():
    """GET is not supported; removal needs the DB-backed API and POST or DELETE."""
    raise HTTPException(
        status_code=400,
        detail="Removing a project requires VIGIL_USE_DATABASE=true and POST or DELETE "
        'with JSON body {"path": "/absolute/path/to/project"}.',
    )


@router.post("/projects/remove")
@router.delete("/projects/remove")
def remove_project_not_available(_req: ProjectPathRequest):
    """Removing projects from the list requires the SQLite/Postgres project registry."""
    raise HTTPException(
        status_code=501,
        detail="Project removal requires VIGIL_USE_DATABASE=true",
    )


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


class AnalyzeRequest(BaseModel):
    path: str


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

    if _provider is None:
        raise HTTPException(status_code=503, detail="LLM provider not available")

    try:
        result = analyze_with_llm(req.path, _provider)
        return result
    except Exception as e:
        log.error("LLM analysis failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/setup/suggest-tasks")
def suggest_tasks_endpoint(req: AnalyzeRequest):
    """Analyze a project and suggest prioritized tasks with rationale."""
    if not os.path.isdir(req.path):
        raise HTTPException(status_code=400, detail="Invalid project path")

    if _provider is not None:
        try:
            from vigil.core.deep_suggest import deep_suggest_tasks

            final: dict | None = None
            p_config = _config.provider if _config else None
            for event_type, data in deep_suggest_tasks(req.path, _provider, provider_config=p_config):
                if event_type == "done":
                    final = data
            if final is not None:
                return final
            log.warning("Deep suggest pipeline returned no result, falling back to basic")
        except Exception as e:
            log.warning("Deep suggest failed, falling back to basic: %s", e)

    from vigil.core.analyzer import suggest_tasks_for_project

    try:
        return suggest_tasks_for_project(req.path, _provider)
    except Exception as e:
        log.error("Task suggestion failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


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
        from vigil.core.git_ops import GitManager
        from vigil.core.state import StateManager
        from vigil.core.task_planner import TaskPlanner

        try:
            _orchestrator.state = StateManager(project_path)
            _orchestrator.git = GitManager(project_path)
            _orchestrator.bench = BenchmarkRunner(new_config.benchmarks, project_path)
            _orchestrator.planner = TaskPlanner(_orchestrator.state, new_config)
            _orchestrator.applier = CodeApplier(project_path)
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
