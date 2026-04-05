"""OpenAI-compatible provider for cloud and self-hosted LLM endpoints."""

import logging
import os
import time

import requests

from vigil.config import ProviderConfig
from vigil.providers.base import BaseProvider, LLMResponse

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 300


class OpenAICompatProvider(BaseProvider):
    def __init__(self, config: ProviderConfig):
        self._config = config
        self._url = f"{config.base_url.rstrip('/')}/v1/chat/completions"
        self._api_key: str | None = None

        if config.api_key_env:
            self._api_key = os.environ.get(config.api_key_env)
            if not self._api_key:
                log.warning(
                    "Environment variable %s not set — requests may fail",
                    config.api_key_env,
                )

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": self._config.max_tokens,
            "temperature": self._config.temperature,
        }

        start = time.monotonic()
        resp = requests.post(
            self._url, json=payload, headers=headers, timeout=TIMEOUT_SECONDS
        )
        resp.raise_for_status()
        elapsed = time.monotonic() - start

        data = resp.json()
        choice = data["choices"][0]
        text = choice["message"]["content"]
        usage = data.get("usage", {})
        tokens = usage.get("total_tokens", 0)

        return LLMResponse(text=text, tokens_used=tokens, duration_seconds=elapsed)

    def name(self) -> str:
        return f"openai-compat/{self._config.model}"
