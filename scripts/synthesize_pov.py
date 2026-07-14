#!/usr/bin/env python3
"""LLM 'where their head is' POV, synthesized from each firm's recent activity + podcasts.
Runs in the Action if OPENAI_API_KEY (or ANTHROPIC_API_KEY) is set. Cost-efficient:
- only calls the model for firms whose content changed (content hash),
- skips firms with too little signal,
- fail-safe (keeps existing POV on any error).
Writes fund['pov'] (+ pov_source='llm', pov_hash) back into data/funds.json.
"""
import json, os, sys, hashlib, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FP = os.path.join(ROOT, "data", "funds.json")
OPENAI = os.environ.get("OPENAI_API_KEY", "").strip()
ANTHRO = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MAX_PER_RUN = int(os.environ.get("POV_MAX_PER_RUN", "200"))

SYS = ("You are a venture analyst. In ONE tight sentence (max 30 words), say where this VC firm is "
       "currently focused / where their head is, based only on the recent items provided (their investments, "
       "essays, podcast topics). Name concrete sectors/themes. Do NOT list people or company names as themes. "
       "No preamble, no hedging.")


def llm(prompt):
    if OPENAI:
        body = json.dumps({"model": "gpt-4o-mini", "temperature": 0.3, "max_tokens": 80,
                           "messages": [{"role": "system", "content": SYS}, {"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body,
                                     headers={"Authorization": "Bearer " + OPENAI, "content-type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=40).read())
        return d["choices"][0]["message"]["content"].strip()
    if ANTHRO:
        body = json.dumps({"model": "claude-3-5-haiku-latest", "max_tokens": 80,
                           "system": SYS, "messages": [{"role": "user", "content": prompt}]}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body,
                                     headers={"x-api-key": ANTHRO, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        d = json.loads(urllib.request.urlopen(req, timeout=40).read())
        return d["content"][0]["text"].strip()
    return None


def main():
    if not (OPENAI or ANTHRO):
        print("No LLM key set — skipping POV synthesis (sector-based POV stays).")
        return
    data = json.load(open(FP, encoding="utf-8"))
    funds = data["funds"]
    done = 0
    for f in funds:
        ups = [u.get("title", "") for u in (f.get("updates") or [])][:8]
        pods = [(p.get("title") or p.get("show") or "") for p in (f.get("podcasts") or [])][:5]
        items = [x for x in ups + pods if x.strip()]
        if len(items) < 2:
            continue
        ctx = "Firm: %s\nFocus: %s\nRecent items:\n- %s" % (f.get("name"), f.get("focus", "")[:120], "\n- ".join(items))
        h = hashlib.sha256(ctx.encode("utf-8")).hexdigest()[:16]
        if f.get("pov_source") == "llm" and f.get("pov_hash") == h:
            continue  # unchanged since last synthesis -> no API call
        if done >= MAX_PER_RUN:
            break
        try:
            pov = llm(ctx)
            if pov:
                f["pov"] = pov.strip().strip('"'); f["pov_source"] = "llm"; f["pov_hash"] = h; done += 1
        except Exception as e:
            print("  synth failed for %s: %s" % (f.get("name"), e))
    json.dump(data, open(FP, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    for f in funds:
        json.dump(f, open(os.path.join(ROOT, "data", "funds", f["slug"] + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Synthesized POV for %d firms (changed/new only)." % done)


if __name__ == "__main__":
    main()
