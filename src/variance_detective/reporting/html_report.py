from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..analysis.format import fmt_pct, fmt_pts, fmt_value
from ..config import AppConfig
from . import charts

if TYPE_CHECKING:  # pragma: no cover
    from ..agent.orchestrator import InvestigationResult

_TEMPLATES = Path(__file__).parent / "templates"


def _env() -> Environment:
    env = Environment(loader=FileSystemLoader(str(_TEMPLATES)), autoescape=select_autoescape(["html"]))
    env.filters["pct"] = lambda x, signed=False: fmt_pct(x, signed=signed)
    env.filters["pts"] = fmt_pts
    return env


def render_html(r: InvestigationResult, cfg: AppConfig) -> str:
    kpi, sym = r.tree.kpi, cfg.reporting.currency_symbol
    v = lambda x, signed=False: fmt_value(x, kpi.unit, sym, signed=signed)
    root = r.tree.root

    # Waterfall: comparison → depth-1 contributions → other → actual
    steps: list[tuple[str, float, str]] = [(f"{r.tree.compare_version}", root.comparison, "start")]
    explained = 0.0
    for c in root.children:
        steps.append((c.label, c.variance, "delta"))
        explained += c.variance
    for o in root.offsets[:3]:
        steps.append((f"{o.member} (offset)", o.variance, "delta"))
        explained += o.variance
    other = root.variance - explained
    if abs(other) > abs(root.variance) * 0.005:
        steps.append(("Other", other, "delta"))
    steps.append((f"{r.tree.actual_version}", root.actual, "end"))
    waterfall_svg = charts.waterfall(steps, lambda x: v(x, signed=False) if abs(x) >= abs(root.comparison) * 0.5 else v(x, signed=True))

    # Leaf contributions chart
    leaves = sorted(r.tree.leaves(), key=lambda n: abs(n.variance), reverse=True)[:10]
    leaf_rows = [(n.label, n.variance, f"×{n.recurrence.count + 1} periods" if n.recurrence else None) for n in leaves]
    leaves_svg = charts.hbars(leaf_rows, lambda x: v(x, signed=True))

    rv_svg = ""
    if root.rate_volume:
        rv = root.rate_volume
        rv_svg = charts.hbars([(f"Rate effect ({fmt_pts(rv.rate_delta_pts)})", rv.rate_effect, None), (f"Volume effect ({rv.driver_name})", rv.volume_effect, None)], lambda x: v(x, signed=True), width=480, row_h=34)

    pvm_svg = ""
    if root.pvm:
        p = root.pvm
        pvm_svg = charts.hbars([("Price", p.price_effect, None), ("Volume", p.volume_effect, None), (f"Mix ({p.dimension})", p.mix_effect, None)], lambda x: fmt_value(x, "currency", sym, signed=True), width=480, row_h=34)

    def node_view(n) -> dict[str, Any]:
        return {
            "label": n.label,
            "leaf": n.path[list(n.path)[-1]] if n.path else "Total",
            "depth": n.depth,
            "variance": v(n.variance, True),
            "actual": v(n.actual),
            "comparison": v(n.comparison),
            "pct": fmt_pct(n.variance_pct, signed=True),
            "share": fmt_pct(n.share_of_root, signed=False),
            "share_num": abs(n.share_of_root),
            "adverse": (n.variance < 0) == (kpi.direction == "higher_is_better"),
            "drill": n.drill_dimension,
            "coverage": fmt_pct(n.coverage, signed=False) if n.coverage is not None else None,
            "recurrence": n.recurrence,
            "rate_volume": ({"rate": v(n.rate_volume.rate_effect, True), "volume": v(n.rate_volume.volume_effect, True), "delta": fmt_pts(n.rate_volume.rate_delta_pts), "r1": fmt_pct(n.rate_volume.rate_actual), "r0": fmt_pct(n.rate_volume.rate_comparison)} if n.rate_volume else None),
            "offsets": [(o.member, v(o.variance, True)) for o in n.offsets[:3]],
            "evidence": n.evidence_ids,
            "children": [node_view(c) for c in n.children],
        }

    ctx = {
        "r": r,
        "kpi": kpi,
        "root": root,
        "v": v,
        "headline": {"actual": v(root.actual), "comparison": v(root.comparison), "variance": v(root.variance, True), "pct": fmt_pct(root.variance_pct, signed=True), "adverse": (root.variance < 0) == (kpi.direction == "higher_is_better")},
        "rate_volume": ({"rate": v(root.rate_volume.rate_effect, True), "volume": v(root.rate_volume.volume_effect, True), "delta": fmt_pts(root.rate_volume.rate_delta_pts), "r1": fmt_pct(root.rate_volume.rate_actual), "r0": fmt_pct(root.rate_volume.rate_comparison), "driver": root.rate_volume.driver_name} if root.rate_volume else None),
        "waterfall_svg": waterfall_svg,
        "leaves_svg": leaves_svg,
        "rv_svg": rv_svg,
        "pvm_svg": pvm_svg,
        "tree": node_view(root),
        "proposal": r.proposal,
        "evidence": list(r.evidence),
        "verification": r.verification,
        "narrative": r.narrative,
        "symbol": sym,
        "version": __import__("variance_detective").__version__,
    }
    return _env().get_template("report.html.j2").render(**ctx)
