"""
Corpus gate — enforces that everything asserted about Magppie traces to an
uploaded document.

The policy, stated once:

  * A claim ABOUT MAGPPIE (material, specification, certification, dimension,
    figure, capability) may only come from the brand corpus. It carries
    evidence_origin='magppie-corpus' and a source_doc_id.
  * General history and science recalled from model weights are permitted as
    context. They carry evidence_origin='general-knowledge', are forced to
    verification_status='UNVERIFIED', and can never become a product claim or
    back a 'verified-stat' hook.

This module is the verifier. Like `diversity_gate`, it is pure Python with no
model call, because a rule the code can check must not be left to the model.

It exists because of a measured failure: a hook claimed a "50+ years" lifespan
for the product while the
dossier's verified evidence said only "does not swell, warp or degrade at 90%+
RH" and "MDF fails within 7-12 years". No 50-year figure existed anywhere. The
writer extrapolated a number and the editor did not catch it.
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from workflows.brand_corpus import ORIGIN_GENERAL, ORIGIN_MAGPPIE

# Severity used when a finding reaches the Approval Brief.
CRITICAL = "CRITICAL"
IMPORTANT = "IMPORTANT"

# Words that mark a sentence as being about the brand rather than the world.
_BRAND_MARKERS = re.compile(r"\bmagppie\b|\bour\b|\bwe\b|\bus\b", re.IGNORECASE)

# A bare number with a unit, or a standards reference. These are the assertions
# that must be traceable — prose can be reworded, a figure cannot be argued with.
_MEASUREMENT = re.compile(
    r"""(?:
        # A quantity, optionally a range (7-12) or open-ended (50+), with a unit.
        \b\d[\d,.]*(?:\s*[-–]\s*\d[\d,.]*)?\+?\s*
            (?:%|percent|years?|yrs?|decades?|db|decibels?|mm|cm|metres?|meters?|
               kg|kilograms?|litres?|liters?|°c|degrees?|hours?|microns?|µm)\+?
      # A standards reference.
      | \b(?:ISO|ASTM|EN|BS|IS|LEED|IGBC|NSF|FDA|GREENGUARD)[\s\-]?\d[\w\-:.]*
      # A metal alloy grade (three digits and an L). Never a MAGPPIE material, so it never traces.
      | \b\d{3}L\b
    )""",
    re.IGNORECASE | re.VERBOSE,
)


def _text_of(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_text_of(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_text_of(v) for v in value)
    return ""


def mentions_brand(text: str) -> bool:
    return bool(_BRAND_MARKERS.search(text or ""))


def measurements_in(text: str) -> List[str]:
    """Figures and standards references found in a piece of text."""
    return [m.group(0).strip() for m in _MEASUREMENT.finditer(text or "")]


# ------------------------------------------------------------------ dossier

def check_dossier(
    dossier: Dict[str, Any],
    corpus_populated: bool,
    known_doc_ids: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Validate Agent 1's evidence origins.

    Returns a list of findings; an empty list means the dossier is clean.
    """
    findings: List[Dict[str, Any]] = []
    known = set(known_doc_ids or [])

    for group in ("historical_evidence", "scientific_evidence"):
        for item in dossier.get(group) or []:
            if not isinstance(item, dict):
                continue
            claim_id = item.get("claim_id", "?")
            origin = item.get("evidence_origin")
            status = item.get("verification_status")
            claim = item.get("claim", "")

            if origin not in (ORIGIN_MAGPPIE, ORIGIN_GENERAL):
                findings.append(_finding(
                    IMPORTANT, "Evidence Origin",
                    f"{claim_id} does not declare evidence_origin. Every claim must "
                    f"state whether it came from the Magppie corpus or general knowledge.",
                ))
                continue

            if origin == ORIGIN_GENERAL:
                # General knowledge may never be presented as settled fact.
                if status in ("VERIFIED", "QUALIFIED"):
                    findings.append(_finding(
                        CRITICAL, "Evidence Origin",
                        f"{claim_id} is marked '{ORIGIN_GENERAL}' but claims status "
                        f"'{status}'. Model-recalled evidence must be UNVERIFIED.",
                    ))
                if mentions_brand(claim):
                    findings.append(_finding(
                        CRITICAL, "Product Truth",
                        f"{claim_id} makes a claim about Magppie from general knowledge: "
                        f"\"{_clip(claim)}\". Anything about Magppie must come from an "
                        f"uploaded document.",
                    ))
                continue

            # origin == magppie-corpus
            if not corpus_populated:
                findings.append(_finding(
                    CRITICAL, "Product Truth",
                    f"{claim_id} cites the Magppie corpus, but no approved documents "
                    f"have been uploaded. It cannot be sourced.",
                ))
                continue
            doc_id = item.get("source_doc_id")
            if not doc_id:
                findings.append(_finding(
                    CRITICAL, "Product Truth",
                    f"{claim_id} claims corpus origin but names no source_doc_id.",
                ))
            elif known and doc_id not in known:
                findings.append(_finding(
                    CRITICAL, "Product Truth",
                    f"{claim_id} cites '{doc_id}', which is not an approved corpus "
                    f"document.",
                ))

    return findings


# ------------------------------------------------------------------- script

def check_script(
    script: Dict[str, Any],
    dossier: Dict[str, Any],
    corpus_populated: bool,
) -> List[Dict[str, Any]]:
    """
    Validate that the script asserts nothing the dossier cannot support.

    Two checks that matter most:
      * a brand claim with no corpus-sourced evidence behind it
      * a figure or standard in the script that appears nowhere in the dossier
    """
    findings: List[Dict[str, Any]] = []

    sourced = [
        item for group in ("historical_evidence", "scientific_evidence")
        for item in (dossier.get(group) or [])
        if isinstance(item, dict) and item.get("evidence_origin") == ORIGIN_MAGPPIE
    ]
    dossier_text = _text_of(dossier)
    dossier_figures = {_norm_figure(f) for f in measurements_in(dossier_text)}

    # Everything the viewer actually hears or reads.
    surfaces: List[tuple] = []
    hook = script.get("hook") or {}
    if hook.get("hook_text"):
        surfaces.append(("hook", hook["hook_text"]))
    for scene in script.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        number = scene.get("scene_number", "?")
        for field in ("narration", "on_screen_text"):
            if scene.get(field):
                surfaces.append((f"scene {number} {field}", scene[field]))
    cta = script.get("call_to_action") or {}
    if cta.get("cta_text"):
        surfaces.append(("call to action", cta["cta_text"]))

    for where, text in surfaces:
        for figure in measurements_in(text):
            if _norm_figure(figure) not in dossier_figures:
                findings.append(_finding(
                    CRITICAL, "Product Truth",
                    f"The {where} states \"{figure}\", which appears nowhere in the "
                    f"research dossier. A figure must be traceable, not extrapolated.",
                ))
        if mentions_brand(text) and measurements_in(text) and not sourced:
            findings.append(_finding(
                CRITICAL, "Product Truth",
                f"The {where} makes a measurable claim about Magppie, but the dossier "
                f"holds no corpus-sourced evidence to support it.",
            ))

    # A verified-stat opening is a promise that the number is verified.
    if (hook.get("opening_form") == "verified-stat"):
        figures = measurements_in(hook.get("hook_text", ""))
        if not figures:
            findings.append(_finding(
                IMPORTANT, "Product Truth",
                "The hook is tagged 'verified-stat' but states no figure.",
            ))
        elif not _has_verified_support(dossier, figures):
            findings.append(_finding(
                CRITICAL, "Product Truth",
                f"The hook opens on {', '.join(figures)} as a verified statistic, but no "
                f"VERIFIED claim in the dossier carries that figure.",
            ))

    if not corpus_populated:
        brandish = [w for w, t in surfaces if mentions_brand(t)]
        if brandish:
            findings.append(_finding(
                IMPORTANT, "Product Truth",
                "The script speaks about Magppie, but no brand corpus documents have "
                "been uploaded, so none of it is traceable. Upload Magppie source "
                "material to make these claims verifiable.",
            ))

    return _dedupe(findings)


# ------------------------------------------------------------------ helpers

def _has_verified_support(dossier: Dict[str, Any], figures: Sequence[str]) -> bool:
    wanted = {_norm_figure(f) for f in figures}
    for group in ("historical_evidence", "scientific_evidence"):
        for item in dossier.get(group) or []:
            if not isinstance(item, dict):
                continue
            if item.get("verification_status") != "VERIFIED":
                continue
            found = {_norm_figure(f) for f in measurements_in(_text_of(item))}
            if wanted & found:
                return True
    return False


def _norm_figure(figure: str) -> str:
    return re.sub(r"[\s,]", "", (figure or "").lower())


def _finding(severity: str, category: str, description: str) -> Dict[str, Any]:
    return {"severity": severity, "category": category, "description": description}


def _clip(text: str, limit: int = 90) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _dedupe(findings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen, unique = set(), []
    for finding in findings:
        key = (finding["severity"], finding["description"])
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


def summarise(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Verdict for run-state, mirroring the diversity gate's shape."""
    critical = [f for f in findings if f["severity"] == CRITICAL]
    return {
        "verdict": "FAIL" if critical else ("WARN" if findings else "PASS"),
        "critical": len(critical),
        "important": len(findings) - len(critical),
        "findings": findings,
    }
