"""WorktreeManager validation and git version gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from vigil.core.worktree import WorktreeManager, _parse_git_version, require_git_worktree_support


def test_parse_git_version() -> None:
    assert _parse_git_version("git version 2.44.0") == (2, 44)
    assert _parse_git_version("git version 1.0.0") == (1, 0)
    assert _parse_git_version("nope") is None


def test_worktree_manager_requires_git_dir(tmp_path: Path) -> None:
    d = tmp_path / "not_git"
    d.mkdir()
    with pytest.raises(RuntimeError, match="Not a git repository"):
        WorktreeManager(str(d))


def test_require_git_worktree_support_passes() -> None:
    """Smoke: real environment has git 2.5+."""
    require_git_worktree_support()
