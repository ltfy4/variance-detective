"""LLM narrator plumbing with a scripted provider: valid JSON, one bad answer then good, total failure → fallback."""
from __future__ import annotations

import json

from variance_detective.agent import InvestigationRequest, Investigator
from variance_detective.agent.narrators import LLMNarrator
from variance_detective.config import load_config
from variance_detective.llm.base import LLMResponse, extract_json


class ScriptedProvider:
    name = "scripted"
    model = "scripted-1"

    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def complete(self, system, user, *, json_mode=True):
        self.calls.append((system, user))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return LLMResponse(text=a, provider=self.name, model=self.model, input_tokens=10, output_tokens=5)


GOOD = json.dumps({
    "headline": "Gross margin below forecast",
    "summary": "Rate erosion in South Womenswear stores.",
    "key_findings": [{"statement": "Gross margin was below forecast.", "evidence_ids": ["E2"]}],
    "root_causes": [],
    "recommended_actions": ["Review markdown policy."],
    "proposed_adjustments": [],
    "open_questions": [],
    "confidence": "high",
})


def test_extract_json_handles_fences_and_prose():
    assert extract_json("Here you go:\n```json\n{\"a\": 1}\n```\nthanks")["a"] == 1
    assert extract_json("{\"b\": 2}")["b"] == 2


def test_llm_path_with_scripted_provider(project):
    cfg = load_config(project / "config" / "agent.yaml")
    inv = Investigator(cfg)
    provider = ScriptedProvider(["not json at all", GOOD])  # first answer invalid → retry with the error → good
    inv.narrator = LLMNarrator(provider)
    r = inv.run(InvestigationRequest(kpi="gross_margin", period="2026-03", source="demo"), remember=False)
    assert r.llm_meta["attempts"] == 2 and "fallback" not in r.llm_meta
    assert r.narrative.headline == "Gross margin below forecast"
    assert r.verification.ok
    assert "rejected" in provider.calls[1][1]
    # the model saw display strings and evidence ids, never raw frames
    assert '"display"' in provider.calls[0][1] and '"E2"' in provider.calls[0][1]


def test_llm_failure_falls_back_to_template(project):
    cfg = load_config(project / "config" / "agent.yaml")
    inv = Investigator(cfg)
    inv.narrator = LLMNarrator(ScriptedProvider([RuntimeError("quota exceeded")]))
    r = inv.run(InvestigationRequest(kpi="gross_margin", period="2026-03", source="demo"), remember=False)
    assert r.llm_meta.get("fallback") == "template" and "quota" in r.llm_meta["error"]
    assert r.warnings and r.verification.ok
