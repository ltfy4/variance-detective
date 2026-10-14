from __future__ import annotations

from ..config import AppConfig
from ..semantic import SemanticModel
from .base import DataConnector


def build_connector(name: str, cfg: AppConfig, semantic: SemanticModel) -> DataConnector:
    """Instantiate the connector for a configured source. New connector types register here."""
    from .csv_connector import CSVConnector
    from .mcp_connector import MCPConnector

    registry: dict[str, type[DataConnector]] = {"csv": CSVConnector, "mcp": MCPConnector}
    try:
        src = cfg.sources[name]
    except KeyError as e:
        raise KeyError(f"Unknown source '{name}'. Configured: {sorted(cfg.sources)}") from e
    cls = registry[src.type]
    semantics = semantic.source_semantics(src.semantics)
    connector = cls(name, src, semantics)
    # let file connectors resolve relative paths against the project base dir
    src._base_dir = str(cfg.base_dir)  # type: ignore[attr-defined]
    return connector
