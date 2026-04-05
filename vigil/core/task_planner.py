"""Task selection and rotation logic for the improvement cycle."""

import logging
import subprocess

from vigil.config import VigilConfig
from vigil.core.state import StateManager

log = logging.getLogger(__name__)


class TaskPlanner:
    def __init__(self, state: StateManager, config: VigilConfig):
        self._state = state
        self._config = config

    def next_task(self, no_improve_streak: int) -> dict:
        queue = self._state.get_task_queue()
        if queue:
            task = queue.pop(0)
            self._state.save_task_queue(queue)
            return {
                "type": "custom",
                "description": task.get("description", "Custom task"),
                "target_files": task.get("files", []),
                "instructions": task.get("instructions", ""),
            }

        priorities = list(self._config.tasks.priorities)

        if self._should_shift_focus(no_improve_streak):
            current_focus = self._state.get_current_focus()
            if current_focus and current_focus in priorities:
                priorities.remove(current_focus)
                priorities.append(current_focus)
                log.info(
                    "Shifting focus away from %s after %d no-improvement iterations",
                    current_focus, no_improve_streak,
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
        """Pick a concrete task for a priority, or None to try the next priority in order."""
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

        # Builtin catalog types (type_safety, security_audit, …) and custom_* must run here,
        # otherwise the planner skipped them and jumped to a later priority (e.g. modernize_code).
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
