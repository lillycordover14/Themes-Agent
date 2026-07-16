#!/usr/bin/env python3
"""Ingest a raw Substack-archive JSON dump into data/stealth.json (merge + rolling 90-day window).

Used by the weekly Claude task, which CAN reach Substack: it web-fetches
https://stealthstartupspy.substack.com/api/v1/archive?sort=new&limit=30 (the daily GitHub Action
cannot — Substack blocks datacenter IPs), saves the output to a file, then runs:
    python scripts/stealth_ingest.py <that-file>
Robust to truncated dumps (regex field extraction). Reuses scripts/stealth.py for filtering.
"""
import sys, os, re, json, importlib.util, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "stealth.json")
spec = importlib.util.spec_from_file_location("st", os.path.join(ROOT, "scripts", "stealth.py"))
st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)


def parse(raw):
    dates = re.findall(r'"post_date":"([^"]+)"', raw)
    urls = re.findall(r'"canonical_url":"([^"]+)"', raw)
    subs = re.findall(r'"subtitle":"((?:\\.|[^"\\])*)"', raw)
    n = min(len(dates), len(urls), len(subs))
    def dec(s):
        try: return json.loads('"' + s + '"')
        except Exception: return s
    return [{"post_date": dates[i], "canonical_url": urls[i], "subtitle": dec(subs[i])} for i in range(n)]


def main(path):
    raw = open(path, encoding="utf-8").read()
    fit = st.load_net(); TODAY = st.TODAY
    fresh = []
    for e in parse(raw):
        d = st.entry_date(e)
        if d and (TODAY - d).days > st.WINDOW:
            continue
        link = e.get("canonical_url", "")
        for frag in st.fragments(e):
            if st.is_consumer(frag, fit):
                continue
            th = st.theme_of(frag, fit)
            if not th and not st.ENT.search(frag):
                continue
            fresh.append({"company": "", "title": frag, "blurb": "",
                          "theme": th or "Applied / horizontal AI",
                          "date": d.isoformat() if d else "", "link": link})
    # merge with existing, dedup by normalized title, keep rolling 90-day window
    try:
        existing = json.load(open(OUT, encoding="utf-8")).get("items", [])
    except Exception:
        existing = []
    merged, seen = [], set()
    for r in fresh + existing:
        k = st.norm(r.get("title", ""))[:60]
        if not k or k in seen:
            continue
        d = st.entry_date({"post_date": r.get("date", "")})
        if d and (TODAY - d).days > st.WINDOW:
            continue
        seen.add(k); merged.append(r)
    merged.sort(key=lambda x: x.get("date", ""), reverse=True)
    merged = merged[:80]
    if not merged:
        print("stealth_ingest: parsed 0 — leaving existing file untouched"); return
    json.dump({"generated": TODAY.isoformat(), "window_days": st.WINDOW, "count": len(merged), "items": merged},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("stealth_ingest: %d items (%d fresh parsed, merged + 90d window)" % (len(merged), len(fresh)))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/stealth_raw.txt")
