#!/usr/bin/env python3
"""Pull Harmonic saved-search companies via API key from GitHub Secrets (HARMONIC_API_KEY).

Uses the documented endpoint GET /savedSearches:results/{id}, which returns full company
objects. Fail-safe: never breaks the build. Verbose logging.
Docs: https://console.harmonic.ai/docs/api-reference/introduction  (auth header: apikey)
"""
import json, os, sys, datetime, urllib.request, urllib.error

KEY = os.environ.get("HARMONIC_API_KEY", "").strip()
BASE = os.environ.get("HARMONIC_BASE", "https://api.harmonic.ai").rstrip("/")
SSID = os.environ.get("HARMONIC_SAVED_SEARCH_ID", "163876").strip()
SIZE = os.environ.get("HARMONIC_SIZE", "50").strip()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "harmonic_raises.json")

if not KEY:
    print("HARMONIC_API_KEY not set - skipping Harmonic pull.")
    sys.exit(0)

URL = "%s/savedSearches:results/%s?size=%s" % (BASE, SSID, SIZE)
H = {"apikey": KEY, "accept": "application/json"}
print("Harmonic GET", URL)
try:
    req = urllib.request.Request(URL, headers=H, method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        res = json.loads(resp.read())
except Exception as e:
    print("Harmonic fetch failed (leaving existing data untouched):", e)
    sys.exit(0)

results = res.get("results", res if isinstance(res, list) else [])
print("results count:", len(results) if isinstance(results, list) else "n/a")

out = []
for c in (results or []):
    if not isinstance(c, dict) or not c:
        continue
    name = c.get("name") or c.get("legal_name")
    if not name:
        continue
    web = c.get("website") or {}
    dom = web.get("domain") if isinstance(web, dict) else (web if isinstance(web, str) else "")
    f = c.get("funding") or {}
    loc = c.get("location") or {}
    out.append({
        "name": name,
        "domain": dom or "",
        "desc": (c.get("description") or "")[:220],
        "stage": f.get("funding_stage") or "",
        "last_amount": f.get("last_funding_total") or 0,
        "total": f.get("funding_total") or 0,
        "investors": [i.get("name") for i in (f.get("investors") or []) if isinstance(i, dict) and i.get("name")][:4],
        "location": (loc.get("location") if isinstance(loc, dict) else "") or "",
    })

json.dump({"generated": datetime.date.today().isoformat(), "count": len(out), "companies": out},
          open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("Wrote %d Harmonic companies to data/harmonic_raises.json" % len(out))
if results and not out:
    print("Endpoint returned results but objects were empty - paste this log and I'll add field params.")
