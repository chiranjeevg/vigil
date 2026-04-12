"""Git worktrees for isolated iteration workspaces (no checkout in the main tree)."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from vigil.core.state_paths import stable_project_hash

log = logging.getLogger(__name__)

_MIN_GIT_VERSION = (2, 5)


def _parse_git_version(text: str) -> tuple[int, int] | None:
    m = re.search(r"git version (\d+)\.(\d+)", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def require_git_worktree_support() -> None:
    """Raise RuntimeError if git is missing or too old for `git worktree add`."""
    try:
        r = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise RuntimeError("Git is required for Vigil worktree isolation.") from e
    if r.returncode != 0:
        raise RuntimeError("Git is required for Vigil worktree isolation.")
    ver = _parse_git_version(r.stdout or "")
    if ver is None or ver < _MIN_GIT_VERSION:
        raise RuntimeError(
            "Git 2.5+ is required for worktree isolation (need `git worktree`). "
            "Upgrade Git or use an older Vigil release."
        )


@dataclass(frozen=True)
class WorktreeHandle:
    """A disposable iteration worktree."""

    path: Path
    branch: str


class WorktreeManager:
    """Creates/removes iteration worktrees under ~/.vigil/worktrees/<project-hash>/."""

    def __init__(self, project_path: str) -> None:
        self._repo = Path(project_path)
        if not (self._repo / ".git").exists():
            raise RuntimeError(f"Not a git repository: {self._repo}")
        h = stable_project_hash(str(self._repo.resolve()))
        self._base = Path.home() / ".vigil" / "worktrees" / h
        self._base.mkdir(parents=True, exist_ok=True)

    def _run(
        self, *args: str, cwd: Path | None = None, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self._repo,
            capture_output=True,
            text=True,
            check=check,
        )

    def create(self, branch_name: str, start_point: str) -> WorktreeHandle:
        """Create a new branch at ``start_point`` in a fresh worktree directory."""
        require_git_worktree_support()
        safe = re.sub(r"[^a-zA-Z0-9._-]", "-", branch_name)[:80]
        wt_path = self._base / safe
        n = 0
        while wt_path.exists():
            n += 1
            wt_path = self._base / f"{safe}-{n}"

        co = self._run(
            "worktree",
            "add",
            str(wt_path),
            "-b",
            branch_name,
            start_point,
            check=False,
        )
        if co.returncode != 0:
            err = (co.stderr or co.stdout or "").strip()
            raise RuntimeError(
                f"git worktree add failed for branch {branch_name!r}: {err}"
            )
        log.info("Worktree %s (branch %s from %s)", wt_path, branch_name, start_point)
        return WorktreeHandle(path=wt_path, branch=branch_name)

    def remove(self, handle: WorktreeHandle, *, delete_branch: bool = False) -> None:
        """Remove worktree directory; optionally delete the local branch."""
        p = handle.path
        if not p.exists():
            return
        r = self._run("worktree", "remove", str(p), "--force", check=False)
        if r.returncode != 0:
            log.warning(
                "git worktree remove failed for %s: %s — trying shutil.rmtree",
                p,
                (r.stderr or r.stdout or "").strip(),
            )
            try:
                shutil.rmtree(p, ignore_errors=True)
            except OSError:
                pass
        if delete_branch:
            self._run("branch", "-D", handle.branch, check=False)
        log.debug("Removed worktree %s (delete_branch=%s)", p, delete_branch)

    def cleanup_stale(self) -> int:
        """Remove orphaned worktrees under this project's vigil dir (e.g. after crash)."""
        removed = 0
        if not self._base.exists():
            return 0
        for child in sorted(self._base.iterdir()):
            if not child.is_dir():
                continue
            r = self._run("worktree", "remove", str(child), "--force", check=False)
            if r.returncode == 0:
                removed += 1
                continue
            # Not a registered worktree — best-effort delete
            try:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
            except OSError:
                pass
        if removed:
            self._run("worktree", "prune", check=False)
            log.info("Cleaned up %d stale worktree path(s) under %s", removed, self._base)
        return removed
