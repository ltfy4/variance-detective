"""The investigation loop.

    request ─► fetch facts (connector) ─► variance tree (deterministic) ─► recall memory
            ─► narrate (LLM or template) ─► verify claims ─► Plan PR draft ─► remember ─► report

Each arrow writes to the evidence ledger or the result object; nothing is hidden in logs.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import BaseModel, Field

from ..analysis import VarianceTree, build_variance_tree
from ..analysis.decomposition import Recurrence
from ..config import AppConfig
from ..connectors import FactQuery, build_connector
from ..evidence import EvidenceLedger
from ..llm import build_provider
from ..memory import MemoryStore
from ..semantic import SemanticModel, load_semantic_model
from ..writeback import ChangeProposal, ProposalStore, build_proposal
from .narrative import Narrative
from .narrators import LLMNarrator, TemplateNarrator
from .payload import build_payload
from .verifier import VerificationReport, verify_narrative


class InvestigationRequest(BaseModel):
    kpi: str
    period: str
    source: str
    actual_version: str = "Actual"
    compare_version: str = "Forecast"
    compare_period: str | None = Field(None, description="Compare against another period (e.g. prior month) instead of the same period")
    scope: dict[str, list[str]] = Field(default_factory=dict, description="Canonical filters, e.g. {'region': ['South']}")
    drill_dimensions: list[str] | None = None
    title: str | None = None


@dataclass
class InvestigationResult:
    id: str
    created_at: str
    request: InvestigationRequest
    tree: VarianceTree
    narrative: Narrative
    verification: VerificationReport
    evidence: EvidenceLedger
    frame: pd.DataFrame
    proposal: ChangeProposal | None = None
    memory_hits: list[dict[str, Any]] = field(default_factory=list)
    llm_meta: dict[str, Any] = field(default_factory=dict)
    timings_ms: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    report_paths: dict[str, Path] = field(default_factory=dict)
    source_description: dict[str, Any] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return self.request.title or f"{self.tree.kpi.label} — {self.request.period} — {self.tree.actual_version} vs {self.tree.compare_version}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "title": self.title,
            "request": self.request.model_dump(),
            "tree": self.tree.to_dict(),
            "narrative": self.narrative.to_dict(),
            "verification": self.verification.to_dict(),
            "evidence": self.evidence.to_list(),
            "proposal": self.proposal.model_dump() if self.proposal else None,
            "memory_hits": self.memory_hits,
            "llm": self.llm_meta,
            "timings_ms": self.timings_ms,
            "warnings": self.warnings,
            "source": self.source_description,
        }


class Investigator:
    def __init__(self, cfg: AppConfig, semantic: SemanticModel | None = None):
        self.cfg = cfg
        self.semantic = semantic or load_semantic_model(cfg.resolve(cfg.semantic_model))
        self.memory = MemoryStore(cfg.resolve(cfg.memory.path)) if cfg.memory.enabled else None
        self.proposals = ProposalStore(cfg.resolve(cfg.writeback.proposals_dir))
        provider = build_provider(cfg.llm)
        self.narrator = TemplateNarrator() if provider.name == "offline" else LLMNarrator(provider)

    # ---- public -------------------------------------------------------------------------
    def run(self, req: InvestigationRequest, *, remember: bool = True) -> InvestigationResult:
        return asyncio.run(self.run_async(req, remember=remember))

    async def run_async(self, req: InvestigationRequest, *, remember: bool = True) -> InvestigationResult:
        t_all = time.perf_counter()
        timings: dict[str, int] = {}
        warnings: list[str] = []
        ledger = EvidenceLedger(rows_limit=self.cfg.reporting.evidence_rows_limit)
        kpi = self.semantic.kpi(req.kpi)
        drill_dims = req.drill_dimensions or kpi.drill_dimensions
        investigation_id = f"INV-{req.period}-{uuid.uuid4().hex[:6]}"

        # 1. fetch ---------------------------------------------------------------------
        t0 = time.perf_counter()
        connector = build_connector(req.source, self.cfg, self.semantic)
        frame, compare_label = await self._fetch(connector, req, kpi, drill_dims, ledger)
        timings["fetch"] = int((time.perf_counter() - t0) * 1000)
        if frame.empty:
            raise ValueError(f"No data returned for {req.kpi} / {req.period} from source '{req.source}'. Check versions, period format and member mappings.")

        # 2. analyse ---------------------------------------------------------------------
        t0 = time.perf_counter()
        tree = build_variance_tree(
            frame, kpi, actual_version=req.actual_version, compare_version=compare_label,
            drill_dimensions=drill_dims, cfg=self.cfg.analysis, evidence=ledger, source=req.source,
        )
        timings["analysis"] = int((time.perf_counter() - t0) * 1000)

        # 3. memory recall -----------------------------------------------------------------
        memory_hits = self._recall(tree, req, ledger) if self.memory else []

        # 4. narrate ---------------------------------------------------------------------
        t0 = time.perf_counter()
        payload = build_payload(tree, period=req.period, source=req.source, symbol=self.cfg.reporting.currency_symbol, memory_notes=memory_hits)
        payload["_evidence_kinds"] = {e.id: e.kind for e in ledger}
        narrative, llm_meta = self.narrator.narrate(payload, kpi)
        if llm_meta.get("fallback"):
            warnings.append(f"LLM narrator failed ({llm_meta.get('error')}); used template narrator instead.")
        timings["narrative"] = int((time.perf_counter() - t0) * 1000)

        # 5. verify ----------------------------------------------------------------------
        verification = verify_narrative(narrative, ledger)
        if not verification.ok:
            warnings.append(f"{verification.total_claims - verification.verified_claims} of {verification.total_claims} claims could not be fully verified against evidence; they are flagged in the report.")

        # 6. Plan PR ---------------------------------------------------------------------
        proposal = None
        if self.cfg.writeback.mode != "disabled" and narrative.proposed_adjustments:
            proposal = build_proposal(
                [a.model_dump() for a in narrative.proposed_adjustments], frame,
                investigation_id=investigation_id, source=req.source, kpi=kpi.name, period=req.period,
                target_version=self.cfg.writeback.target_version, title=f"Forecast adjustment — {kpi.label} {req.period}", summary=narrative.headline,
            )
            if proposal:
                self.proposals.save(proposal)

        result = InvestigationResult(
            id=investigation_id, created_at=datetime.now(UTC).isoformat(timespec="seconds"), request=req, tree=tree,
            narrative=narrative, verification=verification, evidence=ledger, frame=frame, proposal=proposal,
            memory_hits=memory_hits, llm_meta=llm_meta, timings_ms=timings, warnings=warnings,
        )
        try:
            desc = await connector.describe()
            result.source_description = {"name": desc.name, "type": desc.type, "dimensions": desc.dimensions, "measures": desc.measures}
        except Exception as e:  # noqa: BLE001
            result.source_description = {"name": req.source, "error": str(e)}

        # 7. remember --------------------------------------------------------------------
        if remember and self.memory:
            self._remember(result)

        # 8. report ----------------------------------------------------------------------
        t0 = time.perf_counter()
        from ..reporting import write_reports

        result.report_paths = write_reports(result, self.cfg)
        timings["report"] = int((time.perf_counter() - t0) * 1000)
        timings["total"] = int((time.perf_counter() - t_all) * 1000)
        return result

    # ---- steps ------------------------------------------------------------------------
    async def _fetch(self, connector, req: InvestigationRequest, kpi, drill_dims: list[str], ledger: EvidenceLedger) -> tuple[pd.DataFrame, str]:
        dims = list(dict.fromkeys([*drill_dims, *([kpi.pvm_dimension] if kpi.pvm_dimension else []), "version"]))
        base_filters = {**req.scope}
        q_actual = FactQuery(measures=kpi.measures, dimensions=dims, filters={**base_filters, "time": [req.period], "version": [req.actual_version]})
        compare_period = req.compare_period or req.period
        q_compare = FactQuery(measures=kpi.measures, dimensions=dims, filters={**base_filters, "time": [compare_period], "version": [req.compare_version]})
        if compare_period == req.period:
            q = FactQuery(measures=kpi.measures, dimensions=dims, filters={**base_filters, "time": [req.period], "version": [req.actual_version, req.compare_version]})
            res = await connector.fetch(q)
            frame, compare_label = res.frame, req.compare_version
            ledger.add("query", f"Fact query — {req.source}", res.query.describe(), table=frame.head(8).to_dict("records"), values={"rows_returned": res.rows, "elapsed_ms": res.elapsed_ms, "source_query": res.source_query.__dict__}, source=req.source)
        else:
            ra, rc = await connector.fetch(q_actual), await connector.fetch(q_compare)
            compare_label = f"{req.compare_version} {compare_period}"
            fc = rc.frame.copy()
            fc["version"] = compare_label
            frame = pd.concat([ra.frame, fc], ignore_index=True)
            ledger.add("query", f"Fact queries — {req.source}", f"{ra.query.describe()}  ∪  {rc.query.describe()}", table=frame.head(8).to_dict("records"), values={"rows_returned": ra.rows + rc.rows, "elapsed_ms": ra.elapsed_ms + rc.elapsed_ms}, source=req.source)
        return frame, compare_label

    def _recall(self, tree: VarianceTree, req: InvestigationRequest, ledger: EvidenceLedger) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        assert self.memory is not None
        for node in tree.nodes():
            prior = self.memory.recall(kpi=tree.kpi.name, node_key=node.key, exclude_period=req.period)
            same_sign = [p for p in prior if p["variance"] * node.variance > 0]
            if not same_sign:
                continue
            node.recurrence = Recurrence(prior_periods=[p["period"] for p in same_sign], count=len(same_sign), last_explanation=same_sign[0].get("explanation"), last_period=same_sign[0]["period"])
            ev = ledger.add(
                "memory", f"Prior findings — {node.label}",
                f"The same {tree.kpi.label} node was flagged with the same sign in {len(same_sign)} earlier investigation(s).",
                table=[{"period": p["period"], "variance": round(p["variance"], 2), "explanation": p.get("explanation")} for p in same_sign],
                values={"count": len(same_sign)},
            )
            node.evidence_ids.append(ev.id)
            hits.append({"node": node.label, "count": len(same_sign), "periods": node.recurrence.prior_periods, "last_explanation": node.recurrence.last_explanation, "evidence_id": ev.id})
        return hits

    def _remember(self, result: InvestigationResult) -> None:
        assert self.memory is not None
        causes = {c.statement.split(":")[0]: c.statement for c in result.narrative.root_causes}
        findings = []
        for n in result.tree.nodes():
            explanation = next((s for lbl, s in causes.items() if lbl == n.label), None)
            if n.depth == 0:
                explanation = result.narrative.headline
            findings.append({"node_key": n.key, "label": n.label, "depth": n.depth, "variance": n.variance, "share_of_root": n.share_of_root, "explanation": explanation, "tags": []})
        self.memory.remember(
            investigation_id=result.id, kpi=result.tree.kpi.name, period=result.request.period, actual_version=result.tree.actual_version,
            compare_version=result.tree.compare_version, source=result.request.source, variance=result.tree.root.variance,
            headline=result.narrative.headline, summary=result.narrative.summary, findings=findings,
        )
