"""Persistent merge worktree: integrates successful iteration branches into work_branch."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from vigil.core.state_paths import stable_project_hash

log = logging.getLogger(__name__)


@dataclass
class MergeResult:
    success: bool
    conflict_files: list[str]
    message: str
    commit_hash: str | None


class MergeQueue:
    """A dedicated worktree checked out on ``target_branch`` for serial merges."""

    def __init__(
        self,
        project_path: str,
        target_branch: str,
        *,
        base_if_missing: str = "main",
    ) -> None:
        self._repo = Path(project_path).resolve()
        self._target_branch = target_branch
        self._base_if_missing = base_if_missing
        h = stable_project_hash(str(self._repo))
        self._wt_path = Path.home() / ".vigil" / "merge" / h

    def _git(
        self, *args: str, cwd: Path | None = None, check: bool = False
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self._repo,
            capture_output=True,
            text=True,
            check=check,
        )

    def ensure_worktree(self) -> None:
        """Create the merge worktree on ``target_branch`` if missing."""
        git_marker = self._wt_path / ".git"
        if self._wt_path.exists() and git_marker.exists():
            return
        if self._wt_path.exists() and not git_marker.exists():
            shutil.rmtree(self._wt_path, ignore_errors=True)
        self._wt_path.parent.mkdir(parents=True, exist_ok=True)
        # Branch exists locally?
        r = self._git(
            "rev-parse",
            "--verify",
            f"refs/heads/{self._target_branch}",
            check=False,
        )
        if r.returncode == 0:
            co = self._git(
                "worktree",
                "add",
                str(self._wt_path),
                self._target_branch,
                check=False,
            )
        else:
            start = self._base_if_missing
            sr = self._git("rev-parse", "--verify", f"refs/heads/{start}", check=False)
            if sr.returncode != 0:
                raise RuntimeError(
                    f"Cannot create merge queue: branch {start!r} does not exist locally. "
                    f"Create {self._target_branch!r} or fetch {start}."
                )
            co = self._git(
                "worktree",
                "add",
                str(self._wt_path),
                "-b",
                self._target_branch,
                start,
                check=False,
            )
        if co.returncode != 0:
            err = (co.stderr or co.stdout or "").strip()
            raise RuntimeError(f"Merge worktree setup failed: {err}")
        log.info("Merge queue worktree at %s (branch %s)", self._wt_path, self._target_branch)

    def current_head(self) -> str:
        """HEAD SHA of the merge worktree (empty if not created yet)."""
        if not self._wt_path.exists() or not (self._wt_path / ".git").exists():
            return ""
        r = self._git("rev-parse", "HEAD", cwd=self._wt_path, check=False)
        return r.stdout.strip() if r.returncode == 0 else ""

    def try_merge(self, branch: str, *, merge_message: str) -> MergeResult:
        """``git merge --no-ff`` ``branch`` into the merge worktree; abort on conflict."""
        self.ensure_worktree()
        cwd = self._wt_path
        self._git("merge", "--abort", cwd=cwd, check=False)
        # Best-effort sync with remote (ignore failure)
        self._git("pull", "--ff-only", "origin", self._target_branch, cwd=cwd, check=False)

        mr = self._git(
            "merge",
            "--no-ff",
            branch,
            "-m",
            merge_message,
            cwd=cwd,
            check=False,
        )
        if mr.returncode == 0:
            hr = self._git("rev-parse", "HEAD", cwd=cwd, check=False)
            sha = hr.stdout.strip() if hr.returncode == 0 else None
            return MergeResult(
                success=True,
                conflict_files=[],
                message="merged",
                commit_hash=sha,
            )

        # Conflicts
        conflicts: list[str] = []
        unst = self._git("diff", "--name-only", "--diff-filter=U", cwd=cwd, check=False)
        if unst.stdout.strip():
            conflicts = [x.strip() for x in unst.stdout.splitlines() if x.strip()]

        self._git("merge", "--abort", cwd=cwd, check=False)
        err = (mr.stderr or mr.stdout or "").strip()
        return MergeResult(
            success=False,
            conflict_files=conflicts,
            message=err or "merge failed",
            commit_hash=None,
        )

    def parse_conflict_paths(self, stderr: str) -> list[str]:
        """Extract paths from conflicted merge output (fallback)."""
        paths: list[str] = []
        for line in (stderr or "").splitlines():
            m = re.match(r"^\s*([^#\s].+)$", line)
            if m and not line.startswith("CONFLICT"):
                p = m.group(1).strip()
                if p and p not in paths:
                    paths.append(p)
        return paths
