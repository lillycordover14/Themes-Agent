#!/usr/bin/env python3
"""Pull Harmonic saved-search companies using an API key from GitHub Secrets (HARMONIC_API_KEY).

Two-step: (1) fetch saved-search results (company IDs/URNs), (2) enrich those into full
company records. Fail-safe: never breaks the build. Verbose logging so the run log reveals the
exact response shape if anything needs adjusting.
Harmonic API: https://console.harmonic.ai/docs/api-reference/introduction  (auth header: apikey)
"""
import json, os, sys, datetime, urllib.request, urllib.error, urllib.parse

KEY = os.environ.get("HARMONIC_API_KEY", "").strip()
BASE = os.environ.get("HARMONIC_BASE", "https://api.harmonic.ai").rstrip("/")
SSID = os.environ.get("HARMONIC_SAVED_SEARCH_ID", "163876").strip()
RESULTS_URL = os.environ.get("HARMONIC_ENDPOINT", "").strip() or (BASE + "/saved_searches/%s/results?size=50" % SSID)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "harmonic_raises.json")

if not KEY:
    print("HARMONIC_API_KEY not set - skipping Harmonic pull.")
    sys.exit(0)

H = {"apikey": KEY, "accept": "application/json", "content-type": "application/json"}

def req(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, headers=H, method=method)
    with urllib.request.urlopen(r, timeout=60) as resp:
        return json.loads(resp.read())

# Step 1 - saved search results
try:
    res = req("GET", RESULTS_URL)
except Exception as e:
    print("saved-search fetch failed:", e)
    sys.exit(0)
print("results type:", (list(res.keys()) if isinstance(res, dict) else type(res).__name__))

def collect_ids(obj):
    lst = []
    if isinstance(obj, list):
        lst = obj
    elif isinstance(obj, dict):
        for k in ("results", "data", "companies", "entities", "items", "entityUrns", "urns"):
            if isinstance(obj.get(k), list):
                lst = obj[k]; break
    ids = []
    for it in lst:
        if isinstance(it, str):
            ids.append(it)
        elif isinstance(it, dict):
            v = it.get("entity_urn") or it.get("urn") or it.get("id") or it.get("company_urn")
            if v:
                ids.append(str(v))
    return ids

ids = collect_ids(res)
print("collected %d ids; sample %s" % (len(ids), ids[:2]))
if not ids:
    print("no ids parsed; raw head:", json.dumps(res)[:500])

def enrich(urns):
    for method, url, body in [
        ("POST", BASE + "/companies", {"urns": urns}),
        ("POST", BASE + "/companies:batchGet", {"urns": urns}),
        ("POST", BASE + "/companies/batch", {"urns": urns}),
    ]:
        try:
            d = req(method, url, body)
            print("enrich %s %s -> ok" % (method, url))
            return d
        except Exception as e:
            print("enrich %s %s -> %s" % (method, url, e))
    return None

companies = []
if ids:
    d = enrich(ids[:50])
    if d is None:
        d = []
        for u in ids[:25]:
            try:
                d.append(req("GET", BASE + "/companies/" + urllib.parse.quote(u, safe="")))
            except Exception:
                pass
    lst = d if isinstance(d, list) else (
        (d.get("results") or d.get("data") or d.get("companies") or []) if isinstance(d, dict) else [])
    for c in lst:
        if not isinstance(c, dict):
            continue
        name = c.get("name") or c.get("legal_name")
        if not name:
            continue
        web = c.get("website") or {}
        dom = web.get("domain") if isinstance(web, dict) else (web if isinstance(web, str) else "")
        f = c.get("funding") or {}
        companies.append({"name": name, "domain": dom or "", "desc": (c.get("description") or "")[:200],
                          "stage": f.get("funding_stage") or "",
                          "last_amount": f.get("last_funding_total") or 0, "total": f.get("funding_total") or 0})

json.dump({"generated": datetime.date.today().isoformat(), "count": len(companies), "companies": companies},
          open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("Wrote %d Harmonic companies to data/harmonic_raises.json" % len(companies))
if ids and not companies:
    print("Got ids but enrichment returned no company objects - paste this log and I will map the enrich endpoint.")
