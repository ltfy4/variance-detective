from __future__ import annotations

from typing import TYPE_CHECKING

from ..analysis.format import fmt_pct, fmt_pts, fmt_value
from ..config import AppConfig

if TYPE_CHECKING:  # pragma: no cover
    from ..agent.orchestrator import InvestigationResult


def render_markdown(r: InvestigationResult, cfg: AppConfig) -> str:
    kpi, sym = r.tree.kpi, cfg.reporting.currency_symbol
    v = lambda x, signed=False: fmt_value(x, kpi.unit, sym, signed=signed)
    root = r.tree.root
    lines = [
        f"# {r.title}",
        "",
        f"*Investigation {r.id} · source `{r.request.source}` · {r.created_at} · narrator: {r.llm_meta.get('narrator')}"
        + (f" ({r.llm_meta.get('provider')}/{r.llm_meta.get('model')})" if r.llm_meta.get("provider") else "")
        + f" · verification: {r.verification.verified_claims}/{r.verification.total_claims} claims*",
        "",
        f"## {r.narrative.headline}",
        "",
        r.narrative.summary,
        "",
        "| | Actual | Comparison | Variance | % |",
        "|---|---:|---:|---:|---:|",
        f"| {kpi.label} | {v(root.actual)} | {v(root.comparison)} | {v(root.variance, True)} | {fmt_pct(root.variance_pct, signed=True)} |",
    ]
    if root.rate_volume:
        rv = root.rate_volume
        lines += ["", f"Rate effect **{v(rv.rate_effect, True)}** ({fmt_pct(rv.rate_actual)} vs {fmt_pct(rv.rate_comparison)}, {fmt_pts(rv.rate_delta_pts)}) · volume effect **{v(rv.volume_effect, True)}**"]
    lines += ["", "## Key findings", ""]
    for c in r.narrative.key_findings:
        badge = "✅" if c.verified else "⚠️"
        lines.append(f"- {badge} {c.statement} _[{', '.join(c.evidence_ids)}]_")
    if r.narrative.root_causes:
        lines += ["", "## Root causes", ""]
        for c in r.narrative.root_causes:
            badge = "✅" if c.verified else "⚠️"
            lines.append(f"- {badge} {c.statement} _[{', '.join(c.evidence_ids)}]_")
    if r.narrative.recommended_actions:
        lines += ["", "## Recommended actions", ""] + [f"1. {a}" for a in r.narrative.recommended_actions]
    lines += ["", "## Variance tree", ""]
    for n in r.tree.nodes():
        indent = "  " * n.depth
        rec = f" · recurring ×{n.recurrence.count}" if n.recurrence else ""
        lines.append(f"{indent}- **{n.label}** {v(n.variance, True)} ({fmt_pct(n.share_of_root, signed=False)} of total){rec}")
    if r.proposal:
        p = r.proposal
        lines += ["", f"## Plan PR `{p.id}` — status: {p.status}", "", f"Target version: `{p.target_version}` · total delta {v(p.total_delta, True)}", "", "| Intersection | Measure | Current | Proposed | Δ | Rationale |", "|---|---|---:|---:|---:|---|"]
        for ln in p.lines:
            lines.append(f"| {' › '.join(ln.path.values())} | {ln.measure} | {v(ln.current)} | {v(ln.proposed)} | {v(ln.delta, True)} | {ln.rationale} |")
        lines += ["", f"Approve with: `vd pr approve {p.id} --by <name>`"]
    lines += ["", "## Evidence", ""]
    for e in r.evidence:
        lines.append(f"- **{e.id}** · {e.kind} · {e.title} — {e.description}")
    if r.warnings:
        lines += ["", "## Warnings", ""] + [f"- {w}" for w in r.warnings]
    return "\n".join(lines) + "\n"
