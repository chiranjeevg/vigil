"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


def sanitize_llm_text(s: str) -> str:
    """Remove NUL (\\0) characters from prompt strings.

    JSON and HTTP bodies can carry NULs, but some OpenAI-compatible proxies forward
    the prompt to ``child_process.spawn`` on the argv; Node rejects argv strings
    that contain null bytes.
    """
    return s.replace("\x00", "")


@dataclass
class LLMResponse:
    text: str
    tokens_used: int
    duration_seconds: float


class BaseProvider(ABC):
    @abstractmethod
    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse: ...

    @abstractmethod
    def name(self) -> str: ...
