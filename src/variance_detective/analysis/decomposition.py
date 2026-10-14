"""Deterministic variance decomposition.

Given a canonical fact frame with two versions (e.g. Actual vs Forecast), build a *variance
tree*: at each node pick the dimension that explains the variance most concisely, keep the
smallest set of members covering ``coverage_target`` of it, record offsetting members, and
recurse. Optional rate/volume and price/volume/mix splits are attached where the KPI
definition allows.

No language model is involved anywhere in this module. Every intermediate table is written
to the evidence ledger.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from ..config import AnalysisConfig
from ..evidence import EvidenceLedger
from ..semantic import KPIDefinition
from .pvm import PVMResult, RateVolumeResult, price_volume_mix, rate_volume


@dataclass
class MemberContribution:
    member: str
    actual: float
    comparison: float
    variance: float
    share_of_parent: float  # variance / parent variance (can be negative for offsets)
    pct_change: float | None


@dataclass
class Recurrence:
    prior_periods: list[str]
    count: int
    last_explanation: str | None
    last_period: str | None


@dataclass
class VarianceNode:
    path: dict[str, str]
    depth: int
    actual: float
    comparison: float
    variance: float
    variance_pct: float | None
    share_of_root: float
    share_of_parent: float | None
    material: bool
    drill_dimension: str | None = None
    children: list[VarianceNode] = field(default_factory=list)
    siblings_considered: int = 0
    coverage: float | None = None
    offsets: list[MemberContribution] = field(default_factory=list)
    rate_volume: RateVolumeResult | None = None
    pvm: PVMResult | None = None
    recurrence: Recurrence | None = None
    evidence_ids: list[str] = field(default_factory=list)
    dimension_scores: list[dict[str, Any]] = field(default_factory=list)

    @property
    def label(self) -> str:
        return " › ".join(self.path.values()) if self.path else "Total"

    @property
    def key(self) -> str:
        return "|".join(f"{k}={v}" for k, v in sorted(self.path.items())) or "TOTAL"

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()

    def to_dict(self) -> dict[str, Any]:
        d = {
            "label": self.label,
            "key": self.key,
            "path": self.path,
            "depth": self.depth,
            "actual": self.actual,
            "comparison": self.comparison,
            "variance": self.variance,
            "variance_pct": self.variance_pct,
            "share_of_root": self.share_of_root,
            "share_of_parent": self.share_of_parent,
            "material": self.material,
            "drill_dimension": self.drill_dimension,
            "coverage": self.coverage,
            "siblings_considered": self.siblings_considered,
            "offsets": [o.__dict__ for o in self.offsets],
            "rate_volume": self.rate_volume.__dict__ if self.rate_volume else None,
            "pvm": self.pvm.to_dict() if self.pvm else None,
            "recurrence": self.recurrence.__dict__ if self.recurrence else None,
            "evidence_ids": self.evidence_ids,
            "dimension_scores": self.dimension_scores,
            "children": [c.to_dict() for c in self.children],
        }
        return d


@dataclass
class VarianceTree:
    root: VarianceNode
    kpi: KPIDefinition
    actual_version: str
    compare_version: str

    def nodes(self) -> list[VarianceNode]:
        return list(self.root.walk())

    def leaves(self) -> list[VarianceNode]:
        return [n for n in self.root.walk() if not n.children and n.depth > 0]

    def to_dict(self) -> dict[str, Any]:
        return {"kpi": self.kpi.name, "actual_version": self.actual_version, "compare_version": self.compare_version, "root": self.root.to_dict()}


# ---- helpers ---------------------------------------------------------------------------

def _kpi_value(kpi: KPIDefinition, sums: pd.Series | dict[str, float]) -> float:
    env = {k: float(v) for k, v in dict(sums).items()}
    return float(pd.eval(kpi.formula, local_dict=env, engine="python"))  # type: ignore[arg-type]


def _sums_by_version(df: pd.DataFrame, measures: list[str], actual: str, compare: str) -> tuple[dict[str, float], dict[str, float]]:
    g = df.groupby("version")[measures].sum()
    a = g.loc[actual].to_dict() if actual in g.index else {m: 0.0 for m in measures}
    c = g.loc[compare].to_dict() if compare in g.index else {m: 0.0 for m in measures}
    return a, c


def _pct(variance: float, comparison: float) -> float | None:
    return variance / abs(comparison) if comparison else None


def _is_material(variance: float, comparison: float, cfg: AnalysisConfig) -> bool:
    if cfg.materiality_abs <= 0 and cfg.materiality_pct <= 0:
        return True
    if cfg.materiality_abs > 0 and abs(variance) >= cfg.materiality_abs:
        return True
    pct = _pct(variance, comparison)
    return bool(cfg.materiality_pct > 0 and pct is not None and abs(pct) >= cfg.materiality_pct / 100)


def _member_contributions(df: pd.DataFrame, dim: str, kpi: KPIDefinition, measures: list[str], actual: str, compare: str, parent_var: float) -> list[MemberContribution]:
    g = df.groupby([dim, "version"])[measures].sum()
    out: list[MemberContribution] = []
    for member in sorted(df[dim].astype(str).unique()):
        a = g.loc[(member, actual)].to_dict() if (member, actual) in g.index else {m: 0.0 for m in measures}
        c = g.loc[(member, compare)].to_dict() if (member, compare) in g.index else {m: 0.0 for m in measures}
        av, cv = _kpi_value(kpi, a), _kpi_value(kpi, c)
        var = av - cv
        out.append(MemberContribution(member, av, cv, var, (var / parent_var) if parent_var else 0.0, _pct(var, cv)))
    return out


def _score_dimension(contribs: list[MemberContribution], parent_var: float, cfg: AnalysisConfig) -> dict[str, Any]:
    """Fewest same-sign members needed to reach coverage; HHI as tiebreak (higher = more concentrated)."""
    same = sorted([c for c in contribs if c.variance * parent_var > 0], key=lambda c: abs(c.variance), reverse=True)
    target = abs(parent_var) * cfg.coverage_target
    cum, n = 0.0, 0
    for c in same:
        cum += abs(c.variance)
        n += 1
        if cum >= target:
            break
    total_abs = sum(abs(c.variance) for c in contribs) or 1.0
    hhi = sum((abs(c.variance) / total_abs) ** 2 for c in contribs)
    reached = cum >= target
    return {"members": len(contribs), "n_needed": n if reached else len(same) + 1, "coverage_reached": reached, "hhi": round(hhi, 4)}


def _choose_dimension(df: pd.DataFrame, candidates: list[str], kpi: KPIDefinition, measures: list[str], actual: str, compare: str, parent_var: float, cfg: AnalysisConfig):
    scored = []
    for dim in candidates:
        if dim not in df.columns or df[dim].nunique() < 2:
            continue
        contribs = _member_contributions(df, dim, kpi, measures, actual, compare, parent_var)
        s = _score_dimension(contribs, parent_var, cfg)
        scored.append((dim, contribs, s))
    if not scored:
        return None, [], []
    scored.sort(key=lambda t: (t[2]["n_needed"], -t[2]["hhi"]))
    dim, contribs, _ = scored[0]
    return dim, contribs, [{"dimension": d, **s} for d, _, s in scored]


# ---- main ------------------------------------------------------------------------------

def build_variance_tree(
    df: pd.DataFrame,
    kpi: KPIDefinition,
    *,
    actual_version: str,
    compare_version: str,
    drill_dimensions: list[str],
    cfg: AnalysisConfig,
    evidence: EvidenceLedger,
    source: str | None = None,
) -> VarianceTree:
    measures = [m for m in kpi.measures if m in df.columns]
    if "version" not in df.columns:
        raise ValueError("Frame must contain a 'version' column")
    a, c = _sums_by_version(df, measures, actual_version, compare_version)
    av, cv = _kpi_value(kpi, a), _kpi_value(kpi, c)
    root_var = av - cv
    root = VarianceNode(
        path={}, depth=0, actual=av, comparison=cv, variance=root_var, variance_pct=_pct(root_var, cv),
        share_of_root=1.0, share_of_parent=None, material=_is_material(root_var, cv, cfg),
    )
    ev = evidence.add(
        "headline", f"{kpi.label}: {actual_version} vs {compare_version}",
        f"Total {kpi.label} computed from {', '.join(measures)} using formula '{kpi.formula}'.",
        values={"actual": av, "comparison": cv, "variance": root_var, "variance_pct": root.variance_pct, **{f"{m}_{actual_version}": a[m] for m in measures}, **{f"{m}_{compare_version}": c[m] for m in measures}},
        source=source,
    )
    root.evidence_ids.append(ev.id)
    _attach_splits(root, df, kpi, measures, actual_version, compare_version, evidence, source)
    _drill(root, df, kpi, measures, actual_version, compare_version, drill_dimensions, cfg, evidence, root_var, source)
    return VarianceTree(root=root, kpi=kpi, actual_version=actual_version, compare_version=compare_version)


def _attach_splits(node: VarianceNode, df: pd.DataFrame, kpi: KPIDefinition, measures: list[str], actual: str, compare: str, evidence: EvidenceLedger, source: str | None) -> None:
    a, c = _sums_by_version(df, measures, actual, compare)
    if kpi.rate_driver and kpi.rate_driver in a:
        rv = rate_volume(kpi_actual=node.actual, kpi_comparison=node.comparison, driver_actual=a[kpi.rate_driver], driver_comparison=c[kpi.rate_driver], driver_name=kpi.rate_driver)
        node.rate_volume = rv
        ev = evidence.add(
            "rate_volume", f"Rate vs volume split — {node.label}",
            f"{kpi.label} = {kpi.rate_driver} × rate. Volume effect = Δ{kpi.rate_driver} × comparison rate; rate effect = Δrate × actual {kpi.rate_driver}.",
            values=rv.__dict__, source=source,
        )
        node.evidence_ids.append(ev.id)
    if kpi.value_measure and kpi.volume_measure and kpi.pvm_dimension and kpi.pvm_dimension in df.columns and kpi.volume_measure in df.columns:
        pvm = price_volume_mix(df, value=kpi.value_measure, volume=kpi.volume_measure, dim=kpi.pvm_dimension, actual=actual, compare=compare)
        if pvm is not None:
            node.pvm = pvm
            ev = evidence.add(
                "pvm", f"Price / volume / mix on {kpi.value_measure} — {node.label}",
                f"Decomposition of Δ{kpi.value_measure} over {kpi.pvm_dimension} using {kpi.volume_measure} as volume.",
                table=pvm.by_member, values={k: v for k, v in pvm.to_dict().items() if k != "by_member"}, source=source,
            )
            node.evidence_ids.append(ev.id)


def _drill(node: VarianceNode, df: pd.DataFrame, kpi: KPIDefinition, measures: list[str], actual: str, compare: str, dims: list[str], cfg: AnalysisConfig, evidence: EvidenceLedger, root_var: float, source: str | None) -> None:
    if node.depth >= cfg.max_depth or not node.material or node.variance == 0:
        return
    candidates = [d for d in dims if d not in node.path]
    dim, contribs, scores = _choose_dimension(df, candidates, kpi, measures, actual, compare, node.variance, cfg)
    node.dimension_scores = scores
    if dim is None:
        return
    node.drill_dimension = dim
    node.siblings_considered = len(contribs)
    table = [
        {dim: c.member, "actual": round(c.actual, 2), "comparison": round(c.comparison, 2), "variance": round(c.variance, 2), "share_of_parent": round(c.share_of_parent, 4), "share_of_root": round(c.variance / root_var, 4) if root_var else None, "pct_change": round(c.pct_change, 4) if c.pct_change is not None else None}
        for c in sorted(contribs, key=lambda c: abs(c.variance), reverse=True)
    ]
    same = sorted([c for c in contribs if c.variance * node.variance > 0], key=lambda c: abs(c.variance), reverse=True)
    target = abs(node.variance) * cfg.coverage_target
    chosen, cum = [], 0.0
    for c in same:
        if len(chosen) >= cfg.max_children_per_node:
            break
        if abs(c.share_of_parent) < cfg.min_child_share and chosen:
            break
        chosen.append(c)
        cum += abs(c.variance)
        if cum >= target:
            break
    node.coverage = (cum / abs(node.variance)) if node.variance else None

    ev = evidence.add(
        "pivot", f"{kpi.label} by {dim} — {node.label}",
        f"Contribution of each {dim} member to the {node.label} variance of {node.variance:,.0f}. Dimension chosen because it needs the fewest members to explain {cfg.coverage_target:.0%} (candidates scored: {', '.join(s['dimension'] + '=' + str(s['n_needed']) for s in scores)}).",
        table=table,
        values={"parent_variance": node.variance, "coverage_target": cfg.coverage_target, "members_total": len(contribs), "members_selected": len(chosen), "coverage_achieved": round(node.coverage, 4) if node.coverage is not None else None, "selected_variance": cum * (1 if node.variance > 0 else -1)},
        source=source,
    )
    node.evidence_ids.append(ev.id)
    node.offsets = sorted([c for c in contribs if c.variance * node.variance < 0 and abs(c.share_of_parent) >= cfg.offset_threshold], key=lambda c: abs(c.variance), reverse=True)
    if node.offsets:
        evo = evidence.add(
            "offsets", f"Offsetting {dim} members — {node.label}",
            f"Members moving against the {node.label} variance (≥{cfg.offset_threshold:.0%} of it). They mask part of the adverse movement.",
            table=[{dim: o.member, "variance": round(o.variance, 2), "share_of_parent": round(o.share_of_parent, 4)} for o in node.offsets], source=source,
        )
        node.evidence_ids.append(evo.id)

    for c in chosen:
        sub = df[df[dim].astype(str) == c.member]
        child = VarianceNode(
            path={**node.path, dim: c.member}, depth=node.depth + 1, actual=c.actual, comparison=c.comparison, variance=c.variance,
            variance_pct=c.pct_change, share_of_root=(c.variance / root_var) if root_var else 0.0, share_of_parent=c.share_of_parent,
            material=_is_material(c.variance, c.comparison, cfg),
        )
        node.children.append(child)
        _attach_splits(child, sub, kpi, measures, actual, compare, evidence, source)
        _drill(child, sub, kpi, measures, actual, compare, dims, cfg, evidence, root_var, source)
