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
FIN_HIRE = re.compile(r"\b(cfo|chief financial officer|vp\s*(of\s*)?finance|head of finance|financial controller|\bcontroller\b|head of fp&a)\b", re.I)
REV_HIRE = re.compile(r"\b(cro|chief revenue officer|vp\s*(of\s*)?sales|head of sales|chief commercial|cmo|chief marketing officer|head of revenue|head of gtm)\b", re.I)
HIRE_VERB = re.compile(r"\b(hires?|hired|appoints?|appointed|names?|named|joins?|joined|welcomes?|adds?|taps?|brings on)\b", re.I)
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


def history(slug):
    path = os.path.join(HIST_DIR, slug + ".jsonl")
    if not os.path.exists(path):
        return []
    try:
        rows = [json.loads(l) for l in open(path, encoding="utf-8").read().splitlines() if l.strip()]
        rows.sort(key=lambda r: r.get("date", ""))
        return rows
    except Exception:
        return []


def _days_between(a, b):
    try:
        ya, ma, da = map(int, a[:10].split("-")); yb, mb, db = map(int, b[:10].split("-"))
        return abs((datetime.date(yb, mb, db) - datetime.date(ya, ma, da)).days)
    except Exception:
        return 0


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

    arts = [a for a in gdelt_articles(name) if mentions(a["title"], name)]

    # ANCHOR last-raise on the MOST RECENT of Harmonic-by-domain and a web-detected completed raise
    # (Harmonic can lag real announcements — e.g. it missed Taktile's $110M round).
    hf = harmonic_funding(name, domain)
    h_date = (hf.get("last_funding_at") or hf.get("lastFundingAt") or "")[:10]
    stage = pretty_stage(hf.get("funding_stage") or hf.get("fundingStage") or "")
    total = hf.get("funding_total") or hf.get("fundingTotal")

    web_raised = [a for a in arts if a["date"] and RAISED_PAST.search(a["title"])]
    web_date = web_raised[0]["date"] if web_raised else ""

    last_raise = ""; src_note = ""
    cands = [d for d in [h_date, web_date] if d]
    if cands:
        last_raise = max(cands)
        if web_date and last_raise == web_date and (not h_date or web_date > h_date):
            src_note = "recent raise in news" + (" (Harmonic lags)" if h_date and web_date > h_date else "")
            mm = STAGE_RE.search(web_raised[0]["title"]) if web_raised else None
            if mm:
                stage = "Series " + mm.group(1).upper()
        else:
            src_note = "Harmonic (by domain)"
    else:
        fd = edgar_latest(name)
        if fd:
            last_raise = fd; src_note = "SEC Form D"
    months = months_since(last_raise)

    # stage-aware cadence -> cycle position
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

    # ---- backtest-supported signal set ----
    snap = latest_snapshot(slug)
    rows = history(slug)

    def _news(rx, mo):
        return [x for x in arts if x["date"] and rx.search(x["title"]) and HIRE_VERB.search(x["title"]) and _recent(x["date"], mo)]

    imm = [x for x in arts if x["date"] and IMMINENT.search(x["title"]) and not RAISED_PAST.search(x["title"]) and _recent(x["date"], 4)]
    fin_hire = _news(FIN_HIRE, 9)          # finance-leadership hire in the news (late-stage signal)
    rev_hire = _news(REV_HIRE, 9)          # revenue/GTM-leadership hire — MOST consistent hire signal in the pilot
    mh = [x for x in arts if MOM.search(x["title"]) and _recent(x["date"], 4)]
    open_cfo = bool(snap.get("finance_leadership_open"))
    open_gtm = bool(snap.get("gtm_leadership_open"))

    # hiring trajectory from our own point-in-time log (needs >=2 snapshots spanning >=14d)
    ramp = freeze = False; roles_note = ""
    if len(rows) >= 2 and _days_between(rows[0].get("date", ""), rows[-1].get("date", "")) >= 14:
        first = rows[0].get("open_roles_total") or 0
        last = rows[-1].get("open_roles_total") or 0
        peak = max((r.get("open_roles_total") or 0) for r in rows)
        if first >= 3 and last >= first * 1.3:
            ramp = True; roles_note = "open roles %d\u2192%d" % (first, last)
        elif peak >= 10 and last <= peak * 0.7:
            freeze = True; roles_note = "hiring cooled from peak %d to %d" % (peak, last)
    # press pickup (from the day's snapshot: 30d vs 90d run-rate)
    p30 = snap.get("press_30d") or 0; p90 = snap.get("press_90d") or 0
    press_spike = p30 >= 3 and p30 >= (p90 / 3.0) * 1.5

    # classify signals into STRONG (high-precision, backtest-supported) vs SUPPORTING.
    # finance-leadership is treated as STRONG only at later stages (the pilot showed it is a C/D tell);
    # revenue-leadership is STRONG at all stages (most consistent). hiring-freeze-after-ramp is the
    # classic pre-close pattern -> STRONG.
    late = stage in ("Series B", "Series C", "Series D") or stage == ""
    strong = []; supp = []
    if rev_hire:
        strong.append(("Revenue/GTM-leadership hire: \u201c%s\u201d" % rev_hire[0]["title"][:90], rev_hire[0]["link"]))
    if open_gtm:
        strong.append(("Open GTM-leadership role (CRO/VP Sales) on careers page", None))
    if fin_hire:
        (strong if late else supp).append(("Finance-leadership hire: \u201c%s\u201d" % fin_hire[0]["title"][:90], fin_hire[0]["link"]))
    if open_cfo:
        (strong if late else supp).append(("Open finance-leadership role (CFO/VP Finance) on careers page", None))
    if freeze:
        strong.append(("Hiring cooled after a ramp \u2014 classic pre-close pattern (%s)" % roles_note, None))
    if ramp:
        supp.append(("Hiring ramp: %s" % roles_note, None))
    if press_spike:
        supp.append(("Press pickup: %d articles in 30d (vs %d in 90d)" % (p30, p90), None))
    if mh:
        supp.append(("Momentum/PR: \u201c%s\u201d" % mh[0]["title"][:90], mh[0]["link"]))
    S = len(strong); M = len(supp)

    # ---- tiered status (defer to signals; else cadence) ----
    if imm:
        status, lk, rank, basis = "Raising now \u2014 press chatter", "Active", 5, "signal"
    elif cycle == "just raised":
        status, lk, rank, basis = "Just raised \u2014 not soon", "Very low", 1, "cadence"
    elif S >= 2 or (S >= 1 and cycle in ("approaching", "overdue")):
        status, lk, rank, basis = "High chance soon", "High", 4, "signal"
    elif S >= 1:
        status, lk, rank, basis = "Signals building \u2014 watch", "Medium", 3, "signal"
    elif M >= 2 and cycle in ("approaching", "overdue"):
        status, lk, rank, basis = "Heating up (hiring/press)", "Medium", 3, "signal"
    elif M >= 1 and cycle == "approaching":
        status, lk, rank, basis = "Entering window + momentum", "Medium", 3, "signal"
    elif cycle == "approaching":
        status, lk, rank, basis = "Entering raise window", "Medium", 3, "cadence"
    elif cycle == "overdue":
        status, lk, rank, basis = "Overdue \u2014 watch", "Medium", 3, "cadence"
    elif cycle == "mid-cycle":
        status, lk, rank, basis = "Mid-cycle", "Low", 2, "cadence"
    else:
        status, lk, rank, basis = "Unknown \u2014 no round data", "\u2014", 0, "none"

    # ---- evidence ----
    signals = []; links = []
    if months is not None:
        cyc_txt = {"just raised": "just raised", "mid-cycle": "mid-cycle",
                   "approaching": "approaching typical raise window", "overdue": "past typical cadence"}.get(cycle, "")
        signals.append("%d mo since last round%s \u00b7 typical %s cadence ~%d mo \u00b7 %s" % (
            months, " (" + stage + ")" if stage else "", stage or "round", typ, cyc_txt))
        if src_note:
            signals.append("Last round: %s (%s)" % (last_raise, src_note))
    else:
        signals.append("No dated prior round found")
    for label, link in (strong + supp):
        signals.append(label)
        if link:
            links.append(link)
    signals.append("Basis: " + ("live signal" if basis == "signal" else "cadence only (no live signals yet)" if basis == "cadence" else "insufficient data"))

    return {
        "name": name, "domain": domain, "stage": stage,
        "months_since": months, "last_raise_date": last_raise, "last_raise_source": src_note,
        "funding_total": total, "cycle": cycle, "basis": basis,
        "status": status, "likelihood": lk, "rank": rank,
        "strong_signals": S, "supporting_signals": M,
        "finance_leadership_open": open_cfo, "open_roles": snap.get("open_roles_total"),
        "signals": signals[:8], "url": ("https://" + domain if domain else ""), "links": links[:3],
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
