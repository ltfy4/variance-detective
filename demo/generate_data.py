"""Generate the synthetic demo dataset: a UK fashion & home retailer, Jan–Mar 2026.

The data carries a planted story so the agent has something real to find:

* March gross margin lands ~1.6pts below forecast.
* The shortfall is concentrated in the South region, Womenswear, in three stores (S03, S07, S11):
  heavy markdowns booked through COGS — a *rate* problem, not a volume problem.
* S07 Womenswear showed the same pattern in February (so memory flags it as recurring).
* Online Beauty over-delivers in March and partly masks the problem (an offset).

Run:  python demo/generate_data.py   → demo/data/facts.csv
"""
from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).parent / "data" / "facts.csv"

REGIONS = {"North": ["S01", "S02", "S05", "S09"], "Midlands": ["S04", "S06", "S10", "S14"], "South": ["S03", "S07", "S11", "S15"], "Scotland": ["S08", "S12", "S13", "S16"]}
CHANNELS = ["Store", "Online"]
CATEGORIES = {"Womenswear": (0.34, 22.0, 0.44), "Menswear": (0.22, 26.0, 0.42), "Kids": (0.12, 14.0, 0.40), "Home": (0.18, 31.0, 0.38), "Beauty": (0.14, 18.0, 0.47)}  # share, avg price, margin rate
PERIODS = ["2026-01", "2026-02", "2026-03"]
SEASONALITY = {"2026-01": 0.92, "2026-02": 0.88, "2026-03": 1.00}


def generate(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    store_scale = {s: rng.uniform(0.7, 1.4) for s in itertools.chain.from_iterable(REGIONS.values())}
    for period, (region, stores), channel, (cat, (share, price, mrate)) in itertools.product(PERIODS, REGIONS.items(), CHANNELS, CATEGORIES.items()):
        for store in stores:
            base_sales = 24_000_000 / 16 * share * store_scale[store] * SEASONALITY[period] * (0.68 if channel == "Store" else 0.32)
            f_units = base_sales / price
            f_sales = base_sales
            f_cogs = f_sales * (1 - mrate)
            # forecast is the smooth baseline; actuals add noise
            a_sales = f_sales * rng.normal(1.0, 0.025)
            a_units = f_units * rng.normal(1.0, 0.02)
            a_cogs = f_cogs * rng.normal(1.0, 0.012)
            # ---- planted story -------------------------------------------------------------
            if cat == "Womenswear" and channel == "Store":
                if period == "2026-03" and store in ("S03", "S07", "S11"):
                    a_sales *= 0.96           # markdowns depress sales a little
                    a_cogs *= 1.50            # ... and inflate COGS a lot (markdown cost)
                    a_units *= 1.05           # ... while shifting a few more units
                if period == "2026-02" and store == "S07":
                    a_sales *= 0.97
                    a_cogs *= 1.38
            if cat == "Beauty" and channel == "Online" and period == "2026-03":
                a_sales *= 1.11              # favourable offset
                a_cogs *= 1.06
            rows.append((period, "Forecast", region, store, channel, cat, round(f_sales, 2), round(f_cogs, 2), round(f_units)))
            rows.append((period, "Actual", region, store, channel, cat, round(a_sales, 2), round(a_cogs, 2), round(a_units)))
    return pd.DataFrame(rows, columns=["period", "version", "region", "store", "channel", "category", "net_sales", "cogs", "units"])


def main() -> Path:
    df = generate()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    g = df.groupby(["period", "version"])[["net_sales", "cogs"]].sum()
    g["gm_rate"] = 1 - g["cogs"] / g["net_sales"]
    print(g.round(3))
    print(f"\nwrote {len(df):,} rows → {OUT}")
    return OUT


if __name__ == "__main__":
    main()
