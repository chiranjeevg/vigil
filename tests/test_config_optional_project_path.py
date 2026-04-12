"""Optional project.path and minimal project section in vigil.yaml."""

from __future__ import annotations

import textwrap
from pathlib import Path


def test_load_config_allows_missing_project_section(tmp_path: Path) -> None:
    from vigil.config import VigilConfig, load_config

    p = tmp_path / "vigil.yaml"
    p.write_text(
        textwrap.dedent(
            """
            provider:
              type: ollama
              model: qwen2.5-coder:14b
            """
        ).strip(),
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert isinstance(cfg, VigilConfig)
    assert cfg.project.path == ""


def test_load_config_allows_empty_project_path(tmp_path: Path) -> None:
    from vigil.config import load_config

    p = tmp_path / "vigil.yaml"
    p.write_text(
        textwrap.dedent(
            """
            project:
              path: ""
            provider:
              type: ollama
              model: qwen2.5-coder:14b
            """
        ).strip(),
        encoding="utf-8",
    )
    cfg = load_config(str(p))
    assert cfg.project.path == ""
