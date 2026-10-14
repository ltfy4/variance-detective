"""``vd`` — the Variance Detective command line."""
from __future__ import annotations

import asyncio
import json
import os
import webbrowser
from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .config import AppConfig, load_config

app = typer.Typer(help="Variance Detective — evidence-backed variance investigation for FP&A.", no_args_is_help=False, add_completion=False, invoke_without_command=True)
sources_app = typer.Typer(help="Inspect and test data sources.")
memory_app = typer.Typer(help="Investigation memory.")
pr_app = typer.Typer(help="Plan PRs — proposed forecast changes awaiting review.")
config_app = typer.Typer(help="Configuration.")
app.add_typer(sources_app, name="sources")
app.add_typer(memory_app, name="memory")
app.add_typer(pr_app, name="pr")
app.add_typer(config_app, name="config")

console = Console()
REPO_ROOT = Path(__file__).resolve().parents[2]


def _cfg(config: str | None, provider: str | None = None, model: str | None = None) -> AppConfig:
    path = config or os.environ.get("VD_CONFIG")
    if not path:
        for cand in (Path("config/agent.yaml"), REPO_ROOT / "config" / "agent.yaml"):
            if cand.exists():
                path = str(cand)
                break
    cfg = load_config(path)
    if provider:
        cfg.llm.provider = provider  # type: ignore[assignment]
    if model:
        cfg.llm.model = model
    return cfg


def _parse_scope(scope: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s in scope:
        if "=" not in s:
            raise typer.BadParameter(f"--scope expects dim=member[,member]; got '{s}'")
        k, v = s.split("=", 1)
        out[k.strip()] = [m.strip() for m in v.split(",") if m.strip()]
    return out


def _print_result(result, cfg: AppConfig) -> None:
    from .analysis.format import fmt_pct, fmt_value

    kpi = result.tree.kpi
    v = lambda x, s=False: fmt_value(x, kpi.unit, cfg.reporting.currency_symbol, signed=s)
    badge = f"[green]✓ {result.verification.verified_claims}/{result.verification.total_claims} claims verified[/green]" if result.verification.ok else f"[yellow]⚠ {result.verification.verified_claims}/{result.verification.total_claims} claims verified[/yellow]"
    console.print(Panel.fit(f"[bold]{result.narrative.headline}[/bold]\n\n{result.narrative.summary}", title=f"{result.id} · {kpi.label} {result.request.period}", subtitle=badge, border_style="blue"))
    t = Table(box=box.SIMPLE_HEAD, show_edge=False)
    t.add_column("Node")
    t.add_column("Variance", justify="right")
    t.add_column("Share", justify="right")
    t.add_column("Notes")
    for n in result.tree.nodes():
        notes = []
        if n.rate_volume:
            notes.append(f"rate {v(n.rate_volume.rate_effect, True)} / vol {v(n.rate_volume.volume_effect, True)}")
        if n.recurrence:
            notes.append(f"[yellow]recurring ×{n.recurrence.count}[/yellow]")
        if n.offsets:
            notes.append("offsets: " + ", ".join(o.member for o in n.offsets[:2]))
        color = "red" if (n.variance < 0) == (kpi.direction == "higher_is_better") else "blue"
        t.add_row("  " * n.depth + n.label, f"[{color}]{v(n.variance, True)}[/{color}]", fmt_pct(n.share_of_root, signed=False), " · ".join(notes))
    console.print(t)
    if result.proposal:
        console.print(f"[bold]Plan PR[/bold] {result.proposal.id} drafted · {len(result.proposal.lines)} line(s) · total Δ {v(result.proposal.total_delta, True)} → approve with [cyan]vd pr approve {result.proposal.id} --by <name>[/cyan]")
    for w in result.warnings:
        console.print(f"[yellow]⚠ {w}[/yellow]")
    for fmt, p in result.report_paths.items():
        console.print(f"[dim]{fmt:9}[/dim] {p}")


@app.callback()
def _root(ctx: typer.Context, version: bool = typer.Option(False, "--version", help="Show version and exit")):
    if version:
        console.print(f"variance-detective {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


@app.command()
def investigate(
    kpi: str = typer.Option(..., "--kpi", "-k", help="KPI name from semantic_model.yaml, e.g. gross_margin"),
    period: str = typer.Option(..., "--period", "-p", help="Period member, e.g. 2026-03"),
    source: str = typer.Option("demo", "--source", "-s", help="Source name from sources.yaml"),
    actual: str = typer.Option("Actual", help="Canonical version holding actuals"),
    compare: str = typer.Option("Forecast", help="Canonical version to compare against"),
    compare_period: str | None = typer.Option(None, help="Compare against a different period (prior month/year)"),
    scope: list[str] = typer.Option([], "--scope", help="Restrict the investigation: dim=member[,member]. Repeatable."),
    drill: str | None = typer.Option(None, help="Comma-separated drill dimensions (overrides KPI default)"),
    provider: str | None = typer.Option(None, help="LLM provider override: offline|anthropic|bedrock|azure_openai|openai"),
    model: str | None = typer.Option(None, help="LLM model/deployment override"),
    config: str | None = typer.Option(None, "--config", "-c", help="Path to agent.yaml"),
    no_memory: bool = typer.Option(False, help="Do not store this investigation in memory"),
    open_report: bool = typer.Option(False, "--open", help="Open the HTML report when done"),
):
    """Run a variance investigation and write HTML / Markdown / JSON reports."""
    from .agent import InvestigationRequest, Investigator

    cfg = _cfg(config, provider, model)
    req = InvestigationRequest(kpi=kpi, period=period, source=source, actual_version=actual, compare_version=compare, compare_period=compare_period, scope=_parse_scope(scope), drill_dimensions=drill.split(",") if drill else None)
    with console.status(f"Investigating {kpi} for {period} from '{source}' …"):
        result = Investigator(cfg).run(req, remember=not no_memory)
    _print_result(result, cfg)
    if open_report and "html" in result.report_paths:
        webbrowser.open(result.report_paths["html"].resolve().as_uri())


@app.command()
def demo(
    provider: str | None = typer.Option(None, help="LLM provider (default: offline — no keys needed)"),
    model: str | None = typer.Option(None),
    config: str | None = typer.Option(None, "--config", "-c"),
    open_report: bool = typer.Option(False, "--open", help="Open the March HTML report when done"),
    regenerate: bool = typer.Option(False, help="Regenerate the synthetic dataset"),
):
    """End-to-end demo on the synthetic retailer: February (seeds memory) then March (recurring finding)."""
    from .agent import InvestigationRequest, Investigator

    cfg = _cfg(config, provider, model)
    data = cfg.resolve("demo/data/facts.csv")
    if regenerate or not data.exists():
        import importlib.util

        spec = importlib.util.spec_from_file_location("gen", cfg.resolve("demo/generate_data.py"))
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        mod.main()
    inv = Investigator(cfg)
    if inv.memory:
        inv.memory.clear()
    console.rule("[bold]February 2026 — seeding memory")
    feb = inv.run(InvestigationRequest(kpi="gross_margin", period="2026-02", source="demo"))
    _print_result(feb, cfg)
    console.rule("[bold]March 2026 — the investigation")
    mar = inv.run(InvestigationRequest(kpi="gross_margin", period="2026-03", source="demo"))
    _print_result(mar, cfg)
    if open_report and "html" in mar.report_paths:
        webbrowser.open(mar.report_paths["html"].resolve().as_uri())


# ---- sources -------------------------------------------------------------------------

@sources_app.command("list")
def sources_list(config: str | None = typer.Option(None, "--config", "-c")):
    cfg = _cfg(config)
    t = Table("name", "type", "label", "semantics", "write_draft", box=box.SIMPLE_HEAD)
    for name, s in cfg.sources.items():
        t.add_row(name, s.type, s.label or "", s.semantics, "yes" if s.capabilities.get("write_draft") else "no")
    console.print(t)


@sources_app.command("test")
def sources_test(name: str, config: str | None = typer.Option(None, "--config", "-c")):
    """Connect to a source and describe it (lists MCP tools for MCP sources)."""
    from .connectors import build_connector
    from .semantic import load_semantic_model

    cfg = _cfg(config)
    sem = load_semantic_model(cfg.resolve(cfg.semantic_model))
    conn = build_connector(name, cfg, sem)
    ok, msg = asyncio.run(conn.test_connection())
    console.print(("[green]OK[/green] " if ok else "[red]FAILED[/red] ") + msg)
    if ok:
        d = asyncio.run(conn.describe())
        if d.extra:
            console.print_json(json.dumps(d.extra, default=str)[:4000])
    raise typer.Exit(0 if ok else 1)


# ---- memory --------------------------------------------------------------------------

@memory_app.command("list")
def memory_list(config: str | None = typer.Option(None, "--config", "-c")):
    from .memory import MemoryStore

    cfg = _cfg(config)
    store = MemoryStore(cfg.resolve(cfg.memory.path))
    t = Table("id", "kpi", "period", "versions", "variance", "headline", box=box.SIMPLE_HEAD)
    for i in store.list_investigations():
        t.add_row(i["id"], i["kpi"], i["period"], f"{i['actual_version']} vs {i['compare_version']}", f"{i['variance']:,.0f}", (i["headline"] or "")[:80])
    console.print(t)


@memory_app.command("clear")
def memory_clear(config: str | None = typer.Option(None, "--config", "-c"), yes: bool = typer.Option(False, "--yes", "-y")):
    from .memory import MemoryStore

    cfg = _cfg(config)
    if not yes and not typer.confirm("Delete all remembered investigations?"):
        raise typer.Abort()
    MemoryStore(cfg.resolve(cfg.memory.path)).clear()
    console.print("memory cleared")


# ---- Plan PRs ------------------------------------------------------------------------

def _store(config: str | None):
    from .writeback import ProposalStore

    cfg = _cfg(config)
    return cfg, ProposalStore(cfg.resolve(cfg.writeback.proposals_dir))


@pr_app.command("list")
def pr_list(config: str | None = typer.Option(None, "--config", "-c")):
    _, store = _store(config)
    t = Table("id", "status", "kpi", "period", "target", "lines", "total Δ", "title", box=box.SIMPLE_HEAD)
    for p in store.list():
        t.add_row(p.id, p.status, p.kpi, p.period, p.target_version, str(len(p.lines)), f"{p.total_delta:,.0f}", p.title)
    console.print(t)


@pr_app.command("show")
def pr_show(id: str, config: str | None = typer.Option(None, "--config", "-c")):
    _, store = _store(config)
    console.print_json(store.load(id).model_dump_json())


@pr_app.command("approve")
def pr_approve(id: str, by: str = typer.Option(..., help="Approver name / email"), comment: str = typer.Option("", help="Optional comment"), config: str | None = typer.Option(None, "--config", "-c")):
    _, store = _store(config)
    p = store.approve(id, by, comment)
    console.print(f"[green]approved[/green] {p.id} by {by}")


@pr_app.command("reject")
def pr_reject(id: str, by: str = typer.Option(...), comment: str = typer.Option(""), config: str | None = typer.Option(None, "--config", "-c")):
    _, store = _store(config)
    p = store.reject(id, by, comment)
    console.print(f"[red]rejected[/red] {p.id} by {by}")


@pr_app.command("apply")
def pr_apply(id: str, config: str | None = typer.Option(None, "--config", "-c")):
    """Push an approved proposal to the source's draft version via its write_draft operation."""
    from .connectors import build_connector
    from .semantic import load_semantic_model

    cfg, store = _store(config)
    p = store.load(id)
    sem = load_semantic_model(cfg.resolve(cfg.semantic_model))
    conn = build_connector(p.source, cfg, sem)
    if not conn.can_write_draft:
        console.print(f"[red]Source '{p.source}' has no write_draft capability configured.[/red]")
        raise typer.Exit(2)
    p = asyncio.run(store.apply(id, conn))
    console.print(f"[green]applied[/green] {p.id} → {p.source} / {p.target_version}")


# ---- config --------------------------------------------------------------------------

@config_app.command("show")
def config_show(config: str | None = typer.Option(None, "--config", "-c")):
    cfg = _cfg(config)
    console.print_json(cfg.model_dump_json(exclude={"sources"}, indent=2))
    console.print(f"sources: {', '.join(cfg.sources)}")


if __name__ == "__main__":  # pragma: no cover
    app()
