# Raising Soon Signal Engine — Build Specification v1.0

**Smith Point Capital — Proprietary. Internal use only.**
**Date:** 2026-07-15
**Status:** Implementation-ready. Written to be executed by a pure-Python pipeline inside the existing Themes Agent GitHub Action, with zero LLM tokens at runtime.
**Target repo:** `Themes Agent` (existing dashboard + daily Action). This spec extends `scripts/` and `data/` and feeds the **Raising Soon** tab via `data/pipeline_scored.json`.

---

## 1. Executive Summary

### What this engine does

For every company SPC tracks, the Raising Soon engine outputs two numbers every day, computed entirely from token-free data sources (Harmonic API, public ATS job boards, GDELT, SEC EDGAR, GitHub API):

1. **A 0–100 "Raising Soon" score** — the calibrated probability-proxy that the company raises its *next* round soon.
2. **An estimated timing window** — one of `0–3mo`, `3–6mo`, `6–12mo`, `12mo+`, `dormant`.

The engine covers **all stages**: it predicts Seed→A, A→B, B→C, C→D, and D→E/growth transitions, each with its **own signal weights, thresholds, and expected lead times**. This stage segmentation is the core design decision, and it is not optional decoration.

### Why stage segmentation matters

Our 20-company pilot backtest (Seed through D, run against live Harmonic data) shows that the signals that precede a raise are **categorically different by stage**:

- **Seed and Series A raises are announced by people and attention, not by org charts.** The predictive stack is founder pedigree (ex-OpenAI / ex-Tesla / ex-Scale / ex-DeepMind / ex-Stripe), explosive social/web growth off a tiny base (+500% to +11,000% LinkedIn-follower YoY in our sample), fast early headcount growth from a handful of people, and the presence of elite seed investors (a16z, Sequoia, Khosla, Lightspeed) who reliably pre-empt the next round. Finance and GTM executive hires are essentially absent this early.
- **Series B through D raises are announced by the org chart and the hiring curve.** The single most universal signal in the pilot — present in **12 of 12** B/C/D companies — is **headcount "ramp-then-plateau"**: explosive YoY growth (+140% to +610%) that flattens to single-digit or negative growth in the final ~30 days before the raise, as the company pauses hiring while the round closes. The second-most consistent is a **revenue-leadership hire** (VP Sales / CRO / SVP Revenue), present in **10 of 12** B/C/D companies, landing 1–11 months pre-raise and tightest at Series B (1.3–7.6 months).
- **A finance-leadership hire (CFO / VP Finance) is a late-stage tell only.** It appeared in **0 of 4** Series B companies, **0 of 4** Series C companies, and **2 of 4** Series D companies (Cognition's VP Finance ~10.9 months prior; Replit's SVP Finance ~20 months prior; plus one B-stage anomaly, Lovable's "Head of FBOS / startup CFO" ~2.5 months prior). It is high-precision, low-recall, and belongs almost entirely in the C→D and D→E profiles. At B/C, the "adult in the room" hire is more often a COO or Head of GTM.
- **Web traffic and LinkedIn follower curves mirror headcount almost exactly** (same ramp-then-plateau shape at every stage). They are a momentum *proxy*, not an independent signal — the engine weights them as corroboration only, never as a primary driver.
- **Company age is decoupling from stage in the AI cohort** (2–3-year-old companies raising $2B+ Series Ds). The engine therefore keys timing off `fundingStage + lastFundingAt` (stage-conditional cadence), never off `foundingDate`.

### The core insight

A raise is not a surprise event; it is the visible endpoint of a 3–12 month operational sequence — hire the revenue leader, ramp headcount against the new plan, spend down the prior round, then freeze hiring while the term sheet closes. Each stage runs a different version of this sequence. The engine models the sequence directly: a **weighted, stage-specific signal stack**, calibrated on observed pre-raise feature values from companies that actually raised, combined with a **cadence/runway prior** that works within Harmonic's plan limitation (no per-round data; only `lastFundingAt`, `numFundingRounds`, `fundingTotal`).

The output is deliberately simple to consume: one score, one window, one ranked list on the Raising Soon tab — refreshed daily, for free, before the company's raise hits TechCrunch and every other growth fund's inbox.

---

## 2. Signal Taxonomy

Every signal below specifies: **definition → data source → exact extraction logic → raw feature emitted**. Feature names are canonical; the executor must use them verbatim in the signal record schema (§6.4).

Notation for Harmonic traction metrics: each metric arrives as `{value_now, ago30d: {value, percentChange}, ago90d: {...}, ago180d: {...}, ago365d: {...}}`. We write `hc_pct_30` for headcount `ago30d.percentChange`, etc. All `percentChange` values are treated as percentages (e.g., `140.0` = +140%).

### Group A — Capital & Cadence

#### A1. `cadence_pressure` — time-since-last-raise vs. stage-typical cadence

- **Definition:** How far the company is into its stage-typical inter-round interval. The single strongest *prior*; every other signal modulates it.
- **Source:** Harmonic `funding.lastFundingAt`, `funding.fundingStage`.
- **Extraction:**
  - `months_since_raise = (today - lastFundingAt).days / 30.44`
  - Look up the stage's cadence prior (median months between rounds; see §4.1 table).
  - `cadence_ratio = months_since_raise / cadence_median[stage]`
- **Raw features:** `months_since_raise` (float), `cadence_ratio` (float).

#### A2. `runway_depletion` — estimated runway remaining (burn proxy)

- **Definition:** Estimated months of cash left, computed without per-round data (see §4 for the full model).
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

#### B1. `hc_ramp_plateau` — headcount ramp-then-plateau (THE flagship signal)

- **Definition:** Explosive trailing-year headcount growth that has flattened in the trailing 30 days. Pilot: present in **12/12** B/C/D companies; YoY ramps of +140% to +610% collapsing to single-digit or negative 30-day growth immediately pre-raise. Held at every stage; only magnitude differed (B/C swing harder off smaller bases).
- **Source:** Harmonic headcount time series (`value` + `percentChange` at ago30/90/180/365).
- **Extraction (exact):**
  - `ramp = hc_pct_365` (fallback: annualize `hc_pct_180 × 2.03` if 365 missing).
  - `mid = hc_pct_90`
  - `plateau = hc_pct_30`
  - **Plateau flag fires when:** `mid > 30.0 AND plateau < 8.0` *(this is the canonical threshold; tune per §5)*. Strong-plateau variant: `ramp > stage_ramp_ref AND plateau < 3.0` (see stage refs in §3.2).
  - Guard: require `headcount_now ≥ 8` (below that, one departure fakes a plateau).
- **Raw features:** `hc_now` (int), `hc_pct_30`, `hc_pct_90`, `hc_pct_180`, `hc_pct_365` (floats), `hc_plateau_flag` (bool), `hc_strong_plateau_flag` (bool).

#### B2. `revenue_leader_hire` — VP Sales / CRO / SVP Revenue arrival

- **Definition:** A senior revenue leader joined recently. Pilot: **10/12** B/C/D companies, landing 1–11 months pre-raise; tightest at Series B (1.3–7.6 months), earlier and more spread at C.
- **Source:** Harmonic `employees`/`execs` with experience arrays (`title`, `department`, `roleType`, `startDate`, `endDate`, `isCurrentPosition`).
- **Extraction (exact):** Scan every person's experience entries where `isCurrentPosition == true` AND the experience's company matches the tracked company. Title matches (case-insensitive regex):
  `r"(chief revenue|cro\b|vp[,.]?\s*(of\s+)?(sales|revenue)|svp[,.]?\s*(of\s+)?(sales|revenue)|head of (sales|revenue|go.to.market|gtm))"`
  Exclude: `r"(assistant|associate|deputy|intern|advisor)"`. Take the **most recent** qualifying `startDate`.
  `rev_hire_months_ago = (today - startDate).days / 30.44` (null if none).
- **Raw features:** `rev_hire_months_ago` (float|null), `rev_hire_title` (string|null).

#### B3. `finance_leader_hire` — CFO / VP Finance / Head of Finance arrival

- **Definition:** A senior finance leader joined. Pilot: **0/4 at B, 0/4 at C, 2/4 at D** (Cognition VP Finance ~10.9mo prior; Replit SVP Finance ~20mo prior; plus Lovable's "Head of FBOS / startup CFO" ~2.5mo prior at B as the lone early-stage exception). Lead times vary wildly (2.5–23mo): **high precision, low recall, predominantly C→D / D→E**.
- **Source & extraction:** Same person-scan as B2 with regex:
  `r"(chief financial|cfo\b|vp[,.]?\s*(of\s+)?finance|svp[,.]?\s*(of\s+)?finance|head of (finance|fp&a|fbos)|finance lead)"`
  Same exclusions. `fin_hire_months_ago = (today - startDate).days / 30.44`.
- **Raw features:** `fin_hire_months_ago` (float|null), `fin_hire_title` (string|null).

#### B4. `first_senior_hire` — first VP Eng / first GTM hire (Seed→A only)

- **Definition:** At Series A-approaching companies, the first senior VP Engineering or first GTM hire starts to appear (pilot finding). This is the early-stage analog of B2/B3.
- **Source & extraction:** Same person-scan; regex `r"(vp[,.]?\s*(of\s+)?engineering|head of engineering|founding (ae|account executive|gtm|sales)|first (gtm|sales) hire|head of growth)"` with `startDate` within trailing 12 months. Only computed when `fundingStage ∈ {SEED, PRE_SEED}`.
- **Raw features:** `senior_hire_months_ago` (float|null), `senior_hire_title` (string|null).

#### B5. `ats_hiring_state` — open-roles mix and freeze detection

- **Definition:** The live job board is a real-time read on the hiring plan: (a) a posted **finance/BizOps/Chief-of-Staff req** at B+ is the *forward-looking* version of B3; (b) a posted **GTM leadership req** is the forward-looking version of B2; (c) a **≥30% drop in total open roles over 30 days** corroborates the headcount plateau (hiring freeze while the round closes).
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

#### C1. `web_momentum` — web traffic ramp-then-plateau (corroboration only)

- **Definition:** Same shape test as B1 applied to web traffic. Pilot: mirrors headcount "almost exactly" at all stages — a momentum proxy, **never weighted as an independent driver**.
- **Source:** Harmonic web traffic time series.
- **Extraction:** `web_plateau_flag = web_pct_90 > 30.0 AND web_pct_30 < 8.0`; also emit `web_pct_365`.
- **Raw features:** `web_pct_30/90/180/365` (floats), `web_plateau_flag` (bool).

#### C2. `linkedin_momentum` — LinkedIn follower acceleration

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

- **Definition:** Companies stage-manage news into the run-up to a raise (product GA, partnerships, ARR milestones), then often go quiet in the final weeks. We measure the *ratio* of recent to prior press volume plus milestone keywords.
- **Source:** GDELT DOC 2.0 API (free, datacenter-friendly): `https://api.gdeltproject.org/api/v2/doc/doc?query="<company name>"&mode=artlist&format=json&timespan=6m&maxrecords=250`.
- **Extraction (exact):**
  - Count articles bucketed by publish date: `press_90 = count(last 90d)`, `press_prior_90 = count(90–180d ago)`.
  - `press_ratio = press_90 / max(press_prior_90, 1)`
  - `press_milestone_flag = any(title/snippet matches r"(launches|general availability|\bGA\b|partnership|surpasses|\$\d+\s?m(illion)? arr|annual recurring revenue|milestone)", case-insensitive)`
  - Noise guard: require `press_prior_90 + press_90 ≥ 3` before trusting the ratio; else emit nulls.
- **Raw features:** `press_90` (int), `press_prior_90` (int), `press_ratio` (float|null), `press_milestone_flag` (bool).

### Group E — Founder & Network

#### E1. `founder_pedigree` — tier-1 alumni founders (Seed/A primary driver)

- **Definition:** Founders with prior tenure at pedigree organizations. Pilot: one of the four dominant Seed/A predictors (rounds get pre-empted on résumé).
- **Source:** Harmonic execs/employees with `roleType == FOUNDER` (or title regex `r"(founder|co.founder)"`), full experience arrays.
- **Extraction:** For each founder, scan **all** experience entries (past and current) for employer names in the constant `PEDIGREE_ORGS` set (ship in `config/pedigree_orgs.json`): `OpenAI, DeepMind, Anthropic, Google Brain, Meta AI / FAIR, Tesla, SpaceX, Stripe, Scale AI, Databricks, Palantir, Airbnb, Uber (early), Ramp, Figma, Snowflake, Nvidia, Two Sigma, Jane Street, MIT/Stanford PhD (title contains "PhD" at those institutions)`. `pedigree_founder_count = count of distinct founders with ≥1 match`.
- **Raw features:** `pedigree_founder_count` (int), `founder_count` (int).

### Signal → feature summary

| # | Signal | Group | Primary stages | Raw features |
|---|--------|-------|----------------|--------------|
| A1 | cadence_pressure | Capital | all | months_since_raise, cadence_ratio |
| A2 | runway_depletion | Capital | A→B and up | runway_months_remaining, est_monthly_burn_usd |
| A3 | form_d_filed | Capital | all (override) | form_d_date, form_d_age_days |
| A4 | elite_investor_base | Capital | Seed→A, D→E | elite_investor_count |
| B1 | hc_ramp_plateau | Talent | all (B+ strongest) | hc_pct_30/90/180/365, hc_plateau_flag |
| B2 | revenue_leader_hire | Talent | A→B, B→C | rev_hire_months_ago |
| B3 | finance_leader_hire | Talent | C→D, D→E | fin_hire_months_ago |
| B4 | first_senior_hire | Talent | Seed→A | senior_hire_months_ago |
| B5 | ats_hiring_state | Talent | A→B and up | ats_freeze_flag, ats_finance_req_flag, gtm_role_share |
| C1 | web_momentum | Traction | corroboration | web_pct_*, web_plateau_flag |
| C2 | linkedin_momentum | Traction | Seed/A primary; else corroboration | li_pct_*, li_explosive_flag |
| C3 | twitter_momentum | Traction | corroboration | tw_pct_* |
| C4 | github_velocity | Traction | Seed→A, A→B (devtools) | stars_30d_delta, gh_surge_flag |
| D1 | press_cadence | Product/Press | B→C and up | press_ratio, press_milestone_flag |
| E1 | founder_pedigree | Founder | Seed→A | pedigree_founder_count |

---

## 3. Stage-Segmented Scoring Model

### 3.1 Architecture

Each company is assigned a **transition profile** from its current `fundingStage`:

| Harmonic fundingStage | Profile | Predicting |
|---|---|---|
| PRE_SEED, SEED | `SEED_TO_A` | Series A |
| SERIES_A | `A_TO_B` | Series B |
| SERIES_B | `B_TO_C` | Series C |
| SERIES_C | `C_TO_D` | Series D |
| SERIES_D and later / GROWTH | `D_TO_E` | Series E / growth |

If `fundingStage` is null: infer from `fundingTotal` (< $5M → SEED_TO_A; $5–25M → A_TO_B; $25–75M → B_TO_C; $75–200M → C_TO_D; ≥ $200M → D_TO_E) and set `stage_inferred: true` in the output.

**Score = 100 × Σᵢ wᵢ(profile) × sᵢ**, where each subscore `sᵢ ∈ [0,1]` and weights per profile sum to 1.00. Then apply the Form D override (§3.5) and derive the window (§3.6). `clip(x,a,b)` means clamp to `[a,b]`.

### 3.2 Subscore definitions (exact math, all profiles)

**s_cadence** (from A1) — hazard-shaped in `cadence_ratio` `r`, using the profile's `cadence_median` M (§4.1):

```
s_cadence = 0                          if r < 0.50        # too soon; just raised
          = (r - 0.50) / 0.75          if 0.50 ≤ r < 1.25 # ramps linearly to 1.0
          = 1.0                        if 1.25 ≤ r ≤ 2.50 # overdue = hot
          = max(0.2, 1 - (r-2.5)/2)    if r > 2.50        # dormant decay, floor 0.2
```

**s_runway** (from A2) — `RM = runway_months_remaining`:

```
s_runway = clip((12 - RM) / 9, 0, 1)      # 0 at ≥12mo runway, 1.0 at ≤3mo
```

**s_hc** (from B1) — ramp × plateau product. `stage_ramp_ref` (the YoY % that counts as "full ramp"): SEED_TO_A **300**, A_TO_B **150**, B_TO_C **120**, C_TO_D **100**, D_TO_E **80** (pilot: B/C swing harder off smaller bases; observed range +140% to +610%).

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

**s_fin_hire** (from B3) — long window, late-stage only (pilot leads: 2.5–23mo, exemplars 10.9mo and ~20mo):

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
(all nulls → term contributes 0; if no ATS found at all, s_ats = 0 and reweight per §3.4)
```

**s_momentum** (from C1+C2+C3) — corroboration blend. For B+ profiles:

```
s_momentum = clip(0.45·web_plateau_flag + 0.40·li_plateau_flag
                  + 0.15·clip(tw_pct_90/100, 0, 1), 0, 1)
```

For SEED_TO_A (explosive-growth form, per pilot +500%–+11,000%):

```
s_momentum = clip(0.5·clip(li_pct_365/1000, 0, 1) + 0.3·clip(web_pct_365/500, 0, 1)
                  + 0.2·li_explosive_flag, 0, 1)
```

**s_github** (from C4, only if `is_devtool`): `s_github = 1.0 if gh_surge_flag else clip(stars_30d_delta/300, 0, 1)`. Non-devtool → 0 and reweight (§3.4).

**s_press** (from D1): `s_press = clip((press_ratio - 1.0)/2.0, 0, 1) + 0.25·press_milestone_flag`, clipped to [0,1]; nulls → 0.

**s_pedigree** (from E1): `0 founders matched → 0; 1 → 0.6; ≥2 → 1.0`.

**s_elite** (from A4): `0 elite investors → 0; 1 → 0.5; ≥2 → 1.0`.

### 3.3 The five weight profiles

Weights per column sum to 1.00. These are the **v1 calibration** seeded directly from the pilot hit-rates (§7); §5 defines how the 300-company backtest revises them.

| Subscore | SEED_TO_A | A_TO_B | B_TO_C | C_TO_D | D_TO_E |
|---|---|---|---|---|---|
| s_hc (ramp-then-plateau) | 0.12 | **0.22** | **0.25** | **0.22** | 0.18 |
| s_cadence | 0.15 | 0.18 | 0.18 | 0.18 | 0.18 |
| s_runway | 0.05 | 0.08 | 0.10 | 0.10 | 0.12 |
| s_rev_hire | 0.00 | **0.15** | 0.12 | 0.08 | 0.06 |
| s_fin_hire | 0.00 | 0.02 | 0.04 | **0.14** | **0.16** |
| s_ats | 0.05 | 0.08 | 0.08 | 0.06 | 0.06 |
| s_momentum | **0.18** | 0.10 | 0.08 | 0.06 | 0.05 |
| s_github | 0.08 | 0.05 | 0.03 | 0.02 | 0.01 |
| s_press | 0.04 | 0.05 | 0.05 | 0.06 | 0.08 |
| s_pedigree | **0.20** | 0.04 | 0.02 | 0.01 | 0.00 |
| s_elite | 0.13 | 0.03 | 0.05 | 0.07 | 0.10 |
| *(s_senior_hire replaces s_rev_hire at Seed)* | *(folded into s_ats slot: use 0.05 for s_senior_hire, drop s_ats to 0.00 at Seed — seed-stage ATS boards are sparse)* | | | | |

**Rationale, grounded in the backtest:**

- **SEED_TO_A** is pedigree + attention: `s_pedigree` (0.20) and `s_momentum` (0.18) dominate because those were the pilot's Seed/A drivers; `s_rev_hire`/`s_fin_hire` are zeroed because finance/GTM exec hires were "essentially absent this early." `s_elite` (0.13) captures pre-emption by a16z/Sequoia/Khosla/Lightspeed-class insiders.
- **A_TO_B** pivots to operations: `s_hc` jumps to 0.22 and `s_rev_hire` peaks at 0.15 — the pilot's revenue-leader hire was *tightest* at Series B (1.3–7.6mo lead), making it the highest-value timed signal at this transition. `s_fin_hire` stays near zero (0/4 at B; the Lovable FBOS hire is the lone anomaly and is worth 0.02, not more).
- **B_TO_C** is peak ramp-plateau (0.25): B/C companies "swing harder off smaller bases," so the shape is cleanest here. Revenue hire still matters (0.12) but arrives "earlier/more spread at C," so it times the window less precisely.
- **C_TO_D** is where `s_fin_hire` earns its keep (0.14): 2/4 Series D companies hired finance leadership 10.9–20mo out (Cognition, Replit), and the ATS finance-req flag (inside s_ats) catches it even earlier. Ramp-plateau still leads (0.22).
- **D_TO_E** leans institutional: finance function (0.16), runway math (0.12 — burn is enormous and estimable), press choreography (0.08), and elite-investor pre-emption dynamics (0.10). Pedigree is irrelevant (0.00).

### 3.4 Missing-data reweighting

If a subscore is **structurally unavailable** (no ATS board found, non-devtool for s_github, Harmonic returns no traction series), set its weight to 0 and renormalize the remaining weights to sum to 1.00. A subscore that is available but simply zero (e.g., no revenue hire found) is **kept at zero** — absence of the hire is real evidence. Record `signals_missing: [...]` in the output so the dashboard can show coverage.

### 3.5 Form D override

If `form_d_age_days ≤ 120` and the filing post-dates `lastFundingAt + 30d`: `score = max(score, 90)`, `window = "0-3mo"`, `override = "form_d"`. (The round may already be partially closed — this converts Raising Soon into a "get in the second close / next round early" alert.)

### 3.6 Window estimation

Compute `expected_months_to_raise` then map to a band:

```
base_remaining = max(0.5, cadence_median[profile] - months_since_raise)

# Signal-driven compression:
if hc_strong_plateau_flag:              base_remaining = min(base_remaining, 3.0)
elif hc_plateau_flag:                   base_remaining = min(base_remaining, 5.0)
if profile == A_TO_B and rev_hire_months_ago is not null and rev_hire_months_ago ≤ 6:
                                        base_remaining = min(base_remaining, 6.0)
if ats_freeze_flag:                     base_remaining = min(base_remaining, 4.0)
if runway_months_remaining is not null: base_remaining = min(base_remaining,
                                             max(1.0, runway_months_remaining - 2.0))
    # companies start raising ~2mo before projected cash-out at the latest

window: base_remaining ≤ 3 → "0-3mo"; ≤ 6 → "3-6mo"; ≤ 12 → "6-12mo"; else "12mo+"
if cadence_ratio > 3.0 and score < 40 → "dormant"
```

**Score bands for the dashboard:** 80–100 = `Imminent` (red), 60–79 = `Warming` (orange), 40–59 = `Watch` (yellow), <40 = `Quiet` (gray).

### 3.7 Worked example (illustrative arithmetic check)

Series B enterprise-AI company (profile B_TO_C, cadence_median 20mo, ramp_ref 120): raised 14mo ago (`r=0.70 → s_cadence=0.27`); `hc_pct_365=+210, hc_pct_90=+38, hc_pct_30=+2` → `ramp_c=1.0, plateau_c=0.75, gate=1 → s_hc=0.75`; CRO hired 5mo ago → `s_rev_hire=1.0`; no finance hire → 0; ATS freeze fired + gtm_share 0.35 → `s_ats=0.5+0+0.2·0.6=0.62`; web+LI plateau both fired → `s_momentum=0.85`; runway est 7mo → `s_runway=0.56`; press_ratio 1.8 + milestone → `s_press=0.65`; not devtool (reweight s_github's 0.03 pro-rata); 1 elite investor → 0.5; pedigree 0.
Score ≈ 100 × (0.25·0.75 + 0.18·0.27 + 0.10·0.56 + 0.12·1.0 + 0.04·0 + 0.08·0.62 + 0.08·0.85 + 0.05·0.65 + 0.02·0 + 0.05·0.5) / 0.97 ≈ **66 → "Warming."** Window: plateau flag caps at 5.0, runway caps at 5.0 → **"3-6mo."** This matches the pilot's modal pre-raise posture.

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

**Known error sources, accepted deliberately:** ignores revenue offset (understates runway for efficient companies — acceptable: those companies raise opportunistically anyway, and the cadence term catches them), ignores venture debt, and headcount cost varies by geo. The backtest (§5.5) measures whether `runway_months_remaining < 9` actually discriminates; if its lift is < 1.3× it gets down-weighted, not "fixed."

### 4.4 Combining cadence and runway into timing

The window logic (§3.6) uses **whichever binds first**: `min(cadence_median − months_since_raise, runway_months_remaining − 2)`. Rationale: fast-growing AI companies raise on *momentum* before cash pressure (cadence binds); efficient slower burners raise on *cash* (runway binds). Emit both intermediate values in the signal record so the dashboard can show "why this window."

### 4.5 Cross-validation of `lastFundingAt` (403 workaround hygiene)

`lastFundingAt` occasionally lags announcements by weeks. Two free cross-checks, run in the daily job:

1. **GDELT raise detection:** if the last 60 days of GDELT articles for the company match `r"(raises|raised|closes|secures)\s+\$\d+"`, and `lastFundingAt` is older than the article by > 30 days, set `raise_event_suspected: true`, freeze the score at its previous value, and surface a "verify: possible unrecorded round" chip on the dashboard. Do NOT auto-advance the stage (names collide; a human confirms via the Cowork-side PitchBook connector).
2. **Form D date** (A3): if a Form D post-dates `lastFundingAt` by > 45 days, same flag.

When a new raise IS confirmed (Harmonic updates `lastFundingAt` / `numFundingRounds` increments), the engine automatically rolls the company to the next profile and — critically for §5 — **logs the event** to `data/raising_soon/raise_events.jsonl` with the full frozen signal record from the day before, building SPC's own labeled dataset for free, forever.

---

## 5. Reverse-Engineering Backtest Methodology (20 → 300 companies)

The pilot proved the signal shapes. This section scales calibration to statistically usable weights.

### 5.1 The central measurement constraint (state it, design around it)

Two limitations shape the whole design:

1. **fundingRounds 403:** the only per-company event date is `lastFundingAt`. We cannot reconstruct multi-round histories, so every backtest company contributes exactly **one** labeled event: its most recent raise at date `t0 = lastFundingAt`.
2. **Harmonic time series are anchored to *today*** (ago30/90/180/365 from the pull date), not to arbitrary historical dates. We cannot ask "what was headcount growth as of 14 months ago."

**Consequence — the sampling rule:** only companies whose raise happened **30–120 days before the pull date** are usable, because then today's ago-windows *straddle* `t0`: `ago30d` ≈ post-raise, `ago90d/ago180d` ≈ the immediate pre-raise period (where the plateau lives), `ago365d` ≈ the ramp. The pilot used exactly this trick; the scaled backtest institutionalizes it.

### 5.2 Sample construction (target n=300, 60 per profile)

- **Positives (n≈300):** via Harmonic natural-language/saved search (the same mechanism as the existing saved search 163876 "Enterprise Software just raised"), one query per stage: *"B2B enterprise or AI companies that raised a Series {A|B|C|D|E} in the last 4 months"*, filtered in post to `30 ≤ (today − lastFundingAt).days ≤ 120`. Take up to 60 per stage; if a stage under-fills (Series E will), take what exists and widen to 150 days before lowering n.
- **Controls (n≈300, stage-matched):** same searches minus the raise clause — *"B2B enterprise/AI companies at Series {X}"* — filtered to `months_since_raise ≥ 1.5 × cadence_median[profile]` **and** no GDELT raise match in 12 months (i.e., demonstrably NOT raising on schedule). 60 per stage.
- Persist both cohorts to `data/raising_soon/backtest/cohort_{YYYYQ}.json` so every quarterly run is reproducible.

### 5.3 Look-back feature extraction

For each positive, pull the full company record and compute **every raw feature in §2** exactly as production would, then re-index against `t0`:

- **Time-series shape:** label each ago-window as pre- or post-raise relative to `t0`. The **plateau test for backtest purposes** is: growth in the window containing `[t0 − 60d, t0]` < 8% while the window covering `[t0 − 365d, t0 − 90d]` shows ramp above the stage ref. With only 4 anchor points this is coarse — accept it; the pilot showed the shape is violent enough (+140→single digits) to survive coarse windows.
- **Hires:** `startDate` arrays are absolute dates (not today-anchored), so hire lead times are computed *exactly*: `lead = (t0 − startDate).days / 30.44` for every B2/B3/B4 match with `0 ≤ lead ≤ 24`.
- **Press:** GDELT supports historical date ranges natively — compute `press_ratio` for the 90d window ending at `t0` vs. the prior 90d.
- **Form D:** EDGAR is fully historical — record whether a Form D landed within `[t0 − 30d, t0 + 30d]` (measures A3's realistic recall, which the pilot did not cover).
- **Not measurable retroactively:** ATS open-role history (job boards have no free archive) and GitHub star history (would need daily snapshots). For these two, seed weights are held at their §3.3 values and calibrated only from the **forward log** (§5.7) — say so in the calibration report rather than faking it.

### 5.4 Per-signal metrics

For each signal × profile, compute:

- **Hit-rate** `HR = P(signal fired | raised)` — fired means the §2 flag/threshold condition met in the pre-raise window.
- **False-fire rate** `FF = P(signal fired | control)`.
- **Lift** `L = HR / max(FF, 0.02)`.
- **Lead-time distribution** — median and IQR of months-before-raise at first firing (hires and press give exact leads; time-series signals give windowed leads).

Pilot values to beat / confirm: `hc_ramp_plateau` HR = 12/12 at B/C/D; `revenue_leader_hire` HR = 10/12 with lead 1–11mo (median tight at B: 1.3–7.6mo); `finance_leader_hire` HR = 0/4 (B), 0/4 (C), 2/4 (D) with leads 2.5–23mo.

### 5.5 Converting hit-rates into weights

Per profile, mechanical and reproducible:

```
raw_i  = max(0, HR_i × (L_i - 1))          # rewards firing often AND discriminating
w_i    = raw_i / Σ_j raw_j                  # normalize to 1.00
w_i    = 0.5 × w_i + 0.5 × w_i_prior        # shrink toward §3.3 priors (n=60/stage
                                            # is still small); renormalize
Floor/cap: any signal with L < 1.3 → w = 0 (redistribute); no single w > 0.30.
```

Corroboration constraint (from the pilot's "momentum mirrors headcount" finding): cap `s_momentum` weight at **0.10 for all B+ profiles** regardless of its lift, because its correlation with `s_hc` means its marginal lift is inflated. Verify by computing the `s_hc`–`s_momentum` feature correlation in the positive cohort; if ρ < 0.4 (i.e., they've decoupled), lift the cap.

### 5.6 Model-level precision/recall

Score every positive (features as of `t0 − 30d` approximation) and every control with the calibrated weights. Report, per profile: **precision@score≥60**, **recall@score≥60**, ROC-AUC (rank positives vs. controls), and **window accuracy** (share of positives whose predicted window contained the actual `t0`). **v1 acceptance gates: precision ≥ 0.55 and recall ≥ 0.50 at score ≥ 60, per profile.** A profile that fails gates ships with its §3.3 prior weights and a `calibration: "prior"` tag rather than a bad fit.

### 5.7 Re-calibration cadence

- **Quarterly** (first Monday of Jan/Apr/Jul/Oct, manual trigger from Cowork): re-run §5.2–5.6 with a fresh cohort; write `config/weights.json` with a bumped `calibration_version`; commit. The Action never recalibrates on its own — weights are versioned config, not runtime state.
- **Continuous forward validation, free:** the production event log (`raise_events.jsonl`, §4.5) accumulates true outcomes for *tracked* companies — each logged raise stores the prior day's score and window. Quarterly, report: for tracked companies that raised, what was their score 30/90/180 days prior? This forward log is the *only* source that can calibrate the ATS and GitHub signals (§5.3) and is the long-run replacement for the today-anchored backtest hack.
- **Optional PitchBook enrichment (Cowork-side only, token-costed):** for the quarterly calibration sample only, `pitchbook_get_company_deals` can supply true per-round dates/amounts to (a) validate `lastFundingAt`, (b) measure the true cadence medians for §4.1, and (c) validate the §4.2 stage-share decomposition. Budget: ≤ 100 companies/quarter, run manually. Never in CI.

---

## 6. Implementation Plan for the Executor

Hard requirement: **zero LLM tokens in CI.** Everything below is stdlib-Python (urllib, json, re, datetime) plus what's already in `requirements.txt`. All paths relative to repo root.

### 6.1 Module layout

```
scripts/
  raising_soon/
    __init__.py
    config.py            # loads config/*.json; stage tables from §3.3, §4.1, §4.2 as dicts
    harmonic.py          # get_company(id_or_url) -> dict; wraps existing auth pattern from
                         #   pull_harmonic.py (apikey header, candidate-endpoint fallback,
                         #   fail-safe exit-0 on total failure)
    features/
      capital.py         # A1 cadence, A2 runway (implements §4 verbatim), A4 elite match
      talent.py          # B1 hc shape, B2/B3/B4 person-scan regexes, title matching
      ats.py             # B5: greenhouse/lever/ashby fetchers + slug discovery + freeze calc
      traction.py        # C1/C2/C3 momentum, C4 github stars
      press.py           # D1 GDELT fetch + ratio + milestone regex
      founder.py         # E1 pedigree scan
      edgar.py           # A3 Form D search + name normalization/fuzzy match
    scoring.py           # subscores (§3.2), weights apply (§3.3), reweighting (§3.4),
                         #   form-d override (§3.5), window (§3.6)
    build_record.py      # orchestrates features -> data/raising_soon/signals/<slug>.json
    detect_raises.py     # §4.5: lastFundingAt change detection -> raise_events.jsonl
    backtest.py          # §5 end-to-end; ALSO runnable locally/Cowork-side, never in cron
config/
  weights.json           # {"calibration_version": "2026Q3-v1", "profiles": {...§3.3...}}
  stage_priors.json      # cadence medians, stage shares, ramp refs, burn constants
  elite_investors.json   # A4 set
  pedigree_orgs.json     # E1 set
  companies.json         # THE TRACKED UNIVERSE: [{name, slug, harmonic_id_or_url,
                         #   legal_name (for EDGAR), ats: {vendor, slug}|null,
                         #   github_org_repo|null, is_ai_native, is_devtool}]
data/
  raising_soon/
    signals/<slug>.json  # per-company signal record (schema §6.4) — committed daily,
                         #   which gives free 30d history for ATS/GitHub deltas
    raise_events.jsonl   # append-only outcome log (§4.5)
    backtest/            # quarterly cohorts + calibration reports
  pipeline_scored.json   # scored output consumed by the Raising Soon tab (schema §6.5)
```

Function contracts the executor must honor:

- `features/*.py` — every module exposes `extract(company_json, prev_record: dict|None, cfg) -> dict` returning ONLY its raw features from §2, with `None` for unavailable. No scoring logic in feature modules.
- `scoring.py` — `score(record: dict, profile: str, weights: dict) -> {"score": int, "window": str, "subscores": {...}, "signals_missing": [...], "override": str|None}`. Pure function; unit-test with the §3.7 worked example (expected: score 66 ± 1, window "3-6mo").
- `build_record.py` — `main()` iterates `config/companies.json`, is resilient per-company (one company's HTTP failure logs and continues; carry forward the previous record with `"stale": true`), and exits 0 always (matching the existing fail-safe philosophy of `pull_harmonic.py`).

### 6.2 Daily GitHub Action step ordering

Extend `.github/workflows/update.yml` (move cron to daily, e.g. `0 12 * * *`; the Monday funds scrape can key off `if: github.event.schedule` day check or just run daily too — scraping is cheap):

```yaml
steps:
  1. checkout, setup-python, pip install -r requirements.txt
  2. python scripts/scrape_funds.py                      # existing
  3. python scripts/pull_harmonic.py                     # existing (saved-search raises feed)
  4. python -m scripts.raising_soon.build_record         # NEW: fetch + extract per company
       env: HARMONIC_API_KEY, GITHUB_TOKEN (for star API rate limit)
  5. python -m scripts.raising_soon.detect_raises        # NEW: log outcomes, roll stages
  6. python - <<'PY'                                     # NEW: score
     from scripts.raising_soon import scoring; scoring.score_all()   # writes pipeline_scored.json
     PY
  7. python scripts/build_dashboard.py                   # existing — extended to render
                                                         #   the Raising Soon tab from
                                                         #   data/pipeline_scored.json
  8. git add -A && git commit && git push                # existing
```

Rate-limit discipline (be a good citizen, stay free): Harmonic 1 req/company/day; SEC EDGAR ≤ 10 req/s with the User-Agent header, batch all companies in one pass; GDELT ≤ 1 req/company with 1s sleep; ATS endpoints are static JSON, 1 req/company; GitHub ≤ 1 req/devtool-company (well under 5,000/hr with token). For a 150-company universe the whole step budget is ~600 HTTP calls, < 6 minutes.

### 6.3 Token budget

| Path | LLM tokens |
|---|---|
| Daily Action (steps 1–8) | **0** — pure Python + HTTP, by construction |
| Quarterly recalibration (backtest.py, Cowork-side) | 0 required; optional PitchBook validation ≤ 100 companies (§5.7) |
| Ad-hoc company enrichment (Cowork) | optional, human-triggered only |

### 6.4 Per-company signal record schema — `data/raising_soon/signals/<slug>.json`

```json
{
  "schema_version": 1,
  "slug": "acme-ai",
  "name": "Acme AI",
  "as_of": "2026-07-15",
  "stale": false,
  "stage": {"funding_stage": "SERIES_B", "profile": "B_TO_C", "stage_inferred": false},
  "capital": {
    "last_funding_at": "2025-05-10", "num_funding_rounds": 3, "funding_total_usd": 68000000,
    "months_since_raise": 14.2, "cadence_ratio": 1.01,
    "est_last_round_usd": 37400000, "est_monthly_burn_usd": 3860000,
    "runway_months_remaining": 6.8,
    "form_d_date": null, "form_d_age_days": null,
    "elite_investor_count": 1, "raise_event_suspected": false
  },
  "talent": {
    "hc_now": 130, "hc_pct_30": 2.1, "hc_pct_90": 38.0, "hc_pct_180": 96.0, "hc_pct_365": 210.0,
    "hc_plateau_flag": true, "hc_strong_plateau_flag": true,
    "rev_hire_months_ago": 5.0, "rev_hire_title": "Chief Revenue Officer",
    "fin_hire_months_ago": null, "fin_hire_title": null,
    "senior_hire_months_ago": null, "senior_hire_title": null,
    "ats": {"vendor": "greenhouse", "slug": "acmeai", "open_roles_now": 9,
            "open_roles_30d_ago": 16, "ats_freeze_flag": true,
            "ats_finance_req_flag": false, "ats_gtm_req_flag": true, "gtm_role_share": 0.35}
  },
  "traction": {
    "web_pct_30": 4.0, "web_pct_90": 44.0, "web_pct_365": 260.0, "web_plateau_flag": true,
    "li_pct_30": 6.0, "li_pct_90": 51.0, "li_pct_365": 340.0,
    "li_explosive_flag": false, "li_plateau_flag": true,
    "tw_pct_90": 18.0, "tw_pct_365": 90.0,
    "github": null
  },
  "press": {"press_90": 7, "press_prior_90": 4, "press_ratio": 1.75, "press_milestone_flag": true},
  "founder": {"founder_count": 2, "pedigree_founder_count": 0}
}
```

### 6.5 Scored output schema — `data/pipeline_scored.json` (feeds the Raising Soon tab)

```json
{
  "generated_at": "2026-07-15T12:04:00Z",
  "calibration_version": "2026Q3-v1",
  "companies": [
    {
      "slug": "acme-ai", "name": "Acme AI",
      "profile": "B_TO_C", "next_round": "Series C",
      "score": 66, "band": "Warming", "window": "3-6mo",
      "override": null, "stale": false,
      "subscores": {"s_hc": 0.75, "s_cadence": 0.27, "s_runway": 0.56, "s_rev_hire": 1.0,
                    "s_fin_hire": 0.0, "s_ats": 0.62, "s_momentum": 0.85, "s_github": null,
                    "s_press": 0.65, "s_pedigree": 0.0, "s_elite": 0.5},
      "signals_missing": ["s_github"],
      "top_drivers": ["Revenue leader hired 5.0mo ago (CRO)",
                      "Headcount +210% YoY, +2.1% last 30d — ramp-then-plateau",
                      "ATS open roles 16 -> 9 in 30d (freeze)"],
      "score_delta_7d": +9,
      "why_window": "plateau caps at 5mo; est. runway 6.8mo binds at 4.8mo"
    }
  ]
}
```

`top_drivers` is generated by template strings in `scoring.py` (the three highest `wᵢ × sᵢ` contributions), giving the tab human-readable "why" lines with zero LLM involvement. `score_delta_7d` is computed against the git-committed prior file — companies whose score jumps ≥ 10 in a week sort to a "Movers" strip at the top of the tab.

### 6.6 Dashboard integration

`scripts/build_dashboard.py` gains a third tab renderer: read `data/pipeline_scored.json`, render a table sorted by score desc — columns: Company | Next round | Score (colored band chip) | Window | Top drivers | Δ7d — plus the Movers strip and a per-company expandable row showing subscores and `why_window`. Follow the existing template pattern in `scripts/dashboard_template.html`. If `pipeline_scored.json` is missing, render the tab with a "no data yet" placeholder (never break the build — same fail-safe contract as the rest of the pipeline).

### 6.7 Build order for the executor (dependency-sorted)

1. `config/*.json` (constants from this spec, verbatim) → 2. `harmonic.py` (reuse `pull_harmonic.py` auth/fallback code) → 3. `features/capital.py` + `features/talent.py` (covers 70% of weight mass — shippable v0.5 with just these two + scoring) → 4. `scoring.py` + unit test against §3.7 → 5. `build_record.py` + Action wiring + dashboard tab (**ship v0.5 here**) → 6. `features/ats.py`, `edgar.py`, `press.py`, `traction.py`, `founder.py` → 7. `detect_raises.py` → 8. `backtest.py` (Cowork-side) → first quarterly calibration → `weights.json` v2.

---

## 7. Appendix — Pilot Backtest Results (n = 20, Harmonic, run July 2026)

Sample: 20 companies that recently raised, spanning Seed (4), Series A (4), Series B (4), Series C (4), Series D (4); B2B enterprise/AI universe; features extracted from live Harmonic records with ago-windows straddling each company's `lastFundingAt` (the §5.1 method).

### 7.1 Signal hit-rates by stage cohort

| Signal | Seed (n=4) | A (n=4) | B (n=4) | C (n=4) | D (n=4) | Reading |
|---|---|---|---|---|---|---|
| Headcount ramp-then-plateau | shape present as ramp-only (still scaling into round) | ramp-only | **4/4** | **4/4** | **4/4** | **12/12 at B/C/D — most universal signal.** YoY ramp +140% to +610%, flattening to single-digit or negative growth in final ~30d. Magnitude larger at B/C (smaller bases). |
| Revenue-leadership hire (VP Sales/CRO/SVP Rev) | 0/4 | 0/4 | 4/4 | 3/4 | 3/4 | **10/12 at B/C/D.** Lead 1–11mo. Tightest at B: **1.3–7.6mo**; earlier and more spread at C. |
| Finance-leadership hire (CFO/VP Fin) | 0/4 | 0/4 | 0/4* | 0/4 | **2/4** | Late-stage-only tell. Leads 2.5–23mo — high precision, low recall. *One B-stage anomaly: see 7.2. |
| Web-traffic / LinkedIn plateau mirror | — | — | 4/4 | 4/4 | 4/4 | Mirrors headcount "almost exactly" at all stages → corroboration weight only. |
| Explosive LinkedIn/web growth off tiny base | **4/4** | **3/4** | — | — | — | **+500% to +11,000% YoY** pre-raise. Primary Seed/A driver. |
| Founder pedigree (ex-OpenAI/Tesla/Scale/DeepMind/Stripe etc.) | **4/4** | **3/4** | n/m | n/m | n/m | Primary Seed/A driver. |
| Elite prior investors (a16z/Sequoia/Khosla/Lightspeed) | 3/4 | 3/4 | n/m | n/m | n/m | Pre-emption channel at Seed/A. |
| Fast early headcount off tiny base | 4/4 | 4/4 | — | — | — | Seed/A form of the hiring signal (ramp without plateau). |

*n/m = not measured as a driver in the pilot for that cohort; — = signal form not applicable at that stage.*

### 7.2 Named exemplars (finance-hire lead times)

| Company | Round raised | Finance hire | Lead time before raise |
|---|---|---|---|
| Cognition | Series D | VP Finance | ~10.9 months |
| Replit | Series D | SVP Finance | ~20 months |
| Lovable | Series B (anomaly) | "Head of FBOS" (startup-CFO role) | ~2.5 months |

### 7.3 Structural findings carried into the model

1. **Ramp-then-plateau is the flagship** → highest single weight in every B+ profile (0.18–0.25) and the primary window-compressor (§3.6).
2. **Revenue hire is the best *timed* signal at A→B** (1.3–7.6mo lead) → weight 0.15 with a 9-month decay window.
3. **Finance hire is a C→D/D→E signal with wild lead variance** → weights 0.14/0.16 with a 24-month window and no window-compression role; the forward-looking ATS finance-req flag partially de-lags it.
4. **Momentum metrics are correlated corroboration, not independent evidence** → capped at ≤ 0.10 weight for B+ profiles (§5.5 correlation check enforces this permanently).
5. **Age is decoupling from stage in the AI cohort** (2–3yr-old, $2B+ Series D companies observed) → all timing keys off `fundingStage + lastFundingAt`; `foundingDate` appears nowhere in the scoring math.
6. **Sample-size honesty:** n=20 seeds directionally correct weights; the §5 backtest (n≈300 + stage-matched controls) is the calibration of record, and the production `raise_events.jsonl` log supersedes both over time.

---

*End of specification. Executor: begin at §6.7 step 1. All constants in this document are v1 calibration values and live in `config/` — never hard-code them in module logic.*
