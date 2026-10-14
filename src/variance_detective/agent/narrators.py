"""Two narrators behind one interface.

* ``TemplateNarrator`` — deterministic prose from the tree. No model. Always available, always
  verifiable, and the fallback when a model misbehaves.
* ``LLMNarrator`` — asks the configured provider for a richer narrative, validates the JSON
  against the ``Narrative`` schema, retries once with the validation error, then falls back.
"""
from __future__ import annotations

from typing import Any, Protocol

from pydantic import ValidationError

from ..llm import LLMProvider, LLMResponse
from ..semantic import KPIDefinition
from .narrative import Adjustment, Claim, Narrative
from .prompts import build_system_prompt, build_user_prompt


class Narrator(Protocol):
    name: str

    def narrate(self, payload: dict[str, Any], kpi: KPIDefinition) -> tuple[Narrative, dict[str, Any]]: ...


class TemplateNarrator:
    name = "template"

    def narrate(self, payload: dict[str, Any], kpi: KPIDefinition) -> tuple[Narrative, dict[str, Any]]:
        root, nodes = payload["root"], payload["nodes"]
        rd = root["display"]
        period, cv = payload["period"], payload["compare_version"]
        adverse = (root["variance"] < 0) == (kpi.direction == "higher_is_better")
        tone = "below" if adverse else "above"

        findings: list[Claim] = [
            Claim(
                statement=f"{kpi.label} for {period} was {rd['actual']} against {rd['comparison']} {cv}, {rd['variance']} ({rd['variance_pct']}) — {tone} plan.",
                evidence_ids=root["evidence_ids"][:1],
            )
        ]
        if rv := root.get("rate_volume"):
            dv = rv["display"]
            findings.append(
                Claim(
                    statement=(
                        f"Of that, {dv['rate_effect']} is a rate effect (rate {dv['rate_actual']} vs {dv['rate_comparison']}, {dv['rate_delta']}) "
                        f"and {dv['volume_effect']} is a volume effect ({rv['driver']} {dv['driver_actual']} vs {dv['driver_comparison']})."
                    ),
                    evidence_ids=[_ev_of_kind(root, payload, "rate_volume")],
                )
            )
        if root.get("drill_dimension"):
            kids = [n for n in nodes if n["depth"] == 1]
            kid_txt = "; ".join(f"{k['label']} {k['display']['variance']} ({k['display']['share_of_parent']} of total)" for k in kids)
            findings.append(
                Claim(
                    statement=f"By {root['drill_dimension']}, {len(kids)} of {root['members_considered']} members explain {_pct(root['coverage'])} of the variance: {kid_txt}.",
                    evidence_ids=[_ev_of_kind(root, payload, "pivot")],
                )
            )
        for n in nodes:
            if n["depth"] >= 1 and n.get("drill_dimension") and n.get("children"):
                kids = [c for c in nodes if c["depth"] == n["depth"] + 1 and c["label"].startswith(n["label"])]
                kid_txt = "; ".join(f"{k['label'].split(' › ')[-1]} {k['display']['variance']}" for k in kids)
                findings.append(
                    Claim(
                        statement=f"Within {n['label']}, {n['drill_dimension']} concentrates it: {kid_txt} ({_pct(n['coverage'])} of the {n['display']['variance']}).",
                        evidence_ids=[_ev_of_kind(n, payload, "pivot")],
                    )
                )
        for n in [root, *nodes]:
            if n.get("offsets"):
                txt = ", ".join(f"{o['member']} {o['display']}" for o in n["offsets"][:3])
                findings.append(Claim(statement=f"Partly masked at {n['label']} by favourable movements: {txt}.", evidence_ids=[_ev_of_kind(n, payload, "offsets")]))
        if pvm := root.get("pvm"):
            dv = pvm["display"]
            findings.append(
                Claim(
                    statement=f"On {pvm['value_measure']}, price contributed {dv['price']}, volume {dv['volume']} and {pvm['dimension']} mix {dv['mix']} (total {dv['total']}).",
                    evidence_ids=[_ev_of_kind(root, payload, "pvm")],
                )
            )

        causes: list[Claim] = []
        actions: list[str] = []
        adjustments: list[Adjustment] = []
        leaves = [n for n in nodes if not n.get("children")]
        for n in sorted(leaves, key=lambda x: abs(x["variance"]), reverse=True)[:4]:
            rv = n.get("rate_volume")
            rec = n.get("recurrence")
            ev = [_ev_of_kind(n, payload, "rate_volume")] if rv else _parent_pivot(n, payload)
            if rv and abs(rv["rate_effect"]) > abs(rv["volume_effect"]):
                stmt = f"{n['label']}: {n['display']['variance']} is driven by rate erosion ({rv['display']['rate_effect']}, {rv['display']['rate_delta']}) rather than volume ({rv['display']['volume_effect']})."
            elif rv:
                stmt = f"{n['label']}: {n['display']['variance']} is mostly volume ({rv['display']['volume_effect']}); rate effect {rv['display']['rate_effect']}."
            else:
                stmt = f"{n['label']}: {n['display']['variance']} ({n['display']['share_of_root']} of the total variance)."
            if rec and rec["count"] > 0:
                stmt += f" This node also appeared in {rec['count']} prior investigation(s) ({', '.join(rec['prior_periods'])})."
                if rec.get("last_explanation"):
                    stmt += f" Last explanation: “{rec['last_explanation']}” — a recurring pattern should not be treated as one-off."
                ev = ev + [_ev_of_kind(n, payload, "memory")] if _ev_of_kind(n, payload, "memory") else ev
                actions.append(f"Re-baseline the {payload['compare_version']} rate for {n['label']}: the same intersection has driven the variance in {rec['count'] + 1} periods.")
                if rv and kpi.unit == "currency":
                    adjustments.append(
                        Adjustment(
                            path=n["path"],
                            measure=_adjust_measure(kpi),
                            proposed_delta=round(rv["rate_effect"] * _adjust_sign(kpi), 2),
                            rationale=f"Align {payload['compare_version']} with the observed rate at {n['label']} ({rv['display']['rate_delta']}), recurring across {rec['count'] + 1} periods.",
                            evidence_ids=[e for e in ev if e],
                        )
                    )
            else:
                actions.append(f"Confirm the driver behind {n['label']} with the budget owner before the next forecast cycle.")
            causes.append(Claim(statement=stmt, evidence_ids=[e for e in ev if e]))

        if any(n.get("offsets") for n in [root, *nodes]):
            actions.append("Separate favourable offsets from the underlying adverse trend in the commentary — the net figure understates the problem.")

        summary_bits = [findings[0].statement]
        if len(findings) > 1:
            summary_bits.append(findings[1].statement)
        if causes:
            summary_bits.append(causes[0].statement)
        narrative = Narrative(
            headline=f"{kpi.label} {rd['variance']} vs {cv} in {period}" + (f" — concentrated in {leaves[0]['label']}" if leaves else ""),
            summary=" ".join(summary_bits),
            key_findings=findings,
            root_causes=causes,
            recommended_actions=actions[:5],
            proposed_adjustments=adjustments,
            open_questions=[f"Is the movement in {leaves[0]['label']} operational (pricing/markdown/volume) or an accounting timing effect?"] if leaves else [],
            confidence="medium",
        )
        return narrative, {"narrator": self.name}


class LLMNarrator:
    name = "llm"

    def __init__(self, provider: LLMProvider, fallback: TemplateNarrator | None = None):
        self.provider = provider
        self.fallback = fallback or TemplateNarrator()

    def narrate(self, payload: dict[str, Any], kpi: KPIDefinition) -> tuple[Narrative, dict[str, Any]]:
        system = build_system_prompt({})
        user = build_user_prompt(payload)
        meta: dict[str, Any] = {"narrator": self.name, "provider": self.provider.name, "model": self.provider.model, "attempts": 0}
        last_error = ""
        for attempt in range(2):
            meta["attempts"] += 1
            prompt = user if not last_error else user + f"\n\nYour previous answer was rejected: {last_error}\nReturn corrected JSON only."
            try:
                resp: LLMResponse = self.provider.complete(system, prompt, json_mode=True)
                meta.update({"input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens, "latency_ms": resp.latency_ms})
                narrative = Narrative(**resp.json())
                return narrative, meta
            except (ValidationError, ValueError) as e:
                last_error = str(e)[:800]
            except Exception as e:  # noqa: BLE001 - network, auth, quota
                meta["error"] = f"{type(e).__name__}: {e}"
                break
        meta.setdefault("error", f"Model output failed schema validation: {last_error}")
        meta["fallback"] = "template"
        narrative, _ = self.fallback.narrate(payload, kpi)
        return narrative, meta


# ---- helpers ---------------------------------------------------------------------------

def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def _ev_of_kind(node: dict[str, Any], payload: dict[str, Any], kind: str) -> str:
    kinds = payload.get("_evidence_kinds", {})
    for eid in node.get("evidence_ids", []):
        if kinds.get(eid) == kind:
            return eid
    return ""


def _parent_pivot(node: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    """The pivot evidence on the parent is where a child's numbers live."""
    parent_label = " › ".join(node["label"].split(" › ")[:-1])
    for cand in [payload["root"], *payload["nodes"]]:
        if cand["label"] == (parent_label or "Total"):
            ev = _ev_of_kind(cand, payload, "pivot")
            return [ev] if ev else []
    return []


def _adjust_measure(kpi: KPIDefinition) -> str:
    """Which measure to move to shift the KPI. Convention: the last subtracted measure in the formula
    (e.g. 'cogs' in 'net_sales - cogs'), else the first measure."""
    if "-" in kpi.formula:
        return kpi.formula.split("-")[-1].strip()
    return kpi.measures[0]


def _adjust_sign(kpi: KPIDefinition) -> float:
    return -1.0 if "-" in kpi.formula else 1.0
