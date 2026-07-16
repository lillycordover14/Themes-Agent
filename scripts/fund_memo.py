#!/usr/bin/env python3
"""Detailed per-fund memos — pure Python, free, all firms (runs in the daily Action).

Synthesizes a grounded write-up for every fund from data/funds.json: thesis & sector focus (from
their focus text + a sector breakdown of their actual investments) and notable bets & pattern
(real portfolio companies + amounts, stage/sector skew), plus partners and firm metrics. No LLM,
no tokens. Writes data/fund_memos.json {slug: {overview, focus, sectors, bets, pattern, people, generated}}.
"""
import json, os, re, importlib.util, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNDS = os.path.join(ROOT, "data", "funds.json")
OUT = os.path.join(ROOT, "data", "fund_memos.json")
TODAY = datetime.date.today()

bi = importlib.util.module_from_spec(importlib.util.spec_from_file_location("bi", os.path.join(ROOT, "scripts", "build_insights.py")))
importlib.util.spec_from_file_location("bi", os.path.join(ROOT, "scripts", "build_insights.py")).loader.exec_module(bi)

SECTORS = [
    ("Fintech & payments", ["fintech","payment","banking","neobank","lending","credit","treasury","capital markets","brokerage","remittance","spend management","wealth"]),
    ("Insurance", ["insurance","insurtech","actuarial","claims","underwriting","reinsurance"]),
    ("Healthcare & bio", ["health","clinical","patient","biotech","drug","diagnostic","medical","pharma","oncology","therapeutic","genomic","care","life science","medtech"]),
    ("Cybersecurity", ["security","cyber","siem","threat","malware","phishing","zero trust","endpoint","vulnerabilit","identity","fraud"]),
    ("AI infra & compute", ["gpu","inference","compute","model training","foundation model"," llm","semiconductor","chip","datacenter","accelerator"]),
    ("AI agents & apps", ["ai agent","agent","copilot","ai assistant","agentic","genai","ai-native","voice ai"]),
    ("Data infrastructure", ["data platform","data infrastructure","database","warehouse","etl","data pipeline","analytics","observability","vector"]),
    ("Developer tools", ["developer","devtools","devops","sdk"," api","coding","software engineering","ci/cd","platform engineering"]),
    ("Defense, aero & space", ["defense","defence","military","aerospace","space","satellite","dod","national security","drone"]),
    ("Energy & climate", ["energy","climate","nuclear","fusion","battery","grid","solar","carbon","geothermal","renewable"]),
    ("Robotics & industrial", ["robot","robotics","autonomous","manufactur","industrial","factory","warehouse"]),
    ("Legal & compliance", ["legal"," law","contract","litigation","compliance","regtech","grc"]),
    ("Sales & GTM", ["sales"," crm","go-to-market"," gtm","revenue","outbound","prospecting"]),
    ("Supply chain & logistics", ["logistics","supply chain","freight","shipping","procurement","inventory","fulfillment"]),
    ("Vertical SaaS", ["construction","real estate","proptech","retail","hospitality","restaurant","education","edtech","agriculture"]),
    ("Crypto & web3", ["crypto","blockchain","web3","stablecoin","defi","token","onchain"]),
    ("Consumer & marketplace", ["consumer","marketplace","creator","commerce","social","gaming","travel"]),
]
STAGE = re.compile(r"\b(pre-?seed|seed|series\s+([a-e])|growth|late[- ]stage)\b", re.I)


def sector_of(text):
    t = " " + (text or "").lower() + " "
    best, n = "", 0
    for label, kws in SECTORS:
        c = sum(1 for k in kws if k in t)
        if c > n:
            best, n = label, c
    return best or "Enterprise software"


def money(a):
    if not a:
        return ""
    return ("$%.1fB" % (a / 1000)) if a >= 1000 else ("$%dM" % a)


def memo_for(f):
    name = f.get("name", "")
    meta = f.get("meta") or {}
    focus = (f.get("focus") or "").strip()
    ups = f.get("updates") or []
    inv = [u for u in ups if u.get("type") == "Investment"]
    posts = [u for u in ups if u.get("type") in ("Post", "Thesis")]

    bets, sect = [], {}
    stages = {}
    for u in inv:
        title = u.get("title") or ""
        co = bi.company_of(title)
        amt = bi.amount_m(title)
        s = sector_of(co + " " + title)
        sect[s] = sect.get(s, 0) + 1
        sm = STAGE.search(title)
        if sm:
            g = sm.group(0).title()
            stages[g] = stages.get(g, 0) + 1
        if co:
            bets.append({"company": co, "amt": money(amt), "date": (u.get("date") or "")[:10], "link": u.get("link") or u.get("url", "")})
    top_sect = sorted(sect.items(), key=lambda x: -x[1])[:4]
    # de-dupe bets by company, keep newest, cap 8
    seen, dedup = set(), []
    for b in sorted(bets, key=lambda x: x.get("date", ""), reverse=True):
        k = bi.norm(b["company"])
        if k and k not in seen:
            seen.add(k); dedup.append(b)
    dedup = dedup[:8]

    # overview line
    ov = []
    if meta.get("hq"): ov.append(meta["hq"])
    if meta.get("aum"): ov.append("AUM " + str(meta["aum"]))
    if meta.get("d6") is not None: ov.append("%s deals/6mo" % meta["d6"])
    if meta.get("quartile") == 1: ov.append("top-quartile")
    overview = "%s%s." % (name, (" — " + ", ".join(ov)) if ov else "")

    # pattern sentence
    pattern = ""
    if top_sect:
        lead = ", ".join("%s (%d)" % (s, n) for s, n in top_sect)
        pattern = "Recent capital concentrates in %s" % lead
        if stages:
            tops = sorted(stages.items(), key=lambda x: -x[1])[0][0]
            pattern += "; deals skew %s" % tops
        pattern += "."

    people = [{"name": p.get("name", ""), "role": p.get("role", "")} for p in (f.get("people") or [])[:4] if p.get("name")]

    return {
        "overview": overview,
        "focus": focus,
        "activity": "Tracked activity: %d investments, %d posts/theses (last ~6 months)." % (len(inv), len(posts)),
        "sectors": [{"name": s, "n": n} for s, n in top_sect],
        "pattern": pattern,
        "bets": dedup,
        "people": people,
        "generated": TODAY.isoformat(),
    }


def main():
    try:
        funds = json.load(open(FUNDS, encoding="utf-8")).get("funds", [])
    except Exception as e:
        print("no funds.json:", e); return
    out = {}
    for f in funds:
        slug = f.get("slug") or re.sub(r"[^a-z0-9]+", "-", (f.get("name") or "").lower()).strip("-")
        if slug:
            out[slug] = memo_for(f)
    json.dump({"generated": TODAY.isoformat(), "memos": out}, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote fund_memos.json — %d memos" % len(out))


if __name__ == "__main__":
    main()
