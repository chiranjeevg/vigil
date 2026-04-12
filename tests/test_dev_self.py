"""Tests for Vigil tool source-tree detection (dev_self)."""

from __future__ import annotations

import pytest


def test_allow_vigil_self_project_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from vigil.dev_self import allow_vigil_self_project

    monkeypatch.delenv("VIGIL_ALLOW_SELF_PROJECT", raising=False)
    assert allow_vigil_self_project() is False
    monkeypatch.setenv("VIGIL_ALLOW_SELF_PROJECT", "1")
    assert allow_vigil_self_project() is True


def test_vigil_development_repo_root_none_under_site_packages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import vigil
    from vigil.dev_self import vigil_development_repo_root

    monkeypatch.setattr(
        vigil,
        "__file__",
        "/usr/lib/python3.12/site-packages/vigil/__init__.py",
    )
    assert vigil_development_repo_root() is None


def test_is_vigil_source_repo_path_editable_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    import vigil
    from vigil.dev_self import is_vigil_source_repo_path

    repo = tmp_path / "Autonomous"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'vigil-agent'\n")
    pkg = repo / "vigil"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    monkeypatch.setattr(vigil, "__file__", str(pkg / "__init__.py"))
    assert is_vigil_source_repo_path(str(repo))
    assert not is_vigil_source_repo_path(str(tmp_path / "other"))
