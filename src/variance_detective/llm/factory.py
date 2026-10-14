from __future__ import annotations

from ..config import LLMConfig
from .base import LLMProvider


def build_provider(cfg: LLMConfig) -> LLMProvider:
    from . import providers as p

    registry = {
        "anthropic": p.AnthropicProvider,
        "bedrock": p.BedrockProvider,
        "azure_openai": p.AzureOpenAIProvider,
        "openai": p.OpenAICompatibleProvider,
        "offline": p.OfflineProvider,
    }
    try:
        cls = registry[cfg.provider]
    except KeyError as e:
        raise ValueError(f"Unknown llm.provider '{cfg.provider}'. Choose one of {sorted(registry)}") from e
    try:
        return cls(cfg)
    except ImportError as e:
        extra = {"anthropic": "anthropic", "bedrock": "bedrock", "azure_openai": "azure", "openai": "openai"}.get(cfg.provider, "all")
        raise ImportError(
            f"Provider '{cfg.provider}' needs an optional dependency. Install with: pip install 'variance-detective[{extra}]'"
        ) from e
