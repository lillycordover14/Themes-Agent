#!/usr/bin/env python3
"""Daily point-in-time signal logger for the Raising Soon engine — WEB-ONLY (no Harmonic).

WHY: We can't get point-in-time history out of any vendor, and we want to avoid burning metered
API calls. So every day we scrape FREE public sources for each tracked company and append one
JSONL row. Over weeks this becomes our own proprietary point-in-time series that future raises
label — the only honest way to calibrate the time-series-shape signals (see
docs/raising-soon-signal-engine.md).

Free signals captured per company (all keyed off the company's domain):
  - ATS open roles (Greenhouse / Lever / Ashby): total open reqs, and — critically — whether a
    FINANCE-leadership (CFO / VP Finance / Controller) or GTM-leadership (CRO / VP Sales) role is
    open. A finance-leadership opening is one of the strongest pre-raise tells.
  - SEC EDGAR Form D: most recent new-securities filing (a raise, authoritative + free).
  - GDELT press cadence: article counts over the last 30 / 90 days, plus raise-chatter and
    exec-hire headline detection.
  - (optional) GitHub stars, if a repo is listed in pipeline.json.

Runs in the daily Action inside the always-on scrape step (NO API key needed). Fail-safe: any
per-company or per-source error is logged and skipped; never fails the build. Idempotent:
re-running the same day overwrites that day's row.

pipeline.json entries may add optional hints to improve accuracy:
  {"name":..., "domain":"acme.com",
   "ats": "greenhouse:acmeco",          # optional: "<greenhouse|lever|ashby>:<token>"
   "careers_url": "https://acme.com/careers",  # optional
   "github": "acme/acme"}               # optional owner/repo
"""
import json, os, re, sys, datetime, urllib.parse, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = os.path.join(ROOT, "data", "pipeline.json")
HIST_DIR = os.path.join(ROOT, "data", "signal_history")
TODAY = datetime.date.today().isoformat()
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

FIN_LEAD = re.compile(r"(chief financial officer|\bcfo\b|\bvp\b[\s,]*(?:of\s+)?financ|vice president.*financ|head of finance|head of accounting|financial controller|\bcontroller\b|director of finance|head of fp&a)", re.I)
GTM_LEAD = re.compile(r"(chief revenue officer|\bcro\b|\bvp\b[\s,]*(?:of\s+)?sales|vice president.*sales|head of sales|\bvp\b[\s,]*(?:of\s+)?marketing|head of marketing|chief marketing|\bcmo\b|head of revenue|head of gtm)", re.I)
FIN_ANY = re.compile(r"(finance|accounting|controller|fp&a|treasury|revenue operations)", re.I)
SALES_ANY = re.compile(r"(sales|account executive|\bae\b|revenue|gtm|go.to.market|business development|customer success)", re.I)
ENG_ANY = re.compile(r"(engineer|engineering|developer|\bswe\b|machine learning|\bml\b|infrastructure|backend|frontend|founding engineer)", re.I)
RAISE = re.compile(r"\b(raises?|raising|in talks to raise|closes?\s+\$|series\s+[a-e]\b|\$\d+\s*(m|million|b|billion)|funding round|led by)\b", re.I)
HIRE = re.compile(r"\b(cfo|chief financial|vp finance|head of finance|cro|chief revenue|vp sales|appoints?|names?|hires?|joins? as)\b", re.I)


def fetch_text(url, timeout=15):
    for _ in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                continue
            return ""
        except Exception:
            return ""
    return ""


def fetch_json(url, timeout=15):
    txt = fetch_text(url, timeout)
    if not txt:
        return None
    try:
        return json.loads(txt)
    except Exception:
        return None


def domain_token(domain):
    d = (domain or "").split("//")[-1].split("/")[0]
    d = d[4:] if d.startswith("www.") else d
    return d.split(".")[0] if d else ""


def detect_ats(comp):
    """Return (source, token). Use explicit hint if given, else sniff the careers/home page."""
    hint = comp.get("ats") or ""
    if ":" in hint:
        src, tok = hint.split(":", 1)
        return src.strip().lower(), tok.strip()
    domain = comp.get("domain", "")
    pages = [comp.get("careers_url")] if comp.get("careers_url") else []
    if domain:
        base = domain if domain.startswith("http") else "https://" + domain
        pages += [base, base.rstrip("/") + "/careers", base.rstrip("/") + "/jobs", base.rstrip("/") + "/company/careers"]
    for url in [p for p in pages if p]:
        html = fetch_text(url)
        if not html:
            continue
        m = re.search(r"boards\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9]+)", html, re.I)
        if m:
            return "greenhouse", m.group(1)
        m = re.search(r"jobs\.lever\.co/([a-z0-9\-]+)", html, re.I)
        if m:
            return "lever", m.group(1)
        m = re.search(r"jobs\.ashbyhq\.com/([a-z0-9\-]+)", html, re.I)
        if m:
            return "ashby", m.group(1)
    return None, domain_token(domain)  # fall back to guessing token = domain root


def ats_jobs(source, token):
    """Return list of {title, dept, location} from the ATS public API. Empty on any failure."""
    if not token:
        return []
    out = []
    if source == "greenhouse" or source is None:
        d = fetch_json("https://boards-api.greenhouse.io/v1/boards/%s/jobs?content=false" % token)
        for j in ((d or {}).get("jobs", []) if isinstance(d, dict) else []):
            out.append({"title": j.get("title", ""), "dept": "", "location": (j.get("location") or {}).get("name", "")})
        if out:
            return out
    if source == "lever" or source is None:
        d = fetch_json("https://api.lever.co/v0/postings/%s?mode=json" % token)
        for j in (d if isinstance(d, list) else []):
            cats = j.get("categories") or {}
            out.append({"title": j.get("text", ""), "dept": cats.get("team", ""), "location": cats.get("location", "")})
        if out:
            return out
    if source == "ashby" or source is None:
        d = fetch_json("https://api.ashbyhq.com/posting-api/job-board/%s?includeCompensation=false" % token)
        for j in ((d or {}).get("jobs", []) if isinstance(d, dict) else []):
            out.append({"title": j.get("title", ""), "dept": j.get("department", "") or j.get("team", ""), "location": j.get("location", "")})
    return out


def classify_roles(jobs):
    blobs = [((j.get("title", "") or "") + " " + (j.get("dept", "") or "")) for j in jobs]
    return {
        "open_roles_total": len(jobs),
        "roles_finance": sum(1 for b in blobs if FIN_ANY.search(b)),
        "roles_sales": sum(1 for b in blobs if SALES_ANY.search(b)),
        "roles_eng": sum(1 for b in blobs if ENG_ANY.search(b)),
        "finance_leadership_open": any(FIN_LEAD.search(b) for b in blobs),
        "gtm_leadership_open": any(GTM_LEAD.search(b) for b in blobs),
    }


def gdelt(name):
    """Return (press_30d, press_90d, raise_headline, hire_headline) from GDELT (free, CI-friendly)."""
    q = '"%s"' % name
    url = ("https://api.gdeltproject.org/api/v2/doc/doc?query=%s&mode=artlist&format=json"
           "&maxrecords=75&sort=datedesc&timespan=3months" % urllib.parse.quote(q))
    d = fetch_json(url, timeout=20) or {}
    arts = d.get("articles") or []
    c30 = c90 = 0
    raise_hl = hire_hl = ""
    today = datetime.date.today()
    for a in arts:
        sd = (a.get("seendate") or "")[:8]
        try:
            dt = datetime.date(int(sd[0:4]), int(sd[4:6]), int(sd[6:8]))
        except Exception:
            dt = None
        title = (a.get("title") or "").strip()
        if dt:
            days = (today - dt).days
            if days <= 90:
                c90 += 1
            if days <= 30:
                c30 += 1
        if not raise_hl and RAISE.search(title):
            raise_hl = title[:150]
        if not hire_hl and HIRE.search(title):
            hire_hl = title[:150]
    return c30, c90, raise_hl, hire_hl


def edgar_form_d(name):
    """Most recent SEC Form D filing date for the name, or '' (free, needs a UA)."""
    url = "https://efts.sec.gov/LATEST/search-index?q=%s&forms=D" % urllib.parse.quote('"%s"' % name)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "ThemesAgent research@smithpointcapital.com"})
        d = json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception:
        return ""
    tok = (name.lower().split() or [""])[0]
    best = ""
    for h in (d.get("hits", {}) or {}).get("hits", [])[:8]:
        src = h.get("_source", {}) or {}
        disp = ", ".join(src.get("display_names", []) or []).lower()
        filed = src.get("file_date", "") or ""
        if tok and tok in disp and filed > best:
            best = filed
    return best


def github_stars(repo):
    if not repo:
        return None
    d = fetch_json("https://api.github.com/repos/%s" % repo)
    return d.get("stargazers_count") if isinstance(d, dict) else None



def site_customers(comp):
    """Best-effort: pull customer names from 'X logo' alt-text on the homepage / customers page,
    so pipeline_activity can diff day-over-day for NEW customers."""
    domain = comp.get("domain", "")
    if not domain:
        return []
    base = domain if domain.startswith("http") else "https://" + domain
    names = set()
    for url in (base, base.rstrip("/") + "/customers", base.rstrip("/") + "/company/customers"):
        html = fetch_text(url)
        if not html:
            continue
        for alt in re.findall(r'alt=["\']([^"\']{2,50})["\']', html):
            m = re.match(r"^(.*?)\s+logo$", alt.strip(), re.I)
            if m:
                nm = m.group(1).strip()
                if 2 <= len(nm) <= 40 and re.match(r"^[A-Za-z0-9]", nm):
                    names.add(nm)
    return sorted(names)[:40]


def snapshot(comp):
    name = comp.get("name")
    slug = re.sub(r"[^a-z0-9]+", "-", (comp.get("slug") or name or "").lower()).strip("-")
    print("•", name)
    source, token = detect_ats(comp)
    jobs = ats_jobs(source, token)
    roles = classify_roles(jobs)
    c30, c90, raise_hl, hire_hl = gdelt(name)
    row = {
        "date": TODAY, "name": name, "slug": slug,
        "ats_source": (source or ("guess:" + token if token else "")),
        **roles,
        "press_30d": c30, "press_90d": c90,
        "raise_chatter": raise_hl, "exec_hire_news": hire_hl,
        "form_d_latest": edgar_form_d(name),
        "github_stars": github_stars(comp.get("github")),
        "site_customers": site_customers(comp),
    }
    print("  roles=%d (fin_lead=%s gtm_lead=%s) press30=%d formD=%s" % (
        roles["open_roles_total"], roles["finance_leadership_open"], roles["gtm_leadership_open"], c30, row["form_d_latest"] or "-"))
    return row


def _row_date(ln):
    try:
        return json.loads(ln).get("date")
    except Exception:
        return None


def write_row(slug, row):
    os.makedirs(HIST_DIR, exist_ok=True)
    path = os.path.join(HIST_DIR, slug + ".jsonl")
    lines = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
    kept = [ln for ln in lines if _row_date(ln) != row.get("date")]
    kept.append(json.dumps(row, ensure_ascii=False))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(kept) + "\n")


def main():
    try:
        pipe = json.load(open(PIPE, encoding="utf-8"))
    except Exception as e:
        print("could not read pipeline.json:", e); return
    companies = pipe if isinstance(pipe, list) else pipe.get("companies", [])
    n = 0
    for comp in (companies or []):
        try:
            row = snapshot(comp)
            if row:
                write_row(row["slug"], row); n += 1
        except Exception as e:
            print("  snapshot failed for %s: %s" % (comp.get("name"), e))
    print("Snapshotted %d companies (web-only) to data/signal_history/ for %s" % (n, TODAY))


if __name__ == "__main__":
    main()
