"""Translate between a source's vocabulary and the canonical model, in both directions."""
from __future__ import annotations

import pandas as pd

from .model import SourceSemantics


class SemanticMapper:
    def __init__(self, semantics: SourceSemantics):
        self.s = semantics

    # ---- canonical → source (for building queries) ------------------------------------
    def source_filters(self, filters: dict[str, list[str]]) -> dict[str, list[str]]:
        return {
            self.s.source_column(dim): [self.s.to_source_member(dim, m) for m in members]
            for dim, members in filters.items()
        }

    def source_dimensions(self, dims: list[str]) -> list[str]:
        return [self.s.source_column(d) for d in dims]

    def source_measures(self, measures: list[str]) -> list[str]:
        """Source columns needed to compute the requested canonical measures."""
        import re

        cols: list[str] = []
        for m in measures:
            expr = self.s.measures.get(m)
            if expr is None:
                raise KeyError(f"Measure '{m}' is not mapped for this source. Mapped: {sorted(self.s.measures)}")
            for tok in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr):
                if tok not in cols:
                    cols.append(tok)
        return cols

    # ---- source → canonical (for results) ---------------------------------------------
    def to_canonical(self, df: pd.DataFrame, dims: list[str], measures: list[str]) -> pd.DataFrame:
        """Rename dimension columns, translate members, evaluate measure expressions, aggregate."""
        out = pd.DataFrame(index=df.index)
        for dim in dims:
            col = self.s.source_column(dim)
            if col not in df.columns:
                raise KeyError(f"Source result lacks column '{col}' for dimension '{dim}'. Columns: {list(df.columns)}")
            series = df[col].astype(str)
            inverse = {v: k for k, v in self.s.members.get(dim, {}).items()}
            out[dim] = series.map(inverse).fillna(series) if inverse else series
        for m in measures:
            expr = self.s.measures[m]
            if expr in df.columns:
                out[m] = pd.to_numeric(df[expr], errors="coerce").fillna(0.0)
            else:
                out[m] = pd.to_numeric(df.eval(expr), errors="coerce").fillna(0.0)
        if dims:
            out = out.groupby(dims, as_index=False)[measures].sum()
        else:
            out = out[measures].sum().to_frame().T
        return out
