"""Provider-agnostic LLM interface.

The agent needs exactly one capability from a model: *given a system prompt and a user
message, return text (ideally JSON)*. Keeping the surface this small is what makes swapping
Anthropic ↔ Bedrock ↔ Azure ↔ Ollama a one-line config change.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    raw: Any = field(default=None, repr=False)

    def json(self) -> dict[str, Any]:
        return extract_json(self.text)


class LLMProvider(Protocol):
    name: str
    model: str

    def complete(self, system: str, user: str, *, json_mode: bool = True) -> LLMResponse: ...


def extract_json(text: str) -> dict[str, Any]:
    """Robustly pull a JSON object out of model output (handles code fences and prose)."""
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    if text.startswith("{"):
        candidates.append(text)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    last_err: Exception | None = None
    for c in candidates:
        try:
            return json.loads(c)
        except json.JSONDecodeError as e:  # pragma: no cover - depends on model output
            last_err = e
    raise ValueError(f"No JSON object found in model output: {last_err}")


def with_retries(fn, *, retries: int = 3, base_delay: float = 1.5):
    """Call ``fn`` with exponential backoff on any exception (rate limits, transient errors)."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 - provider SDK exceptions vary
            last = e
            if attempt == retries:
                break
            time.sleep(base_delay * (2**attempt))
    assert last is not None
    raise last
