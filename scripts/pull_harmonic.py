#!/usr/bin/env python3
"""Pull fresh Harmonic data using an API key from GitHub Secrets (HARMONIC_API_KEY).

Runs inside the GitHub Action. Fully optional and fail-safe: if the key is missing or the
endpoint errors, it logs and exits 0 without touching existing data. Writes
data/harmonic_raises.json (light company records) which the dashboard build can fold in.

Harmonic API: https://console.harmonic.ai/docs/api-reference/introduction
Auth: header `apikey: <key>`. You can override the endpoint without editing code by setting
the HARMONIC_ENDPOINT secret/variable to the exact URL from your API docs (e.g. a saved-search
results URL). Default targets the keyword company search.
"""
import json, os, sys, urllib.request, urllib.parse, datetime

KEY = os.environ.get("HARMONIC_API_KEY", "").strip()
BASE = os.environ.get("HARMONIC_BASE", "https://api.harmonic.ai").rstrip("/")
# Full override URL (preferred). If empty, we build a keyword-search URL from HARMONIC_QUERY.
ENDPOINT = os.environ.get("HARMONIC_ENDPOINT", "").strip()
QUERY = os.environ.get("HARMONIC_QUERY", "enterprise software OR AI infrastructure seed OR Series A")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "harmonic_raises.json")

if not KEY:
    print("HARMONIC_API_KEY not set — skipping Harmonic pull (web pipeline still runs).")
    sys.exit(0)

url = ENDPOINT or (BASE + "/search/companies?" + urllib.parse.urlencode({"query": QUERY, "size": 50}))
print("Harmonic GET", url)
try:
    req = urllib.request.Request(url, headers={"apikey": KEY, "accept": "application/json"})
    raw = urllib.request.urlopen(req, timeout=40).read()
    data = json.loads(raw)
except Exception as e:
    print("Harmonic pull failed (leaving existing data untouched):", e)
    print("Tip: set the HARMONIC_ENDPOINT secret to the exact URL from your API docs, then re-run.")
    sys.exit(0)

# Generic, defensive parse: find a list of company-like dicts anywhere in the response.
def find_list(obj):
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        for k in ("results", "data", "companies", "entities", "items"):
            if isinstance(obj.get(k), list):
                return obj[k]
        for v in obj.values():
            r = find_list(v)
            if r:
                return r
    return []

rows = find_list(data)
out = []
for c in rows[:100]:
    if not isinstance(c, dict):
        continue
    name = c.get("name") or c.get("company_name") or (c.get("legal_name"))
    if not name:
        continue
    web = c.get("website") or {}
    dom = web.get("domain") if isinstance(web, dict) else (web if isinstance(web, str) else "")
    fund = c.get("funding") or {}
    out.append({
        "name": name,
        "domain": dom or "",
        "desc": (c.get("description") or "")[:200],
        "stage": (fund.get("funding_stage") or c.get("stage") or ""),
        "last_amount": fund.get("last_funding_total") or fund.get("last_round_size") or 0,
        "total": fund.get("funding_total") or 0,
    })

json.dump({"generated": datetime.date.today().isoformat(), "count": len(out), "companies": out},
          open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("Wrote %d Harmonic companies to data/harmonic_raises.json" % len(out))
