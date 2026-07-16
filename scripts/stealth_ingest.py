#!/usr/bin/env python3
"""Ingest Stealth Startup Spy POST PAGES into data/stealth.json (rich records + rolling 90-day window).

Each weekly post page lists companies with structured detail (founder, company, description, industry,
HQ, team size, links). This parses that structure, filters to B2B enterprise fits (SPC thesis; drops
consumer/crypto), and merges into data/stealth.json. The daily GitHub Action can't reach Substack, so
this is driven by the weekly Claude task (or on demand), which fetches the post pages and passes the
saved text file(s) here:  python scripts/stealth_ingest.py <file1.txt> [file2.txt ...]
Fail-safe: parses 0 -> leaves the existing file untouched.
"""
import sys, os, re, json, importlib.util, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "stealth.json")
spec = importlib.util.spec_from_file_location("st", os.path.join(ROOT, "scripts", "stealth.py"))
st = importlib.util.module_from_spec(spec); spec.loader.exec_module(st)

MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}


def _field(block, label):
    m = re.search(r"\*\*%s:?\*\*\s*(.+)" % re.escape(label), block)
    return m.group(1).strip() if m else ""


def _post_date(text):
    m = re.search(r"canonical:\s*\S+", text)  # placeholder; date parsed from rendered header
    m = re.search(r"\b([A-Z][a-z]{2}) (\d{1,2}), (\d{4})\b", text)
    if m and m.group(1) in MONTHS:
        try:
            return datetime.date(int(m.group(3)), MONTHS[m.group(1)], int(m.group(2))).isoformat()
        except Exception:
            pass
    return ""


def _canonical(text):
    m = re.search(r"canonical:\s*(https://\S+)", text)
    return m.group(1).strip() if m else ""


def parse_post_page(text):
    """Return rich company records from a single Stealth Startup Spy post page (markdown text)."""
    date = _post_date(text); link = _canonical(text)
    # split into per-company blocks at '## ' headers
    parts = re.split(r"\n##\s+", "\n" + text)
    out = []
    for b in parts[1:]:
        head = b.split("\n", 1)[0].strip()
        if head.lower().startswith(("founders coming out", "key talent", "discussion", "ready for")):
            continue
        # header: "<Founder> - <Title> at [<Company>](<url>)"  |  "<Founder> - Founder at Stealth Startup"
        founder = re.split(r"\s+[-–]\s+", head)[0].strip()
        title = ""
        mt = re.search(r"[-–]\s+(.+?)\s+at\s+", head)
        if mt:
            title = mt.group(1).strip()
        cm = re.search(r"at\s+\[([^\]]+)\]\((https?://[^)]+)\)", head)
        company = cm.group(1).strip() if cm else ""
        url = cm.group(2).strip() if cm else ""
        if not company or "stealth" in company.lower():
            company = ""  # truly stealth (unnamed)
        # description: a paragraph starting with "[Company](url) ..." OR an italic building line
        desc = ""
        dm = re.search(r"\n\[[^\]]+\]\((?:https?://[^)]+)\)\s+([A-Za-z][^\n]{15,})", b)
        if dm:
            desc = dm.group(1).strip()
        else:
            im = re.search(r"\n\*([^*\n]{15,})\*", b)  # italic "*Building ...*" line
            if im:
                desc = im.group(1).strip()
        industry = _field(b, "Industry").split("|")[0].strip()
        hq = _field(b, "HQ")
        team = ""
        tm = re.search(r"Team Size:?\*{0,2}\s*(\d+)", b)
        if tm:
            team = tm.group(1)
        stealth_t = _field(b, "Time Spent in Stealth Mode")
        prior = _field(b, "Prior Experience")
        li = re.search(r"\[LinkedIn\]\((https?://[^)]+)\)", b)
        em = re.search(r"mailto:([^)\s]+)", b)
        linkedin = li.group(1) if li else ""
        email = em.group(1) if em else ""
        blob = " ".join([company, title, desc, industry, prior])
        if st.is_consumer(blob, st.load_net()):
            continue
        theme = st.theme_of(blob, st.load_net())
        if not theme and not st.ENT.search(blob):
            continue
        if desc and desc[:1].islower() and company:
            desc = company + " " + desc      # "Demi is a proactive AI assistant..."
        name = founder if founder and 2 < len(founder) < 40 else ""
        out.append({"company": company, "url": url, "founder": name, "founder_title": title,
                    "desc": desc[:260], "industry": industry[:60], "hq": hq[:60], "team": team,
                    "stealth": stealth_t[:24], "linkedin": linkedin, "email": email,
                    "theme": theme or "Applied / horizontal AI", "date": date, "link": link})
    return out


def main(paths):
    fit = st.load_net(); TODAY = st.TODAY
    fresh = []
    for p in paths:
        try:
            fresh += parse_post_page(open(p, encoding="utf-8").read())
        except Exception as e:
            print("skip", p, e)
    try:
        existing = json.load(open(OUT, encoding="utf-8")).get("items", [])
    except Exception:
        existing = []
    merged, seen = [], set()
    for r in fresh + existing:
        key = st.norm(r.get("company") or "") or st.norm(r.get("founder") or "") or st.norm(r.get("title") or r.get("desc") or "")[:40]
        if not key or key in seen:
            continue
        d = r.get("date", "")
        if d:
            try:
                y, mo, dd = map(int, d[:10].split("-"))
                if (TODAY - datetime.date(y, mo, dd)).days > st.WINDOW:
                    continue
            except Exception:
                pass
        seen.add(key); merged.append(r)
    merged.sort(key=lambda x: x.get("date", ""), reverse=True)
    merged = merged[:80]
    if not merged:
        print("stealth_ingest: parsed 0 — leaving existing untouched"); return
    json.dump({"generated": TODAY.isoformat(), "window_days": st.WINDOW, "count": len(merged), "items": merged},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("stealth_ingest: %d items (%d fresh parsed)" % (len(merged), len(fresh)))


if __name__ == "__main__":
    main(sys.argv[1:] or [])
