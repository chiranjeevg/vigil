"""Ollama LLM provider — connects to locally running Ollama models."""

import logging
import time

import requests

from vigil.config import ProviderConfig
from vigil.providers.base import BaseProvider, LLMResponse, sanitize_llm_text

log = logging.getLogger(__name__)

MAX_RETRIES = 3
TIMEOUT_SECONDS = 600


class OllamaProvider(BaseProvider):
    def __init__(self, config: ProviderConfig):
        self._config = config
        self._url = f"{config.base_url.rstrip('/')}/api/chat"

    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        system_prompt = sanitize_llm_text(system_prompt)
        user_prompt = sanitize_llm_text(user_prompt)
        payload: dict = {
            "model": self._config.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": {
                "num_predict": self._config.max_tokens,
                "temperature": self._config.temperature,
            },
        }

        if getattr(self, '_disable_thinking', False):
            payload["think"] = False

        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                start = time.monotonic()
                resp = requests.post(self._url, json=payload, timeout=TIMEOUT_SECONDS)
                resp.raise_for_status()
                elapsed = time.monotonic() - start

                data = resp.json()
                text = data.get("message", {}).get("content", "")
                tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)

                return LLMResponse(text=text, tokens_used=tokens, duration_seconds=elapsed)

            except requests.ConnectionError as e:
                last_exc = e
                log.warning(
                    "Ollama connection failed (attempt %d/%d): %s", attempt, MAX_RETRIES, e
                )
            except requests.Timeout as e:
                last_exc = e
                log.warning(
                    "Ollama request timed out (attempt %d/%d)", attempt, MAX_RETRIES
                )
            except requests.HTTPError as e:
                last_exc = e
                log.warning(
                    "Ollama HTTP error (attempt %d/%d): %s", attempt, MAX_RETRIES, e
                )

            if attempt < MAX_RETRIES:
                backoff = 2 ** attempt
                log.info("Retrying in %ds...", backoff)
                time.sleep(backoff)

        raise ConnectionError(
            f"Failed to reach Ollama after {MAX_RETRIES} attempts: {last_exc}"
        )

    def name(self) -> str:
        return f"ollama/{self._config.model}"
