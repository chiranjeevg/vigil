"""Prioritizer — scores and ranks WorkItems for the engineer mode planner.

The scoring model is intentionally simple and transparent so users can
reason about it.  Each item receives a float score; higher is worked sooner.

Score composition
-----------------
source_weight   : goals=100, manual=80, github=70, prd=60, improvement=20
type_weight     : security=50, bug_fix=40, feature=30, test=20, improvement=10
priority_bonus  : P1=40, P2=30, P3=20, P4=10, P5=0
staleness_bonus : +1 per iteration that has passed since last attempt (anti-starvation)
failure_penalty : −15 per recent failure for this item (back-off)

The staleness bonus guarantees that no item is permanently skipped:
after enough iterations the bonus will always outweigh any failure penalty.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring weights — change these to tune the model, not the algorithm
# ---------------------------------------------------------------------------

_SOURCE_WEIGHT: dict[str, float] = {
    "goal": 100.0,
    "manual": 80.0,
    "github_issues": 70.0,
    "prd_scanner": 60.0,
    "improvement": 20.0,
}

_TYPE_WEIGHT: dict[str, float] = {
    "security": 50.0,
    "bug_fix": 40.0,
    "feature": 30.0,
    "test": 20.0,
    "custom": 15.0,
    "improvement": 10.0,
}

_PRIORITY_BONUS: dict[int, float] = {1: 40.0, 2: 30.0, 3: 20.0, 4: 10.0, 5: 0.0}

# Each iteration that passes without working on an item adds this much score.
_STALENESS_PER_ITERATION = 2.0

# Each recent failed attempt subtracts this much score.
_FAILURE_PENALTY = 15.0

# How many recent iterations to look back when computing staleness / failures.
_HISTORY_WINDOW = 50


class Prioritizer:
    """Ranks a list of WorkItems based on source, type, user priority, and history."""

    def rank(
        self,
        items: list[dict],
        completed_tasks: list[dict],
        current_iteration: int,
    ) -> list[dict]:
        """Return *items* sorted highest-score first.

        ``completed_tasks`` is the list from ``StateManager.get_completed_tasks``
        — each entry has at minimum ``task_type`` and ``status``.
        ``current_iteration`` is used to compute staleness.
        """
        if not items:
            return []

        history = _build_history(completed_tasks[-_HISTORY_WINDOW:], current_iteration)

        scored: list[tuple[float, dict]] = []
        for item in items:
            score = self._score(item, history, current_iteration)
            scored.append((score, item))
            log.debug(
                "Prioritizer: %s score=%.1f (src=%s type=%s p%d)",
                item.get("id", "?"),
                score,
                item.get("source", "?"),
                item.get("work_type", "?"),
                item.get("priority", 3),
            )

        scored.sort(key=lambda t: t[0], reverse=True)
        return [item for _, item in scored]

    # ------------------------------------------------------------------
    # Scoring components
    # ------------------------------------------------------------------

    def _score(
        self,
        item: dict,
        history: dict[str, Any],
        current_iteration: int,
    ) -> float:
        item_id: str = item.get("id", "")
        source: str = item.get("source", "improvement")
        work_type: str = item.get("work_type", "improvement")
        priority: int = max(1, min(5, int(item.get("priority", 3))))

        score = _SOURCE_WEIGHT.get(source, 20.0)
        score += _TYPE_WEIGHT.get(work_type, 10.0)
        score += _PRIORITY_BONUS.get(priority, 0.0)

        item_history = history.get(item_id, {"last_iteration": 0, "failures": 0})
        last_iter: int = item_history["last_iteration"]
        failures: int = item_history["failures"]

        gap = max(0, current_iteration - last_iter)
        score += gap * _STALENESS_PER_ITERATION
        score -= failures * _FAILURE_PENALTY

        return score


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------

def _build_history(
    completed_tasks: list[dict],
    current_iteration: int,
) -> dict[str, dict[str, Any]]:
    """Build a per-task-id index of {last_iteration, failures} from state history.

    We key by ``task_type`` because that is what the iteration log records.
    WorkItem ids are formatted as ``<source>:<external-id>``; task_type for
    work-source-driven tasks is stored as the id directly.
    """
    index: dict[str, dict[str, Any]] = {}
    for entry in completed_tasks:
        task_id: str = entry.get("task_type", "")
        if not task_id:
            continue
        iteration = int(entry.get("iteration") or 0)
        is_failure = entry.get("status", "success") != "success"

        if task_id not in index:
            index[task_id] = {"last_iteration": 0, "failures": 0}

        if iteration > index[task_id]["last_iteration"]:
            index[task_id]["last_iteration"] = iteration
        if is_failure:
            index[task_id]["failures"] += 1

    return index
