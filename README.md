# Themes Agent — SPC fund & tailwind intelligence (self-updating)

A **self-updating** intelligence site for Smith Point Capital. A scheduled **GitHub Action** runs on GitHub's own servers, pulls fresh fund activity from the web, rebuilds the dashboard, commits it, and **GitHub Pages** serves it live. No laptop, no manual steps after setup.

## What it does each run (Mondays, automatically)
1. `scripts/scrape_funds.py` pulls each tracked fund's latest activity from the web — the fund's own blog/RSS feed plus a Google News query per firm (investments, new funds, essays). Updates `data/funds.json` + `data/funds/*.json`.
2. `scripts/build_dashboard.py` rebuilds `index.html` from `data/tailwinds.json` + `data/funds.json`.
3. The Action commits and pushes the changes → GitHub Pages redeploys the live site.

## Files
```
index.html                     # the dashboard (two tabs: Tailwind Radar + Funds)
data/tailwinds.json            # tailwind-radar data (Harmonic + PitchBook + press; refreshed by the Cowork agent)
data/funds.json                # all funds + latest updates (refreshed by the Action)
data/funds/<slug>.json         # one file per fund
scripts/scrape_funds.py        # web scraper (feedparser + Google News RSS)
scripts/build_dashboard.py     # renders index.html from the data
.github/workflows/update.yml   # the scheduled GitHub Action
requirements.txt
```

## One-time setup (≈5 minutes)
1. Delete the stray hidden `.git` folder in this directory if present (File Explorer → View → Hidden items).
2. Put the folder on GitHub (GitHub Desktop: Add local repository → create → Publish; or `git init && git add -A && git commit -m init && git remote add origin <url> && git push -u origin main`).
3. **Enable the Action:** GitHub repo → **Settings → Actions → General → Workflow permissions → Read and write permissions → Save.**
4. **Enable the live site:** **Settings → Pages → Source: Deploy from a branch → `main` / (root) → Save.** Live at `https://<you>.github.io/<repo>/`.
5. **Test it now:** repo → **Actions → "Update Themes Agent dashboard" → Run workflow.** It scrapes, rebuilds, commits; the site updates in ~1 minute.

Change the cadence in `.github/workflows/update.yml` (the `cron:` line — currently Monday 12:00 UTC).

## Two data pipelines
- **Funds tab** → fully autonomous in the cloud (GitHub Action, above). This is what "pulls from the internet into GitHub" with no manual step.
- **Tailwind Radar tab** → the richest signals (Harmonic funding data, PitchBook) require authenticated connectors that live in the Cowork app, so that data (`data/tailwinds.json`) is refreshed by the weekly Cowork agent. The Action rebuilds the page from whatever `tailwinds.json` is present, so both pipelines feed one dashboard. (LinkedIn/X are best-effort — only where publicly indexed.)

## Add / remove funds
Edit `data/funds.json` (add an entry: name, slug, url, focus, tier, sources) — the scraper and dashboard pick it up automatically. Add a native RSS feed for a fund in `NATIVE_FEEDS` inside `scripts/scrape_funds.py` for higher-quality pulls.

_Framework reference: Saurav Gopal — "I Analysed 12 Legendary Investors" and "The 7 Mistakes That Keep Repeating."_
