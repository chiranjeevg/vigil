"""build_pr_status_payload includes merge_queue_head when orchestrator exposes merge_queue."""

from __future__ import annotations

from types import SimpleNamespace

from vigil.api.pr_status import build_pr_status_payload
from vigil.config import PRConfig, ProjectConfig, VigilConfig


def _minimal_config(enabled: bool = True) -> VigilConfig:
    return VigilConfig(
        project=ProjectConfig(
            path="/tmp",
            language="python",
            name="n",
            include_paths=["."],
            exclude_paths=[],
        ),
        pr=PRConfig(enabled=enabled, base_branch="main"),
    )


def test_pr_status_disabled_includes_merge_queue_head_empty() -> None:
    orch = SimpleNamespace(
        _pr_enabled=False,
        _pr_push_enabled=False,
        _pr_gh_enabled=False,
        merge_queue=None,
    )
    cfg = _minimal_config(enabled=False)
    p = build_pr_status_payload(orch, cfg)
    assert p["preflight_ok"] is False
    assert "merge_queue_head" in p
    assert p["merge_queue_head"] == ""


def test_pr_status_merge_queue_head_from_orchestrator() -> None:
    """merge_queue_head present when merge_queue.current_head returns a sha."""

    class MQ:
        def current_head(self) -> str:
            return "abc123def456"

    class PM:
        def preflight_push(self) -> tuple[bool, str]:
            return True, "ok"

        def preflight_gh_pr(self) -> tuple[bool, str]:
            return True, "ok"

    orch = SimpleNamespace(
        _pr_enabled=True,
        _pr_push_enabled=True,
        _pr_gh_enabled=True,
        merge_queue=MQ(),
        pr_manager=PM(),
    )
    cfg = _minimal_config(enabled=True)
    p = build_pr_status_payload(orch, cfg)
    assert p["merge_queue_head"] == "abc123def456"
    assert p["preflight_ok"] is True
