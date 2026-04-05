"""Manages Git branches and GitHub Pull Requests for iteration changes."""

import logging
import re
import subprocess
from pathlib import Path

from vigil.config import PRConfig

log = logging.getLogger(__name__)


def _slugify(text: str, max_len: int = 50) -> str:
    """Convert free text into a git-branch-safe slug."""
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:max_len].rstrip("-")


def _task_type_prefix(task_type: str) -> str:
    """Map task type to conventional branch prefix."""
    prefixes = {
        "optimize_performance": "perf",
        "fix_tests": "fix",
        "test_coverage": "test",
        "modernize_code": "refactor",
        "reduce_complexity": "refactor",
        "refactor": "refactor",
    }
    return prefixes.get(task_type, "improve")


class PRManager:
    """Manages per-iteration Git branches and GitHub pull requests.

    Implements an *iterative branching* strategy: each new iteration
    branches off the previous successful iteration's branch so that
    improvements stack on top of each other and never conflict.
    """

    def __init__(self, project_path: str, config: PRConfig):
        self._cwd = Path(project_path)
        self._config = config
        self._last_successful_branch: str | None = None

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self._cwd,
            capture_output=True,
            text=True,
            check=check,
        )

    def has_remote(self) -> bool:
        result = self._git("remote", check=False)
        return bool(result.stdout.strip())

    def gh_authenticated(self) -> bool:
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0

    def preflight_check(self) -> tuple[bool, str]:
        """Check that PR workflow prerequisites are met."""
        if not self.has_remote():
            return False, "No git remote configured. Add a remote with: git remote add origin <url>"

        try:
            result = subprocess.run(
                ["gh", "--version"], capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return False, "GitHub CLI (gh) is not installed. Install from: https://cli.github.com"
        except FileNotFoundError:
            return False, "GitHub CLI (gh) is not installed. Install from: https://cli.github.com"

        if not self.gh_authenticated():
            return False, "GitHub CLI is not authenticated. Run: gh auth login"

        return True, "PR workflow ready"

    @property
    def parent_branch(self) -> str:
        """The branch to fork from: last successful iteration branch, or base_branch."""
        return self._last_successful_branch or self._config.base_branch

    def create_iteration_branch(
        self, iteration: int, task_type: str, task_description: str = ""
    ) -> str:
        """Create a descriptive feature branch from the parent branch.

        The parent is the last successful iteration's branch (so
        improvements accumulate), or base_branch if this is the first
        iteration or no previous success exists.
        """
        prefix = _task_type_prefix(task_type)
        desc_slug = _slugify(task_description) if task_description else _slugify(task_type)
        branch = f"vigil/{prefix}/{desc_slug}-{iteration}"

        parent = self.parent_branch
        if not self.local_branch_exists(parent):
            raise RuntimeError(
                f"Cannot create iteration branch: base branch {parent!r} does not exist locally. "
                f"Check out or create it, or set pr.base_branch in vigil.yaml (e.g. main or master)."
            )
        co = self._git("checkout", parent, check=False)
        if co.returncode != 0:
            err = (co.stderr or co.stdout or "").strip()
            raise RuntimeError(f"git checkout {parent!r} failed: {err}")

        self._git("pull", "--ff-only", check=False)

        nb = self._git("checkout", "-b", branch, check=False)
        if nb.returncode != 0:
            err = (nb.stderr or nb.stdout or "").strip()
            raise RuntimeError(f"git checkout -b {branch!r} failed: {err}")

        log.info("Created branch %s (from %s)", branch, parent)
        return branch

    def set_last_successful_branch(self, branch: str | None) -> None:
        """Restore chain pointer (e.g. after restart from disk) without logging."""
        self._last_successful_branch = branch

    def local_branch_exists(self, name: str) -> bool:
        """True if a local branch named `name` exists."""
        r = self._git("rev-parse", "--verify", f"refs/heads/{name}", check=False)
        return r.returncode == 0

    def mark_success(self, branch: str) -> None:
        """Record this branch as the latest successful iteration.

        The next iteration will branch from here so it inherits all
        accumulated improvements.
        """
        self._last_successful_branch = branch
        log.info("Marked %s as latest successful branch — next iteration will fork from here", branch)

    def push_and_create_pr(self, branch: str, title: str, body: str) -> str | None:
        """Push branch and open a GitHub PR. Returns the PR URL or None."""
        push_result = self._git("push", "-u", "origin", branch, check=False)
        if push_result.returncode != 0:
            log.error("git push failed: %s", push_result.stderr.strip())
            return None

        cmd = [
            "gh", "pr", "create",
            "--base", self._config.base_branch,
            "--head", branch,
            "--title", title,
            "--body", body,
        ]
        for label in self._config.labels:
            cmd += ["--label", label]
        for reviewer in self._config.reviewers:
            cmd += ["--reviewer", reviewer]

        result = subprocess.run(
            cmd, cwd=self._cwd, capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            pr_url = result.stdout.strip()
            log.info("PR created: %s", pr_url)
            return pr_url

        log.error("gh pr create failed: %s", result.stderr.strip())
        return None

    def cleanup_branch(self, branch: str) -> None:
        """Abort: switch to parent branch and delete the failed iteration branch."""
        parent = self.parent_branch
        self._git("checkout", parent, check=False)
        self._git("branch", "-D", branch, check=False)
        log.info("Cleaned up failed branch %s — returned to %s", branch, parent)

    def return_to_base(self) -> None:
        """Switch back to base branch (used after PR creation)."""
        self._git("checkout", self._config.base_branch, check=False)

    def stay_on_branch(self, branch: str) -> None:
        """Stay on the given branch (for iterative stacking)."""
        self._git("checkout", branch, check=False)
