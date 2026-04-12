"""MergeQueue — merge iteration branches into work_branch."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from vigil.core.merge_queue import MergeQueue


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


def test_merge_queue_ff_merge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    _git(repo, "checkout", "-b", "vigil-work", "main")
    _git(repo, "checkout", "main")

    _git(repo, "checkout", "-b", "vigil/feat/sample-1", "main")
    (repo / "feat.txt").write_text("x\n")
    _git(repo, "add", "feat.txt")
    _git(repo, "commit", "-m", "feat")
    _git(repo, "checkout", "main")

    mq = MergeQueue(str(repo), "vigil-work", base_if_missing="main")
    mq.ensure_worktree()
    r = mq.try_merge("vigil/feat/sample-1", merge_message="vigil: merge test")
    assert r.success
    assert r.commit_hash
