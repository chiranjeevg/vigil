"""Abstract base class for LLM providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


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
