"""The evidence ledger.

Every computation the agent performs is recorded here with a stable id (``E1``, ``E2`` ...).
The narrative layer is only allowed to *cite* these ids, and the claim verifier checks that
every number in the narrative exists in the cited evidence. This is what makes the output
auditable: a reviewer can click any sentence and see the table it came from.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Evidence:
    id: str
    kind: str  # query | pivot | headline | rate_volume | pvm | memory | offsets
    title: str
    description: str
    table: list[dict[str, Any]] = field(default_factory=list)
    values: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    columns: list[str] = field(default_factory=list)

    def numbers(self) -> list[float]:
        out: list[float] = []

        def walk(v: Any) -> None:
            if isinstance(v, bool):
                return
            if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
                out.append(float(v))
            elif isinstance(v, dict):
                for x in v.values():
                    walk(x)
            elif isinstance(v, (list, tuple)):
                for x in v:
                    walk(x)

        walk(self.values)
        walk(self.table)
        return out

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EvidenceLedger:
    def __init__(self, rows_limit: int = 25):
        self._items: list[Evidence] = []
        self.rows_limit = rows_limit

    def add(
        self,
        kind: str,
        title: str,
        description: str,
        *,
        table: list[dict[str, Any]] | None = None,
        values: dict[str, Any] | None = None,
        source: str | None = None,
    ) -> Evidence:
        table = table or []
        ev = Evidence(
            id=f"E{len(self._items) + 1}",
            kind=kind,
            title=title,
            description=description,
            table=[_clean(r) for r in table[: self.rows_limit]],
            values=_clean(values or {}),
            source=source,
            columns=list(table[0].keys()) if table else [],
        )
        if len(table) > self.rows_limit:
            ev.values["_truncated_rows"] = len(table) - self.rows_limit
        self._items.append(ev)
        return ev

    def get(self, id_: str) -> Evidence | None:
        return next((e for e in self._items if e.id == id_), None)

    def ids(self) -> set[str]:
        return {e.id for e in self._items}

    def __iter__(self):
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def to_list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._items]


def _clean(obj: Any) -> Any:
    """Make numpy / pandas scalars JSON-friendly."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        np = None  # type: ignore
    if isinstance(obj, dict):
        return {str(k): _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if np is not None and isinstance(obj, np.generic):
        return obj.item()
    if isinstance(obj, float) and math.isnan(obj):
        return None
    return obj
