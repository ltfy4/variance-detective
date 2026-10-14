"""A tiny MCP server that serves a CSV through a `read_fact_data` tool — used to prove the
generic MCP connector end-to-end over stdio. Works with both MCP SDK 1.x (FastMCP) and 2.x (MCPServer).

Usage: python tests/fake_mcp_server.py <path-to-csv>
"""
from __future__ import annotations

import sys
from typing import Any

import pandas as pd

try:  # SDK 2.x
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore

CSV = sys.argv[1]
server = _Server("fake-planning-system")


@server.tool()
def get_model_metadata(model_id: str) -> dict[str, Any]:
    """Describe the (fake) planning model."""
    df = pd.read_csv(CSV, nrows=1)
    return {"model_id": model_id, "columns": list(df.columns)}


@server.tool()
def read_fact_data(model_id: str, filters: dict[str, list[str]] | None = None, measures: list[str] | None = None, dimensions: list[str] | None = None, limit: int = 100000) -> dict[str, Any]:
    """Return fact rows as {"data": [...]} like a real planning MCP server would."""
    df = pd.read_csv(CSV)
    for col, members in (filters or {}).items():
        df = df[df[col].astype(str).isin([str(m) for m in members])]
    cols = [c for c in (dimensions or []) + (measures or []) if c in df.columns] or list(df.columns)
    return {"model_id": model_id, "data": df[cols].head(limit).to_dict("records")}


@server.tool()
def upload_job_data(model_id: str, version: str, rows: list[dict[str, Any]], comment: str = "") -> dict[str, Any]:
    """Pretend to write rows to a draft version."""
    return {"job_id": "job-123", "model_id": model_id, "version": version, "rows_received": len(rows), "comment": comment}


if __name__ == "__main__":
    server.run(transport="stdio")
