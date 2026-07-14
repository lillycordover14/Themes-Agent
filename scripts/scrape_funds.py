#!/usr/bin/env python3
"""Autonomously pull each tracked fund's latest web activity and update data/funds.json.

Sources (no auth, cloud-friendly): the fund's own blog/RSS feed (where one exists) plus a
Google News RSS query for the fund name. Runs on GitHub Actions. Never hard-fails: any fund
that errors keeps its existing data.
"""
import json, os, re, sys, datetime, urllib.parse, urllib.request

try:
    import feedparser
except ImportError:
    print("feedparser missing; run: pip install feedparser"); sys.exit(0)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNDS_PATH = os.path.join(ROOT, "data", "funds.json")
PER_FUND_DIR = os.path.join(ROOT, "data", "funds")
DAYS = 180  # 6-month activity window            # look-back window
MAX_ITEMS = 12        # keep newest N per fund
INVEST_NEWS = re.compile(r"\b(raises?|raised|series\s?[a-e]\b|seed|pre-?seed|funding|invests?|investment|backs?|leads?|led by|acquires?|acquisition|closes?\s+\$|\$\d|new fund|debut fund|fund\s+[ivx]+)\b", re.I)
UA = "Mozilla/5.0 (compatible; ThemesAgent/1.0; +https://github.com)"

# Native RSS/Atom feeds where a fund publishes one (best-effort; extend freely).
NATIVE_FEEDS = {
    "a16z": ["https://a16z.com/feed/"],
    "first-round": ["https://review.firstround.com/feed.xml"],
    "yc": ["https://www.ycombinator.com/blog/rss"],
    "greylock": ["https://greylock.com/feed/"],
    "bessemer": ["https://www.bvp.com/atlas/rss"],
    "battery": ["https://www.battery.com/feed/"],
}

INVEST = re.compile(r"\b(raises?|raised|series [a-e]|seed round|pre-seed|funding round|invests?|investment|backs?|leads?|led by|closes? \$)\b", re.I)
NEWFUND = re.compile(r"\b(new fund|fund [ivx]+|\$\d[\d.]*\s?(m|b|million|billion)\s+fund|closes? .*fund|raises? .*fund)\b", re.I)
THESIS = re.compile(r"\b(thesis|why |how |the future|state of|perspective|outlook|manifesto|playbook|guide|lessons|what we|our take|market map|deep dive)\b", re.I)


def classify(title, from_blog):
    t = title or ""
    if NEWFUND.search(t):
        return "New fund"
    if INVEST.search(t):
        return "Investment"
    if from_blog or THESIS.search(t):
        return "Thesis"
    return "Post"


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())[:80]


def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        raw = urllib.request.urlopen(req, timeout=25).read()
        return feedparser.parse(raw)
    except Exception as e:
        print("  ! fetch failed:", url, e)
        return None


def entries_from(feed, from_blog, cutoff, require_invest=False):
    out = []
    if not feed or not getattr(feed, "entries", None):
        return out
    for e in feed.entries[:100]:
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()
        if not title or not link:
            continue
        if require_invest and not INVEST_NEWS.search(title):
            continue
        dt = None
        for k in ("published_parsed", "updated_parsed"):
            if e.get(k):
                dt = datetime.date(*e[k][:3]); break
        if dt and dt < cutoff:
            continue
        summ = re.sub("<[^>]+>", "", e.get("summary", "") or "").strip()
        summ = re.sub(r"\s+", " ", summ)[:180]
        out.append({
            "date": (dt.isoformat() if dt else datetime.date.today().isoformat()),
            "type": classify(title, from_blog),
            "title": title[:160],
            "link": link,
            "summary": summ,
        })
    return out


def google_news_url(name):
    q = '"%s" (funding OR raises OR fund OR invests OR announces)' % name
    return "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en" % urllib.parse.quote(q)


def podcast_news_url(name):
    q = '"%s" (podcast OR interview OR episode OR "on the show")' % name
    return "https://news.google.com/rss/search?q=%s&hl=en-US&gl=US&ceid=US:en" % urllib.parse.quote(q)




def edgar_formd(name, cutoff):
    """SEC EDGAR full-text search for recent Form D (new fund / securities offering) filings."""
    try:
        q = urllib.parse.quote('"%s"' % name)
        url = "https://efts.sec.gov/LATEST/search-index?q=%s&forms=D" % q
        req = urllib.request.Request(url, headers={"User-Agent": "ThemesAgent research@smithpointcapital.com"})
        d = json.loads(urllib.request.urlopen(req, timeout=25).read())
    except Exception:
        return []
    tok = (name.lower().split() or [""])[0]
    out = []
    for h in (d.get("hits", {}) or {}).get("hits", [])[:6]:
        src = h.get("_source", {}) or {}
        disp = ", ".join(src.get("display_names", []) or [])
        filed = src.get("file_date", "") or ""
        if not filed or filed < cutoff:
            continue
        if tok and tok not in disp.lower():
            continue
        out.append({"date": filed, "type": "New fund", "title": "SEC Form D \u2014 " + disp[:70],
                    "url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company=" + urllib.parse.quote(name) + "&type=D&count=20",
                    "summary": "New fund / securities offering filed with the SEC \u2014 fresh capital to deploy."})
    return out


def main():
    data = json.load(open(FUNDS_PATH, encoding="utf-8"))
    cutoff = datetime.date.today() - datetime.timedelta(days=DAYS)
    total_new = 0
    for f in data["funds"]:
        slug, name = f["slug"], f["name"]
        print("• %s" % name)
        cand = []
        src = f.get("sources", {})
        feeds = list(NATIVE_FEEDS.get(slug, []))
        if src.get("substack"):
            feeds.append(src["substack"].rstrip("/") + "/feed")
        blog = src.get("blog", "")
        if "medium.com" in blog:
            feeds.append(blog.rstrip("/") + "/feed")
        for p in (f.get("partner_substacks") or []):
            if "substack.com" in (p.get("url") or ""):
                feeds.append(p["url"].rstrip("/") + "/feed")
        for u in feeds:
            cand += entries_from(fetch(u), True, cutoff)
        cand += entries_from(fetch(google_news_url(name)), False, cutoff, require_invest=True)
        existing = f.get("updates", [])
        seen = {norm(u["title"]) for u in existing} | {u["link"] for u in existing}
        fresh = []
        for c in cand:
            key = norm(c["title"])
            if key in seen or c["link"] in seen:
                continue
            seen.add(key); seen.add(c["link"]); fresh.append(c)
        allu = fresh + existing
        cut = (datetime.date.today() - datetime.timedelta(days=DAYS)).isoformat()
        allu = [u for u in allu if (not u.get("date")) or u.get("date") >= cut]
        f["updates"] = sorted(allu, key=lambda x: x.get("date", ""), reverse=True)
        total_new += len(fresh)
        if fresh:
            print("  + %d new (total %d in window)" % (len(fresh), len(f["updates"])))
        # podcasts: discover partner/firm appearances from the web
        pods = entries_from(fetch(podcast_news_url(name)), False, cutoff)
        if pods:
            existing_p = f.get("podcasts", [])
            seen_p = {p.get("url") for p in existing_p} | {norm(p.get("title", "")) for p in existing_p}
            add_p = []
            for p in pods:
                if p["link"] in seen_p or norm(p["title"]) in seen_p:
                    continue
                seen_p.add(p["link"])
                add_p.append({"person": "", "show": "", "title": p["title"], "url": p["link"], "date": p["date"]})
            if add_p:
                f["podcasts"] = (add_p + existing_p)[:8]
        try:
            fd_cut = (datetime.date.today() - datetime.timedelta(days=365)).isoformat()
            seen_t = {u.get("title") for u in f.get("updates", [])}
            for it in edgar_formd(name, fd_cut):
                if it["title"] not in seen_t:
                    f.setdefault("updates", []).insert(0, it); seen_t.add(it["title"])
        except Exception:
            pass
        # write per-fund file
        json.dump(f, open(os.path.join(PER_FUND_DIR, slug + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    data["generated"] = datetime.date.today().isoformat()
    json.dump(data, open(FUNDS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Done. %d new items across %d funds." % (total_new, len(data["funds"])))


if __name__ == "__main__":
    main()
