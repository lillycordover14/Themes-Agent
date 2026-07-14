#!/usr/bin/env python3
"""Raising-Soon scorer for pipeline companies (data/pipeline.json).
Signals: runway timing (Harmonic last round), finance/exec hire + raise chatter + momentum (Google News).
Runs inside the Harmonic step (uses HARMONIC_API_KEY). Fail-safe; writes data/pipeline_scored.json."""
import json, os, re, sys, datetime, urllib.parse, urllib.request
try:
    import feedparser
except Exception:
    feedparser = None

KEY = os.environ.get("HARMONIC_API_KEY", "").strip()
BASE = os.environ.get("HARMONIC_BASE", "https://api.harmonic.ai").rstrip("/")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "data", "pipeline.json")
OUT = os.path.join(ROOT, "data", "pipeline_scored.json")
UA = "Mozilla/5.0 (ThemesAgent)"
H = {"apikey": KEY, "accept": "application/json", "content-type": "application/json"}
RAISE = re.compile(r"\b(raises?|raising|in talks|closes?\s+\$|series\s+[a-e]\b|\$\d+\s*(m|million|b|billion))\b", re.I)
FIN = re.compile(r"\b(cfo|vp finance|head of finance|chief of staff|hires?|appoints?|names?)\b", re.I)


def hcall(url, method="GET", body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, headers=H, method=method)
    with urllib.request.urlopen(r, timeout=45) as resp:
        return json.loads(resp.read())


def enrich(name, domain):
    """Resolve the company via typeahead, then fetch its full record (funding, headcount)."""
    if not KEY:
        return {}
    q = domain or name
    try:
        d = hcall(BASE + "/search/typeahead?" + urllib.parse.urlencode({"query": q}))
    except Exception as e:
        print("  typeahead failed:", e); return {}
    cand = None
    if isinstance(d, dict):
        for k in ("results", "companies", "hits", "data", "entities"):
            v = d.get(k)
            if isinstance(v, list) and v:
                cand = v; break
        if cand is None and (d.get("name") or d.get("entity_urn") or d.get("id")):
            cand = [d]
    elif isinstance(d, list):
        cand = d
    if not cand:
        print("  typeahead: no candidates (keys=%s)" % (list(d.keys()) if isinstance(d, dict) else type(d).__name__)); return {}
    it = cand[0] if isinstance(cand[0], dict) else {}
    ident = str(it.get("id") or it.get("company_id") or it.get("entity_urn") or it.get("urn") or "")
    m = re.search(r"(\d+)\s*$", ident)
    cid = m.group(1) if m else ident
    for u in [BASE + "/companies/" + urllib.parse.quote(cid, safe=""), BASE + "/companies/" + urllib.parse.quote(ident, safe="")]:
        if not cid:
            break
        try:
            full = hcall(u)
            if isinstance(full, dict) and (full.get("name") or full.get("legal_name")):
                print("  enriched via %s | funding=%s headcount=%s" % (
                    u.split("/")[-1],
                    bool((full.get("funding") or {}).get("last_funding_at")),
                    full.get("corrected_headcount") or full.get("headcount")))
                return full
        except Exception as e:
            print("  companies/{id} failed:", e)
    print("  falling back to shallow typeahead item (keys=%s)" % list(it.keys()))
    return it


def gnews(q, days=120):
    if not feedparser:
        return []
    url = "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=en-US&gl=US&ceid=US:en"
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=25).read()
        f = feedparser.parse(raw)
    except Exception:
        return []
    cut = datetime.date.today() - datetime.timedelta(days=days)
    out = []
    for e in f.entries[:20]:
        dt = None
        for k in ("published_parsed", "updated_parsed"):
            if e.get(k):
                dt = datetime.date(*e[k][:3]); break
        if dt and dt < cut:
            continue
        out.append({"title": (e.get("title") or "")[:170], "link": e.get("link", "")})
    return out


def score(comp):
    name = comp.get("name"); domain = comp.get("domain", "")
    print("•", name)
    h = enrich(name, domain)
    sc = 0; signals = []
    f = h.get("funding") or {}
    lfa = f.get("last_funding_at") or ""
    stage = (f.get("funding_stage") or "").replace("SERIES_", "Series ").replace("_", " ").title()
    months = None
    if lfa:
        try:
            y, mo, dd = map(int, lfa[:10].split("-")); months = round((datetime.date.today() - datetime.date(y, mo, dd)).days / 30.4)
        except Exception:
            months = None
    if months is not None:
        if 14 <= months <= 30:
            r = round(max(0, 30 * (1 - abs(months - 20) / 12)))
            sc += r; signals.append("Runway: %d mo since last round%s — in the raise window" % (months, " (%s)" % stage if stage else ""))
        else:
            signals.append("Last round %d mo ago%s" % (months, " (%s)" % stage if stage else ""))
    hc = h.get("corrected_headcount") or h.get("headcount")
    rh = [x for x in gnews('"%s" (raises OR raising OR "in talks to raise" OR "Series" OR closes)' % name) if RAISE.search(x["title"])]
    fh = [x for x in gnews('"%s" (CFO OR "VP Finance" OR "Head of Finance" OR "Chief of Staff")' % name) if FIN.search(x["title"])]
    mh = gnews('"%s" (launches OR "partners with" OR customers OR expands OR doubles OR milestone)' % name)
    links = []
    if rh:
        sc += 35; signals.append("Raise chatter: “%s”" % rh[0]["title"][:95]); links.append(rh[0]["link"])
    if fh:
        sc += 25; signals.append("Finance/exec hire signal: “%s”" % fh[0]["title"][:95]); links.append(fh[0]["link"])
    if mh:
        sc += 10; signals.append("Momentum/PR: “%s”" % mh[0]["title"][:95]); links.append(mh[0]["link"])
    if not signals:
        signals.append("No strong pre-raise signals yet")
    return {"name": name, "domain": domain, "score": min(100, sc), "stage": stage, "months_since": months,
            "headcount": hc, "signals": signals[:6], "url": ("https://" + domain if domain else ""), "links": links[:3]}


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
            out.append({"name": c.get("name"), "domain": c.get("domain", ""), "score": 0, "signals": ["data unavailable this run"], "url": ("https://" + c.get("domain", "")) if c.get("domain") else "", "links": []})
    out.sort(key=lambda x: -(x.get("score") or 0))
    json.dump({"generated": datetime.date.today().isoformat(), "companies": out}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote pipeline_scored.json (%d companies)" % len(out))


if __name__ == "__main__":
    main()
