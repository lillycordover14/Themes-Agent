#!/usr/bin/env python3
"""Insights aggregator — WEB/DATA-ONLY, free.

Turns the funds' Investment activity (+ Harmonic just-raised feed) into:
  - a deduped "where money is flowing" ledger of real VC-backed raises (last 6 months), each with
    amount, the investor(s)/fund(s) seen behind it, a theme, and a source link;
  - a theme rollup (which sectors are hot) using the curated sector vocabulary.

Reads data/funds.json + data/harmonic_raises.json; writes data/insights.json. Fail-safe.
Runs in the daily Action (no API key).
"""
import json, os, re, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNDS = os.path.join(ROOT, "data", "funds.json")
HARM = os.path.join(ROOT, "data", "harmonic_raises.json")
OUT = os.path.join(ROOT, "data", "insights.json")
TODAY = datetime.date.today()
WINDOW = 190  # ~6 months

RAISE_V = re.compile(r"\b(raises?|raised|secures?|secured|lands?|landed|closes?|closed|nets?|snags?|bags?|banks?|pulls in|picks up)\b", re.I)
AMT = re.compile(r"\$\s?(\d[\d.,]*)\s?(k|m|mn|million|b|bn|billion)\b", re.I)
FROM_INV = re.compile(r"(?:led by|co-led by|from|backed by)\s+([A-Z][A-Za-z0-9&.\-' ]{2,45})", re.I)
FUND_WORDS = re.compile(r"\b(capital|ventures|partners|fund|management|associates|equity|holdings)\b", re.I)
STAGE_RE = re.compile(r"\bseries\s+([a-e])\b", re.I)

SECTORS = {
    "AI agents": ["agent", "agentic", "copilot", "assistant"],
    "AI infra": ["inference", "gpu", " llm", "mlops", "orchestrat", "vector", "fine-tun", "compute", "foundation model", "token cost", "model training"],
    "Data": ["data ", "analytics", "warehouse", "pipeline", "observability"],
    "Dev tools": ["developer", "devops", " sdk", "open source", "coding", "engineering"],
    "Fintech": ["fintech", "payment", "banking", "lending", "insur", "underwrit", "treasury", "credit", "wealth", " tax", "financial"],
    "Cybersecurity": ["security", "cyber", "threat", "identity", "zero trust", "fraud"],
    "Defense/gov": ["defense", "national security", "govtech", " dod", "military", "autonom", "space"],
    "Robotics/physical": ["robot", "manufactur", "industrial", "warehouse", "drone", "machine vision", "supply chain", "hardware"],
    "Healthcare/bio": ["health", "clinical", "patient", "biotech", " drug", "diagnostic", "medical", "pharma", "care"],
    "Climate/energy": ["climate", "energy", " grid", "solar", "battery", "carbon", "renewable"],
    "Crypto/web3": ["crypto", "blockchain", "web3", "token ", "defi", "stablecoin"],
    "Vertical SaaS": ["vertical", "workflow", "legal", "construction", "logistics", "procurement", "real estate"],
}


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def theme_of(text):
    t = (text or "").lower()
    best, n = "Other", 0
    for label, kws in SECTORS.items():
        c = sum(t.count(k) for k in kws)
        if c > n:
            best, n = label, c
    return best


def amount_m(title):
    m = AMT.search(title)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
    except Exception:
        return None
    u = m.group(2).lower()
    if u in ("b", "bn", "billion"):
        val *= 1000
    elif u in ("k",):
        val /= 1000.0
    return round(val)


def company_of(title):
    m = RAISE_V.search(title)
    if not m:
        return ""
    co = title[:m.start()].strip(" -–—:·|")
    co = re.sub(r"\s*[|–—-]\s*[^-|–—]*$", "", co).strip()   # drop trailing "- Outlet"
    return co


def main():
    try:
        funds = json.load(open(FUNDS, encoding="utf-8")).get("funds", [])
    except Exception as e:
        print("no funds.json:", e); funds = []
    cutoff = (TODAY - datetime.timedelta(days=WINDOW)).isoformat()
    ledger = {}   # norm(company) -> record

    def add(company, amt, date, link, investors, theme, stage, desc):
        k = norm(company)
        if not k:
            return
        r = ledger.get(k)
        if not r:
            r = {"company": company, "amount_m": amt, "date": date, "link": link,
                 "investors": set(investors), "theme": theme, "stage": stage, "desc": desc}
            ledger[k] = r
        else:
            r["investors"].update(investors)
            if amt and (not r["amount_m"] or amt > r["amount_m"]):
                r["amount_m"] = amt
            if date > (r["date"] or ""):
                r["date"] = date; r["link"] = link or r["link"]
            if stage and not r["stage"]:
                r["stage"] = stage
            if desc and not r["desc"]:
                r["desc"] = desc

    for f in funds:
        fund_name = f.get("name", "")
        for u in f.get("updates", []):
            if u.get("type") != "Investment":
                continue
            date = (u.get("date") or "")[:10]
            if date and date < cutoff:
                continue
            title = u.get("title") or ""
            co = company_of(title)
            if not co or len(co) > 48 or FUND_WORDS.search(co):
                continue
            amt = amount_m(title)
            if not amt:
                continue   # keep only real, sized VC raises
            if re.search(r"(incorporated|corporation|\bcorp\b|\bplc\b|holdings|\binc\.?)$", co, re.I):
                continue   # public-company / non-VC shells
            frominv = [x.strip(" .") for x in FROM_INV.findall(title) if 2 < len(x.strip()) < 45]
            st = ("Series " + STAGE_RE.search(title).group(1).upper()) if STAGE_RE.search(title) else ""
            if amt >= 500 and not st and not frominv:
                continue   # very large, no stage, no named VC -> likely PE/debt/growth, not a VC round
            inv = set(frominv); inv.add(fund_name)
            add(co, amt, date, u.get("link") or u.get("url", ""), inv, theme_of(co + " " + title), st, "")

    # fold in Harmonic just-raised feed (VC-backed by construction)
    try:
        harm = json.load(open(HARM, encoding="utf-8")).get("companies", [])
    except Exception:
        harm = []
    import re as _re
    for c in harm:
        name = c.get("name")
        if not name or _re.search(r"(incorporated|corporation|\bcorp\b|\bplc\b|holdings|\binc\.?)$", name, _re.I):
            continue
        st = (c.get("stage") or "").replace("SERIES_", "Series ").replace("_", " ").title().strip()
        amt = round((c.get("last_amount") or 0) / 1e6) or None
        add(name, amt, TODAY.isoformat(), "", set(), theme_of(name + " " + (c.get("desc") or "")), st, (c.get("desc") or "")[:160])

    rows = []
    for r in ledger.values():
        r["investors"] = sorted(i for i in r["investors"] if i)[:6]
        rows.append(r)
    rows.sort(key=lambda x: (x.get("date") or "", x.get("amount_m") or 0), reverse=True)
    rows = rows[:80]

    # theme rollup
    tally = {}
    for r in rows:
        tally.setdefault(r["theme"], []).append(r["company"])
    themes = [{"theme": t, "count": len(v), "examples": v[:6]} for t, v in tally.items()]
    themes.sort(key=lambda x: -x["count"])

    json.dump({"generated": TODAY.isoformat(), "count": len(rows), "raises": rows, "themes": themes},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote insights.json — %d deduped raises across %d themes" % (len(rows), len(themes)))


if __name__ == "__main__":
    main()
