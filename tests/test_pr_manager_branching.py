"""Git branching behavior: each PR iteration forks from the previous successful branch."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from vigil.config import PRConfig
from vigil.core.pr_manager import PRManager
from vigil.core.state import StateManager


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


def test_each_iteration_branch_forks_from_previous_success(repo: Path) -> None:
    """After mark_success(b1), the next create_iteration_branch uses b1 as parent."""
    cfg = PRConfig(base_branch="main")
    pm = PRManager(str(repo), cfg)

    b1 = pm.create_iteration_branch(1, "optimize_performance", "speed up")
    assert b1 == "vigil/perf/speed-up-1"

    pm.mark_success(b1)
    assert pm.parent_branch == b1

    b2 = pm.create_iteration_branch(2, "optimize_performance", "more speed")
    assert b2 == "vigil/perf/more-speed-2"
    assert pm.parent_branch == b1
    pm.mark_success(b2)
    assert pm.parent_branch == b2


def test_state_persists_last_successful_branch_across_state_manager_instances(
    repo: Path,
) -> None:
    sm1 = StateManager(str(repo))
    assert sm1.get_last_successful_branch() is None
    sm1.set_last_successful_branch("vigil/perf/foo-3")
    sm2 = StateManager(str(repo))
    assert sm2.get_last_successful_branch() == "vigil/perf/foo-3"
    sm2.set_last_successful_branch(None)
    sm3 = StateManager(str(repo))
    assert sm3.get_last_successful_branch() is None


def test_pr_manager_restores_chain_from_disk(repo: Path) -> None:
    """Simulate restart: new PRManager + state file should fork from saved branch."""
    cfg = PRConfig(base_branch="main")
    pm1 = PRManager(str(repo), cfg)
    b1 = pm1.create_iteration_branch(10, "fix_tests", "fix flaky")
    pm1.mark_success(b1)

    StateManager(str(repo)).set_last_successful_branch(b1)

    pm2 = PRManager(str(repo), cfg)
    restored = StateManager(str(repo)).get_last_successful_branch()
    assert restored == b1
    assert pm2.local_branch_exists(b1)
    pm2.set_last_successful_branch(restored)
    assert pm2.parent_branch == b1

    b2 = pm2.create_iteration_branch(11, "fix_tests", "another fix")
    assert b2.startswith("vigil/fix/")
    tip_b1 = subprocess.run(
        ["git", "rev-parse", b1],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    merge_base = subprocess.run(
        ["git", "merge-base", b1, b2],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert merge_base == tip_b1


def test_local_branch_exists(repo: Path) -> None:
    cfg = PRConfig(base_branch="main")
    pm = PRManager(str(repo), cfg)
    assert pm.local_branch_exists("main")
    assert not pm.local_branch_exists("nonexistent-branch-xyz")


def test_create_iteration_branch_requires_base_branch_locally(repo: Path) -> None:
    cfg = PRConfig(base_branch="nonexistent-base-xyz")
    pm = PRManager(str(repo), cfg)
    with pytest.raises(RuntimeError, match="base branch"):
        pm.create_iteration_branch(1, "optimize_performance", "x")
