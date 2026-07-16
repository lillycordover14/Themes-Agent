#!/usr/bin/env python3
"""Email Engine — free/templated founder intro drafts in SPC's voice (Day 4).

For each Pipeline + Sourcing company, draft a 4-section cold-outreach email following the
spc-cold-outreach skill (Intro → 'more than capital' → Why this company → CTA). Pure Python, no
tokens: opens on a real activity hook (recent raise / material update), greets the founder by name
when a surfaced connection tells us who the CEO/founder is, picks the 'more than capital' angles by
sector, and names any warm connection. Never invents customer logos — uses only known facts
(description, stage/amount, investors, connections). Writes data/email_drafts.json. Fail-safe.
"""
import json, os, re, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "email_drafts.json")
try:
    FOUNDERS = json.load(open(os.path.join(ROOT, "data", "founder_names.json"), encoding="utf-8"))
except Exception:
    FOUNDERS = {}
TODAY = datetime.date.today()

INTRO = ("I'm Lilly, an investor at Smith Point Capital — an enterprise software fund co-founded by "
         "Keith Block, former co-CEO of Salesforce, alongside Burke Norton (formerly Salesforce, Vista) "
         "and Chris Lytle (formerly Morgan Stanley).")
APPROACH = ("We partner with founders who want more than capital — an operator-led approach backed by a "
            "team with deep experience scaling mission-critical platforms across Salesforce, ServiceNow, "
            "Cisco, Databricks, and Oracle.")
INTRO_SHORT = ("Quick reminder on us: Smith Point is an enterprise-software fund founded by Keith Block "
               "(former co-CEO of Salesforce), with Burke Norton (Salesforce, Vista) and Chris Lytle. We back "
               "mission-critical software and get hands-on with GTM, enterprise pricing, and C-suite introductions.")
CTA = ("Would you be open to a brief intro call? Would love to hear more about {co} and share more about "
       "Smith Point. Please lmk what works in the coming weeks!")

ANGLE = {
    "ai": ("we have C-suite-level connections to enterprises like Anthropic, OpenAI, and Databricks, and can "
           "help accelerate enterprise sales motions in ways that are hard to replicate. We also work closely "
           "with founders on GTM strategy, enterprise pricing, and building out leadership teams at key inflection points."),
    "fin": ("we believe the fastest path to scale here runs through the major financial institutions — custodians, "
            "wirehouses, banks, and insurers — where Keith Block and the team hold active C-suite relationships. We can "
            "help accelerate those enterprise sales motions and work with founders on GTM strategy, enterprise pricing, and leadership buildout."),
    "health": ("we can open doors with the health systems and enterprise buyers you're selling into, help accelerate "
               "those sales motions, and work closely with founders on GTM strategy, enterprise pricing, and building out leadership teams."),
    "default": ("we can help accelerate your enterprise sales motion through active C-suite relationships across "
                "Salesforce, ServiceNow, Cisco, Databricks, and Oracle, and work closely with founders on GTM strategy, "
                "enterprise pricing, and leadership buildout."),
}


def _clean_title(t):
    """Sanitize a scraped headline/conference title for use in an email hook; '' if it's junk (CSS/HTML/JS)."""
    t = (t or "")
    t = re.sub(r"<[^>]+>", " ", t)
    if re.search(r"[{}]|:before|:after|counter\(|content\s*:|@media|function\s*\(|;\s*}|=>|var\s|px\b", t, re.I):
        return ""
    t = re.sub(r"\s+", " ", t).strip(" -–—:·|\"'")
    return t if 4 <= len(t) <= 120 else ""


def angle_for(text):
    t = (text or "").lower()
    if any(k in t for k in ("fintech", "financial", "insurance", "insurtech", "wealth", "bank", "payment", "trust", "accounting")):
        return ANGLE["fin"]
    if any(k in t for k in ("health", "clinical", "patient", "pharma", "care", "medical", "bio")):
        return ANGLE["health"]
    if any(k in t for k in ("ai", "agent", "data", "llm", "model", "ml", "infra", "developer")):
        return ANGLE["ai"]
    return ANGLE["default"]


def founder_of(company):
    """(name, title, email) for the company's founder/CEO from the pre-fetched cache. ('','','') if unknown."""
    f = FOUNDERS.get(re.sub(r"[^a-z0-9]+", "", (company or "").lower()))
    if isinstance(f, dict) and f.get("name"):
        return f.get("name", ""), f.get("title", ""), f.get("email", "")
    return "", "", ""


def first_name_from_connections(conns):
    """If a surfaced connection is the company's CEO/founder, greet them by first name."""
    for c in (conns or []):
        title = (c.get("title") or "").lower()
        person = c.get("person") or ""
        if person and ("ceo" in title or "founder" in title):
            return person.split()[0]
    return ""


def money(amt):
    if not amt:
        return ""
    return ("$%.1fB" % (amt / 1000)) if amt >= 1000 else ("$%dM" % amt)


def warm_line(conns, greet_first):
    real = [c for c in (conns or []) if c.get("person")]
    if not real:
        return ""
    # prefer a teammate other than the sender (Lilly); a Lilly->this-founder tie needs no intro line
    pref = [c for c in real if "lilly" not in (c.get("via") or "").lower()] or real
    c = pref[0]
    who = c.get("via") or "someone on our team"
    person = c.get("person"); title = c.get("title") or ""
    if "lilly" in who.lower() and person.split()[0].lower() == (greet_first or "").lower():
        return ""   # sender already knows the person they're emailing
    tl = (" (" + title + ")") if title else ""
    return "We may also have a warm intro — %s is already connected to %s%s." % (who, person, tl)


def draft(company, desc, stage, amount_m, investors, conns, hook, mode='sourcing'):
    fname, ftitle, femail = founder_of(company)
    greet = (fname.split()[0] if fname else "") or first_name_from_connections(conns) or "there"
    subject = "Smith Point Capital — %s" % company
    if mode == "pipeline":
        # warm follow-up: assume prior touches; lead on genuine attention + a fresh hook, abridged SPC, soft ask
        _d = (desc or "").strip().rstrip(".")
        if _d[:1].isupper() and _d[1:2].islower():
            _d = _d[0].lower() + _d[1:]
        why = ("What keeps standing out: you're building %s — exactly the kind of deeply embedded, mission-critical software we love to back." % _d) if _d else "I've been really impressed by the trajectory."
        first = ("I've been keeping a close eye on %s — %s." % (company, hook.rstrip("."))) if hook else ("I've been keeping a close eye on %s." % company)
        lines = ["Hi %s," % greet, "", first + " " + why, "", INTRO_SHORT, "",
                 'On the "more than capital" front, %s' % angle_for(company + " " + (desc or "")),
                 "", "Would love to grab ~20 minutes to compare notes — no agenda, just have a hunch there could be a fit. Lmk if useful.",
                 "", "Best,", "Lilly"]
        founder = (fname + ((" — " + ftitle) if ftitle else "")) if fname else ""
        return "Smith Point Capital — %s" % company, "\n".join(lines), founder, femail
    # sourcing (and default): full 4-section intro
    lines = ["Hi %s," % greet, "", INTRO, ""]
    lead = (hook + " " if hook else "") + ("We like getting to know founders early and building relationships "
            "well before a round comes together — no agenda, and totally understand if you're heads-down right now. ") + APPROACH
    lines += [lead, ""]
    lines += ['On the "more than capital" front: %s' % angle_for(company + " " + (desc or "")), ""]
    # Why this company
    d = (desc or "").strip().rstrip(".") or "what you're building"
    if d[:1].isupper() and d[1:2].islower():
        d = d[0].lower() + d[1:]   # lowercase a normal capitalized word, but leave acronyms like 'AI-powered'
    bullets = ["- You're building %s — exactly the kind of deeply embedded, mission-critical software we like to back." % d]
    inv = [i for i in (investors or []) if i][:3]
    if stage or amount_m or inv:
        bits = []
        if stage and stage != "Venture":
            bits.append("your recent %s" % stage + ((" (" + money(amount_m) + ")") if amount_m else ""))
        elif amount_m:
            bits.append("your recent %s round" % money(amount_m))
        tail = (" with backing from " + ", ".join(inv)) if inv else ""
        if bits:
            bullets.append("- Momentum is real — %s%s signals genuine enterprise pull." % (bits[0], tail))
        elif inv:
            bullets.append("- Backing from %s signals genuine enterprise pull." % ", ".join(inv))
    lines += ["We've been spending time in this space, and %s stands out:" % company]
    lines += bullets
    w = warm_line(conns, greet)
    if w:
        lines += ["", w]
    lines += ["", CTA.format(co=company), "", "Best,", "Lilly"]
    founder = (fname + ((" — " + ftitle) if ftitle else "")) if fname else ""
    return subject, "\n".join(lines), founder, femail


def main():
    def load(name):
        try:
            return json.load(open(os.path.join(ROOT, "data", name), encoding="utf-8"))
        except Exception:
            return {}

    pipe = load("pipeline_scored.json"); pact = load("pipeline_activity.json")
    _psrc = load("pipeline.json"); _pl = _psrc.get("companies", _psrc) if isinstance(_psrc, dict) else _psrc
    descmap = {c.get("name", ""): (c.get("desc") or "") for c in (_pl or [])}
    src = load("sourcing_enriched.json") or load("sourcing_candidates.json")

    act_by = {}
    for a in (pact.get("companies") or []):
        act_by[re.sub(r"[^a-z0-9]+", "", (a.get("name") or "").lower())] = a

    drafts = []
    seen = set()

    def add(company, desc, stage, amount_m, investors, conns, hook, domain, source):
        k = re.sub(r"[^a-z0-9]+", "", (company or "").lower())
        if not k or k in seen:
            return
        seen.add(k)
        subj, body, founder, to = draft(company, desc, stage, amount_m, investors, conns, hook, mode=source)
        drafts.append({"company": company, "domain": domain, "subject": subj, "body": body,
                       "source": source, "based_on": hook or "profile", "founder": founder, "to": to})

    # Pipeline companies (hook off latest material activity)
    for c in (pipe.get("companies") or []):
        nm = c.get("name", "")
        a = act_by.get(re.sub(r"[^a-z0-9]+", "", nm.lower()), {})
        hook = ""
        ups = a.get("updates") or []
        if ups:
            u0 = ups[0]; cat = (u0.get("category") or "").lower(); t = _clean_title(u0.get("title"))
            if "fund" in cat:
                hook = "congrats on the raise"
            elif "product" in cat:
                hook = ("the new product news caught my eye (“%s”)" % t) if t else "the recent product news caught my eye"
            elif "customer" in cat:
                hook = ("saw the new-customer news (“%s”)" % t) if t else "saw the new-customer news"
            elif "partner" in cat:
                hook = ("saw the partnership announcement (“%s”)" % t) if t else "saw the recent partnership news"
            elif "hire" in cat or "exec" in cat:
                hook = ("saw the leadership news (“%s”)" % t) if t else "saw the recent leadership news"
            elif "award" in cat or "traction" in cat:
                hook = ("saw the recent milestone (“%s”)" % t) if t else "saw the recent milestone"
            else:
                hook = ("just caught your recent update (“%s”)" % t) if t else "just caught your recent update"
        add(nm, descmap.get(nm, ""), c.get("stage", ""), None, [], [], hook,
            c.get("domain", ""), "pipeline")

    # Sourcing companies (hook off the recent raise)
    for r in (src.get("actionable") or []) + (src.get("watchlist") or []):
        stage = r.get("stage", ""); amt = r.get("amount_m")
        hook = ""
        if stage and stage != "Venture":
            hook = "Congrats on the recent %s%s." % (stage, (" (" + money(amt) + ")") if amt else "")
        elif amt:
            hook = "Congrats on the recent %s raise." % money(amt)
        add(r.get("company", ""), r.get("desc", ""), stage, amt, r.get("investors", []),
            r.get("connections", []), hook, r.get("domain", ""), "sourcing")

    json.dump({"generated": TODAY.isoformat(), "count": len(drafts), "drafts": drafts},
              open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("Wrote email_drafts.json — %d drafts" % len(drafts))


if __name__ == "__main__":
    main()
