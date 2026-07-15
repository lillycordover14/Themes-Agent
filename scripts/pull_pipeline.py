#!/usr/bin/env python3
"""Raising-Soon scorer (data/pipeline.json) — HYBRID.

Last-raise date + stage come from Harmonic looked up BY DOMAIN (accurate, no name collisions;
one lightweight call per pipeline company). If Harmonic is unavailable or the company isn't found,
it falls back to SEC Form D + news dating. Live "raising soon" signals are all free/web:
imminent-raise chatter + finance/GTM-hire news (GDELT, STRICT name-in-title matching to kill
off-topic noise) + the day's ATS snapshot (open CFO/VP-Finance role). Fail-safe; writes
data/pipeline_scored.json. Provisional weights — see docs/raising-soon-signal-engine.md (v1.1).
"""
import json, os, re, sys, datetime, urllib.parse, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "data", "pipeline.json")
OUT = os.path.join(ROOT, "data", "pipeline_scored.json")
HIST_DIR = os.path.join(ROOT, "data", "signal_history")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TODAY = datetime.date.today()

KEY = os.environ.get("HARMONIC_API_KEY", "").strip()
HBASE = os.environ.get("HARMONIC_BASE", "https://api.harmonic.ai").rstrip("/")
HHEAD = {"apikey": KEY, "accept": "application/json", "content-type": "application/json"}

RAISED_PAST = re.compile(r"\b(raised|closed|closes|secured|secures|banked|lands|landed|nets?)\b.{0,30}(\$|round|series|funding)|\braises?\b.{0,20}\$", re.I)
IMMINENT = re.compile(r"(in talks to raise|is raising|to raise|nearing (a )?(deal|round)|reportedly (in talks|raising)|seeking to raise|looking to raise|new funding round)", re.I)
FIN = re.compile(r"\b(cfo|chief financial|vp finance|vp of finance|head of finance|controller|chief revenue|cro|vp sales)\b.{0,25}(hire|hires|appoint|appoints|names|joins|new)|\b(appoints?|names?|hires?)\b.{0,25}\b(cfo|chief financial|finance chief|cro|chief revenue)\b", re.I)
MOM = re.compile(r"\b(launches?|launched|partners? with|partnership|customers?|expands?|doubles?|milestone|new product|general availability|acquires?)\b", re.I)
STAGE_RE = re.compile(r"series\s+([a-e])\b", re.I)
STOP = {"the", "inc", "labs", "ai", "app", "io", "co", "company", "technologies", "capital", "ventures", "group"}


def mentions(title, name):
    """Strict: require the company's distinctive name token(s) in the TITLE (not just GDELT's body match).
    Kills 'Lux Capital' matching a story that only contains the generic word 'capital'."""
    toks = [t for t in re.findall(r"[a-z0-9]{3,}", (name or "").lower()) if t not in STOP]
    tl = (title or "").lower()
    if not toks:
        return (name or "").lower() in tl
    # require the most distinctive (first non-stopword) token; if multi-token, require >=1 distinctive hit
    return any(t in tl for t in toks)


def fetch_json(url, timeout=20, headers=None):
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                continue
            return None
        except Exception:
            return None
    return None


def harmonic_funding(name, domain):
    """Accurate last-raise + stage via Harmonic, resolved BY DOMAIN. {} if no key / not found."""
    if not KEY:
        return {}
    q = domain or name
    d = fetch_json(HBASE + "/search/typeahead?" + urllib.parse.urlencode({"query": q}), headers=HHEAD)
    cand = None
    if isinstance(d, dict):
        for k in ("results", "companies", "hits", "data", "entities"):
            if isinstance(d.get(k), list) and d[k]:
                cand = d[k]; break
        if cand is None and (d.get("name") or d.get("id") or d.get("entity_urn")):
            cand = [d]
    elif isinstance(d, list):
        cand = d
    if not cand:
        return {}
    it = cand[0] if isinstance(cand[0], dict) else {}
    ident = str(it.get("id") or it.get("company_id") or it.get("entity_urn") or it.get("urn") or "")
    m = re.search(r"(\d+)\s*$", ident); cid = m.group(1) if m else ident
    for u in [HBASE + "/companies/" + urllib.parse.quote(cid, safe=""), HBASE + "/companies/" + urllib.parse.quote(ident, safe="")]:
        if not cid:
            break
        full = fetch_json(u, headers=HHEAD)
        if isinstance(full, dict) and (full.get("name") or full.get("legal_name")):
            return full.get("funding") or {}
    return it.get("funding") or {}


def gdelt_articles(name, maxrec=75):
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


def pretty_stage(s):
    return (s or "").replace("SERIES_", "Series ").replace("_", " ").title().replace("Series ", "Series ").strip()


def score(comp):
    name = comp.get("name"); domain = comp.get("domain", "")
    slug = re.sub(r"[^a-z0-9]+", "-", (comp.get("slug") or name or "").lower()).strip("-")
    print("•", name)

    # accurate anchor via Harmonic by domain
    hf = harmonic_funding(name, domain)
    last_raise = (hf.get("last_funding_at") or hf.get("lastFundingAt") or "")[:10]
    stage = pretty_stage(hf.get("funding_stage") or hf.get("fundingStage") or "")
    total = hf.get("funding_total") or hf.get("fundingTotal")
    src_note = "Harmonic (by domain)" if last_raise else ""

    # strict, on-topic articles only
    arts = [a for a in gdelt_articles(name) if mentions(a["title"], name)]

    # fallback dating if Harmonic gave nothing
    if not last_raise:
        fd = edgar_latest(name)
        raised = [a for a in arts if a["date"] and RAISED_PAST.search(a["title"])]
        news_raise = raised[0]["date"] if raised else ""
        last_raise = max([d for d in [fd, news_raise] if d] or [""])
        if last_raise:
            src_note = "Form D / news"
        if not stage:
            for a in raised[:3]:
                mm = STAGE_RE.search(a["title"])
                if mm:
                    stage = "Series " + mm.group(1).upper(); break

    months = months_since(last_raise)
    snap = latest_snapshot(slug)
    signals = []; links = []

    # on-topic evidence
    imm = [a for a in arts if a["date"] and IMMINENT.search(a["title"]) and _recent(a["date"], 4)]
    fh = [a for a in arts if FIN.search(a["title"]) and _recent(a["date"], 9)]
    mh = [a for a in arts if MOM.search(a["title"]) and _recent(a["date"], 4)]
    open_cfo = bool(snap.get("finance_leadership_open"))
    open_gtm = bool(snap.get("gtm_leadership_open"))

    # stage-aware cadence -> where in the funding cycle are they?
    CADENCE = {"Seed": 15, "Series A": 18, "Series B": 22, "Series C": 27, "Series D": 33}
    typ = CADENCE.get(stage, 20)
    ratio = (months / typ) if months is not None else None
    if months is None:
        cycle = "unknown"
    elif months < 8 or (ratio is not None and ratio < 0.45):
        cycle = "just raised"
    elif ratio < 0.8:
        cycle = "mid-cycle"
    elif ratio <= 1.25:
        cycle = "approaching"
    else:
        cycle = "overdue"

    # qualitative status + likelihood (no numeric score)
    if imm:
        status, likelihood, rank = "Raising now — press chatter", "Active", 5
    elif cycle in ("approaching", "overdue") and (open_cfo or fh):
        status, likelihood, rank = "High chance soon", "High", 4
    elif cycle == "approaching":
        status, likelihood, rank = "Entering raise window", "Medium", 3
    elif cycle == "overdue":
        status, likelihood, rank = "Overdue — watch", "Medium", 3
    elif cycle == "mid-cycle" and (open_cfo or fh):
        status, likelihood, rank = "Mid-cycle, hiring finance leadership", "Medium", 3
    elif cycle == "mid-cycle":
        status, likelihood, rank = "Mid-cycle", "Low", 2
    elif cycle == "just raised":
        status, likelihood, rank = "Just raised — not soon", "Very low", 1
    else:
        status, likelihood, rank = "Unknown — no round data", "—", 0

    # evidence lines
    if months is not None:
        cyc_txt = {"just raised": "just raised", "mid-cycle": "mid-cycle",
                   "approaching": "approaching typical raise window", "overdue": "past typical cadence"}.get(cycle, "")
        signals.append("%d mo since last round%s · typical %s cadence ~%d mo · %s" % (
            months, " (" + stage + ")" if stage else "", stage or "round", typ, cyc_txt))
    else:
        signals.append("No dated prior round found")
    if imm:
        signals.append("Imminent-raise chatter: “%s”" % imm[0]["title"][:95]); links.append(imm[0]["link"])
    if open_cfo:
        signals.append("Open finance-leadership role (CFO/VP Finance) on careers page")
    elif open_gtm:
        signals.append("Open GTM-leadership role (CRO/VP Sales) on careers page")
    if fh:
        signals.append("Finance/GTM leadership hire: “%s”" % fh[0]["title"][:95]); links.append(fh[0]["link"])
    if snap.get("open_roles_total"):
        signals.append("%d open roles now (fin=%s sales=%s eng=%s)" % (
            snap.get("open_roles_total"), snap.get("roles_finance"), snap.get("roles_sales"), snap.get("roles_eng")))
    if mh:
        signals.append("Momentum/PR: “%s”" % mh[0]["title"][:95]); links.append(mh[0]["link"])

    return {
        "name": name, "domain": domain, "stage": stage,
        "months_since": months, "last_raise_date": last_raise, "last_raise_source": src_note,
        "funding_total": total, "cycle": cycle,
        "status": status, "likelihood": likelihood, "rank": rank,
        "finance_leadership_open": open_cfo, "open_roles": snap.get("open_roles_total"),
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
    out.sort(key=lambda x: (-(x.get("rank") or 0), -(x.get("months_since") or 0)))
    json.dump({"generated": TODAY.isoformat(), "companies": out}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote pipeline_scored.json (%d companies, hybrid)" % len(out))


if __name__ == "__main__":
    main()
