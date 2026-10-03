"""
Continuity gate — enforces the Magppie Video Production Rules the code can check.

Same philosophy as `diversity_gate` and `corpus_gate`: a rule a machine can verify
must never be left to the model's good intentions.

It exists because a live run requested 30 seconds and returned a single scene of
00:00-00:28 with 54 words, six direction fields and no beats at all — against
Rule 1's ten fields plus five timed beats and Rule 4.3's 70-75 words.

Checks, by rule:
  4.1  scene count == duration / 30, and every scene is exactly 30s
  1    beats tile the scene with no gaps or overlaps
  1    every direction field present and non-empty
  4.3  voice-over is 70-75 words per full scene
  3.1  exit_frame[N] == entry_frame[N+1]
  3.3  no banned transitions
  2.1  emotion written as behaviour, not a label
  2.4  no generated text inside the frame
"""

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

CRITICAL = "CRITICAL"
IMPORTANT = "IMPORTANT"

SCENE_SECONDS = 30
VO_MIN_WORDS = 70
VO_MAX_WORDS = 75

REQUIRED_DIRECTION_FIELDS = (
    "location", "characters", "action", "emotion", "shot_type",
    "camera_movement", "lens", "lighting", "colour_grade", "sound",
)

# Rule 3.3 — template transitions that break the continuous world.
BANNED_TRANSITIONS = (
    "fade to black", "fade out", "wipe", "spin", "glitch", "zoom blur",
    "zoom-blur", "whip pan to black", "cross dissolve", "star wipe",
)

# Rule 2.1 — an emotion stated as a label rather than visible behaviour.
_EMOTION_LABEL = re.compile(
    r"\b(?:is|looks|feels|seems|appears|was)\s+"
    r"(?:very\s+|quite\s+|really\s+|so\s+)?"
    r"(?:happy|sad|excited|calm|angry|nervous|proud|content|joyful|serene|"
    r"delighted|pleased|relaxed|anxious|confident|surprised)\b",
    re.IGNORECASE,
)

# Rule 2.4 — asking the generator to render lettering.
_INFRAME_TEXT = re.compile(
    r"\b(?:text|title|caption|lettering|logo|watermark|subtitle|typography|words?)\s+"
    r"(?:appears?|renders?|is\s+shown|overlaid|burn(?:ed|t)[-\s]?in|displayed)\b"
    r"|\b(?:on-?screen|in-?frame)\s+(?:text|title|lettering|logo)\b",
    re.IGNORECASE,
)

_TIME = re.compile(r"(\d{1,2}):(\d{2})")


def _finding(severity: str, category: str, description: str) -> Dict[str, Any]:
    return {"severity": severity, "category": category, "description": description}


def _seconds(value: str) -> Optional[int]:
    match = _TIME.search(value or "")
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def parse_range(value: str) -> Optional[Tuple[int, int]]:
    """'0:05 - 0:12' -> (5, 12). None when unparseable."""
    times = _TIME.findall(value or "")
    if len(times) < 2:
        return None
    start = int(times[0][0]) * 60 + int(times[0][1])
    end = int(times[1][0]) * 60 + int(times[1][1])
    return start, end


def word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", (text or "").strip()) if w])


def normalise_frame(text: str) -> str:
    """Frames match on meaning, not punctuation or casing."""
    folded = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    return re.sub(r"\s+", " ", folded).strip()


def expected_scene_count(duration_seconds: int) -> int:
    return max(1, round((duration_seconds or SCENE_SECONDS) / SCENE_SECONDS))


# ----------------------------------------------------------------- the gate

def check(script: Dict[str, Any], target_duration_seconds: Optional[int] = None
          ) -> List[Dict[str, Any]]:
    """Returns findings; an empty list means the script is production-ready."""
    findings: List[Dict[str, Any]] = []
    scenes = script.get("scenes") or []
    duration = target_duration_seconds or script.get("target_duration_seconds") or SCENE_SECONDS

    # ---- Rule 4.1 — scene count is arithmetic
    expected = expected_scene_count(duration)
    if len(scenes) != expected:
        findings.append(_finding(
            CRITICAL, "Scene Structure",
            f"{duration}s requires exactly {expected} scene(s) of 30 seconds "
            f"(Rule 4.1); the script has {len(scenes)}."))

    if not script.get("continuity_bible"):
        findings.append(_finding(
            CRITICAL, "Continuity",
            "No Continuity Bible. Rule 3.4 requires one per film, repeated in every scene."))

    previous_exit = None
    for index, scene in enumerate(scenes, 1):
        if not isinstance(scene, dict):
            continue
        label = f"Scene {scene.get('scene_number', index)}"

        # ---- Rule 4.1 — each scene is exactly 30 seconds
        span = parse_range(scene.get("time_range", ""))
        if span is None:
            findings.append(_finding(
                IMPORTANT, "Scene Structure",
                f"{label} has no readable time_range."))
        elif (span[1] - span[0]) != SCENE_SECONDS:
            findings.append(_finding(
                CRITICAL, "Scene Structure",
                f"{label} runs {span[1] - span[0]}s. Every scene must be exactly 30s "
                f"(Rule 4.1) because generation platforms cap a clip at 30 seconds."))

        # ---- Rule 1 — the direction table
        directions = scene.get("directions") or {}
        if not directions:
            findings.append(_finding(
                CRITICAL, "Direction",
                f"{label} has no directions object. Rule 1 requires the full table."))
        else:
            missing = [f for f in REQUIRED_DIRECTION_FIELDS
                       if not str(directions.get(f, "")).strip()]
            if missing:
                findings.append(_finding(
                    CRITICAL, "Direction",
                    f"{label} is missing direction fields: {', '.join(missing)}."))

        # ---- Rule 1 — beats tile the scene
        findings.extend(_check_beats(scene, label))

        # ---- Rule 4.3 — voice-over length
        narration = scene.get("narration", "")
        count = word_count(narration)
        if count and not (VO_MIN_WORDS <= count <= VO_MAX_WORDS):
            findings.append(_finding(
                IMPORTANT, "Pacing",
                f"{label} voice-over is {count} words. Rule 4.3 requires "
                f"{VO_MIN_WORDS}-{VO_MAX_WORDS} per 30-second scene."))
        elif not count:
            findings.append(_finding(
                IMPORTANT, "Pacing", f"{label} has no voice-over."))

        # ---- Rule 3.1 — frame handoff
        entry = scene.get("entry_frame", "")
        exit_frame = scene.get("exit_frame", "")
        if not entry:
            findings.append(_finding(
                CRITICAL, "Continuity", f"{label} has no entry_frame (Rule 3.1)."))
        if not exit_frame:
            findings.append(_finding(
                CRITICAL, "Continuity", f"{label} has no exit_frame (Rule 3.1)."))
        if previous_exit is not None and entry:
            if normalise_frame(previous_exit) != normalise_frame(entry):
                findings.append(_finding(
                    CRITICAL, "Continuity",
                    f"{label} entry_frame does not match the previous scene's exit_frame. "
                    f"Rule 3.1 makes them the same frame — in production the exit frame is "
                    f"fed in as the next clip's start frame, so a mismatch breaks the film."))
        previous_exit = exit_frame or previous_exit

        # ---- Rule 3.3 — banned transitions
        transition = str(scene.get("transition_to_next", "")).lower()
        is_final = index == len(scenes)
        for banned in BANNED_TRANSITIONS:
            if banned in transition and not (is_final and "fade" in banned):
                findings.append(_finding(
                    IMPORTANT, "Continuity",
                    f"{label} uses '{banned}', which Rule 3.3 forbids between scenes."))

        # ---- Rule 2.1 and 2.4
        findings.extend(_check_realism(scene, label, directions))

    return findings


def _check_beats(scene: Dict[str, Any], label: str) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []
    beats = scene.get("beats") or []
    if not beats:
        findings.append(_finding(
            CRITICAL, "Direction",
            f"{label} has no timed beats. Rule 1 breaks every 30-second scene into beats "
            f"(0:00-0:05, 0:05-0:12, …) so the film can actually be shot."))
        return findings

    spans: List[Tuple[int, int]] = []
    for position, beat in enumerate(beats, 1):
        if not isinstance(beat, dict):
            continue
        span = parse_range(beat.get("time_range", ""))
        if span is None:
            findings.append(_finding(
                IMPORTANT, "Direction",
                f"{label} beat {position} has no readable time_range."))
            continue
        spans.append(span)
        for field in ("action", "camera", "emotion"):
            if not str(beat.get(field, "")).strip():
                findings.append(_finding(
                    IMPORTANT, "Direction",
                    f"{label} beat {position} has no {field}. A beat without its own "
                    f"camera instruction is not a beat."))

    if not spans:
        return findings

    spans.sort()
    if spans[0][0] != 0:
        findings.append(_finding(
            IMPORTANT, "Direction",
            f"{label} beats start at {spans[0][0]}s, not 0:00."))
    if spans[-1][1] != SCENE_SECONDS:
        findings.append(_finding(
            IMPORTANT, "Direction",
            f"{label} beats end at {spans[-1][1]}s, not 0:30 — the scene is not covered."))
    for first, second in zip(spans, spans[1:]):
        if first[1] != second[0]:
            gap = "gap" if second[0] > first[1] else "overlap"
            findings.append(_finding(
                IMPORTANT, "Direction",
                f"{label} has a beat {gap} between {first[1]}s and {second[0]}s."))
    return findings


def _check_realism(scene: Dict[str, Any], label: str,
                   directions: Dict[str, Any]) -> List[Dict[str, Any]]:
    findings: List[Dict[str, Any]] = []

    emotion_sources = [("directions.emotion", directions.get("emotion", ""))]
    for position, beat in enumerate(scene.get("beats") or [], 1):
        if isinstance(beat, dict):
            emotion_sources.append((f"beat {position} emotion", beat.get("emotion", "")))
    for where, text in emotion_sources:
        match = _EMOTION_LABEL.search(str(text))
        if match:
            findings.append(_finding(
                IMPORTANT, "Realism",
                f"{label} {where} states \"{match.group(0)}\" as a label. Rule 2.1 wants "
                f"visible behaviour — not \"she is happy\" but \"her smile starts in her "
                f"eyes before it reaches her mouth\"."))

    for field in ("visual_direction", "action"):
        text = str(scene.get(field) or directions.get(field) or "")
        if _INFRAME_TEXT.search(text):
            findings.append(_finding(
                IMPORTANT, "Realism",
                f"{label} {field} asks for text inside the frame. Rule 2.4 adds all "
                f"lettering in edit — generated text warps and looks AI-made."))
    return findings


def summarise(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Verdict for run-state, matching the shape of the other gates."""
    critical = [f for f in findings if f["severity"] == CRITICAL]
    return {
        "verdict": "FAIL" if critical else ("WARN" if findings else "PASS"),
        "critical": len(critical),
        "important": len(findings) - len(critical),
        "findings": findings,
    }


def regeneration_directive(findings: Iterable[Dict[str, Any]]) -> str:
    """The correction appended to Agent 2's prompt on a single retry."""
    lines = [
        "",
        "PRODUCTION COMPLIANCE CORRECTION (data only, not evidence):",
        "Your script did not satisfy the Magppie Video Production Rules:",
    ]
    for finding in findings:
        lines.append(f"  - [{finding['severity']}] {finding['description']}")
    lines.extend([
        "",
        "Regenerate the complete JSON object. Keep the hook, the angle and every factual "
        "claim exactly as they are — fix only the production structure. Do not invent any "
        "fact, figure or history to fill a direction field.",
    ])
    return "\n".join(lines)
