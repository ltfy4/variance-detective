"""Rate/volume and price/volume/mix decompositions. Pure functions; identities are unit-tested."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass
class RateVolumeResult:
    driver_name: str
    driver_actual: float
    driver_comparison: float
    rate_actual: float | None
    rate_comparison: float | None
    rate_delta_pts: float | None  # in fraction (0.016 = 1.6pts)
    volume_effect: float
    rate_effect: float
    total: float


def rate_volume(*, kpi_actual: float, kpi_comparison: float, driver_actual: float, driver_comparison: float, driver_name: str) -> RateVolumeResult:
    """KPI = driver × rate.  ΔKPI = Δdriver × rate₀  +  Δrate × driver₁ (exact identity)."""
    r0 = kpi_comparison / driver_comparison if driver_comparison else None
    r1 = kpi_actual / driver_actual if driver_actual else None
    if r0 is None or r1 is None:
        total = kpi_actual - kpi_comparison
        return RateVolumeResult(driver_name, driver_actual, driver_comparison, r1, r0, None, 0.0, total, total)
    volume_effect = (driver_actual - driver_comparison) * r0
    rate_effect = (r1 - r0) * driver_actual
    return RateVolumeResult(driver_name, driver_actual, driver_comparison, r1, r0, r1 - r0, volume_effect, rate_effect, volume_effect + rate_effect)


@dataclass
class PVMResult:
    dimension: str
    value_measure: str
    volume_measure: str
    price_effect: float
    volume_effect: float
    mix_effect: float
    total: float
    by_member: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__


def price_volume_mix(df: pd.DataFrame, *, value: str, volume: str, dim: str, actual: str, compare: str) -> PVMResult | None:
    """Standard PVM over members of ``dim``.

    price  = Σ (p1ᵢ − p0ᵢ) · q1ᵢ
    volume = (Q1 − Q0) · P0̄          where P0̄ = V0 / Q0
    mix    = Σ q1ᵢ · p0ᵢ  −  Q1 · P0̄
    price + volume + mix = V1 − V0 (exact).
    """
    g = df.groupby([dim, "version"])[[value, volume]].sum().unstack("version")
    if actual not in g[value].columns or compare not in g[value].columns:
        return None
    v1, v0 = g[value][actual].fillna(0.0), g[value][compare].fillna(0.0)
    q1, q0 = g[volume][actual].fillna(0.0), g[volume][compare].fillna(0.0)
    Q1, Q0, V0 = float(q1.sum()), float(q0.sum()), float(v0.sum())
    if Q0 <= 0 or Q1 <= 0:
        return None
    P0 = V0 / Q0
    p0 = (v0 / q0.replace(0, float("nan"))).fillna(P0)
    p1 = (v1 / q1.replace(0, float("nan"))).fillna(p0)
    price_i = (p1 - p0) * q1
    mix_i = q1 * p0 - (q1 / Q1) * Q1 * P0  # = q1·(p0ᵢ − P0̄)
    volume_effect = (Q1 - Q0) * P0
    rows = []
    for m in g.index:
        rows.append({dim: str(m), "value_actual": round(float(v1[m]), 2), "value_comparison": round(float(v0[m]), 2), "volume_actual": round(float(q1[m]), 2), "volume_comparison": round(float(q0[m]), 2), "price_actual": round(float(p1[m]), 4), "price_comparison": round(float(p0[m]), 4), "price_effect": round(float(price_i[m]), 2), "mix_effect": round(float(mix_i[m]), 2)})
    rows.sort(key=lambda r: abs(r["price_effect"]) + abs(r["mix_effect"]), reverse=True)
    return PVMResult(dim, value, volume, float(price_i.sum()), float(volume_effect), float(mix_i.sum()), float(v1.sum() - v0.sum()), rows)
