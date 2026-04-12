"""GitHubIssueSource — polls GitHub Issues via the ``gh`` CLI.

We deliberately use ``gh`` (already a dependency for the PR workflow) rather
than the REST API so we need zero extra credentials: the user's existing
``gh auth`` session is sufficient.

Results are cached for ``poll_interval`` seconds so we never fire a network
call on every iteration tick.
"""

from __future__ import annotations

import json
import logging
import subprocess
import time
from typing import Any

from vigil.config import GitHubIssuesConfig
from vigil.core.work_sources.base import WorkItem, WorkSource

log = logging.getLogger(__name__)

# Labels that map to a known work_type.  Everything else is "feature".
_LABEL_WORK_TYPE: dict[str, str] = {
    "bug": "bug_fix",
    "security": "security",
    "vulnerability": "security",
    "test": "test",
    "enhancement": "feature",
    "feature": "feature",
    "p0": "bug_fix",
    "p1": "bug_fix",
}


class GitHubIssueSource(WorkSource):
    """Imports open GitHub issues as ``WorkItem``s.

    Only ``gh`` subprocess calls are made; no third-party HTTP libraries needed.
    The cache prevents hammering the API on every iteration cycle.
    """

    def __init__(self, config: GitHubIssuesConfig) -> None:
        self._config = config
        self._cache: list[WorkItem] = []
        self._last_poll: float = 0.0

    def name(self) -> str:
        return "github_issues"

    @property
    def is_enabled(self) -> bool:
        return self._config.enabled and bool(self._config.repos)

    def poll(self) -> list[WorkItem]:
        now = time.monotonic()
        if now - self._last_poll < self._config.poll_interval and self._cache:
            log.debug("GitHubIssueSource: serving %d items from cache", len(self._cache))
            return list(self._cache)

        items: list[WorkItem] = []
        for repo in self._config.repos:
            try:
                fetched = self._fetch_repo(repo)
                items.extend(fetched)
                log.info("GitHubIssueSource: %d issues from %s", len(fetched), repo)
            except Exception as exc:
                # Non-fatal: a single repo failure must not block the loop
                log.warning("GitHubIssueSource: failed to fetch %s — %s", repo, exc)

        # Honour max_tasks cap after aggregating all repos
        items = items[: self._config.max_tasks]
        self._cache = items
        self._last_poll = now
        return list(items)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_repo(self, repo: str) -> list[WorkItem]:
        """Return WorkItems for open issues in ``repo`` matching label filters."""
        cmd = [
            "gh", "issue", "list",
            "--repo", repo,
            "--state", "open",
            "--json", "number,title,body,labels,url",
            "--limit", str(self._config.max_tasks),
        ]
        if self._config.labels_include:
            # gh supports --label for a single label; repeat for OR semantics
            for lbl in self._config.labels_include:
                cmd += ["--label", lbl]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"gh exited {result.returncode}: {result.stderr.strip()[:200]}"
            )

        raw: list[dict[str, Any]] = json.loads(result.stdout or "[]")
        items: list[WorkItem] = []
        for issue in raw:
            labels = [lbl.get("name", "") for lbl in issue.get("labels", [])]
            if self._should_skip(labels):
                continue
            items.append(self._to_work_item(repo, issue, labels))
        return items

    def _should_skip(self, labels: list[str]) -> bool:
        label_set = {lbl.lower() for lbl in labels}
        return bool(label_set & {lbl.lower() for lbl in self._config.labels_exclude})

    def _to_work_item(
        self, repo: str, issue: dict[str, Any], labels: list[str]
    ) -> WorkItem:
        number = issue.get("number", 0)
        title = issue.get("title", "").strip()
        body = (issue.get("body") or "").strip()
        url = issue.get("url", "")
        label_set = {lbl.lower() for lbl in labels}

        work_type = "feature"
        for lbl, wt in _LABEL_WORK_TYPE.items():
            if lbl in label_set:
                work_type = wt
                break

        # Derive priority from P-labels; fall back to 3 (medium)
        priority = 3
        for p_lbl, p_val in [("p0", 1), ("p1", 1), ("p2", 2), ("p3", 3)]:
            if p_lbl in label_set:
                priority = p_val
                break

        description = f"GitHub issue {repo}#{number}: {title}"
        if body:
            description += f"\n\n{body[:1000]}"

        return WorkItem(
            id=f"github:{repo}#{number}",
            source="github_issues",
            work_type=work_type,  # type: ignore[arg-type]
            title=title[:80],
            description=description,
            priority=priority,
            context_files=[],
            context_docs=[],
            instructions=(
                f"Resolve GitHub issue {repo}#{number}.\n"
                f"Issue URL: {url}\n"
                f"Title: {title}\n\n"
                f"{body[:2000]}"
            ).strip(),
            metadata={
                "repo": repo,
                "number": number,
                "url": url,
                "labels": labels,
            },
        )
