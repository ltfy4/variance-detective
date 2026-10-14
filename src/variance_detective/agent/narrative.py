"""The narrative contract between the model and the rest of the system.

Whatever produces the narrative (an LLM or the offline template) must return this structure.
Every statement carries the evidence ids it rests on; the verifier enforces it.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Claim(BaseModel):
    statement: str
    evidence_ids: list[str] = Field(default_factory=list)
    # filled by the verifier
    verified: bool | None = None
    verification_notes: list[str] = Field(default_factory=list)


class Adjustment(BaseModel):
    path: dict[str, str] = Field(default_factory=dict, description="Canonical dimension → member, e.g. {'region': 'South', 'category': 'Womenswear'}")
    measure: str = Field(description="Canonical measure to adjust, e.g. 'cogs' or 'net_sales'")
    proposed_delta: float = Field(description="Signed change to apply to the target version for this intersection")
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)


class Narrative(BaseModel):
    headline: str = Field(description="One sentence a CFO reads first")
    summary: str = Field(description="Three to five sentences: what moved, where, why, what to do")
    key_findings: list[Claim]
    root_causes: list[Claim] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    proposed_adjustments: list[Adjustment] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "medium"

    def all_claims(self) -> list[Claim]:
        return [*self.key_findings, *self.root_causes]

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


NARRATIVE_JSON_SCHEMA = Narrative.model_json_schema()
