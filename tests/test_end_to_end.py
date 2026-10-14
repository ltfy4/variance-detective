"""Offline end-to-end: CSV source → tree → template narrative → verifier → memory → Plan PR → reports."""
from __future__ import annotations

import json

from variance_detective.agent import InvestigationRequest, Investigator
from variance_detective.config import load_config


def test_full_run_offline(project):
    cfg = load_config(project / "config" / "agent.yaml")
    assert cfg.base_dir == project
    inv = Investigator(cfg)

    feb = inv.run(InvestigationRequest(kpi="gross_margin", period="2026-02", source="demo"))
    assert feb.verification.ok, feb.verification.to_dict()
    assert feb.memory_hits == []

    mar = inv.run(InvestigationRequest(kpi="gross_margin", period="2026-03", source="demo"))
    assert mar.verification.ok, mar.verification.to_dict()
    assert mar.tree.root.variance < 0
    # memory found the recurring S07 node
    assert any("S07" in h["node"] for h in mar.memory_hits)
    rec = [n for n in mar.tree.nodes() if n.recurrence and "S07" in n.label]
    assert rec and rec[0].recurrence.prior_periods == ["2026-02"]
    # a Plan PR was drafted for the recurring node, pointing at the forecast version
    assert mar.proposal is not None and mar.proposal.status == "draft"
    assert mar.proposal.target_version == "Forecast"
    assert all(line.measure == "cogs" and line.delta > 0 for line in mar.proposal.lines)
    assert (project / "workspace" / "proposals" / f"{mar.proposal.id}.json").exists()
    # reports exist and are self-contained
    for fmt in ("html", "markdown", "json"):
        assert mar.report_paths[fmt].exists() and mar.report_paths[fmt].stat().st_size > 2000
    html = mar.report_paths["html"].read_text()
    assert "<script" not in html.lower() and mar.narrative.headline in html
    data = json.loads(mar.report_paths["json"].read_text())
    assert data["verification"]["ok"] and len(data["evidence"]) == len(mar.evidence)


def test_scope_and_compare_period(project):
    cfg = load_config(project / "config" / "agent.yaml")
    inv = Investigator(cfg)
    r = inv.run(InvestigationRequest(kpi="net_sales", period="2026-03", compare_version="Actual", compare_period="2026-02", source="demo", scope={"region": ["South"]}), remember=False)
    assert r.tree.compare_version == "Actual 2026-02"
    assert all(n.path.get("region", "South") == "South" for n in r.tree.nodes())
    assert r.verification.ok


def test_env_override_changes_provider(project, monkeypatch):
    monkeypatch.setenv("VD_LLM__PROVIDER", "anthropic")
    monkeypatch.setenv("VD_LLM__MODEL", "claude-x")
    cfg = load_config(project / "config" / "agent.yaml")
    assert cfg.llm.provider == "anthropic" and cfg.llm.model == "claude-x"
    monkeypatch.delenv("VD_LLM__PROVIDER")
    monkeypatch.delenv("VD_LLM__MODEL")


def test_plan_pr_lifecycle(project):
    from variance_detective.writeback import ProposalStore

    cfg = load_config(project / "config" / "agent.yaml")
    inv = Investigator(cfg)
    inv.run(InvestigationRequest(kpi="gross_margin", period="2026-02", source="demo"))
    mar = inv.run(InvestigationRequest(kpi="gross_margin", period="2026-03", source="demo"))
    store = ProposalStore(cfg.resolve(cfg.writeback.proposals_dir))
    p = store.approve(mar.proposal.id, by="cfo@example.com", comment="agreed")
    assert p.status == "approved" and p.approvals[0]["by"] == "cfo@example.com"
    import pytest

    with pytest.raises(ValueError):
        store.approve(mar.proposal.id, by="again")
