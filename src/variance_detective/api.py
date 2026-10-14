"""Optional HTTP service: ``pip install fastapi uvicorn`` then ``uvicorn variance_detective.api:app``.

Exposes the same investigation as the CLI so schedulers, chat bots and other agents can call it.
Reports are still written to the workspace; the JSON report is returned inline.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

from .agent import InvestigationRequest, Investigator
from .config import load_config
from .writeback import ProposalStore

app = FastAPI(title="Variance Detective", version=__import__("variance_detective").__version__)
_cfg = load_config()
_inv = Investigator(_cfg)
_store = ProposalStore(_cfg.resolve(_cfg.writeback.proposals_dir))


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "llm": _cfg.llm.provider, "sources": sorted(_cfg.sources)}


@app.post("/investigate")
async def investigate(req: InvestigationRequest, remember: bool = True) -> dict[str, Any]:
    try:
        result = await _inv.run_async(req, remember=remember)
    except (KeyError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    out = result.to_dict()
    out["report_paths"] = {k: str(v) for k, v in result.report_paths.items()}
    return out


@app.get("/reports/{name}", response_class=HTMLResponse)
def report(name: str):
    path = _cfg.resolve(_cfg.reporting.output_dir) / Path(name).name
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/proposals")
def proposals() -> list[dict[str, Any]]:
    return [json.loads(p.model_dump_json()) for p in _store.list()]


@app.post("/proposals/{id}/approve")
def approve(id: str, by: str, comment: str = "") -> dict[str, Any]:
    try:
        return json.loads(_store.approve(id, by, comment).model_dump_json())
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
