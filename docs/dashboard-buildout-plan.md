# Themes Agent — Dashboard Build-Out Plan

_Execution plan to restructure the dashboard into a full sourcing OS over the next few days, building on what already exists. Everything stays pure-Python in the daily GitHub Action, web-first / token-efficient, fail-safe, and syntax-gated before every commit._

## Target structure (6 tabs)
1. **Funds** (enhance) — activity buckets + AI 60-day memo on click
2. **Pipeline** (new) — my tracked companies, each with **Raise Estimate** + **Activity**
3. **SPC Sourcing Engine** (new) — fresh fund investments that fit SPC (7-day window) + warm connections + add-to-pipeline
4. **Email Engine** (new) — personalized founder outreach drafts off recent activity
5. **Insights** (replaces Tailwind Radar) — where money/themes are flowing + 7-signal lens with examples
6. **Stealth** (new) — enterprise companies launching out of stealth

## What we already have to build on
- Daily Action pipeline: `scrape_funds.py` (fund activity: native blogs, Substack/Medium, GDELT news, podcasts, EDGAR Form D), `snapshot_signals.py` (per-company point-in-time web log: ATS open roles, Form D, press cadence), `pull_pipeline.py` (Raise Estimate scorer), `build_dashboard.py` (bakes `index.html`), `pull_harmonic.py` (radar feed + domain lookups).
- Free data plumbing already proven: **GDELT** (news, datacenter-friendly), **ATS APIs** (Greenhouse/Lever/Ashby), **SEC EDGAR** Form D, **GitHub** stars, **Harmonic by-domain** (accurate funding anchor, tiny call count).
- Conventions: strict name-in-title matching (kills off-topic noise), idempotent JSONL point-in-time logs under `data/signal_history/`, syntax gate + unit tests before commit, `?v=` cache-bust on deploy.

## Guiding principles
- **Token-efficient:** web/free sources first; Harmonic only for the pipeline funding anchor. LLM is **optional** and only where fluent prose adds value (fund memo, theme narrative, email draft). Default = free Python structured output; flip on a cheap model (gpt-4o-mini/Haiku) later with one secret. Any LLM call is content-hashed so it only runs when inputs change.
- **Static-site constraints:** the dashboard is GitHub Pages (no server). So anything "AI" is **pre-generated daily in the Action** and baked in; "buttons that write data" become **GitHub deep-links** (open the file in GitHub's editor pre-filled) rather than live writes.
- **Honesty:** signal-backed vs cadence/estimate is always labeled; provisional weights stay labeled provisional until the forward log calibrates them.

---

## 1. Funds tab — activity buckets + AI 60-day memo

**Goal:** each firm cleanly shows Podcasts / Investments / Posts / Social, and clicking a firm gives an AI-compiled "what they've been up to in the last 60 days" memo.

**Already have:** updates (classified New fund / Investment / Thesis / Post), podcasts, partner Substacks. **Gaps:** investment detection is noisy vs real portfolio deals; partner social (X/LinkedIn) not scraped.

**Build:**
- **1a. Activity buckets (free).** In `build_dashboard.py`, the panel already groups New funds / Investments / Thesis / Posts. Add a **Podcasts** section (already stored) and a **Social** section that lists partner Substacks/X/LinkedIn links from `sources`/`partner_substacks`. Improve `classify()` so an "Investment" requires a portfolio-company pattern ("leads/backs/invests in X", "$ into X") to reduce false positives.
- **1b. AI 60-day memo — `scripts/fund_memo.py`.** For each firm, gather the last 60 days of updates + podcasts, group into sections (**Content / what they're writing about**, **Podcasts & interviews**, **Investments**, **Fundraising & firm news**), and produce a compiled summary. Two modes, auto-selected:
  - _Free (default):_ Python builds the sectioned digest (bulleted headlines per section + the sector/tailwind rollup we already compute).
  - _LLM (optional):_ if `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` present, generate fluent prose per section. Content-hash the 60-day input; regenerate only on change (near-zero cost).
  - Store `fund["memo"]` (+ `memo_sections`, `memo_hash`, `memo_source`). Render under "Where their head is" in the panel, expandable.
- **Runs:** in the always-on step after `scrape_funds`; token-free unless a key is added.
- **Needs from Lilly:** nothing (works free day one).

---

## 2. Pipeline tab — Raise Estimate + Activity

**Goal:** a dedicated tab for tracked companies (start: Salient, Taktile, NetBox Labs, Bretton), each showing two things: **Raise Estimate** and **Changes in Activity**.

**Build:**
- **2a. Rename Raising Soon → "Raise Estimate."** Keep the tiered, backtest-driven scorer (`pull_pipeline.py`) exactly as built; just relabel the tab/section and copy. It already reads `data/pipeline.json`.
- **2b. Activity feed — `scripts/pipeline_activity.py`.** For each pipeline company, surface **material updates in the past month** from: company blog/changelog RSS, GDELT news (strict name match), Substack, founder posts, and **website diffs**. Writes `data/pipeline_activity.json`.
  - **Website / new-customer detection:** daily-snapshot the homepage + `/customers` (and logo/testimonial text) into the point-in-time log; **diff day-over-day** to surface newly-added customer names or material copy changes. (Same JSONL pattern as `snapshot_signals`.)
  - **Conferences / travel:** detect "at [Conf]", "join us at", "booth", "speaking at", "sponsor of" in news + blog → list upcoming events where Lilly could meet the team. Flag these prominently ("travel opportunity").
  - **Material-update filter:** only show items classified as material (funding, product launch, big customer, exec hire, partnership, conference) from the last ~30 days; drop routine noise.
- **UI:** Pipeline tab → per company card with two panels: Raise Estimate (status/likelihood/evidence) and Activity (dated material updates + conferences).
- **Needs from Lilly:** nothing to start (domains already set). Optional per-company `careers_url`/`ats`/`blog` hints improve coverage.

---

## 3. SPC Sourcing Engine

**Goal:** auto-flag fresh fund investments that look like SPC deals, show for **7 days** then expire, surface any warm connection, and let Lilly push one into her pipeline.

**Build:**
- **3a. Fit flagging — `scripts/sourcing_engine.py`.** Read fund `updates` classified **Investment** from the last 7 days (from `funds.json`), extract the invested company, and keep only **B2B enterprise-tech** fits. Filter uses a keyword/thesis rubric (refined once SPC thesis materials arrive). Each flagged company carries: name, the fund that invested, date, one-line description, source link. **7-day rolling window** — a company announced July 15 shows through July 22, then drops. Writes `data/sourcing.json`.
- **3b. Warm connections (fact, not score).** Read `data/network.json` (provided later — see Materials) and, for each flagged company, surface any factual connection: an advisor/teammate who worked at the company or a founder's prior company; a LinkedIn connection; a known customer. Display as plain statements ("Advisor J. Smith worked at [target's prior co]"). No scoring — just "connection found" with the specifics, to make warm outreach easier.
- **3c. Add-to-pipeline button.** On a static site we can't write files, so the button is a **GitHub deep-link** that opens `data/pipeline.json` in GitHub's web editor pre-filled with the company's entry (name + domain). One commit + next run → it appears in the Pipeline tab (Raise Estimate + Activity) automatically.
- **Needs from Lilly:** SPC thesis/fit rubric (to tighten the filter); advisory-network file (for connections); known portfolio/customer relationships.

---

## 4. Email Engine

**Goal:** turn recent activity into a personalized, ready-to-send founder intro email.

**Build:**
- **4a. `scripts/email_engine.py`.** For each Pipeline or Sourcing company with recent material activity, draft a short, personalized outreach email that opens on the activity hook (e.g., "congrats on the $X round / the [Customer] launch") and pitches an intro meeting. Uses the existing **`spc-cold-outreach` skill's voice/positioning** so it sounds like SPC.
  - _Free (default):_ templated email with the activity line + firm details filled in.
  - _LLM (optional):_ fluent, fully personalized draft (behind the same optional key), regenerated only when the activity hook changes.
  - Writes `data/email_drafts.json`; rendered with a **copy-to-clipboard** button per company.
- **Personalization inputs:** latest Activity item, Raise Estimate status, any warm connection from §3b (so the email can name a mutual tie).
- **Needs from Lilly:** confirm sender identity/signature; optional: run `setup-writing-style` so drafts match her voice.

---

## 5. Insights (replaces Tailwind Radar)

**Goal:** one tab that answers "where is money and attention flowing," built from everything the Funds tab already collects.

**Build:**
- **5a. Money-flow ledger — `scripts/insights_raises.py`.** Aggregate all fund `updates` classified **Investment** over the 6-month window + `harmonic_raises.json`, **dedupe by company**, keep only **real VC-backed raises**, and show: company, one-line description, amount/stage if known, and the investor(s) seen backing it. Sortable/most-recent. Writes `data/insights_raises.json`.
- **5b. Theme grouping.** Cluster the deduped raises + fund POVs into themes using the curated sector vocabulary we already use (agents, infra, fintech, defense, security, robotics, health, data, dev-tools, etc.), with counts and example companies per theme. Optional LLM pass for a sophisticated narrative summary of "the themes this quarter."
- **5c. Emerging tailwinds.** Keep the current tailwind-detection approach (it works) — scrape/aggregate signals to point at rising tailwinds.
- **5d. 7-signal lens (Saurav Gopal) — clickable examples.** Keep all 7 signals; make each **clickable** to show concrete examples pulled from the Funds tab data (e.g., "capable engineers building voluntarily" → OSS/GitHub-momentum examples + relevant seed deals; "falling cost curves" → infra/compute deals and posts). Map each fund investment/post to the signal(s) it evidences.
- **Needs from Lilly:** nothing new; refine tailwind taxonomy in `data/editorial.json` as desired.

---

## 6. Stealth tab

**Goal:** track enterprise companies coming out of stealth; exclude consumer; bias to likely-SPC-fit.

**Build:**
- **6a. `scripts/stealth.py`.** Pull the **stealthstartupspy** Substack feed (`https://stealthstartupspy.substack.com/feed`, free RSS), parse each launch (company, blurb, link, date), filter to **B2B enterprise tech** (drop consumer) and likely-SPC-fit (thesis rubric later). Writes `data/stealth.json`; new tab lists them newest-first with the fit rationale. De-dupe + rolling retention (e.g., last 90 days).
- **Needs from Lilly:** SPC fit criteria (same rubric as §3) to tune enterprise/consumer + fit filtering.

---

## Cross-cutting build items
- **Template → 6 tabs.** Extend `dashboard_template.html` tab bar + panels; keep the fault-tolerant render pattern. Each tab reads its own baked `BLOB` slice.
- **New data files:** `pipeline_activity.json`, `sourcing.json`, `network.json` (provided), `email_drafts.json`, `insights_raises.json`, `stealth.json`, plus memo fields on funds.
- **Action wiring:** new scripts run in the always-on scrape step (free) or the Harmonic step (only where a domain anchor is needed). No workflow-permission changes required except if we add an LLM key env to the build step (2-line edit Lilly can make).
- **Testing:** every new parser ships with mock-payload unit tests + the syntax/build/JS gate before commit (as we've been doing).

## Suggested sequence (a few days)
- **Day 1 — Pipeline tab.** Rename Raise Estimate; build `pipeline_activity.py` (blog/news/website-diff/conferences) + UI. Highest reuse, immediately useful.
- **Day 2 — Insights tab.** `insights_raises.py` money-flow ledger + theme grouping; fold in existing tailwinds + 7-signal clickable examples; retire Tailwind Radar.
- **Day 3 — SPC Sourcing Engine.** `sourcing_engine.py` fit-flag + 7-day window + add-to-pipeline deep-link; connections wired with `network.json` placeholder.
- **Day 4 — Fund memos + Stealth + Email Engine.** `fund_memo.py` (free structured, LLM-optional), `stealth.py`, `email_engine.py` (templated, LLM-optional).

## Materials needed from Lilly (blocking those features)
1. **SPC thesis / fit rubric** — stage, check size, sectors, what makes a deal "SPC" — powers Sourcing (§3), Stealth (§6), and email framing.
2. **Advisory / network file** — advisors/team + prior companies + LinkedIn, so Sourcing surfaces warm paths (facts, not scores).
3. **Portfolio / customer relationships** — for additional warm-intro paths.
4. **Sender identity** for the Email Engine (and optionally `setup-writing-style`).

## Open decisions
- **LLM upgrade:** stays off by default (free structured everywhere). Turn on later with one key (OpenAI gpt-4o-mini recommended; ~cents/month, not free) to upgrade fund memos, theme narrative, and email drafts to fluent prose.
- **Pipeline seed list:** starts with Salient / Taktile / NetBox Labs / Bretton; grows via the Sourcing add-to-pipeline button.
