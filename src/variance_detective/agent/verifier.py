"""Claim verifier.

Parses every number in every claim and checks it exists in the cited evidence (within the
rounding tolerance implied by how it was written: "1.6M" tolerates ±50k, "40.4%" ±0.05pt).
Claims citing unknown evidence ids, or containing numbers that appear nowhere, are flagged —
never silently dropped — so the reviewer sees exactly what the model could not back up.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..evidence import EvidenceLedger
from .narrative import Claim, Narrative

# e.g. -£412.3k  +1.6M  40.4%  -1.6pts  12,345  0.8bn  3 stores
_NUM = re.compile(r"(?<![A-Za-z0-9_])([+\-−]?)[£$€]?\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?\s?(bn|M|k|%|pts|pt|x)?(?![A-Za-z0-9_])", re.IGNORECASE)
_SCALE = {"bn": 1e9, "m": 1e6, "k": 1e3}


@dataclass
class ParsedNumber:
    text: str
    value: float  # absolute, in base units
    tolerance: float
    kind: str  # amount | percent | pts | count


def parse_numbers(text: str) -> list[ParsedNumber]:
    out: list[ParsedNumber] = []
    for m in _NUM.finditer(text):
        whole, frac, suffix = m.group(2).replace(",", ""), m.group(3), (m.group(4) or "").lower()
        raw = float(f"{whole}.{frac}" if frac else whole)
        decimals = len(frac) if frac else 0
        if suffix in _SCALE:
            value = raw * _SCALE[suffix]
            tol = 0.5 * 10 ** (-decimals) * _SCALE[suffix]
            kind = "amount"
        elif suffix == "%":
            value, tol, kind = raw / 100, 0.5 * 10 ** (-decimals) / 100, "percent"
        elif suffix in ("pts", "pt"):
            value, tol, kind = raw / 100, 0.5 * 10 ** (-decimals) / 100, "pts"
        elif suffix == "x":
            continue
        else:
            value, tol, kind = raw, 0.5 * 10 ** (-decimals), "count"
        # years and tiny counts are not claims about the data
        if kind == "count" and (1900 <= value <= 2100 or value < 10):
            continue
        out.append(ParsedNumber(m.group(0).strip(), value, max(tol, abs(value) * 0.0051), kind))
    return out


def _evidence_pool(e) -> list[float]:
    """Numeric values in the evidence, plus numbers written inside its text fields (e.g. a remembered
    explanation such as '-£84k rate erosion' stored by a prior investigation)."""
    pool = list(e.numbers())
    texts: list[str] = []

    def walk(v) -> None:
        if isinstance(v, str):
            texts.append(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)

    walk(e.values)
    walk(e.table)
    for t in texts:
        pool.extend(p.value for p in parse_numbers(t))
        pool.extend(p.value * 100 for p in parse_numbers(t) if p.kind in ("percent", "pts"))
    return pool


def _matches(n: ParsedNumber, pool: list[float]) -> bool:
    for v in pool:
        av = abs(v)
        if abs(av - n.value) <= n.tolerance:
            return True
        if n.kind in ("percent", "pts") and abs(av - n.value * 100) <= n.tolerance * 100:  # evidence stored as 40.4 not 0.404
            return True
    return False


@dataclass
class VerificationReport:
    total_claims: int = 0
    verified_claims: int = 0
    unknown_evidence: list[str] = field(default_factory=list)
    unsupported_numbers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.total_claims > 0 and self.verified_claims == self.total_claims

    @property
    def score(self) -> float:
        return self.verified_claims / self.total_claims if self.total_claims else 0.0

    def to_dict(self) -> dict:
        return {"total_claims": self.total_claims, "verified_claims": self.verified_claims, "score": round(self.score, 3), "ok": self.ok, "unknown_evidence": self.unknown_evidence, "unsupported_numbers": self.unsupported_numbers, "notes": self.notes}


def verify_claim(claim: Claim, ledger: EvidenceLedger) -> Claim:
    notes: list[str] = []
    cited = [ledger.get(i) for i in claim.evidence_ids]
    unknown = [i for i, e in zip(claim.evidence_ids, cited) if e is None]
    if not claim.evidence_ids:
        notes.append("no evidence cited")
    for u in unknown:
        notes.append(f"unknown evidence id {u}")
    pool = [n for e in cited if e for n in _evidence_pool(e)]
    pool_all = [n for e in ledger for n in _evidence_pool(e)]
    for num in parse_numbers(claim.statement):
        if _matches(num, pool):
            continue
        if _matches(num, pool_all):
            notes.append(f"{num.text} exists in evidence but not in the cited ids")
        else:
            notes.append(f"{num.text} not found in evidence")
    claim.verification_notes = notes
    claim.verified = not notes
    return claim


def verify_narrative(narrative: Narrative, ledger: EvidenceLedger) -> VerificationReport:
    report = VerificationReport()
    for claim in narrative.all_claims():
        verify_claim(claim, ledger)
        report.total_claims += 1
        if claim.verified:
            report.verified_claims += 1
        for n in claim.verification_notes:
            if n.startswith("unknown evidence"):
                report.unknown_evidence.append(n)
            elif "not found" in n or "not in the cited" in n:
                report.unsupported_numbers.append(f"{n} — in: “{claim.statement[:80]}”")
            else:
                report.notes.append(f"{n} — in: “{claim.statement[:80]}”")
    for adj in narrative.proposed_adjustments:
        bad = [i for i in adj.evidence_ids if ledger.get(i) is None]
        if bad:
            report.unknown_evidence.extend(f"unknown evidence id {b} (adjustment)" for b in bad)
    return report
