#!/usr/bin/env python3
"""Raising-Soon scorer for pipeline companies (data/pipeline.json) — WEB-ONLY (no Harmonic).

Last-raise date is anchored on the most recent of:
  - SEC EDGAR Form D filing date (authoritative, dated, free), and
  - a news-announced completed raise (GDELT, catches foreign/unfiled raises).
Then cadence (months-since-last-raise vs. a raise window) + imminent-raise chatter + finance/exec
hire news + momentum PR + the day's ATS snapshot (open CFO/VP-Finance role) combine into a 0-100
"Raising Soon" score. Fail-safe; writes data/pipeline_scored.json. NOTE: provisional weights — see
docs/raising-soon-signal-engine.md (v1.1 Confidence & Validity).
"""
import json, os, re, sys, datetime, urllib.parse, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "data", "pipeline.json")
OUT = os.path.join(ROOT, "data", "pipeline_scored.json")
HIST_DIR = os.path.join(ROOT, "data", "signal_history")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TODAY = datetime.date.today()

RAISED_PAST = re.compile(r"\b(raised|closed|closes|secured|secures|banked|lands|landed|nets?)\b.{0,30}(\$|round|series|funding)|\braises?\b.{0,20}\$", re.I)
IMMINENT = re.compile(r"(in talks to raise|is raising|to raise|nearing (a )?(deal|round)|reportedly (in talks|raising)|seeking to raise|looking to raise|new funding round)", re.I)
FIN = re.compile(r"\b(cfo|chief financial|vp finance|vp of finance|head of finance|controller|chief revenue|cro|vp sales)\b.{0,25}(hire|hires|appoint|appoints|names|joins|new)|\b(appoints?|names?|hires?)\b.{0,25}\b(cfo|chief financial|finance chief|cro|chief revenue)\b", re.I)
MOM = re.compile(r"\b(launches?|launched|partners? with|partnership|customers?|expands?|doubles?|milestone|new product|general availability|acquires?)\b", re.I)
STAGE_RE = re.compile(r"series\s+([a-e])\b", re.I)


def fetch_json(url, timeout=20):
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                continue
            return None
        except Exception:
            return None
    return None


def gdelt_articles(name, maxrec=75):
    """Recent articles [{title,date(iso),link}] sorted newest-first, from GDELT (free, CI-friendly)."""
    url = ("https://api.gdeltproject.org/api/v2/doc/doc?query=%s&mode=artlist&format=json"
           "&maxrecords=%d&sort=datedesc&timespan=18months" % (urllib.parse.quote('"%s"' % name), maxrec))
    d = fetch_json(url) or {}
    out = []
    for a in (d.get("articles") or []):
        title = (a.get("title") or "").strip()
        sd = (a.get("seendate") or "")[:8]
        try:
            iso = "%s-%s-%s" % (sd[0:4], sd[4:6], sd[6:8]); datetime.date(int(sd[0:4]), int(sd[4:6]), int(sd[6:8]))
        except Exception:
            iso = ""
        if title:
            out.append({"title": title[:170], "date": iso, "link": a.get("url", "")})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


def edgar_latest(name):
    """Most recent SEC Form D filing date (iso) for the name, or ''."""
    url = "https://efts.sec.gov/LATEST/search-index?q=%s&forms=D" % urllib.parse.quote('"%s"' % name)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ThemesAgent research@smithpointcapital.com"})
        d = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception:
        return ""
    tok = (name.lower().split() or [""])[0]
    best = ""
    for h in (d.get("hits", {}) or {}).get("hits", [])[:8]:
        src = h.get("_source", {}) or {}
        disp = ", ".join(src.get("display_names", []) or []).lower()
        filed = src.get("file_date", "") or ""
        if tok and tok in disp and filed > best:
            best = filed
    return best


def latest_snapshot(slug):
    """Most recent point-in-time row from the web-only logger, if present."""
    path = os.path.join(HIST_DIR, slug + ".jsonl")
    if not os.path.exists(path):
        return {}
    try:
        lines = [ln for ln in open(path, encoding="utf-8").read().splitlines() if ln.strip()]
        return json.loads(lines[-1]) if lines else {}
    except Exception:
        return {}


def months_since(iso):
    try:
        y, mo, dd = map(int, iso[:10].split("-"))
        return round((TODAY - datetime.date(y, mo, dd)).days / 30.4)
    except Exception:
        return None


def _recent(iso_date, maxmo):
    m = months_since(iso_date)
    return m is not None and m <= maxmo


def score(comp):
    name = comp.get("name"); domain = comp.get("domain", "")
    slug = re.sub(r"[^a-z0-9]+", "-", (comp.get("slug") or name or "").lower()).strip("-")
    print("•", name)
    arts = gdelt_articles(name)
    fd = edgar_latest(name)
    # completed-raise articles (for dating the last round + reading stage)
    raised = [a for a in arts if a["date"] and RAISED_PAST.search(a["title"])]
    news_raise_date = raised[0]["date"] if raised else ""
    last_raise = max([d for d in [fd, news_raise_date] if d] or [""])
    months = months_since(last_raise)
    stage = ""
    for a in raised[:3]:
        m = STAGE_RE.search(a["title"])
        if m:
            stage = "Series " + m.group(1).upper(); break

    snap = latest_snapshot(slug)
    sc = 0; signals = []; links = []

    # 1) cadence / runway (provisional window 14-30 months; damp if they JUST raised)
    if months is not None:
        if months < 8:
            signals.append("Raised ~%d mo ago%s — likely NOT raising soon" % (months, " (%s)" % stage if stage else ""))
        elif 14 <= months <= 30:
            r = round(max(0, 30 * (1 - abs(months - 20) / 12)))
            sc += r; signals.append("Cadence: %d mo since last round%s — in the typical raise window" % (months, " (%s)" % stage if stage else ""))
        else:
            signals.append("Last round ~%d mo ago%s" % (months, " (%s)" % stage if stage else ""))
    else:
        signals.append("No dated prior round found (Form D / news)")

    # 2) imminent-raise chatter (fresh, future-tense) — strongest live signal
    imm = [a for a in arts if a["date"] and IMMINENT.search(a["title"]) and _recent(a["date"], 4)]
    if imm:
        sc += 35; signals.append("Imminent-raise chatter: “%s”" % imm[0]["title"][:95]); links.append(imm[0]["link"])

    # 3) finance / revenue leadership hire in the news
    fh = [a for a in arts if FIN.search(a["title"]) and _recent(a["date"], 9)]
    if fh:
        sc += 18; signals.append("Finance/GTM leadership hire: “%s”" % fh[0]["title"][:95]); links.append(fh[0]["link"])

    # 4) ATS open finance-leadership role (from today's snapshot) — a strong structural pre-raise tell
    if snap.get("finance_leadership_open"):
        sc += 20; signals.append("Open finance-leadership role on their careers page (CFO/VP Finance)")
    elif snap.get("gtm_leadership_open"):
        sc += 8; signals.append("Open GTM-leadership role (CRO/VP Sales)")
    if snap.get("open_roles_total"):
        signals.append("%d open roles right now (fin=%s sales=%s eng=%s)" % (
            snap.get("open_roles_total"), snap.get("roles_finance"), snap.get("roles_sales"), snap.get("roles_eng")))

    # 5) momentum / PR
    mh = [a for a in arts if MOM.search(a["title"]) and _recent(a["date"], 4)]
    if mh:
        sc += 8; signals.append("Momentum/PR: “%s”" % mh[0]["title"][:95]); links.append(mh[0]["link"])

    if not signals:
        signals.append("No strong pre-raise signals yet")
    return {
        "name": name, "domain": domain, "score": min(100, sc), "stage": stage,
        "months_since": months, "last_raise_date": last_raise,
        "finance_leadership_open": bool(snap.get("finance_leadership_open")),
        "open_roles": snap.get("open_roles_total"),
        "signals": signals[:6], "url": ("https://" + domain if domain else ""), "links": links[:3],
    }


def main():
    try:
        pipe = json.load(open(PIPE, encoding="utf-8"))
    except Exception as e:
        print("no pipeline.json:", e); return
    comps = pipe.get("companies", []) if isinstance(pipe, dict) else pipe
    out = []
    for c in comps:
        try:
            out.append(score(c))
        except Exception as e:
            print("  scoring failed:", e)
            out.append({"name": c.get("name"), "domain": c.get("domain", ""), "score": 0,
                        "signals": ["data unavailable this run"], "url": ("https://" + c.get("domain", "")) if c.get("domain") else "", "links": []})
    out.sort(key=lambda x: -(x.get("score") or 0))
    json.dump({"generated": TODAY.isoformat(), "companies": out}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote pipeline_scored.json (%d companies, web-only)" % len(out))


if __name__ == "__main__":
    main()
