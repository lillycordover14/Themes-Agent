#!/usr/bin/env python3
"""Refresh data/tailwinds.json from PUBLIC VC funding announcements.

Strict: only keeps items that clearly name a COMPANY and a $ AMOUNT (drops headlines/roundups).
Classifies each into SPC tailwinds via data/editorial.json. Merges with the curated editorial
narrative. Safe: if too few real raises are parsed, keeps the existing file.
"""
import json, os, re, sys, datetime, urllib.parse, urllib.request

try:
    import feedparser
except ImportError:
    print("feedparser missing"); sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TW_PATH = os.path.join(ROOT, "data", "tailwinds.json")
ED = json.load(open(os.path.join(ROOT, "data", "editorial.json"), encoding="utf-8"))
UA = "Mozilla/5.0 (compatible; ThemesAgent/1.0)"
DAYS = 45
MIN_RAISES = 6

FEEDS = [
    "https://news.crunchbase.com/feed/",
    "https://www.finsmes.com/feed",
    "https://techcrunch.com/category/venture/feed/",
    "https://www.eu-startups.com/feed/",
]

# Company raises $Amount  ->  capture company + amount + stage
RAISE = re.compile(
    r"^(?P<co>[A-Z0-9][\w.,&'/+\- ]{1,44}?)\s+"
    r"(?:raises|raised|lands|secures|closes|snags|nabs|bags|scores|banks|picks up|pulls in|reels in|clinches)\s+"
    r".*?\$(?P<amt>\d+(?:\.\d+)?)\s*(?P<unit>billion|million|m|b)\b", re.I)
STAGE = re.compile(r"\b(pre-?seed|angel|seed|series\s?[a-d])\b", re.I)
CONSUMER = re.compile(r"\b(dating|gaming|game studio|creator|influencer|grocery|food delivery|e-?bike|scooter)\b", re.I)


def amt_usd(a, u):
    v = float(a); u = u.lower()
    return int(v * 1e9) if u in ("billion", "b") else int(v * 1e6)


def stage_of(t):
    m = STAGE.search(t or "")
    if not m:
        return "Early Stage"
    s = re.sub(r"\s+", " ", m.group(1).lower()).replace("preseed", "pre-seed")
    return {"pre-seed": "Pre Seed", "angel": "Angel", "seed": "Seed",
            "series a": "Series A", "series b": "Series B", "series c": "Series C", "series d": "Series D"}.get(s, s.title())


def classify(text):
    t = " " + (text or "").lower() + " "
    for k in ED["classify_order"]:
        for w in ED["keywords"][k]:
            if w in t:
                return k
    return ED["classify_order"][-1]


def fetch(url):
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=25).read()
        return feedparser.parse(raw)
    except Exception as e:
        print("  ! feed failed:", url.split("//")[-1][:40], e); return None


def main():
    cutoff = datetime.date.today() - datetime.timedelta(days=DAYS)
    kbyname = {t["k"]: t for t in ED["tailwinds"]}
    seen, recs = set(), []
    for url in FEEDS:
        f = fetch(url)
        if not f:
            continue
        for e in getattr(f, "entries", [])[:40]:
            title = (e.get("title") or "").strip()
            if not title:
                continue
            dt = None
            for k in ("published_parsed", "updated_parsed"):
                if e.get(k):
                    dt = datetime.date(*e[k][:3]); break
            if dt and dt < cutoff:
                continue
            m = RAISE.match(title)
            if not m:
                continue                       # not a clear "<Company> raises $X" item
            if CONSUMER.search(title):
                continue
            co = re.sub(r"[,:].*$", "", m.group("co")).strip()
            if len(co) < 2 or co.lower() in ("the", "this", "new", "a", "an"):
                continue
            key = co.lower()
            if key in seen:
                continue
            seen.add(key)
            summ = re.sub("<[^>]+>", "", e.get("summary", "") or "")
            summ = re.sub(r"\s+", " ", summ).strip()
            amt = amt_usd(m.group("amt"), m.group("unit"))
            stg = stage_of(title + " " + summ)
            tk = classify(title + " " + summ)
            tier = "early" if stg in ("Angel", "Pre Seed", "Seed", "Series A") else ("late" if stg.startswith("Series") else "early")
            recs.append(dict(n=co, d="", tk=tk, tn=kbyname[tk]["name"], s=stg, tier=tier,
                             a=amt, tot=0, inv="", loc="", src="Press", desc=summ[:150]))
    print("parsed %d clean raises from public feeds" % len(recs))
    if len(recs) < MIN_RAISES:
        print("Few clean raises (<%d) - keeping existing tailwinds.json." % MIN_RAISES)
        try:
            d = json.load(open(TW_PATH, encoding="utf-8")); d["generated"] = datetime.date.today().isoformat()
            json.dump(d, open(TW_PATH, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
        return
    agg = {t["k"]: dict(count=0, cap=0) for t in ED["tailwinds"]}
    for r in recs:
        a = agg[r["tk"]]
        if r["tier"] == "early":
            a["count"] += 1
            if (r["a"] or 0) < 5e8:
                a["cap"] += r["a"] or 0
    tailwinds = []
    for t in ED["tailwinds"]:
        tt = dict(t); tt["count"] = agg[t["k"]]["count"]; tt["cap"] = agg[t["k"]]["cap"]; tailwinds.append(tt)
    stages = ED["stages"]
    sc = {s: 0 for s in stages}
    for r in recs:
        sc[r["s"] if r["s"] in sc else "Other"] = sc.get(r["s"] if r["s"] in sc else "Other", 0) + 1
    early = [r for r in recs if r["tier"] == "early"]
    data = dict(generated=datetime.date.today().isoformat(), recs=recs, tailwinds=tailwinds,
                market=ED["market"], investors=ED["investors"], engineers=ED["engineers"],
                trackedFunds=ED["trackedFunds"], stages=stages, sc=sc, nAll=len(recs), nEarly=len(early),
                capEarly=sum((r["a"] or 0) for r in early if (r["a"] or 0) < 5e8),
                seedA=len([r for r in early if r["s"] in ("Seed", "Series A")]))
    json.dump(data, open(TW_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    print("tailwinds.json refreshed: %d clean raises (%d early)." % (len(recs), len(early)))


if __name__ == "__main__":
    main()
