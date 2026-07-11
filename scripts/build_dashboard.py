#!/usr/bin/env python3
"""Build index.html from data/tailwinds.json + data/funds.json using scripts/dashboard_template.html.
Pure, no network. Single source of truth for the template lives alongside this script."""
import json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(ROOT, "data", "tailwinds.json"), encoding="utf-8"))
FUNDS = json.load(open(os.path.join(ROOT, "data", "funds.json"), encoding="utf-8"))
BLOB = json.dumps({"D": D, "F": FUNDS}, ensure_ascii=False)
TEMPLATE = open(os.path.join(HERE, "dashboard_template.html"), encoding="utf-8").read()
html = TEMPLATE.replace("__BLOB__", BLOB)
open(os.path.join(ROOT, "index.html"), "w", encoding="utf-8").write(html)
print("built index.html (%d bytes) from %d funds" % (len(html), FUNDS.get("count", 0)))
