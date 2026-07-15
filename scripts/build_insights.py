#!/usr/bin/env python3
"""Insights aggregator — WEB/DATA-ONLY, free.

Builds data/insights.json from the funds tab's tracked raises (Investment updates, last 6 months,
ALL stages) plus the Harmonic just-raised feed. Every raise is deduped by company and tagged with:
company, stage bucket (unknown -> "Venture"), amount, investors/funds seen behind it, theme, HQ, HC.
Also emits a theme rollup, per-stage counts, KPI aggregates, and a plain-English concentration line.
The dashboard filters everything client-side by stage. Fail-safe; runs in the daily Action.
"""
import json, os, re, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNDS = os.path.join(ROOT, "data", "funds.json")
HARM = os.path.join(ROOT, "data", "harmonic_raises.json")
OUT = os.path.join(ROOT, "data", "insights.json")
TODAY = datetime.date.today()
WINDOW = 190  # ~6 months

RAISE_V = re.compile(r"\b(raises?|raised|secures?|secured|lands?|landed|closes?|closed|nets?|snags?|nabs?|bags?|banks?|scores?|pulls in|picks up)\b", re.I)
AMT = re.compile(r"\$\s?(\d[\d.,]*)\s?(k|m|mn|million|b|bn|billion)\b", re.I)
FROM_INV = re.compile(r"(?:led by|co-led by|from|backed by)\s+([A-Z][A-Za-z0-9&.\-' ]{2,45})", re.I)
FUND_WORDS = re.compile(r"\b(capital|ventures|partners|fund|management|associates|equity|holdings)\b", re.I)
SHELL = re.compile(r"(incorporated|corporation|\bcorp\b|\bplc\b|holdings|\binc\.?)$", re.I)
STAGE_BUCKET = re.compile(r"\b(pre-?seed|angel|seed|series\s?([a-e])|growth round|late[- ]stage|mezzanine)\b", re.I)

SECTORS = {
    "AI agents": ["agent", "agentic", "copilot", "assistant", "automation", "voice ai", "chatbot"],
    "AI infra": ["inference", "gpu", " llm", "mlops", "orchestrat", "vector", "fine-tun", "compute", "foundation model", "token cost", "model training", "datacenter"],
    "Data": ["data ", "analytics", "warehouse", "pipeline", "observability", "etl"],
    "Dev tools": ["developer", "devops", " sdk", "open source", "coding", "software engineering", "code "],
    "Fintech": ["fintech", "payment", "banking", "lending", "insur", "underwrit", "treasury", "credit", "wealth", " tax", "financial", "capital markets", "trading"],
    "Cybersecurity": ["security", "cyber", "threat", "identity", "zero trust", "fraud", "soc "],
    "Defense/gov": ["defense", "national security", "govtech", " dod", "military", "autonom", "space", "drone", "surveillance"],
    "Robotics/physical": ["robot", "manufactur", "industrial", "warehouse", "machine vision", "supply chain", "hardware", "factory"],
    "Healthcare/bio": ["health", "clinical", "patient", "biotech", " drug", "diagnostic", "medical", "pharma", "care", "therapeutic"],
    "Climate/energy": ["climate", "energy", " grid", "solar", "battery", "carbon", "renewable", "nuclear", "fusion"],
    "Crypto/web3": ["crypto", "blockchain", "web3", "token ", "defi", "stablecoin"],
    "Vertical SaaS": ["vertical", "workflow", "legal", "construction", "logistics", "procurement", "real estate", "hr ", "recruit", "marketing", "sales ", "gtm", "insurance", "retail", "hospitality"],
    "Consumer/marketplace": ["consumer", "marketplace", "creator", "commerce", "social", "gaming", "shopping", "travel", "media"],
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


def stage_bucket(title):
    m = STAGE_BUCKET.search(title or "")
    if not m:
        return "Venture"
    g = m.group(0).lower()
    if "pre" in g or "angel" in g:
        return "Pre-seed"
    if "seed" in g:
        return "Seed"
    if "growth" in g or "late" in g or "mezz" in g:
        return "Growth/Late"
    if m.group(2):
        return "Series " + m.group(2).upper()
    return "Venture"


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
    elif u == "k":
        val /= 1000.0
    return round(val)


def company_of(title):
    m = RAISE_V.search(title)
    if not m:
        return ""
    co = title[:m.start()].strip(" -–—:·|")
    co = re.sub(r"\s*[|–—-]\s*[^-|–—]*$", "", co).strip()
    return co


def main():
    try:
        funds = json.load(open(FUNDS, encoding="utf-8")).get("funds", [])
    except Exception as e:
        print("no funds.json:", e); funds = []
    cutoff = (TODAY - datetime.timedelta(days=WINDOW)).isoformat()
    ledger = {}

    def add(company, amt, date, link, investors, theme, stage, desc, hq="", hc=None):
        k = norm(company)
        if not k:
            return
        r = ledger.get(k)
        if not r:
            ledger[k] = {"company": company, "amount_m": amt, "date": date, "link": link,
                         "investors": set(investors), "theme": theme, "stage": stage,
                         "desc": desc, "hq": hq, "hc": hc}
            return
        r["investors"].update(investors)
        if amt and (not r["amount_m"] or amt > r["amount_m"]):
            r["amount_m"] = amt
        if date > (r["date"] or ""):
            r["date"] = date; r["link"] = link or r["link"]
        if stage and (r["stage"] in ("", "Venture")) and stage != "Venture":
            r["stage"] = stage
        if desc and not r["desc"]:
            r["desc"] = desc
        if hq and not r.get("hq"):
            r["hq"] = hq
        if hc and not r.get("hc"):
            r["hc"] = hc

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
            if not co or len(co) > 48 or FUND_WORDS.search(co) or SHELL.search(co):
                continue
            amt = amount_m(title)
            frominv = [x.strip(" .") for x in FROM_INV.findall(title) if 2 < len(x.strip()) < 45]
            st = stage_bucket(title)
            if amt and amt >= 500 and st == "Venture" and not frominv:
                continue   # very large, no stage, no named VC -> likely PE/debt/growth
            inv = set(frominv); inv.add(fund_name)
            add(co, amt, date, u.get("link") or u.get("url", ""), inv,
                theme_of(co + " " + title), st, "")

    try:
        harm = json.load(open(HARM, encoding="utf-8")).get("companies", [])
    except Exception:
        harm = []
    for c in harm:
        name = c.get("name")
        if not name or SHELL.search(name):
            continue
        raw = (c.get("stage") or "").replace("SERIES_", "Series ")