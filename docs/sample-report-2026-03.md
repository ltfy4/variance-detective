# Gross Margin — 2026-03 — Actual vs Forecast

*Investigation INV-2026-03-111d26 · source `demo` · 2026-10-12T22:28:40+00:00 · narrator: template · verification: 11/11 claims*

## Gross Margin -£343k vs Forecast in 2026-03 — concentrated in South › Store › Womenswear › S03

Gross Margin for 2026-03 was £10.4M against £10.7M Forecast, -£343k (-3.2%) — below plan. Of that, -£351k is a rate effect (rate 41.0% vs 42.4%, -1.4pts) and +£7.6k is a volume effect (net_sales £25.4M vs £25.3M). South › Store › Womenswear › S03: -£136k is driven by rate erosion (-£128k, -30.7pts) rather than volume (-£7.8k).

| | Actual | Comparison | Variance | % |
|---|---:|---:|---:|---:|
| Gross Margin | £10.4M | £10.7M | -£343k | -3.2% |

Rate effect **-£351k** (41.0% vs 42.4%, -1.4pts) · volume effect **+£7.6k**

## Key findings

- ✅ Gross Margin for 2026-03 was £10.4M against £10.7M Forecast, -£343k (-3.2%) — below plan. _[E2]_
- ✅ Of that, -£351k is a rate effect (rate 41.0% vs 42.4%, -1.4pts) and +£7.6k is a volume effect (net_sales £25.4M vs £25.3M). _[E3]_
- ✅ By region, 1 of 4 members explain 92% of the variance: South -£316k (92.1% of total). _[E5]_
- ✅ Within South, channel concentrates it: Store -£352k (111% of the -£316k). _[E8]_
- ✅ Within South › Store, category concentrates it: Womenswear -£358k (102% of the -£352k). _[E12]_
- ✅ Within South › Store › Womenswear, store concentrates it: S03 -£136k; S07 -£131k; S11 -£102k (103% of the -£358k). _[E15]_
- ✅ Partly masked at South by favourable movements: Online +£36k. _[E9]_
- ✅ On net_sales, price contributed +£40k, volume -£13k and category mix -£9.6k (total +£18k). _[E4]_

## Root causes

- ✅ South › Store › Womenswear › S03: -£136k is driven by rate erosion (-£128k, -30.7pts) rather than volume (-£7.8k). _[E16]_
- ✅ South › Store › Womenswear › S07: -£131k is driven by rate erosion (-£119k, -36.2pts) rather than volume (-£12k). This node also appeared in 1 prior investigation(s) (2026-02). Last explanation: “Store › Womenswear › South › S07: -£75k is driven by rate erosion (-£71k, -23.2pts) rather than volume (-£4.4k).” — a recurring pattern should not be treated as one-off. _[E18, E24]_
- ✅ South › Store › Womenswear › S11: -£102k is driven by rate erosion (-£97k, -31.7pts) rather than volume (-£4.8k). _[E20]_

## Recommended actions

1. Confirm the driver behind South › Store › Womenswear › S03 with the budget owner before the next forecast cycle.
1. Re-baseline the Forecast rate for South › Store › Womenswear › S07: the same intersection has driven the variance in 2 periods.
1. Confirm the driver behind South › Store › Womenswear › S11 with the budget owner before the next forecast cycle.
1. Separate favourable offsets from the underlying adverse trend in the commentary — the net figure understates the problem.

## Variance tree

- **Total** -£343k (100.0% of total) · recurring ×1
  - **South** -£316k (92.1% of total)
    - **South › Store** -£352k (102.6% of total)
      - **South › Store › Womenswear** -£358k (104.3% of total) · recurring ×1
        - **South › Store › Womenswear › S03** -£136k (39.7% of total)
        - **South › Store › Womenswear › S07** -£131k (38.2% of total) · recurring ×1
        - **South › Store › Womenswear › S11** -£102k (29.6% of total)

## Plan PR `PR-2026-03-6523eb` — status: draft

Target version: `Forecast` · total delta +£119k

| Intersection | Measure | Current | Proposed | Δ | Rationale |
|---|---|---:|---:|---:|---|
| South › Store › Womenswear › S07 | cogs | £200k | £319k | +£119k | Align Forecast with the observed rate at South › Store › Womenswear › S07 (-36.2pts), recurring across 2 periods. |

Approve with: `vd pr approve PR-2026-03-6523eb --by <name>`

## Evidence

- **E1** · query · Fact query — demo — SELECT cogs, net_sales, units BY region, category, store, channel, version WHERE time in ['2026-03'], version in ['Actual', 'Forecast']
- **E2** · headline · Gross Margin: Actual vs Forecast — Total Gross Margin computed from cogs, net_sales, units using formula 'net_sales - cogs'.
- **E3** · rate_volume · Rate vs volume split — Total — Gross Margin = net_sales × rate. Volume effect = Δnet_sales × comparison rate; rate effect = Δrate × actual net_sales.
- **E4** · pvm · Price / volume / mix on net_sales — Total — Decomposition of Δnet_sales over category using units as volume.
- **E5** · pivot · Gross Margin by region — Total — Contribution of each region member to the Total variance of -343,080. Dimension chosen because it needs the fewest members to explain 80% (candidates scored: region=1, channel=1, category=1, store=3).
- **E6** · rate_volume · Rate vs volume split — South — Gross Margin = net_sales × rate. Volume effect = Δnet_sales × comparison rate; rate effect = Δrate × actual net_sales.
- **E7** · pvm · Price / volume / mix on net_sales — South — Decomposition of Δnet_sales over category using units as volume.
- **E8** · pivot · Gross Margin by channel — South — Contribution of each channel member to the South variance of -315,940. Dimension chosen because it needs the fewest members to explain 80% (candidates scored: channel=1, category=1, store=3).
- **E9** · offsets · Offsetting channel members — South — Members moving against the South variance (≥10% of it). They mask part of the adverse movement.
- **E10** · rate_volume · Rate vs volume split — South › Store — Gross Margin = net_sales × rate. Volume effect = Δnet_sales × comparison rate; rate effect = Δrate × actual net_sales.
- **E11** · pvm · Price / volume / mix on net_sales — South › Store — Decomposition of Δnet_sales over category using units as volume.
- **E12** · pivot · Gross Margin by category — South › Store — Contribution of each category member to the South › Store variance of -351,961. Dimension chosen because it needs the fewest members to explain 80% (candidates scored: category=1, store=3).
- **E13** · rate_volume · Rate vs volume split — South › Store › Womenswear — Gross Margin = net_sales × rate. Volume effect = Δnet_sales × comparison rate; rate effect = Δrate × actual net_sales.
- **E14** · pvm · Price / volume / mix on net_sales — South › Store › Womenswear — Decomposition of Δnet_sales over category using units as volume.
- **E15** · pivot · Gross Margin by store — South › Store › Womenswear — Contribution of each store member to the South › Store › Womenswear variance of -357,747. Dimension chosen because it needs the fewest members to explain 80% (candidates scored: store=3).
- **E16** · rate_volume · Rate vs volume split — South › Store › Womenswear › S03 — Gross Margin = net_sales × rate. Volume effect = Δnet_sales × comparison rate; rate effect = Δrate × actual net_sales.
- **E17** · pvm · Price / volume / mix on net_sales — South › Store › Womenswear › S03 — Decomposition of Δnet_sales over category using units as volume.
- **E18** · rate_volume · Rate vs volume split — South › Store › Womenswear › S07 — Gross Margin = net_sales × rate. Volume effect = Δnet_sales × comparison rate; rate effect = Δrate × actual net_sales.
- **E19** · pvm · Price / volume / mix on net_sales — South › Store › Womenswear › S07 — Decomposition of Δnet_sales over category using units as volume.
- **E20** · rate_volume · Rate vs volume split — South › Store › Womenswear › S11 — Gross Margin = net_sales × rate. Volume effect = Δnet_sales × comparison rate; rate effect = Δrate × actual net_sales.
- **E21** · pvm · Price / volume / mix on net_sales — South › Store › Womenswear › S11 — Decomposition of Δnet_sales over category using units as volume.
- **E22** · memory · Prior findings — Total — The same Gross Margin node was flagged with the same sign in 1 earlier investigation(s).
- **E23** · memory · Prior findings — South › Store › Womenswear — The same Gross Margin node was flagged with the same sign in 1 earlier investigation(s).
- **E24** · memory · Prior findings — South › Store › Womenswear › S07 — The same Gross Margin node was flagged with the same sign in 1 earlier investigation(s).
