"""Tests for deep analysis profile auto-detection."""

from vigil.config import ProviderConfig, resolve_deep_analysis_profile


def test_openai_localhost_proxy_uses_api_fast_not_local_caps() -> None:
    """Cursor / LiteLLM on localhost:4000 must use api_fast (not local_*)."""
    p = ProviderConfig(
        type="openai",
        model="gpt-4",
        base_url="http://localhost:4000",
        api_key_env="OPENAI_API_KEY",
    )
    prof = resolve_deep_analysis_profile(p, None)
    assert prof.max_repo_map_chars == 16_000
    assert prof.max_investigation_targets == 5
    assert prof.parallel_workers == 5
    assert prof.timeout_seconds == 60


def test_openai_cloud_url_uses_api_fast() -> None:
    p = ProviderConfig(
        type="openai",
        model="gpt-4o",
        base_url="https://api.openai.com/v1",
    )
    prof = resolve_deep_analysis_profile(p, None)
    assert prof.max_repo_map_chars == 16_000


def test_ollama_localhost_uses_local_profile_by_model_size() -> None:
    p = ProviderConfig(
        type="ollama",
        model="qwen2.5-coder:7b",
        base_url="http://localhost:11434",
    )
    prof = resolve_deep_analysis_profile(p, None)
    assert prof.max_repo_map_chars == 2_000
    assert prof.parallel_workers == 1


def test_ollama_large_model_uses_local_large() -> None:
    p = ProviderConfig(
        type="ollama",
        model="qwen3:32b",
        base_url="http://localhost:11434",
    )
    prof = resolve_deep_analysis_profile(p, None)
    assert prof.max_repo_map_chars == 4_000
    assert prof.parallel_workers == 2
