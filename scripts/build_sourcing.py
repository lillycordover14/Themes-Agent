#!/usr/bin/env python3
"""SPC Sourcing Engine — daily candidate builder (pure Python, free, no tokens).

Finds recently-raised companies that fit Smith Point Capital's thesis and stages them for the
Sourcing tab. Two sources (per Lilly): (1) funds-tab raises via data/insights.json (already deduped,
dated, themed, with investors), and (2) a broad GDELT news sweep for raises in SPC's themes that the
tracked funds didn't lead. Applies the fit filter from data/spc_network.json (4 SPC themes + applied-AI
verticals; sweet-spot vs watchlist tiers; drops the categories SPC repeatedly passes on), then does a
FREE first-pass connection guess by scraping each company's exec bios and matching prior employers /
schools / known co-investors to the SPC network graph.

This is the free daily layer. The authoritative connection layer is the WEEKLY Affinity/Harmonic
enrichment (see scripts/enrich_sourcing_prompt.md), which overwrites the connection fields with real
warm paths. Fail-safe throughout; writes data/sourcing_candidates.json.
"""
import json, os, re, time, datetime, urllib.parse, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INS = os.path.join(ROOT, "data", "insights.json")
NET = os.path.join(ROOT, "data", "spc_network.json")
PIPE = os.path.join(ROOT, "data", "pipeline.json")
OUT = os.path.join(ROOT, "data", "sourcing_candidates.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TODAY = datetime.date.today()
RECENT_DAYS = 45           # "recently raised" window for weekly clearing
FETCH_CAP = int(os.environ.get("SOURCING_FETCH_CAP", "60"))   # max company sites to scrape for connections

RAISE_V = re.compile(r"\b(raises?|raised|secures?|secured|lands?|landed|closes?|closed|nets?|snags?|nabs?|bags?)\b", re.I)
AMT = re.compile(r"\$\s?(\d[\d.,]*)\s?(k|m|mn|million|b|bn|billion)\b", re.I)
STAGE_BUCKET = re.compile(r"\b(pre-?seed|angel|seed|series\s?([a-e])|growth round|late[- ]stage|mezzanine)\b", re.I)
PRIOR = re.compile(r"\b(?:previously|prior(?:ly)?|formerly|ex-|before(?: joining)?|was at|came from|spent .* at|veteran of|alum(?:nus|na)? of)\b[^.]{0,90}", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def fetch_json(url, timeout=20):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except Exception:
        return None


def fetch_text(url, timeout=12):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        raw = urllib.request.urlopen(req, timeout=timeout).read()
        return raw.decode("utf-8", "replace")
    except Exception:
        return ""


def strip_html(html):
    html = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    html = re.sub(r"&[a-z#0-9]+;", " ", html)
    return re.sub(r"\s+", " ", html).strip()


# ---------- fit ----------
def load_net():
    try:
        return json.load(open(NET, encoding="utf-8"))
    except Exception:
        return {}


def theme_and_vertical(text, net):
    t = (text or "").lower()
    fit = net.get("fit", {})
    best, n = "", 0
    for label, kws in fit.get("themes", {}).items():
        c = sum(1 for k in kws if k in t)
        if c > n:
            best, n = label, c
    vert = ""
    for v in fit.get("applied_ai_verticals", []):
        if v in t:
            vert = v.title(); break
    return best, vert, n


def pass_check(text, net):
    """Return (exclude, reason) using SPC's repeatedly-passed categories/keywords."""
    t = (text or "").lower()
    ps = net.get("fit", {}).get("pass_signals", {})
    for c in ps.get("categories", []):
        if c in t:
            return True, "matches a category SPC has passed on (%s)" % c
    hits = [k for k in ps.get("keywords_downrank", []) if k in t]
    if hits:
        return True, "off-thesis signal: %s" % ", ".join(hits[:3])
    return False, ""


def months_ago_days(iso):
    try:
        y, mo, dd = map(int, iso[:10].split("-"))
        return (TODAY - datetime.date(y, mo, dd)).days
    except Exception:
        return None


def stage_norm(s):
    s = (s or "").strip()
    m = STAGE_BUCKET.search(s.lower())
    if s in ("Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Growth/Late", "Venture"):
        return s
    if not m:
        return s or "Venture"
    g = m.group(0).lower()
    if "pre" in g or "angel" in g:
        return "Pre-seed"
    if "seed" in g:
        return "Seed"
    if "growth" in g or "late" in g or "mezz" in g:
        return "Growth/Late"
    if m.group(2):
        return "Series " + m.group(2).upper()
    return "Venture"


def tier_of(stage, amount_m, net):
    """actionable (sweet spot) vs watchlist vs skip-too-late."""
    sw = net["fit"]["sweet_spot"]; wl = net["fit"]["watchlist"]
    a = amount_m or 0
    if stage in ("Series B", "Series C"):
        if a >= 400:
            return "actionable", "large %s ($%dM) — likely late; confirm it's not already priced out" % (stage, a)
        return "actionable", "%s%s — growth-stage sweet spot" % (stage, (" ($%dM)" % a) if a else "")
    if stage == "Series A":
        if a >= sw["min_raise_m_hint"]:
            return "actionable", "Series A ($%dM) — sizable A, likely at/near the ARR floor" % a
        return "watchlist", "Series A%s — track for the next round" % ((" ($%dM)" % a) if a else "")
    if stage in ("Seed", "Pre-seed"):
        return "watchlist", "%s — early; track for traction" % stage
    if stage in ("Growth/Late",):
        return "actionable", "growth/late — confirm still in the <$250M-rev band"
    return "watchlist", "stage unconfirmed — track"


# ---------- free connection pass ----------
def exec_pages(domain):
    base = domain if domain.startswith("http") else "https://" + domain
    base = base.rstrip("/")
    return [base, base + "/team", base + "/about", base + "/about-us", base + "/company", base + "/leadership", base + "/our-team"]


def free_connections(domain, investors, net):
    """Scrape exec bios; match prior employers / schools to SPC network; match investors to co-investors.
    Returns list of {kind, detail}. Fail-safe / best-effort (LinkedIn is blocked, so coverage is partial)."""
    out = []
    # investor overlap (no fetch needed)
    coinv = {norm(x) for x in net.get("co_investors", [])}
    for inv in (investors or []):
        if norm(inv) in coinv:
            out.append({"kind": "co-investor", "detail": "Backed by %s — a fund SPC gets intros through" % inv})
    if not domain:
        return out[:6]
    emp = {e.lower(): e for e in net.get("network_employers", [])}
    sch = {s.lower(): s for s in net.get("network_schools", [])}
    # reverse index: which SPC people (team + Precision Advisory Network) share each employer / school
    emp_people, sch_people = {}, {}
    for grp in ("team", "advisors"):
        for mem in net.get(grp, []):
            who = mem.get("name", "")
            for e in mem.get("employers", []):
                emp_people.setdefault(e.lower(), []).append(who)
            for sc in mem.get("schools", []):
                sch_people.setdefault(sc.lower(), []).append(who)
    def wholist(names):
        names = [n for n in names if n]
        if not names:
            return "SPC"
        return names[0] if len(names) == 1 else (names[0] + " + %d more" % (len(names) - 1) if len(names) > 2 else " & ".join(names))
    text = ""
    for url in exec_pages(domain):
        html = fetch_text(url)
        if html:
            text += " " + strip_html(html)[:20000]
        if len(text) > 40000:
            break
    tl = text.lower()
    seen = set()
    for frag in PRIOR.findall(text):
        fl = frag.lower()
        for k, v in emp.items():
            if k in fl and v not in seen:
                seen.add(v); out.append({"kind": "experience", "detail": "Exec previously at %s — shared work history with %s (SPC)" % (v, wholist(emp_people.get(k, [])))})
    # employer mentions even without an explicit 'prior' cue (bios often list logos/companies)
    for k, v in emp.items():
        if v not in seen and re.search(r"\b" + re.escape(k) + r"\b", tl):
            seen.add(v); out.append({"kind": "experience", "detail": "Team overlaps with %s — shared with %s (SPC)" % (v, wholist(emp_people.get(k, [])))})
    for k, v in sch.items():
        if re.search(r"\b" + re.escape(k) + r"\b", tl) and v not in seen:
            seen.add(v); out.append({"kind": "school", "detail": "%s alum — shared alma mater with %s (SPC)" % (v, wholist(sch_people.get(k, [])))})
    # de-dupe, cap
    uniq = []
    keys = set()
    for c in out:
        kk = (c["kind"], c["detail"])
        if kk not in keys:
            keys.add(kk); uniq.append(c)
    return uniq[:6]


def main():
    net = load_net()
    if not net:
        print("no spc_network.json — aborting fail-safe"); 
        json.dump({"generated": TODAY.isoformat(), "actionable": [], "watchlist": [], "note": "network graph missing"}, open(OUT, "w"))
        return
    try:
        raises = json.load(open(INS, encoding="utf-8")).get("raises", [])
    except Exception as e:
        print("no insights.json:", e); raises = []

    cands = {}
    FUND_STOP = {"menlo","accel","sequoia","redpoint","bessemer","lightspeed","kleiner","kleinerperkins","insight",
                 "insightpartners","khosla","coatue","felicis","greylock","benchmark","battery","index","pear","thrive",
                 "a16z","andreessen","foundersfund","generalcatalyst","menloventures","iconiq","ivp","nea","gv"}
    def consider(company, desc, stage, amount_m, investors, date, link, domain, src):
        company = re.sub(r"^(?:fintech|healthtech|insurtech|proptech|legaltech|climatetech|trading app|pitch deck:?)\s+", "", (company or ""), flags=re.I).strip(" :-")
        k = norm(company)
        if not k or len(company) < 3:
            return
        if k in FUND_STOP or "pitch deck" in company.lower() or "ex-apple" in company.lower():
            return   # a fund, or a headline fragment — not a portfolio company
        blob = company + " . " + (desc or "")
        theme, vert, tscore = theme_and_vertical(blob, net)
        if not theme:
            return  # not in an SPC theme
        excl, reason = pass_check(blob, net)
        if excl:
            cands.setdefault("_excluded", 0)
            cands["_excluded"] += 1
            return
        st = stage_norm(stage)
        tier, why = tier_of(st, amount_m, net)
        row = cands.get(k)
        if row and (date or "") <= (row.get("date") or ""):
            return
        cands[k] = {"company": company, "desc": (desc or "")[:200], "theme": theme, "vertical": vert,
                    "stage": st, "amount_m": amount_m, "investors": investors[:8], "date": date,
                    "link": link, "domain": domain, "tier": tier, "fit_reason": why, "source": src}

    # 1) funds-tab raises (insights.json), recent window
    for r in raises:
        d = (r.get("date") or "")[:10]
        da = months_ago_days(d)
        if da is None or da > RECENT_DAYS:
            continue
        dom = ""   # never derive a domain from a news article; real domains come from enrichment
        consider(r.get("company", ""), r.get("desc") or r.get("theme", ""), r.get("stage", ""),
                 r.get("amount_m"), r.get("investors") or [], d, (r.get("link") or ""), dom, "funds")

    # 2) broad GDELT news sweep for recent raises across SPC verticals
    verticals = [] if os.environ.get("SOURCING_SKIP_NEWS") else ["healthcare AI", "legal AI", "procurement software", "supply chain AI", "manufacturing AI",
                 "industrial AI", "insurance software", "data infrastructure", "edge computing", "compliance software"]
    for v in verticals:
        q = '"%s" (raises OR "series a" OR "series b" OR "series c" OR funding)' % v
        url = ("https://api.gdeltproject.org/api/v2/doc/doc?query=%s&mode=artlist&format=json"
               "&maxrecords=25&sort=datedesc&timespan=%dd" % (urllib.parse.quote(q), RECENT_DAYS + 5))
        d = fetch_json(url) or {}
        for a in (d.get("articles") or [])[:25]:
            title = (a.get("title") or "").strip()
            if not title or not RAISE_V.search(title):
                continue
            sd = (a.get("seendate") or "")[:8]
            try:
                iso = "%s-%s-%s" % (sd[0:4], sd[4:6], sd[6:8])
            except Exception:
                iso = ""
            co = title[:RAISE_V.search(title).start()].strip(" -–—:·|")
            co = re.sub(r"\s*[|–—-]\s*.*$", "", co).strip()
            if not co or len(co.split()) > 5 or norm(co) in {"ai", "the", "startup"}:
                continue
            amt = None
            am = AMT.search(title)
            if am:
                try:
                    val = float(am.group(1).replace(",", "")); u = am.group(2).lower()
                    amt = round(val * 1000) if u in ("b", "bn", "billion") else round(val)
                except Exception:
                    amt = None
            sm = STAGE_BUCKET.search(title.lower())
            consider(co, title, sm.group(0) if sm else "", amt, [], iso, a.get("url", ""), "", "news")
        time.sleep(0.15)

    excluded = cands.pop("_excluded", 0)
    rows = list(cands.values())
    # free connection pass (bounded)
    fetched = 0; t0 = time.time()
    for r in rows:
        if fetched < FETCH_CAP and (time.time() - t0) < 200:
            r["connections"] = free_connections(r.get("domain", ""), r.get("investors", []), net)
            if r.get("domain"):
                fetched += 1
        else:
            r["connections"] = free_connections("", r.get("investors", []), net)  # investor-only, no fetch
        r["connection_status"] = "prospective (web) — confirmed weekly via Affinity" if r["connections"] else "no connection surfaced — good to flag"

    def sort_key(r):
        return (1 if r["tier"] == "actionable" else 0, r.get("date") or "", r.get("amount_m") or 0)
    rows.sort(key=sort_key, reverse=True)
    actionable = [r for r in rows if r["tier"] == "actionable"]
    watchlist = [r for r in rows if r["tier"] == "watchlist"]

    out = {"generated": TODAY.isoformat(), "window_days": RECENT_DAYS,
           "counts": {"actionable": len(actionable), "watchlist": len(watchlist), "excluded_off_thesis": excluded},
           "actionable": actionable[:60], "watchlist": watchlist[:60],
           "enriched": False, "enriched_at": None}
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote sourcing_candidates.json — %d actionable, %d watchlist, %d excluded (fetched %d sites)"
          % (len(actionable), len(watchlist), excluded, fetched))


if __name__ == "__main__":
    main()
