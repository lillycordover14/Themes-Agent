#!/usr/bin/env python3
"""Pipeline Activity feed (data/pipeline.json) — WEB-ONLY, free.

For each tracked company, surface MATERIAL updates from the last ~35 days: funding, product
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
WINDOW = 35  # days

STOP = {"the", "inc", "labs", "ai", "app", "io", "co", "company", "technologies", "capital", "ventures", "group", "partners", "fund"}
CAT = [
    ("Funding", re.compile(r"\b(raise[sd]?|raising|closed?|secures?|series\s+[a-e]\b|\$\d+\s*(m|million|b|billion)|funding round|valuation)\b", re.I)),
    ("New customer", re.compile(r"\b(new customer|selected by|chosen by|deployed (at|by)|goes live|now powering|signs|onboard|case study|wins? deal|expands? use)\b", re.I)),
    ("Product", re.compile(r"\b(launch(e[sd])?|unveil|introduc\w+|general availability|\bGA\b|new (product|feature|release|model)|rolls out|ships|debuts?)\b", re.I)),
    ("Exec hire", re.compile(r"\b(appoints?|names?|hires?|joins? as|welcomes?|taps?)\b.{0,30}\b(ceo|cfo|cro|coo|cto|cmo|chief|vp|head of|president|general counsel)\b", re.I)),
    ("Partnership", re.compile(r"\b(partners? with|partnership|integrat\w+|collaborat\w+|teams? up with|alliance|joins forces)\b", re.I)),
    ("Award/traction", re.compile(r"\b(named|ranked|award|fastest.growing|milestone|surpass|doubl\w+|crosses|reaches \$)\b", re.I)),
]
CONF = re.compile(r"\b(speaking at|join us at|meet us at|booth|keynote|will present|presenting at|exhibit\w*|sponsor\w* of|fireside|panel at|on stage at|attending)\b|\b[A-Z][A-Za-z0-9&' ]{2,30}\s(Summit|Conference|Conf|Expo|Forum|World|Week|Days|Live|Connect|Re:?Invent|Ignite|Dreamforce)\b", re.I)


def mentions(title, name):
    toks = [t for t in re.findall(r"[a-z0-9]{3,}", (name or "").lower()) if t not in STOP]
    tl = (title or "").lower()
    return (any(t in tl for t in toks)) if toks else ((name or "").lower() in tl)


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


def gdelt_articles(name):
    url = ("https://api.gdeltproject.org/api/v2/doc/doc?query=%s&mode=artlist&format=json"
           "&maxrecords=60&sort=datedesc&timespan=2months" % urllib.parse.quote('"%s"' % name))
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


def activity(comp):
    name = comp.get("name"); domain = comp.get("domain", "")
    slug = re.sub(r"[^a-z0-9]+", "-", (comp.get("slug") or name or "").lower()).strip("-")
    print("•", name)
    arts = [a for a in gdelt_articles(name) if a["date"] and within_window(a["date"]) and mentions(a["title"], name)]

    updates = []; confs = []; seen = set()
    for a in arts:
        key = re.sub(r"[^a-z0-9]+", "", a["title"].lower())[:60]
        if key in seen:
            continue
        seen.add(key)
        if CONF.search(a["title"]):
            confs.append({"date": a["date"], "title": a["title"], "link": a["link"]})
            continue
        cat = categorize(a["title"])
        if cat:
            updates.append({"date": a["date"], "category": cat, "title": a["title"], "link": a["link"]})

    # company blog posts in-window
    for b in blog_posts(domain):
        if b["date"] and not within_window(b["date"]):
            continue
        key = re.sub(r"[^a-z0-9]+", "", (b["title"] or "").lower())[:60]
        if not b["title"] or key in seen:
            continue
        seen.add(key)
        (confs if CONF.search(b["title"]) else updates).append(
            {"date": b["date"], "category": "Blog", "title": b["title"], "link": b["link"]})

    updates.sort(key=lambda x: x.get("date", ""), reverse=True)
    confs.sort(key=lambda x: x.get("date", ""), reverse=True)
    ncust = new_customers(slug)
    return {
        "name": name, "domain": domain, "slug": slug,
        "updates": updates[:12],
        "conferences": confs[:6],
        "new_customers": ncust,
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
