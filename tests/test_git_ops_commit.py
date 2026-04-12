"""GitManager.commit excludes legacy .vigil-state paths from commits."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from vigil.core.git_ops import GitManager


def _git(cwd: Path, *args: str, check: bool = True) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=check, capture_output=True, text=True)


def _init_repo(path: Path) -> None:
    _git(path, "init")
    _git(path, "config", "user.email", "t@e.st")
    _git(path, "config", "user.name", "T")
    (path / "tracked.txt").write_text("x\n")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "init")
    _git(path, "branch", "-M", "main")


def test_commit_stages_tracked_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    gm = GitManager(str(tmp_path), auto_init=False)
    (tmp_path / "new.txt").write_text("y\n")
    gm.commit("add new")
    r = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "new.txt" in r.stdout


def test_commit_does_not_commit_vigil_state_when_untracked(tmp_path: Path) -> None:
    """Untracked .vigil-state is never added by commit (not in git add scope for ignored)."""
    _init_repo(tmp_path)
    vs = tmp_path / ".vigil-state"
    vs.mkdir()
    (vs / "iterations.json").write_text("[]")
    gm = GitManager(str(tmp_path), auto_init=False)
    (tmp_path / "a.txt").write_text("z\n")
    gm.commit("msg")
    r = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert ".vigil-state" not in r.stdout


def test_commit_unstages_tracked_vigil_state(tmp_path: Path) -> None:
    """If .vigil-state was committed historically, it is unstaged before commit."""
    _init_repo(tmp_path)
    vs = tmp_path / ".vigil-state"
    vs.mkdir()
    (vs / "x.json").write_text("{}")
    _git(tmp_path, "add", ".vigil-state")
    _git(tmp_path, "commit", "-m", "bad: track state")
    (tmp_path / "b.txt").write_text("q\n")
    gm = GitManager(str(tmp_path), auto_init=False)
    gm.commit("only b")
    r = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert "b.txt" in r.stdout
    assert ".vigil-state" not in r.stdout
