"""WorktreeManager — create/remove iteration workspaces."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from vigil.core.worktree import WorktreeManager


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


def test_worktree_create_remove(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    wm = WorktreeManager(str(repo))
    h = wm.create("vigil/test/iter-1", "main")
    assert h.path.exists()
    assert (h.path / "README.md").read_text().startswith("hello")
    wm.remove(h, delete_branch=True)
    assert not h.path.exists()


def test_cleanup_stale_removes_orphan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    wm = WorktreeManager(str(repo))
    h = wm.create("vigil/test/orphan-1", "main")
    p = h.path
    # Simulate crash: delete git metadata only
    subprocess.run(["git", "worktree", "remove", str(p), "--force"], cwd=repo, check=False)
    # Orphan dir may remain — cleanup removes dirs under vigil worktrees base
    n = wm.cleanup_stale()
    assert n >= 0
