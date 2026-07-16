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


SECTOR_THESIS = {
 "Fintech & payments": "modernizing money movement, banking and financial infrastructure",
 "Insurance": "rebuilding the insurance value chain from underwriting to claims",
 "Healthcare & bio": "AI and software reengineering clinical, care-delivery and life-science workflows",
 "Cybersecurity": "securing enterprises against evolving threats and identity risk",
 "AI infra & compute": "the compute, models and tooling layer beneath the AI stack",
 "AI agents & apps": "autonomous agents and applied-AI products that do real work",
 "Data infrastructure": "the data platforms and pipelines that power analytics and AI",
 "Developer tools": "how software gets built, shipped and operated",
 "Defense, aero & space": "national-security, aerospace and space technology",
 "Energy & climate": "the energy transition \u2014 power, storage and decarbonization",
 "Robotics & industrial": "physical AI, robotics and industrial automation",
 "Legal & compliance": "AI for legal, risk and regulatory work",
 "Sales & GTM": "the modern go-to-market and revenue stack",
 "Supply chain & logistics": "digitizing supply chain, freight and logistics",
 "Vertical SaaS": "software purpose-built for specific industries",
 "Crypto & web3": "onchain finance and infrastructure",
 "Consumer & marketplace": "consumer products and marketplaces",
 "Enterprise software": "broad enterprise software and applied AI",
}
SPC_OVERLAP = {"AI agents & apps","AI infra & compute","Data infrastructure","Developer tools",
               "Cybersecurity","Healthcare & bio","Fintech & payments","Insurance","Legal & compliance",
               "Sales & GTM","Supply chain & logistics","Robotics & industrial","Defense, aero & space","Enterprise software"}
CO_INV = {"a16z","andreessen","accel","redpoint","felicis","founders fund","sequoia","benchmark","greylock",
          "lightspeed","bessemer","battery","menlo","index","insight","pear","khosla","coatue","ivp","iconiq",
          "thrive","general catalyst","kleiner","spark","ribbit","scale","salesforce ventures","gv","google ventures"}


def _n(k):
    return "%d deal%s" % (k, "" if k == 1 else "s")


def memo_for(f):
    name = f.get("name", ""); meta = f.get("meta") or {}
    focus = re.sub(r"^(?:Venture Capital|Private Equity)\s*[\u00b7|-]\s*", "", (f.get("focus") or "").strip()).strip().rstrip(".")
    ups = f.get("updates") or []
    inv = [u for u in ups if u.get("type") == "Investment"]
    posts = [u for u in ups if u.get("type") in ("Post", "Thesis")]
    region = meta.get("hq", ""); aum = meta.get("aum", ""); d6 = meta.get("d6")

    bets, sect, stages = [], {}, {}
    for u in inv:
        title = u.get("title") or ""; co = bi.company_of(title); amt = bi.amount_m(title)
        s = sector_of(co + " " + title); sect[s] = sect.get(s, 0) + 1
        sm = STAGE.search(title)
        if sm: g = sm.group(0).title(); stages[g] = stages.get(g, 0) + 1
        if co:
            fn0 = bi.norm(name.split()[0]) if name.split() else ""
            if fn0 and fn0 in bi.norm(co):
                continue   # the fund's own fundraise, not a portfolio bet
            if re.search(r"\b(eyes|to raise|raises?\s+(new\s+)?\$|closes?\s+\$|fund\s+[ivx]+)\b", co.lower()):
                continue
            if amt and amt >= 5000:
                amt = None   # $5B+ is a valuation/mega figure, not a clean round size
            bets.append({"company": co, "amt": amt, "amt_s": money(amt), "date": (u.get("date") or "")[:10], "link": u.get("link") or u.get("url", "")})
    seen, dd = set(), []
    for b in sorted(bets, key=lambda x: (x.get("amt") or 0), reverse=True):
        k = bi.norm(b["company"])
        if k and k not in seen: seen.add(k); dd.append(b)
    top_sect = sorted(sect.items(), key=lambda x: -x[1])
    n = len(inv)

    # --- narrative sections ---
    ov = "%s is a%s venture firm%s%s." % (
        name, (" " + region.split(",")[0]) if region else "",
        (" managing %s" % aum) if aum else "",
        (", among the most active investors we track" if (d6 or 0) >= 60 or n >= 30 else ""))
    if focus:
        ov += " Its stated focus: %s." % focus

    if n == 0:
        six = "We haven't logged public deal activity from %s in the last six months \u2014 either a quiet stretch or deals we couldn't attribute from public sources." % name
    else:
        pace = "a rapid clip" if n >= 30 else ("a steady pace" if n >= 10 else "selectively")
        six = "Over the last six months we tracked %d investment%s and %d post%s/theses from %s, investing at %s." % (
            n, "" if n == 1 else "s", len(posts), "" if len(posts) == 1 else "s", name, pace)

    thesis = ""
    if top_sect:
        s1, n1 = top_sect[0]
        lead = "%s (%s)" % (s1, _n(n1))
        if len(top_sect) > 1:
            lead += ", followed by " + ", ".join("%s (%s)" % (s, _n(k)) for s, k in top_sect[1:3])
        thesis = "The money is concentrated in %s. " % lead
        thesis += "That points to a thesis centered on %s." % SECTOR_THESIS.get(s1, s1.lower())
        if len(top_sect) > 1 and top_sect[1][1] >= max(2, n1 // 3):
            thesis += " There's a genuine second leg in %s (%s), so this isn't a one-note fund." % (top_sect[1][0], SECTOR_THESIS.get(top_sect[1][0], top_sect[1][0].lower()))

    how = ""
    if stages:
        st = sorted(stages.items(), key=lambda x: -x[1])[0][0]
        infer = ("leaning early and taking first-check risk" if "seed" in st.lower() or "pre" in st.lower()
                 else "concentrating at the growth inflection, after product-market fit" if re.search(r"series\s+[bc]|growth|late", st.lower())
                 else "backing companies right as they scale")
        how = "By stage, recent checks skew %s \u2014 %s." % (st, infer)

    notable = ""
    if dd:
        named = [("%s (%s)" % (b["company"], b["amt_s"]) if b["amt_s"] else b["company"]) for b in dd[:5]]
        notable = "Standout recent bets include %s." % ", ".join(named)
        if dd[0].get("amt"):
            notable += " Their largest tracked check went to %s (%s), a read on where their conviction sits right now." % (dd[0]["company"], dd[0]["amt_s"])

    watch = ""
    ov_sec = [s for s, _ in top_sect if s in SPC_OVERLAP]
    is_co = any(c in name.lower() for c in CO_INV)
    parts = []
    if ov_sec:
        parts.append("For Smith Point, the overlap is clearest in %s" % ", ".join(ov_sec[:3]))
    if is_co:
        parts.append("and they're a fund we can often reach founders through")
    watch = (" ".join(parts) + ".") if parts else ""
    if top_sect:
        watch += " Worth watching: continued concentration in %s suggests more of the same ahead%s." % (
            top_sect[0][0], (", while rising %s activity is the emerging tell" % top_sect[1][0]) if len(top_sect) > 1 else "")

    return {
        "name": name,
        "overview": ov, "six_months": six, "thesis": thesis, "how": how,
        "notable": notable, "watch": watch,
        "sectors": [{"name": s, "n": k} for s, k in top_sect[:5]],
        "bets": [{"company": b["company"], "amt": b["amt_s"], "date": b["date"], "link": b["link"]} for b in dd[:8]],
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
