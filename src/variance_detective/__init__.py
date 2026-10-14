"""Variance Detective — an evidence-backed variance investigation agent for FP&A.

Design principles (see docs/architecture.md):

1. **Tech-agnostic.** Data comes in through *connectors* (generic MCP, CSV, ...) and is
   normalised into a canonical finance semantic model before anything else touches it.
2. **Deterministic math.** Every number is computed in pandas, never by a language model.
3. **Evidence first.** Every computation is logged in an evidence ledger; the narrative may
   only cite evidence ids, and a claim verifier rejects numbers that do not trace back.
4. **Memory.** Findings are remembered per KPI and node so recurring explanations are detected.
5. **Never write silently.** Write-back is a *Plan PR*: a draft change proposal that a human
   approves before anything is pushed to the planning system.
6. **Provider-agnostic LLM.** Anthropic, Amazon Bedrock, Azure OpenAI, any OpenAI-compatible
   endpoint — or fully offline with a template narrator.
"""

__version__ = "0.1.0"
