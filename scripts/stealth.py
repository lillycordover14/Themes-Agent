#!/usr/bin/env python3
"""Stealth tab — companies emerging from stealth (pure Python, free, runs in the daily Action).

Pulls the stealthstartupspy Substack RSS, treats each post as a launch item, filters to B2B
enterprise fits against SPC's thesis (data/spc_network.json), drops obvious consumer/crypto,
theme-tags each, dedupes, and keeps a rolling ~90-day window. Writes data/stealth.json. Fail-safe:
any error yields an empty (but valid) file rather than breaking the build.
"""
import json, os, re, datetime, urllib.request
try:
    import feedparser
except Exception:
    feedparser = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NET = os.path.join(ROOT, "data", "spc_network.json")
OUT = os.path.join(ROOT, "data", "stealth.json")
FEED = "https://stealthstartupspy.substack.com/feed"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TODAY = datetime.date.today()
WINDOW = 90  # days

RAISE_V = re.compile(r"\b(raises?|raised|emerges?|emerged|launch(?:e[sd])?|unveils?|debuts?|secures?|lands?|closes?)\b", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def strip_html(t):
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t or "")
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = re.sub(r"&[a-z#0-9]+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def load_net():
    try:
        return json.load(open(NET, encoding="utf-8"))
    except Exception:
        return {"fit": {"themes": {}, "pass_signals": {}}}


def theme_of(text, fit):
    t = (text or "").lower()
    best, n = "", 0
    for label, kws in fit.get("themes", {}).items():
        c = sum(1 for k in kws if k in t)
        if c > n:
            best, n = label, c
    return best


def is_consumer(text, fit):
    t = (text or "").lower()
    bad = fit.get("pass_signals", {}).get("keywords_downrank", [])
    return any(b in t for b in bad)


def company_of(title):
    """Best-effort company name from a launch headline; '' if it reads like a topic, not a name."""
    t = strip_html(title or "")
    t = re.sub(r"^\s*(?:exclusive|scoop|breaking|stealth\s+startup\s+spy)\s*[:\-–]\s*", "", t, flags=re.I)
    m = RAISE_V.search(t)
    co = t[:m.start()].strip(" -–—:·|") if m else t
    co = re.sub(r"\s*[|–—-]\s+.*$", "", co).strip()
    # strip leading "<Demonym/sector> " noise handled loosely; drop if too long / clearly a sentence
    if not co or len(co.split()) > 5:
        return ""
    if norm(co) in {"the", "a", "an", "ai", "startup", "stealth"}:
        return ""
    return co


def fetch_feed():
    if not feedparser:
        return []
    try:
        raw = urllib.request.urlopen(urllib.request.Request(FEED, headers={"User-Agent": UA}), timeout=20).read()
        return getattr(feedparser.parse(raw), "entries", []) or []
    except Exception:
        return []


def within_window(d):
    try:
        return (TODAY - d).days <= WINDOW
    except Exception:
        return True


def main():
    net = load_net(); fit = net.get("fit", {})
    items, seen = [], set()
    for e in fetch_feed():
        title = strip_html(e.get("title") or "")
        link = e.get("link", "") or ""
        blurb = strip_html(e.get("summary") or (e.get("content", [{}])[0].get("value") if e.get("content") else "") or "")[:280]
        dt = None
        for k in ("published_parsed", "updated_parsed"):
            if e.get(k):
                try:
                    dt = datetime.date(*e[k][:3]); break
                except Exception:
                    pass
        if dt and not within_window(dt):
            continue
        key = norm(link) or norm(title)
        if not title or key in seen:
            continue
        seen.add(key)
        blob = title + " . " + blurb
        if is_consumer(blob, fit):
            continue                      # drop consumer/crypto
        theme = theme_of(blob, fit)
        if not theme:
            continue                      # keep only recognizable B2B-enterprise fits
        items.append({
            "company": company_of(title), "title": title[:180], "blurb": blurb,
            "theme": theme, "date": dt.isoformat() if dt else "", "link": link,
        })
    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    items = items[:60]
    json.dump({"generated": TODAY.isoformat(), "window_days": WINDOW, "count": len(items), "items": items},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote stealth.json — %d B2B-fit stealth items" % len(items))


if __name__ == "__main__":
    main()
