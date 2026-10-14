"""Local file connector: CSV or Parquet, a single file or a directory of files.

Used for demos, tests, and the very common real-world case of "FP&A exported it to a file".
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .base import DataConnector, SourceQuery, apply_filters


class CSVConnector(DataConnector):
    type = "csv"

    def _load(self) -> pd.DataFrame:
        if not self.cfg.path:
            raise ValueError(f"Source '{self.name}': csv connector needs 'path'")
        path = Path(self.cfg.path)
        if not path.is_absolute():
            path = Path(getattr(self.cfg, "_base_dir", ".")) / path
        files = sorted(path.glob("*.csv")) + sorted(path.glob("*.parquet")) if path.is_dir() else [path]
        if not files:
            raise FileNotFoundError(f"No data files found at {path}")
        frames = [pd.read_parquet(f) if f.suffix == ".parquet" else pd.read_csv(f) for f in files]
        return pd.concat(frames, ignore_index=True)

    async def _read_source(self, query: SourceQuery) -> pd.DataFrame:
        df = self._load()
        df = apply_filters(df, query.filters)
        cols = [c for c in query.dimension_columns + query.measure_columns if c in df.columns]
        missing = set(query.dimension_columns + query.measure_columns) - set(cols)
        if missing:
            raise KeyError(f"Source '{self.name}' lacks columns {sorted(missing)}. Available: {list(df.columns)}")
        return df[cols].copy()
