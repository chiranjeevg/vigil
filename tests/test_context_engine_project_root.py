"""ContextEngine.build(project_root=...) reads from the given tree."""

from __future__ import annotations

from pathlib import Path

import pytest

from vigil.config import VigilConfig, ProjectConfig
from vigil.core.context_engine import ContextEngine


def test_build_uses_project_root_override(tmp_path: Path) -> None:
    main = tmp_path / "main"
    main.mkdir()
    (main / "main_only.txt").write_text("main")

    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / "wt_only.txt").write_text("worktree")

    cfg = VigilConfig(
        project=ProjectConfig(
            path=str(main),
            language="python",
            name="p",
            include_paths=["."],
            exclude_paths=[],
        ),
    )
    ce = ContextEngine(cfg)
    task = {
        "type": "improvement",
        "work_type": "improvement",
        "context_files": ["wt_only.txt"],
    }
    ctx = ce.build(
        task,
        progress_summary="",
        recent_benchmarks=[],
        completed_tasks=[],
        project_root=wt,
    )
    assert "wt_only.txt" in ctx["file_contents"]
    assert ctx["file_contents"]["wt_only.txt"] == "worktree"
