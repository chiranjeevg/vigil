"""GitHub PR creation and push helpers (iteration branches are created via worktrees)."""

from __future__ import annotations

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
        "security_audit": "audit",
        "error_handling": "errors",
        "add_logging": "logging",
        "add_tests": "tests",
        "documentation": "docs",
        "fix_warnings": "lint",
        "type_safety": "types",
    }
    return prefixes.get(task_type, "improve")


def iteration_branch_name(
    iteration: int, task_type: str, task_description: str = ""
) -> str:
    """Stable branch name for a worktree iteration (forked from base/work_branch)."""
    prefix = _task_type_prefix(task_type)
    desc_slug = (
        _slugify(task_description) if task_description else _slugify(task_type)
    )
    return f"vigil/{prefix}/{desc_slug}-{iteration}"


class PRManager:
    """Push branches and open GitHub PRs (``gh``). Branches are created in worktrees."""

    def __init__(self, project_path: str, config: PRConfig) -> None:
        self._cwd = Path(project_path)
        self._config = config

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

    def preflight_push(self) -> tuple[bool, str]:
        """True when ``git push origin <branch>`` can be attempted (remote + git CLI)."""
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return False, "Git CLI is not working"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False, "Git CLI not found"

        if not self.has_remote():
            return False, "No git remote configured. Add a remote with: git remote add origin <url>"

        return True, "git push available"

    def preflight_gh_pr(self) -> tuple[bool, str]:
        """True when ``gh pr create`` can run (GitHub CLI installed and authenticated)."""
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

        return True, "gh pr create available"

    def preflight_check(self) -> tuple[bool, str]:
        """Full PR automation: push to origin plus ``gh pr create`` (both must succeed)."""
        push_ok, push_msg = self.preflight_push()
        gh_ok, gh_msg = self.preflight_gh_pr()
        if push_ok and gh_ok:
            return True, "PR workflow ready"
        parts = [m for ok, m in ((push_ok, push_msg), (gh_ok, gh_msg)) if not ok]
        return False, " ".join(parts)

    def local_branch_exists(self, name: str) -> bool:
        """True if a local branch named `name` exists."""
        r = self._git("rev-parse", "--verify", f"refs/heads/{name}", check=False)
        return r.returncode == 0

    def push_branch(self, branch: str) -> tuple[bool, str]:
        """Push ``branch`` to ``origin``. Returns (success, error_message)."""
        push_result = self._git("push", "-u", "origin", branch, check=False)
        if push_result.returncode != 0:
            err = (push_result.stderr or push_result.stdout or "").strip()
            log.error("git push failed: %s", err)
            return False, err or "git push failed"
        log.info("Pushed branch %s to origin", branch)
        return True, ""

    def create_pr_with_gh(self, branch: str, title: str, body: str) -> str | None:
        """Open a GitHub PR for an already-pushed branch. Returns PR URL or None."""
        cmd = [
            "gh",
            "pr",
            "create",
            "--base",
            self._config.base_branch,
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
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

    def push_and_create_pr(self, branch: str, title: str, body: str) -> str | None:
        """Push branch and open a GitHub PR. Returns the PR URL or None."""
        ok, _ = self.push_branch(branch)
        if not ok:
            return None
        return self.create_pr_with_gh(branch, title, body)
