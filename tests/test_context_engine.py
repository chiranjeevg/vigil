"""Tests for the ContextEngine.

We test the public ``build()`` interface and the smart-sampling helpers using
a real (temporary) project directory on disk.  Phase-1 deep analysis is mocked
so tests run quickly without needing a full git repo.
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from vigil.config import VigilConfig
from vigil.core.context_engine import ContextEngine, _extract_keywords


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(include_paths: list[str], project_path: str) -> VigilConfig:
    return VigilConfig(
        project={
            "path": project_path,
            "name": "test",
            "include_paths": include_paths,
            "exclude_paths": [],
        }
    )


def _write_file(base: Path, rel: str, content: str) -> None:
    f = base / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content)


# ---------------------------------------------------------------------------
# _extract_keywords
# ---------------------------------------------------------------------------

class TestExtractKeywords:
    def test_removes_stop_words(self):
        kws = _extract_keywords("implement the auth service")
        assert "the" not in kws
        assert "auth" in kws
        assert "service" in kws

    def test_deduplicates(self):
        kws = _extract_keywords("auth auth auth service")
        assert kws.count("auth") == 1

    def test_short_words_excluded(self):
        kws = _extract_keywords("fix it up now")
        assert "it" not in kws
        assert "up" not in kws

    def test_empty_returns_empty(self):
        assert _extract_keywords("") == []


# ---------------------------------------------------------------------------
# ContextEngine.build()
# ---------------------------------------------------------------------------

class TestContextEngine:
    def _setup(self, files: dict[str, str]) -> tuple[ContextEngine, str]:
        """Create a temp project with given files, return (engine, project_path)."""
        tmp = tempfile.mkdtemp()
        for rel, content in files.items():
            _write_file(Path(tmp), rel, content)
        config = _make_config(["src/"], tmp)
        engine = ContextEngine(config)
        return engine, tmp

    def test_file_tree_included_in_context(self):
        engine, _ = self._setup({"src/main.py": "print('hello')"})
        ctx = engine.build({}, "", [], [])
        assert "src/main.py" in ctx["file_tree"]

    def test_progress_and_benchmarks_forwarded(self):
        engine, _ = self._setup({})
        ctx = engine.build({}, "some progress", [{"data": 1}], [])
        assert ctx["progress_summary"] == "some progress"
        assert ctx["recent_benchmarks"] == [{"data": 1}]

    def test_explicit_context_files_loaded(self):
        engine, tmp = self._setup({"src/auth.py": "# auth code"})
        task = {"context_files": ["src/auth.py"]}
        ctx = engine.build(task, "", [], [])
        assert "src/auth.py" in ctx["file_contents"]
        assert "# auth code" in ctx["file_contents"]["src/auth.py"]

    def test_missing_context_file_silently_skipped(self):
        engine, _ = self._setup({"src/real.py": "pass"})
        task = {"context_files": ["src/does_not_exist.py"]}
        ctx = engine.build(task, "", [], [])
        assert ctx["file_contents"] == {}

    def test_reference_docs_loaded(self):
        engine, tmp = self._setup({})
        doc = Path(tmp) / "docs" / "prd.md"
        doc.parent.mkdir(parents=True, exist_ok=True)
        doc.write_text("# PRD\n- [ ] Build auth")
        task = {"context_docs": ["docs/prd.md"]}
        ctx = engine.build(task, "", [], [])
        assert "docs/prd.md" in ctx["reference_docs"]
        assert "Build auth" in ctx["reference_docs"]["docs/prd.md"]

    def test_global_context_documents_always_included(self):
        tmp = tempfile.mkdtemp()
        doc = Path(tmp) / "arch.md"
        doc.write_text("# Architecture")
        config = VigilConfig(
            project={"path": tmp, "name": "test", "include_paths": []},
            work_sources={"context_documents": ["arch.md"]},
        )
        engine = ContextEngine(config)
        ctx = engine.build({}, "", [], [])
        assert "arch.md" in ctx["reference_docs"]

    def test_target_files_also_loaded(self):
        """Backward-compat: target_files should still load file contents."""
        engine, tmp = self._setup({"src/service.py": "# service"})
        task = {"target_files": ["src/service.py"]}
        ctx = engine.build(task, "", [], [])
        assert "src/service.py" in ctx["file_contents"]

    def test_cache_invalidate_resets(self):
        engine, _ = self._setup({})
        engine._phase1_cache = {"source_file_count": 999}
        engine.invalidate_cache()
        assert engine._phase1_cache is None

    def test_smart_sample_fallback_used_when_no_phase1(self):
        """When phase-1 fails, engine falls back to alphabetical scan."""
        engine, _ = self._setup({"src/alpha.py": "pass", "src/beta.py": "pass"})
        with patch.object(engine, "_get_phase1", return_value=None):
            ctx = engine.build({"work_type": "improvement"}, "", [], [])
        # Both files should appear (alphabetical fallback)
        assert "src/alpha.py" in ctx["file_contents"]
        assert "src/beta.py" in ctx["file_contents"]

    def test_file_content_capped_at_limit(self):
        """Large files should be truncated to _FILE_CHAR_LIMIT."""
        from vigil.core.context_engine import _FILE_CHAR_LIMIT
        big_content = "x" * (_FILE_CHAR_LIMIT + 5000)
        engine, _ = self._setup({"src/big.py": big_content})
        task = {"context_files": ["src/big.py"]}
        ctx = engine.build(task, "", [], [])
        assert len(ctx["file_contents"]["src/big.py"]) <= _FILE_CHAR_LIMIT
