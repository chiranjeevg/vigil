"""Shared payload for GET /api/pr/status (file-backed and DB API routes)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def build_pr_status_payload(orch: Any, config: Any) -> dict:
    """Mirror orchestrator PR flags and live git/gh preflight."""
    mq_head = ""
    try:
        if hasattr(orch, "merge_queue") and orch.merge_queue:
            mq_head = orch.merge_queue.current_head()
    except Exception:
        pass
    status = {
        "enabled": config.pr.enabled,
        "pr_active": getattr(orch, "_pr_enabled", False),
        "push_enabled": getattr(orch, "_pr_push_enabled", False),
        "gh_pr_enabled": getattr(orch, "_pr_gh_enabled", False),
        "strategy": config.pr.strategy,
        "base_branch": config.pr.base_branch,
        "merge_queue_head": mq_head,
    }

    if not config.pr.enabled:
        status["preflight_ok"] = False
        status["preflight_message"] = "PR workflow disabled in vigil.yaml"
        status["push_enabled"] = False
        status["gh_pr_enabled"] = False
    elif hasattr(orch, "pr_manager") and orch.pr_manager:
        push_ok, push_msg = orch.pr_manager.preflight_push()
        gh_ok, gh_msg = orch.pr_manager.preflight_gh_pr()
        status["push_enabled"] = push_ok
        status["gh_pr_enabled"] = gh_ok
        status["preflight_ok"] = push_ok and gh_ok
        parts = [m for ok, m in ((push_ok, push_msg), (gh_ok, gh_msg)) if not ok]
        status["preflight_message"] = " ".join(parts) if parts else "PR workflow ready"
    else:
        status["preflight_ok"] = False
        status["preflight_message"] = "PR manager not initialized"
        status["push_enabled"] = False
        status["gh_pr_enabled"] = False

    return status
