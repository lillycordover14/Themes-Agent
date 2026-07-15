# Raising Soon Signal Engine — Build Specification v1.1

**Smith Point Capital — Proprietary. Internal use only.**
**Date:** 2026-07-15
**Status:** Implementation-ready as *architecture*. Scoring weights are provisional priors, not calibrated fits (see box below). Written to be executed by a pure-Python pipeline inside the existing Themes Agent GitHub Action, with zero LLM tokens at runtime.
**Target repo:** `Themes Agent` (existing dashboard + daily Action). This spec extends `scripts/` and `data/` and feeds the **Raising Soon** tab via `data/pipeline_scored.json`.
**Revision v1.1:** incorporates an adversarial review's fixes — temporal alignment of the pilot's shape signals, provisional-prior weight labeling, a headcount/web/LinkedIn collinearity cap, a thin-signal quarantine rule, decoupling runway from the output window, a coverage-bias cap on missing-data reweighting, and a corrected worked-example arithmetic check.

---

> ## Confidence & Validity (read this first)
>
> - **Framework soundness: 6.5/10.** The stage-segmented signal taxonomy — Seed→A through D→E, each with its own drivers, thresholds, and lead times — is a sound, well-motivated design. It should survive calibration largely intact.
> - **Current weights & scores: 2.5/10 — NOT yet trustworthy for live sourcing.** Every weight in §3.4 is a provisional prior seeded from a 20-company pilot with no negative controls. Do not rank companies, brief IC, or gate outreach off raw scores until the four caveats below are closed by the controlled backtest (§5) and the forward point-in-time log (§5.1).
>
> **Four headline caveats:**
>
> 1. **Temporal alignment.** Harmonic's `ago30d/90d/180d/365d` windows are anchored to *today*, not to each company's raise date. The pilot's "ramp-then-plateau" finding may be measuring **post-raise** behavior, not pre-raise (§3.1, §5.2).
> 2. **No negative controls.** The pilot measured hit-rate on companies known to have already raised; it never measured false-fire rate on companies that did *not* raise. Without controls, "12/12 fired" tells us nothing about lift.
> 3. **n = 20.** Four companies per stage does not support setting a weight, let alone eleven weights per profile.
> 4. **Collinearity.** Headcount, web traffic, and LinkedIn followers move together — the pilot's own finding is that momentum "mirrors headcount almost exactly." Weighting all three independently triple-counts one underlying momentum factor.
>
> Until §5's controlled backtest (negative controls, n≈300, measured lift) and §5.1's forward log produce validated numbers, treat every score in this system as a **shape hypothesis demonstration**, not a sourcing signal.

### What we can trust today vs. what must be earned

| Trust level | Signal | Why |
|---|---|---|
| **Temporally sound today** | Hire lead-times (revenue leader B2, finance leader B3, first senior hire B4) | `startDate` is an absolute historical date — lead time is exact regardless of pull date. |
| | Founder pedigree (E1) | Career history is static, not a rolling today-anchored window. |
| | Elite investor base (A4) | Cap-table membership is a point-in-time fact, not a time series. |
| | Form D confirmation (A3) | EDGAR filings are dated events, fully historical and retroactively verifiable. |
| | Press cadence (D1, GDELT) | GDELT supports true historical date ranges; the ratio is computed against real pre-event windows. |
| **Provisional — must be earned via §5.1** | Headcount ramp-then-plateau (B1) | Computed from today-anchored ago-windows; may reflect post-raise hiring freeze, not a pre-raise signal. |
| | Web traffic plateau (C1) | Same today-anchoring problem; mirrors headcount, so it is not an independent check. |
| | LinkedIn follower plateau (C2, B+ use) | Same today-anchoring problem. |
| | Runway / burn proxy (A2) | Unvalidated burn model; wrong by construction for AI-native cost structures (§4.3). Now a score input only, not a window cap (§3.7, §4.4). |
| | Finance-leader hire (B3) | Lead time itself is exact, but the *signal is quarantined* for low n (2 firings) until it clears the n≥5 threshold (§2, §3.4). |

---

## 1. Executive Summary

### What this engine does

For every company SPC tracks, the Raising Soon engine outputs two numbers every day, computed entirely from token-free data sources (Harmonic API, public ATS job boards, GDELT, SEC EDGAR, GitHub API):

1. **A 0–100 "Raising Soon" score** — the calibrated probability-proxy that the company raises its *next* round soon.
2. **An estimated timing window** — one of `0–3mo`, `3–6mo`, `6–12mo`, `12mo+`, `dormant`.

The engine covers **all stages**: it predicts Seed→A, A→B, B→C, C→D, and D→E/growth transitions, each with its **own signal weights, thresholds, and expected lead times**. This stage segmentation is the core design decision, and it is not optional decoration.

### Why stage segmentation matters

Our 20-company pilot backtest (Seed through D, run against live Harmonic data) shows that the signals that precede a raise are **categorically different by stage** — directionally, at least; see the Confidence & Validity box above before treating any specific hit-rate as fact:

- **Seed and Series A raises are announced by people and attention, not by org charts.** The predictive stack is founder pedigree (ex-OpenAI / ex-Tesla / ex-Scale / ex-DeepMind / ex-Stripe), explosive social/web growth off a tiny base (+500% to +11,000% LinkedIn-follower YoY in our sample), fast early headcount growth from a handful of people, and the presence of elite seed investors (a16z, Sequoia, Khosla, Lightspeed) who reliably pre-empt the next round. Finance and GTM executive hires are essentially absent this early.
- **Series B through D raises are announced by the org chart and the hiring curve.** The single most universal signal in the pilot — present in **12 of 12** B/C/D companies — is **headcount "ramp-then-plateau"**: explosive YoY growth (+140% to +610%) that flattens to single-digit or negative growth in the final ~30 days before the raise, as the company pauses hiring while the round closes. **This is now classified PROVISIONAL — see §3.1: the pilot's measurement method cannot distinguish a pre-raise plateau from a post-raise hiring freeze.** The second-most consistent is a **revenue-leadership hire** (VP Sales / CRO / SVP Revenue), present in **10 of 12** B/C/D companies, landing 1–11 months pre-raise and tightest at Series B (1.3–7.6 months) — this one IS temporally sound, because hire dates are absolute.
- **A finance-leadership hire (CFO / VP Finance) is a late-stage tell only, and is quarantined in v1.1.** It appeared in **0 of 4** Series B companies, **0 of 4** Series C companies, and **2 of 4** Series D companies (Cognition's VP Finance ~10.9 months prior; Replit's SVP Finance ~20 months prior; plus one B-stage anomaly, Lovable's "Head of FBOS / startup CFO" ~2.5 months prior). Two positive firings is below the n≥5 quarantine threshold (§2, §3.4): the signal stays in the taxonomy, monitoring-only, weight 0.0, until it earns enough events.
- **Web traffic and LinkedIn follower curves mirror headcount almost exactly** (same ramp-then-plateau shape at every stage). They are a momentum *proxy*, not an independent signal, and are also PROVISIONAL for the same temporal-alignment reason as headcount — plus they are collinear with it (§3.4 collinearity cap).
- **Company age is decoupling from stage in the AI cohort** (2–3-year-old companies raising $2B+ Series Ds). The engine therefore keys timing off `fundingStage + lastFundingAt` (stage-conditional cadence), never off `foundingDate`.

### The core insight

A raise is not a surprise event; it is the visible endpoint of a 3–12 month operational sequence — hire the revenue leader, ramp headcount against the new plan, spend down the prior round, then freeze hiring while the term sheet closes. Each stage runs a different version of this sequence. The engine models the sequence directly: a **weighted, stage-specific signal stack**, calibrated on observed pre-raise feature values from companies that actually raised, combined with a **cadence prior** that works within Harmonic's plan limitation (no per-round data; only `lastFundingAt`, `numFundingRounds`, `fundingTotal`). Runway is estimated too, but as of v1.1 it informs the score only — it no longer sets a hard ceiling on the timing window (§3.7, §4.4).

The output is deliberately simple to consume: one score, one window, one ranked list on the Raising Soon tab — refreshed daily, for free. Until calibration closes the gaps in the box above, treat the ranked list as a **research queue to investigate**, not a probability-ordered sourcing feed.

---

## 2. Signal Taxonomy

Every signal below specifies: **definition → data source → exact extraction logic → raw feature emitted**. Feature names are canonical; the executor must use them verbatim in the signal record schema (§6.4).

Notation for Harmonic traction metrics: each metric arrives as `{value_now, ago30d: {value, percentChange}, ago90d: {...}, ago180d: {...}, ago365d: {...}}`. We write `hc_pct_30` for headcount `ago30d.percentChange`, etc. All `percentChange` values are treated as percentages (e.g., `140.0` = +140%). **All four `ago*` windows are anchored to today's pull date, not to any company-specific event date — see §3.1 for why this matters for the three signals below marked PROVISIONAL.**

### Group A — Capital & Cadence

#### A1. `cadence_pressure` — time-since-last-raise vs. stage-typical cadence

- **Definition:** How far the company is into its stage-typical inter-round interval. The single strongest *prior*; every other signal modulates it.
- **Source:** Harmonic `funding.lastFundingAt`, `funding.fundingStage`.
- **Extraction:**
  - `months_since_raise = (today - lastFundingAt).days / 30.44`
  - Look up the stage's cadence prior (median months between rounds; see §4.1 table).
  - `cadence_ratio = months_since_raise / cadence_median[stage]`
- **Raw features:** `months_since_raise` (float), `cadence_ratio` (float).

#### A2. `runway_depletion` — estimated runway remaining (burn proxy) — **score input only, not a window cap (v1.1, §3.7, §4.4)**

- **Definition:** Estimated months of cash left, computed without per-round data (see §4 for the full model, including v1.1's AI-native caveats).
- **Source:** Harmonic `funding.fundingTotal`, `fundingStage`, headcount time series.
- **Extraction:** Per §4.3: estimate last round size from `fundingTotal × stage_share[stage]`, estimate cumulative burn from the trapezoidal average of the headcount time series × a fully-loaded monthly cost, subtract.
- **Raw features:** `est_last_round_usd` (float), `est_monthly_burn_usd` (float), `runway_months_remaining` (float).

#### A3. `form_d_filed` — SEC Form D detection (override signal)

- **Definition:** A new Form D filing means the raise is *already happening* (Reg D closings are filed within 15 days of first sale). This is not a prediction — it is confirmation, and it overrides the model (score floor 90, window `0–3mo`).
- **Source:** SEC EDGAR full-text search JSON API: `https://efts.sec.gov/LATEST/search-index?q="<company legal name>"&forms=D&dateRange=custom&startdt=<today-180d>&enddt=<today>` (use `https://efts.sec.gov/LATEST/search-index?q=...` GET with `User-Agent: SmithPointCapital lilly@smithpointcapital.com` per SEC fair-access rules; fall back to `https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=<name>&type=D&dateb=&owner=include&count=10&output=atom`).
- **Extraction:** Match filings where the issuer name normalized (lowercase, strip `Inc/Corp/LLC/,/.`) equals the company's normalized legal name OR fuzzy-matches at Levenshtein ratio ≥ 0.92. Record the most recent Form D dated **after** `lastFundingAt + 30 days` (to avoid matching the *previous* round's filing).
- **Raw features:** `form_d_date` (ISO date or null), `form_d_age_days` (int or null).
- **Note:** Many AI companies skip Form D or file late/under holding-co names — treat absence as zero information, never as negative evidence.

#### A4. `elite_investor_base` — quality of existing cap table

- **Definition:** Presence of top-tier funds on the current investor list. Elite insiders pre-empt: in the pilot's Seed/A cohort, elite prior investors were one of the four dominant early-stage predictors.
- **Source:** Harmonic `funding.investors[]` (names).
- **Extraction:** Case-insensitive normalized match against the constant `ELITE_INVESTORS` set (ship in `config/elite_investors.json`): `a16z / Andreessen Horowitz, Sequoia, Khosla Ventures, Lightspeed, Benchmark, Index Ventures, Greylock, Thrive Capital, ICONIQ, General Catalyst, Founders Fund, Accel, Bessemer, CRV, Kleiner Perkins, Insight Partners, Coatue, Greenoaks, Redpoint, Felicis, Spark Capital, Conviction, Elad Gil, First Round`. `elite_count = |investors ∩ ELITE_INVESTORS|`.
- **Raw feature:** `elite_investor_count` (int).

### Group B — Talent & Hiring

#### B1. `hc_ramp_plateau` — headcount ramp-then-plateau **(PROVISIONAL)**

- **Status: PROVISIONAL — unproven until validated on the forward point-in-time log (§5.1).** Today-anchored ago-windows may reflect post-raise hiring freezes rather than pre-raise behavior; see §3.1.
- **Definition:** Explosive trailing-year headcount growth that has flattened in the trailing 30 days. Pilot: present in **12/12** B/C/D companies; YoY ramps of +140% to +610% collapsing to single-digit or negative 30-day growth immediately pre-raise. Held at every stage; only magnitude differed (B/C swing harder off smaller bases).
- **Source:** Harmonic headcount time series (`value` + `percentChange` at ago30/90/180/365).
- **Extraction (exact):**
  - `ramp = hc_pct_365` (fallback: annualize `hc_pct_180 × 2.03` if 365 missing).
  - `mid = hc_pct_90`
  - `plateau = hc_pct_30`
  - **Plateau flag fires when:** `mid > 30.0 AND plateau < 8.0` *(this is the canonical threshold; tune per §5)*. Strong-plateau variant: `ramp > stage_ramp_ref AND plateau < 3.0` (see stage refs in §3.3).
  - Guard: require `headcount_now ≥ 8` (below that, one departure fakes a plateau).
- **Raw features:** `hc_now` (int), `hc_pct_30`, `hc_pct_90`, `hc_pct_180`, `hc_pct_365` (floats), `hc_plateau_flag` (bool), `hc_strong_plateau_flag` (bool).

#### B2. `revenue_leader_hire` — VP Sales / CRO / SVP Revenue arrival

- **Definition:** A senior revenue leader joined recently. Pilot: **10/12** B/C/D companies, landing 1–11 months pre-raise; tightest at Series B (1.3–7.6 months), earlier and more spread at C. Temporally sound: `startDate` is an absolute date, not today-anchored.
- **Source:** Harmonic `employees`/`execs` with experience arrays (`title`, `department`, `roleType`, `startDate`, `endDate`, `isCurrentPosition`).
- **Extraction (exact):** Scan every person's experience entries where `isCurrentPosition == true` AND the experience's company matches the tracked company. Title matches (case-insensitive regex):
  `r"(chief revenue|cro\b|vp[,.]?\s*(of\s+)?(sales|revenue)|svp[,.]?\s*(of\s+)?(sales|revenue)|head of (sales|revenue|go.to.market|gtm))"`
  Exclude: `r"(assistant|associate|deputy|intern|advisor)"`. Take the **most recent** qualifying `startDate`.
  `rev_hire_months_ago = (today - startDate).days / 30.44` (null if none).
- **Raw features:** `rev_hire_months_ago` (float|null), `rev_hire_title` (string|null).

#### B3. `finance_leader_hire` — CFO / VP Finance / Head of Finance arrival **(QUARANTINED, w=0 — monitoring only)**

- **Status: QUARANTINED (v1.1).** Only **2** positive firings in the pilot (Cognition, Replit; the Lovable B-stage case is a labeled anomaly). Below the n≥5 quarantine threshold (§2 "Thin-signal quarantine rule," §3.4). The signal remains in the taxonomy and is computed/logged, but its scoring weight is forced to 0.0 across every profile until it clears the threshold in the backtest (§5.6) or forward log (§5.1).
- **Definition:** A senior finance leader joined. Pilot: **0/4 at B, 0/4 at C, 2/4 at D** (Cognition VP Finance ~10.9mo prior; Replit SVP Finance ~20mo prior; plus Lovable's "Head of FBOS / startup CFO" ~2.5mo prior at B as the lone early-stage exception). Lead times vary wildly (2.5–23mo): the *lead-time computation itself* is temporally sound (absolute dates), but the *sample* is too thin to trust a weight.
- **Source & extraction:** Same person-scan as B2 with regex:
  `r"(chief financial|cfo\b|vp[,.]?\s*(of\s+)?finance|svp[,.]?\s*(of\s+)?finance|head of (finance|fp&a|fbos)|finance lead)"`
  Same exclusions. `fin_hire_months_ago = (today - startDate).days / 30.44`.
- **Raw features:** `fin_hire_months_ago` (float|null), `fin_hire_title` (string|null).

#### B4. `first_senior_hire` — first VP Eng / first GTM hire (Seed→A only)

- **Definition:** At Series A-approaching companies, the first senior VP Engineering or first GTM hire starts to appear (pilot finding). This is the early-stage analog of B2/B3.
- **Source & extraction:** Same person-scan; regex `r"(vp[,.]?\s*(of\s+)?engineering|head of engineering|founding (ae|account executive|gtm|sales)|first (gtm|sales) hire|head of growth)"` with `startDate` within trailing 12 months. Only computed when `fundingStage ∈ {SEED, PRE_SEED}`.
- **Raw features:** `senior_hire_months_ago` (float|null), `senior_hire_title` (string|null).

#### B5. `ats_hiring_state` — open-roles mix and freeze detection

- **Definition:** The live job board is a real-time read on the hiring plan: (a) a posted **finance/BizOps/Chief-of-Staff req** at B+ is the *forward-looking* version of B3 (and, being sampled continuously rather than as a one-off hire event, may accumulate a usable sample faster than B3 itself); (b) a posted **GTM leadership req** is the forward-looking version of B2; (c) a **≥30% drop in total open roles over 30 days** corroborates the headcount plateau (hiring freeze while the round closes) — note this corroboration inherits B1's temporal-alignment caveat where it overlaps with the plateau read.
- **Source:** Public ATS endpoints, tried in order per company (store the discovered `ats_slug` in the company config once found):
  - Greenhouse: `https://boards-api.greenhouse.io/v1/boards/<slug>/jobs` (JSON)
  - Lever: `https://api.lever.co/v0/postings/<slug>?mode=json` (JSON)
  - Ashby: `https://api.ashbyhq.com/posting-api/job-board/<slug>` (JSON)
- **Extraction (exact):**
  - `open_roles_now = len(jobs)`; persist daily in the per-company signal record so `open_roles_30d_ago` is read from the record history (the Action commits `data/raising_soon/signals/*.json` daily, so history is free).
  - `ats_freeze_flag = open_roles_30d_ago ≥ 5 AND open_roles_now ≤ 0.70 × open_roles_30d_ago`
  - `ats_finance_req_flag = any(title matches B3 regex ∪ r"(controller|head of (bizops|business operations)|chief of staff|strategic finance)")`
  - `ats_gtm_req_flag = any(title matches B2 regex)`
  - `gtm_role_share = count(dept/title matches r"(sales|marketing|gtm|revenue|account exec|customer success)") / open_roles_now`
- **Raw features:** `open_roles_now` (int|null), `open_roles_30d_ago` (int|null), `ats_freeze_flag` (bool), `ats_finance_req_flag` (bool), `ats_gtm_req_flag` (bool), `gtm_role_share` (float|null).

### Group C — Traction & Momentum

#### C1. `web_momentum` — web traffic ramp-then-plateau (corroboration only) **(PROVISIONAL)**

- **Status: PROVISIONAL — unproven until validated on the forward point-in-time log (§5.1).** Same today-anchoring problem as B1; see §3.1.
- **Definition:** Same shape test as B1 applied to web traffic. Pilot: mirrors headcount "almost exactly" at all stages — a momentum proxy, **never weighted as an independent driver**, and collinear with B1 (§3.4 collinearity cap).
- **Source:** Harmonic web traffic time series.
- **Extraction:** `web_plateau_flag = web_pct_90 > 30.0 AND web_pct_30 < 8.0`; also emit `web_pct_365`.
- **Raw features:** `web_pct_30/90/180/365` (floats), `web_plateau_flag` (bool).

#### C2. `linkedin_momentum` — LinkedIn follower acceleration **(PROVISIONAL, plateau form)**

- **Status:** the **plateau form** (`li_plateau_flag`, B+ use) is PROVISIONAL for the same reason as B1/C1 — see §3.1. The **explosive-growth form** (`li_explosive_flag`, Seed/A use) measures magnitude off a tiny base rather than a ramp-then-plateau shape, so it is less exposed to the post-raise-confound specifically, but its `ago365d` input is still today-anchored — treat it as directionally useful, not yet validated.
- **Definition:** Dual-purpose. Early stage (Seed/A): explosive growth off a tiny base is a *primary* signal (pilot: +500% to +11,000% YoY pre-raise). Later stages: corroboration-only plateau shape.
- **Source:** Harmonic LinkedIn follower time series.
- **Extraction:** `li_pct_365`, `li_pct_90`, `li_pct_30`; `li_explosive_flag = li_pct_365 > 500.0` (Seed/A use); `li_plateau_flag = li_pct_90 > 30.0 AND li_pct_30 < 8.0` (B+ use).
- **Raw features:** `li_pct_30/90/365` (floats), `li_explosive_flag` (bool), `li_plateau_flag` (bool).

#### C3. `twitter_momentum` — Twitter/X follower growth (weakest corroboration)

- **Source:** Harmonic Twitter follower series. **Extraction:** `tw_pct_365`, `tw_pct_90`. Fold into the momentum corroboration subscore at one-third weight of C1/C2; never a standalone flag.
- **Raw features:** `tw_pct_90`, `tw_pct_365` (floats).

#### C4. `github_velocity` — repo star velocity (infra/dev-tool companies only)

- **Definition:** Developer-adoption acceleration for companies tagged `is_devtool: true` in the company config.
- **Source:** GitHub API `GET /repos/{org}/{repo}` (`stargazers_count`) — free, 60 req/hr unauthenticated or 5,000/hr with the Action's `GITHUB_TOKEN`. Persist daily counts in the signal record to compute deltas (same trick as B5).
- **Extraction:** `stars_now`; `stars_30d_delta = stars_now - stars_30d_ago`; `stars_accel = stars_30d_delta / max(stars_prev_30d_delta, 1)`; `gh_surge_flag = stars_30d_delta ≥ 300 AND stars_accel ≥ 1.5`.
- **Raw features:** `stars_now` (int|null), `stars_30d_delta` (int|null), `stars_accel` (float|null), `gh_surge_flag` (bool).

### Group D — Product & Press

#### D1. `press_cadence` — GDELT announcement rhythm

- **Definition:** Companies stage-manage news into the run-up to a raise (product GA, partnerships, ARR milestones), then often go quiet in the final weeks. We measure the *ratio* of recent to prior press volume plus milestone keywords. Temporally sound: GDELT supports true historical date ranges.
- **Source:** GDELT DOC 2.0 API (free, datacenter-friendly): `https://api.gdeltproject.org/api/v2/doc/doc?query="<company name>"&mode=artlist&format=json&timespan=6m&maxrecords=250`.
- **Extraction (exact):**
  - Count articles bucketed by publish date: `press_90 = count(last 90d)`, `press_prior_90 = count(90–180d ago)`.
  - `press_ratio = press_90 / max(press_prior_90, 1)`
  - `press_milestone_flag = any(title/snippet matches r"(launches|general availability|\bGA\b|partnership|surpasses|\$\d+\s?m(illion)? arr|annual recurring revenue|milestone)", case-insensitive)`
  - Noise guard: require `press_prior_90 + press_90 ≥ 3` before trusting the ratio; else emit nulls.
- **Raw features:** `press_90` (int), `press_prior_90` (int), `press_ratio` (float|null), `press_milestone_flag` (bool).

### Group E — Founder & Network

#### E1. `founder_pedigree` — tier-1 alumni founders (Seed/A primary driver)

- **Definition:** Founders with prior tenure at pedigree organizations. Pilot: one of the four dominant Seed/A predictors (rounds get pre-empted on résumé). Temporally sound: career history is static.
- **Source:** Harmonic execs/employees with `roleType == FOUNDER` (or title regex `r"(founder|co.founder)"`), full experience arrays.
- **Extraction:** For each founder, scan **all** experience entries (past and current) for employer names in the constant `PEDIGREE_ORGS` set (ship in `config/pedigree_orgs.json`): `OpenAI, DeepMind, Anthropic, Google Brain, Meta AI / FAIR, Tesla, SpaceX, Stripe, Scale AI, Databricks, Palantir, Airbnb, Uber (early), Ramp, Figma, Snowflake, Nvidia, Two Sigma, Jane Street, MIT/Stanford PhD (title contains "PhD" at those institutions)`. `pedigree_founder_count = count of distinct founders with ≥1 match`.
- **Raw features:** `pedigree_founder_count` (int), `founder_count` (int).

### Thin-signal quarantine rule (v1.1)

Any signal with fewer than **5** positive firings in the calibration sample is **quarantined**: it stays in the taxonomy and is still computed, logged, and shown (e.g., in `top_drivers` and the signal record), but its scoring weight is forced to **0.0 ("monitoring only")** until it accumulates ≥5 positive firings in either the backtest cohort (§5.6) or the forward log (§5.1). `finance_leader_hire` (B3) is quarantined today with only 2 confirmed firings. Re-evaluate every quarantine whenever §5.1 or §5.6 reports an updated firing count.

### Signal → feature summary

| # | Signal | Group | Primary stages | Raw features |
|---|--------|-------|----------------|--------------|
| A1 | cadence_pressure | Capital | all | months_since_raise, cadence_ratio |
| A2 | runway_depletion (score input only, §3.7) | Capital | A→B and up | runway_months_remaining, est_monthly_burn_usd |
| A3 | form_d_filed | Capital | all (override) | form_d_date, form_d_age_days |
| A4 | elite_investor_base | Capital | Seed→A, D→E | elite_investor_count |
| B1 | hc_ramp_plateau **(PROVISIONAL)** | Talent | all (B+ strongest) | hc_pct_30/90/180/365, hc_plateau_flag |
| B2 | revenue_leader_hire | Talent | A→B, B→C | rev_hire_months_ago |
| B3 | finance_leader_hire **(QUARANTINED, w=0)** | Talent | C→D, D→E | fin_hire_months_ago |
| B4 | first_senior_hire | Talent | Seed→A | senior_hire_months_ago |
| B5 | ats_hiring_state | Talent | A→B and up | ats_freeze_flag, ats_finance_req_flag, gtm_role_share |
| C1 | web_momentum **(PROVISIONAL)** | Traction | corroboration | web_pct_*, web_plateau_flag |
| C2 | linkedin_momentum **(PROVISIONAL, plateau form)** | Traction | Seed/A primary; else corroboration | li_pct_*, li_explosive_flag |
| C3 | twitter_momentum | Traction | corroboration | tw_pct_* |
| C4 | github_velocity | Traction | Seed→A, A→B (devtools) | stars_30d_delta, gh_surge_flag |
| D1 | press_cadence | Product/Press | B→C and up | press_ratio, press_milestone_flag |
| E1 | founder_pedigree | Founder | Seed→A | pedigree_founder_count |

---

## 3. Stage-Segmented Scoring Model

### 3.1 Temporal Alignment Caveat (read before §3.2–3.8)

Harmonic's traction time series are anchored to the pull date (`ago30d/90d/180d/365d` = 30/90/180/365 days before *today*), not to any company-specific reference date. For a live company being scored today, this is fine — the windows are exactly what production needs. It is **not** fine for validating the *shape* claims this model depends on:

- The pilot's "ramp-then-plateau" finding (§7) was measured by pulling live Harmonic data for companies that had *already* raised, then reading their today-anchored windows. Because the pull happened after the raise, `ago30d` may fall entirely in the **post-raise** period — meaning the observed "plateau" could be a post-raise hiring pause, not a pre-raise signal at all.
- This affects every signal built on the same mechanic: `hc_ramp_plateau` (B1), `web_momentum` (C1), and `linkedin_momentum`'s plateau form (C2, B+ use). All three are reclassified **PROVISIONAL**.
- It does **not** affect signals built on absolute dates: hire `startDate`, Form D filing dates, GDELT article dates, founder career history, investor names. Those are computed identically whether read today or reconstructed retroactively (§5.4).

**Reclassification (v1.1):**

| Signal | Status |
|---|---|
| B1 `hc_ramp_plateau` | **PROVISIONAL — unproven until validated on the forward point-in-time log (§5.1)** |
| C1 `web_momentum` (plateau flag) | **PROVISIONAL — same reason** |
| C2 `linkedin_momentum` (plateau flag, B+ use) | **PROVISIONAL — same reason** |

The only way to actually validate a shape claim is to compare a company's signal state *as captured on the day it was captured* against what happens to that company later — a point-in-time snapshot taken before the outcome is known. That is the forward log described in **§5.1, now the primary calibration method** for these three signals. The §5 backtest's today-anchored reconstruction (§5.2–5.4) remains a useful stopgap for signals built on absolute dates, but it **cannot** validate shape signals — this is stated explicitly rather than treating the backtest as equivalent evidence. This same caveat governs backtest design at §5.2.

### 3.2 Architecture

Each company is assigned a **transition profile** from its current `fundingStage`:

| Harmonic fundingStage | Profile | Predicting |
|---|---|---|
| PRE_SEED, SEED | `SEED_TO_A` | Series A |
| SERIES_A | `A_TO_B` | Series B |
| SERIES_B | `B_TO_C` | Series C |
| SERIES_C | `C_TO_D` | Series D |
| SERIES_D and later / GROWTH | `D_TO_E` | Series E / growth |

If `fundingStage` is null: infer from `fundingTotal` (< $5M → SEED_TO_A; $5–25M → A_TO_B; $25–75M → B_TO_C; $75–200M → C_TO_D; ≥ $200M → D_TO_E) and set `stage_inferred: true` in the output.

**Score = 100 × Σᵢ wᵢ(profile) × sᵢ**, where each subscore `sᵢ ∈ [0,1]` and weights per profile sum to ~1.00 (v1.1: rounded to 1 decimal, see §3.4). Then apply the Form D override (§3.6) and derive the window (§3.7). `clip(x,a,b)` means clamp to `[a,b]`.

### 3.3 Subscore definitions (exact math, all profiles)

**s_cadence** (from A1) — hazard-shaped in `cadence_ratio` `r`, using the profile's `cadence_median` M (§4.1):

```
s_cadence = 0                          if r < 0.50        # too soon; just raised
          = (r - 0.50) / 0.75          if 0.50 ≤ r < 1.25 # ramps linearly to 1.0
          = 1.0                        if 1.25 ≤ r ≤ 2.50 # overdue = hot
          = max(0.2, 1 - (r-2.5)/2)    if r > 2.50        # dormant decay, floor 0.2
```

**s_runway** (from A2, score input only — §3.7, §4.4) — `RM = runway_months_remaining`:

```
s_runway = clip((12 - RM) / 9, 0, 1)      # 0 at ≥12mo runway, 1.0 at ≤3mo
```

**s_hc** (from B1, **PROVISIONAL**) — ramp × plateau product. `stage_ramp_ref` (the YoY % that counts as "full ramp"): SEED_TO_A **300**, A_TO_B **150**, B_TO_C **120**, C_TO_D **100**, D_TO_E **80** (pilot: B/C swing harder off smaller bases; observed range +140% to +610%).

```
ramp_c    = clip(hc_pct_365 / stage_ramp_ref, 0, 1)
plateau_c = clip((8.0 - hc_pct_30) / 8.0, 0, 1)      # 1.0 at ≤0%, 0 at ≥8%
gate      = 1 if hc_pct_90 > 30.0 else 0.5           # canonical flag condition
s_hc      = ramp_c * plateau_c * gate                # SEED_TO_A exception below
```

*SEED_TO_A exception:* early companies are ramping INTO the A, not plateauing — use `s_hc = ramp_c` only (no plateau term) when profile is SEED_TO_A.

**s_rev_hire** (from B2) — recency decay, stage-specific window `H` (months): A_TO_B **H=9** (pilot: 1.3–7.6mo lead), B_TO_C **H=12**, C_TO_D and D_TO_E **H=12**. Null hire → 0.

```
m = rev_hire_months_ago
s_rev_hire = 1.0   if m ≤ H/2
           = 0.6   if H/2 < m ≤ H
           = 0.2   if H < m ≤ 1.5H
           = 0.0   otherwise
```

**s_fin_hire** (from B3, **QUARANTINED — weight forced to 0.0 in §3.4 regardless of this subscore's value**) — long window, late-stage only (pilot leads: 2.5–23mo, exemplars 10.9mo and ~20mo). The subscore is still computed and logged (it feeds the forward log, §5.1) even though it currently contributes nothing to the score:

```
m = fin_hire_months_ago
s_fin_hire = 1.0  if m ≤ 12
           = 0.7  if 12 < m ≤ 24
           = 0.0  otherwise
```

**s_senior_hire** (from B4, SEED_TO_A only): `1.0 if senior_hire_months_ago ≤ 6, 0.5 if ≤ 12, else 0`.

**s_ats** (from B5) — composite:

```
s_ats = 0.5·ats_freeze_flag + 0.3·(ats_finance_req_flag if profile ∈ {C_TO_D, D_TO_E}
                                    else ats_gtm_req_flag)
      + 0.2·clip((gtm_role_share - 0.20)/0.25, 0, 1)
(all nulls → term contributes 0; if no ATS found at all, s_ats = 0 and reweight per §3.5)
```

**s_momentum** (from C1+C2+C3, **PROVISIONAL** — §3.1; collinear with s_hc, capped in combination per §3.4) — corroboration blend. For B+ profiles:

```
s_momentum = clip(0.45·web_plateau_flag + 0.40·li_plateau_flag
                  + 0.15·clip(tw_pct_90/100, 0, 1), 0, 1)
```

For SEED_TO_A (explosive-growth form, per pilot +500%–+11,000%):

```
s_momentum = clip(0.5·clip(li_pct_365/1000, 0, 1) + 0.3·clip(web_pct_365/500, 0, 1)
                  + 0.2·li_explosive_flag, 0, 1)
```

**s_github** (from C4, only if `is_devtool`): `s_github = 1.0 if gh_surge_flag else clip(stars_30d_delta/300, 0, 1)`. Non-devtool → 0 and reweight (§3.5).

**s_press** (from D1): `s_press = clip((press_ratio - 1.0)/2.0, 0, 1) + 0.25·press_milestone_flag`, clipped to [0,1]; nulls → 0.

**s_pedigree** (from E1): `0 founders matched → 0; 1 → 0.6; ≥2 → 1.0`.

**s_elite** (from A4): `0 elite investors → 0; 1 → 0.5; ≥2 → 1.0`.

### 3.4 The Five Weight Profiles — Provisional Priors (NOT Calibrated)

**These are provisional priors, not calibrated weights.** They are seeded from the n=20 pilot's directional hit-rates (§7) with no negative controls (Confidence & Validity box, caveat 2), and are **frozen at these placeholder values** until the controlled backtest (§5, with negative controls and measured lift) or the forward point-in-time log (§5.1) produces a validated revision. Column sums, relative rankings, and precision beyond one decimal place are not meaningful yet — they are illustrative starting points, rounded to 1 decimal place for that reason.

Two frozen-placeholder rules apply on top of the table:

- **Quarantine.** `s_fin_hire` is forced to **0.0 in every profile** (§2 thin-signal quarantine rule) — the pilot observed only 2 positive firings, below the n≥5 minimum. The signal stays in the taxonomy (§2, B3) and is still computed and logged for the forward log, but contributes nothing to the score until it clears the threshold. Weight mass freed by this quarantine has been folded into neighboring signals below (mostly `s_ats`, `s_press`, `s_elite`) — see §5.6 for how quarantine interacts with the mechanical hit-rate-to-weight conversion once real data exists.
- **Collinearity cap.** `s_hc` and `s_momentum` are, per the pilot's own finding, one underlying momentum factor measured three ways (headcount, web, LinkedIn). `w(s_hc) + w(s_momentum)` is capped at **≤ 0.4** in every profile below, and — once calibrated — must be set from the *marginal* lift of momentum *given* headcount is already known, not from each signal's standalone lift. Standalone lift double/triple-counts one factor.

| Subscore | SEED_TO_A | A_TO_B | B_TO_C | C_TO_D | D_TO_E |
|---|---|---|---|---|---|
| s_hc **(PROVISIONAL)** | 0.1 | 0.2 | 0.3 | 0.2 | 0.2 |
| s_cadence | 0.1 | 0.2 | 0.2 | 0.2 | 0.2 |
| s_runway (score input only) | 0.1 | 0.1 | 0.1 | 0.1 | 0.1 |
| s_rev_hire | 0.0 | 0.2 | 0.1 | 0.1 | 0.1 |
| s_fin_hire **(QUARANTINED)** | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| s_ats | 0.0 | 0.1 | 0.1 | 0.1 | 0.1 |
| s_momentum **(PROVISIONAL)** | 0.2 | 0.1 | 0.1 | 0.1 | 0.1 |
| s_github | 0.1 | 0.0 | 0.0 | 0.0 | 0.0 |
| s_press | 0.0 | 0.1 | 0.1 | 0.1 | 0.1 |
| s_pedigree | 0.2 | 0.0 | 0.0 | 0.0 | 0.0 |
| s_elite | 0.1 | 0.0 | 0.1 | 0.1 | 0.1 |
| s_senior_hire (SEED_TO_A only, replaces s_ats slot) | 0.1 | — | — | — | — |
| **Column sum** | **1.0** | **1.0** | **1.0** | **1.0** | **1.0** |
| **s_hc + s_momentum (cap ≤ 0.4)** | 0.3 | 0.3 | 0.4 | 0.3 | 0.3 |

**Rationale (directional only, all subject to recalibration):**

- **SEED_TO_A** leans pedigree + momentum + elite investors, per the pilot's Seed/A cohort; rev/fin hires are absent this early, so both sit at 0.0.
- **A_TO_B** leans headcount + revenue-leader hire (tightest timed signal at this transition per pilot); `s_fin_hire` is quarantined here too (0/4 in pilot).
- **B_TO_C** carries the largest combined momentum allocation (0.4, at the cap) because the pilot's ramp-then-plateau shape was cleanest here — but see §3.1: this is exactly the profile most exposed to the temporal-alignment problem, since the shape claim itself is unvalidated.
- **C_TO_D** and **D_TO_E** lose their pilot-suggested `s_fin_hire` weight to quarantine (only 2 firings total, both here); that mass has been folded into `s_ats` (which includes a forward-looking finance-req flag with a larger sample) and `s_elite`/`s_press`.

### 3.5 Missing-Data Reweighting and Coverage-Bias Cap

If a subscore is **structurally unavailable** (no ATS board found, non-devtool for s_github, Harmonic returns no traction series), it contributes 0 to the raw score. What happens next depends on how much weight mass is missing — a v1.1 fix, because naive renormalization silently rewards thin coverage:

```
missing_mass = Σ wᵢ over structurally-unavailable subscores

if missing_mass ≤ 0.20:
    # coverage is fine; renormalize remaining weights to sum to 1.00, as v1.0 did
    score = 100 × Σ (wᵢ / (1 - missing_mass)) × sᵢ     over available i

else:
    # v1.1 fix: do NOT renormalize. A poorly-tracked company should not float to
    # the top just because its few available subscores happen to be high.
    score = 100 × Σ wᵢ × sᵢ                             over available i (weights NOT rescaled)
    score = min(score, 100 × (1 - missing_mass))         # explicit coverage cap
    coverage_capped = true
```

A subscore that is available but simply zero (e.g., no revenue hire found) is **kept at zero** — absence of the hire is real evidence, and is not the same as missing data. Record `signals_missing: [...]`, `missing_weight_mass`, and `coverage_capped` in the output (§6.5) so the dashboard can show coverage, and exclude `coverage_capped: true` companies from any auto-alert / "Imminent" surfacing until a human confirms tracking quality.

### 3.6 Form D Override

If `form_d_age_days ≤ 120` and the filing post-dates `lastFundingAt + 30d`: `score = max(score, 90)`, `window = "0-3mo"`, `override = "form_d"`. (The round may already be partially closed — this converts Raising Soon into a "get in the second close / next round early" alert.)

### 3.7 Window Estimation

Compute `expected_months_to_raise` then map to a band:

```
base_remaining = max(0.5, cadence_median[profile] - months_since_raise)

# Signal-driven compression:
if hc_strong_plateau_flag:              base_remaining = min(base_remaining, 3.0)
elif hc_plateau_flag:                   base_remaining = min(base_remaining, 5.0)
if profile == A_TO_B and rev_hire_months_ago is not null and rev_hire_months_ago ≤ 6:
                                        base_remaining = min(base_remaining, 6.0)
if ats_freeze_flag:                     base_remaining = min(base_remaining, 4.0)

window: base_remaining ≤ 3 → "0-3mo"; ≤ 6 → "3-6mo"; ≤ 12 → "6-12mo"; else "12mo+"
if cadence_ratio > 3.0 and score < 40 → "dormant"
```

**v1.1 change: runway is no longer a window cap.** The v1.0 formula additionally capped `base_remaining` at `runway_months_remaining - 2.0`, letting an unvalidated burn estimate directly shrink the customer-facing timing window. Because the burn proxy is known to be wrong for AI-native companies (compute cost, revenue offset, and venture debt are all ignored or crudely patched — §4.3), that cap is **removed**. `runway_months_remaining` still feeds `s_runway` (§3.3, §3.4) and therefore the *score*, but no longer ceilings the *window* until §4.4's validation runs.

Note also that two of the remaining compressors (`hc_strong_plateau_flag`, `hc_plateau_flag`) are themselves **PROVISIONAL** (§3.1) — treat window-tightening from these two triggers with the same caution as the score contribution.

**Score bands for the dashboard:** 80–100 = `Imminent` (red), 60–79 = `Warming` (orange), 40–59 = `Watch` (yellow), <40 = `Quiet` (gray).

### 3.8 Worked Example (Arithmetic Check Only — Not Evidence of Predictive Power)

This example exists to verify the scoring code adds up correctly. It is **not** a claim that the resulting score is accurate — see the Confidence & Validity box.

Series B enterprise-AI company (profile `B_TO_C`, cadence_median 20mo, ramp_ref 120, non-devtool): raised 14mo ago → `r = 0.70 → s_cadence = 0.27`; `hc_pct_365=+210, hc_pct_90=+38, hc_pct_30=+2` → `ramp_c=1.0, plateau_c=0.75, gate=1 → s_hc=0.75` (**PROVISIONAL, §3.1**); CRO hired 5mo ago → `s_rev_hire=1.0`; no finance hire, and `s_fin_hire` is quarantined regardless → contributes `0.0` at weight `0.0`; ATS freeze fired + `gtm_role_share=0.35` → `s_ats = 0.5 + 0 + 0.2·0.6 = 0.62`; web+LinkedIn plateau both fired → `s_momentum=0.85` (**PROVISIONAL, §3.1**); estimated runway → `s_runway=0.56` (score input only, §3.7); `press_ratio=1.8` + milestone → `s_press=0.65`; not devtool → `s_github` weight is 0.0 (no post-hoc reweighting needed); 1 elite investor → `s_elite=0.5`; 0 founders matched → `s_pedigree=0`.

Using the v1.1 `B_TO_C` weights (§3.4: s_hc 0.3, s_cadence 0.2, s_runway 0.1, s_rev_hire 0.1, s_fin_hire 0.0, s_ats 0.1, s_momentum 0.1, s_github 0.0, s_press 0.1, s_pedigree 0.0, s_elite 0.1 — column already sums to 1.00, so no reweighting division is needed for a non-devtool company):

```
score = 100 × (0.3·0.75 + 0.2·0.27 + 0.1·0.56 + 0.1·1.0 + 0.0·0
              + 0.1·0.62 + 0.1·0.85 + 0.1·0.65 + 0.0·0 + 0.1·0.5)
      = 100 × (0.225 + 0.054 + 0.056 + 0.1 + 0 + 0.062 + 0.085 + 0.065 + 0 + 0.05)
      = 100 × 0.697
      ≈ 70 → "Warming"
```

**Window:** `base_remaining = max(0.5, 20 - 14) = 6.0`. `hc_strong_plateau_flag` fires (ramp 210 > 120 ref, plateau 2 < 3.0) → cap at 3.0. `ats_freeze_flag` fires → cap at 4.0 (non-binding, 3.0 already lower). Runway is **not** applied as a window cap (§3.7). → **base_remaining = 3.0 → "0-3mo."**

*(v1.0 of this example contained an arithmetic error — its stated formula actually summed to ≈0.605, not the ≈0.66 it claimed, and it used a runway-based window cap that v1.1 removes. The corrected values above replace it, and the unit test target in §6.1 has been updated to match. This is an arithmetic self-check, not evidence that the score is predictive.)*

---

## 4. Runway / Cadence Model Under the `fundingRounds` 403 Constraint

**The constraint:** Harmonic's `funding.fundingRounds` (per-round dates/amounts) returns **403 Forbidden** on SPC's plan. Available: `lastFundingAt` (date only), `numFundingRounds` (count), `fundingTotal` (cumulative $), `fundingStage`, `valuationInfo`. The model below never touches per-round data.

### 4.1 Stage-conditional cadence priors

Median months between rounds, two regimes (a company is `is_ai_native` if tagged in company config — most of SPC's tracked universe):

| Profile | General median M | AI-native median M | 25th–75th pct band |
|---|---|---|---|
| SEED_TO_A | 15 | 11 | 9–22 |
| A_TO_B | 18 | 13 | 11–26 |
| B_TO_C | 20 | 14 | 12–28 |
| C_TO_D | 22 | 15 | 13–30 |
| D_TO_E | 24 | 16 | 14–32 |

These v1 priors encode the pilot's finding that the AI cohort compresses cadence dramatically (2–3-year-old companies at $2B+ Series D) — which is also why **`foundingDate` is never used for timing**, only `lastFundingAt`. §5's backtest replaces these priors with measured medians per profile.

### 4.2 Estimating the last round size (no per-round data)

Decompose `fundingTotal` using stage-share priors — the typical fraction of cumulative capital contributed by the most recent round:

| Current stage | `stage_share` (last round / fundingTotal) | Fallback absolute prior if fundingTotal null |
|---|---|---|
| Seed | 0.90 | $4M |
| Series A | 0.65 | $15M |
| Series B | 0.55 | $40M |
| Series C | 0.50 | $80M |
| Series D+ | 0.45 | $150M |

```
est_last_round_usd = fundingTotal × stage_share[stage]        (or fallback prior)
Sanity clamp: clip(est_last_round_usd, 0.15 × fundingTotal, fundingTotal)
```

If `numFundingRounds == 1`, then `est_last_round_usd = fundingTotal` exactly (the one case where the 403 doesn't matter).

### 4.3 Burn proxy from the headcount time series

Fully-loaded monthly cost per employee: **$22,000** baseline (enterprise B2B, US-weighted), × **1.35 AI-compute multiplier** when `is_ai_native` (=$29,700/head/mo — deliberately conservative on GPU-heavy infra; tune in backtest).

Average headcount since the raise via trapezoid over the available snapshots. Let `E = months_since_raise` and take the headcount values at now/ago30/ago90/ago180/ago365 that fall inside the elapsed window:

```
pts = [(0, hc_now), (1, hc_30d_ago), (3, hc_90d_ago), (6, hc_180d_ago), (12, hc_365d_ago)]
keep points with months_ago ≤ E; if E > 12, extend with hc_365d_ago flat (conservative).
avg_hc = trapezoidal mean of kept points over [0, min(E, 12)]

est_monthly_burn_usd   = avg_hc × 22000 × (1.35 if is_ai_native else 1.0)
est_burn_to_date_usd   = est_monthly_burn_usd × E
usable_capital         = 0.85 × est_last_round_usd     # 15% haircut: fees, debt paydown,
                                                        # buffer, secondary components
current_run_rate_usd   = hc_now × 22000 × multiplier
runway_months_remaining = max(0, (usable_capital - est_burn_to_date_usd)
                                  / current_run_rate_usd)
```

**v1.1 caveat — this proxy is likely wrong for AI-native companies specifically, in three ways that don't cancel out:**

- **Compute cost.** The $22,000–$29,700/head/month figure is a *people*-cost model. AI-native companies frequently spend more on GPU/cloud compute than on headcount — a cost this model does not see at all, so `est_monthly_burn_usd` likely **understates** true burn for compute-heavy companies.
- **Revenue offset.** The model ignores revenue entirely, which **overstates** burn (understates true runway pressure) for companies with real ARR against their burn.
- **Venture debt.** The model ignores debt facilities, which extend actual runway beyond what `fundingTotal` implies — another source of **understated** runway that pushes the opposite direction from the compute-cost error.

Because these errors point in different directions for different companies and don't net out predictably, `runway_months_remaining` is **no longer allowed to cap the output timing window** (§3.7) — it feeds the score only (§3.4 `s_runway`), and even that weight should be treated as unvalidated until §5.6/§5.7 measures its actual lift. If lift is < 1.3× it gets down-weighted, not "fixed."

### 4.4 Runway's Role: Score Input Only, Not a Window Cap (v1.1)

v1.0 combined cadence and runway directly into the timing window (`min(cadence-based remaining, runway - 2)`), on the theory that "whichever binds first" should set the window. **v1.1 removes runway from that combination**: the window (§3.7) is now driven only by cadence and the (provisional) signal-driven compressors. Runway remains an input to the *score* via `s_runway` (§3.3, §3.4), because the directional idea — low runway correlates with urgency — is still plausible, but the burn proxy is not yet validated well enough to let it override or tighten a customer-facing timing estimate (§4.3). Emit `runway_months_remaining` in the signal record regardless, so the dashboard can show it as context and so §5's backtest can measure its actual lift (§5.6, §5.7) before it is ever reinstated as a window input.

### 4.5 Cross-validation of `lastFundingAt` (403 workaround hygiene)

`lastFundingAt` occasionally lags announcements by weeks. Two free cross-checks, run in the daily job:

1. **GDELT raise detection:** if the last 60 days of GDELT articles for the company match `r"(raises|raised|closes|secures)\s+\$\d+"`, and `lastFundingAt` is older than the article by > 30 days, set `raise_event_suspected: true`, freeze the score at its previous value, and surface a "verify: possible unrecorded round" chip on the dashboard. Do NOT auto-advance the stage (names collide; a human confirms via the Cowork-side PitchBook connector).
2. **Form D date** (A3): if a Form D post-dates `lastFundingAt` by > 45 days, same flag.

When a new raise IS confirmed (Harmonic updates `lastFundingAt` / `numFundingRounds` increments), the engine automatically rolls the company to the next profile and — critically for §5.1 — **logs the event** to `data/raising_soon/raise_events.jsonl` with the full frozen signal record from the day before, building SPC's own labeled, point-in-time dataset for free, forever.

---

## 5. Reverse-Engineering Backtest Methodology (20 → 300 companies)

The pilot proved the signal shapes exist; it did not prove they predict. This section scales calibration to statistically usable weights, and §5.1 explains why, for three of the signals, this section alone is not sufficient.

### 5.1 Primary Calibration Method — Forward Point-in-Time Snapshot Log

**This section, not the today-anchored backtest below, is the primary calibration method for the three PROVISIONAL shape signals (§3.1): `hc_ramp_plateau`, `web_momentum`, and `linkedin_momentum`'s plateau form.** Historical Harmonic data cannot validate them, because there is no way to retroactively ask "what did the today-anchored windows look like on an arbitrary past date" — Harmonic simply doesn't expose that. The only valid fix is to stop reconstructing the past and start capturing the present, then wait for outcomes.

**Mechanism (already built into the daily pipeline, §4.5, §6.1):**

- Every day, `build_record.py` writes a full signal record per company to `data/raising_soon/signals/<slug>.json`, and the Action commits it. This is, by construction, a true point-in-time snapshot — no anchoring ambiguity, because it captures exactly what the production model saw on that date.
- When `detect_raises.py` observes a new raise (`lastFundingAt` advances), it appends the **prior day's frozen record** to `data/raising_soon/raise_events.jsonl` — a genuine labeled example: "here is what the signals looked like N days before this company's raise, captured before anyone knew the raise was coming."
- Symmetrically, companies that do **not** raise accumulate snapshots that never get labeled positive — the full tracked universe (`companies.json`, §6.1) is a running set of negative controls for free, closing caveat #2 in the Confidence & Validity box as soon as enough calendar time has passed.

**Why this supersedes the backtest for shape signals:** a snapshot logged today and labeled in 3–12 months when the raise (or non-raise) resolves has zero temporal-alignment ambiguity. The backtest in §5.2–5.7 remains useful for signals on absolute dates (hires, Form D, press) because those can be reconstructed exactly against `t0`. For the three shape signals, treat every number quoted from §7 (pilot) or §5.6 (backtest) as a **hypothesis**, and treat this forward log as the only source that can convert that hypothesis into a validated weight.

**Reporting cadence:** quarterly (aligned with §5.8), report for every tracked company that raised in the quarter: what did its score/subscores look like 30/60/90/180 days prior, and — the comparison the pilot never ran — what did non-raising companies' plateau flags look like over the same horizon. Do not revise `weights.json` for the three provisional signals until this comparison shows measured lift ≥ 1.3× (the same bar used in §5.6).

### 5.2 The central measurement constraint (state it, design around it)

*(See §3.1 for why this matters and §5.1 for the calibration method it ultimately hands off to for shape signals.)*

Two limitations shape the whole design:

1. **fundingRounds 403:** the only per-company event date is `lastFundingAt`. We cannot reconstruct multi-round histories, so every backtest company contributes exactly **one** labeled event: its most recent raise at date `t0 = lastFundingAt`.
2. **Harmonic time series are anchored to *today*** (ago30/90/180/365 from the pull date), not to arbitrary historical dates. We cannot ask "what was headcount growth as of 14 months ago."

**Consequence — the sampling rule:** only companies whose raise happened **30–120 days before the pull date** are usable, because then today's ago-windows *straddle* `t0`: `ago30d` ≈ post-raise, `ago90d/ago180d` ≈ the immediate pre-raise period (where the plateau lives), `ago365d` ≈ the ramp. The pilot used exactly this trick; the scaled backtest institutionalizes it. **This trick still cannot fully resolve the post-raise confound for the plateau window itself (§3.1) — it narrows the ambiguity, it does not eliminate it. Only §5.1's forward log eliminates it.**

### 5.3 Sample construction (target n=300, 60 per profile)

- **Positives (n≈300):** via Harmonic natural-language/saved search (the same mechanism as the existing saved search 163876 "Enterprise Software just raised"), one query per stage: *"B2B enterprise or AI companies that raised a Series {A|B|C|D|E} in the last 4 months"*, filtered in post to `30 ≤ (today − lastFundingAt).days ≤ 120`. Take up to 60 per stage; if a stage under-fills (Series E will), take what exists and widen to 150 days before lowering n.
- **Controls (n≈300, stage-matched):** same searches minus the raise clause — *"B2B enterprise/AI companies at Series {X}"* — filtered to `months_since_raise ≥ 1.5 × cadence_median[profile]` **and** no GDELT raise match in 12 months (i.e., demonstrably NOT raising on schedule). 60 per stage. These controls resolve caveat #2 for the absolute-date signal