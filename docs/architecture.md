# Architecture

## 1. The problem this design solves

Every planning vendor now ships a copilot *inside* its own product. The pain that finance teams
actually report (2026 FP&A Impact Report: data quality 58 %, integration 51 % partial, forecast
variance > 6 % for half of respondents) lives *between* products: ERP vs EPM vs BI, forecast vs
actual, this month's explanation vs last month's.

Variance Detective is built for that seam. Three decisions follow from it:

1. **A canonical semantic model** sits between every source and every consumer.
2. **The language model never computes.** It explains tables that pandas produced, and it may only
   cite evidence ids. A verifier checks it.
3. **Writes are proposals, not actions.**

## 2. Layers

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│  CLI / API           vd investigate · vd demo · vd pr · (FastAPI wrapper trivial)  │
├───────────────────────────────────────────────────────────────────────────────────┤
│  Agent               orchestrator ─ narrators (template | LLM) ─ verifier ─ payload│
├───────────────────────────────────────────────────────────────────────────────────┤
│  Skills (deterministic)   decomposition · rate/volume · price/volume/mix · format  │
├───────────────────────────────────────────────────────────────────────────────────┤
│  State               evidence ledger · memory (SQLite) · Plan PR store (JSON)      │
├───────────────────────────────────────────────────────────────────────────────────┤
│  Semantic model      canonical dims/measures/KPIs · per-source mappings            │
├───────────────────────────────────────────────────────────────────────────────────┤
│  Connectors          generic MCP (stdio / HTTP / SSE) · CSV/Parquet · (yours)      │
├───────────────────────────────────────────────────────────────────────────────────┤
│  LLM providers       Anthropic · Bedrock Converse · Azure OpenAI · OpenAI-compat   │
└───────────────────────────────────────────────────────────────────────────────────┘
```

Dependencies point downward only. The agent never imports a connector class; the analysis layer
never sees a source column name; the reporting layer never calls a model.

## 3. Data flow of one investigation

| Step | Module | Output | Evidence |
|---|---|---|---|
| 1 Fetch | `connectors.*` | canonical frame: dims + `version` + measures | `E1` query, rows, timings |
| 2 Tree | `analysis.decomposition` | `VarianceTree` | headline, one pivot per node, offsets |
| 3 Splits | `analysis.pvm` | rate/volume, PVM per node | one item per split |
| 4 Recall | `memory.store` | `Recurrence` on nodes | one `memory` item per hit |
| 5 Narrate | `agent.narrators` | `Narrative` (pydantic) | — (consumes ids) |
| 6 Verify | `agent.verifier` | `VerificationReport`, per-claim flags | — |
| 7 Plan PR | `writeback.plan_pr` | `ChangeProposal` JSON (draft) | cites ids |
| 8 Remember | `memory.store` | rows per node | — |
| 9 Report | `reporting.*` | HTML / MD / JSON | renders ledger |

### 3.1 How a node picks its drill dimension

For each candidate dimension not already on the path, compute each member's contribution to the
node's variance. Score = number of same-sign members needed to reach `coverage_target` (80 %);
tiebreak = Herfindahl concentration. The dimension needing the fewest members wins. Children are
the same-sign members up to coverage (max 5, each ≥ 5 % of parent). Opposite-sign members above
10 % are recorded as **offsets** — they are what makes "the net number" understate a problem.

Recursion stops at `max_depth`, at immateriality, or when no dimension has ≥ 2 members.

### 3.2 Exact identities used

- Rate/volume: `ΔKPI = Δdriver × rate₀ + Δrate × driver₁`
- PVM: `price = Σ(p1ᵢ−p0ᵢ)q1ᵢ`, `volume = (Q1−Q0)·P̄0`, `mix = Σ q1ᵢ p0ᵢ − Q1·P̄0`; sum = ΔV exactly.

Both are unit-tested as identities, not as examples.

### 3.3 Why the verifier is strict

Finance will forgive a dull sentence; it will not forgive an invented number. The verifier parses
every number in every claim (`-£412.3k`, `-1.6pts`, `40.4%`, `16`), derives the tolerance from how
it was written, and checks it against the numeric *and textual* values of the cited evidence.
Failures are shown as ⚠ with the reason, never dropped. The template narrator is held to the same
standard, which is why it is a trustworthy fallback.

## 4. Tech-agnosticism in practice

| Concern | Where it lives | Changing systems means |
|---|---|---|
| Column names | `semantic_model.yaml → sources.<x>.dimensions/measures` | edit YAML |
| Member ids | `… sources.<x>.members` | edit YAML |
| Tool names / argument shapes | `sources.yaml → operations` | edit YAML |
| Transport & auth | `sources.yaml` (+ env vars) | edit YAML |
| A system with an unusual API | `connectors/<new>.py` implementing `_read_source` | ~40 lines |

The MCP connector enforces filters locally after the call, so a server that ignores a filter
still yields correct numbers (at the cost of transfer).

## 5. LLM-agnosticism in practice

`LLMProvider.complete(system, user) -> LLMResponse` is the entire contract. Bedrock uses the
Converse API so one class covers Claude, Nova, Llama and Mistral on AWS; Azure OpenAI and any
OpenAI-compatible endpoint share one body. Secrets never touch YAML. The narrator retries once on
schema failure (sending the validation error back) and then falls back to the template narrator
with a visible warning in the report.

## 6. Governance model

- **Read**: service identity with read-only scope on the planning model.
- **Propose**: Plan PR JSON on disk (or in your ticketing system).
- **Approve**: `vd pr approve --by` records identity and timestamp; the proposal is immutable
  afterwards except for status.
- **Apply**: only to a draft/private version named in `writeback.target_version`; the connector's
  `write_draft` operation should be pointed at the system's own draft mechanism (SAC private
  version, Anaplan scenario, Oracle sandbox).
- **Audit**: the JSON report is a complete record — request, tree, every evidence table, narrative
  with verification flags, model and token usage, timings.

## 7. Scaling and operations

- Single investigation on a 1M-row extract: fetch is the bottleneck; analysis is seconds.
- Batch: loop over KPIs × scopes with `Investigator.run_async` under one event loop.
- Memory: SQLite is fine to ~100k findings; swap `MemoryStore` for Postgres by re-implementing
  four methods.
- Serving: wrap `Investigator` in FastAPI (`POST /investigate` → JSON report) and schedule with
  Airflow / Step Functions / Azure Data Factory; see the deployment handbook.

## 8. The agent family — how the next agents plug in

Every agent reuses the spine and adds one analysis module and one narrator:

| Agent | Adds | Reuses |
|---|---|---|
| Forecast Integrity | bias scoring over version history | connectors, semantic, evidence, verifier, reports |
| Reconciler | cross-source diff classifier | + two sources at once |
| Cycle Operator | submission status + nudges (Slack/Teams MCP) | memory, Plan PR |
| Model Guardian | metadata diff, impact graph, regression runner | MCP describe ops |

They can run independently or hand each other evidence ids: a Reconciler finding ("EPM COGS
excludes late journal 4711") can be cited by the Variance Detective narrative as `R-E7`, because
the ledger is just ids and tables.
