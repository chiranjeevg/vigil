"""MergeQueue conflict handling and branch creation from base."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from vigil.core.merge_queue import MergeQueue


def _git(cwd: Path, *args: str, check: bool = True) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "t@e.st")
    _git(path, "config", "user.name", "T")
    (path / "README.md").write_text("base\n")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "init")
    _git(path, "branch", "-M", "main")


def test_merge_conflict_returns_failure_and_aborts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Two branches touching the same line produce merge --abort and MergeResult.success False."""
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "r"
    repo.mkdir()
    _init_repo(repo)

    _git(repo, "checkout", "-b", "vigil-work", "main")
    _git(repo, "checkout", "main")

    _git(repo, "checkout", "-b", "vigil/a/conflict-1", "main")
    (repo / "shared.txt").write_text("AAA\n")
    _git(repo, "add", "shared.txt")
    _git(repo, "commit", "-m", "a")
    _git(repo, "checkout", "main")

    _git(repo, "checkout", "-b", "vigil/b/conflict-2", "main")
    (repo / "shared.txt").write_text("BBB\n")
    _git(repo, "add", "shared.txt")
    _git(repo, "commit", "-m", "b")
    _git(repo, "checkout", "main")

    mq = MergeQueue(str(repo), "vigil-work", base_if_missing="main")
    mq.ensure_worktree()
    r1 = mq.try_merge("vigil/a/conflict-1", merge_message="merge a")
    assert r1.success

    r2 = mq.try_merge("vigil/b/conflict-2", merge_message="merge b")
    assert r2.success is False
    assert r2.commit_hash is None
    assert "shared.txt" in r2.conflict_files or "merge" in r2.message.lower()

    # Merge worktree should not be stuck mid-merge
    wt = mq._wt_path
    st = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=wt,
        capture_output=True,
        text=True,
        check=False,
    )
    assert "UU" not in st.stdout


def test_ensure_worktree_creates_target_from_base_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When target branch does not exist, create it from base_if_missing."""
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "r2"
    repo.mkdir()
    _init_repo(repo)

    mq = MergeQueue(str(repo), "brand-new-work", base_if_missing="main")
    mq.ensure_worktree()
    assert mq._wt_path.exists()
    r = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=mq._wt_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert r.stdout.strip() == "brand-new-work"


def test_current_head_empty_when_merge_dir_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "r3"
    repo.mkdir()
    _init_repo(repo)
    mq = MergeQueue(str(repo), "w", base_if_missing="main")
    assert mq.current_head() == ""


def test_parse_conflict_paths_helper(tmp_path: Path) -> None:
    repo = tmp_path / "rx"
    repo.mkdir()
    _init_repo(repo)
    mq = MergeQueue(str(repo), "w", base_if_missing="main")
    assert mq.parse_conflict_paths("") == []
