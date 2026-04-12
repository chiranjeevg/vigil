"""Extra coverage for state_paths migration and StateManager APIs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vigil.core.state import StateManager
from vigil.core.state_paths import migrate_legacy_vigil_state_if_needed


def test_migration_skips_when_external_already_has_iterations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "p"
    proj.mkdir()
    legacy = proj / ".vigil-state"
    legacy.mkdir()
    (legacy / "iterations.json").write_text('[{"iteration":1}]')

    from vigil.core.state_paths import external_state_dir

    ext = external_state_dir(str(proj))
    ext.mkdir(parents=True)
    (ext / "iterations.json").write_text('[{"iteration":99}]')
    (ext / "tasks.json").write_text("[]")
    (ext / "benchmarks.json").write_text("[]")
    (ext / "progress.md").write_text("# x\n")

    migrate_legacy_vigil_state_if_needed(str(proj), ext)
    data = json.loads((ext / "iterations.json").read_text())
    assert data[0]["iteration"] == 99


def test_iterative_branch_setters_are_noops(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "p2"
    proj.mkdir()
    sm = StateManager(str(proj))
    assert sm.get_last_successful_branch() is None
    sm.set_last_successful_branch("vigil/x/foo-1")
    assert sm.get_last_successful_branch() is None


def test_save_iteration_roundtrip(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "p3"
    proj.mkdir()
    sm = StateManager(str(proj))
    sm.save_iteration({
        "iteration": 1,
        "timestamp": "2026-01-01T00:00:00Z",
        "task_type": "t",
        "task_description": "d",
        "status": "success",
        "benchmark_data": {},
        "summary": "ok",
        "duration_ms": 0,
        "steps": [],
        "files_changed": [],
        "diff": "",
        "commit_hash": "",
        "llm_response": "",
        "llm_prompt_system": "",
        "llm_prompt_user": "",
        "llm_tokens": 0,
        "llm_duration_s": 0,
        "changes_detail": [],
        "test_output": "",
        "branch_name": "b",
        "provider_name": "p",
    })
    assert sm.get_iteration(1) is not None
    assert sm.get_stats()["total_iterations"] == 1
