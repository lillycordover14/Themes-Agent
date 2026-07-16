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



SECTORS = [
    ("Cybersecurity", ["cybersecurity","cyber security","siem","threat","malware","phishing","zero trust","endpoint","vulnerabilit","soc ","identity","appsec","ransomware","detection and response"]),
    ("Fintech & payments", ["fintech","payments","payment","banking","neobank","lending","credit","treasury","capital markets","brokerage","remittance","cards","spend management","financial infrastructure","wealth"]),
    ("Insurance / insurtech", ["insurance","insurtech","actuarial","claims","underwriting","reinsurance"]),
    ("Healthcare & bio", ["healthcare","health","clinical","patient","biotech","drug","diagnostic","medical","pharma","oncology","therapeutic","genomic","care","life science","medtech","provider","rcm","revenue cycle"]),
    ("Robotics & physical AI", ["robotics","robot","physical ai","autonomous","drone","humanoid","actuator","teleop","industrial automation","warehouse automation"]),
    ("AI infrastructure & compute", ["gpu","inference","compute","model training","foundation model"," llm","semiconductor","chip","tpu","asic","accelerator","datacenter","cuda","hardware design"]),
    ("Data infrastructure", ["data platform","data infrastructure","database","warehouse","data pipeline"," etl","data quality","observability","vector","analytics","data governance","lakehouse"]),
    ("Developer tools", ["developer","devtools","dev tools","devops","sdk"," api ","coding","software engineering","ci/cd","codebase","platform engineering","infrastructure as code"]),
    ("Defense, aerospace & space", ["defense","defence","military","aerospace","space","satellite","dod","interceptor","national security","weapons","isr","missile","nuclear technology"]),
    ("Energy, climate & nuclear", ["energy","climate","nuclear","fusion","isotope","battery","grid","solar","carbon","geothermal","renewable","power"]),
    ("Legal tech", ["legal","law firm"," law ","contract","litigation","paralegal","compliance","regulatory"]),
    ("Sales & GTM", ["sales","crm","go-to-market"," gtm","revenue team","outbound","prospecting","pipeline","lead generation"]),
    ("Marketing & creative", ["marketing","advertising","adtech","content creation","creative","brand","seo","video generation","image generation"]),
    ("HR & workforce", ["recruit","hiring","payroll","talent","workforce","people ops","staffing","hr "]),
    ("Supply chain & logistics", ["supply chain","logistics","freight","shipping","procurement","inventory","fulfillment","warehouse management"]),
    ("Manufacturing & materials", ["manufacturing","industrial","factory","cnc","advanced materials","materials","machining","quality inspection"]),
    ("Government & public sector", ["government","public sector","govtech","municipal","citizen","permitting"]),
    ("Construction & real estate", ["construction","real estate","proptech","building","architecture"]),
    ("Voice & language AI", ["voice ai","speech","voice agent","transcription","translation","language model app"]),
    ("Productivity & workplace", ["workplace","productivity","collaboration","meeting","knowledge management","assistant","workflow automation","operations"]),
]
_AI_GENERIC = ["artificial intelligence","ai-native","ai native"," ai ","machine learning"," ml ","genai","agent","copilot"]

def sector_of(text):
    t = " " + (text or "").lower() + " "
    best, n = "", 0
    for label, kws in SECTORS:
        c = sum(1 for k in kws if k in t)
        if c > n:
            best, n = label, c
    if best:
        return best
    if any(k in t for k in _AI_GENERIC):
        return "AI (broad / applied)"
    return "Enterprise software"


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


def _parse_blocks(region, date, link, status):
    out = []
    parts = re.split(r"\n##\s+", "\n" + region)
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
        if not st.theme_of(blob, st.load_net()) and not st.ENT.search(blob):
            continue
        sector = sector_of(industry + " . " + desc + " . " + prior + " . " + title)
        if desc and desc[:1].islower() and company:
            desc = company + " " + desc      # "Demi is a proactive AI assistant..."
        name = founder if founder and 2 < len(founder) < 40 else ""
        out.append({"company": company, "url": url, "founder": name, "founder_title": title,
                    "desc": desc[:260], "prior": prior[:200], "industry": industry[:60], "hq": hq[:60],
                    "team": team, "stealth": stealth_t[:24], "linkedin": linkedin, "email": email,
                    "status": status, "theme": sector, "date": date, "link": link})
    return out


def parse_post_page(text):
    """Rich records split by section: 'emerging' (coming out of stealth) vs 'going' (key talent under stealth)."""
    date = _post_date(text); link = _canonical(text)
    i_out = text.find("Founders Coming Out of Stealth")
    i_under = text.find("Key Talent Going Under Stealth")
    recs = []
    if i_out >= 0 or i_under >= 0:
        if i_out >= 0:
            emerging = text[i_out: i_under if i_under > i_out else len(text)]
            recs += _parse_blocks(emerging, date, link, "emerging")
        if i_under >= 0:
            recs += _parse_blocks(text[i_under:], date, link, "going")
    else:
        recs = _parse_blocks(text, date, link, "emerging")
    return recs


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
