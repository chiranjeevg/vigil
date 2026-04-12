"""StateManager stores under ~/.vigil/state/<hash>/ and migrates legacy .vigil-state/."""

from __future__ import annotations

from pathlib import Path

import pytest

from vigil.core.state import StateManager
from vigil.core.state_paths import external_state_dir, stable_project_hash


def test_external_state_dir_stable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "myproject"
    proj.mkdir()
    h = stable_project_hash(str(proj.resolve()))
    d = external_state_dir(str(proj))
    assert h in str(d)
    assert d == tmp_path / ".vigil" / "state" / h


def test_migrates_legacy_vigil_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "proj"
    proj.mkdir()
    legacy = proj / ".vigil-state"
    legacy.mkdir()
    (legacy / "iterations.json").write_text("[]")
    (legacy / "tasks.json").write_text("[]")
    (legacy / "benchmarks.json").write_text("[]")
    (legacy / "progress.md").write_text("# Log\n")

    sm = StateManager(str(proj))
    assert sm.get_all_iterations() == []
    ext = external_state_dir(str(proj))
    assert (ext / "iterations.json").exists()
    assert (proj / ".vigil-state.migrated").exists() or not (proj / ".vigil-state").exists()
