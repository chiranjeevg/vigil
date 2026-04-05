"""Git operations wrapper for safe version control during improvements."""

import logging
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)


class GitManager:
    def __init__(self, project_path: str, auto_init: bool = True):
        self._cwd = Path(project_path)
        if not (self._cwd / ".git").exists():
            if auto_init:
                log.info("No git repository found at %s — initializing", self._cwd)
                subprocess.run(
                    ["git", "init"],
                    cwd=self._cwd,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                subprocess.run(
                    ["git", "add", "-A"],
                    cwd=self._cwd,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                subprocess.run(
                    ["git", "commit", "-m", "Initial commit (auto-created by Vigil)"],
                    cwd=self._cwd,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                log.info("Git repository initialized with initial commit")
            else:
                raise RuntimeError(f"Not a git repository: {self._cwd}")

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self._cwd,
            capture_output=True,
            text=True,
            check=check,
        )

    def ensure_branch(self, branch_name: str) -> None:
        current = self.get_current_branch()
        if current == branch_name:
            return

        result = self._run("branch", "--list", branch_name, check=False)
        if branch_name in result.stdout:
            self._run("checkout", branch_name)
        else:
            self._run("checkout", "-b", branch_name)
        log.info("On branch %s", branch_name)

    def has_changes(self) -> bool:
        result = self._run("status", "--porcelain", check=False)
        return bool(result.stdout.strip())

    def revert_all(self) -> None:
        self._run("checkout", ".", check=False)
        # Do not remove .vigil-state/ — it is untracked and holds iteration logs;
        # `git clean -fd` would delete it and break StateManager on the next write.
        self._run(
            "clean",
            "-fd",
            "-e",
            ".vigil-state",
            check=False,
        )
        log.info("Reverted all working tree changes")

    def commit(self, message: str) -> None:
        self._run("add", "-A")
        result = self._run("commit", "-m", message, check=False)
        if result.returncode == 0:
            log.info("Committed: %s", message)
        else:
            log.warning("Nothing to commit or commit failed: %s", result.stderr.strip())

    def get_log(self, n: int = 20) -> list[dict]:
        sep = "---VIGIL-SEP---"
        fmt = f"%H{sep}%s{sep}%ai{sep}%an"
        result = self._run("log", f"-{n}", f"--pretty=format:{fmt}", check=False)
        if not result.stdout.strip():
            return []

        entries: list[dict] = []
        for line in result.stdout.strip().splitlines():
            parts = line.split(sep)
            if len(parts) == 4:
                entries.append(
                    {
                        "hash": parts[0],
                        "message": parts[1],
                        "date": parts[2],
                        "author": parts[3],
                    }
                )
        return entries

    def get_diff(self) -> str:
        result = self._run("diff", check=False)
        staged = self._run("diff", "--cached", check=False)
        return result.stdout + staged.stdout

    def get_current_branch(self) -> str:
        result = self._run("rev-parse", "--abbrev-ref", "HEAD", check=False)
        return result.stdout.strip()

    def lines_changed(self) -> int:
        diff_text = self.get_diff()
        count = 0
        for line in diff_text.splitlines():
            if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
                count += 1
        return count

    def files_changed(self) -> list[str]:
        result = self._run("diff", "--name-only", check=False)
        staged = self._run("diff", "--cached", "--name-only", check=False)
        untracked = self._run(
            "ls-files", "--others", "--exclude-standard", check=False
        )
        all_files = set()
        for output in (result.stdout, staged.stdout, untracked.stdout):
            for f in output.strip().splitlines():
                if f:
                    all_files.add(f)
        return sorted(all_files)

    def get_last_commit_hash(self) -> str:
        result = self._run("rev-parse", "HEAD", check=False)
        return result.stdout.strip()

    def get_commit_diff(self, commit_hash: str) -> str:
        result = self._run("show", commit_hash, "--format=", check=False)
        return result.stdout

    def get_commit_files(self, commit_hash: str) -> list[str]:
        result = self._run("show", commit_hash, "--name-only", "--format=", check=False)
        return [f for f in result.stdout.strip().splitlines() if f]

    def has_remote(self) -> bool:
        result = self._run("remote", check=False)
        return bool(result.stdout.strip())

    def get_remote_url(self) -> str | None:
        result = self._run("remote", "get-url", "origin", check=False)
        if result.returncode == 0:
            return result.stdout.strip()
        return None
