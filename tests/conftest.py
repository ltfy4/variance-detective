from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(scope="session")
def demo_frame() -> pd.DataFrame:
    """Canonical frame straight from the generator (no file I/O)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("gen", ROOT / "demo" / "generate_data.py")
    mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    df = mod.generate()
    return df.rename(columns={"period": "time"})


@pytest.fixture
def demo_facts_csv(tmp_path, demo_frame) -> Path:
    p = tmp_path / "facts.csv"
    demo_frame.rename(columns={"time": "period"}).to_csv(p, index=False)
    return p


@pytest.fixture
def project(tmp_path, demo_facts_csv) -> Path:
    """A throwaway project dir: real config + semantic model, demo CSV, isolated workspace."""
    import shutil

    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "semantic_model.yaml", tmp_path / "config" / "semantic_model.yaml")
    (tmp_path / "config" / "agent.yaml").write_text(
        "llm:\n  provider: offline\nanalysis:\n  max_depth: 4\nmemory:\n  path: workspace/memory.sqlite\n"
        "writeback:\n  mode: draft\nreporting:\n  output_dir: workspace/reports\n"
    )
    (tmp_path / "config" / "sources.yaml").write_text(
        f"sources:\n  demo:\n    type: csv\n    semantics: default\n    path: {demo_facts_csv}\n"
    )
    return tmp_path
