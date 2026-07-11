#!/usr/bin/env python3
"""Pull Harmonic saved-search companies (net-new first, deal-flow mode) using HARMONIC_API_KEY.

Tries the net-new endpoint (only companies that appeared since last check); if it returns
nothing, falls back to the full saved-search results so the dashboard is never empty.
Fail-safe: never breaks the build. Docs: https://console.harmonic.ai/docs/api-reference/
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

H = {"apikey": KEY, "accept": "application/json"}


def get(url):
    req = urllib.request.Request(url, headers=H, method="GET")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read())


def parse(res):
    results = res.get("results", res if isinstance(res, list) else [])
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
        out.append({"name": name, "domain": dom or "", "desc": (c.get("description") or "")[:220],
                    "stage": f.get("funding_stage") or "", "last_amount": f.get("last_funding_total") or 0,
                    "total": f.get("funding_total") or 0,
                    "investors": [i.get("name") for i in (f.get("investors") or []) if isinstance(i, dict) and i.get("name")][:4],
                    "location": (loc.get("location") if isinstance(loc, dict) else "") or ""})
    return out


companies, mode = [], "net-new"
try:
    url = "%s/savedSearches:netNewResults/%s?size=%s" % (BASE, SSID, SIZE)
    print("Harmonic GET", url)
    companies = parse(get(url))
    print("net-new companies:", len(companies))
except Exception as e:
    print("net-new failed:", e)

if not companies:
    mode = "full"
    try:
        url = "%s/savedSearches:results/%s?size=%s" % (BASE, SSID, SIZE)
        print("Fallback GET", url)
        companies = parse(get(url))
        print("full-results companies:", len(companies))
    except Exception as e:
        print("full results failed (leaving existing data untouched):", e)
        sys.exit(0)

json.dump({"generated": datetime.date.today().isoformat(), "mode": mode, "count": len(companies), "companies": companies},
          open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("Wrote %d Harmonic companies (mode=%s)" % (len(companies), mode))
