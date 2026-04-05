"""
Phase 1: Deep structural intelligence — no LLM, pure static analysis.

Extracts rich, factual signals from a codebase so that later LLM phases
receive *evidence* instead of guesses.

All public helpers accept a project root path and return plain dicts/lists
suitable for JSON serialisation and LLM context injection.
"""

from __future__ import annotations

import ast
import logging
import os
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

SKIP_DIRS = frozenset({
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "target", "build", "dist", ".idea", ".vscode", ".next",
    ".nuxt", "vendor", "Pods", ".gradle", ".mvn",
})

BINARY_EXTENSIONS = frozenset({
    ".pyc", ".pyo", ".class", ".jar", ".war", ".o", ".a", ".so",
    ".dll", ".exe", ".bin", ".png", ".jpg", ".jpeg", ".gif",
    ".ico", ".svg", ".woff", ".woff2", ".ttf", ".eot", ".mp3",
    ".mp4", ".zip", ".gz", ".tar", ".pdf", ".lock",
})

SOURCE_EXTENSIONS = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".kt", ".kts",
    ".go", ".rs", ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp",
    ".rb", ".php", ".swift", ".cs", ".scala", ".lua", ".sh",
    ".bash", ".zsh", ".sql", ".r", ".m", ".mm",
})

DOC_FILES = frozenset({
    "readme.md", "readme.rst", "readme.txt", "readme",
    "architecture.md", "design.md", "contributing.md",
    "changelog.md", "changes.md", "todo.md",
})

MAX_FILE_READ_BYTES = 100_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _should_skip_dir(name: str) -> bool:
    return name in SKIP_DIRS or name.startswith(".")


def _is_source(path: Path) -> bool:
    return path.suffix.lower() in SOURCE_EXTENSIONS


def _safe_read(path: Path, max_bytes: int = MAX_FILE_READ_BYTES) -> str | None:
    try:
        raw = path.read_bytes()[:max_bytes]
        return raw.decode("utf-8", errors="replace")
    except (OSError, PermissionError):
        return None


def _source_files(root: Path) -> list[Path]:
    """Collect all source files, respecting skip dirs."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        for fname in filenames:
            p = Path(dirpath) / fname
            if _is_source(p) and p.suffix.lower() not in BINARY_EXTENSIONS:
                files.append(p)
    return files


# ---------------------------------------------------------------------------
# 1. TODO / FIXME / HACK / BUG / XXX extraction
# ---------------------------------------------------------------------------

_TODO_RE = re.compile(
    r"(?:#|//|/\*+|\*|--|;)\s*"  # comment leader
    r"(TODO|FIXME|HACK|BUG|XXX|OPTIMIZE|PERF|SECURITY|DEPRECATED|REFACTOR)"
    r"\s*[:(\-]?\s*"
    r"(.*)",
    re.IGNORECASE,
)


def extract_todos(root: Path, files: list[Path] | None = None) -> list[dict[str, Any]]:
    """Return inline markers (TODO/FIXME/…) with surrounding context."""
    if files is None:
        files = _source_files(root)

    results: list[dict] = []
    for path in files:
        content = _safe_read(path)
        if content is None:
            continue
        lines = content.splitlines()
        rel = str(path.relative_to(root))
        for i, line in enumerate(lines):
            m = _TODO_RE.search(line)
            if m:
                tag = m.group(1).upper()
                text = m.group(2).strip().rstrip("*/").strip()
                ctx_start = max(0, i - 2)
                ctx_end = min(len(lines), i + 3)
                results.append({
                    "file": rel,
                    "line": i + 1,
                    "tag": tag,
                    "text": text,
                    "context": "\n".join(lines[ctx_start:ctx_end]),
                })
    return results


# ---------------------------------------------------------------------------
# 2. Import / dependency graph
# ---------------------------------------------------------------------------

def _extract_python_imports(content: str) -> list[str]:
    """Extract imported module names from Python source using the ast module."""
    try:
        tree = ast.parse(content, type_comments=False)
    except SyntaxError:
        return []
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.append(node.module.split(".")[0])
    return modules


_IMPORT_PATTERNS: dict[str, re.Pattern] = {
    ".java": re.compile(r"^\s*import\s+(?:static\s+)?([\w.]+)", re.MULTILINE),
    ".kt": re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE),
    ".go": re.compile(r'"([\w./]+)"'),
    ".js": re.compile(r"""(?:import\s.*?from\s+|require\s*\(\s*)['"]([^'"]+)['"]"""),
    ".ts": re.compile(r"""(?:import\s.*?from\s+|require\s*\(\s*)['"]([^'"]+)['"]"""),
    ".jsx": re.compile(r"""(?:import\s.*?from\s+|require\s*\(\s*)['"]([^'"]+)['"]"""),
    ".tsx": re.compile(r"""(?:import\s.*?from\s+|require\s*\(\s*)['"]([^'"]+)['"]"""),
    ".rs": re.compile(r"^\s*(?:use|extern crate)\s+([\w:]+)", re.MULTILINE),
    ".cpp": re.compile(r'^\s*#include\s*[<"]([^>"]+)[>"]', re.MULTILINE),
    ".cc": re.compile(r'^\s*#include\s*[<"]([^>"]+)[>"]', re.MULTILINE),
    ".c": re.compile(r'^\s*#include\s*[<"]([^>"]+)[>"]', re.MULTILINE),
    ".h": re.compile(r'^\s*#include\s*[<"]([^>"]+)[>"]', re.MULTILINE),
    ".hpp": re.compile(r'^\s*#include\s*[<"]([^>"]+)[>"]', re.MULTILINE),
    ".rb": re.compile(r"^\s*require\s+['\"]([^'\"]+)['\"]", re.MULTILINE),
    ".php": re.compile(r"^\s*(?:use|require_once|include)\s+['\"]?([^'\";\s]+)", re.MULTILINE),
    ".cs": re.compile(r"^\s*using\s+([\w.]+)\s*;", re.MULTILINE),
    ".scala": re.compile(r"^\s*import\s+([\w.]+)", re.MULTILINE),
}


def build_import_graph(root: Path, files: list[Path] | None = None) -> dict[str, Any]:
    """Build a directed import graph and compute centrality (fan-in count).

    Returns:
        {
            "edges": {rel_path: [imported_module, ...]},
            "fan_in": {rel_path_or_module: count},
            "most_imported": [(module, count), ...],  # top 20
        }
    """
    if files is None:
        files = _source_files(root)

    edges: dict[str, list[str]] = {}
    fan_in: Counter[str] = Counter()

    for path in files:
        content = _safe_read(path)
        if content is None:
            continue
        rel = str(path.relative_to(root))
        ext = path.suffix.lower()

        imports: list[str] = []
        if ext == ".py":
            imports = _extract_python_imports(content)
        elif ext in _IMPORT_PATTERNS:
            imports = _IMPORT_PATTERNS[ext].findall(content)

        cleaned = [m.strip() for m in imports if m.strip()]
        if cleaned:
            edges[rel] = cleaned
            for m in cleaned:
                fan_in[m] += 1

    most_imported = fan_in.most_common(20)
    return {
        "edges": edges,
        "fan_in": dict(fan_in),
        "most_imported": most_imported,
    }


# ---------------------------------------------------------------------------
# 3. Git churn — most-changed files
# ---------------------------------------------------------------------------

def compute_git_churn(
    root: Path,
    months: int = 6,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """Top N most-changed files in the last `months` months via git log.

    Returns [{"file": str, "commits": int}, …] sorted descending.
    Falls back to empty list if not a git repo or git is unavailable.
    """
    if not (root / ".git").is_dir():
        return []

    try:
        result = subprocess.run(
            [
                "git", "log",
                f"--since={months} months ago",
                "--format=",
                "--name-only",
                "--diff-filter=ACMR",
            ],
            capture_output=True,
            text=True,
            cwd=str(root),
            timeout=30,
        )
        if result.returncode != 0:
            return []
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []

    counts: Counter[str] = Counter()
    for line in result.stdout.splitlines():
        name = line.strip()
        if name:
            counts[name] += 1

    return [
        {"file": f, "commits": c}
        for f, c in counts.most_common(limit)
    ]


# ---------------------------------------------------------------------------
# 4. Complexity metrics
# ---------------------------------------------------------------------------

def _count_python_functions(content: str) -> int:
    try:
        tree = ast.parse(content, type_comments=False)
    except SyntaxError:
        return 0
    return sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))


_FUNC_RE = re.compile(
    r"(?:"
    r"^\s*(?:public|private|protected|static|final|abstract|async|export|default)?\s*"
    r"(?:def |fn |func |function |fun )"
    r")",
    re.MULTILINE,
)


def compute_complexity(
    root: Path,
    files: list[Path] | None = None,
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Identify the largest / most complex files.

    Returns top_n files sorted by a weighted score of LOC + function count.
    """
    if files is None:
        files = _source_files(root)

    entries: list[dict] = []
    for path in files:
        content = _safe_read(path)
        if content is None:
            continue
        rel = str(path.relative_to(root))
        lines = content.splitlines()
        loc = len(lines)
        if loc < 20:
            continue

        if path.suffix == ".py":
            fn_count = _count_python_functions(content)
        else:
            fn_count = len(_FUNC_RE.findall(content))

        max_nesting = 0
        for line in lines:
            stripped = line.lstrip()
            if stripped:
                indent = len(line) - len(stripped)
                level = indent // 4 if indent > 0 else indent // 2
                if level > max_nesting:
                    max_nesting = level

        score = loc + fn_count * 10 + max_nesting * 5
        entries.append({
            "file": rel,
            "loc": loc,
            "functions": fn_count,
            "max_nesting": max_nesting,
            "score": score,
        })

    entries.sort(key=lambda e: e["score"], reverse=True)
    return entries[:top_n]


# ---------------------------------------------------------------------------
# 5. Entry point detection
# ---------------------------------------------------------------------------

_ENTRY_HINTS = re.compile(
    r"""(?:
        if\s+__name__\s*==\s*['"]__main__['"]          # Python
        | public\s+static\s+void\s+main\s*\(            # Java
        | func\s+main\s*\(                               # Go
        | fn\s+main\s*\(                                 # Rust
        | @SpringBootApplication                         # Spring Boot
        | @RestController                                # Spring REST
        | app\.listen\s*\(                               # Node/Express
        | createServer\s*\(                              # Node HTTP
        | FastAPI\s*\(                                   # Python FastAPI
        | Flask\s*\(                                     # Python Flask
        | @app\.route                                    # Flask route
        | @router\.(get|post|put|delete|patch)           # FastAPI router
        | @(Get|Post|Put|Delete|Patch)Mapping            # Spring
        | @RequestMapping                                # Spring
        | @Controller                                    # Spring / NestJS
        | def\s+handle                                   # Lambda/handler
        | exports\.handler                               # AWS Lambda Node
        | @Scheduled                                     # Spring cron
        | @Cron                                          # NestJS cron
        | cron\.schedule                                 # node-cron
        | schedule\.every                                # Python schedule
    )""",
    re.VERBOSE | re.MULTILINE,
)


def detect_entry_points(root: Path, files: list[Path] | None = None) -> list[dict[str, Any]]:
    """Find likely entry points, HTTP handlers, cron jobs, etc."""
    if files is None:
        files = _source_files(root)

    results: list[dict] = []
    for path in files:
        content = _safe_read(path)
        if content is None:
            continue
        rel = str(path.relative_to(root))
        matches = _ENTRY_HINTS.findall(content)
        if matches:
            results.append({
                "file": rel,
                "kind": _classify_entry(rel, content),
                "match_count": len(matches),
            })
    results.sort(key=lambda e: e["match_count"], reverse=True)
    return results


def _classify_entry(rel: str, content: str) -> str:
    lower = content[:3000].lower()
    if "cron" in lower or "schedule" in lower or "@scheduled" in lower:
        return "cron/scheduler"
    if "handler" in rel.lower() or "lambda" in rel.lower():
        return "handler/lambda"
    if any(kw in lower for kw in ("app.route", "router.", "requestmapping", "restcontroller", "fastapi")):
        return "http/api"
    if "__main__" in lower or "public static void main" in lower or "func main(" in lower:
        return "main"
    return "entry"


# ---------------------------------------------------------------------------
# 6. Repo map — compact function/class signature index
# ---------------------------------------------------------------------------

def _python_signatures(path: Path, content: str) -> list[str]:
    """Extract class and function signatures from Python using ast."""
    try:
        tree = ast.parse(content, type_comments=False)
    except SyntaxError:
        return []

    sigs: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(
                ast.dump(b) if not isinstance(b, ast.Name) else b.id
                for b in node.bases
            )
            sigs.append(f"class {node.name}({bases}):" if bases else f"class {node.name}:")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
            args = []
            for a in node.args.args:
                ann = ""
                if a.annotation:
                    try:
                        ann = ": " + ast.unparse(a.annotation)
                    except Exception:
                        pass
                args.append(f"{a.arg}{ann}")
            ret = ""
            if node.returns:
                try:
                    ret = " -> " + ast.unparse(node.returns)
                except Exception:
                    pass
            sigs.append(f"{prefix} {node.name}({', '.join(args)}){ret}")
    return sigs


_SIG_PATTERNS: dict[str, re.Pattern] = {
    ".java": re.compile(
        r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?"
        r"(?:abstract\s+)?(?:synchronized\s+)?"
        r"(?:[\w<>\[\],\s]+\s+)?"
        r"(class|interface|enum|record)\s+(\w+)"
        r"|"
        r"^\s*(?:public|private|protected)?\s*(?:static\s+)?(?:final\s+)?"
        r"(?:abstract\s+)?(?:synchronized\s+)?"
        r"([\w<>\[\]]+)\s+(\w+)\s*\(",
        re.MULTILINE,
    ),
    ".go": re.compile(
        r"^\s*(?:func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)\s*\(|type\s+(\w+)\s+(struct|interface))",
        re.MULTILINE,
    ),
    ".rs": re.compile(
        r"^\s*(?:pub\s+)?(?:async\s+)?(?:fn\s+(\w+)|(?:struct|enum|trait|impl)\s+(\w+))",
        re.MULTILINE,
    ),
}

_GENERIC_SIG = re.compile(
    r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?"
    r"(?:class|interface|function|const|let|var|type)\s+(\w+)",
    re.MULTILINE,
)


def build_repo_map(
    root: Path,
    files: list[Path] | None = None,
    max_files: int = 200,
) -> str:
    """Build a compact, LLM-friendly repo map showing signatures per file.

    Returns a multi-line string like:
        src/engine/calc.py:
          class Calculator:
          def compute(self, ticks: list[Tick]) -> Decimal
          def reset(self)

        src/engine/feed.py:
          class FeedAggregator:
          async def on_tick(self, tick: RawTick)
    """
    if files is None:
        files = _source_files(root)

    files = files[:max_files]
    parts: list[str] = []

    for path in sorted(files, key=lambda p: str(p.relative_to(root))):
        content = _safe_read(path, max_bytes=60_000)
        if content is None:
            continue
        rel = str(path.relative_to(root))
        ext = path.suffix.lower()

        sigs: list[str]
        if ext == ".py":
            sigs = _python_signatures(path, content)
        elif ext in _SIG_PATTERNS:
            raw = _SIG_PATTERNS[ext].findall(content)
            sigs = [" ".join(g for g in groups if g).strip() for groups in raw]
            sigs = [s for s in sigs if s]
        else:
            raw_matches = _GENERIC_SIG.findall(content)
            sigs = list(dict.fromkeys(raw_matches))

        if sigs:
            sig_block = "\n".join(f"  {s}" for s in sigs[:30])
            parts.append(f"{rel}:\n{sig_block}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 7. Read documentation files
# ---------------------------------------------------------------------------

def read_docs(root: Path, max_bytes_per_file: int = 8000) -> dict[str, str]:
    """Read README, ARCHITECTURE.md, and other doc files.

    Returns {relative_path: content} for files found.
    """
    found: dict[str, str] = {}

    for item in root.iterdir():
        if item.is_file() and item.name.lower() in DOC_FILES:
            content = _safe_read(item, max_bytes=max_bytes_per_file)
            if content:
                found[item.name] = content

    docs_dir = root / "docs"
    if docs_dir.is_dir():
        for item in docs_dir.iterdir():
            if item.is_file() and item.suffix.lower() in (".md", ".rst", ".txt"):
                content = _safe_read(item, max_bytes=max_bytes_per_file)
                if content:
                    found[f"docs/{item.name}"] = content

    vigil_ctx = root / ".vigil" / "context.yaml"
    if vigil_ctx.is_file():
        content = _safe_read(vigil_ctx, max_bytes=max_bytes_per_file)
        if content:
            found[".vigil/context.yaml"] = content

    return found


# ---------------------------------------------------------------------------
# 8. Read critical file contents (for LLM phases)
# ---------------------------------------------------------------------------

def read_critical_files(
    root: Path,
    import_graph: dict[str, Any],
    entry_points: list[dict],
    complexity: list[dict],
    max_files: int = 12,
    max_lines_per_file: int = 250,
) -> dict[str, str]:
    """Select and read the most important files based on analysis signals.

    Prioritises: entry points > most-imported modules > most complex files.
    Returns {relative_path: content (truncated to max_lines)}.
    """
    candidates: dict[str, float] = {}

    for ep in entry_points:
        f = ep["file"]
        candidates[f] = candidates.get(f, 0) + 100 + ep["match_count"] * 10

    for mod, count in import_graph.get("most_imported", []):
        for edge_file, imports in import_graph.get("edges", {}).items():
            if mod in imports:
                candidates[edge_file] = candidates.get(edge_file, 0) + count * 5

    fan_in = import_graph.get("fan_in", {})
    all_source = _source_files(root)
    for path in all_source:
        rel = str(path.relative_to(root))
        stem = path.stem
        if stem in fan_in:
            candidates[rel] = candidates.get(rel, 0) + fan_in[stem] * 3

    for cx in complexity:
        f = cx["file"]
        candidates[f] = candidates.get(f, 0) + cx["score"] * 0.5

    ranked = sorted(candidates.items(), key=lambda x: x[1], reverse=True)

    result: dict[str, str] = {}
    for rel, _score in ranked[:max_files]:
        full = root / rel
        content = _safe_read(full)
        if content is None:
            continue
        lines = content.splitlines()
        if len(lines) > max_lines_per_file:
            truncated = lines[:max_lines_per_file]
            truncated.append(f"\n... ({len(lines) - max_lines_per_file} more lines)")
            content = "\n".join(truncated)
        result[rel] = content

    return result


# ---------------------------------------------------------------------------
# 9. Run all Phase 1 analysis
# ---------------------------------------------------------------------------

def run_phase1(project_path: str) -> dict[str, Any]:
    """Execute all Phase 1 static analysis and return a unified result dict.

    This is the main entry point for the deep analysis pipeline.
    """
    root = Path(project_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {project_path}")

    log.info("Phase 1: scanning %s", root)
    files = _source_files(root)
    log.info("Phase 1: found %d source files", len(files))

    todos = extract_todos(root, files)
    log.info("Phase 1: found %d TODO/FIXME markers", len(todos))

    import_graph = build_import_graph(root, files)
    log.info("Phase 1: import graph has %d nodes", len(import_graph["edges"]))

    git_churn = compute_git_churn(root)
    log.info("Phase 1: git churn for %d files", len(git_churn))

    complexity = compute_complexity(root, files)
    log.info("Phase 1: complexity ranked %d files", len(complexity))

    entry_points = detect_entry_points(root, files)
    log.info("Phase 1: detected %d entry points", len(entry_points))

    repo_map = build_repo_map(root, files)
    log.info("Phase 1: repo map is %d chars", len(repo_map))

    docs = read_docs(root)
    log.info("Phase 1: read %d doc files", len(docs))

    critical_files = read_critical_files(
        root, import_graph, entry_points, complexity,
    )
    log.info("Phase 1: read %d critical files", len(critical_files))

    return {
        "root": str(root),
        "source_file_count": len(files),
        "todos": todos,
        "import_graph": import_graph,
        "git_churn": git_churn,
        "complexity": complexity,
        "entry_points": entry_points,
        "repo_map": repo_map,
        "docs": docs,
        "critical_files": critical_files,
    }
