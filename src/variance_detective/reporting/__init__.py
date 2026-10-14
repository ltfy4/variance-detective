from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ..config import AppConfig

if TYPE_CHECKING:  # pragma: no cover
    from ..agent.orchestrator import InvestigationResult


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()


def write_reports(result: InvestigationResult, cfg: AppConfig) -> dict[str, Path]:
    out_dir = cfg.resolve(cfg.reporting.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{_slug(result.tree.kpi.name)}-{_slug(result.request.period)}-{result.id.split('-')[-1]}"
    paths: dict[str, Path] = {}
    if "json" in cfg.reporting.formats:
        p = out_dir / f"{stem}.json"
        p.write_text(json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8")
        paths["json"] = p
    if "markdown" in cfg.reporting.formats:
        from .markdown_report import render_markdown

        p = out_dir / f"{stem}.md"
        p.write_text(render_markdown(result, cfg), encoding="utf-8")
        paths["markdown"] = p
    if "html" in cfg.reporting.formats:
        from .html_report import render_html

        p = out_dir / f"{stem}.html"
        p.write_text(render_html(result, cfg), encoding="utf-8")
        paths["html"] = p
    return paths
