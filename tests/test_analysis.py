"""Deterministic engine: identities and planted-story recovery."""
from __future__ import annotations

import pandas as pd
import pytest

from variance_detective.analysis.decomposition import build_variance_tree
from variance_detective.analysis.pvm import price_volume_mix, rate_volume
from variance_detective.config import AnalysisConfig
from variance_detective.evidence import EvidenceLedger
from variance_detective.semantic import KPIDefinition

GM = KPIDefinition(name="gross_margin", label="Gross Margin", formula="net_sales - cogs", drill_dimensions=["region", "category", "store", "channel"], rate_driver="net_sales", value_measure="net_sales", volume_measure="units", pvm_dimension="category")


def test_rate_volume_identity():
    rv = rate_volume(kpi_actual=1030.0, kpi_comparison=1000.0, driver_actual=2600.0, driver_comparison=2500.0, driver_name="net_sales")
    assert rv.volume_effect + rv.rate_effect == pytest.approx(30.0)
    assert rv.rate_delta_pts == pytest.approx(1030 / 2600 - 1000 / 2500)


def test_pvm_identity(demo_frame):
    df = demo_frame[demo_frame["time"] == "2026-03"]
    r = price_volume_mix(df, value="net_sales", volume="units", dim="category", actual="Actual", compare="Forecast")
    assert r is not None
    assert r.price_effect + r.volume_effect + r.mix_effect == pytest.approx(r.total, rel=1e-9)
    ga = df[df.version == "Actual"].net_sales.sum() - df[df.version == "Forecast"].net_sales.sum()
    assert r.total == pytest.approx(ga)


def test_single_member_explains_everything():
    rows = []
    for region in ["A", "B", "C"]:
        rows.append({"region": region, "version": "Forecast", "net_sales": 100.0, "cogs": 60.0})
        rows.append({"region": region, "version": "Actual", "net_sales": 100.0, "cogs": 60.0 + (30.0 if region == "B" else 0.0)})
    df = pd.DataFrame(rows)
    tree = build_variance_tree(df, GM, actual_version="Actual", compare_version="Forecast", drill_dimensions=["region"], cfg=AnalysisConfig(), evidence=EvidenceLedger())
    assert tree.root.variance == pytest.approx(-30.0)
    assert tree.root.drill_dimension == "region"
    assert [c.label for c in tree.root.children] == ["B"]
    assert tree.root.coverage == pytest.approx(1.0)


def test_children_sum_matches_pivot_and_offsets_detected():
    rows = []
    for region, delta in {"A": -50.0, "B": -40.0, "C": +20.0, "D": -5.0}.items():
        rows.append({"region": region, "version": "Forecast", "net_sales": 100.0, "cogs": 60.0})
        rows.append({"region": region, "version": "Actual", "net_sales": 100.0 + delta, "cogs": 60.0})
    df = pd.DataFrame(rows)
    tree = build_variance_tree(df, GM, actual_version="Actual", compare_version="Forecast", drill_dimensions=["region"], cfg=AnalysisConfig(coverage_target=0.8), evidence=EvidenceLedger())
    assert tree.root.variance == pytest.approx(-75.0)
    assert [c.label for c in tree.root.children] == ["A", "B"]  # -90 of -75 → ≥80% after A alone? A=67%, A+B=120%
    assert [o.member for o in tree.root.offsets] == ["C"]


def test_planted_story_is_recovered(demo_frame):
    df = demo_frame[demo_frame["time"] == "2026-03"]
    ledger = EvidenceLedger()
    tree = build_variance_tree(df, GM, actual_version="Actual", compare_version="Forecast", drill_dimensions=GM.drill_dimensions, cfg=AnalysisConfig(max_depth=4), evidence=ledger)
    assert tree.root.variance < 0
    assert tree.root.rate_volume is not None and abs(tree.root.rate_volume.rate_effect) > abs(tree.root.rate_volume.volume_effect)
    leaves = {n.label for n in tree.leaves()}
    assert {"South › Store › Womenswear › S03", "South › Store › Womenswear › S07", "South › Store › Womenswear › S11"} <= leaves
    assert len(ledger) > 5
    # every node cites at least one evidence item that exists
    ids = ledger.ids()
    for n in tree.nodes():
        assert n.evidence_ids and set(n.evidence_ids) <= ids


def test_materiality_stops_drilling():
    rows = [
        {"region": "A", "version": "Forecast", "net_sales": 1000.0, "cogs": 600.0},
        {"region": "A", "version": "Actual", "net_sales": 1000.0, "cogs": 601.0},
        {"region": "B", "version": "Forecast", "net_sales": 1000.0, "cogs": 600.0},
        {"region": "B", "version": "Actual", "net_sales": 1000.0, "cogs": 600.0},
    ]
    tree = build_variance_tree(pd.DataFrame(rows), GM, actual_version="Actual", compare_version="Forecast", drill_dimensions=["region"], cfg=AnalysisConfig(materiality_abs=50), evidence=EvidenceLedger())
    assert tree.root.material is False and tree.root.children == []
