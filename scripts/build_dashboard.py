#!/usr/bin/env python3
"""Build index.html from data/tailwinds.json + data/funds.json using scripts/dashboard_template.html.
Also folds in Harmonic saved-search companies (data/harmonic_raises.json) if present, since the
Harmonic pull runs before this build. Pure, no network."""
import json, os, base64, re
PW_HASH = "1d5aaaa4c93515f767b7fe618476505c1bfefdb92db1625648f46e3c431a16a8"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(ROOT, "data", "tailwinds.json"), encoding="utf-8"))
FUNDS = json.load(open(os.path.join(ROOT, "data", "funds.json"), encoding="utf-8"))
if os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"):
    try:
        import subprocess, sys as _sys
        subprocess.run([_sys.executable, os.path.join(HERE, "synthesize_pov.py")])
        FUNDS = json.load(open(os.path.join(ROOT, "data", "funds.json"), encoding="utf-8"))
    except Exception as _e:
        print("POV synthesis skipped:", _e)



def merge_harmonic():
    hp = os.path.join(ROOT, "data", "harmonic_raises.json")
    ep = os.path.join(ROOT, "data", "editorial.json")
    if not (os.path.exists(hp) and os.path.exists(ep)):
        return
    try:
        hd = json.load(open(hp, encoding="utf-8"))
        ED = json.load(open(ep, encoding="utf-8"))
    except Exception as e:
        print("harmonic merge skipped:", e); return
    comps = hd.get("companies", [])
    if not comps:
        return

    def classify(text):
        t = " " + (text or "").lower() + " "
        for k in ED["classify_order"]:
            for w in ED["keywords"][k]:
                if w in t:
                    return k
        return ED["classify_order"][-1]

    kname = {t["k"]: t["name"] for t in D["tailwinds"] if "k" in t}
    EARLY = ("SEED", "SERIES_A", "PRE_SEED", "ANGEL", "SERIES_A2", "SERIES_A3", "EARLY_STAGE")
    seen = {r.get("n") for r in D["recs"]}
    for c in comps:
        n = c.get("name")
        if not n or n in seen:
            continue
        stg = (c.get("stage") or "").upper()
        s = (c.get("stage") or "").replace("SERIES_", "Series ").replace("_", " ").title() or "Early Stage"
        tier = "early" if stg in EARLY else ("late" if stg.startswith("SERIES") else "early")
        tk = classify((c.get("name", "") + " " + c.get("desc", "")))
        D["recs"].append(dict(n=n, d=c.get("domain", ""), tk=tk, tn=kname.get(tk, tk), s=s, tier=tier,
                              a=int(c.get("last_amount") or 0), tot=int(c.get("total") or 0),
                              inv=", ".join(c.get("investors") or []), loc=c.get("location", ""),
                              src="Harmonic", desc=(c.get("desc") or "")[:150]))
        seen.add(n)
    # recompute aggregates so cards / KPIs / charts include Harmonic
    agg = {t["k"]: {"count": 0, "cap": 0} for t in D["tailwinds"] if "k" in t}
    for r in D["recs"]:
        a = agg.get(r.get("tk"))
        if a and r.get("tier") == "early":
            a["count"] += 1
            if (r.get("a") or 0) < 5e8:
                a["cap"] += r.get("a") or 0
    for t in D["tailwinds"]:
        if t.get("k") in agg:
            t["count"] = agg[t["k"]]["count"]; t["cap"] = agg[t["k"]]["cap"]
    stages = D.get("stages", [])
    sc = {s2: 0 for s2 in stages}
    for r in D["recs"]:
        key = r["s"] if r["s"] in sc else "Other"
        sc[key] = sc.get(key, 0) + 1
    D["sc"] = sc
    early = [r for r in D["recs"] if r.get("tier") == "early"]
    D["nAll"] = len(D["recs"]); D["nEarly"] = len(early)
    D["capEarly"] = sum((r.get("a") or 0) for r in early if (r.get("a") or 0) < 5e8)
    D["seedA"] = len([r for r in early if r["s"] in ("Seed", "Series A")])
    print("merged %d Harmonic companies into the dashboard" % len(comps))


merge_harmonic()


def compute_momentum():
    import datetime, os as _os
    hp = _os.path.join(ROOT, "data", "history.json")
    try:
        hist = json.load(open(hp, encoding="utf-8"))
    except Exception:
        hist = []
    today = datetime.date.today().isoformat()
    snap = {"date": today,
            "tw": {t["k"]: t.get("count", 0) for t in D.get("tailwinds", []) if "k" in t},
            "funds": {f["slug"]: len(f.get("updates", [])) for f in FUNDS.get("funds", [])}}
    hist = [h for h in hist if h.get("date") != today] + [snap]
    hist = hist[-120:]
    json.dump(hist, open(hp, "w", encoding="utf-8"), ensure_ascii=False)
    cutoff = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    older = [h for h in hist[:-1] if h.get("date") <= cutoff]
    base = older[-1] if older else (hist[0] if len(hist) > 1 else None)
    if not base:
        D["momentum"] = {"since": None}; return
    twd = []
    for t in D.get("tailwinds", []):
        k = t.get("k"); now = t.get("count", 0); then = base["tw"].get(k, 0)
        twd.append({"name": t.get("name"), "now": now, "delta": now - then})
    rising = []
    for f in FUNDS.get("funds", []):
        now = len(f.get("updates", [])); then = base["funds"].get(f["slug"], 0)
        if now - then > 0:
            rising.append({"name": f["name"], "delta": now - then})
    rising = sorted(rising, key=lambda x: -x["delta"])[:8]
    D["momentum"] = {"since": base["date"], "tw": twd, "rising": rising}


compute_momentum()



def compute_pov():
    """Derive each firm's 'current focus' (POV) from its recent activity + podcasts. Pure Python, no LLM."""
    import re, collections
    try:
        ED = json.load(open(os.path.join(ROOT, "data", "editorial.json"), encoding="utf-8"))
        kw = ED.get("keywords", {})
    except Exception:
        kw = {}
    kname = {t["k"]: t["name"] for t in D.get("tailwinds", []) if "k" in t}
    STOP = set(("the a an and or of to for in on with at from into over new raises raise raised series seed pre fund funds "
                "capital ventures venture partners group round million billion backs leads led invests investment invest announces "
                "podcast interview episode show host ai co founder ceo their your you our this that how why what its it is are "
                "management llc lp inc first second why-now list latest update").split())
    for f in FUNDS.get("funds", []):
        if f.get("pov_source") == "llm":
            continue
        items = [(u.get("title") or "") for u in (f.get("updates") or [])] + \
                [((p.get("title") or "") + " " + (p.get("show") or "")) for p in (f.get("podcasts") or [])]
        blob = " ".join(items).lower()
        if len([i for i in items if i.strip()]) < 2:
            continue
        tally = collections.Counter()
        for k, words in kw.items():
            c = sum(blob.count(w) for w in words)
            if c:
                tally[k] = c
        top_tw = [kname.get(k, k) for k, _ in tally.most_common(2)]
        SECTORS = {
            "AI agents": ["agent", "agentic", "copilot", "assistant"],
            "AI infra": ["inference", "gpu", " llm", "mlops", "orchestrat", "vector", "fine-tun", "compute", "foundation model"],
            "data": ["data ", "analytics", "warehouse", "pipeline", "observability"],
            "dev tools": ["developer", "devops", " sdk", "open source", "coding", "engineering"],
            "fintech": ["fintech", "payment", "banking", "lending", "insur", "underwrit", "treasury", "credit", "wealth", " tax"],
            "cybersecurity": ["security", "cyber", "threat", "identity", "zero trust", "fraud"],
            "defense/gov": ["defense", "national security", "govtech", " dod", "military", "autonom", "space"],
            "robotics/physical": ["robot", "manufactur", "industrial", "warehouse", "drone", "machine vision", "supply chain", "hardware"],
            "healthcare/bio": ["health", "clinical", "patient", "biotech", " drug", "diagnostic", "medical", "pharma"],
            "climate/energy": ["climate", "energy", " grid", "solar", "battery", "carbon", "renewable"],
            "crypto/web3": ["crypto", "blockchain", "web3", "token", "defi", "stablecoin"],
            "consumer": ["consumer", "marketplace", "creator", "commerce"],
            "vertical SaaS": ["vertical", "workflow", "legal", "construction", "logistics", "real estate", "procurement"],
            "GTM/revenue": ["gtm", "go-to-market", " revenue", " crm", "sales team"],
        }
        sec = collections.Counter()
        for label, words in SECTORS.items():
            c = sum(blob.count(w) for w in words)
            if c:
                sec[label] = c
        top_sec = [x for x, _ in sec.most_common(3)]
        parts = []
        if top_tw:
            parts.append("Leaning into " + " & ".join(top_tw))
        if top_sec:
            parts.append("active in " + ", ".join(top_sec))
        if parts:
            pv = "; ".join(parts)
            f["pov"] = pv[0].upper() + pv[1:]
    print("computed POV for %d firms" % sum(1 for f in FUNDS.get("funds", []) if f.get("pov")))


_FOCUS_CITIES = {"san francisco","menlo park","palo alto","new york","boston","cambridge","chicago",
    "seattle","austin","los angeles","denver","houston","salt lake city","durham","san jose","santa monica",
    "foster city","burlingame","oklahoma city","fort lauderdale","greenwich","woodside","madison","manhattan beach",
    "jupiter","skaneateles","niwot","portola valley","santa fe","pittsburgh","atlanta","miami","washington",
    "san diego","boulder","portland","minneapolis","dallas","philadelphia","brooklyn","mountain view","redwood city",
    "sunnyvale","bellevue","san mateo","stamford","waltham","newton","providence","ann arbor","detroit","columbus",
    "nashville","raleigh","toronto","london","berlin","paris","tel aviv","singapore","hong kong","bangalore",
    "chevy chase","tulsa","reston","tysons","santa clara","irvine","new orleans","kansas city","salt lake"}
_FOCUS_LOC = re.compile(r"\s+(?:based in|headquartered in|located in)\s+(.+)$", re.I)


def clean_focus(s):
    """Only tidy PitchBook boilerplate (leave curated focus lines untouched). No ellipsis; never end mid-word."""
    s = (s or "").strip()
    if "Founded in" not in s:          # curated focus lines (e.g. "Seed -> growth") stay exactly as written
        return s
    if s and s[-1] in ".!?)":
        return s
    c = s.rfind(". ")
    if c >= 40:                        # end at the last complete sentence
        return s[:c + 1]
    cm = s.rfind(", ")                 # drop an incomplete trailing ", State" clause -> end on the city
    if cm >= 40:
        s = s[:cm]
    s = s.rstrip(" ,;:-")
    m = _FOCUS_LOC.search(s)           # keep the city only if it's a recognized (complete) city
    if m and m.group(1).strip().rstrip(".,").lower() not in _FOCUS_CITIES:
        s = s[:m.start()].rstrip(" ,;:-")
    # strip any dangling location lead-in fragment(s) ("... firm headquarte", "... based in")
    while True:
        ns = re.sub(r"\s+(?:head\w*|based|located|in)$", "", s, flags=re.I).rstrip(" ,;:-")
        if ns == s:
            break
        s = ns
    return s


compute_pov()

for _f in FUNDS.get("funds", []):
    _f["focus"] = clean_focus(_f.get("focus"))
_active = [f for f in FUNDS.get("funds", []) if f.get("updates") or f.get("pin")]
F_DISPLAY = {"generated": FUNDS.get("generated"), "count": len(_active), "funds": _active}
print("dashboard shows %d firms with activity (of %d tracked)" % (len(_active), len(FUNDS.get("funds", []))))
try:
    PIPE = json.load(open(os.path.join(ROOT, "data", "pipeline_scored.json"), encoding="utf-8"))
except Exception:
    PIPE = {"companies": []}
BLOB = json.dumps({"D": D, "F": F_DISPLAY, "P": PIPE}, ensure_ascii=False).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
TEMPLATE = open(os.path.join(HERE, "dashboard_template.html"), encoding="utf-8").read()
html = TEMPLATE.replace("__BLOB__", BLOB)
open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(html)
print("built index.html (%d bytes) from %d funds" % (len(html), FUNDS.get("count", 0)))


def write_digest():
    import datetime as _dt
    recs = D.get("recs", [])
    tw = sorted(D.get("tailwinds", []), key=lambda t: t.get("count", 0), reverse=True)
    top_raises = sorted([r for r in recs if (r.get("a") or 0) > 0], key=lambda r: r.get("a") or 0, reverse=True)[:8]
    moves = []
    for f in FUNDS.get("funds", []):
        for u in (f.get("updates") or [])[:1]:
            if u.get("type") in ("Investment", "New fund"):
                moves.append((f.get("name"), u))
    def money(n):
        n = n or 0
        return ("$%.1fB" % (n/1e9)) if n >= 1e9 else ("$%.0fM" % (n/1e6)) if n >= 1e6 else ("$%.0fK" % (n/1e3)) if n >= 1e3 else "-"
    d = _dt.date.today().isoformat()
    L = ["# Themes Radar digest - %s" % d, ""]
    L.append("## Top tailwinds (early-stage this period)")
    for t in tw[:4]:
        L.append("- **%s** - %d raises, %s in" % (t.get("name"), t.get("count", 0), money(t.get("cap", 0))))
    L.append(""); L.append("## Notable raises")
    for r in top_raises:
        L.append("- %s - %s %s _(%s)_" % (r.get("n"), r.get("s", ""), money(r.get("a")), r.get("tn", "")))
    L.append(""); L.append("## Fund moves")
    for name, u in moves[:10]:
        L.append("- **%s**: %s _(%s)_" % (name, u.get("title", ""), u.get("type", "")))
    import os as _os
    dd = _os.path.join(ROOT, "digests"); _os.makedirs(dd, exist_ok=True)
    open(_os.path.join(dd, "themes-%s.md" % d), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("wrote digests/themes-%s.md" % d)

write_digest()
