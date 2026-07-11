#!/usr/bin/env python3
"""Build index.html from data/tailwinds.json + data/funds.json using scripts/dashboard_template.html.
Also folds in Harmonic saved-search companies (data/harmonic_raises.json) if present, since the
Harmonic pull runs before this build. Pure, no network."""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(ROOT, "data", "tailwinds.json"), encoding="utf-8"))
FUNDS = json.load(open(os.path.join(ROOT, "data", "funds.json"), encoding="utf-8"))


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
BLOB = json.dumps({"D": D, "F": FUNDS}, ensure_ascii=False)
TEMPLATE = open(os.path.join(HERE, "dashboard_template.html"), encoding="utf-8").read()
html = TEMPLATE.replace("__BLOB__", BLOB)
open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(html)
print("built index.html (%d bytes) from %d funds" % (len(html), FUNDS.get("count", 0)))
