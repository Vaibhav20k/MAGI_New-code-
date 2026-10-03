"""The brand rules every piece of writing must pass (from inputs/brand-guide.md).

clean()      fixes what can be fixed without thought: no em or en dashes.
violations() names what must not be published: health claims, "kills", steel or wood kitchens,
             the IPO, the wrong family names. The agents rewrite or drop anything it flags.
"""

import re

BANNED = [
    (r"\b(?:stainless[\s-]*steel|steel|metal)\s+(?:kitchens?|cabinets?|carcass(?:es)?|wardrobes?|drawers?)\b",
     "MAGPPIE kitchens are stone, never steel"),
    (r"\b(?:316L|304)\b|\bsurgical[\s-]*grade\b", "steel grades do not belong to MAGPPIE"),
    (r"\bcures?\b|\bcured\b|\bprevents?\s+(?:disease|illness|cancer)\b|\bcancer[\s-]*safe\b|\bboosts?\s+immunity\b",
     "health outcome claim"),
    (r"\bkill(?:s|ed|ing)?\b", "MAGPPIE never kills (ahimsa): say pests find nothing to eat"),
    (r"\b99(?:\.9+)?\s*%", "germ percentage claim needs a lab report"),
    (r"\banti[\s-]?(?:bacterial|microbial|viral)\b", "antimicrobial claim needs a lab report"),
    (r"(?-i:\bSME\b)", "the word SME is never used"),
    (r"(?-i:\bIPO\b)|\bvaluation\b|\border book\b", "IPO and money matters are not for public content"),
    (r"\bShweta\b|\bIshaan\b", "wrong family name (the names are Subah and Ishat)"),
]
_BANNED = [(re.compile(p, re.I), why) for p, why in BANNED]


def clean(text: str) -> str:
    """No em or en dashes: commas, colons or 'to' instead."""
    if not isinstance(text, str):
        return text
    t = text.replace("‑", "-")                              # non-breaking hyphen
    t = re.sub(r"(?<=\d)\s*[–—]\s*(?=\d)", " to ", t)   # 4–5 → 4 to 5
    t = re.sub(r"\s*[–—]\s*", ", ", t)
    t = re.sub(r",\s*,", ",", t)
    return re.sub(r",\s*([.!?:;])", r"\1", t)


def scrub(obj):
    """clean() applied to every string inside lists and dictionaries."""
    if isinstance(obj, str):
        return clean(obj)
    if isinstance(obj, list):
        return [scrub(x) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    return obj


def _strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, list):
        for x in obj:
            yield from _strings(x)
    elif isinstance(obj, dict):
        for x in obj.values():
            yield from _strings(x)


def violations(obj) -> list[str]:
    """Why this text may not be published; empty when it is fine."""
    text = "\n".join(_strings(obj))
    found = []
    for rx, why in _BANNED:
        m = rx.search(text)
        if m:
            found.append(f'"{m.group(0)}": {why}')
    return found


RULES = """BRAND RULES (never broken):
- No em dashes or en dashes anywhere. Use commas, periods, colons or parentheses.
- MAGPPIE kitchens and wardrobes are built entirely from SILVERSTONE engineered stone infused with silver and
  copper. Zero wood. Never describe them as steel, stainless steel, wood, MDF, plywood or laminate.
- Describe only what the material physically does and does not contain: does not burn, does not swell, does not
  stain, zero formaldehyde by composition. No health outcome claims: never "cures", "prevents disease",
  "cancer-safe", "boosts immunity", "antibacterial", "kills 99.9%".
- Ahimsa: MAGPPIE never kills. Termites and cockroaches find nothing to eat.
- Compare against materials (MDF, particle board, plywood), never against a named brand.
- Never mention the IPO, valuation, revenue, funding or store targets. Never use the word "SME".
- Lead with safety for the family. Short declarative sentences. Vision first, then proof.
- If a number is an estimate, say so."""
