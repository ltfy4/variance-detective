"""Turn the variance tree into the compact, display-ready JSON the narrators consume."""
from __future__ import annotations

from typing import Any

from ..analysis import VarianceNode, VarianceTree
from ..analysis.format import fmt_money, fmt_pct, fmt_pts, fmt_value
from ..semantic import KPIDefinition


class Display:
    def __init__(self, kpi: KPIDefinition, symbol: str):
        self.kpi = kpi
        self.symbol = symbol

    def value(self, x: float | None, signed: bool = False) -> str:
        return fmt_value(x, self.kpi.unit, self.symbol, signed=signed)

    def money(self, x: float | None, signed: bool = False) -> str:
        return fmt_money(x, self.symbol, signed=signed)

    def pct(self, x: float | None, signed: bool = True) -> str:
        return fmt_pct(x, signed=signed)

    def pts(self, x: float | None) -> str:
        return fmt_pts(x)


def node_payload(n: VarianceNode, d: Display) -> dict[str, Any]:
    out: dict[str, Any] = {
        "label": n.label,
        "path": n.path,
        "depth": n.depth,
        "actual": round(n.actual, 2),
        "comparison": round(n.comparison, 2),
        "variance": round(n.variance, 2),
        "variance_pct": round(n.variance_pct, 4) if n.variance_pct is not None else None,
        "share_of_root": round(n.share_of_root, 4),
        "share_of_parent": round(n.share_of_parent, 4) if n.share_of_parent is not None else None,
        "display": {
            "actual": d.value(n.actual),
            "comparison": d.value(n.comparison),
            "variance": d.value(n.variance, signed=True),
            "variance_pct": d.pct(n.variance_pct),
            "share_of_root": d.pct(n.share_of_root, signed=False),
            "share_of_parent": d.pct(n.share_of_parent, signed=False) if n.share_of_parent is not None else None,
        },
        "evidence_ids": n.evidence_ids,
        "drill_dimension": n.drill_dimension,
        "coverage": round(n.coverage, 4) if n.coverage is not None else None,
        "members_considered": n.siblings_considered,
        "children": [c.label for c in n.children],
    }
    if n.offsets:
        out["offsets"] = [{"member": o.member, "variance": round(o.variance, 2), "display": d.value(o.variance, signed=True), "share_of_parent": round(o.share_of_parent, 4)} for o in n.offsets]
    if n.rate_volume:
        rv = n.rate_volume
        out["rate_volume"] = {
            "driver": rv.driver_name,
            "volume_effect": round(rv.volume_effect, 2),
            "rate_effect": round(rv.rate_effect, 2),
            "rate_actual": round(rv.rate_actual, 4) if rv.rate_actual is not None else None,
            "rate_comparison": round(rv.rate_comparison, 4) if rv.rate_comparison is not None else None,
            "display": {
                "volume_effect": d.value(rv.volume_effect, signed=True),
                "rate_effect": d.value(rv.rate_effect, signed=True),
                "rate_actual": d.pct(rv.rate_actual, signed=False),
                "rate_comparison": d.pct(rv.rate_comparison, signed=False),
                "rate_delta": d.pts(rv.rate_delta_pts),
                "driver_actual": d.money(rv.driver_actual),
                "driver_comparison": d.money(rv.driver_comparison),
            },
        }
    if n.pvm:
        p = n.pvm
        out["pvm"] = {
            "dimension": p.dimension,
            "value_measure": p.value_measure,
            "price_effect": round(p.price_effect, 2),
            "volume_effect": round(p.volume_effect, 2),
            "mix_effect": round(p.mix_effect, 2),
            "display": {"price": d.money(p.price_effect, signed=True), "volume": d.money(p.volume_effect, signed=True), "mix": d.money(p.mix_effect, signed=True), "total": d.money(p.total, signed=True)},
        }
    if n.recurrence:
        r = n.recurrence
        out["recurrence"] = {"count": r.count, "prior_periods": r.prior_periods, "last_period": r.last_period, "last_explanation": r.last_explanation}
    return out


def build_payload(tree: VarianceTree, *, period: str, source: str, symbol: str, memory_notes: list[dict[str, Any]]) -> dict[str, Any]:
    d = Display(tree.kpi, symbol)
    nodes = [node_payload(n, d) for n in tree.nodes()]
    return {
        "kpi": {"name": tree.kpi.name, "label": tree.kpi.label, "unit": tree.kpi.unit, "direction": tree.kpi.direction, "formula": tree.kpi.formula},
        "period": period,
        "source": source,
        "actual_version": tree.actual_version,
        "compare_version": tree.compare_version,
        "root": nodes[0],
        "nodes": nodes[1:],
        "memory": memory_notes,
        "canonical_measures": tree.kpi.measures,
    }
