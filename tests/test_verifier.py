from __future__ import annotations

from variance_detective.agent.narrative import Claim, Narrative
from variance_detective.agent.verifier import parse_numbers, verify_narrative
from variance_detective.evidence import EvidenceLedger


def test_parse_numbers_formats():
    nums = parse_numbers("Gross margin -£412.3k (-3.9%), rate -1.6pts, net sales £25.4M, 16 stores, in 2026")
    texts = [n.text for n in nums]
    assert "-£412.3k" in texts and "-3.9%" in texts and "-1.6pts" in texts and "£25.4M" in texts and "16" in texts
    assert all(t != "2026" for t in texts)  # years ignored
    by = {n.text: n for n in nums}
    assert by["-£412.3k"].value == 412_300 and by["-£412.3k"].tolerance >= 50
    assert by["-1.6pts"].value == 0.016 and by["-3.9%"].kind == "percent"


def _ledger() -> EvidenceLedger:
    led = EvidenceLedger()
    led.add("headline", "GM", "x", values={"actual": 10_412_345.0, "comparison": 10_830_100.0, "variance": -417_755.0, "variance_pct": -0.0386})
    led.add("rate_volume", "rv", "x", values={"rate_delta_pts": -0.0163, "rate_effect": -425_000.0})
    led.add("memory", "prior", "x", table=[{"period": "2026-02", "explanation": "S07: -£84k rate erosion (-6.8pts)"}])
    return led


def test_supported_claims_pass():
    n = Narrative(headline="h", summary="s", key_findings=[
        Claim(statement="GM was £10.4M vs £10.8M, -£418k (-3.9%).", evidence_ids=["E1"]),
        Claim(statement="Rate effect -£425k (-1.6pts).", evidence_ids=["E2"]),
        Claim(statement="Last time: “S07: -£84k rate erosion (-6.8pts)”.", evidence_ids=["E3"]),
    ])
    rep = verify_narrative(n, _ledger())
    assert rep.ok, rep.to_dict()


def test_unsupported_number_and_unknown_evidence_are_flagged():
    n = Narrative(headline="h", summary="s", key_findings=[
        Claim(statement="GM fell by -£999k.", evidence_ids=["E1"]),
        Claim(statement="Rate effect -£425k.", evidence_ids=["E9"]),
        Claim(statement="Something with no citation 12.5%.", evidence_ids=[]),
    ])
    rep = verify_narrative(n, _ledger())
    assert not rep.ok
    assert rep.verified_claims == 0
    assert any("-£999k not found" in s for s in rep.unsupported_numbers)
    assert any("E9" in s for s in rep.unknown_evidence)
    assert n.key_findings[1].verified is False and "not in the cited ids" in n.key_findings[1].verification_notes[-1]
