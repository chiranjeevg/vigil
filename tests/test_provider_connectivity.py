"""Tests for POST /api/provider/test-connection handler."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from vigil.api.provider_test import run_provider_connectivity_test


def test_rejects_unknown_provider_type() -> None:
    with pytest.raises(HTTPException) as ei:
        run_provider_connectivity_test(
            {
                "type": "unknown-provider-xyz",
                "model": "m",
                "base_url": "http://127.0.0.1:9",
                "max_tokens": 64,
                "temperature": 0.2,
            }
        )
    assert ei.value.status_code == 400
    assert "Unknown provider type" in (ei.value.detail or "")
