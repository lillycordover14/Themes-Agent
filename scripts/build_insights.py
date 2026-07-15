#!/usr/bin/env python3
"""Insights aggregator — WEB/DATA-ONLY, free. Builds data/insights.json from the funds tab's
tracked raises (Investment updates, 6mo, all stages) + Harmonic feed. Deduped by company; tagged
with stage bucket (unknown->Venture), amount, investors, theme. Emits theme rollup, per-stage
counts, KPIs, concentration line, and a per-fund investor-signal (real early-stage picks)."""
import json, os, re, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNDS = os.path.join(ROOT, "data", "funds.json")
HARM = os.path.join(ROOT, "data", "harmonic_raises.json")
OUT = os.path.join(ROOT, "data", "insights.json")
LLM_CACHE = os.path.join(ROOT, "data", "insights_llm_cache.json")
OPENAI = os.environ.get("OPENAI_API_KEY", "").strip()
TODAY = datetime.date.today()
WINDOW = 190

RAISE_V = re.compile(r"\b(raises?|raised|secures?|secured|lands?|landed|closes?|closed|nets?|snags?|nabs?|bags?|banks?|scores?|pulls in|picks up)\b", re.I)
AMT = re.compile(r"\$\s?(\d[\d.,]*)\s?(k|m|mn|million|b|bn|billion)\b", re.I)
FROM_INV = re.compile(r"(?:led by|co-led by|from|backed by)\s+([A-Z][A-Za-z0-9&.\-' ]{2,45})", re.I)
FUND_WORDS = re.compile(r"\b(capital|ventures|partners|fund|management|associates|equity|holdings)\b", re.I)
SHELL = re.compile(r"(incorporated|corporation|\bcorp\b|\bplc\b|holdings|\binc\.?)$", re.I)
STAGE_BUCKET = re.compile(r"\b(pre-?seed|angel|seed|series\s?([a-e])|growth round|late[- ]stage|mezzanine)\b", re.I)

# theme -> keywords (matched as word-ish substrings on company name + full news title)
THEME_KWS = {
    "Physical AI & robotics": ["robot", "humanoid", "embodied", "physical ai", "physical world", "machine vision", "manufactur", "warehouse", "drone", "autonomous vehicle", "self-driving", "factory", "industrial automation", "hardware", "actuator", "lidar"],
    "Agent-native infra": ["agent infrastructure", "agentic infra", "agentic", "agent orchestration", "multi-agent", "agent platform", "tool use", "\bmcp\b", "agent framework", "orchestration layer", "eval infra", "agent memory"],
    "Applied AI agents": ["ai agent", "ai agents", "copilot", "ai assistant", "ai worker", "ai employee", "voice agent", "ai sdr", "ai coworker", "autonomous agent", "workflow automation", "agent for"],
    "AI compute & models": ["inference", "\bgpu\b", "foundation model", "\bllm\b", "large language model", "model training", "compute", "datacenter", "ai chip", "accelerator", "fine-tun", "pretrain", "frontier model"],
    "AI dev tooling": ["developer", "devtools", "coding", "code generation", "\bcode\b", "software engineering", "\bsdk\b", "ci/cd", "devops", "codebase", "vibe coding"],
    "Data infrastructure": ["data platform", "data infrastructure", "warehouse", "data pipeline", "\betl\b", "analytics", "observability", "vector database", "data lake", "streaming data"],
    "Cybersecurity": ["security", "cyber", "threat", "\bfraud\b", "identity", "zero trust", "\bsoc\b", "endpoint", "vulnerabilit", "phishing", "malware"],
    "Defense & national security": ["defense", "defence", "military", "national security", "\bspace\b", "govtech", "surveillance", "\bdod\b", "warfare", "border"],
    "Fintech & payments": ["fintech", "payments", "banking", "lending", "\bcredit\b", "neobank", "spend management", "wealth", "trading", "capital markets", "card", "remittance", "brokerage"],
    "Financial back-office & compliance AI": ["compliance", "\baml\b", "\bkyc\b", "audit", "risk management", "underwrit", "back office", "back-office", "regtech", "financial operations", "controls", "reconciliation", "financial crime"],
    "Insurance / insurtech": ["insurance", "insurtech", "claims", "actuarial", "reinsurance"],
    "Energy & climate": ["energy", "\bgrid\b", "solar", "battery", "fusion", "nuclear", "carbon", "climate", "renewable", "\bev\b", "power plant", "geothermal", "decarboniz"],
    "Healthcare & bio AI": ["health", "clinical", "patient", "\bdrug\b", "diagnostic", "biotech", "medical", "pharma", "therapeutic", "care delivery", "life science", "genomic"],
    "Legal AI": ["legal", "\blaw\b", "contract", "litigation", "paralegal", "law firm"],
    "Sales & GTM AI": ["sales", "\bgtm\b", "\bcrm\b", "revenue team", "outbound", "prospecting", "go-to-market", "lead generation"],
    "Marketing & creative AI": ["marketing", "advertising", "adtech", "content creation", "creative", "\bdesign\b", "brand", "video generation", "image generation"],
    "HR & workforce": ["recruit", "hiring", "\bhr\b", "payroll", "talent", "workforce", "people ops", "staffing"],
    "Logistics & supply chain": ["logistics", "supply chain", "freight", "shipping", "procurement", "inventory", "fulfillment", "warehouse management"],
    "Vertical SaaS": ["construction", "real estate", "restaurant", "hospitality", "retail", "field service", "proptech", "legaltech", "dental", "agriculture", "education", "edtech"],
    "Consumer & marketplace": ["consumer", "marketplace", "creator", "\bcommerce\b", "social app", "gaming", "shopping", "travel", "dating", "e-commerce"],
    "Crypto & digital assets": ["crypto", "blockchain", "stablecoin", "\bdefi\b", "web3", "tokeniz", "digital asset", "onchain"],
}
THEME_RX = {t: re.compile("|".join(r"\b" + re.escape(k) for k in kws), re.I) for t, kws in THEME_KWS.items()}
ENTERPRISE = re.compile(r"\b(platform|software|saas|enterprise|workflow|automation|\bops\b|operations|management|b2b|api|infrastructure|ai-native|ai-powered|ai )\b", re.I)

FUND_SIGNAL = ["Accel", "Redpoint", "Felicis", "Founders Fund", "Sequoia", "Benchmark", "Greylock",
               "Lightspeed", "Bessemer", "Battery", "Menlo", "Index", "Insight", "Pear", "Y Combinator"]
EARLY = {"Pre-seed", "Seed", "Series A"}


def norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def theme_of(text):
    t = (text or "")
    best, n = "", 0
    for label, rx in THEME_RX.items():
        c = len(rx.findall(t))
        if c > n:
            best, n = label, c
    return best or "Enterprise AI software"


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


LEADIN = re.compile(r"^(exclusive|scoop|breaking|just in|update|report|reports?|opinion|analysis)\s*[:\-–]\s*", re.I)
DESCR = re.compile(r"^(?:ai|ml|genai|fintech|healthtech|insurtech|proptech|legaltech|climate|defen[cs]e|crypto|web3|data|dev(?:eloper)?|security|cyber|robotics?|biotech|enterprise|vertical|b2b|saas|startup)\s+(?:startup|company|firm|platform|unicorn|maker|provider|player|giant|leader|venture|business|app|tool|scaleup)\s+", re.I)


def company_of(title):
    t = LEADIN.sub("", title or "")
    m = RAISE_V.search(t)
    if not m:
        return ""
    co = t[:m.start()].strip(" -–—:·|\"'")
    co = re.sub(r"\s*[|–—-]\s*[^-|–—]*$", "", co).strip()
    co = DESCR.sub("", co).strip()
    if len(co.split()) > 4:            # descriptive headline fragment, not a clean name
        return ""
    return co


THEME_LIST = list(THEME_KWS.keys()) + ["Enterprise AI software"]


def _llm_call(items):
    """items: [{i,name,title}] -> {i:{company,theme}}. gpt-4o-mini, JSON. {} on any failure."""
    import urllib.request as _u
    sys_p = ("You are a VC analyst. For each company (name + funding headline) return the cleaned "
             "company name (proper name only, drop words like 'startup'/'Exclusive:'/descriptions) and the "
             "single best theme from this exact list: " + ", ".join(THEME_LIST) + ". Use 'Unclassified' only if truly unknown. "
             "Reply ONLY with a JSON object: {\"items\":[{\"i\":<int>,\"company\":<str>,\"theme\":<str>}]}.")
    body = json.dumps({"model": "gpt-4o-mini", "temperature": 0, "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": sys_p},
                                    {"role": "user", "content": json.dumps(items)}]}).encode()
    try:
        req = _u.Request("https://api.openai.com/v1/chat/completions", data=body,
                         headers={"Authorization": "Bearer " + OPENAI, "content-type": "application/json"})
        d = json.loads(_u.urlopen(req, timeout=45).read())
        parsed = json.loads(d["choices"][0]["message"]["content"])
        out = {}
        for it in parsed.get("items", []):
            if "i" in it:
                out[int(it["i"])] = {"company": (it.get("company") or "").strip(), "theme": (it.get("theme") or "").strip()}
        return out
    except Exception as e:
        print("  llm batch failed:", e); return {}


def llm_enrich(rows):
    """Clean company name + theme via LLM, cached by company key. No-op without OPENAI_API_KEY."""
    if not OPENAI:
        return
    try:
        cache = json.load(open(LLM_CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    todo = []
    for idx, r in enumerate(rows):
        key = norm(r["company"])
        c = cache.get(key)
        if c:
            r["company"] = c.get("company") or r["company"]
            if c.get("theme"):
                r["theme"] = c["theme"]
        else:
            todo.append((idx, key))
    for chunk_start in range(0, len(todo), 40):
        chunk = todo[chunk_start:chunk_start + 40]
        items = [{"i": idx, "name": rows[idx]["company"], "title": ""} for idx, _k in chunk]
        # include the strongest available context: company name only (headline already parsed into name+theme)
        res = _llm_call(items)
        for idx, key in chunk:
            r = res.get(idx)
            if r:
                if r.get("theme") in THEME_LIST:
                    rows[idx]["theme"] = r["theme"]
                if r.get("company"):
                    rows[idx]["company"] = r["company"]
                cache[key] = {"company": rows[idx]["company"], "theme": rows[idx]["theme"]}
    try:
        json.dump(cache, open(LLM_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass
    print("  LLM enriched %d new companies (cached %d total)" % (len(todo), len(cache)))


def main():
    try:
        funds = json.load(open(FUNDS, encoding="utf-8")).get("funds", [])
    except Exception as e:
        print("no funds.json:", e); funds = []
    cutoff = (TODAY - datetime.timedelta(days=WINDOW)).isoformat()
    ledger = {}
    inv_sig = {}   # fund -> list of picks

    def add(company, amt, date, link, investors, theme, stage):
        k = norm(company)
        if not k:
            return
        r = ledger.get(k)
        if not r:
            ledger[k] = {"company": company, "amount_m": amt, "date": date, "link": link,
                         "investors": set(investors), "theme": theme, "stage": stage}
            return
        r["investors"].update(investors)
        if amt and (not r["amount_m"] or amt > r["amount_m"]):
            r["amount_m"] = amt
        if date > (r["date"] or ""):
            r["date"] = date; r["link"] = link or r["link"]
        if stage and r["stage"] in ("", "Venture") and stage != "Venture":
            r["stage"] = stage

    def match_signal_fund(fund_name):
        fl = (fund_name or "").lower()
        for s in FUND_SIGNAL:
            if s.lower() in fl or (s == "Y Combinator" and ("combinator" in fl or fl.strip() == "yc")):
                return s
        return None

    for f in funds:
        fund_name = f.get("name", "")
        sigfund = match_signal_fund(fund_name)
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
                continue
            inv = set(frominv); inv.add(fund_name)
            th = theme_of(co + " " + title)
            add(co, amt, date, u.get("link") or u.get("url", ""), inv, th, st)
            if sigfund:
                inv_sig.setdefault(sigfund, {}).setdefault(norm(co), {
                    "company": co, "stage": st, "amount_m": amt, "date": date,
                    "link": u.get("link") or u.get("url", ""), "theme": th})

    try:
        harm = json.load(open(HARM, encoding="utf-8")).get("companies", [])
    except Exception:
        harm = []
    for c in harm:
        name = c.get("name")
        if not name or SHELL.search(name):
            continue
        raw = (c.get("stage") or "").replace("SERIES_", "Series ").replace("_", " ").title().strip()
        st = raw or "Venture"
        amt = round((c.get("last_amount") or 0) / 1e6) or None
        add(name, amt, TODAY.isoformat(), ("https://" + c["domain"]) if c.get("domain") else "", set(),
            theme_of(name + " " + (c.get("desc") or "")), st)

    rows = []
    for r in ledger.values():
        r["investors"] = sorted(i for i in r["investors"] if i)[:6]
        rows.append(r)
    rows.sort(key=lambda x: (x.get("date") or "", x.get("amount_m") or 0), reverse=True)
    rows = rows[:200]
    llm_enrich(rows)

    tally = {}
    for r in rows:
        tally.setdefault(r["theme"], []).append(r["company"])
    themes = [{"theme": t, "count": len(v), "examples": v[:6]} for t, v in tally.items()]
    themes.sort(key=lambda x: -x["count"])

    total_cap = sum(r.get("amount_m") or 0 for r in rows)
    early = [r for r in rows if r.get("stage") in EARLY]
    order = ["Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Growth/Late", "Venture"]
    stage_counts = {s: sum(1 for r in rows if r.get("stage") == s) for s in order}
    stage_counts = {k: v for k, v in stage_counts.items() if v}
    named = [t for t in themes if t["theme"] != "Enterprise AI software"]
    kpis = {"strongest_theme": (named[0]["theme"] if named else (themes[0]["theme"] if themes else "")),
            "total_raises": len(rows), "early_raises": len(early),
            "total_cap_m": total_cap, "early_cap_m": sum(r.get("amount_m") or 0 for r in early),
            "stage_counts": stage_counts}

    summary = ""
    if named:
        summary = "Capital is concentrating in " + ", ".join("%s (%d)" % (t["theme"], t["count"]) for t in named[:3]) + "."
        biggest = max((r for r in rows if r.get("amount_m")), key=lambda r: r["amount_m"], default=None)
        if biggest:
            a = biggest["amount_m"]; asx = ("$%.1fB" % (a / 1000)) if a >= 1000 else ("$%dM" % a)
            stg = (biggest["stage"] + ", ") if biggest.get("stage") and biggest["stage"] != "Venture" else ""
            summary += " Largest recent round: %s (%s%s)." % (biggest["company"], stg, asx)

    # investor signal: per-fund early-stage picks (Seed / Series A first), then recent others
    investor_signal = []
    for s in FUND_SIGNAL:
        picks = list((inv_sig.get(s) or {}).values())
        picks.sort(key=lambda x: (x.get("stage") in EARLY, x.get("date") or ""), reverse=True)
        if picks:
            investor_signal.append({"fund": s, "picks": picks[:10],
                                    "early": sum(1 for p in picks if p.get("stage") in EARLY)})

    emerging = []
    for t in themes:
        if t["theme"] == "Enterprise AI software":
            continue   # generic catch-all — not surfaced as an "emerging theme" card
        comps = [r for r in rows if r["theme"] == t["theme"]]
        cap = sum(r.get("amount_m") or 0 for r in comps)
        stg = {}
        for r in comps:
            stg[r["stage"]] = stg.get(r["stage"], 0) + 1
        top_stage = max(stg, key=stg.get) if stg else ""
        emerging.append({"theme": t["theme"], "count": t["count"], "cap_m": cap,
                         "examples": [r["company"] for r in comps][:6], "top_stage": top_stage})
    emerging = emerging[:12]

    json.dump({"generated": TODAY.isoformat(), "count": len(rows), "summary": summary, "kpis": kpis,
               "raises": rows, "themes": themes, "emerging": emerging, "investor_signal": investor_signal},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote insights.json — %d raises, %d themes, %d funds in investor signal" % (len(rows), len(themes), len(investor_signal)))


if __name__ == "__main__":
    main()
