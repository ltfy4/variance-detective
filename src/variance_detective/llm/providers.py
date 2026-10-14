"""Concrete providers. SDKs are imported lazily so you only install what you use:

    pip install "variance-detective[anthropic]"   # Anthropic API
    pip install "variance-detective[bedrock]"     # Amazon Bedrock (boto3)
    pip install "variance-detective[azure]"       # Azure OpenAI
    pip install "variance-detective[openai]"      # OpenAI / Ollama / vLLM / Groq (OpenAI-compatible)
"""
from __future__ import annotations

import time

from ..config import LLMConfig
from .base import LLMResponse, with_retries


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, cfg: LLMConfig):
        from anthropic import Anthropic  # lazy

        self.cfg = cfg
        self.model = cfg.model
        self.client = Anthropic(timeout=cfg.timeout_seconds, max_retries=0)

    def complete(self, system: str, user: str, *, json_mode: bool = True) -> LLMResponse:
        def call():
            t0 = time.perf_counter()
            msg = self.client.messages.create(
                model=self.model,
                max_tokens=self.cfg.max_tokens,
                temperature=self.cfg.temperature,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            return LLMResponse(
                text=text,
                provider=self.name,
                model=self.model,
                input_tokens=msg.usage.input_tokens,
                output_tokens=msg.usage.output_tokens,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                raw=msg,
            )

        return with_retries(call, retries=self.cfg.max_retries)


class BedrockProvider:
    """Amazon Bedrock via the Converse API — works for Claude, Nova, Llama, Mistral on Bedrock.

    Auth is the standard AWS chain (env vars, profile, instance/task role). No keys in config.
    """

    name = "bedrock"

    def __init__(self, cfg: LLMConfig):
        import boto3  # lazy
        from botocore.config import Config as BotoConfig

        self.cfg = cfg
        self.model = cfg.model  # e.g. "anthropic.claude-sonnet-4-5-20250929-v1:0" or an inference profile ARN
        self.client = boto3.client(
            "bedrock-runtime",
            region_name=cfg.region or None,
            config=BotoConfig(read_timeout=cfg.timeout_seconds, retries={"max_attempts": 0}),
        )

    def complete(self, system: str, user: str, *, json_mode: bool = True) -> LLMResponse:
        def call():
            t0 = time.perf_counter()
            resp = self.client.converse(
                modelId=self.model,
                system=[{"text": system}],
                messages=[{"role": "user", "content": [{"text": user}]}],
                inferenceConfig={"maxTokens": self.cfg.max_tokens, "temperature": self.cfg.temperature},
            )
            text = "".join(p.get("text", "") for p in resp["output"]["message"]["content"])
            usage = resp.get("usage", {})
            return LLMResponse(
                text=text,
                provider=self.name,
                model=self.model,
                input_tokens=usage.get("inputTokens"),
                output_tokens=usage.get("outputTokens"),
                latency_ms=int((time.perf_counter() - t0) * 1000),
                raw=resp,
            )

        return with_retries(call, retries=self.cfg.max_retries)


class _OpenAIChatBase:
    """Shared body for Azure OpenAI and OpenAI-compatible endpoints."""

    name = "openai"

    def __init__(self, cfg: LLMConfig, client, model: str):
        self.cfg = cfg
        self.client = client
        self.model = model

    def complete(self, system: str, user: str, *, json_mode: bool = True) -> LLMResponse:
        def call():
            t0 = time.perf_counter()
            kwargs = {}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            resp = self.client.chat.completions.create(
                model=self.model,
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                **kwargs,
            )
            usage = getattr(resp, "usage", None)
            return LLMResponse(
                text=resp.choices[0].message.content or "",
                provider=self.name,
                model=self.model,
                input_tokens=getattr(usage, "prompt_tokens", None),
                output_tokens=getattr(usage, "completion_tokens", None),
                latency_ms=int((time.perf_counter() - t0) * 1000),
                raw=resp,
            )

        return with_retries(call, retries=self.cfg.max_retries)


class AzureOpenAIProvider(_OpenAIChatBase):
    name = "azure_openai"

    def __init__(self, cfg: LLMConfig):
        from openai import AzureOpenAI  # lazy

        if not cfg.azure_endpoint:
            raise ValueError("llm.azure_endpoint is required for provider=azure_openai")
        client = AzureOpenAI(
            azure_endpoint=cfg.azure_endpoint,
            api_version=cfg.azure_api_version,
            timeout=cfg.timeout_seconds,
            max_retries=0,
        )  # api key from AZURE_OPENAI_API_KEY, or use azure_ad_token_provider in your own wrapper
        super().__init__(cfg, client, cfg.azure_deployment or cfg.model)


class OpenAICompatibleProvider(_OpenAIChatBase):
    name = "openai"

    def __init__(self, cfg: LLMConfig):
        from openai import OpenAI  # lazy

        client = OpenAI(base_url=cfg.base_url or None, timeout=cfg.timeout_seconds, max_retries=0)
        super().__init__(cfg, client, cfg.model)


class OfflineProvider:
    """No model at all. The orchestrator detects this and uses the template narrator.

    Useful for CI, air-gapped demos, and proving that the deterministic layer stands on its own.
    """

    name = "offline"
    model = "template-narrator"

    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg

    def complete(self, system: str, user: str, *, json_mode: bool = True) -> LLMResponse:
        raise RuntimeError("OfflineProvider cannot complete; use TemplateNarrator")
