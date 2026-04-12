"""PRDScanner — scans markdown design docs for actionable TODO / action items.

Reads markdown files from ``work_sources.prd_paths`` and extracts lines that
look like pending work.  The extraction is purely static (regex) with no LLM
call, so it runs instantly and never blocks an iteration.

Each extracted item becomes a ``WorkItem`` of type ``feature`` with the PRD
file set as a ``context_docs`` entry so the LLM receives the full requirements
context during the iteration.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from vigil.core.work_sources.base import WorkItem, WorkSource

log = logging.getLogger(__name__)

# Patterns that signal an actionable line in a markdown doc
_ACTIONABLE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^\s*-\s*\[\s*\]\s+(.+)$", re.MULTILINE),   # - [ ] task
    re.compile(r"^\s*TODO[:\s]+(.+)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*FIXME[:\s]+(.+)$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*\*\*Action\*\*[:\s]+(.+)$", re.MULTILINE),  # **Action**: ...
]

# Cap per file to avoid polluting the queue from one large PRD
_MAX_ITEMS_PER_FILE = 10


class PRDScanner(WorkSource):
    """Produces WorkItems by scanning PRD/design-doc markdown files."""

    def __init__(self, prd_paths: list[str], project_path: str) -> None:
        self._prd_paths = prd_paths
        self._project_path = Path(project_path)

    def name(self) -> str:
        return "prd_scanner"

    @property
    def is_enabled(self) -> bool:
        return bool(self._prd_paths)

    def poll(self) -> list[WorkItem]:
        items: list[WorkItem] = []
        for raw_path in self._prd_paths:
            path = Path(raw_path)
            if not path.is_absolute():
                path = self._project_path / raw_path
            try:
                extracted = self._scan_file(path)
                items.extend(extracted)
                log.debug("PRDScanner: %d items from %s", len(extracted), path.name)
            except Exception as exc:
                log.warning("PRDScanner: failed to scan %s — %s", raw_path, exc)
        return items

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _scan_file(self, path: Path) -> list[WorkItem]:
        if not path.exists():
            log.warning("PRDScanner: file not found — %s", path)
            return []

        text = path.read_text(errors="replace")
        seen: set[str] = set()
        items: list[WorkItem] = []
        rel_path = str(path)
        try:
            rel_path = str(path.relative_to(self._project_path))
        except ValueError:
            pass

        for pattern in _ACTIONABLE_PATTERNS:
            for match in pattern.finditer(text):
                title = match.group(1).strip()
                # Normalise — strip trailing punctuation and markdown bold/italic
                title = re.sub(r"[*_`]", "", title).strip(" .")
                if not title or title.lower() in seen:
                    continue
                seen.add(title.lower())
                items.append(
                    WorkItem(
                        id=f"prd:{path.stem}:{len(items)}",
                        source="prd_scanner",
                        work_type="feature",
                        title=title[:80],
                        description=f"From {path.name}: {title}",
                        priority=3,
                        context_files=[],
                        # Attach the PRD itself so the LLM reads requirements
                        context_docs=[rel_path],
                        instructions=(
                            f"Implement the following item from {path.name}:\n\n{title}\n\n"
                            f"Refer to the attached document for full requirements."
                        ),
                        metadata={"prd_file": rel_path},
                    )
                )
                if len(items) >= _MAX_ITEMS_PER_FILE:
                    break
            if len(items) >= _MAX_ITEMS_PER_FILE:
                break

        return items
