"""Configuration models and YAML loading/saving for Vigil projects."""

from __future__ import annotations

import logging
import re
from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deep analysis profile — auto-detected from provider, overridable in YAML
# ---------------------------------------------------------------------------

_THINKING_MODEL_PATTERNS: tuple[str, ...] = (
    "qwen3",
    "qwq",
    "deepseek-r1",
    "deepseek-reasoner",
)

_SIZE_PATTERN = re.compile(r"(\d+)[bB]")


def _estimate_model_size_b(model: str) -> int | None:
    """Extract approximate parameter count (in billions) from an Ollama model tag."""
    m = _SIZE_PATTERN.search(model)
    return int(m.group(1)) if m else None


def _is_thinking_model(model: str) -> bool:
    low = model.lower()
    return any(pat in low for pat in _THINKING_MODEL_PATTERNS)


def _is_local_provider(provider: "ProviderConfig") -> bool:
    if provider.type == "ollama":
        return True
    url = provider.base_url.lower()
    return "localhost" in url or "127.0.0.1" in url


class DeepAnalysisProfile:
    """Resolved runtime profile — all values concrete, no ``auto``."""

    __slots__ = (
        "max_repo_map_chars",
        "max_file_chars",
        "max_investigation_targets",
        "phase2_max_tokens",
        "phase3_max_tokens",
        "phase4_max_tokens",
        "timeout_seconds",
        "disable_thinking",
        "parallel_workers",
    )

    def __init__(
        self,
        *,
        max_repo_map_chars: int,
        max_file_chars: int,
        max_investigation_targets: int,
        phase2_max_tokens: int,
        phase3_max_tokens: int,
        phase4_max_tokens: int,
        timeout_seconds: int,
        disable_thinking: bool,
        parallel_workers: int,
    ):
        self.max_repo_map_chars = max_repo_map_chars
        self.max_file_chars = max_file_chars
        self.max_investigation_targets = max_investigation_targets
        self.phase2_max_tokens = phase2_max_tokens
        self.phase3_max_tokens = phase3_max_tokens
        self.phase4_max_tokens = phase4_max_tokens
        self.timeout_seconds = timeout_seconds
        self.disable_thinking = disable_thinking
        self.parallel_workers = parallel_workers


_PROFILES: dict[str, dict] = {
    "api_fast": {
        "max_repo_map_chars": 16000,
        "max_file_chars": 6000,
        "max_investigation_targets": 5,
        "phase2_max_tokens": 4000,
        "phase3_max_tokens": 3000,
        "phase4_max_tokens": 5000,
        "timeout_seconds": 60,
        "disable_thinking": False,
        "parallel_workers": 5,
    },
    "local_large": {
        "max_repo_map_chars": 4000,
        "max_file_chars": 2500,
        "max_investigation_targets": 3,
        "phase2_max_tokens": 2000,
        "phase3_max_tokens": 2000,
        "phase4_max_tokens": 3000,
        "timeout_seconds": 180,
        "disable_thinking": False,
        "parallel_workers": 2,
    },
    "local_small": {
        "max_repo_map_chars": 2000,
        "max_file_chars": 1500,
        "max_investigation_targets": 2,
        "phase2_max_tokens": 1500,
        "phase3_max_tokens": 1500,
        "phase4_max_tokens": 2000,
        "timeout_seconds": 120,
        "disable_thinking": False,
        "parallel_workers": 1,
    },
}


def _auto_detect_profile_name(provider: "ProviderConfig") -> str:
    if not _is_local_provider(provider):
        return "api_fast"

    size = _estimate_model_size_b(provider.model)
    if size is not None and size >= 25:
        return "local_large"
    return "local_small"


def resolve_deep_analysis_profile(
    provider: "ProviderConfig",
    overrides: "DeepAnalysisConfig | None" = None,
) -> DeepAnalysisProfile:
    """Merge auto-detected defaults with explicit YAML overrides."""
    if overrides and overrides.profile != "auto":
        profile_name = overrides.profile
    else:
        profile_name = _auto_detect_profile_name(provider)

    base = dict(_PROFILES.get(profile_name, _PROFILES["local_large"]))

    if _is_thinking_model(provider.model):
        base["disable_thinking"] = True

    if overrides:
        for field in DeepAnalysisConfig.model_fields:
            if field == "profile":
                continue
            val = getattr(overrides, field)
            if val is not None:
                if field == "disable_thinking" and val == "auto":
                    continue
                if field == "disable_thinking":
                    base[field] = val == "true"
                else:
                    base[field] = val

    return DeepAnalysisProfile(**base)


class DeepAnalysisConfig(BaseModel):
    """Optional user overrides for the deep analysis pipeline. Omitted fields use auto-detected values."""

    profile: str = "auto"
    max_investigation_targets: int | None = None
    max_repo_map_chars: int | None = None
    max_file_chars: int | None = None
    timeout_seconds: int | None = None
    disable_thinking: str = "auto"
    parallel_workers: int | None = None
    phase2_max_tokens: int | None = None
    phase3_max_tokens: int | None = None
    phase4_max_tokens: int | None = None


class CoverageConfig(BaseModel):
    enabled: bool = False
    command: str = ""
    report_path: str = ""
    format: str = "auto"
    target: int = 90


class ProjectConfig(BaseModel):
    path: str
    language: str = "auto"
    name: str = "My Project"
    include_paths: list[str] = ["src/", "lib/", "test/", "tests/"]
    exclude_paths: list[str] = ["node_modules/", "venv/", ".git/", "build/", "dist/"]
    read_only_paths: list[str] = []


class ProviderConfig(BaseModel):
    type: str = "ollama"
    model: str = "qwen2.5-coder:14b"
    base_url: str = "http://localhost:11434"
    max_tokens: int = 8192
    temperature: float = 0.2
    api_key_env: str | None = None
    deep_analysis: DeepAnalysisConfig | None = None


class TestsConfig(BaseModel):
    command: str = ""
    timeout: int = 300
    coverage: CoverageConfig = CoverageConfig()


class BenchmarksConfig(BaseModel):
    enabled: bool = False
    command: str = ""
    timeout: int = 600
    results_path: str = ""
    format: str = "auto"
    regression_threshold: float = -2.0
    run_every: int = 3


class TaskPriority(str, Enum):
    FIX_TESTS = "fix_tests"
    RUN_BENCHMARKS = "run_benchmarks"
    TEST_COVERAGE = "test_coverage"
    OPTIMIZE_PERFORMANCE = "optimize_performance"
    MODERNIZE_CODE = "modernize_code"
    REDUCE_COMPLEXITY = "reduce_complexity"
    FIX_WARNINGS = "fix_warnings"
    REFACTOR = "refactor"


class CustomTask(BaseModel):
    id: str
    description: str
    files: list[str] = []
    priority: int = 5


class TasksConfig(BaseModel):
    priorities: list[str] = [e.value for e in TaskPriority]
    custom: list[CustomTask] = []
    instructions: dict[str, str] = {}


class ControlsConfig(BaseModel):
    max_iterations_per_day: int = 200
    max_iterations_total: int | None = None
    sleep_between_iterations: int = 30
    sleep_after_failure: int = 60
    max_consecutive_no_improvement: int = 10
    min_improvement_threshold: float = 0.1
    work_branch: str = "vigil-improvements"
    auto_commit: bool = True
    commit_prefix: str = "vigil"
    max_files_per_iteration: int = 5
    max_lines_changed: int = 200
    require_test_pass: bool = True
    dry_run: bool = False
    pause_on_battery: bool = True


class NotificationsConfig(BaseModel):
    log_level: str = "info"
    desktop_enabled: bool = True
    desktop_on_failure: bool = True
    desktop_on_milestone: bool = True


class ApiConfig(BaseModel):
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 7420


class PRConfig(BaseModel):
    enabled: bool = False
    strategy: str = "per_iteration"
    base_branch: str = "main"
    auto_push: bool = True
    labels: list[str] = ["vigil", "automated"]
    reviewers: list[str] = []
    use_llm_description: bool = True


class VigilConfig(BaseModel):
    project: ProjectConfig
    provider: ProviderConfig = ProviderConfig()
    tests: TestsConfig = TestsConfig()
    benchmarks: BenchmarksConfig = BenchmarksConfig()
    tasks: TasksConfig = TasksConfig()
    controls: ControlsConfig = ControlsConfig()
    notifications: NotificationsConfig = NotificationsConfig()
    api: ApiConfig = ApiConfig()
    pr: PRConfig = PRConfig()


def load_config(path: str) -> VigilConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Config file not found: {config_path.resolve()}\n"
            f"Create a vigil.yaml with at minimum:\n"
            f"  project:\n"
            f"    path: /path/to/your/project"
        )

    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML in {config_path}: {e}") from e

    if not isinstance(raw, dict):
        raise ValueError(f"Config file must contain a YAML mapping, got {type(raw).__name__}")

    if "project" not in raw:
        raise ValueError("Config must include a 'project' section with at least 'path'")

    try:
        return VigilConfig(**raw)
    except Exception as e:
        raise ValueError(f"Config validation error: {e}") from e


def save_config(config: VigilConfig, path: str) -> None:
    data = config.model_dump(mode="json")
    config_path = Path(path)
    with open(config_path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    log.info("Config saved to %s", config_path)
