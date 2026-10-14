# Variance Detective

**An evidence-backed variance investigation agent for FP&A — tech-agnostic, LLM-agnostic, and never silently wrong.**

Point it at any planning or ERP system (SAP Analytics Cloud, Anaplan, Oracle EPM, OneStream, Workday Adaptive, a warehouse, or a CSV export) through MCP, ask *"why is gross margin below forecast?"*, and get back:

- a **variance tree** — the smallest set of intersections that explains the movement, found deterministically
- **rate vs volume** and **price / volume / mix** splits where the KPI allows
- a **narrative** in which every number is cited to an evidence id and machine-verified
- a **memory** of prior investigations, so recurring explanations are called out as recurring
- a **Plan PR** — a draft forecast adjustment a human approves before anything is written back
- an **HTML / Markdown / JSON report** you can hand to a CFO

```
request ─► connector (MCP / CSV) ─► canonical semantic model ─► variance tree (pandas, deterministic)
        ─► memory recall ─► narrative (Anthropic | Bedrock | Azure OpenAI | OpenAI-compatible | offline)
        ─► claim verifier ─► Plan PR draft ─► remember ─► reports
```

## Quick start (no API keys needed)

```bash
git clone <this repo> && cd variance-detective
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

vd demo --open          # Feb seeds memory, March finds the recurring store; opens the HTML report
vd --help
```

The demo runs fully **offline** with the template narrator. Add a model when you want richer prose:

```bash
# Anthropic
pip install -e ".[anthropic]" && export ANTHROPIC_API_KEY=...
vd demo --provider anthropic --model claude-sonnet-4-5

# Amazon Bedrock (uses your AWS credential chain / IAM role)
pip install -e ".[bedrock]" && export AWS_REGION=eu-west-2
vd demo --provider bedrock --model anthropic.claude-sonnet-4-5-20250929-v1:0

# Azure OpenAI
pip install -e ".[azure]" && export AZURE_OPENAI_ENDPOINT=https://<res>.openai.azure.com AZURE_OPENAI_API_KEY=...
vd demo --provider azure_openai --model <deployment-name>

# Anything OpenAI-compatible (OpenAI, Ollama, vLLM, Groq)
pip install -e ".[openai]" && export OPENAI_BASE_URL=http://localhost:11434/v1 OPENAI_API_KEY=ollama
vd demo --provider openai --model llama3.1
```

## Run a real investigation

```bash
vd investigate --kpi gross_margin --period 2026-03 --source sac            # SAC via SAC-MCP
vd investigate --kpi net_sales --period 2026-03 --compare Actual --compare-period 2026-02 --scope region=South
vd investigate --kpi gross_margin --period 2026-03 --source demo --drill region,store --open
```

Reports land in `workspace/reports/`, proposals in `workspace/proposals/`, memory in `workspace/memory.sqlite`.

```bash
vd sources list / vd sources test sac       # connectivity + tool discovery for MCP sources
vd memory list / vd memory clear
vd pr list / vd pr show <id> / vd pr approve <id> --by "name" / vd pr apply <id>
vd config show
```

## Connect your own system (no code)

1. **Describe its vocabulary** in `config/semantic_model.yaml` under `sources:` — which source column is `time`, `version`, `region`…, which columns are `net_sales`, `cogs`…, and how members translate (`Actual → public.Actual`).
2. **Register the source** in `config/sources.yaml` — the MCP transport (stdio / Streamable HTTP / SSE) and the `operations` map that names the server's tools and shapes their arguments with placeholders (`{filters}`, `{measures}`, `{dimensions}`, `{filter_first:Version}`).
3. `vd sources test <name>` then `vd investigate … --source <name>`.

Everything downstream — analysis, memory, prompts, reports — speaks only the canonical names, so a second system is a second mapping, not a second codebase.

## Design principles

| Principle | What it means in the code |
|---|---|
| **Deterministic math** | Every number comes from pandas (`analysis/`). The model never computes. |
| **Evidence first** | Every step writes to the evidence ledger (`evidence.py`). The narrative cites ids; `agent/verifier.py` rejects numbers that don't trace back and flags them in the report rather than hiding them. |
| **Memory** | `memory/store.py` (SQLite, stdlib) remembers findings per KPI × node × period and surfaces recurrence. |
| **Never write silently** | `writeback/plan_pr.py` drafts a change proposal; `vd pr approve` records who signed off; `vd pr apply` pushes to a *draft* version through the connector. |
| **Provider-agnostic** | `llm/providers.py` — one small class per provider behind a single `complete()` method. Offline fallback always available. |
| **Tech-agnostic** | `semantic/` canonical model + `connectors/mcp_connector.py` generic operation map. |

## Project layout

```
config/              agent.yaml · semantic_model.yaml · sources.yaml
src/variance_detective/
  agent/             orchestrator · narrators (template + LLM) · prompts · verifier · payload
  analysis/          decomposition (variance tree) · pvm (rate/volume, price/volume/mix) · format
  connectors/        base contract · csv · generic MCP · registry
  llm/               provider interface · anthropic · bedrock · azure openai · openai-compatible · offline
  memory/            sqlite store
  reporting/         html (self-contained, light/dark, inline SVG) · markdown · json
  semantic/          canonical model · mapper
  writeback/         Plan PR proposals
  evidence.py        the ledger
  cli.py             `vd`
demo/                synthetic retailer generator + data
docs/                architecture.md · deployment-handbook.html
tests/               19 tests incl. a live MCP round-trip through a fake server
```

## Tests

```bash
pytest            # identities, planted-story recovery, verifier, MCP round-trip, end-to-end, LLM plumbing
ruff check src tests demo
```

## Roadmap (the agent family)

Variance Detective is the first of a set of agents that share the same spine (connectors → semantic model → evidence → memory → Plan PR):

- **Forecast Integrity** — bias and sandbagging scoring per submitter from version history
- **Reconciler** — "which number is right?" across ERP / EPM / BI
- **Cycle Operator** — budget-season PMO: submissions, validation, chasing
- **Model Guardian** — model documentation, change impact, regression tests

See `docs/architecture.md` for how they compose.

## Licence

Apache-2.0
