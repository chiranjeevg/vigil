"""
Project analyzer that uses LLM to suggest configuration based on project structure.
"""
import concurrent.futures
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

LANGUAGE_PATTERNS = {
    "python": ["*.py", "pyproject.toml", "setup.py", "requirements.txt", "Pipfile"],
    "javascript": ["*.js", "*.jsx", "package.json"],
    "typescript": ["*.ts", "*.tsx", "tsconfig.json"],
    "java": ["*.java", "pom.xml", "build.gradle", "build.gradle.kts"],
    "kotlin": ["*.kt", "*.kts", "build.gradle.kts"],
    "go": ["*.go", "go.mod", "go.sum"],
    "rust": ["*.rs", "Cargo.toml"],
    "cpp": ["*.cpp", "*.cc", "*.cxx", "*.hpp", "*.h", "CMakeLists.txt", "Makefile"],
    "c": ["*.c", "*.h", "CMakeLists.txt", "Makefile"],
    "ruby": ["*.rb", "Gemfile", "Rakefile"],
    "php": ["*.php", "composer.json"],
    "swift": ["*.swift", "Package.swift"],
    "csharp": ["*.cs", "*.csproj", "*.sln"],
}

TEST_COMMANDS = {
    "python": {
        "pytest": "pytest",
        "unittest": "python -m unittest discover",
        "nose": "nosetests",
    },
    "javascript": {
        "jest": "npm test",
        "mocha": "npm test",
        "vitest": "npm test",
    },
    "typescript": {
        "jest": "npm test",
        "vitest": "npm test",
    },
    "java": {
        "maven": "mvn test",
        "gradle": "./gradlew test",
    },
    "go": {
        "go": "go test ./...",
    },
    "rust": {
        "cargo": "cargo test",
    },
    "ruby": {
        "rspec": "bundle exec rspec",
        "minitest": "bundle exec rake test",
    },
}

BENCHMARK_COMMANDS = {
    "python": {
        "pytest-benchmark": "pytest --benchmark-only",
        "pyperf": "python -m pyperf",
    },
    "java": {
        "jmh": "./gradlew jmh",
    },
    "go": {
        "go": "go test -bench=. ./...",
    },
    "rust": {
        "cargo": "cargo bench",
    },
    "javascript": {
        "benchmark": "npm run benchmark",
    },
}

COVERAGE_COMMANDS = {
    "python": {
        "pytest-cov": "pytest --cov --cov-report=xml",
        "coverage": "coverage run -m pytest && coverage xml",
    },
    "javascript": {
        "jest": "npm test -- --coverage",
        "c8": "npx c8 npm test",
    },
    "go": {
        "go": "go test -coverprofile=coverage.out ./...",
    },
    "rust": {
        "tarpaulin": "cargo tarpaulin --out Xml",
    },
    "java": {
        "jacoco": "./gradlew jacocoTestReport",
    },
}


def scan_project_structure(project_path: str) -> dict:
    """Scan a project directory and return structural information."""
    path = Path(project_path)
    if not path.exists():
        raise ValueError(f"Project path does not exist: {project_path}")
    if not path.is_dir():
        raise ValueError(f"Project path is not a directory: {project_path}")

    result = {
        "path": str(path.absolute()),
        "name": path.name,
        "is_git_repo": (path / ".git").exists(),
        "files": [],
        "directories": [],
        "config_files": [],
        "detected_languages": [],
        "detected_frameworks": [],
        "has_tests": False,
        "has_benchmarks": False,
        "file_count": 0,
    }

    config_file_names = {
        "package.json", "pyproject.toml", "setup.py", "Cargo.toml",
        "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
        "CMakeLists.txt", "Makefile", "Gemfile", "composer.json",
        "tsconfig.json", ".eslintrc.js", ".prettierrc",
    }

    test_indicators = {"test", "tests", "spec", "specs", "__tests__"}
    benchmark_indicators = {"benchmark", "benchmarks", "bench", "perf"}

    language_scores: dict[str, int] = {}

    for item in path.rglob("*"):
        if item.is_file():
            rel_path = str(item.relative_to(path))
            if any(skip in rel_path for skip in [
                "node_modules", ".git", "__pycache__", ".venv", "venv",
                "target", "build", "dist", ".idea", ".vscode"
            ]):
                continue

            result["file_count"] += 1
            if result["file_count"] <= 100:
                result["files"].append(rel_path)

            if item.name in config_file_names:
                result["config_files"].append(rel_path)

            for lang, patterns in LANGUAGE_PATTERNS.items():
                for pattern in patterns:
                    if item.match(pattern):
                        language_scores[lang] = language_scores.get(lang, 0) + 1

            rel_lower = rel_path.lower()
            if any(t in rel_lower for t in test_indicators):
                result["has_tests"] = True
            if any(b in rel_lower for b in benchmark_indicators):
                result["has_benchmarks"] = True

        elif item.is_dir():
            rel_path = str(item.relative_to(path))
            if not any(skip in rel_path for skip in [
                "node_modules", ".git", "__pycache__", ".venv", "venv",
                "target", "build", "dist"
            ]):
                if len(result["directories"]) < 50:
                    result["directories"].append(rel_path)

    if language_scores:
        sorted_langs = sorted(language_scores.items(), key=lambda x: -x[1])
        result["detected_languages"] = [lang for lang, _ in sorted_langs[:3]]

    return result


def detect_test_framework(project_path: str, language: str) -> dict | None:
    """Detect which test framework is used in the project."""
    path = Path(project_path)

    if language == "python":
        if (path / "pytest.ini").exists() or (path / "pyproject.toml").exists():
            pyproject = path / "pyproject.toml"
            if pyproject.exists():
                content = pyproject.read_text()
                if "pytest" in content:
                    return {"framework": "pytest", "command": "pytest"}
        if any(path.rglob("test_*.py")) or any(path.rglob("*_test.py")):
            return {"framework": "pytest", "command": "pytest"}

    elif language in ("javascript", "typescript"):
        pkg_json = path / "package.json"
        if pkg_json.exists():
            try:
                pkg = json.loads(pkg_json.read_text())
                scripts = pkg.get("scripts", {})
                deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "jest" in deps:
                    return {"framework": "jest", "command": "npm test"}
                if "vitest" in deps:
                    return {"framework": "vitest", "command": "npm test"}
                if "test" in scripts:
                    return {"framework": "npm", "command": "npm test"}
            except json.JSONDecodeError:
                pass

    elif language == "java":
        if (path / "build.gradle").exists() or (path / "build.gradle.kts").exists():
            return {"framework": "gradle", "command": "./gradlew test"}
        if (path / "pom.xml").exists():
            return {"framework": "maven", "command": "mvn test"}

    elif language == "go":
        if any(path.rglob("*_test.go")):
            return {"framework": "go", "command": "go test ./..."}

    elif language == "rust":
        if (path / "Cargo.toml").exists():
            return {"framework": "cargo", "command": "cargo test"}

    return None


def generate_default_config(project_path: str) -> dict:
    """Generate a default configuration based on project analysis."""
    scan = scan_project_structure(project_path)

    primary_language = scan["detected_languages"][0] if scan["detected_languages"] else "auto"

    include_paths = ["src/", "lib/"]
    if primary_language == "python":
        include_paths = ["src/", "lib/", scan["name"] + "/"]
    elif primary_language in ("javascript", "typescript"):
        include_paths = ["src/", "lib/", "app/", "pages/", "components/"]
    elif primary_language == "java":
        include_paths = ["src/main/", "src/test/"]
    elif primary_language == "go":
        include_paths = ["cmd/", "pkg/", "internal/"]

    existing_dirs = [d for d in include_paths if (Path(project_path) / d).exists()]
    if not existing_dirs:
        existing_dirs = [d + "/" for d in scan["directories"][:3] if d and not d.startswith(".")]
    include_paths = existing_dirs or ["./"]

    test_info = detect_test_framework(project_path, primary_language)
    test_command = test_info["command"] if test_info else ""

    coverage_cmd = ""
    if primary_language in COVERAGE_COMMANDS:
        coverage_cmd = list(COVERAGE_COMMANDS[primary_language].values())[0]

    benchmark_cmd = ""
    if primary_language in BENCHMARK_COMMANDS and BENCHMARK_COMMANDS[primary_language]:
        benchmark_cmd = list(BENCHMARK_COMMANDS[primary_language].values())[0]

    return {
        "project": {
            "path": scan["path"],
            "name": scan["name"],
            "language": primary_language,
            "include_paths": include_paths,
            "exclude_paths": [
                "node_modules/", ".git/", "__pycache__/", ".venv/", "venv/",
                "target/", "build/", "dist/", ".idea/", ".vscode/",
            ],
            "read_only_paths": [],
        },
        "provider": {
            "type": "ollama",
            "model": "qwen2.5-coder:14b",
            "base_url": "http://localhost:11434",
            "max_tokens": 8192,
            "temperature": 0.2,
            "api_key_env": None,
        },
        "tests": {
            "command": test_command,
            "timeout": 300,
            "coverage": {
                "enabled": bool(coverage_cmd),
                "command": coverage_cmd,
                "report_path": "",
                "format": "auto",
                "target": 80,
            },
        },
        "benchmarks": {
            "enabled": scan["has_benchmarks"],
            "command": benchmark_cmd,
            "timeout": 600,
            "results_path": "",
            "format": "auto",
            "regression_threshold": -2.0,
            "run_every": 3,
        },
        "tasks": {
            "priorities": [
                "fix_tests",
                "test_coverage",
                "optimize_performance",
                "modernize_code",
                "reduce_complexity",
                "refactor",
            ],
            "custom": [],
            "instructions": {},
        },
        "controls": {
            "max_iterations_per_day": 100,
            "max_iterations_total": None,
            "sleep_between_iterations": 30,
            "sleep_after_failure": 60,
            "max_consecutive_no_improvement": 10,
            "min_improvement_threshold": 0.1,
            "work_branch": "vigil-improvements",
            "auto_commit": True,
            "commit_prefix": "vigil",
            "max_files_per_iteration": 5,
            "max_lines_changed": 200,
            "require_test_pass": True,
            "dry_run": False,
            "pause_on_battery": True,
        },
        "notifications": {
            "log_level": "info",
            "desktop_enabled": True,
            "desktop_on_failure": True,
            "desktop_on_milestone": True,
        },
        "api": {
            "enabled": True,
            "host": "127.0.0.1",
            "port": 7420,
        },
        "_analysis": {
            "detected_languages": scan["detected_languages"],
            "is_git_repo": scan["is_git_repo"],
            "has_tests": scan["has_tests"],
            "has_benchmarks": scan["has_benchmarks"],
            "file_count": scan["file_count"],
            "config_files": scan["config_files"],
        },
    }


def analyze_with_llm(project_path: str, provider) -> dict:
    """Use LLM to provide more detailed analysis and suggestions."""
    scan = scan_project_structure(project_path)
    defaults = generate_default_config(project_path)

    file_sample = "\n".join(scan["files"][:50])
    config_files_content = {}
    for cf in scan["config_files"][:5]:
        try:
            content = (Path(project_path) / cf).read_text()[:2000]
            config_files_content[cf] = content
        except Exception:
            pass

    prompt = f"""Analyze this project and suggest optimal Vigil configuration.

Project: {scan['name']}
Path: {scan['path']}
Detected languages: {scan['detected_languages']}
Has tests: {scan['has_tests']}
Has benchmarks: {scan['has_benchmarks']}
File count: {scan['file_count']}

Sample files:
{file_sample}

Config files found:
{json.dumps(list(config_files_content.keys()), indent=2)}

Current defaults:
- Test command: {defaults['tests']['command']}
- Coverage command: {defaults['tests']['coverage']['command']}
- Benchmark command: {defaults['benchmarks']['command']}

Please respond with ONLY a JSON object containing suggested improvements:
{{
  "test_command": "suggested test command or null if default is good",
  "coverage_command": "suggested coverage command or null",
  "benchmark_command": "suggested benchmark command or null",
  "include_paths": ["suggested", "paths"] or null,
  "task_instructions": {{
    "optimize_performance": "specific instructions for this project",
    "test_coverage": "specific instructions"
  }},
  "notes": "any important notes about this project"
}}
"""

    try:
        response = provider.complete(
            "You are a code analysis assistant. Respond only with valid JSON.",
            prompt
        )
        suggestions = json.loads(response.text)
        return {
            "defaults": defaults,
            "suggestions": suggestions,
            "analysis": scan,
        }
    except Exception as e:
        log.warning("LLM analysis failed: %s", e)
        return {
            "defaults": defaults,
            "suggestions": None,
            "analysis": scan,
        }


BUILTIN_TASK_CATALOG = [
    {
        "type": "fix_tests",
        "label": "Fix Failing Tests",
        "description": "Identify and fix tests that are currently failing",
        "category": "quality",
    },
    {
        "type": "test_coverage",
        "label": "Increase Test Coverage",
        "description": "Add unit tests for uncovered code paths",
        "category": "quality",
    },
    {
        "type": "optimize_performance",
        "label": "Optimize Performance",
        "description": "Find and fix performance bottlenecks",
        "category": "performance",
    },
    {
        "type": "modernize_code",
        "label": "Modernize Code",
        "description": "Update to modern language features and idioms",
        "category": "quality",
    },
    {
        "type": "reduce_complexity",
        "label": "Reduce Complexity",
        "description": "Simplify overly complex functions and reduce cyclomatic complexity",
        "category": "quality",
    },
    {
        "type": "fix_warnings",
        "label": "Fix Warnings",
        "description": "Resolve compiler/linter warnings and deprecation notices",
        "category": "quality",
    },
    {
        "type": "refactor",
        "label": "Refactor",
        "description": "Improve code structure, naming, and organization",
        "category": "quality",
    },
    {
        "type": "security_audit",
        "label": "Security Audit",
        "description": "Find and fix common security vulnerabilities",
        "category": "security",
    },
    {
        "type": "documentation",
        "label": "Improve Documentation",
        "description": "Add or improve docstrings, comments, and inline documentation",
        "category": "docs",
    },
    {
        "type": "error_handling",
        "label": "Improve Error Handling",
        "description": "Add proper error handling, input validation, and edge case coverage",
        "category": "quality",
    },
    {
        "type": "type_safety",
        "label": "Improve Type Safety",
        "description": "Add type annotations and fix type errors",
        "category": "quality",
    },
]


def suggest_tasks_for_project(project_path: str, provider=None) -> dict:
    """Analyze a project and suggest prioritized tasks with rationale.

    Returns both static analysis based suggestions and (optionally)
    LLM-powered suggestions when a provider is available.
    """
    scan = scan_project_structure(project_path)
    primary_lang = scan["detected_languages"][0] if scan["detected_languages"] else "auto"

    suggested: list[dict] = []
    available: list[dict] = []

    if scan["has_tests"]:
        suggested.append({
            "type": "fix_tests",
            "label": "Fix Failing Tests",
            "description": "Identify and fix tests that are currently failing",
            "reason": "Test files detected in project — fixing broken tests should always come first.",
            "priority": 1,
            "enabled": True,
            "instructions": "",
        })
        suggested.append({
            "type": "test_coverage",
            "label": "Increase Test Coverage",
            "description": "Add unit tests for uncovered code paths",
            "reason": f"Test framework detected for {primary_lang}. Increasing coverage catches regressions early.",
            "priority": 2,
            "enabled": True,
            "instructions": "",
        })
    else:
        suggested.append({
            "type": "test_coverage",
            "label": "Add Tests",
            "description": "Create a test suite for the project",
            "reason": "No test files detected — adding tests is the highest-impact improvement.",
            "priority": 1,
            "enabled": True,
            "instructions": f"This {primary_lang} project has no tests yet. Start with the most critical modules.",
        })

    suggested.append({
        "type": "optimize_performance",
        "label": "Optimize Performance",
        "description": "Find and fix performance bottlenecks",
        "reason": f"Scanned {scan['file_count']} files — look for inefficient patterns in {primary_lang}.",
        "priority": len(suggested) + 1,
        "enabled": True,
        "instructions": "",
    })

    if primary_lang in ("python", "typescript", "javascript"):
        suggested.append({
            "type": "type_safety",
            "label": "Improve Type Safety",
            "description": "Add type annotations and fix type errors",
            "reason": f"{primary_lang} benefits significantly from type annotations for maintainability.",
            "priority": len(suggested) + 1,
            "enabled": True,
            "instructions": "",
        })

    suggested.append({
        "type": "modernize_code",
        "label": "Modernize Code",
        "description": "Update to modern language features and idioms",
        "reason": f"Ensure the codebase uses current {primary_lang} best practices.",
        "priority": len(suggested) + 1,
        "enabled": True,
        "instructions": "",
    })

    suggested.append({
        "type": "reduce_complexity",
        "label": "Reduce Complexity",
        "description": "Simplify overly complex functions",
        "reason": "Lower complexity means fewer bugs and easier maintenance.",
        "priority": len(suggested) + 1,
        "enabled": True,
        "instructions": "",
    })

    suggested_types = {t["type"] for t in suggested}
    for task in BUILTIN_TASK_CATALOG:
        if task["type"] not in suggested_types:
            available.append({
                **task,
                "reason": "",
                "priority": 0,
                "enabled": False,
                "instructions": "",
            })

    result = {
        "suggested": suggested,
        "available": available,
        "analysis": {
            "languages": scan["detected_languages"],
            "file_count": scan["file_count"],
            "has_tests": scan["has_tests"],
            "has_benchmarks": scan["has_benchmarks"],
            "config_files": scan["config_files"],
            "is_git_repo": scan["is_git_repo"],
        },
        "llm_enhanced": False,
    }

    if provider is None:
        return result

    file_sample = "\n".join(scan["files"][:60])
    config_contents: list[str] = []
    for cf in scan["config_files"][:5]:
        try:
            content = (Path(project_path) / cf).read_text()[:2000]
            config_contents.append(f"--- {cf} ---\n{content}")
        except Exception:
            pass

    prompt = f"""You are analyzing a software project to suggest improvement tasks for an autonomous coding agent.

Project: {scan['name']}
Languages: {', '.join(scan['detected_languages']) or 'unknown'}
File count: {scan['file_count']}
Has tests: {scan['has_tests']}
Has benchmarks: {scan['has_benchmarks']}

Files:
{file_sample}

Config files:
{chr(10).join(config_contents) or 'None found'}

Based on this project, suggest which improvement tasks are most valuable, in priority order.
For each task, explain WHY it's important for THIS specific project. Be concrete.

Respond with ONLY a JSON array. Each element:
{{
  "type": "task_type_slug",
  "label": "Human-readable label",
  "description": "What the task does",
  "reason": "Why this task matters for THIS project specifically",
  "instructions": "Specific instructions for the LLM when working on this task for THIS project"
}}

Include 4-8 tasks. Use these types when they fit: fix_tests, test_coverage, optimize_performance,
modernize_code, reduce_complexity, fix_warnings, refactor, security_audit, documentation,
error_handling, type_safety.
You can also suggest custom types (use snake_case slugs).
"""

    llm_timeout_s = 90

    def _call_llm():
        return provider.complete(
            (
                "You are a senior software architect. Respond with ONLY valid JSON — "
                "a JSON array of task objects. No markdown fences."
            ),
            prompt,
        )

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call_llm)
            response = future.result(timeout=llm_timeout_s)

        text = response.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        llm_tasks = json.loads(text)
        if isinstance(llm_tasks, list) and llm_tasks:
            enhanced: list[dict] = []
            for i, t in enumerate(llm_tasks):
                if not isinstance(t, dict) or "type" not in t:
                    continue
                enhanced.append({
                    "type": t["type"],
                    "label": t.get("label", t["type"].replace("_", " ").title()),
                    "description": t.get("description", ""),
                    "reason": t.get("reason", ""),
                    "priority": i + 1,
                    "enabled": True,
                    "instructions": t.get("instructions", ""),
                })

            all_types = {t["type"] for t in enhanced}
            for task in BUILTIN_TASK_CATALOG:
                if task["type"] not in all_types:
                    available.append({
                        **task,
                        "reason": "",
                        "priority": 0,
                        "enabled": False,
                        "instructions": "",
                    })

            result["suggested"] = enhanced
            result["available"] = [a for a in available if a["type"] not in all_types]
            result["llm_enhanced"] = True

    except concurrent.futures.TimeoutError:
        log.warning("LLM task suggestion timed out after %ds, using static analysis", llm_timeout_s)
    except Exception as e:
        log.warning("LLM task suggestion failed, using static analysis: %s", e)

    return result


def analyze_project_streaming(project_path: str, provider=None):
    """Generator that yields (event_type, data) tuples as analysis proceeds.

    Events:
      ("log", {"msg": str, "level": "info"|"detail"})
      ("scan_complete", {scan data})
      ("config_ready", {config data})
      ("tasks_ready", {suggested, available, ...})
      ("llm_prompt", {"system": str, "user": str})
      ("llm_chunk", {"text": str})   — full response when done
      ("done", {config, analysis, suggested, available, llm_enhanced})
      ("error", {"msg": str})
    """
    import time

    def emit(kind, data):
        return (kind, data)

    yield emit("log", {"msg": f"Starting analysis of {project_path}", "level": "info"})

    try:
        yield emit("log", {"msg": "Scanning project structure...", "level": "info"})
        t0 = time.time()
        scan = scan_project_structure(project_path)
        elapsed = time.time() - t0
        yield emit("log", {
            "msg": f"Scanned {scan['file_count']} files in {elapsed:.1f}s",
            "level": "info",
        })
        langs = ", ".join(scan["detected_languages"]) or "unknown"
        yield emit("log", {"msg": f"Detected languages: {langs}", "level": "detail"})
        if scan["config_files"]:
            yield emit("log", {
                "msg": f"Config files found: {', '.join(scan['config_files'][:8])}",
                "level": "detail",
            })
        yield emit("log", {
            "msg": f"Git repo: {'yes' if scan['is_git_repo'] else 'no'} | "
                   f"Tests: {'detected' if scan['has_tests'] else 'none'} | "
                   f"Benchmarks: {'detected' if scan['has_benchmarks'] else 'none'}",
            "level": "detail",
        })
        yield emit("scan_complete", {
            "file_count": scan["file_count"],
            "languages": scan["detected_languages"],
            "has_tests": scan["has_tests"],
            "has_benchmarks": scan["has_benchmarks"],
            "is_git_repo": scan["is_git_repo"],
            "config_files": scan["config_files"],
        })

        yield emit("log", {"msg": "Generating default configuration...", "level": "info"})
        config = generate_default_config(project_path)
        analysis_data = config.pop("_analysis", {})
        primary_lang = scan["detected_languages"][0] if scan["detected_languages"] else "auto"

        test_cmd = config.get("tests", {}).get("command", "")
        if test_cmd:
            yield emit("log", {"msg": f"Detected test command: {test_cmd}", "level": "detail"})
        bench_cmd = config.get("benchmarks", {}).get("command", "")
        if bench_cmd:
            yield emit("log", {"msg": f"Detected benchmark command: {bench_cmd}", "level": "detail"})
        yield emit("config_ready", config)

        yield emit("log", {"msg": "Building task suggestions from static analysis...", "level": "info"})
        task_result = _suggest_tasks_static(project_path, scan, primary_lang)
        suggested = task_result["suggested"]
        available = task_result["available"]
        for t in suggested:
            yield emit("log", {
                "msg": f"  [{t['priority']}] {t['label']} — {t['reason'][:100]}",
                "level": "detail",
            })
        yield emit("tasks_ready", task_result)

        llm_enhanced = False
        if provider is not None:
            yield emit("log", {"msg": f"Requesting AI-enhanced suggestions from {provider.name()}...", "level": "info"})

            file_sample = "\n".join(scan["files"][:60])
            config_contents: list[str] = []
            for cf in scan["config_files"][:5]:
                try:
                    content = (Path(project_path) / cf).read_text()[:2000]
                    config_contents.append(f"--- {cf} ---\n{content}")
                except Exception:
                    pass

            sys_prompt = (
                "You are a senior software architect. Respond with ONLY valid JSON — "
                "a JSON array of task objects. No markdown fences."
            )
            user_prompt = f"""You are analyzing a software project to suggest improvement tasks \
for an autonomous coding agent.

Project: {scan['name']}
Languages: {langs}
File count: {scan['file_count']}
Has tests: {scan['has_tests']}
Has benchmarks: {scan['has_benchmarks']}

Files:
{file_sample}

Config files:
{chr(10).join(config_contents) or 'None found'}

Based on this project, suggest which improvement tasks are most valuable, in priority order.
For each task, explain WHY it's important for THIS specific project. Be concrete.

Respond with ONLY a JSON array. Each element:
{{
  "type": "task_type_slug",
  "label": "Human-readable label",
  "description": "What the task does",
  "reason": "Why this task matters for THIS project specifically",
  "instructions": "Specific instructions for the LLM when working on this task for THIS project"
}}

Include 4-8 tasks. Use these types when they fit: fix_tests, test_coverage, optimize_performance,
modernize_code, reduce_complexity, fix_warnings, refactor, security_audit, documentation,
error_handling, type_safety.
You can also suggest custom types (use snake_case slugs)."""

            yield emit("llm_prompt", {"system": sys_prompt, "user": user_prompt[:500] + "..."})
            yield emit(
                "log",
                {
                    "msg": (
                        f"Sent prompt ({len(user_prompt)} chars) — waiting for LLM response..."
                    ),
                    "level": "info",
                },
            )

            llm_timeout_s = 90
            try:
                t0 = time.time()

                def _call():
                    return provider.complete(sys_prompt, user_prompt)

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(_call)
                    response = future.result(timeout=llm_timeout_s)

                elapsed = time.time() - t0
                yield emit(
                    "log",
                    {
                        "msg": (
                            f"LLM responded in {elapsed:.1f}s ({len(response.text)} chars)"
                        ),
                        "level": "info",
                    },
                )
                yield emit("llm_chunk", {"text": response.text[:2000]})

                text = response.text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()

                llm_tasks = json.loads(text)
                if isinstance(llm_tasks, list) and llm_tasks:
                    enhanced = []
                    for i, t in enumerate(llm_tasks):
                        if not isinstance(t, dict) or "type" not in t:
                            continue
                        enhanced.append({
                            "type": t["type"],
                            "label": t.get("label", t["type"].replace("_", " ").title()),
                            "description": t.get("description", ""),
                            "reason": t.get("reason", ""),
                            "priority": i + 1,
                            "enabled": True,
                            "instructions": t.get("instructions", ""),
                        })

                    all_types = {t["type"] for t in enhanced}
                    new_available = [
                        {**bt, "reason": "", "priority": 0, "enabled": False, "instructions": ""}
                        for bt in BUILTIN_TASK_CATALOG if bt["type"] not in all_types
                    ]
                    suggested = enhanced
                    available = new_available
                    llm_enhanced = True
                    yield emit("log", {"msg": f"AI suggested {len(enhanced)} tasks", "level": "info"})
                    for t in enhanced:
                        yield emit("log", {
                            "msg": f"  [{t['priority']}] {t['label']} — {t['reason'][:100]}",
                            "level": "detail",
                        })
                else:
                    yield emit(
                        "log",
                        {
                            "msg": (
                                "LLM returned empty/invalid list — keeping static suggestions"
                            ),
                            "level": "info",
                        },
                    )

            except concurrent.futures.TimeoutError:
                yield emit(
                    "log",
                    {
                        "msg": (
                            f"LLM timed out after {llm_timeout_s}s — using static suggestions"
                        ),
                        "level": "info",
                    },
                )
            except json.JSONDecodeError as e:
                yield emit("log", {"msg": f"Failed to parse LLM JSON: {e} — using static suggestions", "level": "info"})
            except Exception as e:
                yield emit("log", {"msg": f"LLM error: {e} — using static suggestions", "level": "info"})
        else:
            yield emit("log", {"msg": "No LLM provider available — using static analysis only", "level": "info"})

        final = {
            "config": config,
            "analysis": analysis_data,
            "suggested": suggested,
            "available": available,
            "llm_enhanced": llm_enhanced,
        }
        yield emit("log", {"msg": "Analysis complete", "level": "info"})
        yield emit("done", final)

    except Exception as e:
        log.exception("Streaming analysis failed")
        yield emit("error", {"msg": str(e)})


def _suggest_tasks_static(project_path: str, scan: dict, primary_lang: str) -> dict:
    """Static-only task suggestions (no LLM). Used by streaming pipeline."""
    suggested: list[dict] = []
    available: list[dict] = []

    if scan["has_tests"]:
        suggested.append({
            "type": "fix_tests", "label": "Fix Failing Tests",
            "description": "Identify and fix tests that are currently failing",
            "reason": "Test files detected — fixing broken tests should always come first.",
            "priority": 1, "enabled": True, "instructions": "",
        })
        suggested.append({
            "type": "test_coverage", "label": "Increase Test Coverage",
            "description": "Add unit tests for uncovered code paths",
            "reason": f"Test framework detected for {primary_lang}. Increasing coverage catches regressions early.",
            "priority": 2, "enabled": True, "instructions": "",
        })
    else:
        suggested.append({
            "type": "test_coverage", "label": "Add Tests",
            "description": "Create a test suite for the project",
            "reason": "No test files detected — adding tests is the highest-impact improvement.",
            "priority": 1, "enabled": True,
            "instructions": f"This {primary_lang} project has no tests yet. Start with the most critical modules.",
        })

    suggested.append({
        "type": "optimize_performance", "label": "Optimize Performance",
        "description": "Find and fix performance bottlenecks",
        "reason": f"Scanned {scan['file_count']} files — look for inefficient patterns in {primary_lang}.",
        "priority": len(suggested) + 1, "enabled": True, "instructions": "",
    })

    if primary_lang in ("python", "typescript", "javascript"):
        suggested.append({
            "type": "type_safety", "label": "Improve Type Safety",
            "description": "Add type annotations and fix type errors",
            "reason": f"{primary_lang} benefits significantly from type annotations for maintainability.",
            "priority": len(suggested) + 1, "enabled": True, "instructions": "",
        })

    suggested.append({
        "type": "modernize_code", "label": "Modernize Code",
        "description": "Update to modern language features and idioms",
        "reason": f"Ensure the codebase uses current {primary_lang} best practices.",
        "priority": len(suggested) + 1, "enabled": True, "instructions": "",
    })

    suggested.append({
        "type": "reduce_complexity", "label": "Reduce Complexity",
        "description": "Simplify overly complex functions",
        "reason": "Lower complexity means fewer bugs and easier maintenance.",
        "priority": len(suggested) + 1, "enabled": True, "instructions": "",
    })

    suggested_types = {t["type"] for t in suggested}
    for task in BUILTIN_TASK_CATALOG:
        if task["type"] not in suggested_types:
            available.append({
                **task, "reason": "", "priority": 0, "enabled": False, "instructions": "",
            })

    return {"suggested": suggested, "available": available, "llm_enhanced": False}


def list_recent_directories(base_path: str = None, limit: int = 20) -> list[dict]:
    """List recent/common project directories for quick selection."""
    if base_path is None:
        base_path = os.path.expanduser("~")

    common_locations = [
        os.path.expanduser("~/Developer"),
        os.path.expanduser("~/Projects"),
        os.path.expanduser("~/Code"),
        os.path.expanduser("~/workspace"),
        os.path.expanduser("~/repos"),
        os.path.expanduser("~/src"),
        os.path.expanduser("~/git"),
    ]

    results = []
    seen = set()

    for loc in common_locations:
        if os.path.isdir(loc):
            try:
                for item in sorted(os.listdir(loc)):
                    item_path = os.path.join(loc, item)
                    if os.path.isdir(item_path) and item_path not in seen:
                        is_git = os.path.isdir(os.path.join(item_path, ".git"))
                        results.append({
                            "path": item_path,
                            "name": item,
                            "is_git_repo": is_git,
                        })
                        seen.add(item_path)
                        if len(results) >= limit:
                            break
            except PermissionError:
                continue
        if len(results) >= limit:
            break

    return results
