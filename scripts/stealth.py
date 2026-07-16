#!/usr/bin/env python3
"""Stealth tab — companies emerging from stealth (pure Python, free, runs in the daily Action).

The stealthstartupspy Substack posts are DIGESTS: each post ("Stealth Startup Spy #NNN") packs
several stealth companies into the subtitle, e.g. "Ex-SpaceX engineer builds AI R&D platform for
deep tech, Stanford oncology fellow applies AI to cancer biopsies, & Ex-Google engineer ...".
So we split each recent post into individual company blurbs, drop consumer/crypto, keep B2B
enterprise fits (theme-tag against SPC's thesis), dedupe, and keep a rolling ~90-day window.
Writes data/stealth.json. Fail-safe.
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
WINDOW = 90

SPLIT = re.compile(r",\s+|\s+&\s+|;\s+|\s+•\s+")
ENT = re.compile(r"\b(ai|ml|llm|platform|software|infrastructure|enterprise|b2b|api|saas|developer|dev tools|"
                 r"automation|agent|agentic|security|cyber|cloud|compute|robotics|fintech|health|clinical|legal|"
                 r"defense|manufactur|supply chain|analytics|payments|insurance|devops|observability|workflow|"
                 r"copilot|data|model|research|biotech|drug|genomic|protocol|network)\b", re.I)
TITLE_JUNK = re.compile(r"^stealth\s+startup\s+spy\s*#?\d*$", re.I)


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def strip_html(t):
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", t or "")
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    t = re.sub(r"&[a-z#0-9]+;", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def load_net():
    try:
        return json.load(open(NET, encoding="utf-8")).get("fit", {})
    except Exception:
        return {"themes": {}, "pass_signals": {}}


def theme_of(text, fit):
    t = (text or "").lower(); best, n = "", 0
    for label, kws in fit.get("themes", {}).items():
        c = sum(1 for k in kws if k in t)
        if c > n:
            best, n = label, c
    return best


def is_consumer(text, fit):
    t = (text or "").lower()
    return any(b in t for b in fit.get("pass_signals", {}).get("keywords_downrank", []))


def fetch_entries():
    if not feedparser:
        return []
    try:
        raw = urllib.request.urlopen(urllib.request.Request(FEED, headers={"User-Agent": UA}), timeout=20).read()
        return getattr(feedparser.parse(raw), "entries", []) or []
    except Exception:
        return []


def entry_date(e):
    for k in ("published_parsed", "updated_parsed"):
        if e.get(k):
            try:
                return datetime.date(*e[k][:3])
            except Exception:
                pass
    return None


def fragments(e):
    """Individual company blurbs from a digest post (subtitle preferred, else body)."""
    sub = strip_html(e.get("summary") or "")
    body = ""
    if e.get("content"):
        try:
            body = strip_html(e["content"][0].get("value") or "")
        except Exception:
            body = ""
    text = sub if len(sub) > 40 else (sub + " " + body)
    text = re.sub(r"…|\.\.\.$", "", text).strip()
    parts = [p.strip(" .–—-") for p in SPLIT.split(text) if p.strip()]
    # merge trailing "and X" style handled by split; keep parts that read like a company blurb
    out = []
    for p in parts:
        if TITLE_JUNK.match(p) or len(p) < 14 or len(p.split()) < 3:
            continue
        p = re.sub(r"^(?:and|&)\s+", "", p).strip(" .–—-&")
        if len(p) < 14 or len(p.split()) < 3:
            continue
        out.append(p[:200])
    return out


def main():
    fit = load_net()
    items, seen = [], set()
    for e in fetch_entries():
        d = entry_date(e)
        if d and (TODAY - d).days > WINDOW:
            continue
        link = e.get("link", "") or ""
        for frag in fragments(e):
            if is_consumer(frag, fit):
                continue
            theme = theme_of(frag, fit)
            if not theme and not ENT.search(frag):
                continue
            k = norm(frag)[:60]
            if not k or k in seen:
                continue
            seen.add(k)
            items.append({"company": "", "title": frag, "blurb": "",
                          "theme": theme or "Applied / horizontal AI",
                          "date": d.isoformat() if d else "", "link": link})
    items.sort(key=lambda x: x.get("date", ""), reverse=True)
    items = items[:80]
    json.dump({"generated": TODAY.isoformat(), "window_days": WINDOW, "count": len(items), "items": items},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote stealth.json — %d B2B-fit stealth items" % len(items))


if __name__ == "__main__":
    main()
