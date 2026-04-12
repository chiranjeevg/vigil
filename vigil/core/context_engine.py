"""Context engine — assembles the file and document context sent to the LLM.

Replaces the original ``Orchestrator._build_context`` method, which picked
files alphabetically.  This engine is task-aware:

1. If the task carries ``context_files`` (from a Goal or GitHub issue), those
   files are loaded first — they are the primary edit targets.
2. ``context_docs`` are read-only reference documents (PRDs, design specs)
   injected as a separate section so the LLM uses them as requirements.
3. ``global_docs`` from ``work_sources.context_documents`` (always attached to
   every iteration) keeps architectural context fresh.
4. When no explicit files are provided the engine falls back to smart sampling:
   - bug_fix / security → high-churn + high-complexity files (where defects hide)
   - feature / custom   → entry points + keyword-matched files from the repo map
   - improvement        → highest-complexity files (original behaviour, improved)

File content is capped at ``_FILE_CHAR_LIMIT`` to stay within the context
window; the full file tree (up to 200 lines) is always included for navigation.
"""

from __future__ import annotations

import logging
from pathlib import Path

from vigil.config import VigilConfig

log = logging.getLogger(__name__)

# Per-file character budget when loading content into the prompt.
# 10 000 chars ≈ ~2 500 tokens — keeps 10 files within a 32k context.
_FILE_CHAR_LIMIT = 10_000

# How many smart-sampled files to include when no explicit list is given
_SMART_SAMPLE_LIMIT = 10

# File extensions worth loading as source code
_SOURCE_EXTENSIONS = frozenset({
    ".py", ".ts", ".tsx", ".js", ".jsx",
    ".go", ".rs", ".java", ".kt", ".rb",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp",
    ".cs", ".swift", ".php",
})


class ContextEngine:
    """Builds the context dict that the orchestrator passes to the prompt builders."""

    def __init__(self, config: VigilConfig) -> None:
        self._config = config
        self._project_path = Path(config.project.path)
        # Cache the deep-analysis phase-1 data so we only compute it once per
        # run.  It's a pure read of disk/git so stale data is acceptable — we
        # reset the cache when the orchestrator is reconfigured.
        self._phase1_cache: dict | None = None

    def invalidate_cache(self) -> None:
        """Call after a project switch to force re-analysis on the next poll."""
        self._phase1_cache = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        task: dict,
        progress_summary: str,
        recent_benchmarks: list[dict],
        completed_tasks: list[dict],
        *,
        project_root: Path | str | None = None,
    ) -> dict:
        """Return the full context dict for ``get_task_prompt``.

        When ``project_root`` is set (e.g. git worktree path), file reads use that
        tree instead of ``config.project.path`` — keeps LLM context aligned with
        the iteration workspace.
        """
        if project_root is not None:
            root = Path(project_root)
            old_path = self._project_path
            old_cache = self._phase1_cache
            self._project_path = root
            self._phase1_cache = None
            try:
                return self._build_inner(
                    task,
                    progress_summary,
                    recent_benchmarks,
                    completed_tasks,
                )
            finally:
                self._project_path = old_path
                self._phase1_cache = old_cache
        return self._build_inner(
            task,
            progress_summary,
            recent_benchmarks,
            completed_tasks,
        )

    def _build_inner(
        self,
        task: dict,
        progress_summary: str,
        recent_benchmarks: list[dict],
        completed_tasks: list[dict],
    ) -> dict:
        context: dict = {
            "file_tree": self._get_file_tree(),
            "progress_summary": progress_summary,
            "recent_benchmarks": recent_benchmarks,
            "completed_tasks": completed_tasks,
        }

        context["file_contents"] = self._load_file_contents(task)
        context["reference_docs"] = self._load_reference_docs(task)

        return context

    # ------------------------------------------------------------------
    # File content loading
    # ------------------------------------------------------------------

    def _load_file_contents(self, task: dict) -> dict[str, str]:
        """Return {rel_path: content} for the files most relevant to this task."""
        explicit = task.get("context_files") or task.get("target_files") or []
        if explicit:
            return self._read_named_files(explicit)

        return self._smart_sample(task)

    def _read_named_files(self, paths: list[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        for rel in paths:
            full = self._project_path / rel
            if full.exists() and full.is_file():
                try:
                    result[rel] = full.read_text(errors="replace")[:_FILE_CHAR_LIMIT]
                except OSError as exc:
                    log.warning("ContextEngine: cannot read %s — %s", rel, exc)
        return result

    def _smart_sample(self, task: dict) -> dict[str, str]:
        """Pick files intelligently based on task type using phase-1 signals."""
        work_type = task.get("work_type", task.get("type", "improvement"))

        if work_type in ("bug_fix", "security"):
            candidates = self._churn_and_complexity_files()
        elif work_type in ("feature", "custom", "test"):
            candidates = self._keyword_matched_files(task)
        else:
            # improvement, refactor, etc. — use highest-complexity files
            candidates = self._complexity_ranked_files()

        return self._read_named_files(candidates[:_SMART_SAMPLE_LIMIT])

    def _churn_and_complexity_files(self) -> list[str]:
        """Return files with both high git churn and high complexity — bug hotspots."""
        phase1 = self._get_phase1()
        if phase1 is None:
            return self._fallback_files()

        churn_set = {item["file"] for item in phase1.get("git_churn", [])[:20]}
        complex_files = [c["file"] for c in phase1.get("complexity", [])[:20]]

        # Intersection first (both signals), then churn-only, then complexity-only
        both = [f for f in complex_files if f in churn_set]
        churn_only = [f for f in phase1.get("git_churn", []) if f["file"] not in set(both)]
        complex_only = [f for f in complex_files if f not in set(both)]

        ordered: list[str] = both
        ordered += [f["file"] for f in churn_only[:5]]
        ordered += complex_only[:5]
        return [f for f in ordered if self._is_source_file(f)]

    def _keyword_matched_files(self, task: dict) -> list[str]:
        """Match files against keywords in the task title/description."""
        phase1 = self._get_phase1()
        description = (
            (task.get("title") or "") + " " + (task.get("description") or "")
        ).lower()

        if phase1 is not None:
            repo_map = phase1.get("repo_map", "")
            keywords = _extract_keywords(description)
            matched: list[str] = []
            for line in repo_map.splitlines():
                # repo_map lines are "path/to/file.py  def func_name(..."
                if any(kw in line.lower() for kw in keywords):
                    # Extract just the file path (first token)
                    parts = line.split()
                    if parts:
                        candidate = parts[0]
                        if self._is_source_file(candidate):
                            matched.append(candidate)
            if matched:
                # Deduplicate while preserving order
                seen: set[str] = set()
                deduped = []
                for f in matched:
                    if f not in seen:
                        seen.add(f)
                        deduped.append(f)
                return deduped

        # Fallback: entry points are good starting points for new features
        if phase1 is not None:
            entry = [ep["file"] for ep in phase1.get("entry_points", [])[:5]]
            if entry:
                return entry

        return self._fallback_files()

    def _complexity_ranked_files(self) -> list[str]:
        """Return the most complex files — best for refactor / improvement tasks."""
        phase1 = self._get_phase1()
        if phase1 is None:
            return self._fallback_files()
        return [
            c["file"]
            for c in phase1.get("complexity", [])
            if self._is_source_file(c["file"])
        ]

    def _fallback_files(self) -> list[str]:
        """Alphabetical scan of include_paths — original behaviour, last resort."""
        result: list[str] = []
        for inc in self._config.project.include_paths:
            inc_path = self._project_path / inc
            if not inc_path.exists():
                continue
            for f in sorted(inc_path.rglob("*")):
                if f.is_file() and not self._is_excluded(f):
                    rel = str(f.relative_to(self._project_path))
                    if self._is_source_file(rel):
                        result.append(rel)
                        if len(result) >= _SMART_SAMPLE_LIMIT:
                            return result
        return result

    # ------------------------------------------------------------------
    # Reference document loading (read-only, for requirements context)
    # ------------------------------------------------------------------

    def _load_reference_docs(self, task: dict) -> dict[str, str]:
        """Load PRDs / design docs attached to the task or configured globally."""
        doc_paths: list[str] = list(task.get("context_docs") or [])

        # Global context documents are always included (project architecture, etc.)
        doc_paths += self._config.work_sources.context_documents

        if not doc_paths:
            return {}

        docs: dict[str, str] = {}
        for raw in doc_paths:
            path = Path(raw)
            if not path.is_absolute():
                path = self._project_path / raw
            if not path.exists():
                log.warning("ContextEngine: reference doc not found — %s", raw)
                continue
            try:
                # Allow slightly larger budget for docs since they are read-only
                docs[raw] = path.read_text(errors="replace")[:15_000]
            except OSError as exc:
                log.warning("ContextEngine: cannot read doc %s — %s", raw, exc)
        return docs

    # ------------------------------------------------------------------
    # File tree (always included for navigation)
    # ------------------------------------------------------------------

    def _get_file_tree(self) -> str:
        lines: list[str] = []
        for inc in self._config.project.include_paths:
            inc_path = self._project_path / inc
            if not inc_path.exists():
                continue
            for f in sorted(inc_path.rglob("*")):
                if f.is_file() and not self._is_excluded(f):
                    lines.append(str(f.relative_to(self._project_path)))
        return "\n".join(lines[:200])

    # ------------------------------------------------------------------
    # Phase-1 deep analysis (lazy + cached)
    # ------------------------------------------------------------------

    def _get_phase1(self) -> dict | None:
        if self._phase1_cache is not None:
            return self._phase1_cache
        try:
            from vigil.core.deep_analysis import run_phase1
            self._phase1_cache = run_phase1(str(self._project_path))
            log.debug(
                "ContextEngine: phase-1 analysis complete (%d files, %d todos)",
                self._phase1_cache.get("source_file_count", 0),
                len(self._phase1_cache.get("todos", [])),
            )
            return self._phase1_cache
        except Exception as exc:
            log.warning("ContextEngine: phase-1 analysis failed — %s", exc)
            return None

    # ------------------------------------------------------------------
    # Path utilities
    # ------------------------------------------------------------------

    def _is_excluded(self, filepath: Path) -> bool:
        try:
            rel = str(filepath.relative_to(self._project_path))
        except ValueError:
            return True
        for exc in self._config.project.exclude_paths:
            if rel.startswith(exc) or f"/{exc}" in rel:
                return True
        return False

    def _is_source_file(self, rel_path: str) -> bool:
        return Path(rel_path).suffix in _SOURCE_EXTENSIONS


def _extract_keywords(text: str) -> list[str]:
    """Pull the most meaningful words from a task description for file matching.

    Strips short words and common English stop words to reduce false positives.
    """
    stop_words = frozenset({
        "the", "a", "an", "and", "or", "for", "to", "in", "of", "with",
        "on", "at", "from", "by", "as", "is", "it", "be", "this", "that",
        "add", "fix", "update", "implement", "create", "build", "write",
        "new", "old", "use", "using", "into", "make",
    })
    words = [
        w.strip(".,;:!?\"'()")
        for w in text.split()
        if len(w) >= 4 and w.lower() not in stop_words
    ]
    # Deduplicate, preserve order
    seen: set[str] = set()
    result: list[str] = []
    for w in words:
        lw = w.lower()
        if lw not in seen:
            seen.add(lw)
            result.append(lw)
    return result[:15]
