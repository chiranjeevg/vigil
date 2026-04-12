"""Tests for the Prioritizer scoring and ranking logic."""

import pytest

from vigil.core.prioritizer import Prioritizer, _build_history


def _make_item(
    id: str = "test:1",
    source: str = "goal",
    work_type: str = "feature",
    priority: int = 1,
) -> dict:
    return {
        "id": id,
        "source": source,
        "work_type": work_type,
        "priority": priority,
        "title": "Test item",
        "description": "Test description",
        "context_files": [],
        "context_docs": [],
        "instructions": "",
        "metadata": {},
    }


class TestPrioritizer:
    def setup_method(self):
        self.p = Prioritizer()

    def test_empty_items_returns_empty(self):
        assert self.p.rank([], [], 1) == []

    def test_single_item_returned(self):
        item = _make_item()
        ranked = self.p.rank([item], [], 1)
        assert len(ranked) == 1
        assert ranked[0]["id"] == item["id"]

    def test_goal_beats_github(self):
        goal = _make_item(id="goal:x", source="goal", work_type="feature", priority=1)
        github = _make_item(id="github:x", source="github_issues", work_type="feature", priority=1)
        ranked = self.p.rank([github, goal], [], 1)
        assert ranked[0]["id"] == "goal:x"

    def test_bug_beats_feature_same_source(self):
        bug = _make_item(id="bug:1", source="github_issues", work_type="bug_fix", priority=1)
        feat = _make_item(id="feat:1", source="github_issues", work_type="feature", priority=1)
        ranked = self.p.rank([feat, bug], [], 1)
        assert ranked[0]["id"] == "bug:1"

    def test_security_beats_bug_same_source(self):
        bug = _make_item(id="bug:1", source="github_issues", work_type="bug_fix", priority=1)
        sec = _make_item(id="sec:1", source="github_issues", work_type="security", priority=1)
        ranked = self.p.rank([bug, sec], [], 1)
        assert ranked[0]["id"] == "sec:1"

    def test_higher_user_priority_wins(self):
        p1 = _make_item(id="p1", source="goal", work_type="feature", priority=1)
        p3 = _make_item(id="p3", source="goal", work_type="feature", priority=3)
        ranked = self.p.rank([p3, p1], [], 1)
        assert ranked[0]["id"] == "p1"

    def test_staleness_bonus_accumulates(self):
        """An item not touched for many iterations should climb the ranks."""
        # fresh item: last_iteration = 9, current = 10 → gap 1
        fresh = _make_item(id="fresh", source="github_issues", work_type="feature", priority=3)
        # stale item: last_iteration = 0, current = 10 → gap 10
        stale = _make_item(id="stale", source="github_issues", work_type="feature", priority=3)
        completed = [
            {"task_type": "fresh", "iteration": 9, "status": "success"},
        ]
        ranked = self.p.rank([fresh, stale], completed, 10)
        # stale item has larger gap so must win despite same base score
        assert ranked[0]["id"] == "stale"

    def test_failure_penalty_reduces_score(self):
        """Items that failed recently should be deprioritised."""
        good = _make_item(id="good", source="github_issues", work_type="feature", priority=1)
        bad = _make_item(id="bad", source="github_issues", work_type="feature", priority=1)
        # bad has two recent failures
        completed = [
            {"task_type": "bad", "iteration": 5, "status": "tests_failed"},
            {"task_type": "bad", "iteration": 6, "status": "llm_error"},
        ]
        ranked = self.p.rank([bad, good], completed, 10)
        assert ranked[0]["id"] == "good"

    def test_ordering_is_stable_for_equal_scores(self):
        items = [_make_item(id=f"item:{i}", source="goal", work_type="feature", priority=3)
                 for i in range(4)]
        ranked = self.p.rank(items, [], 1)
        assert len(ranked) == 4


class TestBuildHistory:
    def test_empty_completed_returns_empty(self):
        assert _build_history([], 5) == {}

    def test_tracks_last_iteration(self):
        completed = [
            {"task_type": "goal:x", "iteration": 3, "status": "success"},
            {"task_type": "goal:x", "iteration": 7, "status": "success"},
        ]
        history = _build_history(completed, 10)
        assert history["goal:x"]["last_iteration"] == 7

    def test_counts_failures(self):
        completed = [
            {"task_type": "goal:x", "iteration": 1, "status": "tests_failed"},
            {"task_type": "goal:x", "iteration": 2, "status": "llm_error"},
            {"task_type": "goal:x", "iteration": 3, "status": "success"},
        ]
        history = _build_history(completed, 5)
        assert history["goal:x"]["failures"] == 2

    def test_success_does_not_count_as_failure(self):
        completed = [{"task_type": "goal:y", "iteration": 1, "status": "success"}]
        history = _build_history(completed, 5)
        assert history["goal:y"]["failures"] == 0

    def test_missing_task_type_skipped(self):
        completed = [{"iteration": 1, "status": "success"}]
        history = _build_history(completed, 5)
        assert history == {}
