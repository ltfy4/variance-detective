"""The generic MCP connector: argument templating, result parsing, and a live stdio round-trip."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from variance_detective.config import SourceConfig
from variance_detective.connectors import FactQuery
from variance_detective.connectors.mcp_connector import MCPConnector, records_to_frame, render_arguments
from variance_detective.semantic import SourceSemantics

HERE = Path(__file__).parent


def test_render_arguments_preserves_structure():
    tpl = {"model_id": "M1", "filters": "{filters}", "version": "{filter_first:Version}", "cols": "{dimensions}", "note": "run for {proposal_id}"}
    ctx = {"filters": {"Version": ["public.Actual"], "Date": ["202603"]}, "dimensions": ["Region"], "measures": ["NetSales"], "proposal_id": "PR-1"}
    out = render_arguments(tpl, ctx)
    assert out["filters"] == ctx["filters"] and out["version"] == "public.Actual" and out["cols"] == ["Region"] and out["note"] == "run for PR-1"
    with pytest.raises(KeyError):
        render_arguments({"x": "{nope}"}, ctx)


def test_records_to_frame_shapes():
    assert list(records_to_frame([{"a": 1}, {"a": 2}]).a) == [1, 2]
    assert list(records_to_frame({"data": [{"a": 3}]}).a) == [3]
    assert list(records_to_frame({"columns": ["a"], "rows": [[4]]}, "columns").a) == [4]
    assert list(records_to_frame("a,b\n5,6\n").b) == [6]


@pytest.mark.asyncio
async def test_stdio_round_trip(demo_facts_csv):
    cfg = SourceConfig(
        type="mcp", transport="stdio", command=sys.executable, args=[str(HERE / "fake_mcp_server.py"), str(demo_facts_csv)],
        capabilities={"write_draft": True},
        operations={
            "describe": {"tool": "get_model_metadata", "arguments": {"model_id": "M1"}},
            "read_facts": {"tool": "read_fact_data", "arguments": {"model_id": "M1", "filters": "{filters}", "measures": "{measures}", "dimensions": "{dimensions}"}, "result_path": "data"},
            "write_draft": {"tool": "upload_job_data", "arguments": {"model_id": "M1", "version": "{target_version}", "rows": "{rows}", "comment": "VD {proposal_id}"}},
        },
    )
    sem = SourceSemantics(dimensions={"time": "period", "version": "version", "region": "region", "store": "store"}, measures={"net_sales": "net_sales", "cogs": "cogs"})
    conn = MCPConnector("fake", cfg, sem)
    ok, msg = await conn.test_connection()
    assert ok, msg
    res = await conn.fetch(FactQuery(measures=["net_sales", "cogs"], dimensions=["region", "version"], filters={"time": ["2026-03"], "version": ["Actual", "Forecast"]}))
    assert set(res.frame.columns) == {"region", "version", "net_sales", "cogs"}
    assert set(res.frame.version) == {"Actual", "Forecast"} and len(res.frame) == 8
    out = await conn.write_draft({"id": "PR-1", "target_version": "Forecast", "lines": [{"path": {"region": "South", "store": "S07"}, "measure": "cogs", "proposed": 123.0}]})
    assert out["rows_received"] == 1 and out["version"] == "Forecast" and out["comment"] == "VD PR-1"
