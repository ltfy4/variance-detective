"""Generic MCP connector.

Any MCP server that exposes a "read facts" style tool can be plugged in with *configuration
only*. The ``operations`` block in ``config/sources.yaml`` maps the connector's abstract
operations onto the server's actual tool names and argument shapes:

    operations:
      read_facts:
        tool: read_fact_data             # the server's tool name
        arguments:                       # templated; placeholders are substituted per query
          model_id: "Cv3a9...."          # constant
          filters: "{filters}"           # → {source_col: [members]}
          measures: "{measures}"         # → [source measure columns]
          dimensions: "{dimensions}"     # → [source dimension columns]
          version: "{filter_first:Version}"   # → first member of the 'Version' source filter
        result_path: "data"              # dotted path to the records inside the tool result
        record_format: records           # records = list[dict] | columns = {columns: [...], rows: [[...]]}
      describe:
        tool: get_model_metadata
        arguments: {model_id: "Cv3a9...."}
      write_draft:
        tool: upload_job_data
        arguments: {model_id: "Cv3a9....", version: "{target_version}", rows: "{rows}"}

Placeholders available in ``read_facts`` arguments:
    {filters} {measures} {dimensions} {filter:<col>} {filter_first:<col>}
Placeholders available in ``write_draft`` arguments:
    {rows} {target_version} {proposal_id}

Transports: ``stdio`` (command + args), ``streamable_http`` (url + headers), ``sse`` (url + headers).
Works with both the 1.x and 2.x Python MCP SDKs.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pandas as pd

from .base import DataConnector, SourceDescription, SourceQuery, apply_filters

_PLACEHOLDER = re.compile(r"^\{([a-z_]+)(?::([^}]+))?\}$")


def render_arguments(template: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Substitute placeholders. A value that is exactly ``{name}`` is replaced by the object
    (list/dict/str) so JSON structure is preserved; embedded ``{name}`` inside longer strings
    is replaced textually."""

    def render(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: render(x) for k, x in v.items()}
        if isinstance(v, list):
            return [render(x) for x in v]
        if isinstance(v, str):
            m = _PLACEHOLDER.match(v)
            if m:
                name, arg = m.group(1), m.group(2)
                if name == "filter":
                    return context["filters"].get(arg, [])
                if name == "filter_first":
                    vals = context["filters"].get(arg, [])
                    return vals[0] if vals else None
                if name in context:
                    return context[name]
                raise KeyError(f"Unknown placeholder '{v}'")
            if "{" in v:
                out = v
                for k, val in context.items():
                    if isinstance(val, (str, int, float)):
                        out = out.replace("{" + k + "}", str(val))
                return out
        return v

    return render(template)


def _dig(obj: Any, path: str | None) -> Any:
    if not path:
        return obj
    for part in path.split("."):
        if isinstance(obj, list) and part.isdigit():
            obj = obj[int(part)]
        elif isinstance(obj, dict):
            obj = obj[part]
        else:
            raise KeyError(f"Cannot resolve '{part}' in tool result at path '{path}'")
    return obj


def parse_tool_result(result: Any) -> Any:
    """Turn a CallToolResult (1.x or 2.x SDK) into Python data."""
    if getattr(result, "is_error", False) or getattr(result, "isError", False):
        text = " ".join(getattr(c, "text", "") for c in getattr(result, "content", []) or [])
        raise RuntimeError(f"MCP tool returned an error: {text[:500]}")
    structured = getattr(result, "structured_content", None) or getattr(result, "structuredContent", None)
    if structured:
        # Servers often wrap a bare list as {"result": [...]}
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured
    texts = [getattr(c, "text", None) for c in getattr(result, "content", []) or []]
    texts = [t for t in texts if t]
    if not texts:
        return None
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return joined


def records_to_frame(data: Any, record_format: str = "records") -> pd.DataFrame:
    if record_format == "columns":
        return pd.DataFrame(data["rows"], columns=data["columns"])
    if isinstance(data, dict):
        for key in ("data", "rows", "records", "items", "result", "values"):
            if key in data and isinstance(data[key], list):
                return pd.DataFrame(data[key])
        raise ValueError(f"Cannot find a record list in tool result keys {list(data)}; set result_path")
    if isinstance(data, list):
        return pd.DataFrame(data)
    if isinstance(data, str):
        from io import StringIO

        return pd.read_csv(StringIO(data))
    raise ValueError(f"Unsupported tool result type {type(data).__name__}")


class MCPConnector(DataConnector):
    type = "mcp"

    # ---- session management ------------------------------------------------------------
    @asynccontextmanager
    async def session(self) -> AsyncIterator[Any]:
        from mcp import ClientSession

        transport = self.cfg.transport or ("stdio" if self.cfg.command else "streamable_http")
        if transport == "stdio":
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            if not self.cfg.command:
                raise ValueError(f"Source '{self.name}': stdio transport needs 'command'")
            params = StdioServerParameters(command=self.cfg.command, args=self.cfg.args, env={**os.environ, **self.cfg.env})
            async with stdio_client(params) as (read, write), ClientSession(read, write) as s:
                await s.initialize()
                yield s
        elif transport == "streamable_http":
            if not self.cfg.url:
                raise ValueError(f"Source '{self.name}': streamable_http transport needs 'url'")
            try:  # SDK 2.x
                import httpx
                from mcp.client.streamable_http import streamable_http_client as shttp

                async with httpx.AsyncClient(headers=self.cfg.headers, timeout=120) as http:
                    async with shttp(self.cfg.url, http_client=http) as streams:
                        async with ClientSession(streams[0], streams[1]) as s:
                            await s.initialize()
                            yield s
            except ImportError:  # SDK 1.x
                from mcp.client.streamable_http import streamablehttp_client as shttp1

                async with shttp1(self.cfg.url, headers=self.cfg.headers) as (read, write, _):
                    async with ClientSession(read, write) as s:
                        await s.initialize()
                        yield s
        elif transport == "sse":
            from mcp.client.sse import sse_client

            async with sse_client(self.cfg.url, headers=self.cfg.headers) as (read, write):
                async with ClientSession(read, write) as s:
                    await s.initialize()
                    yield s
        else:
            raise ValueError(f"Unknown transport '{transport}'")

    async def call(self, op: str, context: dict[str, Any]) -> Any:
        spec = self.cfg.operations.get(op)
        if not spec:
            raise NotImplementedError(f"Source '{self.name}' has no '{op}' operation configured")
        args = render_arguments(spec.get("arguments", {}), context)
        async with self.session() as s:
            result = await s.call_tool(spec["tool"], args)
        data = parse_tool_result(result)
        return _dig(data, spec.get("result_path"))

    # ---- contract ------------------------------------------------------------------------
    async def _read_source(self, query: SourceQuery) -> pd.DataFrame:
        spec = self.cfg.operations.get("read_facts", {})
        data = await self.call(
            "read_facts",
            {"filters": query.filters, "measures": query.measure_columns, "dimensions": query.dimension_columns},
        )
        df = records_to_frame(data, spec.get("record_format", "records"))
        # Servers may ignore filters/dimensions; enforce locally so results are always correct.
        present = {c: m for c, m in query.filters.items() if c in df.columns}
        df = apply_filters(df, present)
        missing = [c for c in query.dimension_columns + query.measure_columns if c not in df.columns]
        if missing:
            raise KeyError(f"MCP source '{self.name}' returned no column(s) {missing}. Columns: {list(df.columns)}")
        return df[query.dimension_columns + query.measure_columns].copy()

    async def describe(self) -> SourceDescription:
        base = await super().describe()
        if "describe" in self.cfg.operations:
            base.extra["server_metadata"] = await self.call("describe", {})
        else:
            async with self.session() as s:
                tools = await s.list_tools()
                base.extra["tools"] = [t.name for t in tools.tools]
        return base

    async def write_draft(self, proposal: dict[str, Any]) -> dict[str, Any]:
        if not self.can_write_draft or "write_draft" not in self.cfg.operations:
            raise NotImplementedError(f"Source '{self.name}' is not configured for write-back")
        rows = [
            {**{self.semantics.source_column(d): self.semantics.to_source_member(d, m) for d, m in line["path"].items()},
             self.semantics.measures.get(line["measure"], line["measure"]): line["proposed"]}
            for line in proposal["lines"]
        ]
        return await self.call(
            "write_draft",
            {"rows": rows, "target_version": proposal["target_version"], "proposal_id": proposal["id"]},
        )
