"""The video team's script engine.

The engine itself is the Magppie Content Intelligence Engine, handed over as magppie-handover-v2.zip and kept
as it was written in backend/script_engine (its prompts, schemas, rule gates and OpenRouter client):

  request → agent 1 (evidence) → agent 2 (director-writer) → hook gate → production gate
          → agent 3 (executive editor) → your approval → script locked

Added here on 3 Oct 2026, the way its rulebook says rules are added: rule 6, the voice must sound human
(one narrator, voice direction for every scene, a delivery note for every spoken line).

This file is the bridge to it. It gives the engine the company's real knowledge (the handed-over copy carried
an older company story), gives each agent its own OpenRouter key, runs it off the web server's main loop, and
returns the script in the shape the dashboard shows.

The handover names five agents. Agents 1 to 3 came built in the engine. Agents 4 and 5 were built on 3 Oct 2026
from the "Agents 4 & 5 Implementation Master Prompt" the company supplied, inside the engine itself:

  script locked → agent 4 (lookbook director) → your approval of the lookbook
                → agent 5 (video prompt engineer) → production package complete

Nothing is skipped: no lookbook before the script is locked, no video prompt before the lookbook is approved,
and an approval holds only for the exact lookbook that was approved.
"""

import asyncio
import json
import logging
import re
import shutil
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from . import brand, inputs, llm, video_types
from .config import get_settings

ENGINE = Path(__file__).resolve().parents[1] / "script_engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from workflows import corpus_gate, production                        # noqa: E402
from workflows.config import EngineConfig                            # noqa: E402
from workflows.content_pipeline import ContentPipeline               # noqa: E402
from workflows.openrouter_client import OpenRouterClient, OpenRouterError, OpenRouterRateLimitError   # noqa: E402

log = logging.getLogger("mai.script_engine")

NAME = "Magppie Content Intelligence Engine"
SECONDS = 30            # one 30-second scene: the engine's unit, and one Higgsfield clip
# Measured 3 Oct 2026: a healthy call answers in 50 to 80 seconds. Now and then the free provider stalls (about
# 8 tokens a second instead of 100) and gives up after some 340 seconds with nothing. Such a call is left behind
# after this long and asked again.
DEADLINE = 200
AGENTS = (              # number, key slot, role, built
    (1, "evidence", "Evidence and Intelligence", True),
    (2, "writer", "Director-Writer", True),
    (3, "editor", "Executive Editor", True),
    (4, "lookbook", "Lookbook Director", True),
    (5, "video_prompt", "Video Prompt Engineer", True),
)
STAGES = {              # the engine's run states, in plain words for the progress bar
    "RESEARCHING": "Agent 1 of 5 · gathering the evidence",
    "MASTER_DRAFTING": "Agent 2 of 5 · writing and directing the script",
    "DIVERSITY_CHECK": "Rule gate · is the hook new",
    "CONTINUITY_CHECK": "Rule gate · timing, beats and frames",
    "EDITOR_REVIEWING": "Agent 3 of 5 · editing and checking every claim",
    "MASTER_DRAFT_REVISION": "Rewriting the script with the changes asked for",
    "LOOKBOOK_DRAFTING": "Agent 4 of 5 · drawing up the lookbook",
    "VIDEO_PROMPTS_DRAFTING": "Agent 5 of 5 · writing the video prompts and the edit sheet",
}
AUDIENCE = ("Families building or renovating premium homes in India, and the architects, designers and builders "
            "who specify for them")
PRODUCT = "MAGPPIE Wellness Kitchen, built entirely from SILVERSTONE engineered stone"


def keys() -> dict[int, str]:
    """Each agent's own OpenRouter key; an agent without one uses the shared key."""
    s = get_settings()
    return {n: (getattr(s, f"openrouter_key_{slot}") or s.openrouter_api_key).strip() for n, slot, _, _ in AGENTS}


def available() -> bool:
    k = keys()
    return all(k[n] for n in (1, 2, 3))


def status() -> dict:
    s = get_settings()
    return {"name": NAME, "model": s.script_engine_model, "ready": available(),
            "agents": [{"number": n, "role": role, "built": built,
                        "own_key": bool(getattr(s, f"openrouter_key_{slot}")), "has_key": bool(keys()[n])}
                       for n, slot, role, built in AGENTS]}


class KeyedClient(OpenRouterClient):
    """The engine's own OpenRouter client, sending each agent's calls with that agent's key."""

    def __init__(self, config: EngineConfig, agent_keys: dict[int, str]):
        super().__init__(config)
        self.agent_keys = agent_keys

    def _request_model(self, system_instruction, user_prompt, temperature=None, max_tokens=None,
                       agent_name="unknown", run_id="run-unknown", **more):
        m = re.match(r"Agent (\d)", agent_name)
        self.api_key = (self.agent_keys.get(int(m.group(1))) if m else "") or self.config.openrouter_api_key
        ask = super()._request_model
        for attempt in (1, 2):
            box: dict = {}

            def work():
                try:
                    box["answer"] = ask(system_instruction, user_prompt, temperature, max_tokens, agent_name, run_id, **more)
                except BaseException as e:  # noqa: BLE001 — handed back to the caller's thread below
                    box["error"] = e

            worker = threading.Thread(target=work, daemon=True)
            worker.start()
            worker.join(DEADLINE)
            if "answer" in box:
                return box["answer"]
            error = box.get("error") or OpenRouterError(f"{agent_name} gave no answer within {DEADLINE} seconds.")
            stalled = "error" not in box or "returned no script content" in str(error)
            if attempt == 2 or not stalled or isinstance(error, OpenRouterRateLimitError):
                raise error
            log.warning("[%s] %s stalled (%s); asking again", run_id, agent_name, str(error)[:120])


def _config(run_id: str | None = None) -> EngineConfig:
    """The engine's settings, as in its own .env.example. Each run reads the knowledge written for it."""
    s = get_settings()
    runs = s.data_dir / "script-engine" / "runs"
    return EngineConfig(
        project_root=ENGINE, openrouter_api_key=s.openrouter_api_key.strip() or None, model_provider="openrouter",
        model_name=s.script_engine_model, temperature=0.7, max_tokens=20000, timeout_seconds=90, max_retries=3,
        runs_dir=runs, schemas_dir=ENGINE / "schemas", agents_dir=ENGINE / "agents",
        knowledge_dir=runs / run_id / "knowledge" if run_id else ENGINE / "knowledge")


class Pipeline(ContentPipeline):
    """The engine's pipeline with two additions: the writer must direct the voice (rule 6 of the rulebook),
    and the writer's latest draft is kept, because a revision's draft is not saved as data by the engine."""

    last_draft: dict = {}

    def _generation_schema(self, name: str) -> dict:
        schema = super()._generation_schema(name)
        if name == "script.schema.json" and schema:
            required = schema["properties"]["scenes"]["items"].setdefault("required", [])
            required += [f for f in ("voice_direction",) if f not in required]
            for part, field in (("continuity_bible", "voice"), ("beat", "delivery")):
                required = schema["definitions"][part].setdefault("required", [])
                required += [f for f in (field,) if f not in required]
        return schema

    def _execute_agent_2(self, *args, **kwargs):
        result = super()._execute_agent_2(*args, **kwargs)
        self.last_draft = result[0]
        return result

    def _execute_agent_4(self, *args, **kwargs):
        draft, latency, tokens = super()._execute_agent_4(*args, **kwargs)
        return brand.scrub(draft), latency, tokens

    def _execute_agent_5(self, *args, **kwargs):
        draft, latency, tokens = super()._execute_agent_5(*args, **kwargs)
        return brand.scrub(draft), latency, tokens

    @staticmethod
    def extra_checks(kind: str, artifact: dict) -> list[dict]:
        """The brand rules, as findings for the engine's production gates."""
        return [{"severity": "CRITICAL", "category": "Brand", "description": f"The {kind} breaks a MAGPPIE brand rule: {why}"}
                for why in _brand_breaks(artifact)]


NOT_ASKED_FOR = re.compile(r"\b(?:no|not|never|without|zero|free of|avoid(?:s|ing)?)\b[^.;:]{0,40}$", re.I)


def _brand_breaks(obj) -> list[str]:
    """brand.violations for visual directions, where "no steel cabinets anywhere" is an instruction, not a claim."""
    found = []
    for text in brand._strings(obj):
        for rx, why in brand._BANNED:
            for m in rx.finditer(text):
                if not NOT_ASKED_FOR.search(text[:m.start()]):
                    found.append(f'"{m.group(0)}": {why}')
                    break
    return list(dict.fromkeys(found))


class BackupClient:
    """The other brains, speaking the engine's client language. Used for agents 4 and 5 only when OpenRouter
    cannot answer (its free model is limited per day), so an approved script is never left stranded."""

    def __init__(self, loop):
        self.loop = loop

    def call_model(self, system_instruction, user_prompt, temperature=None, agent_name="unknown", run_id="run",
                   response_schema=None, **_):
        began = time.time()
        log.warning("[%s] %s runs on the backup brains", run_id, agent_name)
        if response_schema:                      # these brains are not handed the schema any other way
            user_prompt += "\n\nJSON SCHEMA of the object to return:\n" + json.dumps(response_schema, ensure_ascii=False)
        ask = llm.chat_json(system_instruction, user_prompt, temperature=temperature if temperature is not None else 0.4)
        parsed = asyncio.run_coroutine_threadsafe(ask, self.loop).result(timeout=900)
        return {"parsed_json": parsed, "latency_seconds": round(time.time() - began, 3), "usage": {}, "status": "SUCCESS"}


def _pipeline(run_id: str) -> Pipeline:
    p = Pipeline(_config(run_id))
    p.client = KeyedClient(p.config, keys())
    return p


def _write_knowledge(folder: Path, team_knowledge: str) -> None:
    """The company truth the three agents read: brand identity, product knowledge and the claims register."""
    s = get_settings()
    product = (s.inputs_dir / "company-kb.md").read_text(encoding="utf-8")
    if team_knowledge.strip():
        product += "\n\n# Added by the team\n" + team_knowledge.strip() + "\n"
    files = {
        "brand/positioning.md": inputs.brand_guide(),
        "products/core_products.md": product,
        "approved-claims/verified_claims.md": (s.inputs_dir / "approved-claims.md").read_text(encoding="utf-8"),
    }
    for name, text in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text, encoding="utf-8")
    (folder / "references").mkdir(parents=True, exist_ok=True)
    for name in ("angle-taxonomy.md", "evidence-index.md"):
        shutil.copyfile(ENGINE / "knowledge" / "references" / name, folder / "references" / name)


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _untraced_figures(script: dict, dossier: dict, folder: Path) -> list[str]:
    """Numbers and standards the viewer would hear or read that are in neither the dossier nor the knowledge.
    (The engine's corpus gate does this reading; it is built there but not yet called by its pipeline.)"""
    known = corpus_gate._text_of(dossier) + "\n" + "\n".join(
        p.read_text(encoding="utf-8") for p in folder.rglob("*.md") if p.parent.name != "references")
    known = {corpus_gate._norm_figure(f) for f in corpus_gate.measurements_in(known)}
    said = [(script.get("hook") or {}).get("hook_text", ""), (script.get("call_to_action") or {}).get("cta_text", "")]
    for scene in script.get("scenes") or []:
        said += [str(scene.get("narration") or ""), str(scene.get("on_screen_text") or "")]
    out = []
    for text in said:
        for figure in corpus_gate.measurements_in(text):
            if corpus_gate._norm_figure(figure) not in known and figure not in out:
                out.append(figure)
    return out


align_beats = production.align_beats


COLOURS = re.compile(r"\b(?:white(?:ness)?|black|grey|gray|beige|ivory|cream|golden)\b", re.I)


def notes_for(script: dict) -> list[str]:
    """What a person should look at before approving, in plain words."""
    said = " ".join(str(sc.get("narration") or "") for sc in script.get("scenes") or [])
    colours = sorted({m.group(0).lower() for m in COLOURS.finditer(said)})
    return [f"The voice-over names a colour of the stone ({', '.join(colours)}). The knowledge does not give the "
            "stone's colour: check it, or change the line."] if colours else []


def _run(run_id: str, request: dict) -> dict:
    began = time.time()
    p = _pipeline(run_id)
    run_dir = p.config.runs_dir / run_id
    try:
        out = p.run_pipeline(request, run_id=run_id)      # stops at the human approval gate
    except OpenRouterRateLimitError:
        raise                                             # the day's free requests are spent: waiting will not help
    except Exception as e:  # noqa: BLE001 — the free model sometimes returns nothing: resume keeps the finished steps
        log.warning("%s: the engine stopped (%s); resuming from the last finished step", run_id, str(e)[:200])
        out = p.run_pipeline(request, run_id=run_id, resume=True)
    script, revised = out["final_script"], False
    broken = brand.violations(script)
    if broken:                                            # the engine's own "request changes" path, once
        log.warning("%s: the script broke brand rules (%s); asking the engine for changes", run_id, broken)
        out = p.apply_approval_decision(
            run_id, "REQUEST_CHANGES", "MAGI brand check",
            "Rewrite every line that breaks a MAGPPIE brand rule, and change nothing else: " + "; ".join(broken))
        script, revised = out["final_script"], True
        broken = brand.violations(script)
        if broken:
            raise RuntimeError("The script kept breaking the brand rules: " + "; ".join(broken))
    return _assemble(p, run_id, request, script, began, "brand check" if revised else "")


def _revise(run_id: str, asked_by: str, feedback: str) -> dict:
    """The manager asked for changes to the script: the engine's own revision loop (agent 2, then agent 3), once."""
    began = time.time()
    p = _pipeline(run_id)
    request = _read(p.config.runs_dir / run_id / "request.json")
    state_file = p.config.runs_dir / run_id / "run-state.json"
    before = state_file.read_text(encoding="utf-8")
    for attempt in (1, 2):                 # the engine leaves a failed revision half-done: put the run back, try once more
        try:
            out = p.apply_approval_decision(run_id, "REQUEST_CHANGES", asked_by or "Manager", feedback)
            break
        except ValueError:
            raise                          # the engine's own rule (for example: already revised once)
        except Exception as e:  # noqa: BLE001
            state_file.write_text(before, encoding="utf-8")
            if attempt == 2 or isinstance(e, OpenRouterRateLimitError):
                raise
            log.warning("%s: the revision stopped (%s); trying once more", run_id, str(e)[:160])
    script = out["final_script"]
    broken = brand.violations(script)
    if broken:
        raise RuntimeError("The rewritten script breaks the brand rules: " + "; ".join(broken))
    return _assemble(p, run_id, request, script, began, "the manager")


def _assemble(p: Pipeline, run_id: str, request: dict, script: dict, began: float, revised_by: str) -> dict:
    """The engine's artifacts as the dashboard shows them, and as agents 4 and 5 will read them."""
    run_dir = p.config.runs_dir / run_id
    review, state = _read(run_dir / "editorial-review.json"), _read(run_dir / "run-state.json")
    dossier = _read(run_dir / "research-dossier.json")
    draft = p.last_draft or _read(run_dir / "master-draft.json")      # empty last_draft: the run was resumed
    by_number = {sc.get("scene_number"): sc for sc in draft.get("scenes") or [] if isinstance(sc, dict)}
    shooting, scenes = [], []
    for scene in script.get("scenes") or []:
        mine = by_number.get(scene.get("scene_number"), {})
        src = scene if scene.get("beats") else mine
        shot = {k: src[k] for k in ("entry_frame", "exit_frame", "transition_to_next", "directions", "beats") if src.get(k)}
        if shot.get("beats"):
            shot["beats"] = align_beats(str(scene.get("narration") or ""), shot["beats"])
        if shot:
            shooting.append({"scene_number": scene.get("scene_number"), **shot})
        voice = scene.get("voice_direction") or mine.get("voice_direction")      # the editor may leave it out
        scenes.append({**scene, "voice_direction": voice} if voice else scene)
    script = {**script, "scenes": scenes}
    bible = script.get("continuity_bible") or draft.get("continuity_bible") or {}
    spoken = [b for shot in shooting for b in shot.get("beats") or [] if str(b.get("narration") or "").strip()]
    voice_missing = [what for what, missing in (
        ("the narrator", not bible.get("voice")),
        ("voice direction for a scene", any(not sc.get("voice_direction") for sc in scenes)),
        ("the delivery of a spoken line", any(not str(b.get("delivery") or "").strip() for b in spoken))) if missing]

    words = sum(len(str(sc.get("narration") or "").split()) for sc in script.get("scenes") or [])
    script = {**script, "total_word_count": words, "target_duration_seconds": request["target_duration_seconds"],
              "estimated_duration_seconds": script.get("actual_duration_seconds") or request["target_duration_seconds"]}
    gate = lambda v: {k: v[k] for k in ("verdict", "reason", "regenerated", "critical", "important") if k in (v or {})}  # noqa: E731
    result = brand.scrub({
        "final_script": script,
        "continuity_bible": bible,
        "shooting": shooting,
        "qa_summary": review.get("qa_summary") or {},
        "issues": [i for i in review.get("issues_detected") or [] if i.get("severity") != "PASS"][:12],
        "approval_brief": review.get("approval_brief") or {},
        "research": {"core_insight": dossier.get("core_insight"), "angle": dossier.get("recommended_angle"),
                     "claims": (dossier.get("claim_ledger") or {}).get("approved_claims") or []},
        "gates": {"hook": gate(state.get("diversity")), "production": gate(state.get("continuity")),
                  "voice": {"verdict": "WARN" if voice_missing else "PASS",
                            "reason": ("Missing: " + ", ".join(voice_missing)) if voice_missing else ""},
                  "untraced_figures": _untraced_figures(script, dossier, p.config.knowledge_dir),
                  "notes": notes_for(script)},
        "engine": {"name": NAME, "model": p.config.model_name, "run_id": run_id, "agents": 3,
                   "revised_for_brand": revised_by == "brand check", "revised_by": revised_by,
                   "revisions_left": max(0, state.get("max_revisions_allowed", 1) - state.get("revision_count", 0)),
                   "seconds": round(time.time() - began),
                   "tokens": (state.get("metrics") or {}).get("total_tokens_estimated"),
                   "state": state.get("current_state")},
    })
    _write_directed(run_dir, result)
    return result


def _write_directed(run_dir: Path, payload: dict) -> None:
    """directed-script.json: the script exactly as the dashboard shows it, for the production phases to read."""
    script = payload.get("final_script") or {}
    shots = {s.get("scene_number"): s for s in payload.get("shooting") or []}
    scenes = [{**scene, **{k: v for k, v in (shots.get(scene.get("scene_number")) or {}).items() if k != "scene_number"}}
              for scene in script.get("scenes") or []]
    directed = {"title": script.get("title"), "format": script.get("format"),
                "target_duration_seconds": script.get("target_duration_seconds"), "hook": script.get("hook") or {},
                "continuity_bible": payload.get("continuity_bible") or {}, "scenes": scenes,
                "call_to_action": script.get("call_to_action") or {}}
    (run_dir / "directed-script.json").write_text(json.dumps(directed, indent=2, ensure_ascii=False), encoding="utf-8")


async def write(video_id: int, idea: dict, team_knowledge: str, on_stage) -> dict:
    """Run the three script agents and the rule gates for one idea. Takes four to seven minutes on the free model."""
    if not available():
        raise RuntimeError("No OpenRouter key is saved for the script engine.")
    draft = idea.get("payload") or {}
    kind = video_types.get(draft.get("video_type"))
    run_id = f"run_{datetime.now():%Y%m%d_%H%M%S}_v{video_id}"
    cfg = _config(run_id)
    await asyncio.to_thread(_write_knowledge, cfg.knowledge_dir, team_knowledge)
    request = {
        "request_id": f"REQ-VIDEO-{video_id}",
        "topic": str(idea["title"]).strip().ljust(5, "."),
        "primary_objective": (str(idea.get("summary") or "").strip() or f"Show why {idea['title']} matters for a family home")[:600],
        "format": "short-form", "target_duration_seconds": int(kind.get("length_seconds") or SECONDS), "target_audience": AUDIENCE,
        "platform": "instagram_reels", "featured_product_category": PRODUCT,
        "video_type": kind["key"],
        "video_type_brief": brand.clean(video_types.brief(kind))[:2500],
        "custom_instructions": brand.clean(
            f"Why this idea fits MAGPPIE: {idea.get('angle') or ''}\nSuggested hook: {draft.get('hook', '')}\n"
            f"Suggested beats: {draft.get('beats', '')}\nVertical 9:16 reel. End on the company's call to action.\n"
            "Never name a colour or a finish of the stone in the voice-over: say that it comes back clean.\n\n"
            f"{brand.RULES}")[:3000],
    }
    return await _watched(run_id, on_stage, _run, run_id, request)


async def revise(run_id: str, asked_by: str, feedback: str, on_stage) -> dict:
    """Ask the engine to change the script once, as the manager asked."""
    return await _watched(run_id, on_stage, _revise, run_id, asked_by, feedback)


async def _watched(run_id: str, on_stage, work, *args):
    """Run engine work off the main loop, passing each new stage of the run to the dashboard."""
    state_file = _config(run_id).runs_dir / run_id / "run-state.json"
    task = asyncio.create_task(asyncio.to_thread(work, *args))
    seen = None
    while not task.done():
        await asyncio.sleep(3)
        state = _read(state_file).get("current_state")
        if state != seen and state in STAGES:
            seen = state
            await on_stage(STAGES[state])
    return await task


def _state(run_id: str) -> dict:
    return _read(_config(run_id).runs_dir / run_id / "run-state.json")


def _lock(run_id: str, approved_by: str, payload: dict) -> str:
    """The manager approved the script on the dashboard: the engine locks it and returns its fingerprint."""
    p = _pipeline(run_id)
    run_dir = p.config.runs_dir / run_id
    _write_directed(run_dir, payload)
    if _state(run_id).get("current_state") == "HUMAN_APPROVAL_REQUIRED":
        p.apply_approval_decision(run_id, "APPROVE", approved_by or "Manager", "Approved on the MAGI dashboard.")
    return _read(run_dir / "approval.json").get("script_hash", "")


async def lock(run_id: str, approved_by: str, payload: dict) -> str:
    return await asyncio.to_thread(_lock, run_id, approved_by, payload)


def _phase(run_id: str, loop, work) -> tuple[dict, str]:
    """One production phase on the engine's model; if OpenRouter cannot answer, once more on the backup brains."""
    p = _pipeline(run_id)
    try:
        return work(p), p.config.model_name
    except ValueError:
        raise                                   # a state rule: the phase may not run now, on any brain
    except Exception as e:  # noqa: BLE001
        log.warning("%s: the engine's model could not finish (%s); trying the backup brains", run_id, str(e)[:200])
        p.client = BackupClient(loop)
        return work(p), "backup brains"


def _lookbook_card(run_id: str, lookbook: dict, state: dict, made_by: str) -> dict:
    """What the dashboard keeps about a lookbook. The lookbook itself is served from the engine's own file."""
    overview, book = lookbook.get("film_overview") or {}, state.get("lookbook") or {}
    notes = [str(i) for i in lookbook.get("open_issues") or [] if str(i).strip()]
    notes += [f["description"] for f in (book.get("gate") or {}).get("findings") or []]
    return {"version": lookbook.get("version"), "status": book.get("status"), "hash": book.get("hash"),
            "approved_hash": book.get("approved_hash"), "decided_by": book.get("decided_by"),
            "one_line_story": overview.get("one_line_story"), "mood_words": overview.get("mood_words") or [],
            "palette": overview.get("colour_palette") or [], "keyframes": 3 * len(lookbook.get("scenes") or []),
            "changes_left": max(0, state.get("max_revisions_allowed", 1) - int(book.get("revision_count") or 0)),
            "notes": notes[:8], "made_by": made_by}


async def lookbook(run_id: str, on_stage) -> dict:
    """Agent 4: the lookbook for a locked script. Ends waiting for the manager's approval."""
    loop = asyncio.get_running_loop()

    def work() -> dict:
        result, made_by = _phase(run_id, loop, lambda p: p.run_lookbook_phase(run_id))
        return _lookbook_card(run_id, result["lookbook"], result["state"], made_by)
    return await _watched(run_id, on_stage, work)


async def decide_lookbook(run_id: str, decision: str, decided_by: str, feedback: str, on_stage) -> dict:
    """The manager's decision on the lookbook. Approve: its exact content is fingerprinted. Changes: agent 4 redraws it."""
    loop = asyncio.get_running_loop()

    def work() -> dict:
        if decision == "APPROVE" and _state(run_id).get("current_state") in ("LOOKBOOK_APPROVED", "VIDEO_PROMPTS_DRAFTING"):
            state = _state(run_id)                       # already approved (a restart came in between)
            return _lookbook_card(run_id, _read(_config(run_id).runs_dir / run_id / "lookbook.json"), state, "")
        if decision == "APPROVE":
            result = _pipeline(run_id).apply_lookbook_decision(run_id, "APPROVE", decided_by or "Manager", feedback)
            return _lookbook_card(run_id, result["lookbook"], result["state"], "")
        result, made_by = _phase(run_id, loop, lambda p: p.apply_lookbook_decision(
            run_id, "REQUEST_CHANGES", decided_by or "Manager", feedback))
        return _lookbook_card(run_id, result["lookbook"], result["state"], made_by)
    return await _watched(run_id, on_stage, work)


HIGGSFIELD_LIMIT = 3500      # characters; one prompt, as the team's own prompts were sent


def higgsfield_prompt(prompt: dict) -> str:
    """One scene prompt for the video model, inside its length limit. The Continuity Bible is never shortened;
    what gives way first is what the edit adds anyway."""
    start, end, audio, vo = prompt["start_frame"], prompt["exit_frame"], prompt["audio"], prompt["vo"]
    said = " ".join(f'[{l["time_range"]}] "{l["line"]}"' + (f' ({l["delivery"]})' if l.get("delivery") else "")
                    for l in vo["lines"])
    blocks = [                                     # (keep while it fits, text)
        (0, prompt["continuity_bible"]),
        (0, f"START FRAME: {start['entry_frame']}"),
        (3, start["starting_visual_state"]),
        (0, "ACTION: " + " ".join(f"[{b['time_range']}] {b['action']}" for b in prompt["beats"])),
        (0, f"CAMERA: {prompt['shot']}. Lens: {prompt['lens']}. {prompt['movement']}"),
        (1, f"VOICE-OVER ({vo['narrator']}): {said} Spoken like a person talking, with natural breaths and pauses, never like an announcer."),
        (4, f"SOUND: {audio['ambient_sound']}. Music: {audio['music']}. {audio['sound_effects']}."),
        (2, "REALISM: " + "; ".join(prompt["realism_cues"]) + "."),
        (0, f"END FRAME: {end['exit_frame']}"),
        (3, end["ending_visual_state"]),
        (0, "No text, titles, captions or logos inside the frame."),
        (0, f"Avoid: {prompt['negative_prompt']}"),
    ]
    for drop in (9, 4, 3, 2, 1):                   # 9: nothing dropped yet
        text = "\n".join(b for rank, b in blocks if rank < drop and b.strip())
        if len(text) <= HIGGSFIELD_LIMIT:
            return text
    return text[:HIGGSFIELD_LIMIT].rsplit(". ", 1)[0] + "."


async def video_prompts(run_id: str, on_stage) -> dict:
    """Agent 5: the video prompts and the Edit Sheet, against the approved lookbook. Ends the production package."""
    loop = asyncio.get_running_loop()

    def work() -> dict:
        result, made_by = _phase(run_id, loop, lambda p: p.run_video_prompt_phase(run_id))
        package, run_dir = result["video_prompts"], _config(run_id).runs_dir / run_id
        gate = (result["state"].get("production") or {}).get("gate") or {}
        return {"scene_prompts": [{"scene_number": s["scene_number"], "time_range": s["time_range"],
                                   "prompt_text": s["prompt_text"]} for s in package["scene_prompts"]],
                "edit_sheet_md": (run_dir / "edit-sheet.md").read_text(encoding="utf-8"),
                "script_hash": package["script_hash"], "lookbook_hash": package["lookbook_hash"],
                "aspect_ratio": package["platform_settings"]["aspect_ratio"],
                "gate": {k: gate[k] for k in ("verdict", "critical", "important", "regenerated") if k in gate},
                "higgsfield_prompt": higgsfield_prompt(package["scene_prompts"][0]), "made_by": made_by,
                "state": result["status"]}
    return await _watched(run_id, on_stage, work)


FILES = {"lookbook.html": "text/html", "lookbook.json": "application/json", "video-prompts.json": "application/json",
         "video-prompts.md": "text/markdown", "edit-sheet.md": "text/markdown"}


def artifact(run_id: str, name: str) -> Path | None:
    """One of the engine's production files for a run, if it exists."""
    path = _config(run_id).runs_dir / Path(run_id).name / name
    return path if name in FILES and path.exists() else None
