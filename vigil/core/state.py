"""File-based and database state management for iteration tracking."""

import json
import logging
import threading
import time as _time
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


class IterationLog:
    """Accumulates step-by-step detail for a single iteration.

    Optionally broadcasts each step in real-time via a callback so the
    frontend can show live progress.
    """

    def __init__(
        self,
        iteration: int,
        task: dict,
        broadcast_fn=None,
    ):
        self.iteration = iteration
        self.task = task
        self.started_at = datetime.now(timezone.utc)
        self.steps: list[dict] = []
        self._step_timer: float | None = None
        self._broadcast = broadcast_fn

    def _emit(self, step: dict) -> None:
        if self._broadcast:
            self._broadcast("iteration_step", {
                "iteration": self.iteration,
                "task_type": self.task.get("type", ""),
                "task_description": self.task.get("description", ""),
                "step": step,
                "step_index": len(self.steps) - 1,
                "elapsed_ms": self.total_duration_ms(),
            })

    def begin_step(self, label: str) -> None:
        self._step_timer = _time.monotonic()
        step = {
            "label": label,
            "ts": datetime.now(timezone.utc).isoformat(),
            "duration_ms": 0,
            "detail": None,
            "status": "running",
        }
        self.steps.append(step)
        self._emit(step)

    def end_step(self, detail: str | dict | None = None) -> None:
        if not self.steps:
            return
        step = self.steps[-1]
        if self._step_timer is not None:
            step["duration_ms"] = round((_time.monotonic() - self._step_timer) * 1000)
        if detail is not None:
            step["detail"] = detail
        step["status"] = "done"
        self._emit(step)

    def add_step(self, label: str, detail: str | dict | None = None) -> None:
        step = {
            "label": label,
            "ts": datetime.now(timezone.utc).isoformat(),
            "duration_ms": 0,
            "detail": detail,
            "status": "done",
        }
        self.steps.append(step)
        self._emit(step)

    def total_duration_ms(self) -> int:
        return round((datetime.now(timezone.utc) - self.started_at).total_seconds() * 1000)

    def to_dict(
        self,
        status: str,
        summary: str,
        benchmark_data: dict,
        *,
        files_changed: list[str] | None = None,
        diff: str | None = None,
        commit_hash: str | None = None,
        llm_response: str | None = None,
        llm_prompt_system: str | None = None,
        llm_prompt_user: str | None = None,
        llm_tokens: int = 0,
        llm_duration_s: float = 0.0,
        changes_detail: list[dict] | None = None,
        test_output: str | None = None,
        branch_name: str | None = None,
        provider_name: str | None = None,
    ) -> dict:
        return {
            "iteration": self.iteration,
            "timestamp": self.started_at.isoformat(),
            "task_type": self.task.get("type", "unknown"),
            "task_description": self.task.get("description", ""),
            "status": status,
            "benchmark_data": benchmark_data,
            "summary": summary,
            "duration_ms": self.total_duration_ms(),
            "steps": self.steps,
            "files_changed": files_changed or [],
            "diff": (diff or "")[:50000],
            "commit_hash": commit_hash or "",
            "llm_response": (llm_response or "")[:30000],
            "llm_prompt_system": (llm_prompt_system or "")[:5000],
            "llm_prompt_user": (llm_prompt_user or "")[:20000],
            "llm_tokens": llm_tokens,
            "llm_duration_s": round(llm_duration_s, 2),
            "changes_detail": changes_detail or [],
            "test_output": (test_output or "")[:10000],
            "branch_name": branch_name or "",
            "provider_name": provider_name or "",
        }


class StateManager:
    def __init__(self, project_path: str):
        self._project_path = project_path
        self._dir = Path(project_path) / ".vigil-state"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

        self._progress_file = self._dir / "progress.md"
        self._tasks_file = self._dir / "tasks.json"
        self._benchmarks_file = self._dir / "benchmarks.json"
        self._iterations_file = self._dir / "iterations.json"
        self._iterative_branch_file = self._dir / "iterative_branch.json"

        for f in (self._tasks_file, self._benchmarks_file, self._iterations_file):
            if not f.exists():
                f.write_text("[]")

        if not self._progress_file.exists():
            self._progress_file.write_text("# Vigil Progress Log\n\n")

    def _read_json(self, path: Path) -> list[dict]:
        with self._lock:
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, FileNotFoundError):
                return []

    def _write_json(self, path: Path, data: list[dict]) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2, default=str))

    def next_iteration(self) -> int:
        iterations = self._read_json(self._iterations_file)
        return len(iterations) + 1

    def new_iteration_log(self, iteration: int, task: dict, broadcast_fn=None) -> IterationLog:
        return IterationLog(iteration, task, broadcast_fn=broadcast_fn)

    def save_iteration(self, entry: dict) -> None:
        iterations = self._read_json(self._iterations_file)
        iterations.append(entry)
        self._write_json(self._iterations_file, iterations)

        self._save_to_db(entry)

        with self._lock:
            with open(self._progress_file, "a") as f:
                f.write(
                    f"### Iteration {entry['iteration']} — {entry['status']}\n"
                    f"**Task:** {entry.get('task_type', 'unknown')} — "
                    f"{entry.get('task_description', '')}\n"
                    f"**Summary:** {entry.get('summary', '')}\n"
                    f"**Duration:** {entry.get('duration_ms', 0)}ms\n"
                    f"**Time:** {entry['timestamp']}\n\n"
                )

    def _save_to_db(self, entry: dict) -> None:
        """Persist the iteration to the SQLite database using raw sqlite3."""
        try:
            import sqlite3 as _sqlite3
            from pathlib import Path as _Path

            db_path = _Path.home() / ".vigil" / "vigil.db"
            if not db_path.exists():
                return

            conn = _sqlite3.connect(str(db_path), timeout=5)
            try:
                cur = conn.cursor()
                cur.execute("SELECT id FROM projects WHERE path = ?", (self._project_path,))
                row = cur.fetchone()
                if not row:
                    import os
                    name = os.path.basename(self._project_path) or "project"
                    cur.execute(
                        "INSERT INTO projects (path, name, language, is_active, "
                        "total_iterations, successful_iterations, created_at, updated_at) "
                        "VALUES (?,?,?,1,0,0,datetime('now'),datetime('now'))",
                        (self._project_path, name, "unknown"),
                    )
                    project_id = cur.lastrowid
                    log.info("Auto-registered project %s in DB (id=%d)", name, project_id)
                else:
                    project_id = row[0]

                import json as _json
                cur.execute(
                    """INSERT OR REPLACE INTO iterations
                    (project_id, iteration_num, task_type, task_description,
                     status, summary, files_changed, diff, commit_hash,
                     llm_response, llm_prompt_system, llm_prompt_user,
                     llm_tokens, llm_duration_s, steps, changes_detail,
                     test_output, branch_name, provider_name,
                     benchmark_data, duration_ms, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))""",
                    (
                        project_id,
                        entry["iteration"],
                        entry.get("task_type", ""),
                        entry.get("task_description", ""),
                        entry.get("status", ""),
                        entry.get("summary", ""),
                        _json.dumps(entry.get("files_changed")) if entry.get("files_changed") else None,
                        entry.get("diff"),
                        entry.get("commit_hash"),
                        entry.get("llm_response"),
                        entry.get("llm_prompt_system"),
                        entry.get("llm_prompt_user"),
                        entry.get("llm_tokens", 0),
                        entry.get("llm_duration_s"),
                        _json.dumps(entry.get("steps")) if entry.get("steps") else None,
                        _json.dumps(entry.get("changes_detail")) if entry.get("changes_detail") else None,
                        entry.get("test_output"),
                        entry.get("branch_name"),
                        entry.get("provider_name"),
                        _json.dumps(entry.get("benchmark_data")) if entry.get("benchmark_data") else None,
                        entry.get("duration_ms", 0),
                    ),
                )
                cur.execute(
                    "UPDATE projects SET total_iterations = total_iterations + 1 WHERE id = ?",
                    (project_id,),
                )
                if entry.get("status") == "success":
                    cur.execute(
                        "UPDATE projects SET successful_iterations = successful_iterations + 1 WHERE id = ?",
                        (project_id,),
                    )
                conn.commit()
                log.debug("Saved iteration %d to DB", entry["iteration"])
            finally:
                conn.close()

        except Exception as exc:
            log.warning("Failed to save iteration to DB: %s", exc)

    def log_iteration(
        self,
        iteration: int,
        task: dict,
        status: str,
        benchmark_data: dict,
        summary: str,
        *,
        files_changed: list[str] | None = None,
        diff: str | None = None,
        commit_hash: str | None = None,
        llm_response_preview: str | None = None,
        changes_detail: list[dict] | None = None,
    ) -> None:
        """Legacy method for backward compatibility."""
        entry = {
            "iteration": iteration,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task_type": task.get("type", "unknown"),
            "task_description": task.get("description", ""),
            "status": status,
            "benchmark_data": benchmark_data,
            "summary": summary,
            "duration_ms": 0,
            "steps": [],
            "files_changed": files_changed or [],
            "diff": (diff or "")[:50000],
            "commit_hash": commit_hash or "",
            "llm_response": (llm_response_preview or "")[:30000],
            "llm_prompt_system": "",
            "llm_prompt_user": "",
            "llm_tokens": 0,
            "llm_duration_s": 0,
            "changes_detail": changes_detail or [],
            "test_output": "",
        }
        self.save_iteration(entry)

    def get_progress_summary(self, last_n: int = 10) -> str:
        with self._lock:
            if not self._progress_file.exists():
                return ""
            lines = self._progress_file.read_text().splitlines()

        chunks: list[str] = []
        current_chunk: list[str] = []
        for line in lines:
            if line.startswith("### Iteration"):
                if current_chunk:
                    chunks.append("\n".join(current_chunk))
                current_chunk = [line]
            elif current_chunk:
                current_chunk.append(line)
        if current_chunk:
            chunks.append("\n".join(current_chunk))

        return "\n\n".join(chunks[-last_n:])

    def get_recent_benchmarks(self, last_n: int = 5) -> list[dict]:
        data = self._read_json(self._benchmarks_file)
        return data[-last_n:]

    def get_completed_tasks(self, last_n: int = 20) -> list[dict]:
        iterations = self._read_json(self._iterations_file)
        completed = [i for i in iterations if i.get("status") == "success"]
        return completed[-last_n:]

    def get_current_focus(self) -> str | None:
        iterations = self._read_json(self._iterations_file)
        if not iterations:
            return None
        return iterations[-1].get("task_type")

    def get_stats(self) -> dict:
        iterations = self._read_json(self._iterations_file)
        total = len(iterations)
        successes = sum(1 for i in iterations if i.get("status") == "success")
        failures = total - successes
        llm_tokens_total = sum(int(i.get("llm_tokens") or 0) for i in iterations)
        duration_ms_total = sum(int(i.get("duration_ms") or 0) for i in iterations)

        benchmarks = self._read_json(self._benchmarks_file)
        coverage_trend: list[float] = []
        for b in benchmarks[-10:]:
            cov = b.get("coverage")
            if cov is not None:
                coverage_trend.append(cov)

        return {
            "total_iterations": total,
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / total * 100, 1) if total else 0.0,
            "coverage_trend": coverage_trend,
            "llm_tokens_total": llm_tokens_total,
            "duration_ms_total": duration_ms_total,
        }

    def save_benchmark(self, data: dict) -> None:
        benchmarks = self._read_json(self._benchmarks_file)
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
        benchmarks.append(data)
        self._write_json(self._benchmarks_file, benchmarks)

    def get_all_iterations(self) -> list[dict]:
        return self._read_json(self._iterations_file)

    def iteration_summaries_page(
        self,
        offset: int = 0,
        limit: int = 25,
        status_filter: str | None = None,
        sort_order: str = "desc",
    ) -> tuple[list[dict], int]:
        """Return (summary rows for one page, total matching count). Sorted by time, then iteration."""
        all_iters = self._read_json(self._iterations_file)
        if status_filter == "success":
            filtered = [i for i in all_iters if i.get("status") == "success"]
        elif status_filter == "failed":
            filtered = [i for i in all_iters if i.get("status") != "success"]
        else:
            filtered = all_iters

        def _iter_sort_key(x: dict) -> tuple[str, int]:
            return (x.get("timestamp") or "", int(x.get("iteration") or 0))

        sorted_iters = sorted(
            filtered,
            key=_iter_sort_key,
            reverse=(sort_order == "desc"),
        )
        total = len(sorted_iters)
        page = sorted_iters[offset : offset + limit]
        summaries = [
            {
                "iteration": it.get("iteration"),
                "task_type": it.get("task_type", ""),
                "task_description": it.get("task_description", ""),
                "status": it.get("status", ""),
                "summary": it.get("summary", ""),
                "benchmark_data": it.get("benchmark_data", {}),
                "timestamp": it.get("timestamp", ""),
                "files_changed": it.get("files_changed", []),
                "commit_hash": it.get("commit_hash", ""),
                "duration_ms": it.get("duration_ms", 0),
                "llm_tokens": it.get("llm_tokens", 0),
                "llm_duration_s": it.get("llm_duration_s", 0),
                "step_count": len(it.get("steps", [])),
            }
            for it in page
        ]
        return summaries, total

    def get_iteration(self, iteration_num: int) -> dict | None:
        """Get a specific iteration by number."""
        iterations = self.get_all_iterations()
        for it in iterations:
            if it.get("iteration") == iteration_num:
                return it
        return None

    def get_task_queue(self) -> list[dict]:
        return self._read_json(self._tasks_file)

    def save_task_queue(self, tasks: list[dict]) -> None:
        self._write_json(self._tasks_file, tasks)

    def get_last_successful_branch(self) -> str | None:
        """Last successful PR iteration branch name (for chaining after process restart)."""
        with self._lock:
            if not self._iterative_branch_file.exists():
                return None
            try:
                data = json.loads(self._iterative_branch_file.read_text())
            except (json.JSONDecodeError, OSError):
                return None
            b = data.get("last_successful_branch")
            return b if isinstance(b, str) and b.strip() else None

    def set_last_successful_branch(self, branch: str | None) -> None:
        """Persist or clear the branch the next iteration should fork from (PR workflow)."""
        with self._lock:
            if not branch:
                if self._iterative_branch_file.exists():
                    try:
                        self._iterative_branch_file.unlink()
                    except OSError:
                        pass
                return
            self._iterative_branch_file.parent.mkdir(parents=True, exist_ok=True)
            self._iterative_branch_file.write_text(
                json.dumps({"last_successful_branch": branch}, indent=2)
            )
