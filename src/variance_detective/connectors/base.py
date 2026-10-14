"""Connector contract.

A connector answers one question — *give me these measures by these dimensions with these
filters* — in its own vocabulary. The base class handles translation to and from the
canonical model, so a concrete connector only implements ``_read_source``.

Everything is expressed in canonical names at the boundary (``FactQuery``), which is what
lets the orchestrator stay ignorant of SAC vs Anaplan vs a CSV on disk.
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from ..config import SourceConfig
from ..semantic import SemanticMapper, SourceSemantics


class FactQuery(BaseModel):
    """A canonical fact query. Filters and dimensions use canonical names."""

    measures: list[str]
    dimensions: list[str] = Field(default_factory=list)
    filters: dict[str, list[str]] = Field(default_factory=dict)

    def describe(self) -> str:
        f = ", ".join(f"{k} in {v}" for k, v in self.filters.items()) or "no filters"
        return f"SELECT {', '.join(self.measures)} BY {', '.join(self.dimensions) or '(total)'} WHERE {f}"


@dataclass
class SourceQuery:
    """The same query translated into the source's own column/member names."""

    measure_columns: list[str]
    dimension_columns: list[str]
    filters: dict[str, list[str]]


@dataclass
class SourceDescription:
    name: str
    type: str
    dimensions: list[str] = field(default_factory=list)
    measures: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class FetchResult:
    frame: pd.DataFrame
    query: FactQuery
    source_query: SourceQuery
    rows: int
    elapsed_ms: int
    source: str


class DataConnector(ABC):
    type: str = "abstract"

    def __init__(self, name: str, cfg: SourceConfig, semantics: SourceSemantics):
        self.name = name
        self.cfg = cfg
        self.semantics = semantics
        self.mapper = SemanticMapper(semantics)

    # ---- public API --------------------------------------------------------------------
    async def fetch(self, query: FactQuery) -> FetchResult:
        t0 = time.perf_counter()
        sq = SourceQuery(
            measure_columns=self.mapper.source_measures(query.measures),
            dimension_columns=self.mapper.source_dimensions(query.dimensions),
            filters=self.mapper.source_filters(query.filters),
        )
        raw = await self._read_source(sq)
        frame = self.mapper.to_canonical(raw, query.dimensions, query.measures)
        return FetchResult(
            frame=frame,
            query=query,
            source_query=sq,
            rows=len(raw),
            elapsed_ms=int((time.perf_counter() - t0) * 1000),
            source=self.name,
        )

    async def describe(self) -> SourceDescription:
        return SourceDescription(name=self.name, type=self.type, dimensions=sorted(self.semantics.dimensions), measures=sorted(self.semantics.measures))

    async def test_connection(self) -> tuple[bool, str]:
        try:
            d = await self.describe()
            return True, f"{d.type}: {len(d.dimensions)} dimensions, {len(d.measures)} measures"
        except Exception as e:  # noqa: BLE001
            return False, f"{type(e).__name__}: {e}"

    @property
    def can_write_draft(self) -> bool:
        return bool(self.cfg.capabilities.get("write_draft", False))

    async def write_draft(self, proposal: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"Source '{self.name}' does not support write-back")

    # ---- to implement ------------------------------------------------------------------
    @abstractmethod
    async def _read_source(self, query: SourceQuery) -> pd.DataFrame:
        """Return rows in *source* vocabulary containing at least the requested columns."""


def apply_filters(df: pd.DataFrame, filters: dict[str, list[str]]) -> pd.DataFrame:
    for col, members in filters.items():
        if col not in df.columns:
            raise KeyError(f"Filter column '{col}' not found. Columns: {list(df.columns)}")
        df = df[df[col].astype(str).isin([str(m) for m in members])]
    return df
