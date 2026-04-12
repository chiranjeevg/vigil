"""PR manager: branch naming and push/PR helpers (iterations use worktrees)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from vigil.config import PRConfig
from vigil.core.pr_manager import PRManager, iteration_branch_name


def _git(cwd: Path, *args: str, check: bool = True) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "README.md").write_text("hello\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "init")
    _git(path, "branch", "-M", "main")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    d = tmp_path / "repo"
    d.mkdir()
    _init_repo(d)
    return d


def test_iteration_branch_name_format() -> None:
    b = iteration_branch_name(7, "optimize_performance", "speed up")
    assert b == "vigil/perf/speed-up-7"


def test_iteration_branch_name_empty_description_uses_task_type() -> None:
    b = iteration_branch_name(3, "documentation", "")
    assert "vigil/docs/" in b
    assert b.endswith("-3")


def test_local_branch_exists(repo: Path) -> None:
    cfg = PRConfig(base_branch="main")
    pm = PRManager(str(repo), cfg)
    assert pm.local_branch_exists("main")
    assert not pm.local_branch_exists("nonexistent-branch-xyz")


def test_push_branch_requires_remote(repo: Path) -> None:
    cfg = PRConfig(base_branch="main")
    pm = PRManager(str(repo), cfg)
    ok, err = pm.push_branch("main")
    assert ok is False
    assert "remote" in err.lower() or "failed" in err.lower()
