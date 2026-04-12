"""Tests for the work_sources package.

Covers GoalSource, PRDScanner, and work-item type inference.
GitHubIssueSource is excluded from unit tests because it invokes the
``gh`` CLI — integration tests for that should run in CI with a real token.
"""

import tempfile
from pathlib import Path

import pytest

from vigil.config import (
    GitHubIssuesConfig,
    GoalItem,
    GoalsConfig,
    PriorityMode,
    VigilConfig,
    WorkSourcesConfig,
)
from vigil.core.work_sources.goal_source import GoalSource, _infer_work_type
from vigil.core.work_sources.prd_scanner import PRDScanner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs) -> VigilConfig:
    return VigilConfig(project={"path": "/tmp/vigil-test", "name": "test"}, **kwargs)


# ---------------------------------------------------------------------------
# GoalSource
# ---------------------------------------------------------------------------

class TestGoalSource:
    def test_empty_goals_returns_empty(self):
        src = GoalSource(GoalsConfig(current=[]))
        assert src.poll() == []
        assert not src.is_enabled

    def test_single_goal_produces_one_item(self):
        goal = GoalItem(id="ws-feed", description="Implement WebSocket price feed")
        src = GoalSource(GoalsConfig(current=[goal]))
        items = src.poll()
        assert len(items) == 1
        item = items[0]
        assert item["id"] == "goal:ws-feed"
        assert item["source"] == "goal"
        assert item["priority"] == 1
        assert item["description"] == "Implement WebSocket price feed"

    def test_goal_with_context_files_propagates(self):
        goal = GoalItem(
            id="g1",
            description="Fix auth bug",
            context_files=["src/auth.py", "tests/test_auth.py"],
        )
        src = GoalSource(GoalsConfig(current=[goal]))
        item = src.poll()[0]
        assert item["context_files"] == ["src/auth.py", "tests/test_auth.py"]

    def test_goal_with_context_docs_propagates(self):
        goal = GoalItem(
            id="g2",
            description="Build settlement service",
            context_docs=["docs/settlement-prd.md"],
        )
        src = GoalSource(GoalsConfig(current=[goal]))
        item = src.poll()[0]
        assert item["context_docs"] == ["docs/settlement-prd.md"]

    def test_goal_issue_ref_in_metadata(self):
        goal = GoalItem(id="g3", description="Fix race", issue_ref="org/repo#42")
        src = GoalSource(GoalsConfig(current=[goal]))
        item = src.poll()[0]
        assert item["metadata"]["issue_ref"] == "org/repo#42"

    def test_multiple_goals_all_returned(self):
        goals = [GoalItem(id=f"g{i}", description=f"Goal {i}") for i in range(5)]
        src = GoalSource(GoalsConfig(current=goals))
        assert len(src.poll()) == 5

    def test_is_enabled_false_when_no_goals(self):
        src = GoalSource(GoalsConfig(current=[]))
        assert not src.is_enabled

    def test_is_enabled_true_when_goals_present(self):
        src = GoalSource(GoalsConfig(current=[GoalItem(id="x", description="foo")]))
        assert src.is_enabled


# ---------------------------------------------------------------------------
# _infer_work_type
# ---------------------------------------------------------------------------

class TestInferWorkType:
    @pytest.mark.parametrize("description,expected", [
        ("Fix settlement reconciliation race condition", "bug_fix"),
        ("Security vulnerability in auth module", "security"),
        ("Write tests for matching engine", "test"),
        ("Implement WebSocket price feed", "feature"),
        ("Add rate limiting to REST API", "feature"),
        ("Improve code readability", "custom"),
        ("XSS injection vulnerability", "security"),
    ])
    def test_infer(self, description: str, expected: str):
        assert _infer_work_type(description) == expected


# ---------------------------------------------------------------------------
# PRDScanner
# ---------------------------------------------------------------------------

class TestPRDScanner:
    def _make_prd(self, content: str, name: str = "test-prd.md") -> tuple[Path, str]:
        """Write content to a temp file, return (path, str(path))."""
        tmp = tempfile.NamedTemporaryFile(
            suffix=".md", delete=False, mode="w", prefix=name
        )
        tmp.write(content)
        tmp.close()
        return Path(tmp.name), tmp.name

    def test_empty_prd_returns_no_items(self):
        path, name = self._make_prd("# PRD\n\nSome intro text.\n")
        scanner = PRDScanner([name], "/tmp")
        assert scanner.poll() == []

    def test_checkbox_items_extracted(self):
        content = "# PRD\n\n- [ ] Implement WebSocket feed\n- [x] Done already\n"
        path, name = self._make_prd(content)
        scanner = PRDScanner([name], "/tmp")
        items = scanner.poll()
        assert len(items) == 1
        assert "WebSocket feed" in items[0]["title"]

    def test_todo_items_extracted(self):
        content = "# Design\n\nTODO: Add rate limiting\nTodo: Another one\n"
        path, name = self._make_prd(content)
        scanner = PRDScanner([name], "/tmp")
        items = scanner.poll()
        assert len(items) >= 1
        titles = [i["title"] for i in items]
        assert any("rate limiting" in t.lower() for t in titles)

    def test_context_doc_attached(self):
        content = "- [ ] Build order matching\n"
        path, name = self._make_prd(content)
        scanner = PRDScanner([name], "/tmp")
        items = scanner.poll()
        assert items[0]["context_docs"] == [name]

    def test_source_is_prd_scanner(self):
        content = "- [ ] Task one\n"
        _, name = self._make_prd(content)
        scanner = PRDScanner([name], "/tmp")
        items = scanner.poll()
        assert items[0]["source"] == "prd_scanner"

    def test_missing_file_returns_empty(self):
        scanner = PRDScanner(["/nonexistent/file.md"], "/tmp")
        # Must not raise
        assert scanner.poll() == []

    def test_max_items_per_file_respected(self):
        lines = "\n".join(f"- [ ] Task {i}" for i in range(20))
        content = f"# PRD\n\n{lines}\n"
        _, name = self._make_prd(content)
        scanner = PRDScanner([name], "/tmp")
        items = scanner.poll()
        # Default cap is 10
        assert len(items) <= 10

    def test_not_enabled_without_paths(self):
        scanner = PRDScanner([], "/tmp")
        assert not scanner.is_enabled


# ---------------------------------------------------------------------------
# Config: new fields round-trip through YAML
# ---------------------------------------------------------------------------

class TestConfigNewFields:
    def test_goals_default_empty(self):
        cfg = _make_config()
        assert cfg.goals.current == []

    def test_work_sources_default_empty(self):
        cfg = _make_config()
        assert not cfg.work_sources.github_issues.enabled
        assert cfg.work_sources.prd_paths == []
        assert cfg.work_sources.context_documents == []

    def test_priority_mode_default_improver(self):
        cfg = _make_config()
        assert cfg.tasks.priority_mode == PriorityMode.IMPROVER.value

    def test_engineer_mode_round_trip(self):
        cfg = _make_config(tasks={"priority_mode": "engineer"})
        assert cfg.tasks.priority_mode == PriorityMode.ENGINEER.value

    def test_goal_item_round_trip(self):
        raw = {
            "id": "auth-service",
            "description": "Implement JWT auth",
            "priority": 1,
            "context_files": ["src/auth.py"],
            "context_docs": ["docs/auth-prd.md"],
        }
        goal = GoalItem(**raw)
        assert goal.id == "auth-service"
        assert goal.context_files == ["src/auth.py"]
        assert goal.context_docs == ["docs/auth-prd.md"]
        assert goal.issue_ref is None

    def test_goal_priority_bounds_enforced(self):
        with pytest.raises(Exception):
            GoalItem(id="x", description="x", priority=0)
        with pytest.raises(Exception):
            GoalItem(id="x", description="x", priority=6)

    def test_github_issues_config_defaults(self):
        gh = GitHubIssuesConfig()
        assert not gh.enabled
        assert "wontfix" in gh.labels_exclude
        assert gh.max_tasks == 20
        assert gh.poll_interval == 300
