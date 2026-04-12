"""Integration tests for DB-backed project config loading and empty project.path bootstrap."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from vigil.config import VigilConfig


@pytest.fixture
def isolated_sqlite_db(monkeypatch: pytest.MonkeyPatch):
    """Fresh SQLite DB and reset global manager so tests do not share state."""
    import vigil.db.session as db_session

    db_session._db_manager = None
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setenv("VIGIL_DATABASE_URL", f"sqlite+aiosqlite:///{path}")
    yield path
    db_session._db_manager = None
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.mark.asyncio
async def test_load_vigil_config_aligns_empty_path_from_config_json(
    isolated_sqlite_db: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """DB-stored JSON must not leave project.path empty after load (UI selection)."""
    monkeypatch.setenv("VIGIL_USE_DATABASE", "true")
    from vigil.db.repository import ProjectRepository
    from vigil.db.session import get_db_manager, init_db
    from vigil.project_config_loader import load_vigil_config_for_project_path

    proj = tmp_path / "client_app"
    proj.mkdir()

    template = VigilConfig(project={})
    broken = template.model_copy(
        update={
            "project": template.project.model_copy(
                update={"path": "", "name": "StaleName"},
            ),
        },
    )
    await init_db()
    mgr = get_db_manager()
    assert mgr is not None
    async with mgr.session() as db:
        repo = ProjectRepository(db)
        await repo.create(
            str(proj),
            "RegistryName",
            "python",
            config_json=json.dumps(broken.model_dump(mode="json")),
        )

    async with mgr.session() as db:
        cfg = await load_vigil_config_for_project_path(str(proj), db)

    assert cfg.project.path == os.path.normpath(os.path.realpath(str(proj)))
    assert cfg.project.name == "RegistryName"
    assert cfg.project.language == "python"


@pytest.mark.asyncio
async def test_load_vigil_config_aligns_wrong_path_in_yaml(
    isolated_sqlite_db: str,
    tmp_path: Path,
) -> None:
    """On-disk vigil.yaml may list a stale path; registry directory wins."""
    from vigil.db.repository import ProjectRepository
    from vigil.db.session import get_db_manager, init_db
    from vigil.project_config_loader import load_vigil_config_for_project_path

    proj = tmp_path / "repo_a"
    proj.mkdir()
    (proj / "vigil.yaml").write_text(
        "\n".join(
            [
                "project:",
                "  path: /totally/wrong/path",
                "  name: Wrong",
                "provider:",
                "  type: ollama",
                "  model: qwen2.5-coder:14b",
                "  base_url: http://localhost:11434",
                "  max_tokens: 8192",
                "  temperature: 0.2",
            ]
        ),
        encoding="utf-8",
    )

    await init_db()
    mgr = get_db_manager()
    assert mgr is not None
    async with mgr.session() as db:
        repo = ProjectRepository(db)
        await repo.create(str(proj), "RepoA", "python")

    async with mgr.session() as db:
        cfg = await load_vigil_config_for_project_path(str(proj), db)

    assert cfg.project.path == os.path.normpath(os.path.realpath(str(proj)))
    assert cfg.project.name == "RepoA"


@pytest.mark.asyncio
async def test_resolve_daemon_config_empty_path_uses_registry(
    isolated_sqlite_db: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """End-to-end: minimal daemon YAML with no path + DB row -> resolved path."""
    monkeypatch.setenv("VIGIL_USE_DATABASE", "true")
    from vigil.daemon_bootstrap import resolve_daemon_config_if_empty_project_path
    from vigil.db.repository import ProjectRepository
    from vigil.db.session import get_db_manager, init_db

    work = tmp_path / "worktree"
    work.mkdir()
    (work / "vigil.yaml").write_text(
        "\n".join(
            [
                "project:",
                "  path: /old/wrong",
                "  name: Ignored",
                "provider:",
                "  type: ollama",
                "  model: qwen2.5-coder:14b",
                "  base_url: http://localhost:11434",
                "  max_tokens: 8192",
                "  temperature: 0.2",
            ]
        ),
        encoding="utf-8",
    )

    await init_db()
    mgr = get_db_manager()
    assert mgr is not None
    async with mgr.session() as db:
        repo = ProjectRepository(db)
        await repo.create(str(work), "Work", "python")

    daemon = VigilConfig.model_validate(
        {
            "project": {"path": ""},
            "provider": {
                "type": "openai",
                "model": "gpt-4",
                "base_url": "http://proxy.example:4000",
                "max_tokens": 100,
                "temperature": 0.1,
            },
        }
    )

    out = await resolve_daemon_config_if_empty_project_path(daemon)
    assert out.project.path == os.path.normpath(os.path.realpath(str(work)))
    assert out.project.name == "Work"
    # Overlay: daemon file provider should win over loaded project file
    assert out.provider.type == "openai"
    assert out.provider.base_url == "http://proxy.example:4000"
