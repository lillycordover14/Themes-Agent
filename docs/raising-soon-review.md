# Raising Soon Signal Engine — Adversarial Review (v1.0 spec)

_Independent skeptical review. Purpose: quantify how much conviction SPC can place in the engine today, and what must change to earn more._

## Bottom line
The flagship signal is very likely a look-ahead / base-rate artifact, the weights are hand-set priors dressed as calibration, and there are zero negative controls — so the engine's false-positive rate (the only number that matters for sourcing) is unknown. The plan is a sound *framework*; the current *numbers* are not yet trustworthy.

**Conviction to source deals TODAY: 2.5 / 10.**
**Methodology/plan as a framework to build on: 6.5 / 10.**

---

## 1. FATAL: "ramp-then-plateau" likely measures POST-raise behavior, not pre-raise
Harmonic's `ago30/90/180/365` windows are trailing windows anchored to **today**. Pilot companies raised in the past 9–15 months, so for a company that raised ~60 days ago:
- `ago30d` growth covers `[raise+30, raise+60]` -> entirely **post-raise**.
- `ago90d` mixes 30 days pre-raise with 60 post.
- `ago365d` "ramp" also includes post-raise growth.

So the "hiring flattens in the final 30 days before the raise" finding is more plausibly **post-raise deceleration / mean-reversion**. The causal story may be inverted. Worse, `percentChange` is % of current base, so a company that grew 20->120 shows low 30-day % growth near the end *regardless of raising* — "plateau" is nearly automatic for any large fast-grower. The Seed/A vs B/C/D "plateau difference" is therefore likely a **base-size artifact**, not company behavior. Practical danger: the strongest signal fires *right after* a raise — the opposite of the value prop.

**Survives temporally:** hire lead-times (absolute `startDate`), founder pedigree, elite investors, GDELT press, Form D. **Dies/unproven:** all time-series-shape signals (headcount/web/LinkedIn plateau) — which carry the most weight at B+.

## 2. No negative controls -> false-positive rate unknown; n=20 too small
Every pilot company raised, so we can compute P(signal | raised) but not P(signal | didn't raise). Without controls there is no lift, precision, or false-positive rate. A signal in 12/12 raisers is worthless if it's also in 12/12 non-raisers ("grew headcount, hired a CRO" describes nearly every hot AI company). With n=4/stage, a 4/4 hit-rate has a 95% CI of roughly [51%, 100%] — you cannot distinguish a 0.22 weight from 0.25. Weights to 2 decimals imply precision the data cannot support.

## 3. Collinear signals double-count; finance-hire is n=2 noise
Headcount, web, and LinkedIn "mirror each other" (author's own finding) = one momentum factor, but it collects ~0.32-0.35 of total weight through two channels (`s_hc` + `s_momentum`). Finance-hire rests on 2 events with lead times of 2.5-23 months (~9x spread) — uninformative for timing; the Lovable case was reclassified to fit the story. Quarantine any signal with <5 positive firings.

## 4. Scoring math: arbitrary breakpoints + an arithmetic bug
Weight decimals aren't derived from anything. The worked example is a constructed hypothetical, not a real company, so it validates nothing. And reproducing it with the spec's own B->C weights yields **score ~= 60-61, not 66** — the spec's own unit test (`66 +/- 1`) would fail. Coverage reweighting (section 3.4) lets poorly-tracked companies float to the top on the thinnest evidence — backwards for sourcing.

## 5. Runway workaround corrupts the timing window
Runway = a chain of +/-30-50% guesses (last-round size x stage prior; burn = headcount x $22k x 1.35; ignores compute-heavy AI burn, revenue offset, venture debt). A "6.8-month runway" could truly be ~3 or ~18 — and the spec lets it hard-cap the output window, so the error feeds straight into the headline timing band.

## What must change to earn conviction (prioritized)
1. **Fix temporal alignment (non-negotiable).** Start daily point-in-time snapshots now; calibrate shape signals only from the forward log once future raises accrue. Until then treat ramp-then-plateau as unproven.
2. **Build negative controls** (stage-matched companies that did NOT raise); recompute every signal as lift with confidence intervals; re-derive weights only then.
3. **Directly test the confound** — compare pre- vs post-raise headcount growth with point-in-time data; drop plateau if it's post-raise.
4. **Minimum viable n** — ~50-60 positives + ~50-60 matched controls per stage, with a time-separated holdout.
5. **Collapse collinear signals** into one momentum factor; cap its weight.
6. **Quarantine thin signals** (finance-hire, anything <5 firings).
7. **Fix runway for AI-native** (separate compute; bound revenue offset) and **remove runway from the window cap** until validated.
8. **Fix coverage bias** — penalize/cap scores when much weight mass is missing.
9. **Round weights to 1 decimal.**
10. **Fix the arithmetic discrepancy** (~60 vs 66).

## What's genuinely good and worth keeping
Stage segmentation is the right instinct. Hire lead-time signals, cadence, and the Form D override (confirmation, not prediction) are sound. The plan already specifies controls, lift, and out-of-sample gates in its backtest section — and the **forward event log that builds a proprietary labeled dataset over time is the real long-term asset.** Make that the core of the plan, not a footnote.
