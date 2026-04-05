"""
Phases 2–4: LLM-powered deep task suggestion pipeline.

Phase 2 — Architecture understanding (1 LLM call)
Phase 3 — Sequential deep code tracing (3-6 LLM calls)
Phase 4 — Task synthesis (1 LLM call)

Yields (event_type, data) tuples for streaming to the UI.
All LLM calls use the provider.complete(system, user) interface.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Generator

from vigil.config import DeepAnalysisProfile, ProviderConfig, resolve_deep_analysis_profile
from vigil.core.deep_analysis import (
    _safe_read,
    run_phase1,
)

log = logging.getLogger(__name__)

# LLMs often copy schema placeholders literally (e.g. "slug" for type).
_BAD_TASK_TYPE_KEYS = frozenset(
    {"slug", "title", "type", "task", "label", "unknown", "name", "id"},
)


def _slug_from_label(label: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    return (s[:64] if s else "task")


def _normalize_suggested_task_type(
    raw: str | None,
    label: str,
    used: set[str],
) -> str:
    """Produce a unique, stable task id for priorities/instructions keys."""
    t = (raw or "").strip().lower()
    if not t or t in _BAD_TASK_TYPE_KEYS:
        base = _slug_from_label(label)
    else:
        base = re.sub(r"[^a-z0-9_-]+", "-", t).strip("-")[:64]
        if not base:
            base = _slug_from_label(label)
    key = base
    n = 2
    while key in used:
        key = f"{base}-{n}"
        n += 1
    used.add(key)
    return key


def _emit(kind: str, data: Any) -> tuple[str, Any]:
    return (kind, data)


def _repair_trailing_commas(s: str) -> str:
    """Remove trailing commas before ``}`` or ``]`` (common invalid JSON from LLMs)."""
    prev = None
    out = s
    while prev != out:
        prev = out
        out = re.sub(r",(\s*[}\]])", r"\1", out)
    return out


def _normalize_json_unicode_quotes(s: str) -> str:
    """Replace curly quotes with ASCII quotes (common in LLM output)."""
    return (
        s.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
    )


def _repair_invalid_json_escapes(s: str) -> str:
    """Escape backslashes that are not valid JSON escapes inside string literals.

    Models often emit Windows paths (``C:\\Users`` written wrong) or regex fragments
    with lone ``\\`` before characters other than ``"\\/bfnrtu``, which makes
    ``json.loads`` raise ``Invalid \\escape``.

    Also fixes ``\\`` followed by a literal newline/tab (invalid in JSON; models
    sometimes line-wrap inside strings after ``\\``).
    """
    out: list[str] = []
    i = 0
    in_string = False

    while i < len(s):
        ch = s[i]
        if not in_string:
            if ch == '"':
                in_string = True
            out.append(ch)
            i += 1
            continue

        # Inside a JSON string (scanning *raw* text; quote open/close matches JSON rules).
        if ch == '"':
            bs = 0
            j = i - 1
            while j >= 0 and s[j] == "\\":
                bs += 1
                j -= 1
            if bs % 2 == 1:
                out.append(ch)
            else:
                in_string = False
                out.append(ch)
            i += 1
            continue

        if ch == "\\":
            if i + 1 >= len(s):
                out.append("\\\\")
                i += 1
                continue
            nxt = s[i + 1]
            # JSON allows only \\ " / b f n r t uXXXX after \ — not literal CR/LF/TAB.
            if nxt in "\n\r\t":
                out.append("\\n" if nxt == "\n" else "\\r" if nxt == "\r" else "\\t")
                i += 2
                continue
            if nxt in '"\\/bfnrt':
                out.append(ch)
                out.append(nxt)
                i += 2
                continue
            if nxt == "u" and i + 5 <= len(s):
                hexpart = s[i + 2 : i + 6]
                if len(hexpart) == 4 and all(
                    c in "0123456789abcdefABCDEF" for c in hexpart
                ):
                    out.append(s[i : i + 6])
                    i += 6
                    continue
            out.append("\\\\")
            out.append(nxt)
            i += 2
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def _json_parse_attempts(raw: str) -> list[str]:
    """Ordered variants to try so we preserve valid JSON and fix common breakage."""
    seen: set[str] = set()
    out: list[str] = []

    def add(x: str) -> None:
        if x not in seen:
            seen.add(x)
            out.append(x)

    add(raw)
    q = _normalize_json_unicode_quotes(raw)
    add(q)
    for base in (raw, q):
        add(_repair_trailing_commas(base))
        add(_repair_invalid_json_escapes(base))
    t_raw = _repair_trailing_commas(raw)
    t_q = _repair_trailing_commas(q)
    add(_repair_invalid_json_escapes(t_raw))
    add(_repair_invalid_json_escapes(t_q))
    return out


def _loads_json_lenient(fragment: str) -> Any:
    last_err: json.JSONDecodeError | None = None
    for candidate in _json_parse_attempts(fragment):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_err = exc
            continue
    assert last_err is not None
    raise last_err


def _balanced_json_fragments(text: str) -> list[str]:
    """Extract balanced JSON objects/arrays from *text*, respecting string literals.

    Using first ``{`` to last ``}`` is unsafe when strings contain ``}`` or when
    the model emits prose plus JSON; this finds complete top-level values.
    """
    n = len(text)
    found: list[str] = []
    seen: set[str] = set()
    for start in range(n):
        if text[start] not in "{[":
            continue
        stack: list[str] = [text[start]]
        in_string = False
        escape = False
        j = start + 1
        while j < n:
            c = text[j]
            if in_string:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_string = False
                j += 1
                continue
            if c == '"':
                in_string = True
            elif c == "{":
                stack.append("{")
            elif c == "[":
                stack.append("[")
            elif c == "}":
                if not stack or stack[-1] != "{":
                    break
                stack.pop()
                if not stack:
                    frag = text[start : j + 1]
                    if frag not in seen:
                        seen.add(frag)
                        found.append(frag)
                    break
            elif c == "]":
                if not stack or stack[-1] != "[":
                    break
                stack.pop()
                if not stack:
                    frag = text[start : j + 1]
                    if frag not in seen:
                        seen.add(frag)
                        found.append(frag)
                    break
            j += 1
    # Prefer longer fragments first (usually the full document).
    found.sort(key=len, reverse=True)
    return found


def _extract_json(text: str) -> Any:
    """Best-effort extraction of JSON from LLM output (handles markdown fences).

    Applies repairs for invalid string escapes and trailing commas before failing.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

    fragments: list[str] = []
    fragments.extend(_balanced_json_fragments(text))
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        idx_start = text.find(start_char)
        idx_end = text.rfind(end_char)
        if idx_start != -1 and idx_end > idx_start:
            fragments.append(text[idx_start : idx_end + 1])

    fragments.append(text)

    seen: set[str] = set()
    last_err: json.JSONDecodeError | None = None
    for fragment in fragments:
        if fragment in seen:
            continue
        seen.add(fragment)
        try:
            return _loads_json_lenient(fragment)
        except json.JSONDecodeError as exc:
            last_err = exc
            continue

    assert last_err is not None
    raise last_err


def _llm_call(provider, system: str, user: str, timeout: int = 180, max_tokens: int | None = None):
    """Blocking LLM call with timeout and optional token limit override.

    When *max_tokens* is supplied and the provider exposes ``_config.max_tokens``,
    the value is temporarily reduced for this call.  NOT safe to call concurrently
    with different *max_tokens* values on the same provider — use
    ``ScopedMaxTokens`` for batch parallel calls.
    """
    original_max = None
    if max_tokens is not None and hasattr(provider, '_config'):
        original_max = provider._config.max_tokens
        provider._config.max_tokens = max_tokens

    def _call():
        return provider.complete(system, user)

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call)
            return future.result(timeout=timeout)
    finally:
        if original_max is not None:
            provider._config.max_tokens = original_max


class ScopedMaxTokens:
    """Context manager to temporarily cap provider max_tokens for a block of calls."""

    def __init__(self, provider, max_tokens: int | None):
        self._provider = provider
        self._max_tokens = max_tokens
        self._original: int | None = None

    def __enter__(self):
        if self._max_tokens is not None and hasattr(self._provider, '_config'):
            self._original = self._provider._config.max_tokens
            self._provider._config.max_tokens = self._max_tokens
        return self

    def __exit__(self, *exc):
        if self._original is not None:
            self._provider._config.max_tokens = self._original


# ---------------------------------------------------------------------------
# Phase 2 — Architecture understanding
# ---------------------------------------------------------------------------

_PHASE2_SYSTEM = """\
You are a principal software architect. Analyze this codebase. Respond with ONLY valid JSON."""

_PHASE2_USER = """\
## Docs
{docs_section}

## Repo map (signatures)
{repo_map}

## Entry points
{entry_points}

## Most imported modules
{most_imported}

## Git churn (recent)
{git_churn}

## Complex files
{complexity}

## TODOs ({todo_count})
{todo_sample}

---
Respond with JSON:
{{
  "domain": "one sentence",
  "architecture": "pattern name",
  "primary_language": "lang",
  "critical_quality_attributes": ["top 3 attributes"],
  "components": [{{"name":"","path":"","role":"","concerns":[""]}}],
  "data_flows": ["flow descriptions"],
  "investigation_targets": [
    {{"area":"","why":"","files_to_read":["max 3 files"],"concern":"latency|correctness|…"}}
  ]
}}

Rules: 3-4 investigation targets. Use repo map paths; focus bugs and perf."""


def _run_phase2(
    provider,
    phase1: dict,
    profile: DeepAnalysisProfile,
) -> Generator[tuple[str, Any], None, dict | None]:
    """Phase 2: Architecture understanding."""
    yield _emit("log", {"msg": "Phase 2: Understanding project architecture...", "level": "info"})

    doc_chars = min(profile.max_file_chars, 3000)
    docs_section = ""
    for name, content in phase1.get("docs", {}).items():
        docs_section += f"\n--- {name} ---\n{content[:doc_chars]}\n"
    if not docs_section:
        docs_section = "(no documentation files found)"

    repo_map = phase1.get("repo_map", "")[:profile.max_repo_map_chars]

    entry_points = "\n".join(
        f"  {ep['file']} — {ep['kind']}"
        for ep in phase1.get("entry_points", [])[:8]
    ) or "(none)"

    most_imported = "\n".join(
        f"  {mod} ({count})"
        for mod, count in phase1.get("import_graph", {}).get("most_imported", [])[:8]
    ) or "(none)"

    git_churn = "\n".join(
        f"  {item['file']} ({item['commits']})"
        for item in phase1.get("git_churn", [])[:8]
    ) or "(none)"

    complexity = "\n".join(
        f"  {c['file']} — {c['loc']}LOC {c['functions']}fn"
        for c in phase1.get("complexity", [])[:8]
    ) or "(none)"

    todos = phase1.get("todos", [])
    todo_sample = "\n".join(
        f"  [{t['tag']}] {t['file']}:{t['line']} — {t['text'][:80]}"
        for t in todos[:10]
    ) or "(none)"

    user_prompt = _PHASE2_USER.format(
        docs_section=docs_section,
        repo_map=repo_map,
        entry_points=entry_points,
        most_imported=most_imported,
        git_churn=git_churn,
        complexity=complexity,
        todo_count=len(todos),
        todo_sample=todo_sample,
    )

    yield _emit("log", {"msg": f"Phase 2: Sending {len(user_prompt)} chars to LLM...", "level": "detail"})

    try:
        t0 = time.time()
        response = _llm_call(
            provider, _PHASE2_SYSTEM, user_prompt,
            timeout=profile.timeout_seconds,
            max_tokens=profile.phase2_max_tokens,
        )
        elapsed = time.time() - t0
        yield _emit("log", {"msg": f"Phase 2: LLM responded in {elapsed:.1f}s", "level": "info"})

        arch = _extract_json(response.text)
        if not isinstance(arch, dict):
            yield _emit("log", {"msg": "Phase 2: LLM returned non-object, skipping deep analysis", "level": "info"})
            return None

        domain = arch.get("domain", "unknown")
        yield _emit("log", {"msg": f"Phase 2: Domain — {domain}", "level": "info"})
        yield _emit("log", {"msg": f"Phase 2: Architecture — {arch.get('architecture', '?')}", "level": "info"})

        attrs = arch.get("critical_quality_attributes", [])
        if attrs:
            yield _emit("log", {"msg": f"Phase 2: Critical attributes — {', '.join(attrs)}", "level": "info"})

        targets = arch.get("investigation_targets", [])
        yield _emit("log", {"msg": f"Phase 2: Identified {len(targets)} investigation targets", "level": "info"})
        for t in targets:
            yield _emit("log", {"msg": f"  → {t.get('area', '?')} ({t.get('concern', '?')})", "level": "detail"})

        yield _emit("architecture", arch)
        return arch

    except concurrent.futures.TimeoutError:
        yield _emit("log", {"msg": f"Phase 2: LLM timed out after {profile.timeout_seconds}s", "level": "info"})
        return None
    except Exception as e:
        yield _emit("log", {"msg": f"Phase 2: LLM error — {e}", "level": "info"})
        log.warning("Phase 2 LLM error: %s", e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Phase 3 — Sequential deep code tracing
# ---------------------------------------------------------------------------

_PHASE3_SYSTEM = (
    "You are a principal engineer doing a code review. "
    "Be SPECIFIC: exact file names, function names. Respond with ONLY valid JSON. "
    "Use double quotes for all keys and string values. Escape internal quotes as \\\". "
    "Escape backslashes in paths (use / or \\\\). Do not put raw newlines inside strings. "
    "No trailing commas."
)

_PHASE3_USER = """\
Domain: {domain} | Architecture: {architecture} | Key: {quality_attrs}

## Investigate: {area}
Why: {why} | Concern: {concern}

## Code
{code_section}

---
Find issues in "{area}" for {domain_short}. JSON response:
{{
  "area": "{area}",
  "findings": [
    {{
      "severity": "P0|P1|P2|P3",
      "category": "bug|performance|security|architecture|tech_debt|reliability",
      "title": "short title",
      "description": "the issue",
      "file": "path",
      "approach": "concrete fix — not 'improve' but 'replace X with Y'",
      "language_specific": "lang-specific guidance if any",
      "impact": "what breaks if unfixed"
    }}
  ]
}}
P0=crash/data-loss, P1=perf/reliability, P2=quality, P3=nice-to-have. Only confident findings."""


def _build_phase3_prompt(
    target: dict,
    phase1: dict,
    architecture: dict,
    profile: DeepAnalysisProfile,
) -> tuple[str, str] | None:
    """Build the user prompt for a single Phase 3 investigation. Returns (area, prompt) or None."""
    root = Path(phase1["root"])
    critical_files = phase1.get("critical_files", {})
    domain = architecture.get("domain", "software project")
    arch_pattern = architecture.get("architecture", "unknown")
    quality_attrs = ", ".join(architecture.get("critical_quality_attributes", ["quality"]))
    domain_short = domain.split("—")[0].split(",")[0].strip()[:60]

    area = target.get("area", "investigation")
    why = target.get("why", "")
    concern = target.get("concern", "quality")
    files_to_read = target.get("files_to_read", [])

    max_chars = profile.max_file_chars
    code_section = ""
    files_included = 0
    for fpath in files_to_read[:4]:
        if fpath in critical_files:
            content = critical_files[fpath]
        else:
            full = root / fpath
            content = _safe_read(full)
        if content is None:
            continue
        truncated = content[:max_chars]
        if len(content) > max_chars:
            truncated += f"\n... ({len(content) - max_chars} more chars)"
        code_section += f"\n--- {fpath} ---\n{truncated}\n"
        files_included += 1

    if files_included == 0:
        return None

    user_prompt = _PHASE3_USER.format(
        domain=domain,
        architecture=arch_pattern,
        quality_attrs=quality_attrs,
        area=area,
        why=why,
        concern=concern,
        code_section=code_section,
        domain_short=domain_short,
    )
    return (area, user_prompt)


def _run_phase3(
    provider,
    phase1: dict,
    architecture: dict,
    profile: DeepAnalysisProfile,
) -> Generator[tuple[str, Any], None, list[dict]]:
    """Phase 3: Parallel deep code investigation."""
    targets = architecture.get("investigation_targets", [])
    if not targets:
        yield _emit("log", {"msg": "Phase 3: No investigation targets — skipping", "level": "info"})
        return []

    max_targets = min(len(targets), profile.max_investigation_targets)
    selected = targets[:max_targets]

    prompts: list[tuple[str, str]] = []
    for target in selected:
        result = _build_phase3_prompt(target, phase1, architecture, profile)
        if result:
            prompts.append(result)

    if not prompts:
        yield _emit("log", {"msg": "Phase 3: No readable files for any target — skipping", "level": "info"})
        return []

    yield _emit("log", {
        "msg": f"Phase 3: Investigating {len(prompts)} areas in parallel…",
        "level": "info",
    })
    for area, _ in prompts:
        yield _emit("log", {"msg": f"  → {area}", "level": "detail"})

    all_findings: list[dict] = []
    t0 = time.time()

    with ScopedMaxTokens(provider, profile.phase3_max_tokens):
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(prompts), profile.parallel_workers)) as pool:
            def _p3_call(prompt: str):
                return provider.complete(_PHASE3_SYSTEM, prompt)

            future_map = {
                pool.submit(_p3_call, prompt): area
                for area, prompt in prompts
            }

            for future in concurrent.futures.as_completed(future_map):
                area = future_map[future]
                elapsed = time.time() - t0
                try:
                    response = future.result(timeout=profile.timeout_seconds)
                    result = _extract_json(response.text)
                    if isinstance(result, dict):
                        findings = result.get("findings", [])
                        for f in findings:
                            f["investigation_area"] = area
                        all_findings.extend(findings)
                        yield _emit("log", {
                            "msg": f"Phase 3 [{area}]: {len(findings)} issue(s) ({elapsed:.0f}s)",
                            "level": "info",
                        })
                        for f in findings:
                            sev = f.get("severity", "?")
                            title = f.get("title", "?")
                            yield _emit("log", {"msg": f"    [{sev}] {title}", "level": "detail"})
                    else:
                        yield _emit(
                            "log",
                            {
                                "msg": (
                                    f"Phase 3 [{area}]: invalid response ({elapsed:.0f}s)"
                                ),
                                "level": "info",
                            },
                        )

                except (concurrent.futures.TimeoutError, TimeoutError):
                    yield _emit("log", {"msg": f"Phase 3 [{area}]: timed out ({elapsed:.0f}s)", "level": "info"})
                except Exception as e:
                    yield _emit("log", {"msg": f"Phase 3 [{area}]: error — {e} ({elapsed:.0f}s)", "level": "info"})
                    log.warning("Phase 3 error for %s: %s", area, e, exc_info=True)

    total = time.time() - t0
    yield _emit(
        "log",
        {
            "msg": (
                f"Phase 3: {len(all_findings)} findings total ({total:.0f}s wall-clock)"
            ),
            "level": "info",
        },
    )
    return all_findings


# ---------------------------------------------------------------------------
# Phase 4 — Task synthesis
# ---------------------------------------------------------------------------

_PHASE4_SYSTEM = (
    "Convert code audit findings into prioritized tasks. Respond with ONLY valid JSON. "
    "Use double quotes for keys and strings; escape \" inside strings as \\\". "
    "Escape backslashes in file paths. No trailing commas; no comments inside JSON."
)

_PHASE4_USER = """\
Domain: {domain} | {architecture} | Key: {quality_attrs}

## Findings
{findings_section}

## TODOs ({todo_count})
{todo_section}

## Stats: {source_count} files | Complex: {complex_files} | Churn: {churn_files}

---
Merge findings into actionable tasks. JSON:
{{
  "tasks": [
    {{
      "type": "fix-cache-race",
      "label": "Human-readable short title",
      "severity": "P0|P1|P2|P3",
      "category": "bug|performance|security|architecture|tech_debt|reliability|testing",
      "description": "what and why",
      "reason": "why for THIS project",
      "files": ["path/to/file.ext"],
      "approach": "concrete steps",
      "language_specific": "if applicable",
      "estimated_complexity": "trivial|moderate|significant",
      "instructions": "agent instructions"
    }}
  ],
  "project_summary": "1-2 sentences"
}}
Rules:
- "type" MUST be a unique kebab-case id per task (e.g. fix-ffi-bridge, add-input-validation).
  NEVER use the words "slug", "title", or "type" as the value of "type".
- "label" is the human-readable title shown in the UI.
- merge related findings, P0 first, 6-10 tasks, each references specific files with concrete approach."""


def _run_phase4(
    provider,
    phase1: dict,
    architecture: dict,
    findings: list[dict],
    profile: DeepAnalysisProfile,
) -> Generator[tuple[str, Any], None, dict | None]:
    """Phase 4: Task synthesis."""
    yield _emit("log", {"msg": "Phase 4: Synthesizing findings into tasks...", "level": "info"})

    domain = architecture.get("domain", "software project")
    arch_pattern = architecture.get("architecture", "unknown")
    quality_attrs = ", ".join(architecture.get("critical_quality_attributes", ["quality"]))

    findings_section = ""
    for f in findings:
        findings_section += (
            f"[{f.get('severity','?')}] {f.get('title','?')} | "
            f"{f.get('file','?')} | {f.get('description','?')[:200]} | "
            f"Fix: {f.get('approach','?')[:200]}\n"
        )
    if not findings_section:
        findings_section = "(none)"

    todos = phase1.get("todos", [])
    todo_section = "\n".join(
        f"[{t['tag']}] {t['file']}:{t['line']} — {t['text'][:80]}"
        for t in todos[:15]
    ) or "(none)"

    complex_files = ", ".join(
        f"{c['file']} ({c['loc']} LOC)"
        for c in phase1.get("complexity", [])[:5]
    ) or "none"

    churn_files = ", ".join(
        f"{c['file']} ({c['commits']} commits)"
        for c in phase1.get("git_churn", [])[:5]
    ) or "none"

    user_prompt = _PHASE4_USER.format(
        domain=domain,
        architecture=arch_pattern,
        quality_attrs=quality_attrs,
        findings_section=findings_section,
        todo_count=len(todos),
        todo_section=todo_section,
        source_count=phase1.get("source_file_count", 0),
        complex_files=complex_files,
        churn_files=churn_files,
    )

    try:
        t0 = time.time()
        response = _llm_call(
            provider, _PHASE4_SYSTEM, user_prompt,
            timeout=profile.timeout_seconds,
            max_tokens=profile.phase4_max_tokens,
        )
        elapsed = time.time() - t0
        yield _emit("log", {"msg": f"Phase 4: LLM responded in {elapsed:.1f}s", "level": "info"})

        result = _extract_json(response.text)
        if not isinstance(result, dict):
            yield _emit("log", {"msg": "Phase 4: Invalid response format", "level": "info"})
            return None

        tasks = result.get("tasks", [])
        yield _emit("log", {"msg": f"Phase 4: Synthesized {len(tasks)} tasks", "level": "info"})

        for t in tasks:
            sev = t.get("severity", "?")
            label = t.get("label", "?")
            cat = t.get("category", "?")
            yield _emit("log", {"msg": f"  [{sev}] [{cat}] {label}", "level": "detail"})

        summary = result.get("project_summary", "")
        if summary:
            yield _emit("log", {"msg": f"Summary: {summary}", "level": "info"})

        return result

    except concurrent.futures.TimeoutError:
        yield _emit("log", {"msg": f"Phase 4: Timed out after {profile.timeout_seconds}s", "level": "info"})
        return None
    except Exception as e:
        yield _emit("log", {"msg": f"Phase 4: Error — {e}", "level": "info"})
        log.warning("Phase 4 error: %s", e, exc_info=True)
        return None


# ---------------------------------------------------------------------------
# Public entry point — full deep suggestion pipeline (streaming)
# ---------------------------------------------------------------------------

def deep_suggest_tasks(
    project_path: str,
    provider,
    provider_config: ProviderConfig | None = None,
) -> Generator[tuple[str, Any], None, None]:
    """Run the full 4-phase deep analysis and task suggestion pipeline.

    Yields (event_type, data) tuples for streaming to the UI.

    *provider_config* is used to auto-detect the analysis profile. When omitted
    the provider's ``_config`` attribute is used as fallback.

    Events:
      ("log", {"msg": str, "level": "info"|"detail"})
      ("phase1_complete", {phase1 data summary})
      ("architecture", {architecture understanding})
      ("finding", {individual finding})
      ("tasks_ready", {tasks, suggested, available, ...})
      ("done", {final result})
      ("error", {"msg": str})
    """
    if provider_config is None:
        provider_config = getattr(provider, "_config", None)
    if provider_config is None:
        provider_config = ProviderConfig()

    profile = resolve_deep_analysis_profile(
        provider_config,
        provider_config.deep_analysis,
    )

    t_start = time.time()

    if profile.disable_thinking:
        provider._disable_thinking = True

    try:
        yield _emit("log", {"msg": f"Starting deep analysis of {project_path}", "level": "info"})
        yield _emit("log", {
            "msg": f"Profile: {profile.max_investigation_targets} targets, "
                   f"{profile.parallel_workers} workers, "
                   f"timeout {profile.timeout_seconds}s, "
                   f"thinking {'off' if profile.disable_thinking else 'on'}",
            "level": "detail",
        })

        # Phase 1 — structural intelligence
        yield _emit("log", {"msg": "Phase 1: Running structural analysis...", "level": "info"})
        t0 = time.time()
        phase1 = run_phase1(project_path)
        elapsed1 = time.time() - t0
        yield _emit("log", {
            "msg": f"Phase 1 complete: {phase1['source_file_count']} files, "
                   f"{len(phase1['todos'])} TODOs, "
                   f"{len(phase1['entry_points'])} entry points "
                   f"in {elapsed1:.1f}s",
            "level": "info",
        })
        yield _emit("phase1_complete", {
            "source_file_count": phase1["source_file_count"],
            "todo_count": len(phase1["todos"]),
            "entry_point_count": len(phase1["entry_points"]),
            "git_churn_files": len(phase1["git_churn"]),
            "doc_files": list(phase1["docs"].keys()),
            "elapsed_seconds": round(elapsed1, 1),
        })

        # Phase 2 — architecture understanding
        architecture = None
        gen2 = _run_phase2(provider, phase1, profile)
        while True:
            try:
                event = next(gen2)
                yield event
            except StopIteration as e:
                architecture = e.value
                break

        if architecture is None:
            yield _emit("log", {"msg": "Deep analysis requires a working LLM provider", "level": "info"})
            yield _emit("error", {"msg": "Phase 2 failed — cannot continue without architecture understanding"})
            return

        # Phase 3 — parallel deep code tracing
        all_findings: list[dict] = []
        gen3 = _run_phase3(provider, phase1, architecture, profile)
        while True:
            try:
                event = next(gen3)
                yield event
            except StopIteration as e:
                all_findings = e.value if e.value else []
                break

        # Phase 4 — task synthesis
        final_result = None
        gen4 = _run_phase4(provider, phase1, architecture, all_findings, profile)
        while True:
            try:
                event = next(gen4)
                yield event
            except StopIteration as e:
                final_result = e.value
                break

        total_elapsed = time.time() - t_start

        if final_result is None:
            yield _emit("error", {"msg": "Phase 4 failed — could not synthesize tasks"})
            return

        tasks = final_result.get("tasks", [])
        suggested = []
        used_type_keys: set[str] = set()
        for i, t in enumerate(tasks):
            label = t.get("label", "Unknown task")
            typ = _normalize_suggested_task_type(t.get("type"), str(label), used_type_keys)
            suggested.append({
                "type": typ,
                "label": label,
                "description": t.get("description", ""),
                "reason": t.get("reason", ""),
                "priority": i + 1,
                "enabled": True,
                "instructions": t.get("instructions", ""),
                "severity": t.get("severity", "P2"),
                "category": t.get("category", "quality"),
                "files": t.get("files", []),
                "approach": t.get("approach", ""),
                "language_specific": t.get("language_specific", ""),
                "estimated_complexity": t.get("estimated_complexity", "moderate"),
            })

        n_inv = min(len(architecture.get("investigation_targets", [])), 6)
        yield _emit(
            "log",
            {
                "msg": (
                    f"Deep analysis complete: {len(suggested)} tasks in {total_elapsed:.1f}s "
                    f"({len(all_findings)} raw findings across {n_inv} investigations)"
                ),
                "level": "info",
            },
        )

        result = {
            "suggested": suggested,
            "available": [],
            "llm_enhanced": True,
            "deep_analysis": True,
            "architecture": architecture,
            "findings_count": len(all_findings),
            "project_summary": final_result.get("project_summary", ""),
            "elapsed_seconds": round(total_elapsed, 1),
        }
        yield _emit("tasks_ready", result)
        yield _emit("done", result)

    except Exception as e:
        log.exception("Deep suggestion pipeline failed")
        yield _emit("error", {"msg": str(e)})
    finally:
        if profile.disable_thinking:
            provider._disable_thinking = False
