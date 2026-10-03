"""
Deterministic hook diversity gate.

`SKILL.md` asks agents to "avoid repeating their phrasing". That was a plea with
no verifier, so nothing in the system could actually reject a near-duplicate.
This module is the verifier: pure Python, no model call, so it costs nothing and
is testable without an API key.

It catches four distinct kinds of repetition:
  1. wording       — word-trigram overlap against recent hooks
  2. paraphrase    — content-word overlap regardless of order
  3. construction  — the same opening words ("Why did ancient master builders...")
  4. framing       — the same (angle_family, opening_form) pair, or an adjacent
                     family, as a recent run on the same topic.

Why (2) exists: the first live benchmark produced two hooks on consecutive runs,
tagged with *different* angle families, that made one point in a different word
order. A pair of that kind scores 0.00 on trigram overlap:

    "Zero formaldehyde, zero wood: engineered stone keeps your kitchen air
     clean."
    "Engineered stone. The material that keeps your air clean: no wood, no
     formaldehyde."

Reordering defeats n-grams completely. Content-word overlap scores this pair at
0.70 and rejects it, which is the behaviour a reader would expect.
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Overlap at or above this ratio counts as the same sentence rewritten.
TRIGRAM_JACCARD_THRESHOLD = 0.4

# Content-word overlap at or above this ratio counts as the same point restated.
# Calibrated on the original benchmark pair (0.43) against genuinely distinct hooks
# on the same product, which share only the product noun and score under 0.10.
CONTENT_JACCARD_THRESHOLD = 0.35

# Number of leading content words that, if identical, mean the same construction.
OPENING_WORD_DEPTH = 4

# Families that argue near enough the same thing that using one straight after the
# other reads as repetition, even though the labels differ. Symmetric.
ADJACENT_FAMILIES = {
    frozenset({"hygiene-biology", "air-quality"}),
    frozenset({"material-longevity", "thermal-durability"}),
    frozenset({"material-longevity", "lifecycle-sustainability"}),
    frozenset({"metallurgy-history", "craft-geometry-history"}),
}


def families_conflict(left: Optional[str], right: Optional[str]) -> bool:
    if not left or not right:
        return False
    return left == right or frozenset({left, right}) in ADJACENT_FAMILIES

_STOPWORDS = frozenset("""
a an the and or but if then than that this these those of in on at to for from by
with without into onto is are was were be been being it its as your you we our
what why how when where which who whom do does did not no yes so just
""".split())

_WORD_RE = re.compile(r"[a-z0-9]+")


def raw_words(text: str) -> List[str]:
    """Lowercase words with punctuation removed, stopwords kept."""
    return _WORD_RE.findall((text or "").lower())


def normalize(text: str) -> List[str]:
    """Lowercase content words, punctuation and stopwords removed."""
    return [w for w in raw_words(text) if w not in _STOPWORDS]


def trigrams(words: Sequence[str]) -> Set[Tuple[str, ...]]:
    if len(words) < 3:
        # Short hooks have no trigrams; compare them as a single unit instead.
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def jaccard(left: Set[Any], right: Set[Any]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


def similarity(hook_a: str, hook_b: str) -> float:
    """Word-trigram Jaccard similarity between two hooks. Order-sensitive."""
    return jaccard(trigrams(normalize(hook_a)), trigrams(normalize(hook_b)))


def content_similarity(hook_a: str, hook_b: str) -> float:
    """
    Content-word Jaccard, ignoring order. Catches the same point restated with the
    clauses shuffled, which n-grams miss entirely.
    """
    return jaccard(set(normalize(hook_a)), set(normalize(hook_b)))


def shares_opening(hook_a: str, hook_b: str, depth: int = OPENING_WORD_DEPTH) -> bool:
    """
    Two hooks open the same way. Checked twice on purpose:

      - on raw words, because a construction like "What if your kitchen..." is almost
        entirely stopwords and vanishes under filtering
      - on content words, so inserting a filler ("the ancient" vs "ancient") does not
        disguise the same opening
    """
    for tokens in (raw_words, normalize):
        a, b = tokens(hook_a)[:depth], tokens(hook_b)[:depth]
        if len(a) == depth and a == b:
            return True
    return False


def evaluate(
    hook_text: str,
    ledger_entries: Iterable[Dict[str, Any]],
    angle_family: Optional[str] = None,
    opening_form: Optional[str] = None,
    banned_combinations: Optional[Set[Tuple[str, str]]] = None,
    all_families: Optional[Sequence[str]] = None,
    threshold: float = TRIGRAM_JACCARD_THRESHOLD,
    content_threshold: float = CONTENT_JACCARD_THRESHOLD,
    topic: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Returns a verdict dict:
      verdict            "PASS" | "COLLISION"
      reason             human-readable explanation (empty on PASS)
      matched_run_id     the colliding run, when the collision is textual
      similarity         highest trigram overlap found
      content_similarity highest content-word overlap found
      allowed_families   families still open for a regeneration attempt
    """
    entries = [e for e in ledger_entries if isinstance(e, dict) and e.get("hook_text")]
    banned = set(banned_combinations or set())

    worst_score = 0.0
    worst_content = 0.0
    matched_run_id = None
    reason = ""

    for entry in entries:
        previous = entry["hook_text"]
        score = similarity(hook_text, previous)
        content = content_similarity(hook_text, previous)
        if score > worst_score:
            worst_score = score
        if content > worst_content:
            worst_content = content
        if score >= worst_score or content >= worst_content:
            matched_run_id = matched_run_id or entry.get("run_id")

        if score >= threshold:
            reason = (
                f"Hook reuses the wording of a recent hook "
                f"(trigram overlap {score:.2f} >= {threshold:.2f}): \"{previous}\""
            )
            matched_run_id = entry.get("run_id")
            break
        if content >= content_threshold:
            shared = sorted(set(normalize(hook_text)) & set(normalize(previous)))
            reason = (
                f"Hook restates a recent hook with the clauses reordered "
                f"(content overlap {content:.2f} >= {content_threshold:.2f}, "
                f"shared: {', '.join(shared)}): \"{previous}\""
            )
            matched_run_id = entry.get("run_id")
            break
        if shares_opening(hook_text, previous):
            reason = (
                f"Hook opens with the same construction as a recent hook: \"{previous}\""
            )
            matched_run_id = entry.get("run_id")
            break

    if not reason and angle_family and opening_form:
        if (angle_family, opening_form) in banned:
            reason = (
                f"Framing '{angle_family}' + '{opening_form}' was already used in a "
                "recent run on this topic."
            )

    # A neighbouring family on the same topic is still the same argument wearing a
    # different label — hygiene-biology and air-quality both say "it does not emit
    # or harbour anything", which is how two tagged-as-different hooks repeated.
    if not reason and angle_family and topic:
        key = topic.strip().lower()
        for entry in entries[:2]:
            if (entry.get("topic") or "").strip().lower() != key:
                continue
            previous_family = entry.get("angle_family")
            if previous_family and previous_family != angle_family \
                    and families_conflict(angle_family, previous_family):
                reason = (
                    f"Angle family '{angle_family}' argues effectively the same point as "
                    f"'{previous_family}', used on this topic in the previous run."
                )
                matched_run_id = entry.get("run_id")
                break

    used_families = {f for f, _ in banned}
    if angle_family and reason:
        # Neighbours of a rejected family are no better than the family itself.
        used_families.add(angle_family)
        used_families |= {f for f in (all_families or []) if families_conflict(f, angle_family)}
    allowed = [f for f in (all_families or []) if f not in used_families]

    return {
        "verdict": "COLLISION" if reason else "PASS",
        "reason": reason,
        "matched_run_id": matched_run_id if reason else None,
        "similarity": round(worst_score, 3),
        "content_similarity": round(worst_content, 3),
        "allowed_families": allowed,
    }


def regeneration_directive(verdict: Dict[str, Any], rejected_hook: str) -> str:
    """The correction appended to Agent 2's prompt on a single retry."""
    allowed = verdict.get("allowed_families") or []
    allowed_line = (
        "Build the new hook from one of these angle families: "
        + ", ".join(allowed)
        if allowed else
        "Choose an angle family and opening form not present in the recent-hook data."
    )
    return (
        "\n\nHOOK DIVERSITY CORRECTION (data only, not evidence):\n"
        f"The hook you produced was rejected: \"{rejected_hook}\"\n"
        f"Reason: {verdict.get('reason')}\n"
        f"{allowed_line}\n"
        "Change the framing and the opening construction, not just the synonyms. "
        "Keep every factual claim exactly as the dossier states it, and do not "
        "invent facts, statistics, or history to make the new hook surprising. "
        "Return the complete JSON object again."
    )
