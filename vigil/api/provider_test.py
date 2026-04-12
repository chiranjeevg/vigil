"""Shared handler for POST /api/provider/test-connection (Settings connectivity check)."""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Any

from fastapi import HTTPException

from vigil.config import ProviderConfig
from vigil.providers import create_provider

log = logging.getLogger(__name__)

PING_TIMEOUT_S = 45


def run_provider_connectivity_test(provider_dict: dict[str, Any]) -> dict[str, Any]:
    """Run a minimal LLM call using the given provider config (unsaved draft is OK).

    Raises HTTPException with 4xx/5xx and a clear ``detail`` string on failure.
    """
    try:
        p_cfg = ProviderConfig(**provider_dict)
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider configuration: {e}",
        ) from e

    ping_cfg = p_cfg.model_copy(update={"max_tokens": min(64, p_cfg.max_tokens)})

    try:
        provider = create_provider(ping_cfg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=f"Could not initialize provider: {e}",
        ) from e

    def _run():
        return provider.complete(
            "You are a connectivity check. Reply with exactly one word: ok",
            "ping",
        )

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            response = future.result(timeout=PING_TIMEOUT_S)
    except concurrent.futures.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                f"The LLM did not respond within {PING_TIMEOUT_S}s. Check base URL, model name, "
                "and that the server is reachable."
            ),
        ) from None
    except Exception as e:
        log.warning("Provider connectivity test failed: %s", e)
        raise HTTPException(
            status_code=502,
            detail=f"Connection failed: {e!s}",
        ) from e

    sample = (response.text or "").strip().replace("\n", " ")[:280]
    return {
        "ok": True,
        "provider_name": provider.name(),
        "latency_ms": int(response.duration_seconds * 1000),
        "tokens_used": response.tokens_used,
        "preview": sample,
    }
