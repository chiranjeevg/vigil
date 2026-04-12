"""Fetch model lists from Ollama and OpenAI-compatible ``/v1/models`` endpoints."""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

REQUEST_TIMEOUT_S = 8.0


def _normalize_openai_base_url(url: str) -> str | None:
    """Accept only http(s) origins; strip path for ``/v1/models`` construction."""
    raw = (url or "").strip()
    if not raw:
        return None
    p = urlparse(raw if "://" in raw else f"http://{raw}")
    if p.scheme not in ("http", "https"):
        return None
    if not p.netloc:
        return None
    return f"{p.scheme}://{p.netloc}".rstrip("/")


def fetch_ollama_models(ollama_base_url: str) -> list[dict[str, Any]]:
    """GET ``/api/tags`` from Ollama."""
    models: list[dict[str, Any]] = []
    base = _normalize_openai_base_url(ollama_base_url) or ollama_base_url.rstrip("/")
    try:
        resp = requests.get(f"{base}/api/tags", timeout=REQUEST_TIMEOUT_S)
        if resp.status_code != 200:
            return []
        data = resp.json()
        for m in data.get("models", []):
            name = m.get("name", "")
            if not name:
                continue
            size = m.get("size", 0)
            size_gb = round(size / (1024**3), 1) if size else None
            models.append({
                "name": name,
                "provider": "ollama",
                "size_gb": size_gb,
                "family": m.get("details", {}).get("family", "") or "",
                "parameter_size": m.get("details", {}).get("parameter_size", "") or "",
            })
    except Exception as e:
        log.warning("Ollama model list failed: %s", e)
    return models


def fetch_openai_compatible_models(
    base_url: str,
    api_key: str | None = None,
) -> list[dict[str, Any]]:
    """GET ``{base}/v1/models`` (OpenAI-compatible)."""
    norm = _normalize_openai_base_url(base_url)
    if not norm:
        return []
    url = f"{norm}/v1/models"
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    models: list[dict[str, Any]] = []
    try:
        resp = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT_S)
        resp.raise_for_status()
        data = resp.json()
        for item in data.get("data") or []:
            mid = item.get("id")
            if not mid:
                continue
            models.append({
                "name": mid,
                "provider": "openai",
                "size_gb": None,
                "family": "",
                "parameter_size": (item.get("owned_by") or "") or "",
            })
    except Exception as e:
        log.warning("OpenAI-compatible /v1/models failed (%s): %s", url, e)
    return models


def resolve_api_key_for_config(api_key_env: str | None) -> str | None:
    if not api_key_env:
        return None
    return os.environ.get(api_key_env) or None


def collect_models_for_request(
    config: Any,
    ollama_base_url: str | None,
    openai_base_url: str | None,
) -> dict[str, Any]:
    """Build the ``/models`` JSON response.

    Query params let the Settings UI list models from **draft** base URLs before save.
    """
    models: list[dict[str, Any]] = []

    obase = (ollama_base_url or "").strip() or None
    if not obase and config is not None and config.provider.type == "ollama":
        obase = config.provider.base_url
    if obase:
        models.extend(fetch_ollama_models(obase))

    abase = (openai_base_url or "").strip() or None
    if not abase and config is not None and config.provider.type == "openai":
        abase = config.provider.base_url
    if abase:
        api_key = None
        if config is not None and config.provider.type == "openai":
            api_key = resolve_api_key_for_config(config.provider.api_key_env)
        models.extend(fetch_openai_compatible_models(abase, api_key))

    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for m in models:
        n = m.get("name")
        if not n or n in seen:
            continue
        seen.add(n)
        deduped.append(m)

    return {
        "models": deduped,
        "ollama_available": any(m.get("provider") == "ollama" for m in deduped),
        "openai_compatible_available": any(m.get("provider") == "openai" for m in deduped),
    }
