"""GoalSource — turns the user's ``goals.current`` list into WorkItems.

Goals are the highest-trust signal: the human has explicitly stated what
they want Vigil to work on.  They are always returned as-is (no filtering,
no external I/O) and scored highest by the Prioritizer.
"""

from __future__ import annotations

import logging

from vigil.config import GoalsConfig
from vigil.core.work_sources.base import WorkItem, WorkSource

log = logging.getLogger(__name__)


class GoalSource(WorkSource):
    """Converts ``GoalsConfig.current`` entries into ``WorkItem`` dicts."""

    def __init__(self, config: GoalsConfig) -> None:
        self._config = config

    def name(self) -> str:
        return "goal"

    @property
    def is_enabled(self) -> bool:
        return bool(self._config.current)

    def poll(self) -> list[WorkItem]:
        items: list[WorkItem] = []
        for goal in self._config.current:
            # Infer work_type from description keywords so the Prioritizer can
            # score security/bug items higher even within the goals list.
            work_type = _infer_work_type(goal.description)
            items.append(
                WorkItem(
                    id=f"goal:{goal.id}",
                    source="goal",
                    work_type=work_type,
                    title=goal.description[:80],
                    description=goal.description,
                    priority=goal.priority,
                    context_files=list(goal.context_files),
                    context_docs=list(goal.context_docs),
                    instructions=goal.description,
                    metadata={"issue_ref": goal.issue_ref} if goal.issue_ref else {},
                )
            )
        log.debug("GoalSource: %d goals", len(items))
        return items


_BUG_KEYWORDS = frozenset({"fix", "bug", "crash", "error", "race", "leak", "wrong", "broken"})
_SECURITY_KEYWORDS = frozenset({"security", "auth", "injection", "xss", "csrf", "vuln", "secret"})
_TEST_KEYWORDS = frozenset({"test", "tests", "spec", "specs", "coverage", "assertion"})
_FEATURE_KEYWORDS = frozenset({"implement", "add", "build", "create", "write", "support", "integrate"})


def _infer_work_type(description: str) -> str:
    words = set(description.lower().split())
    # Security and bug signals take precedence — they drive the highest priority score.
    if words & _SECURITY_KEYWORDS:
        return "security"
    if words & _BUG_KEYWORDS:
        return "bug_fix"
    # Test must be checked before feature because "write tests" contains a
    # feature keyword ("write") but the intent is clearly test work.
    if words & _TEST_KEYWORDS:
        return "test"
    if words & _FEATURE_KEYWORDS:
        return "feature"
    return "custom"
