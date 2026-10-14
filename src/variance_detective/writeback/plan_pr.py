"""Plan PR — pull requests for planning data.

The agent never writes a number into a planning system on its own. It produces a
*change proposal*: a diff (current → proposed) per intersection, with rationale and evidence
ids, that a human reviews. ``approve`` records who approved it; ``apply`` pushes it through
the source connector's ``write_draft`` operation (which itself should target a draft/private
version in the planning tool, never the published forecast).

Proposals are plain JSON files so they can be reviewed in a PR, attached to a ticket, or
loaded into any workflow tool.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class ProposalLine(BaseModel):
    path: dict[str, str]
    measure: str
    current: float | None
    proposed: float
    delta: float
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)


class ChangeProposal(BaseModel):
    id: str
    created_at: str
    status: Literal["draft", "approved", "rejected", "applied", "failed"] = "draft"
    investigation_id: str
    source: str
    kpi: str
    period: str
    target_version: str
    title: str
    summary: str
    lines: list[ProposalLine]
    approvals: list[dict[str, str]] = Field(default_factory=list)
    applied_result: dict[str, Any] | None = None

    @property
    def total_delta(self) -> float:
        return sum(line.delta for line in self.lines)


def build_proposal(
    adjustments: list[dict[str, Any]],
    frame: pd.DataFrame,
    *,
    investigation_id: str,
    source: str,
    kpi: str,
    period: str,
    target_version: str,
    title: str,
    summary: str,
) -> ChangeProposal | None:
    """Turn the narrator's proposed adjustments (deltas) into concrete current→proposed lines."""
    lines: list[ProposalLine] = []
    for adj in adjustments:
        path = {k: str(v) for k, v in (adj.get("path") or {}).items()}
        measure = adj.get("measure")
        delta = adj.get("proposed_delta")
        if not measure or delta in (None, 0) or measure not in frame.columns:
            continue
        sub = frame[frame["version"].astype(str) == target_version]
        for dim, member in path.items():
            if dim in sub.columns:
                sub = sub[sub[dim].astype(str) == member]
        current = float(sub[measure].sum()) if len(sub) else None
        proposed = (current or 0.0) + float(delta)
        lines.append(ProposalLine(path=path, measure=measure, current=current, proposed=proposed, delta=float(delta), rationale=adj.get("rationale", ""), evidence_ids=list(adj.get("evidence_ids", []))))
    if not lines:
        return None
    return ChangeProposal(
        id=f"PR-{period}-{uuid.uuid4().hex[:6]}",
        created_at=_now(),
        investigation_id=investigation_id,
        source=source,
        kpi=kpi,
        period=period,
        target_version=target_version,
        title=title,
        summary=summary,
        lines=lines,
    )


class ProposalStore:
    def __init__(self, directory: str | Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, id_: str) -> Path:
        return self.dir / f"{id_}.json"

    def save(self, p: ChangeProposal) -> Path:
        path = self._path(p.id)
        path.write_text(json.dumps(p.model_dump(), indent=2), encoding="utf-8")
        return path

    def load(self, id_: str) -> ChangeProposal:
        path = self._path(id_)
        if not path.exists():
            raise FileNotFoundError(f"No proposal {id_} in {self.dir}")
        return ChangeProposal(**json.loads(path.read_text(encoding="utf-8")))

    def list(self) -> list[ChangeProposal]:
        return sorted((ChangeProposal(**json.loads(p.read_text(encoding="utf-8"))) for p in self.dir.glob("PR-*.json")), key=lambda p: p.created_at, reverse=True)

    def approve(self, id_: str, by: str, comment: str = "") -> ChangeProposal:
        p = self.load(id_)
        if p.status not in ("draft",):
            raise ValueError(f"Proposal {id_} is {p.status}; only drafts can be approved")
        p.approvals.append({"by": by, "at": _now(), "comment": comment})
        p.status = "approved"
        self.save(p)
        return p

    def reject(self, id_: str, by: str, comment: str = "") -> ChangeProposal:
        p = self.load(id_)
        p.approvals.append({"by": by, "at": _now(), "comment": comment, "decision": "rejected"})
        p.status = "rejected"
        self.save(p)
        return p

    async def apply(self, id_: str, connector) -> ChangeProposal:
        p = self.load(id_)
        if p.status != "approved":
            raise ValueError(f"Proposal {id_} must be approved before it can be applied (status: {p.status})")
        try:
            result = await connector.write_draft(p.model_dump())
            p.applied_result = result if isinstance(result, dict) else {"result": result}
            p.status = "applied"
        except Exception as e:
            p.applied_result = {"error": f"{type(e).__name__}: {e}"}
            p.status = "failed"
            self.save(p)
            raise
        self.save(p)
        return p
