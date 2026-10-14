"""The canonical finance semantic model.

This is the heart of being tech-agnostic. The analysis engine, memory, prompts and reports
only ever see *canonical* dimension and measure names (``region``, ``net_sales`` ...).
Each source declares how its own columns and members translate into those names.

Swapping SAP Analytics Cloud for Anaplan or Oracle EPM is therefore a mapping change,
never a code change.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

# Dimensions every source must be able to provide, by canonical name.
REQUIRED_DIMENSIONS = ("time", "version")


class KPIDefinition(BaseModel):
    name: str
    label: str
    formula: str = Field(description="pandas-eval expression over canonical measures, e.g. 'net_sales - cogs'")
    unit: Literal["currency", "number", "percent"] = "currency"
    direction: Literal["higher_is_better", "lower_is_better"] = "higher_is_better"
    drill_dimensions: list[str] = Field(default_factory=list, description="Candidate dimensions for drilling, in order of preference")
    # Optional decompositions
    rate_driver: str | None = Field(None, description="Measure that drives the KPI through a rate (e.g. net_sales for gross_margin → volume vs rate split)")
    value_measure: str | None = Field(None, description="Value measure for price/volume/mix (e.g. net_sales)")
    volume_measure: str | None = Field(None, description="Volume measure for price/volume/mix (e.g. units)")
    pvm_dimension: str | None = Field(None, description="Dimension over which mix is computed (e.g. category)")

    @property
    def measures(self) -> list[str]:
        """Canonical measures needed to compute this KPI and its decompositions."""
        import re

        names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", self.formula))
        for m in (self.rate_driver, self.value_measure, self.volume_measure):
            if m:
                names.add(m)
        return sorted(names)


class SourceSemantics(BaseModel):
    """How one source's columns and members map onto the canonical model."""

    dimensions: dict[str, str] = Field(description="canonical dimension → source column")
    measures: dict[str, str] = Field(description="canonical measure → source column or pandas expression over source columns")
    members: dict[str, dict[str, str]] = Field(default_factory=dict, description="canonical dim → {canonical member: source member}")

    @model_validator(mode="after")
    def _check_required(self):
        missing = [d for d in REQUIRED_DIMENSIONS if d not in self.dimensions]
        if missing:
            raise ValueError(f"Source semantics missing required dimensions: {missing}")
        return self

    def source_column(self, canonical_dim: str) -> str:
        try:
            return self.dimensions[canonical_dim]
        except KeyError as e:
            raise KeyError(f"Dimension '{canonical_dim}' is not mapped for this source. Mapped: {sorted(self.dimensions)}") from e

    def to_source_member(self, dim: str, member: str) -> str:
        return self.members.get(dim, {}).get(member, member)

    def to_canonical_member(self, dim: str, member: str) -> str:
        inverse = {v: k for k, v in self.members.get(dim, {}).items()}
        return inverse.get(member, member)


class SemanticModel(BaseModel):
    dimensions: list[str]
    measures: list[str]
    kpis: dict[str, KPIDefinition]
    sources: dict[str, SourceSemantics]

    def kpi(self, name: str) -> KPIDefinition:
        try:
            return self.kpis[name]
        except KeyError as e:
            raise KeyError(f"Unknown KPI '{name}'. Known: {sorted(self.kpis)}") from e

    def source_semantics(self, key: str) -> SourceSemantics:
        try:
            return self.sources[key]
        except KeyError as e:
            raise KeyError(f"No semantics '{key}' in semantic model. Known: {sorted(self.sources)}") from e


def load_semantic_model(path: str | Path) -> SemanticModel:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    kpis = {k: KPIDefinition(name=k, **v) for k, v in (raw.get("kpis") or {}).items()}
    sources = {k: SourceSemantics(**v) for k, v in (raw.get("sources") or {}).items()}
    canonical = raw.get("canonical") or {}
    return SemanticModel(
        dimensions=canonical.get("dimensions", []),
        measures=canonical.get("measures", []),
        kpis=kpis,
        sources=sources,
    )
