#!/usr/bin/env python3
"""Daily point-in-time signal logger for the Raising Soon engine.

WHY THIS EXISTS: Harmonic's ago30/90/180/365 windows are anchored to *today*, so historical
data can't tell us what a company looked like BEFORE a past raise. The only way to earn real
conviction in the time-series-shape signals (headcount ramp, momentum) is to snapshot each
tracked company's ABSOLUTE metrics every day and let future raises label the series ourselves.
This script does that: one append-only JSONL line per company per day. Over weeks it becomes a
proprietary point-in-time dataset for honest calibration (see docs/raising-soon-signal-engine.md §5).

Runs inside the Harmonic Action step (shares HARMONIC_API_KEY). Fail-safe: missing key or any
per-company error is logged and skipped; never fails the build. Idempotent: re-running on the
same day overwrites that day's row rather than duplicating it.
"""
import json, os, re, sys, datetime, urllib.parse, urllib.request

KEY = os.environ.get("HARMONIC_API_KEY", "").strip()
BASE = os.environ.get("HARMONIC_BASE", "https://api.harmonic.ai").rstrip("/")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "data", "pipeline.json")
HIST_DIR = os.path.join(ROOT, "data", "signal_history")
H = {"apikey": KEY, "accept": "application/json", "content-type": "application/json"}
TODAY = datetime.date.today().isoformat()


def hcall(url, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, headers=H, method=method)
    with urllib.request.urlopen(r, timeout=45) as resp:
        return json.loads(resp.read())


def enrich(name, domain):
    """Resolve via typeahead -> fetch full company record. Mirrors pull_pipeline.enrich()."""
    if not KEY:
        return {}
    try:
        d = hcall(BASE + "/search/typeahead?" + urllib.parse.urlencode({"query": domain or name}))
    except Exception as e:
        print("  typeahead failed:", e); return {}
    cand = None
    if isinstance(d, dict):
        for k in ("results", "companies", "hits", "data", "entities"):
            if isinstance(d.get(k), list) and d[k]:
                cand = d[k]; break
        if cand is None and (d.get("name") or d.get("entity_urn") or d.get("id")):
            cand = [d]
    elif isinstance(d, list):
        cand = d
    if not cand:
        return {}
    it = cand[0] if isinstance(cand[0], dict) else {}
    ident = str(it.get("id") or it.get("company_id") or it.get("entity_urn") or it.get("urn") or "")
    m = re.search(r"(\d+)\s*$", ident)
    cid = m.group(1) if m else ident
    for u in [BASE + "/companies/" + urllib.parse.quote(cid, safe=""),
              BASE + "/companies/" + urllib.parse.quote(ident, safe="")]:
        if not cid:
            break
        try:
            full = hcall(u)
            if isinstance(full, dict) and (full.get("name") or full.get("legal_name")):
                return full
        except Exception as e:
            print("  companies/{id} failed:", e)
    return it


def deep_find(obj, keys, _depth=0):
    """Best-effort: find the first numeric value under any of `keys` anywhere in a nested dict."""
    if _depth > 6 or obj is None:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, (int, float)):
                return v
            if k in keys and isinstance(v, dict) and isinstance(v.get("value"), (int, float)):
                return v["value"]
        for v in obj.values():
            r = deep_find(v, keys, _depth + 1)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = deep_find(v, keys, _depth + 1)
            if r is not None:
                return r
    return None


def exec_titles(full):
    """Collect current leadership titles + their start dates, to detect NEW hires over time."""
    out = []
    people = full.get("people") or full.get("employees") or full.get("team") or []
    if not isinstance(people, list):
        return out
    for p in people[:40]:
        if not isinstance(p, dict):
            continue
        exps = p.get("experience") or []
        for e in (exps if isinstance(exps, list) else []):
            if not isinstance(e, dict):
                continue
            if not e.get("isCurrentPosition"):
                continue
            title = (e.get("title") or "").strip()
            rt = (e.get("roleType") or "").upper()
            if title and rt in ("EXECUTIVE", "FOUNDER", "OPERATOR"):
                out.append({"name": p.get("fullName") or p.get("name") or "",
                            "title": title[:80], "start": (e.get("startDate") or "")[:10],
                            "role_type": rt})
    return out[:25]


def snapshot(comp):
    name, domain, slug = comp.get("name"), comp.get("domain", ""), comp.get("slug") or comp.get("name")
    slug = re.sub(r"[^a-z0-9]+", "-", (slug or "").lower()).strip("-")
    print("•", name)
    full = enrich(name, domain)
    if not full:
        print("  no Harmonic record — skipped"); return None
    f = full.get("funding") or {}
    row = {
        "date": TODAY,
        "name": name,
        "slug": slug,
        # ABSOLUTE values (the point) — build our own time series from these:
        "headcount": full.get("corrected_headcount") or full.get("headcount") or deep_find(full, {"headcount"}),
        "web_visits": deep_find(full, {"web_traffic", "webTraffic", "monthly_visits"}),
        "linkedin_followers": deep_find(full, {"linkedin_follower_count", "linkedinFollowerCount"}),
        "twitter_followers": deep_find(full, {"twitter_follower_count", "twitterFollowerCount"}),
        # funding context (last_funding_at is what we key runway/cadence off of):
        "funding_stage": f.get("funding_stage") or f.get("fundingStage") or "",
        "last_funding_at": (f.get("last_funding_at") or f.get("lastFundingAt") or "")[:10],
        "funding_total": f.get("funding_total") or f.get("fundingTotal"),
        "num_funding_rounds": f.get("num_funding_rounds") or f.get("numFundingRounds"),
        # leadership snapshot (diff day-over-day to detect a NEW finance/revenue hire):
        "execs": exec_titles(full),
    }
    return row


def write_row(slug, row):
    os.makedirs(HIST_DIR, exist_ok=True)
    path = os.path.join(HIST_DIR, slug + ".jsonl")
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    # idempotent: drop any existing row for TODAY, then append the fresh one
    kept = []
    for ln in lines:
        try:
            if json.loads(ln).get("date") != TODAY:
                kept.append(ln)
        except Exception:
            pass
    kept.append(json.dumps(row, ensure_ascii=False))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(kept) + "\n")


def main():
    if not KEY:
        print("HARMONIC_API_KEY not set — skipping point-in-time snapshot (pipeline still runs).")
        return
    try:
        pipe = json.load(open(PIPE, encoding="utf-8"))
    except Exception as e:
        print("could not read pipeline.json:", e); return
    companies = pipe.get("companies") or pipe if isinstance(pipe, list) else pipe.get("companies", [])
    n = 0
    for comp in (companies or []):
        try:
            row = snapshot(comp)
            if row:
                write_row(row["slug"], row); n += 1
        except Exception as e:
            print("  snapshot failed for %s: %s" % (comp.get("name"), e))
    print("Snapshotted %d companies to data/signal_history/ for %s" % (n, TODAY))


if __name__ == "__main__":
    main()
