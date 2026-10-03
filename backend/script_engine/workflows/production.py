"""
Production phases — everything after SCRIPT_LOCKED that code can do without a model.

Agent 4 (Lookbook Director) and Agent 5 (Video Prompt Engineer) decide how the locked
script should look and how each scene is asked of a video generator. Everything in this
module is the part of that work a machine can do or verify:

  * building the directed script the two agents read (the editor's final words joined
    with the director-writer's beats, directions and frames)
  * the facts of a lookbook that are not a matter of taste (title, length, scene count,
    the frame handed from one scene to the next)
  * the parts of a video prompt that must be exact: the Continuity Bible word for word,
    the Rule 2.5 negative prompt, the locked voice-over, the entry and exit frames
  * the two production gates, and the HTML / Markdown a person reads

Same philosophy as `diversity_gate`, `continuity_gate` and `corpus_gate`: a rule a
machine can check is never left to the model's good intentions. Pure Python, no model
call, so it is testable without an API key.
"""

import copy
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from workflows import continuity_gate

CRITICAL = "CRITICAL"
IMPORTANT = "IMPORTANT"

SCENE_SECONDS = continuity_gate.SCENE_SECONDS

# States from which the production phases may start. The pipeline passes through
# SCRIPT_LOCKED on approval and comes to rest on MVP_COMPLETE; both mean "locked".
LOCKED_STATES = ("SCRIPT_LOCKED", "MVP_COMPLETE")

ASPECT_RATIOS = {
    "instagram_reels": "9:16",
    "youtube_shorts": "9:16",
    "youtube_long": "16:9",
    "brand_film": "16:9",
    "website": "16:9",
    "linkedin": "4:5",
}

KEYFRAME_FIELDS = (
    "subject", "action_state", "environment", "composition", "camera_position", "lens",
    "lighting", "materials", "colour", "depth", "realism", "continuity_constraints",
)
KEYFRAME_NAMES = (("entry_keyframe", "ENTRY"), ("key_moment_keyframe", "KEY MOMENT"),
                  ("exit_keyframe", "EXIT"))

# What Agent 5 itself writes. Everything else in video-prompts.json is placed by code
# from the locked script, the approved lookbook and the rulebook.
AGENT5_OUTPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "title": "VideoPromptDraft",
    "type": "object",
    "required": ["scene_prompts", "edit"],
    "properties": {
        "scene_prompts": {
            "type": "array", "minItems": 1,
            "items": {
                "type": "object",
                "required": ["scene_number", "starting_visual_state", "beats", "shot", "lens",
                             "movement", "realism_cues", "ending_visual_state", "audio"],
                "properties": {
                    "scene_number": {"type": "integer", "minimum": 1},
                    "starting_visual_state": {"type": "string", "minLength": 20},
                    "beats": {
                        "type": "array", "minItems": 3, "maxItems": 8,
                        "items": {"type": "object", "required": ["beat_number", "action"],
                                  "properties": {"beat_number": {"type": "integer", "minimum": 1},
                                                 "action": {"type": "string", "minLength": 15}},
                                  "additionalProperties": False},
                    },
                    "shot": {"type": "string", "minLength": 10},
                    "lens": {"type": "string", "minLength": 3},
                    "movement": {"type": "string", "minLength": 10},
                    "realism_cues": {"type": "array", "minItems": 3, "maxItems": 10,
                                     "items": {"type": "string", "minLength": 8}},
                    "ending_visual_state": {"type": "string", "minLength": 20},
                    "audio": {
                        "type": "object",
                        "required": ["ambient_sound", "music", "sound_effects", "silence"],
                        "properties": {"ambient_sound": {"type": "string"}, "music": {"type": "string"},
                                       "sound_effects": {"type": "string"}, "silence": {"type": "string"}},
                        "additionalProperties": False,
                    },
                    "overlay_timing": {"type": "string"},
                    "edit_notes": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        "edit": {
            "type": "object",
            "required": ["music_track", "end_card", "stitching_notes"],
            "properties": {"music_track": {"type": "string"}, "end_card": {"type": "string"},
                           "stitching_notes": {"type": "string"}},
            "additionalProperties": False,
        },
    },
    "additionalProperties": False,
}


class ProductionError(Exception):
    """A production phase could not produce a valid artifact. Nothing invalid is saved as approved."""


# --------------------------------------------------------------- small helpers

def read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def artifact_hash(data: Dict[str, Any]) -> str:
    """The same canonical SHA-256 the script lock uses."""
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def aspect_ratio_for(platform: str) -> str:
    return ASPECT_RATIOS.get(platform or "", "9:16")


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


_NEGATED = re.compile(r"\b(?:no|not|never|without|free of|avoid(?:s|ing)?|zero)\b[^.;:]{0,40}$", re.IGNORECASE)


def asks_for_text(text: str) -> bool:
    """True when a visual instruction asks for lettering inside the frame (Rule 2.4).
    "No on-screen text" is an instruction to leave it out, so it does not count."""
    for match in continuity_gate._INFRAME_TEXT.finditer(text or ""):
        if not _NEGATED.search(text[:match.start()]):
            return True
    return False


def _finding(severity: str, category: str, description: str) -> Dict[str, Any]:
    return {"severity": severity, "category": category, "description": description}


def summarise(findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    critical = [f for f in findings if f["severity"] == CRITICAL]
    return {"verdict": "FAIL" if critical else ("WARN" if findings else "PASS"),
            "critical": len(critical), "important": len(findings) - len(critical),
            "findings": findings}


def regeneration_directive(what: str, findings: List[Dict[str, Any]]) -> str:
    """The correction appended to an agent's prompt on its single retry."""
    lines = ["", f"PRODUCTION CORRECTION (data only, not evidence): your {what} was not accepted:"]
    lines += [f"  - [{f['severity']}] {f['description']}" for f in findings]
    lines += ["", "Return the complete JSON object again with these fixed. Change nothing else, "
                  "and never change the locked script."]
    return "\n".join(lines)


# ----------------------------------------------------------- the directed script

def align_beats(narration: str, beats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Beats come from the director-writer's draft; the editor may change the words
    afterwards. Each spoken beat must carry the approved words: the edited sentence
    when the sentences still pair up one to one, otherwise none at all (the scene's
    narration then stands alone as the authority).
    """
    spoken = [b for b in beats if str(b.get("narration") or "").strip()]
    approved = _norm(narration)
    if all(_norm(b["narration"]) in approved for b in spoken):
        return beats
    sentences = [s.strip() for s in re.findall(r"[^.!?]+[.!?]+[\"')\]]*", narration or "")]
    if len(sentences) == len(spoken):
        fixed = iter(sentences)
        return [{**b, "narration": next(fixed)} if str(b.get("narration") or "").strip() else b for b in beats]
    # Some lines survived the edit and some did not. The untouched beats keep their lines; the
    # sentences nobody holds any more go, in order, to the beats whose lines were changed.
    kept = [b for b in spoken if _norm(b["narration"]) in approved]
    held = " ".join(_norm(b["narration"]) for b in kept)
    loose = [s for s in sentences if _norm(s) not in held]
    changed = [b for b in spoken if _norm(b["narration"]) not in approved]
    share: Dict[int, str] = {}
    if changed and len(loose) >= len(changed):
        size, extra = divmod(len(loose), len(changed))
        start = 0
        for index, beat in enumerate(changed):
            take = size + (1 if index >= len(changed) - extra else 0)
            share[id(beat)] = " ".join(loose[start:start + take])
            start += take
    return [{**b, "narration": share.get(id(b), "")} if any(b is c for c in changed) else b for b in beats]


PRODUCTION_FIELDS = ("entry_frame", "exit_frame", "transition_to_next", "directions", "beats",
                     "voice_direction")


def directed_script(run_dir: Path) -> Dict[str, Any]:
    """
    The locked script as the production agents read it: the editor's final words, with
    the director-writer's frames, directions, beats and Continuity Bible attached.

    `directed-script.json` wins when a caller has already assembled it. Otherwise it is
    built from the two artifacts the script phase leaves behind.
    """
    run_dir = Path(run_dir)
    ready = read_json(run_dir / "directed-script.json")
    if ready.get("scenes"):
        return ready

    final = (read_json(run_dir / "editorial-review.json").get("final_script")) or {}
    draft = read_json(run_dir / "master-draft.json")
    by_number = {s.get("scene_number"): s for s in draft.get("scenes") or [] if isinstance(s, dict)}
    scenes = []
    for scene in final.get("scenes") or []:
        mine = by_number.get(scene.get("scene_number"), {})
        merged = dict(scene)
        for field in PRODUCTION_FIELDS:
            if not merged.get(field) and mine.get(field):
                merged[field] = mine[field]
        if merged.get("beats"):
            merged["beats"] = align_beats(str(merged.get("narration") or ""), merged["beats"])
        scenes.append(merged)
    return {
        "title": final.get("title"),
        "format": final.get("format"),
        "target_duration_seconds": final.get("target_duration_seconds"),
        "hook": final.get("hook") or {},
        "continuity_bible": final.get("continuity_bible") or draft.get("continuity_bible") or {},
        "scenes": scenes,
        "call_to_action": final.get("call_to_action") or {},
    }


def continuity_text(bible: Dict[str, Any]) -> str:
    """The Continuity Bible as one fixed block (Rule 3.4). Repeated word for word in every scene prompt."""
    people = bible.get("characters") or []
    lines = ["CHARACTERS"]
    lines += [f"  {c.get('continuity_id', 'C?')}: {str(c.get('description', '')).strip()}"
              for c in people if isinstance(c, dict)] or ["  None in frame."]
    for heading, key in (("SET / LOCATION", "set_location"), ("LIGHTING", "lighting"),
                         ("COLOUR GRADE", "colour_grade"), ("CAMERA LANGUAGE", "camera_language"),
                         ("VOICE", "voice"), ("PRODUCT", "product")):
        value = str(bible.get(key) or "").strip()
        if value:
            lines += [heading, f"  {value}"]
    return "\n".join(lines)


def negative_prompt(skill_text: str) -> str:
    """Rule 2.5's list, exactly as the rulebook words it, on one line."""
    section = re.search(r"###\s*2\.5[^\n]*\n(.*?)(?:\n###\s|\n---)", skill_text or "", re.S)
    block = re.search(r"```[^\n]*\n(.*?)```", section.group(1) if section else "", re.S)
    if not block:
        raise ProductionError("Rule 2.5's negative prompt could not be read from SKILL.md.")
    return re.sub(r"\s+", " ", block.group(1)).strip()


# ------------------------------------------------------------------ the lookbook

def generation_lookbook_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """What Agent 4 is asked for: the lookbook without the fields code fills in."""
    out = copy.deepcopy(schema)
    for field in ("lookbook_id", "run_id", "request_id", "version"):
        out.get("properties", {}).pop(field, None)
        if field in out.get("required", []):
            out["required"].remove(field)
    return out


def finish_lookbook(lookbook: Dict[str, Any], script: Dict[str, Any], request: Dict[str, Any],
                    run_id: str, version: int) -> Dict[str, Any]:
    """
    Set everything about a lookbook that is a fact rather than a visual decision.

    The title, the length, the scene count and the platform belong to the locked script,
    so they are written from it. Rule 3.1 makes scene N's exit frame and scene N+1's
    entry frame one frame, so the next entry keyframe is the previous exit keyframe.
    """
    out = copy.deepcopy(lookbook)
    scenes = script.get("scenes") or []
    overview = out.setdefault("film_overview", {})
    overview.update({
        "title": script.get("title") or overview.get("title") or request.get("topic", ""),
        "duration_seconds": len(scenes) * SCENE_SECONDS,
        "scene_count": len(scenes),
        "platform": request.get("platform", ""),
        "aspect_ratio": aspect_ratio_for(request.get("platform", "")),
    })
    made = [s for s in out.get("scenes") or [] if isinstance(s, dict)]
    made.sort(key=lambda s: s.get("scene_number") or 0)
    for index, scene in enumerate(made):
        scene["duration_seconds"] = SCENE_SECONDS
        if index and made[index - 1].get("exit_keyframe"):
            scene["entry_keyframe"] = copy.deepcopy(made[index - 1]["exit_keyframe"])
    out["scenes"] = made
    out.update({"lookbook_id": f"LKB-{run_id}-{version}", "run_id": run_id,
                "request_id": request.get("request_id", ""), "version": version})
    return out


def check_lookbook(lookbook: Dict[str, Any], script: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Findings for a schema-valid lookbook; an empty list means it may go to the reviewer."""
    findings: List[Dict[str, Any]] = []
    locked = [s.get("scene_number") for s in script.get("scenes") or []]
    made = [s.get("scene_number") for s in lookbook.get("scenes") or []]
    if made != locked:
        findings.append(_finding(
            CRITICAL, "Scene Structure",
            f"The locked script has scenes {locked}; the lookbook has {made}. The lookbook "
            f"inherits the script's scenes and may not add, drop or reorder them."))

    last = len(lookbook.get("scenes") or [])
    for index, scene in enumerate(lookbook.get("scenes") or [], 1):
        label = f"Scene {scene.get('scene_number', index)}"
        for key, name in KEYFRAME_NAMES:
            frame = scene.get(key) or {}
            empty = [f for f in KEYFRAME_FIELDS if len(str(frame.get(f) or "").strip()) < 3]
            if empty:
                findings.append(_finding(
                    CRITICAL, "Keyframe",
                    f"{label} {name} keyframe is missing: {', '.join(empty)}. A keyframe must be "
                    f"concrete enough for an image model to reproduce it."))
            if any(asks_for_text(str(frame.get(f) or "")) for f in KEYFRAME_FIELDS):
                findings.append(_finding(
                    CRITICAL, "Realism",
                    f"{label} {name} keyframe asks for text inside the frame. Rule 2.4 adds all "
                    f"titles, captions and logos in the edit."))
        transition = str(scene.get("transition_to_next") or "").lower()
        for banned in continuity_gate.BANNED_TRANSITIONS:
            if banned in transition and not (index == last and "fade" in banned):
                findings.append(_finding(
                    CRITICAL, "Continuity",
                    f"{label} uses '{banned}', which Rule 3.3 forbids between scenes."))

    moment = lookbook.get("product_moment") or {}
    if locked and moment.get("scene_number") not in locked:
        findings.append(_finding(
            IMPORTANT, "Product Moment",
            f"The product moment names scene {moment.get('scene_number')}, which the locked "
            f"script does not have."))
    return findings


# ------------------------------------------------------------- the video prompts

def _vo_lines(scene: Dict[str, Any]) -> List[Dict[str, str]]:
    lines = [{"time_range": str(b.get("time_range") or ""), "line": str(b["narration"]).strip(),
              "delivery": str(b.get("delivery") or "").strip()}
             for b in scene.get("beats") or [] if str(b.get("narration") or "").strip()]
    spoken = _norm(" ".join(l["line"] for l in lines))
    if spoken != _norm(scene.get("narration")):
        # The beats no longer carry the approved words: the scene narration is the authority.
        return [{"time_range": str(scene.get("time_range") or ""),
                 "line": str(scene.get("narration") or "").strip(), "delivery": ""}]
    return lines


def _prompt_text(prompt: Dict[str, Any], aspect_ratio: str) -> str:
    """One scene prompt in the rulebook's Phase 3 order."""
    start, end, audio, vo = prompt["start_frame"], prompt["exit_frame"], prompt["audio"], prompt["vo"]
    lines = [
        f"SCENE {prompt['scene_number']} [{prompt['time_range']}]",
        f"Platform settings: duration {SCENE_SECONDS}s, aspect ratio {aspect_ratio}",
        "", "CONTINUITY BIBLE", prompt["continuity_bible"],
        "", "START FRAME", f"Lookbook reference: {start['lookbook_keyframe_reference']}",
        start["entry_frame"], start["starting_visual_state"],
        "", "BEAT-BY-BEAT ACTION",
    ]
    lines += [f"[{b['time_range']}] {b['action']}" for b in prompt["beats"]]
    lines += ["", "SHOT / LENS / MOVEMENT", f"Shot: {prompt['shot']}", f"Lens: {prompt['lens']}",
              f"Movement: {prompt['movement']}", "", "REALISM CUES"]
    lines += [f"- {cue}" for cue in prompt["realism_cues"]]
    lines += ["", "EXIT FRAME", f"Lookbook reference: {end['lookbook_keyframe_reference']}",
              end["exit_frame"], end["ending_visual_state"],
              "", "NEGATIVE PROMPT", prompt["negative_prompt"],
              "", "AUDIO / VO (for edit)", f"Narrator: {vo['narrator']}"]
    for line in vo["lines"]:
        how = f" ({line['delivery']})" if line.get("delivery") else ""
        lines.append(f"[{line['time_range']}] \"{line['line']}\"{how}")
    lines += [f"Ambient: {audio['ambient_sound']}", f"Music: {audio['music']}",
              f"Sound effects: {audio['sound_effects']}", f"Silence: {audio['silence']}",
              "", "TEXT FOR EDIT (added in the edit, never generated in the frame)"]
    lines += [f"- \"{o['text']}\" at {o['timing']}" for o in prompt["text_overlays"]] or ["- None."]
    return "\n".join(lines)


def build_package(draft: Dict[str, Any], script: Dict[str, Any], lookbook: Dict[str, Any],
                  request: Dict[str, Any], run_id: str, script_hash: str, lookbook_hash: str,
                  negative: str) -> Dict[str, Any]:
    """
    video-prompts.json: Agent 5's visual instructions set into the parts that must be exact.

    Agent 5 never writes the Continuity Bible, the negative prompt, the voice-over, the
    locked frames or the transitions. They are placed here from the approved material,
    which is what makes them verifiable.
    """
    bible = script.get("continuity_bible") or {}
    bible_text = continuity_text(bible)
    aspect = aspect_ratio_for(request.get("platform", ""))
    by_number = {p.get("scene_number"): p for p in draft.get("scene_prompts") or [] if isinstance(p, dict)}
    scenes = script.get("scenes") or []
    edit = draft.get("edit") or {}

    prompts, sheet = [], []
    for index, scene in enumerate(scenes, 1):
        number = scene.get("scene_number", index)
        mine = by_number.get(number) or {}
        actions = {b.get("beat_number"): b.get("action") for b in mine.get("beats") or [] if isinstance(b, dict)}
        beats = [{"beat_number": b.get("beat_number", n), "time_range": str(b.get("time_range") or ""),
                  "action": str(actions.get(b.get("beat_number", n)) or "").strip()}
                 for n, b in enumerate(scene.get("beats") or [], 1)]
        overlays = ([{"text": str(scene["on_screen_text"]).strip(),
                      "timing": str(mine.get("overlay_timing") or "over the final beat").strip(),
                      "note": "TEXT FOR EDIT: added in the edit, never generated in the frame."}]
                    if str(scene.get("on_screen_text") or "").strip() else [])
        audio = mine.get("audio") or {}
        prompt = {
            "scene_number": number,
            "time_range": str(scene.get("time_range") or ""),
            "continuity_bible": bible_text,
            "start_frame": {"entry_frame": str(scene.get("entry_frame") or "").strip(),
                            "lookbook_keyframe_reference": f"Scene {number} ENTRY keyframe",
                            "starting_visual_state": str(mine.get("starting_visual_state") or "").strip()},
            "beats": beats,
            "shot": str(mine.get("shot") or "").strip(),
            "lens": str(mine.get("lens") or "").strip(),
            "movement": str(mine.get("movement") or "").strip(),
            "realism_cues": [str(c).strip() for c in mine.get("realism_cues") or [] if str(c).strip()],
            "exit_frame": {"exit_frame": str(scene.get("exit_frame") or "").strip(),
                           "lookbook_keyframe_reference": f"Scene {number} EXIT keyframe",
                           "ending_visual_state": str(mine.get("ending_visual_state") or "").strip()},
            "negative_prompt": negative,
            "audio": {k: str(audio.get(k) or "").strip() or "None"
                      for k in ("ambient_sound", "music", "sound_effects", "silence")},
            "vo": {"narrator": str(bible.get("voice") or "").strip(), "lines": _vo_lines(scene)},
            "text_overlays": overlays,
        }
        prompt["prompt_text"] = _prompt_text(prompt, aspect)
        prompts.append(prompt)

        final = index == len(scenes)
        sheet.append({
            "scene_number": number,
            "duration_seconds": SCENE_SECONDS,
            "source_clip": f"scene-{int(number):02d}.mp4" if isinstance(number, int) else f"scene-{number}.mp4",
            "entry_frame": prompt["start_frame"]["entry_frame"],
            "exit_frame": prompt["exit_frame"]["exit_frame"],
            "vo": str(scene.get("narration") or "").strip(),
            "vo_timing": [{"time_range": l["time_range"], "line": l["line"], "delivery": l["delivery"]}
                          for l in prompt["vo"]["lines"]],
            "music": prompt["audio"]["music"],
            "sound_effects": prompt["audio"]["sound_effects"],
            "ambient_sound": prompt["audio"]["ambient_sound"],
            "text_overlays": [{"text": o["text"], "timing": o["timing"]} for o in overlays],
            "transition": ("End of film: hold the exit frame, then the logo and call to action end card."
                           if final else str(scene.get("transition_to_next") or "").strip()),
            "notes": str(mine.get("edit_notes") or "").strip(),
        })

    return {
        "run_id": run_id,
        "script_hash": script_hash,
        "lookbook_hash": lookbook_hash,
        "lookbook_id": lookbook.get("lookbook_id", ""),
        "platform_settings": {"aspect_ratio": aspect, "scene_duration_seconds": SCENE_SECONDS,
                              "scene_count": len(scenes)},
        "continuity_bible": bible_text,
        "scene_prompts": prompts,
        "edit_sheet": {
            "scenes": sheet,
            "music_track": str(edit.get("music_track") or "").strip() or "None",
            "end_card": str(edit.get("end_card") or "").strip(),
            "stitching_notes": str(edit.get("stitching_notes") or "").strip(),
            "call_to_action": str((script.get("call_to_action") or {}).get("cta_text") or "").strip(),
        },
    }


def check_video_prompts(package: Dict[str, Any], script: Dict[str, Any], script_hash: str,
                        lookbook_hash: str, negative: str) -> List[Dict[str, Any]]:
    """Findings for a schema-valid production package; empty means PRODUCTION_PACKAGE_COMPLETE is earned."""
    findings: List[Dict[str, Any]] = []
    bible_text = continuity_text(script.get("continuity_bible") or {})
    scenes = script.get("scenes") or []
    prompts = {p.get("scene_number"): p for p in package.get("scene_prompts") or []}
    sheet = {s.get("scene_number"): s for s in (package.get("edit_sheet") or {}).get("scenes") or []}

    if package.get("script_hash") != script_hash:
        findings.append(_finding(CRITICAL, "Traceability", "The package does not carry the locked script's hash."))
    if package.get("lookbook_hash") != lookbook_hash:
        findings.append(_finding(CRITICAL, "Traceability", "The package does not carry the approved lookbook's hash."))
    if len(package.get("scene_prompts") or []) != len(scenes):
        findings.append(_finding(
            CRITICAL, "Scene Structure",
            f"The locked script has {len(scenes)} scene(s); the package has "
            f"{len(package.get('scene_prompts') or [])} prompt(s)."))

    for index, scene in enumerate(scenes, 1):
        number = scene.get("scene_number", index)
        label = f"Scene {number}"
        prompt = prompts.get(number)
        if not prompt:
            findings.append(_finding(CRITICAL, "Scene Structure", f"{label} has no video prompt."))
            continue
        if prompt.get("continuity_bible") != bible_text:
            findings.append(_finding(
                CRITICAL, "Continuity",
                f"{label} does not repeat the Continuity Bible word for word (Rule 3.4)."))
        if prompt.get("negative_prompt") != negative:
            findings.append(_finding(
                CRITICAL, "Realism", f"{label} does not carry Rule 2.5's negative prompt exactly."))
        locked_beats = [str(b.get("time_range") or "") for b in scene.get("beats") or []]
        made_beats = [str(b.get("time_range") or "") for b in prompt.get("beats") or []]
        if made_beats != locked_beats:
            findings.append(_finding(
                CRITICAL, "Direction",
                f"{label} must follow the locked script's {len(locked_beats)} timed beats exactly; "
                f"the prompt has {made_beats}."))
        for beat in prompt.get("beats") or []:
            if len(str(beat.get("action") or "").strip()) < 15:
                findings.append(_finding(
                    CRITICAL, "Direction",
                    f"{label} beat {beat.get('beat_number')} has no visible action written for it."))
        for where, text in (("start frame", prompt["start_frame"].get("starting_visual_state")),
                            ("exit frame", prompt["exit_frame"].get("ending_visual_state")),
                            ("shot", prompt.get("shot")), ("lens", prompt.get("lens")),
                            ("movement", prompt.get("movement"))):
            if len(str(text or "").strip()) < 3:
                findings.append(_finding(CRITICAL, "Direction", f"{label} has no {where} instruction."))
        if len(prompt.get("realism_cues") or []) < 3:
            findings.append(_finding(
                CRITICAL, "Realism", f"{label} needs at least three concrete realism cues (Rule 2)."))
        if prompt["start_frame"].get("entry_frame") != str(scene.get("entry_frame") or "").strip():
            findings.append(_finding(CRITICAL, "Continuity", f"{label} start frame is not the locked entry frame."))
        if prompt["exit_frame"].get("exit_frame") != str(scene.get("exit_frame") or "").strip():
            findings.append(_finding(CRITICAL, "Continuity", f"{label} exit frame is not the locked exit frame."))
        spoken = _norm(" ".join(l.get("line", "") for l in (prompt.get("vo") or {}).get("lines") or []))
        if spoken != _norm(scene.get("narration")):
            findings.append(_finding(
                CRITICAL, "Voice-over", f"{label} voice-over is not the locked narration."))
        generated = [prompt["start_frame"].get("starting_visual_state"), prompt["exit_frame"].get("ending_visual_state"),
                     prompt.get("shot"), prompt.get("movement"), *(b.get("action") for b in prompt.get("beats") or []),
                     *(prompt.get("realism_cues") or [])]
        if any(asks_for_text(str(g or "")) for g in generated):
            findings.append(_finding(
                CRITICAL, "Realism",
                f"{label} asks the video model for text inside the frame. Rule 2.4: on-screen "
                f"text is an edit instruction only."))
        row = sheet.get(number)
        if not row:
            findings.append(_finding(CRITICAL, "Edit Sheet", f"{label} is missing from the Edit Sheet."))
        elif index < len(scenes):
            for banned in continuity_gate.BANNED_TRANSITIONS:
                if banned in str(row.get("transition") or "").lower():
                    findings.append(_finding(
                        CRITICAL, "Edit Sheet", f"{label} uses '{banned}', which Rule 3.3 forbids."))
    return findings


# --------------------------------------------------------------------- renderers

def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


LOOKBOOK_CSS = """
:root{--bg:#0B0B0D;--card:#141417;--line:#26262B;--ink:#F2F3F5;--dim:#9A9FA8;--copper:#C77B4A;--silver:#C9CED6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 Lato,-apple-system,"Segoe UI",sans-serif;padding:28px 24px 48px}
h1{font-size:30px;font-weight:900;letter-spacing:.01em;margin:0 0 6px}h2{font-size:12px;letter-spacing:.22em;text-transform:uppercase;color:var(--copper);margin:40px 0 14px;font-weight:700}
h3{font-size:12px;letter-spacing:.16em;text-transform:uppercase;color:var(--silver);margin:0 0 10px;font-weight:700}
p{margin:0 0 8px}.dim{color:var(--dim)}.story{font-size:19px;max-width:44em;margin:14px 0}
.chips span{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:4px 14px;margin:0 8px 8px 0;font-size:13px;color:var(--silver)}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(230px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px}
.sw{border-radius:12px;overflow:hidden;border:1px solid var(--line);background:var(--card)}.sw i{display:block;height:74px}.sw div{padding:10px 12px;font-size:13px}.sw b{display:block;letter-spacing:.06em}
dl{margin:0}dt{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--dim);margin-top:9px}dd{margin:1px 0 0}
.board{display:grid;gap:10px;grid-template-columns:1fr 34px 1fr 34px 1fr;align-items:stretch}.arrow{display:flex;align-items:center;justify-content:center;color:var(--copper);font-size:22px}
.hand{margin:16px 0;padding:12px 16px;border:1px dashed var(--copper);border-radius:12px;color:var(--silver)}.hand b{color:var(--copper);letter-spacing:.1em}
.vo{border-left:2px solid var(--copper);padding:2px 0 2px 14px;margin:0 0 14px;color:var(--silver);font-style:italic}
.issue{border:1px solid var(--copper);border-radius:12px;padding:12px 16px;margin-top:10px}
footer{margin-top:44px;color:var(--dim);font-size:12px;word-break:break-all}
@media(max-width:820px){.board{grid-template-columns:1fr}.arrow{transform:rotate(90deg);height:26px}}
"""


def _card(title: str, rows: List[tuple]) -> str:
    body = "".join(f"<dt>{_e(label)}</dt><dd>{_e(value)}</dd>" for label, value in rows if str(value or "").strip())
    return f'<div class="card"><h3>{_e(title)}</h3><dl>{body}</dl></div>'


def _label(key: str) -> str:
    return key.replace("_", " ")


def render_lookbook_html(lookbook: Dict[str, Any], script: Dict[str, Any]) -> str:
    """lookbook.html: the approval artifact, ready to show as it is."""
    o = lookbook.get("film_overview") or {}
    bible = lookbook.get("continuity_bible") or {}
    narration = {s.get("scene_number"): s.get("narration") for s in script.get("scenes") or []}
    part = [f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>Lookbook: {_e(o.get('title'))}</title><style>{LOOKBOOK_CSS}</style></head><body>",
            f"<p class=\"dim\">LOOKBOOK · VERSION {_e(lookbook.get('version'))}</p><h1>{_e(o.get('title'))}</h1>",
            f"<p class=\"dim\">{_e(o.get('duration_seconds'))} seconds · {_e(o.get('scene_count'))} scene(s) · "
            f"{_e(_label(str(o.get('platform') or '')))} · {_e(o.get('aspect_ratio'))}</p>",
            f"<p class=\"story\">{_e(o.get('one_line_story'))}</p>",
            "<div class=\"chips\">" + "".join(f"<span>{_e(m)}</span>" for m in o.get("mood_words") or []) + "</div>",
            "<h2>Colour palette</h2><div class=\"grid\">"]
    for colour in o.get("colour_palette") or []:
        hex_value = colour.get("hex") if re.fullmatch(r"#[0-9A-Fa-f]{6}", str(colour.get("hex") or "")) else "#000000"
        part.append(f"<div class=\"sw\"><i style=\"background:{hex_value}\"></i><div><b>{_e(colour.get('hex'))}</b>"
                    f"{_e(colour.get('name'))}<br><span class=\"dim\">{_e(colour.get('use'))}</span></div></div>")
    part.append("</div><h2>Look</h2><div class=\"grid\">" +
                _card("Visual language", [("", o.get("overall_visual_language"))]) +
                _card("Typography (added in the edit)", [("", o.get("typography"))]) + "</div>")

    part.append("<h2>Continuity bible</h2><div class=\"grid\">")
    for person in bible.get("character_cards") or []:
        part.append(_card(f"Character {person.get('continuity_id', '')}",
                          [(_label(k), person.get(k)) for k in ("identity", "appearance", "wardrobe", "hair",
                                                               "physical_continuity", "behavioural_continuity")]))
    for title, key in (("Set and environment", "set_card"), ("Lighting", "lighting_card"),
                       ("Colour and grade", "colour_grade_card"), ("Camera language", "camera_language_card"),
                       ("Product", "product_card")):
        card = bible.get(key) or {}
        part.append(_card(title, [(_label(k), v) for k, v in card.items()]))
    part.append("</div><h2>Storyboard</h2>")

    scenes = lookbook.get("scenes") or []
    for index, scene in enumerate(scenes):
        number = scene.get("scene_number")
        part.append(f"<h3>Scene {_e(number)} · {_e(scene.get('duration_seconds'))} seconds</h3>")
        if narration.get(number):
            part.append(f"<p class=\"vo\">{_e(narration[number])}</p>")
        frames = []
        for key, name in KEYFRAME_NAMES:
            frame = scene.get(key) or {}
            frames.append(_card(name, [(_label(f), frame.get(f)) for f in KEYFRAME_FIELDS]))
        part.append("<div class=\"board\">" + "<div class=\"arrow\">&rarr;</div>".join(frames) + "</div>")
        if index + 1 < len(scenes):
            part.append(f"<div class=\"hand\"><b>SCENE {_e(number)} EXIT &rArr; SCENE "
                        f"{_e(scenes[index + 1].get('scene_number'))} ENTRY</b><br>"
                        f"{_e(scene.get('transition_to_next'))}</div>")
        else:
            part.append(f"<div class=\"hand\"><b>END OF FILM</b><br>{_e(scene.get('transition_to_next'))}</div>")

    moment = lookbook.get("product_moment") or {}
    sound = lookbook.get("sound_direction") or {}
    part.append("<h2>Product moment and sound</h2><div class=\"grid\">" +
                _card(f"Product moment · scene {moment.get('scene_number', '')}",
                      [(_label(k), moment.get(k)) for k in ("product", "moment", "visual_treatment", "camera_emphasis",
                                                           "physical_interaction", "product_truth_demonstrated")]) +
                _card("Sound direction",
                      [(_label(k), ", ".join(v) if isinstance(v, list) else v) for k, v in sound.items()]) + "</div>")
    issues = [i for i in lookbook.get("open_issues") or [] if str(i).strip()]
    if issues:
        part.append("<h2>To check before approving</h2>" +
                    "".join(f"<div class=\"issue\">{_e(i)}</div>" for i in issues))
    part.append(f"<footer>{_e(lookbook.get('lookbook_id'))} · SHA-256 {artifact_hash(lookbook)}</footer></body></html>")
    return "".join(part)


def render_video_prompts_md(package: Dict[str, Any], title: str) -> str:
    lines = [f"# Video prompts: {title}", "",
             f"Run `{package['run_id']}` · script `{package['script_hash'][:16]}` · "
             f"lookbook `{package['lookbook_hash'][:16]}`", ""]
    for prompt in package["scene_prompts"]:
        lines += [f"## Scene {prompt['scene_number']}", "", "```text", prompt["prompt_text"], "```", ""]
    return "\n".join(lines)


def render_edit_sheet_md(package: Dict[str, Any], title: str) -> str:
    sheet = package["edit_sheet"]
    lines = [f"# Edit Sheet: {title}", "",
             f"Run `{package['run_id']}` · {package['platform_settings']['scene_count']} scene(s) of "
             f"{SCENE_SECONDS} seconds · aspect ratio {package['platform_settings']['aspect_ratio']}", ""]
    for row in sheet["scenes"]:
        lines += [f"## Scene {row['scene_number']} · {row['duration_seconds']} seconds", "",
                  f"- **Clip:** `{row['source_clip']}`",
                  f"- **Entry frame:** {row['entry_frame']}",
                  f"- **Exit frame:** {row['exit_frame']}",
                  "- **Voice-over:**"]
        lines += [f"  - `{l['time_range']}` \"{l['line']}\"" + (f" ({l['delivery']})" if l.get("delivery") else "")
                  for l in row["vo_timing"]]
        lines += [f"- **Music:** {row['music']}", f"- **Sound effects:** {row['sound_effects']}",
                  f"- **Ambient sound:** {row['ambient_sound']}", "- **Text overlays (added in the edit):**"]
        lines += [f"  - \"{o['text']}\" at {o['timing']}" for o in row["text_overlays"]] or ["  - None."]
        lines += [f"- **Transition:** {row['transition']}"]
        if row.get("notes"):
            lines.append(f"- **Notes:** {row['notes']}")
        lines.append("")
    lines += ["## Whole film", "", f"- **Music track:** {sheet['music_track']}",
              f"- **End card (added in the edit):** {sheet['end_card']}",
              f"- **Call to action:** {sheet['call_to_action']}",
              f"- **Stitching:** {sheet['stitching_notes']}", ""]
    return "\n".join(lines)
