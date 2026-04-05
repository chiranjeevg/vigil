from vigil.config import ProviderConfig
from vigil.providers.base import BaseProvider


def create_provider(config: ProviderConfig) -> BaseProvider:
    if config.type == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider(config)
    elif config.type == "openai":
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(config)
    raise ValueError(f"Unknown provider type: {config.type}")
