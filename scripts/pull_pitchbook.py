#!/usr/bin/env python3
"""Optional PitchBook pull via API key from GitHub Secrets (PITCHBOOK_API_KEY).

NOTE: PitchBook's key-based Data API is an enterprise add-on and is NOT the same as the
PitchBook MCP used inside Cowork. If you don't have Data API credentials, leave the secret
unset — this script no-ops. Set PITCHBOOK_ENDPOINT to the exact URL from your PitchBook API
docs. Fail-safe: never breaks the build.
"""
import json, os, sys, urllib.request, datetime

KEY = os.environ.get("PITCHBOOK_API_KEY", "").strip()
ENDPOINT = os.environ.get("PITCHBOOK_ENDPOINT", "").strip()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "pitchbook.json")

if not KEY or not ENDPOINT:
    print("PITCHBOOK_API_KEY/ENDPOINT not both set — skipping PitchBook pull (expected unless you have Data API access).")
    sys.exit(0)

try:
    req = urllib.request.Request(ENDPOINT, headers={"Authorization": "Bearer " + KEY, "accept": "application/json"})
    data = json.loads(urllib.request.urlopen(req, timeout=40).read())
    json.dump({"generated": datetime.date.today().isoformat(), "raw": data},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote data/pitchbook.json")
except Exception as e:
    print("PitchBook pull failed (leaving existing data untouched):", e)
    sys.exit(0)
