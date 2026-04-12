"""Task selection and rotation logic for the improvement cycle.

In **improver** mode (default) the planner walks ``tasks.priorities`` in order.
After each **successful** iteration, that ``task_type`` is moved to the **end** of
the walk. After **failed** iterations (e.g. ``safety_revert``), the same rotation
applies so the planner does **not** reset to the config file order and get stuck
on the first priority again. While tests are failing, ``fix_tests`` is walked
first and is not rotated away on failure until tests pass.

In **engineer** mode the planner:
1. Pops the first item from the manual queue (highest trust — user-injected).
2. Aggregates WorkItems from all enabled work sources.
3. Scores and ranks them via the Prioritizer.
4. Converts the top-ranked item into a task dict for the orchestrator.
5. Falls back to the static priority walk only when all sources are empty.

The two modes share the same public API (``next_task``, ``add_task``, etc.)
so the orchestrator needs no changes between modes.
"""

from __future__ import annotations

import logging
import subprocess
from typing import TYPE_CHECKING

from vigil.config import PriorityMode, VigilConfig
from vigil.core.state import StateManager

if TYPE_CHECKING:
    from vigil.core.work_sources.base import WorkItem

log = logging.getLogger(__name__)


class TaskPlanner:
    def __init__(self, state: StateManager, config: VigilConfig) -> None:
        self._state = state
        self._config = config
        self._work_sources = _build_work_sources(config)
        self._prioritizer = _build_prioritizer(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def next_task(self, no_improve_streak: int) -> dict:
        """Return the next task dict for the orchestrator.

        Always drains the manual queue first (both modes).
        In engineer mode, delegates to the work-source pipeline.
        In improver mode, walks the static priority list.
        """
        manual = self._pop_manual_queue()
        if manual is not None:
            return manual

        if self._config.tasks.priority_mode == PriorityMode.ENGINEER.value:
            task = self._next_from_work_sources()
            if task is not None:
                return task
            # No forward work available — fall through to improvement tasks
            log.info("TaskPlanner: no work-source items; falling back to improver mode")

        return self._next_from_priorities(no_improve_streak)

    def add_task(self, task: dict) -> None:
        queue = self._state.get_task_queue()
        queue.append(task)
        self._state.save_task_queue(queue)

    def remove_task(self, task_id: str) -> None:
        queue = self._state.get_task_queue()
        queue = [t for t in queue if t.get("id") != task_id]
        self._state.save_task_queue(queue)

    def reorder_tasks(self, task_ids: list[str]) -> None:
        queue = self._state.get_task_queue()
        by_id = {t.get("id"): t for t in queue}
        reordered = [by_id[tid] for tid in task_ids if tid in by_id]
        remaining = [t for t in queue if t.get("id") not in set(task_ids)]
        self._state.save_task_queue(reordered + remaining)

    def get_queue(self) -> list[dict]:
        return self._state.get_task_queue()

    def get_work_source_status(self) -> list[dict]:
        """Return a summary of each configured work source for the status API."""
        return [
            {
                "name": src.name(),
                "enabled": src.is_enabled,
                "item_count": len(src.poll()) if src.is_enabled else 0,
            }
            for src in self._work_sources
        ]

    # ------------------------------------------------------------------
    # Manual queue
    # ------------------------------------------------------------------

    def _pop_manual_queue(self) -> dict | None:
        queue = self._state.get_task_queue()
        if not queue:
            return None
        task = queue.pop(0)
        self._state.save_task_queue(queue)
        return {
            "type": "custom",
            "description": task.get("description", "Custom task"),
            "target_files": task.get("files", []),
            "instructions": task.get("instructions", ""),
        }

    # ------------------------------------------------------------------
    # Engineer mode — work source pipeline
    # ------------------------------------------------------------------

    def _next_from_work_sources(self) -> dict | None:
        if not self._work_sources:
            return None

        all_items: list[WorkItem] = []
        for src in self._work_sources:
            if not src.is_enabled:
                continue
            try:
                items = src.poll()
                log.debug("TaskPlanner: %s returned %d items", src.name(), len(items))
                all_items.extend(items)
            except Exception as exc:
                log.warning("TaskPlanner: work source %s failed — %s", src.name(), exc)

        if not all_items:
            return None

        completed_tasks = self._state.get_completed_tasks(last_n=50)
        current_iteration = self._state.next_iteration() - 1
        ranked = self._prioritizer.rank(
            all_items, completed_tasks, max(0, current_iteration)
        )
        if not ranked:
            return None

        best: WorkItem = ranked[0]
        log.info(
            "TaskPlanner: selected %s (%s/%s p%d) from %d candidates",
            best.get("id"),
            best.get("source"),
            best.get("work_type"),
            best.get("priority", 3),
            len(ranked),
        )
        return _work_item_to_task(best)

    # ------------------------------------------------------------------
    # Improver mode — priority walk with history-based rotation
    # ------------------------------------------------------------------

    def _next_from_priorities(self, no_improve_streak: int) -> dict:
        priorities = list(self._config.tasks.priorities)

        # Rotate based on a window of recent iterations so we advance
        # through the full list instead of ping-ponging between #1 and #2.
        recent = self._state.get_recent_iterations(len(priorities))
        priorities = _rotate_priorities_from_history(priorities, recent)

        # fix_tests always comes first when tests are actually failing.
        if not self._check_tests_passing() and "fix_tests" in priorities:
            priorities = ["fix_tests"] + [p for p in priorities if p != "fix_tests"]

        if self._should_shift_focus(no_improve_streak):
            current_focus = self._state.get_current_focus()
            if current_focus and current_focus in priorities:
                priorities.remove(current_focus)
                priorities.append(current_focus)
                log.info(
                    "Shifting focus away from %s after %d no-improvement iterations",
                    current_focus,
                    no_improve_streak,
                )

        for priority in priorities:
            task = self._evaluate_priority(priority)
            if task:
                return task

        return {
            "type": "refactor",
            "description": "General code quality improvements",
            "target_files": [],
            "instructions": self._config.tasks.instructions.get("refactor", ""),
        }

    def _evaluate_priority(self, priority: str) -> dict | None:
        """Pick a concrete task for a priority, or None to try the next one."""
        instructions = self._config.tasks.instructions.get(priority, "")

        if priority == "fix_tests":
            if not self._check_tests_passing():
                return {
                    "type": "fix_tests",
                    "description": "Fix failing tests",
                    "target_files": [],
                    "instructions": instructions,
                }
            return None

        if priority == "test_coverage":
            coverage = self._check_coverage()
            if coverage is not None and coverage < self._config.tests.coverage.target:
                return {
                    "type": "test_coverage",
                    "description": f"Increase test coverage (currently {coverage:.1f}%)",
                    "target_files": [],
                    "instructions": instructions,
                }
            return None

        if priority == "run_benchmarks":
            if not self._config.benchmarks.enabled or not str(
                self._config.benchmarks.command or ""
            ).strip():
                return None

        return self._generic_priority_task(priority, instructions)

    def _generic_priority_task(self, priority: str, instructions: str) -> dict:
        return {
            "type": priority,
            "description": f"Perform {priority.replace('_', ' ')}",
            "target_files": [],
            "instructions": instructions,
        }

    def _check_tests_passing(self) -> bool:
        cmd = self._config.tests.command
        if not cmd:
            return True
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=self._config.project.path,
                capture_output=True,
                text=True,
                timeout=self._config.tests.timeout,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def _check_coverage(self) -> float | None:
        cov = self._config.tests.coverage
        if not cov.enabled or not cov.command:
            return None
        try:
            result = subprocess.run(
                cov.command,
                shell=True,
                cwd=self._config.project.path,
                capture_output=True,
                text=True,
                timeout=120,
            )
            for line in reversed(result.stdout.splitlines()):
                for token in line.split():
                    cleaned = token.strip("%")
                    try:
                        val = float(cleaned)
                        if 0 <= val <= 100:
                            return val
                    except ValueError:
                        continue
        except (subprocess.TimeoutExpired, OSError) as e:
            log.warning("Coverage check failed: %s", e)
        return None

    def _should_shift_focus(self, streak: int) -> bool:
        return streak >= self._config.controls.max_consecutive_no_improvement


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions, easy to unit-test)
# ---------------------------------------------------------------------------


def _rotate_priorities_from_history(
    priorities: list[str],
    recent_iterations: list[dict],
) -> list[str]:
    """Rotate all recently attempted task types to the end of the walk.

    Processes the last ``len(priorities)`` iterations in chronological order.
    Each iteration's ``task_type`` is moved to the end so the planner advances
    through the full priority list.

    Example with config ``[A, B, C]`` and history ``[A-success, B-success]``:
      start   → [A, B, C]
      after A → [B, C, A]
      after B → [C, A, B]
      next pick: C  ✓

    Without this, the planner only rotates the *single* last task type and
    permanently ping-pongs between positions 1 and 2.
    """
    out = list(priorities)
    if not recent_iterations:
        return out

    for it in recent_iterations:
        task_type = it.get("task_type")
        if task_type and isinstance(task_type, str) and task_type in out:
            out.remove(task_type)
            out.append(task_type)

    return out


def _work_item_to_task(item: WorkItem) -> dict:
    """Convert a WorkItem to the task dict the orchestrator expects."""
    # Store the work_type as the task type so the context engine can use it.
    return {
        "type": item.get("id", "custom"),
        "work_type": item.get("work_type", "custom"),
        "description": item.get("description", item.get("title", "Work item")),
        "target_files": [],  # ContextEngine reads context_files from the item
        "context_files": item.get("context_files", []),
        "context_docs": item.get("context_docs", []),
        "instructions": item.get("instructions", ""),
        "source": item.get("source", ""),
        "metadata": item.get("metadata", {}),
    }


def _build_work_sources(config: VigilConfig) -> list:
    """Instantiate all configured work sources. Import here to keep startup fast."""
    if config.tasks.priority_mode != PriorityMode.ENGINEER.value:
        return []

    sources: list = []
    try:
        from vigil.core.work_sources.goal_source import GoalSource
        sources.append(GoalSource(config.goals))
    except Exception as exc:  # pragma: no cover
        log.warning("TaskPlanner: GoalSource init failed — %s", exc)

    try:
        from vigil.core.work_sources.github_issues import GitHubIssueSource
        sources.append(GitHubIssueSource(config.work_sources.github_issues))
    except Exception as exc:  # pragma: no cover
        log.warning("TaskPlanner: GitHubIssueSource init failed — %s", exc)

    try:
        from vigil.core.work_sources.prd_scanner import PRDScanner
        sources.append(PRDScanner(
            config.work_sources.prd_paths,
            config.project.path,
        ))
    except Exception as exc:  # pragma: no cover
        log.warning("TaskPlanner: PRDScanner init failed — %s", exc)

    return sources


def _build_prioritizer(config: VigilConfig):
    if config.tasks.priority_mode != PriorityMode.ENGINEER.value:
        return None
    from vigil.core.prioritizer import Prioritizer
    return Prioritizer()
