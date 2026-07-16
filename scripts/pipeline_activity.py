#!/usr/bin/env python3
"""Pipeline Activity feed (data/pipeline.json) — WEB-ONLY, free.

For each tracked company, surface MATERIAL updates from the last ~45 days: funding, product
launches, new customers, exec hires, partnerships, and — called out specially — CONFERENCES the
company will be at (a chance for Lilly to meet the team). Sources: GDELT news (strict name match),
the company blog RSS, and website/customer-page diffs recorded by snapshot_signals.py.

Runs in the always-on scrape step (no API key). Fail-safe. Writes data/pipeline_activity.json.
"""
import json, os, re, sys, datetime, urllib.parse, urllib.request, urllib.error
try:
    import feedparser
except Exception:
    feedparser = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "data", "pipeline.json")
HIST_DIR = os.path.join(ROOT, "data", "signal_history")
OUT = os.path.join(ROOT, "data", "pipeline_activity.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
TODAY = datetime.date.today()
WINDOW = 45  # days

STOP = {"the", "inc", "labs", "ai", "app", "io", "co", "company", "technologies", "capital", "ventures", "group", "partners", "fund"}
CAT = [
    ("Funding", re.compile(r"\b(raise[sd]?|raising|closed?|secures?|series\s+[a-e]\b|\$\d+\s*(m|million|b|billion)|funding round|valuation)\b", re.I)),
    ("New customer", re.compile(r"\b(new customer|selected by|chosen by|deployed (at|by)|goes live|now powering|signs|onboard|case study|wins? deal|expands? use)\b", re.I)),
    ("Product", re.compile(r"\b(launch(e[sd])?|unveil|introduc\w+|general availability|\bGA\b|new (product|feature|release|model)|rolls out|ships|debuts?)\b", re.I)),
    ("Exec hire", re.compile(r"\b(appoints?|names?|hires?|joins? as|welcomes?|taps?)\b.{0,30}\b(ceo|cfo|cro|coo|cto|cmo|chief|vp|head of|president|general counsel)\b", re.I)),
    ("Partnership", re.compile(r"\b(partners? with|partnership|integrat\w+|collaborat\w+|teams? up with|alliance|joins forces)\b", re.I)),
    ("Award/traction", re.compile(r"\b(named|ranked|award|fastest.growing|milestone|surpass|doubl\w+|crosses|reaches \$)\b", re.I)),
]
CONF = re.compile(r"\b(speaking at|to speak at|join us at|meet us at|see us at|catch us at|booth|keynote|will present|presenting at|exhibit\w*|sponsor\w* of|fireside|panel at|on stage at|attending)\b|\b(conference|summit|expo|symposium|forum|dreamforce|re:?invent|hackathon|demo day|money\s?20/?20|saastr|finovate|web ?summit|fintech nexus|lendit|sxsw|kubecon|\bgtc\b|\bces\b|hlth|davos)\b|\b[A-Z][A-Za-z0-9&' ]{2,30}\s(Summit|Conference|Conf|Expo|Forum|World|Week|Days|Live|Connect|Ignite)\b", re.I)


def mentions(title, name):
    toks = [t for t in re.findall(r"[a-z0-9]{3,}", (name or "").lower()) if t not in STOP]
    tl = (title or "").lower()
    return (any(t in tl for t in toks)) if toks else ((name or "").lower() in tl)


def fetch_text(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
    except Exception:
        return ""


def social_links(domain):
    """Resolve the company's REAL LinkedIn company page + X handle from its own site footer."""
    if not domain:
        return "", ""
    base = domain if domain.startswith("http") else "https://" + domain
    li = x = ""
    for url in (base, base.rstrip("/") + "/contact", base.rstrip("/") + "/about"):
        html = fetch_text(url)
        if not html:
            continue
        if not li:
            m = re.search(r"https?://(?:www\.)?linkedin\.com/company/[A-Za-z0-9_\-%.]+", html)
            if m:
                li = m.group(0).rstrip("/")
        if not x:
            m = re.search(r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{2,30})", html)
            if m and m.group(1).lower() not in ("share", "intent", "home", "hashtag", "search", "i"):
                x = "https://x.com/" + m.group(1)
        if li and x:
            break
    return li, x


UPCOMING = re.compile(r"(join us at|meet us at|see us at|visit us at|will be at|we.?ll be at|will attend|attending|catch us at|find us at|upcoming|register|book (a )?(meeting|time|demo)|stop by|come see us|this week at|next week at)", re.I)


def events_confs(domain):
    """Best-effort: pull upcoming event/conference names off the company's own events page."""
    if not domain:
        return []
    base = domain if domain.startswith("http") else "https://" + domain
    out = []
    for url in (base.rstrip("/") + "/events", base.rstrip("/") + "/company/events", base.rstrip("/") + "/resources/events"):
        html = fetch_text(url)
        if not html:
            continue
        text = re.sub("<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        for m in CONF.finditer(text):
            snip = text[max(0, m.start() - 45):m.end() + 8].strip()
            if 6 < len(snip) < 90:
                out.append({"date": "", "title": snip[:120], "link": url, "when": "upcoming", "source": "Events page"})
        if out:
            break
    return out[:5]


def fetch_json(url, timeout=20):
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                continue
            return None
        except Exception:
            return None
    return None


def gdelt_articles(name, months=2):
    url = ("https://api.gdeltproject.org/api/v2/doc/doc?query=%s&mode=artlist&format=json"
           "&maxrecords=80&sort=datedesc&timespan=%dmonths" % (urllib.parse.quote('"%s"' % name), months))
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
    return out


def blog_posts(domain):
    if not feedparser or not domain:
        return []
    base = domain if domain.startswith("http") else "https://" + domain
    base = base.rstrip("/")
    out = []
    for feed in (base + "/blog/feed", base + "/feed", base + "/blog/rss.xml", base + "/articles/feed", base + "/news/feed"):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(feed, headers={"User-Agent": UA}), timeout=12).read()
            f = feedparser.parse(raw)
        except Exception:
            continue
        for e in getattr(f, "entries", [])[:15]:
            dt = None
            for k in ("published_parsed", "updated_parsed"):
                if e.get(k):
                    dt = datetime.date(*e[k][:3]); break
            out.append({"title": (e.get("title") or "")[:170], "link": e.get("link", ""),
                        "date": dt.isoformat() if dt else ""})
        if out:
            break
    return out


def within_window(iso):
    try:
        y, mo, dd = map(int, iso[:10].split("-"))
        return (TODAY - datetime.date(y, mo, dd)).days <= WINDOW
    except Exception:
        return False


def within_days(iso, n):
    try:
        y, mo, dd = map(int, iso[:10].split("-"))
        return (TODAY - datetime.date(y, mo, dd)).days <= n
    except Exception:
        return False


def categorize(title):
    for label, rx in CAT:
        if rx.search(title):
            return label
    return None


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


def new_customers(slug):
    """Names that appeared on the website/customers page since the previous snapshot."""
    rows = [r for r in history(slug) if r.get("site_customers")]
    if len(rows) < 2:
        return []
    prev = set(rows[-2].get("site_customers") or [])
    cur = set(rows[-1].get("site_customers") or [])
    return sorted(cur - prev)[:12]



KNOWN_EVENTS = ["money20/20", "money2020", "dreamforce", "re:invent", "reinvent", "web summit", "websummit",
    "fintech devcon", "ai summit", "saastr", "hlth", "finovate", "davos", "gtc", "kubecon", "rsa conference",
    "lendit", "fintech nexus", "sxsw", "collision", "ces", "transform", "the ai conference"]
EVENT_NAME = re.compile(r"([A-Z0-9][A-Za-z0-9&/.'\-]{1,24}(?:\s+[A-Z0-9][A-Za-z0-9&/.'\-]{1,20}){0,3}\s+(?:Summit|Conference|Conf|Expo|Forum|Week|World|Days|Live|Connect|Ignite|Dreamforce))", re.I)


def event_key(title):
    tl = (title or "").lower()
    tln = re.sub(r"[^a-z0-9]", "", tl)
    for k in KNOWN_EVENTS:
        kn = re.sub(r"[^a-z0-9]", "", k)
        if kn and kn in tln:
            return kn
    m = EVENT_NAME.search(title or "")
    if m:
        return re.sub(r"[^a-z0-9]", "", m.group(1).lower())
    return tln[:40]


def dedup_events(confs):
    seen = set(); out = []
    for c in confs:
        k = event_key(c.get("title", ""))
        if k in seen:
            continue
        seen.add(k); out.append(c)
    return out


def activity(comp):
    name = comp.get("name"); domain = comp.get("domain", "")
    slug = re.sub(r"[^a-z0-9]+", "-", (comp.get("slug") or name or "").lower()).strip("-")
    print("•", name)
    # News/Google-news (GDELT) over 6 months, strict on-topic
    arts = [a for a in gdelt_articles(name, 6) if a["date"] and mentions(a["title"], name)]

    updates = []; confs = []; seen = set()

    def add(date, cat, title, link, src):
        key = re.sub(r"[^a-z0-9]+", "", (title or "").lower())[:60]
        if not title or key in seen:
            return
        seen.add(key)
        if CONF.search(title) and within_days(date, 180):
            confs.append({"date": date, "title": title, "link": link, "source": src,
                          "when": "upcoming" if UPCOMING.search(title) else "prior"})
        elif within_days(date, WINDOW):
            cat2 = cat or categorize(title)
            if cat2:
                updates.append({"date": date, "category": cat2, "title": title, "link": link, "source": src})

    for a in arts:
        add(a["date"], None, a["title"], a["link"], "News")
    # company blog + Substack posts
    for feed_domain, src in ((domain, "Blog"), (comp.get("substack"), "Substack")):
        if not feed_domain:
            continue
        for b in blog_posts(feed_domain):
            add(b["date"], src, b["title"], b["link"], src)
    # founder / executive activity via news (LinkedIn post content is not scrapable without login)
    for founder in (comp.get("founders") or [])[:4]:
        for a in gdelt_articles(founder, 2):
            if a["date"] and mentions(a["title"], founder):
                add(a["date"], "Founder", a["title"], a["link"], "Founder news")

    for ec in events_confs(domain):
        key = re.sub(r"[^a-z0-9]+", "", ec["title"].lower())[:60]
        if key not in seen:
            seen.add(key); confs.append(ec)
    updates.sort(key=lambda x: x.get("date", ""), reverse=True)
    # upcoming conferences first, then most recent
    confs.sort(key=lambda x: (0 if x.get("when") == "upcoming" else 1, "" if x.get("when") == "upcoming" else x.get("date", "")))
    confs = dedup_events(confs)
    # resolve real LinkedIn / X profile from the company site (fallback to provided/empty)
    li = comp.get("linkedin") or ""; xx = comp.get("x") or ""
    if not (li and xx):
        rli, rx = social_links(domain)
        li = li or rli; xx = xx or rx
    return {
        "name": name, "domain": domain, "slug": slug,
        "updates": updates[:14],
        "conferences": confs[:5],
        "new_customers": new_customers(slug),
        "linkedin": li,
        "x": xx,
        "substack": comp.get("substack", ""),
        "url": ("https://" + domain if domain else ""),
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
            out.append(activity(c))
        except Exception as e:
            print("  activity failed:", e)
            out.append({"name": c.get("name"), "slug": re.sub(r"[^a-z0-9]+", "-", (c.get("name") or "").lower()).strip("-"),
                        "updates": [], "conferences": [], "new_customers": [], "url": ""})
    json.dump({"generated": TODAY.isoformat(), "companies": out}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote pipeline_activity.json (%d companies)" % len(out))


if __name__ == "__main__":
    main()
