"""Configuration: layered YAML + environment variables.

Precedence (highest first):
  1. environment variables, prefixed ``VD_`` and nested with ``__``
     (e.g. ``VD_LLM__PROVIDER=bedrock``, ``VD_LLM__MODEL=...``)
  2. the YAML file passed on the command line (``--config``) or ``VD_CONFIG``
  3. built-in defaults below

Secrets never live in YAML. They are read from the environment by the provider SDKs:
``ANTHROPIC_API_KEY``; ``AWS_*`` / instance role for Bedrock; ``AZURE_OPENAI_API_KEY``;
``OPENAI_API_KEY``. See ``.env.example``.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, ClassVar, Literal

import yaml
from pydantic import BaseModel, Field, PrivateAttr, field_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

LLMProviderName = Literal["anthropic", "bedrock", "azure_openai", "openai", "offline"]


class LLMConfig(BaseModel):
    provider: LLMProviderName = "offline"
    model: str = "claude-sonnet-4-5"
    temperature: float = 0.1
    max_tokens: int = 4000
    timeout_seconds: int = 120
    max_retries: int = 3
    # Bedrock
    region: str | None = None
    # Azure OpenAI
    azure_endpoint: str | None = None
    azure_api_version: str = "2024-10-21"
    azure_deployment: str | None = None
    # OpenAI-compatible (OpenAI, Ollama, vLLM, Groq, ...)
    base_url: str | None = None


class AnalysisConfig(BaseModel):
    coverage_target: float = Field(0.80, ge=0.5, le=1.0, description="Share of a node's variance the selected children must explain")
    max_depth: int = Field(4, ge=1, le=8)
    max_children_per_node: int = Field(5, ge=1, le=20)
    materiality_abs: float = Field(0.0, description="Absolute materiality in KPI units; 0 disables")
    materiality_pct: float = Field(0.0, description="Materiality as % of comparison value; 0 disables")
    min_child_share: float = Field(0.05, description="Do not drill into a child explaining less than this share of parent variance")
    offset_threshold: float = Field(0.10, description="Report offsetting members larger than this share of |node variance|")


class MemoryConfig(BaseModel):
    enabled: bool = True
    path: str = "workspace/memory.sqlite"


class WritebackConfig(BaseModel):
    mode: Literal["disabled", "draft", "auto"] = "draft"
    proposals_dir: str = "workspace/proposals"
    target_version: str = "Forecast"


class ReportingConfig(BaseModel):
    output_dir: str = "workspace/reports"
    formats: list[Literal["html", "markdown", "json"]] = ["html", "markdown", "json"]
    currency_symbol: str = "£"
    evidence_rows_limit: int = 25


class SourceConfig(BaseModel):
    """A data source. ``type`` selects the connector; the rest is connector-specific."""

    type: Literal["csv", "mcp"]
    label: str | None = None
    semantics: str = Field("default", description="Key into semantic_model.sources")
    # csv
    path: str | None = None
    # mcp
    transport: Literal["stdio", "streamable_http", "sse"] | None = None
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None
    headers: dict[str, str] = {}
    operations: dict[str, dict[str, Any]] = {}
    capabilities: dict[str, bool] = {}
    # set by the registry so file connectors can resolve relative paths
    _base_dir: str = PrivateAttr(default=".")


class _YamlSource(PydanticBaseSettingsSource):
    """YAML values sit *below* environment variables in precedence."""

    def __init__(self, settings_cls, data: dict[str, Any]):
        super().__init__(settings_cls)
        self.data = data

    def get_field_value(self, field, field_name: str):
        return self.data.get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(self.data)


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VD_", env_nested_delimiter="__", extra="ignore")
    _yaml_data: ClassVar[dict[str, Any]] = {}

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        return (init_settings, env_settings, dotenv_settings, _YamlSource(settings_cls, cls._yaml_data), file_secret_settings)

    workspace: str = "workspace"
    semantic_model: str = "config/semantic_model.yaml"
    sources_file: str = "config/sources.yaml"
    llm: LLMConfig = LLMConfig()
    analysis: AnalysisConfig = AnalysisConfig()
    memory: MemoryConfig = MemoryConfig()
    writeback: WritebackConfig = WritebackConfig()
    reporting: ReportingConfig = ReportingConfig()
    sources: dict[str, SourceConfig] = {}
    base_dir: Path = Path(".")

    @field_validator("base_dir", mode="before")
    @classmethod
    def _coerce_path(cls, v: Any) -> Path:
        return Path(v)

    def resolve(self, p: str | Path) -> Path:
        p = Path(p)
        return p if p.is_absolute() else (self.base_dir / p)


def _expand_env(obj: Any) -> Any:
    """Expand ``${VAR}`` / ``${VAR:-default}`` inside YAML strings."""
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_env(v) for v in obj]
    if isinstance(obj, str) and "${" in obj:
        import re

        def repl(m: re.Match[str]) -> str:
            name, _, default = m.group(1).partition(":-")
            return os.environ.get(name, default)

        return re.sub(r"\$\{([^}]+)\}", repl, obj)
    return obj


def load_config(config_path: str | Path | None = None) -> AppConfig:
    """Load config from YAML (optional) then overlay environment variables."""
    path = Path(config_path or os.environ.get("VD_CONFIG", "config/agent.yaml"))
    data: dict[str, Any] = {}
    base_dir = Path(".")
    if path.exists():
        data = _expand_env(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        base_dir = path.resolve().parent.parent if path.parent.name == "config" else path.resolve().parent
    AppConfig._yaml_data = data
    try:
        cfg = AppConfig()
    finally:
        AppConfig._yaml_data = {}
    cfg.base_dir = base_dir
    # sources may live in a separate file (keeps agent.yaml small)
    sources_path = cfg.resolve(cfg.sources_file)
    if sources_path.exists() and not cfg.sources:
        raw = _expand_env(yaml.safe_load(sources_path.read_text(encoding="utf-8")) or {})
        cfg.sources = {k: SourceConfig(**v) for k, v in (raw.get("sources") or {}).items()}
    return cfg
