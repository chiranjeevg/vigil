"""Parses LLM output and safely applies code changes via SEARCH/REPLACE blocks."""

import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)


def _strip_code_fences(text: str) -> str:
    """Remove markdown code fences that LLMs often wrap code in."""
    text = text.strip()
    text = re.sub(r"^```\w*\n", "", text)
    text = re.sub(r"\n```$", "", text)
    return text


def _is_placeholder_search(search: str) -> bool:
    """Detect if a SEARCH block is a placeholder (new file indicator)."""
    stripped = search.strip()
    if not stripped:
        return True
    placeholder_patterns = [
        r"^#.*no existing",
        r"^#.*new file",
        r"^#.*empty",
        r"^#.*placeholder",
        r"^//.*no existing",
        r"^//.*new file",
    ]
    for pattern in placeholder_patterns:
        if re.match(pattern, stripped, re.IGNORECASE):
            return True
    if len(stripped.splitlines()) <= 2 and len(stripped) < 50:
        non_comment = re.sub(r"^[#/\-*\s]+", "", stripped)
        if not non_comment or non_comment.lower() in ("none", "n/a", "empty"):
            return True
    return False


class CodeApplier:
    def __init__(self, project_path: str, read_only_paths: list[str] | None = None):
        self._root = Path(project_path)
        self._read_only = read_only_paths or []

    def _is_read_only(self, filepath: str) -> bool:
        for ro in self._read_only:
            if filepath == ro or filepath.startswith(ro):
                return True
        return False

    def parse_and_apply(self, llm_output: str) -> tuple[list[dict], list[str]]:
        """Returns (applied changes, paths skipped due to read_only_paths)."""
        changes: list[dict] = []
        blocked_readonly: list[str] = []

        sr_blocks = self._extract_search_replace(llm_output)
        for filepath, search, replace in sr_blocks:
            if self._is_read_only(filepath):
                blocked_readonly.append(filepath)
                log.warning("Blocked write to read-only path: %s", filepath)
                continue

            search = _strip_code_fences(search)
            replace = _strip_code_fences(replace)

            if self._apply_search_replace(filepath, search, replace):
                lines_changed = len(replace.splitlines()) + len(search.splitlines())
                changes.append(
                    {"file": filepath, "action": "search_replace", "lines_changed": lines_changed}
                )

        if not changes:
            file_blocks = self._extract_file_blocks(llm_output)
            for filepath, content in file_blocks:
                if self._is_read_only(filepath):
                    blocked_readonly.append(filepath)
                    log.warning("Blocked write to read-only path: %s", filepath)
                    continue
                full_path = self._root / filepath
                full_path.parent.mkdir(parents=True, exist_ok=True)
                old_lines = 0
                if full_path.exists():
                    old_lines = len(full_path.read_text().splitlines())
                full_path.write_text(content)
                new_lines = len(content.splitlines())
                changes.append(
                    {
                        "file": filepath,
                        "action": "write",
                        "lines_changed": abs(new_lines - old_lines) or new_lines,
                    }
                )

        return changes, blocked_readonly

    def _extract_file_blocks(self, text: str) -> list[tuple[str, str]]:
        pattern = r"```filepath:\s*(.+?)\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        results: list[tuple[str, str]] = []
        for filepath, content in matches:
            filepath = filepath.strip()
            if filepath and not filepath.startswith("/"):
                results.append((filepath, content))
        return results

    def _extract_search_replace(self, text: str) -> list[tuple[str, str, str]]:
        results: list[tuple[str, str, str]] = []

        file_header_pattern = r"===\s*FILE:\s*(.+?)\s*==="
        sr_pattern = r"<{7}\s*SEARCH\n(.*?)\n={7}\n(.*?)\n>{7}\s*REPLACE"

        sections = re.split(file_header_pattern, text)

        i = 1
        while i + 1 < len(sections):
            filepath = sections[i].strip()
            block_text = sections[i + 1]
            for match in re.finditer(sr_pattern, block_text, re.DOTALL):
                results.append((filepath, match.group(1), match.group(2)))
            i += 2

        if not results:
            inline_pattern = (
                r"===\s*FILE:\s*(.+?)\s*===\s*\n"
                r"<{7}\s*SEARCH\n(.*?)\n={7}\n(.*?)\n>{7}\s*REPLACE"
            )
            for match in re.finditer(inline_pattern, text, re.DOTALL):
                results.append((match.group(1).strip(), match.group(2), match.group(3)))

        return results

    def _apply_search_replace(self, filepath: str, search: str, replace: str) -> bool:
        full_path = self._root / filepath

        if _is_placeholder_search(search):
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(replace)
            log.info("Created new file: %s", filepath)
            return True

        if not full_path.exists():
            log.warning("File not found for search/replace: %s", filepath)
            return False

        content = full_path.read_text()

        if search in content:
            content = content.replace(search, replace, 1)
            full_path.write_text(content)
            log.info("Applied search/replace to %s", filepath)
            return True

        normalized_content = re.sub(r"[ \t]+", " ", content)
        normalized_search = re.sub(r"[ \t]+", " ", search)
        if normalized_search in normalized_content:
            idx = normalized_content.index(normalized_search)
            orig_start = self._map_norm_to_orig(content, normalized_content, idx)
            orig_end = self._map_norm_to_orig(
                content, normalized_content, idx + len(normalized_search)
            )
            content = content[:orig_start] + replace + content[orig_end:]
            full_path.write_text(content)
            log.info("Applied search/replace (normalized) to %s", filepath)
            return True

        search_lines = [line.strip() for line in search.splitlines() if line.strip()]
        content_lines = content.splitlines()
        match_start = None
        match_end = None
        si = 0
        for ci, line in enumerate(content_lines):
            if si < len(search_lines) and line.strip() == search_lines[si]:
                if si == 0:
                    match_start = ci
                si += 1
                if si == len(search_lines):
                    match_end = ci + 1
                    break

        if match_start is not None and match_end is not None:
            new_lines = content_lines[:match_start] + replace.splitlines() + content_lines[match_end:]
            full_path.write_text("\n".join(new_lines) + "\n")
            log.info("Applied search/replace (line-level match) to %s", filepath)
            return True

        log.warning("Search block not found in %s", filepath)
        return False

    @staticmethod
    def _map_norm_to_orig(original: str, normalized: str, norm_idx: int) -> int:
        oi = 0
        ni = 0
        while ni < norm_idx and oi < len(original):
            if original[oi] in " \t":
                while oi + 1 < len(original) and original[oi + 1] in " \t":
                    oi += 1
            oi += 1
            ni += 1
        return oi

    def validate_changes(
        self, changes: list[dict], max_files: int, max_lines: int
    ) -> bool:
        if len(changes) > max_files:
            log.warning("Too many files changed: %d > %d", len(changes), max_files)
            return False
        total_lines = sum(c.get("lines_changed", 0) for c in changes)
        if total_lines > max_lines:
            log.warning("Too many lines changed: %d > %d", total_lines, max_lines)
            return False
        return True
