#!/usr/bin/env python3
"""Autonomously refresh data/tailwinds.json from PUBLIC VC funding announcements.

No auth / no Harmonic — reads funding-news RSS (TechCrunch, Crunchbase News, FinSMEs,
EU-Startups) + Google News, extracts raises (company / amount / stage), classifies each
into SPC's tailwinds using data/editorial.json keywords, and merges with the curated
editorial narrative. Safe: if too few raises are parsed, it keeps the existing file.
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
MIN_RAISES = 8          # if fewer parsed, keep existing file (transient-failure guard)

FEEDS = [
    "https://news.crunchbase.com/feed/",
    "https://www.finsmes.com/feed",
    "https://techcrunch.com/category/venture/feed/",
    "https://www.eu-startups.com/feed/",
    "https://news.google.com/rss/search?q=" + urllib.parse.quote(
        '(seed OR "Series A" OR "pre-seed") (enterprise OR B2B OR AI OR infrastructure) raises funding') +
        "&hl=en-US&gl=US&ceid=US:en",
]

AMT = re.compile(r"\$(\d+(?:\.\d+)?)\s*(billion|million|b|m|k)\b", re.I)
STAGE = re.compile(r"\b(pre-seed|pre seed|angel|seed|series\s?a|series\s?b|series\s?c|series\s?d)\b", re.I)
SPLIT = re.compile(r"\b(raises|raised|lands|secures|closes|snags|nabs|bags|picks up|scores|gets|banks)\b", re.I)
CONSUMER = re.compile(r"\b(dating|game|gaming|consumer app|creator|influencer|grocery|food delivery)\b", re.I)


def amount_usd(t):
    m = AMT.search(t or "")
    if not m:
        return 0
    v = float(m.group(1)); u = m.group(2).lower()
    if u in ("billion", "b"): return int(v * 1e9)
    if u in ("million", "m"): return int(v * 1e6)
    if u == "k": return int(v * 1e3)
    return int(v)


def stage_of(t):
    m = STAGE.search(t or "")
    if not m:
        return ""
    s = m.group(1).lower().replace("series ", "series ").replace("  ", " ").strip()
    return {"pre seed": "Pre Seed", "pre-seed": "Pre Seed", "angel": "Angel", "seed": "Seed",
            "seriesa": "Series A", "series a": "Series A", "series b": "Series B",
            "series c": "Series C", "series d": "Series D"}.get(s.replace("series", "series ").replace("series  ", "series ").strip(), s.title())


def tier_of(stage):
    return "early" if stage in ("Angel", "Pre Seed", "Seed", "Series A") else ("late" if stage.startswith("Series") else "early")


def company_of(title):
    parts = SPLIT.split(title, maxsplit=1)
    name = parts[0].strip(" :–-") if parts else title
    name = re.sub(r",.*$", "", name).strip()
    return name[:48] if name else title[:48]


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
            link = (e.get("link") or "").strip()
            if not title or not link:
                continue
            dt = None
            for k in ("published_parsed", "updated_parsed"):
                if e.get(k):
                    dt = datetime.date(*e[k][:3]); break
            if dt and dt < cutoff:
                continue
            summ = re.sub("<[^>]+>", "", e.get("summary", "") or "")
            summ = re.sub(r"\s+", " ", summ).strip()
            blob = title + " " + summ
            amt = amount_usd(blob)
            stage = stage_of(blob)
            if not amt and not stage:
                continue                      # not clearly a funding round
            if CONSUMER.search(blob):
                continue
            comp = company_of(title)
            key = comp.lower()
            if key in seen:
                continue
            seen.add(key)
            tk = classify(blob)
            recs.append(dict(n=comp, d="", tk=tk, tn=kbyname[tk]["name"], s=stage or "Early Stage",
                             tier=tier_of(stage) if stage else "early", a=amt, tot=0,
                             inv="", loc="", src="Press", desc=summ[:150]))
    if len(recs) < MIN_RAISES:
        print("Only %d raises parsed (<%d) — keeping existing tailwinds.json." % (len(recs), MIN_RAISES))
        try:
            d = json.load(open(TW_PATH, encoding="utf-8"))
            d["generated"] = datetime.date.today().isoformat()
            json.dump(d, open(TW_PATH, "w", encoding="utf-8"), ensure_ascii=False)
        except Exception:
            pass
        return
    # aggregate
    agg = {t["k"]: dict(count=0, cap=0) for t in ED["tailwinds"]}
    for r in recs:
        a = agg[r["tk"]]
        if r["tier"] == "early":
            a["count"] += 1
            if (r["a"] or 0) < 5e8:
                a["cap"] += r["a"] or 0
    tailwinds = []
    for t in ED["tailwinds"]:
        tt = dict(t); tt["count"] = agg[t["k"]]["count"]; tt["cap"] = agg[t["k"]]["cap"]
        tailwinds.append(tt)
    stages = ED["stages"]
    sc = {s: 0 for s in stages}
    for r in recs:
        s = r["s"] if r["s"] in sc else "Other"
        sc[s] = sc.get(s, 0) + 1
    early = [r for r in recs if r["tier"] == "early"]
    data = dict(
        generated=datetime.date.today().isoformat(),
        recs=recs, tailwinds=tailwinds,
        market=ED["market"], investors=ED["investors"], engineers=ED["engineers"],
        trackedFunds=ED["trackedFunds"], stages=stages, sc=sc,
        nAll=len(recs), nEarly=len(early),
        capEarly=sum((r["a"] or 0) for r in early if (r["a"] or 0) < 5e8),
        seedA=len([r for r in early if r["s"] in ("Seed", "Series A")]),
    )
    json.dump(data, open(TW_PATH, "w", encoding="utf-8"), ensure_ascii=False)
    print("tailwinds.json refreshed: %d raises (%d early) from public funding feeds." % (len(recs), len(early)))


if __name__ == "__main__":
    main()
