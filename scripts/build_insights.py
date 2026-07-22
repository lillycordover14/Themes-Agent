#!/usr/bin/env python3
"""Insights aggregator — WEB/DATA-ONLY, free. Builds data/insights.json from the funds tab's
tracked raises (Investment updates, 6mo, all stages) + Harmonic feed. Deduped by company; tagged
with stage bucket (unknown->Venture), amount, investors, theme. Emits theme rollup, per-stage
counts, KPIs, concentration line, and a per-fund investor-signal (real early-stage picks)."""
import json, os, re, time, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FUNDS = os.path.join(ROOT, "data", "funds.json")
HARM = os.path.join(ROOT, "data", "harmonic_raises.json")
OUT = os.path.join(ROOT, "data", "insights.json")
FIRST_SEEN = os.path.join(ROOT, "data", "raise_first_seen.json")
THEME_HIST = os.path.join(ROOT, "data", "insights_theme_history.jsonl")
NAME_RES_PATH = os.path.join(ROOT, "data", "name_resolution.json")
try:
    NAME_RES = json.load(open(NAME_RES_PATH, encoding="utf-8"))
except Exception:
    NAME_RES = {}
def reskey(title):
    return re.sub(r"[^a-z0-9]+", "", (title or "").lower())[:80]
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

FUND_SIGNAL = ["a16z", "Accel", "Redpoint", "Felicis", "Founders Fund", "Sequoia", "Benchmark", "Greylock",
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
    return best or "Applied / horizontal AI"


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


INV_STOP = {"y combinator","yc","ycombinator","a16z","andreessen horowitz","sequoia","accel","greylock","benchmark",
            "kleiner perkins","kleiner","lightspeed","bessemer","index ventures","founders fund","khosla","khosla ventures",
            "tiger global","coatue","insight partners","general catalyst","gv","google ventures","first round","nea","ivp",
            "iconiq","thrive capital","thrive","redpoint","felicis","menlo ventures","battery ventures","spark capital","ribbit",
            "scale venture partners","emergence","craft ventures","8vc","lux capital","dimension","bain capital","tcv","norwest",
            "ggv","dst global","softbank","sapphire ventures","ngp capital","sorenson","flybridge","headline","alleycorp"}
DEMO_STOP = {"alabama","alaska","arizona","arkansas","california","colorado","connecticut","delaware","florida","georgia",
            "hawaii","idaho","illinois","indiana","iowa","kansas","kentucky","louisiana","maine","maryland","massachusetts",
            "michigan","minnesota","mississippi","missouri","montana","nebraska","nevada","ohio","oklahoma","oregon",
            "pennsylvania","tennessee","texas","utah","vermont","virginia","washington","wisconsin","wyoming",
            "american","indian","chinese","british","israeli","european","african","canadian","australian","french","german",
            "japanese","korean","singaporean","dutch","spanish","italian","brazilian","mexican","nigerian","kenyan","irish",
            "swiss","swedish","danish","norwegian","finnish","polish","turkish","emirati","saudi","egyptian","sri lankan"}
DEMO_LEAD = sorted(DEMO_STOP, key=len, reverse=True)
DESC_TAIL = {"fintech","startup","firm","platform","maker","unicorn","provider","player","giant","leader","scaleup","business","venture"}


def company_of(title):
    t = LEADIN.sub("", title or "")
    m = RAISE_V.search(t)
    if not m:
        return ""
    co = t[:m.start()].strip(" -–—:·|\"'")
    co = re.sub(r"\s+[|–—-]\s+.*$", "", co).strip()   # only split on SPACED separators (keep hyphenated words like Illinois-based)
    co = DESCR.sub("", co).strip()
    co = re.sub(r",\s+(?:an?|the)\b.*$", "", co).strip(" ,")   # drop appositive ("Maxima, an AI accounting platform" -> "Maxima")
    # strip a leading descriptor phrase that ends in startup/company/etc ("AI coworker startup Viktor" -> "Viktor")
    co = re.sub(r"^(?:[A-Za-z][\w.&-]*\s+){1,3}?(?:startup|start-up|company|firm|platform|venture|maker)\s+(?=[A-Z])", "", co).strip()
    # headline-about-a-person / non-company fragments -> not a company
    _lw = co.lower()
    if re.search(r"[\u2019']s\b", co):                 # possessive subject ("Gillibrand's ... son")
        return ""
    _BAD = {"ceo","cto","cfo","coo","cmo","cro","president","founder","co-founder","cofounder","chief",
            "senator","sen","rep","congressman","congresswoman","governor","son","daughter","wife","husband",
            "exec","execs","executive","executives","billionaire","heir","professor","alumnus","alumni"}
    if any(re.search(r"\b" + re.escape(b) + r"\b", _lw) for b in _BAD):
        return ""
    # strip a leading bare sector word / descriptor ("fintech Float"->"Float", "Trading app Fomo"->"Fomo")
    co = re.sub(r"^(?:fintech|healthtech|insurtech|proptech|legaltech|climatetech|edtech|adtech|trading app|pitch deck)\s*:?\s+", "", co, flags=re.I).strip(" :-")
    _FUNDSTOP = {"menlo","accel","sequoia","redpoint","bessemer","lightspeed","kleiner","insight","khosla","coatue",
                 "felicis","greylock","benchmark","battery","index","pear","thrive","a16z","andreessen","foundersfund",
                 "generalcatalyst","iconiq","ivp","nea","gv","greycroft","emergence","craft","8vc","dst","tiger","bain"}
    if norm(co) in _FUNDSTOP or "pitch deck" in co.lower() or "ex-apple" in co.lower():
        return ""
    # strip a leading "<X>-backed / -based / -led / -founded" qualifier (e.g. "Illinois-based Klinic", "Y Combinator-backed Klinic")
    co = re.sub(r"^[A-Za-z0-9.&'’ ]+?-(?:backed|based|led|founded|headquartered)\b\s*", "", co, flags=re.I).strip(" -–—:·|")
    # strip a leading nationality/state word ("Sri Lankan Klinic" -> "Klinic")
    low = co.lower()
    for d in DEMO_LEAD:
        if low.startswith(d + " "):
            co = co[len(d):].strip(); low = co.lower(); break
    co = re.sub(r"^(?:fintech|healthtech|insurtech|proptech|legaltech|climatetech|edtech|adtech)\s+", "", co, flags=re.I).strip()  # after demonym strip ("Canadian fintech Float"->"Float")
    if len(co.split()) > 4:            # descriptive headline fragment, not a clean name
        return ""
    JUNK = {"ai", "ml", "api", "saas", "the", "a", "an", "new", "app", "data", "cloud", "io", "inc",
            "startup", "company", "it", "us", "tech", "labs", "group"}
    toks = low.split()
    if low in INV_STOP or low in DEMO_STOP:
        return ""                      # an investor/accelerator or a geography, not the company
    if toks and toks[-1] in DESC_TAIL:
        return ""                      # trailing descriptor ("... fintech", "... startup"), not a real name
    if norm(co) in JUNK or len(re.sub(r"[^a-z0-9]", "", co.lower())) < 3:
        return ""                      # generic token, not a real company name
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


UA_H = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"}
THEME_CACHE = os.path.join(ROOT, "data", "insights_theme_cache.json")


def _get(url, timeout=10):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=UA_H), timeout=timeout).read().decode("utf-8", "replace")
    except Exception:
        return ""


def clearbit_domain(name):
    """Resolve company name -> (domain, clean_name) via Clearbit's free autocomplete. ('','') on miss."""
    try:
        raw = _get("https://autocomplete.clearbit.com/v1/companies/suggest?query=" + urllib.parse.quote(name), 8)
        arr = json.loads(raw) if raw else []
    except Exception:
        arr = []
    if isinstance(arr, list) and arr:
        nn = norm(name)
        for it in arr:
            if nn and (nn in norm(it.get("name", "")) or norm(it.get("name", "")).startswith(nn[:6])):
                return it.get("domain", ""), it.get("name", "")
        return arr[0].get("domain", ""), arr[0].get("name", "")
    return "", ""


def site_text(domain):
    """Homepage <title> + meta/og description — a concise description of what the company does."""
    if not domain:
        return ""
    html = _get("https://" + domain.lstrip("/"))
    if not html:
        return ""
    parts = []
    t = re.search(r"<title[^>]*>([^<]{3,140})", html, re.I)
    if t:
        parts.append(t.group(1))
    for pat in (r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']{5,300})',
                r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']{5,300})'):
        m = re.search(pat, html, re.I)
        if m:
            parts.append(m.group(1))
    return " ".join(parts)[:600]


def enrich_themes(rows, cap=None):
    """For companies the headline could not classify, resolve their site and theme from what they DO.
    Cached in data/insights_theme_cache.json (committed) so repeat runs are near-free. Fully free."""
    if cap is None:
        cap = int(os.environ.get("INSIGHTS_FETCH_CAP", "200"))
    try:
        cache = json.load(open(THEME_CACHE, encoding="utf-8"))
    except Exception:
        cache = {}
    fetched = 0; t0 = time.time()
    for r in rows:
        k = norm(r["company"])
        if k in cache:
            c = cache[k]
            if c.get("theme"):
                r["theme"] = c["theme"]
            if c.get("clean"):
                r["company"] = c["clean"]
            continue
        if fetched >= cap or (time.time() - t0) > 300:
            continue
        fetched += 1
        dom, clean = clearbit_domain(r["company"])
        if not dom:
            slug = re.sub(r"[^a-z0-9]", "", r["company"].lower())
            for g in (slug + ".com", slug + ".ai", slug + ".io"):
                if site_text(g):
                    dom = g; break
        txt = site_text(dom) if dom else ""
        th = theme_of(txt) if txt else r["theme"]      # site says what they do; else keep headline theme
        if clean and 2 < len(clean) < 42:
            r["company"] = clean
        if th:
            r["theme"] = th
        cache[k] = {"theme": r["theme"], "domain": dom, "clean": r["company"]}
        time.sleep(0.1)
    try:
        json.dump(cache, open(THEME_CACHE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    except Exception:
        pass
    print("  theme discovery: fetched %d company sites (cache %d)" % (fetched, len(cache)))


def theme_momentum(counts):
    """Month-over-month change in the raise MIX by theme. Appends today's per-theme raise counts to
    a daily history file and compares against the closest row ~30 days back. Deltas accrue over time;
    the first few weeks read as a baseline. Free, pure-data."""
    today = TODAY.isoformat()
    rows = []
    try:
        for ln in open(THEME_HIST, encoding="utf-8"):
            if ln.strip():
                rows.append(json.loads(ln))
    except Exception:
        pass
    rows = [r for r in rows if r.get("date") != today]      # idempotent: overwrite today
    rows.append({"date": today, "counts": counts})
    rows.sort(key=lambda r: r.get("date", ""))
    try:
        open(THEME_HIST, "w", encoding="utf-8").write("\n".join(json.dumps(r) for r in rows) + "\n")
    except Exception:
        pass

    def days_ago(d):
        try:
            y, mo, dd = map(int, d[:10].split("-")); return (TODAY - datetime.date(y, mo, dd)).days
        except Exception:
            return 0
    cand = [r for r in rows if 21 <= days_ago(r["date"]) <= 45]
    base = cand[-1] if cand else next((r for r in rows if r["date"] < today), None)
    if not base:
        return {"since": "", "tw": []}
    bc = base.get("counts", {})
    tw = [{"name": t, "delta": c - bc.get(t, 0), "now": c} for t, c in counts.items()]
    tw.sort(key=lambda x: (-x["delta"], -x["now"]))
    return {"since": base["date"], "tw": tw}


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
            r = ledger[k] = {"company": company, "amount_m": amt, "date": date, "link": link,
                             "investors": set(investors), "theme": theme, "stage": stage,
                             "_dc": {}, "_dl": {}}
        else:
            r["investors"].update(investors)
            if amt and (not r["amount_m"] or amt > r["amount_m"]):
                r["amount_m"] = amt
            if stage and r["stage"] in ("", "Venture") and stage != "Venture":
                r["stage"] = stage
        # Accumulate every dated Investment mention. The announcement date is the MODAL
        # date (the day the raise was actually covered), not the latest — this ignores
        # stray late reposts (e.g. a fund re-sharing a months-old round) and early leaks.
        d = (date or "")[:10]
        if d:
            r["_dc"][d] = r["_dc"].get(d, 0) + 1
            r["_dl"].setdefault(d, link)

    def match_signal_fund(fund_name):
        fl = (fund_name or "").lower()
        for s in FUND_SIGNAL:
            if s.lower() in fl or (s == "Y Combinator" and ("combinator" in fl or fl.strip() == "yc")) or (s == "a16z" and "andreessen" in fl):
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
            if not co:
                _r = NAME_RES.get(reskey(title))
                if _r and _r.get("name"):
                    co = _r["name"]     # resolved from a headline fragment by the weekly Affinity pass
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
    _FUNDSTOP_H = {"menlo","accel","sequoia","redpoint","bessemer","lightspeed","kleiner","insight","khosla","coatue",
                   "felicis","greylock","benchmark","battery","index","pear","thrive","a16z","andreessen","foundersfund",
                   "generalcatalyst","iconiq","ivp","nea","gv","greycroft","emergence","craft","8vc","dst","tiger","bain"}
    for c in harm:
        name = c.get("name")
        if not name or SHELL.search(name):
            continue
        name = re.sub(r"^(?:fintech|healthtech|insurtech|proptech|legaltech|climatetech|edtech|adtech|trading app|pitch deck)\s*:?\s+", "", name, flags=re.I).strip(" :-")
        name = re.sub(r"\s+[|–—-]\s+.*$", "", name).strip()        # cut " - descriptive suffix"
        if not name or len(name) < 3 or norm(name) in _FUNDSTOP_H or "pitch deck" in name.lower():
            continue
        raw = (c.get("stage") or "").replace("SERIES_", "Series ").replace("_", " ").title().strip()
        st = raw or "Venture"
        amt = round((c.get("last_amount") or 0) / 1e6) or None
        # Harmonic gives no announcement date; leave it empty so a real fund-update date
        # is never overwritten. Undated (Harmonic-only) rows get a persistent first-seen
        # date below so they don't jump to "today" on every run.
        add(name, amt, "", ("https://" + c["domain"]) if c.get("domain") else "", set(),
            theme_of(name + " " + (c.get("desc") or "")), st)

    rows = []
    for r in ledger.values():
        r["investors"] = sorted(i for i in r["investors"] if i)[:6]
        rows.append(r)

    # ---- Modal announcement date (most-covered day; earliest wins ties) ----
    for r in rows:
        dc = r.pop("_dc", None); dl = r.pop("_dl", None)
        if dc:
            best = sorted(dc.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
            r["date"] = best
            if dl.get(best):
                r["link"] = dl[best]

    # ---- Stable announcement/first-seen date -------------------------------
    # Real fund-article dates are the true announcement dates and are kept as-is.
    # Companies with no real date (Harmonic-only) are stamped once with the date we
    # first saw them and never re-stamped, so "newest first" reflects genuinely new deals.
    try:
        first_seen = json.load(open(FIRST_SEEN, encoding="utf-8"))
    except Exception:
        first_seen = {}
    today_iso = TODAY.isoformat()
    for r in rows:
        k = norm(r.get("company"))
        d = (r.get("date") or "").strip()
        if d:
            # record the earliest real date we've ever seen for this company
            prev = first_seen.get(k)
            first_seen[k] = min(prev, d) if prev else d
            r["date"] = first_seen[k]
        else:
            if k not in first_seen:
                first_seen[k] = today_iso   # first time this Harmonic-only deal appears
            r["date"] = first_seen[k]
    try:
        json.dump(first_seen, open(FIRST_SEEN, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    except Exception as e:
        print("first_seen write skipped:", e)

    rows.sort(key=lambda x: (x.get("date") or "", x.get("amount_m") or 0), reverse=True)
    rows = rows[:200]
    enrich_themes(rows)   # free: resolve each unclassified company's site and theme from what it does
    llm_enrich(rows)      # optional LLM refinement (off unless OPENAI_API_KEY set)

    tally = {}
    for r in rows:
        tally.setdefault(r["theme"], []).append(r["company"])
    themes = [{"theme": t, "count": len(v), "examples": v[:6]} for t, v in tally.items()]
    themes.sort(key=lambda x: -x["count"])

    momentum = theme_momentum({t["theme"]: t["count"] for t in themes})
    total_cap = sum(r.get("amount_m") or 0 for r in rows)
    early = [r for r in rows if r.get("stage") in EARLY]
    order = ["Pre-seed", "Seed", "Series A", "Series B", "Series C", "Series D", "Growth/Late", "Venture"]
    stage_counts = {s: sum(1 for r in rows if r.get("stage") == s) for s in order}
    stage_counts = {k: v for k, v in stage_counts.items() if v}
    named = [t for t in themes if t["theme"] != "Applied / horizontal AI"]
    kpis = {"strongest_theme": (named[0]["theme"] if named else (themes[0]["theme"] if themes else "")),
            "total_raises": len(rows), "early_raises": len(early),
            "total_cap_m": total_cap, "early_cap_m": sum(r.get("amount_m") or 0 for r in early),
            "stage_counts": stage_counts}

    summary = ""   # concentration line removed per request

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
               "raises": rows, "themes": themes, "emerging": emerging, "investor_signal": investor_signal, "momentum": momentum},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote insights.json — %d raises, %d themes, %d funds in investor signal" % (len(rows), len(themes), len(investor_signal)))


if __name__ == "__main__":
    main()
