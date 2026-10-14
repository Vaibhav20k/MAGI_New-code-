"""Agent 10 — Video.

Step 1 (script): the Magppie Content Intelligence Engine (see app/script_engine.py) on OpenRouter's Nemotron:
  agent 1  gathers the evidence and the angles this video may use,
  agent 2  writes and directs the shooting script: continuity bible, ten directions, five timed beats,
  gates    check that the hook is new and that the timing, beats and frames add up,
  agent 3  edits it and checks every claim against the evidence and the brand.
If the engine cannot finish (its free model is limited per day), the backup writer below writes the script
on the other brains, and the card says so.

Step 2 (lookbook): approving the script locks it, and agent 4, the lookbook director, shows what the film
should look like: palette, continuity cards, three keyframes for every scene, the product moment, the sound.

Step 3 (video prompts): approving the lookbook fingerprints it, and agent 5, the video prompt engineer, writes
the prompt for every scene and the Edit Sheet. That completes the production package.

Step 4 (video): Higgsfield renders the scene from agent 5's prompt. Runs only after a price is chosen.

A script from the backup writer has no engine run behind it, so it keeps the short road: one prompt in the
house style of the team's earlier prompts, written by the other brains.
"""

import json
import logging

from .. import brand, db, inputs, kb, kitchens, llm, media, script_engine, video_types
from ..config import get_settings

log = logging.getLogger("mai.video")
WORDS_PER_SECOND = 2.3

RESEARCH = """You are the research step of a video team for the company described in COMPANY KNOWLEDGE.
For the IDEA, choose what this short video may say. Use COMPANY KNOWLEDGE only.
Return JSON: {"angle": "the one idea of the video, in a sentence",
"facts": [{"fact": "a fact the script may state, in plain words", "kb": <the KB number it comes from>}],
"hooks": ["three different opening lines for the first 3 seconds"],
"proof": "what the viewer can see or test for themselves"}
Give 4 to 7 facts. Nothing that is not in COMPANY KNOWLEDGE."""

WRITER = """You are the script writer for the company described in COMPANY KNOWLEDGE.
Write one short-form vertical video script (reel or short) for the IDEA, about %d seconds long.

Rules:
- State only the FACTS given. Add no other product fact, number, award or claim.
- Follow the BRAND RULES and the brand voice: short declarative sentences, vision first, then proof.
  Show, do not tell: the pictures carry the proof.
- The first scene is the hook: it must stop the scroll in 3 seconds.
- Narration is spoken aloud: about %d words in total, no more.
- 4 to 6 scenes. Every scene has what is seen (camera, light, material, action) and what is said.
- On-screen text: a few words at most, or empty.
- The voice must sound like a person talking, never text read out: one breath per line, plain spoken words, a
  longer line then a short one. Every scene has a voice direction: tone (something you can hear, not a label
  like "warm"), pace, where the pauses fall, and the words that carry the stress.
- End with the company's call to action.

Return JSON: {"title": "...", "hook": {"hook_text": "..."},
"scenes": [{"scene_number": 1, "time_range": "0-3s", "narration": "...", "visual_direction": "...", "on_screen_text": "...",
"voice_direction": {"tone": "...", "pace": "...", "pauses": "...", "emphasis": "..."}}],
"call_to_action": {"cta_text": "..."}, "music_mood": "...", "target_duration_seconds": %d}"""

EDITOR = """You are the editor of a video team for the company described in COMPANY KNOWLEDGE.
Check the SCRIPT line by line and return the corrected script.
- Remove or rewrite any line that states something COMPANY KNOWLEDGE does not say.
- Remove or rewrite anything that breaks the BRAND RULES.
- Keep the narration to about %d words in total so it fits %d seconds. Cut, do not pad.
- Keep the same JSON shape. Add "changes": a short list of what you changed and why (empty if nothing)."""


def _words(script: dict) -> int:
    return sum(len(str(x.get("narration") or "").split()) for x in script.get("scenes") or [])


async def _stage(video_id: int, text: str) -> None:
    await db.execute("update videos set script = script || %s where id = %s", db.Jsonb({"stage": text}), video_id)


def _why(e: Exception) -> str:
    """An engine error in words for the card."""
    text = str(e)
    if "429" in text or "rate limit" in text.lower():
        return "The free AI limit for today is used up on every brain. Try again later."
    return text[:500]


def _seedance(seconds: int) -> dict:
    """Seedance settings the team has used for a clip of this length."""
    if seconds > 12:
        return {"aspect_ratio": "9:16", "duration": 30 if seconds > 20 else 15, "resolution": "480p"}
    return {"aspect_ratio": "9:16", "duration": 10 if seconds > 8 else 8, "resolution": "720p"}


async def write_script(idea_id: int) -> int:
    """Create the video row and write the script for this idea."""
    idea = await db.fetchrow("select * from ideas where id = %s", idea_id)
    if not (idea["payload"] or {}).get("kitchen"):     # approved without a choice (e.g. by MAGI): the best kitchen
        best = await kitchens.options(f"{idea['title']}. {idea['summary'] or ''}", n=1)
        if best:
            idea["payload"] = {**(idea["payload"] or {}), "kitchen": best[0]}
            await db.execute("update ideas set payload = coalesce(payload, '{}'::jsonb) || %s where id = %s",
                             db.Jsonb({"kitchen": best[0]}), idea_id)
    row = await db.fetchrow("insert into videos (idea_id, script, status, started_at) values (%s,%s,'writing',now()) "
                            "returning id", idea_id, db.Jsonb({"stage": "Starting the script engine"}))
    video_id = row["id"]
    try:
        try:
            team = await kb.search(f"{idea['title']}. {idea['summary']}", k=5, docs=["manager"])
            payload = await script_engine.write(video_id, idea, "\n\n".join(r["content"] for r in team),
                                                lambda text: _stage(video_id, text))
        except Exception as e:  # noqa: BLE001 — the free model is limited per day: the backup writer takes over
            log.warning("script engine could not finish idea %s (%s); the backup writer takes over", idea_id, e)
            await _stage(video_id, "Backup writer · the script engine could not finish")
            payload = await _backup_script(idea)
            payload["engine"] = {"name": "Backup writer", "why": str(e)[:300]}
        await db.execute("update videos set script = %s, status = 'script_ready' where id = %s",
                         db.Jsonb(payload), video_id)
    except Exception as e:  # noqa: BLE001
        log.exception("script for idea %s failed", idea_id)
        await db.execute("update videos set status = 'failed', error = %s where id = %s", str(e)[:600], video_id)
        raise
    return video_id


async def _backup_script(idea: dict) -> dict:
    """Three passes on the other brains: research, writer, editor. Used only when the engine cannot finish."""
    idea_id, draft = idea["id"], idea["payload"] or {}
    kb_rows = await kb.search(f"{idea['title']}. {idea['summary']}", k=12,
                              docs=["core", "brand", "manager", "learned"])
    knowledge = f"COMPANY KNOWLEDGE:\n{kb.as_context(kb_rows)}"
    try:
        seconds = max(15, min(int(draft.get("length_seconds") or 30), 60))
    except (TypeError, ValueError):
        seconds = 30
    words = int(seconds * WORDS_PER_SECOND)
    idea_text = (f"IDEA:\nTitle: {idea['title']}\nSummary: {idea['summary']}\nWhy it fits us: {idea['angle']}\n"
                 f"Suggested hook: {draft.get('hook', '')}\nSuggested beats: {draft.get('beats', '')}\n\n"
                 f"{video_types.brief(video_types.get(draft.get('video_type')))}"
                 + (f"\n\n{kitchens.as_brief(draft['kitchen'])}" if draft.get("kitchen") else ""))

    research = brand.scrub(await llm.chat_json(RESEARCH, f"{idea_text}\n\n{knowledge}", temperature=0.4))
    facts = "\n".join(f"- {f.get('fact')}" for f in research.get("facts") or [] if f.get("fact"))
    if not facts:
        raise RuntimeError("The research step found no facts for this idea in the knowledge base.")
    brief = (f"{idea_text}\n\nANGLE: {research.get('angle', '')}\nFACTS (the only facts you may state):\n{facts}\n"
             f"HOOK OPTIONS: {research.get('hooks', '')}\nPROOF TO SHOW: {research.get('proof', '')}\n\n"
             f"{brand.RULES}\n\nBRAND GUIDE:\n{inputs.brand_guide()[:4000]}")
    script = brand.scrub(await llm.chat_json(WRITER % (seconds, words, seconds), brief, temperature=0.8))

    changes: list = []
    for _ in range(3):                     # the editor reads it; a script that still breaks a rule goes back
        edited = brand.scrub(await llm.chat_json(
            EDITOR % (words, seconds),
            f"SCRIPT:\n{json.dumps(script, ensure_ascii=False)}\n\n{brand.RULES}\n\n{knowledge}", temperature=0.2))
        if edited.get("scenes"):
            changes += [c for c in edited.pop("changes", []) or [] if isinstance(c, str)]
            script = edited
        broken = brand.violations(script)
        if not broken:
            break
        log.warning("script for idea %s broke brand rules: %s", idea_id, broken)
        script["editor_note"] = "Rewrite to remove: " + "; ".join(broken)
    else:
        raise RuntimeError("The script kept breaking the brand rules: " + "; ".join(broken))
    script.pop("editor_note", None)
    if not script.get("scenes") or not (script.get("hook") or {}).get("hook_text"):
        raise RuntimeError("The script came back incomplete.")
    count = _words(script)
    script.update(total_word_count=count, estimated_duration_seconds=round(count / WORDS_PER_SECOND),
                  target_duration_seconds=seconds)
    return {"final_script": script, "changes": changes[:12], "research": research,
            "kb": [{"id": r["id"], "section": r["section"]} for r in kb_rows[:8]]}


DIRECTOR = """You are the video prompt writer for MAGPPIE. Turn the approved SCRIPT into ONE prompt
for a text-to-video model (Seedance 2.5 on Higgsfield).

Follow the house style of the EXAMPLE PROMPTS, which the team wrote and used before: the way they open,
their level of detail, their material and brand rules. Keep every fact and every spoken line of the script
exactly as approved; do not add claims.

The prompt must give: format and length, the look (lighting, lenses, colour, materials), then the scenes in
order with timing, what is seen, camera movement, and the narration line for that scene. When SHOOTING
DIRECTIONS are given, they are the director's own: repeat the continuity bible lines word for word, follow the
timed beats in order, open on the entry frame and close on the exit frame. The SCRIPT's narration is the
approved wording: where a beat's line differs from it, the SCRIPT wins.

The voice-over must sound like a person talking, never text being read. Describe the narrator once (from the
continuity bible when it gives one). After each narration line, give in brackets how it is said, from the
script's voice direction and delivery notes: the pace, the breath or pause, the stressed word, pitch rising or
falling. Uneven, natural rhythm, audible breaths, close to the microphone. Never an announcer or advert voice,
never the same pitch and speed on every line.

It must look shot, not generated: natural skin texture, real physics, light that comes from a source in the
scene, subtle handheld or gimbal movement, real lenses. No text, captions, titles or logos inside the frames:
the on-screen text is added in the edit. No people's faces in close-up unless the script calls for them. Every
kitchen, cabinet, door and surface shown is stone (SILVERSTONE engineered stone): no wood and no steel
cabinets anywhere. End the prompt with the line "Avoid:" followed by this list exactly:
%s

Return JSON: {"prompt": "the full prompt, under 3500 characters", "title": "..."}"""

# Rule 2.5 of the Magppie Video Production Rules (backend/script_engine/SKILL.md)
AVOID = ("plastic skin, waxy face, airbrushed, over-smoothed, uncanny valley, dead eyes, extra fingers, deformed hands, "
         "merged objects, morphing faces, warped geometry, floating objects, inconsistent shadows, impossible reflections, "
         "over-saturated colours, HDR glow, perfect symmetry, CGI look, video-game render, stock-photo pose, generated text, "
         "gibberish lettering, watermark, sudden identity change, flickering, jittery motion, slow-motion overuse")


async def direct(video_id: int) -> dict:
    """The short road, for a script from the backup writer: one Higgsfield prompt from the other brains."""
    v = await db.fetchrow("select * from videos where id = %s", video_id)
    script = v["script"]["final_script"]
    bank = json.loads((get_settings().inputs_dir / "prompt-bank.json").read_text()) \
        if (get_settings().inputs_dir / "prompt-bank.json").exists() else {"items": []}
    examples = [i for i in bank["items"] if i["type"] == "video"][:3]
    seconds = int(script.get("target_duration_seconds") or script.get("estimated_duration_seconds") or 30)
    shooting = {k: v["script"][k] for k in ("continuity_bible", "shooting") if v["script"].get(k)}
    system = DIRECTOR % AVOID
    user = ("EXAMPLE PROMPTS:\n" + "\n---\n".join(e["prompt"][:1800] for e in examples) +
            f"\n\n{brand.RULES}\n\nBRAND GUIDE:\n{inputs.brand_guide()[:3000]}\n\n"
            f"SCRIPT:\n{json.dumps(script, ensure_ascii=False)[:7000]}" +
            (f"\n\nSHOOTING DIRECTIONS:\n{json.dumps(shooting, ensure_ascii=False)[:6000]}" if shooting else ""))
    data = await llm.chat_json(system, user, temperature=0.5)
    plan = {"prompt": brand.clean(data.get("prompt") or "")[:3500], "model": "seedance_2_5", **_seedance(seconds)}
    if len(plan["prompt"]) < 200:
        raise RuntimeError("The director returned no usable prompt.")
    await db.execute("update videos set script = script || %s where id = %s",
                     db.Jsonb({"higgsfield": plan}), video_id)
    return plan


async def revise_script(video_id: int, feedback: str) -> bool:
    """The manager asked for changes: the engine rewrites the script once (agent 2, then agent 3)."""
    v = await db.fetchrow("select script from videos where id = %s", video_id)
    before = v["script"]
    try:
        payload = await script_engine.revise(before["engine"]["run_id"], get_settings().manager_name, feedback,
                                             lambda text: _stage(video_id, text))
        payload["asked"] = feedback[:600]
        await db.execute("update videos set script = %s, status = 'script_ready', error = null where id = %s",
                         db.Jsonb(payload), video_id)
        return True
    except Exception as e:  # noqa: BLE001 — the script the manager already has stays as it was
        log.exception("revising the script of video %s failed", video_id)
        await db.execute("update videos set script = %s, status = 'script_ready', error = %s where id = %s",
                         db.Jsonb({k: x for k, x in before.items() if k != "stage"}),
                         "The script could not be changed: " + _why(e), video_id)
        return False


async def make_lookbook(video_id: int) -> bool:
    """The manager approved the script: it is locked, and agent 4 draws up the lookbook for approval."""
    v = await db.fetchrow("select script from videos where id = %s", video_id)
    engine = dict(v["script"]["engine"])
    try:
        engine["locked"] = await script_engine.lock(engine["run_id"], get_settings().manager_name, v["script"])
        engine["state"] = "SCRIPT_LOCKED"
        await db.execute("update videos set script = script || %s where id = %s", db.Jsonb({"engine": engine}), video_id)
        card = await script_engine.lookbook(engine["run_id"], lambda text: _stage(video_id, text))
        await db.execute("update videos set script = (script - 'stage') || %s, status = 'lookbook_ready', error = null "
                         "where id = %s", db.Jsonb({"lookbook": card}), video_id)
        return True
    except Exception as e:  # noqa: BLE001 — back to the approved script, so the lookbook can be asked for again
        log.exception("the lookbook for video %s failed", video_id)
        await db.execute("update videos set script = script - 'stage', status = 'script_ready', error = %s where id = %s",
                         "The lookbook could not be made: " + _why(e), video_id)
        return False


async def decide_lookbook(video_id: int, decision: str, feedback: str = "") -> bool:
    """The manager's decision on the lookbook. Approved: agent 5 writes the video prompts and the Edit Sheet.
    Changes asked: agent 4 draws it up again, once."""
    v = await db.fetchrow("select script from videos where id = %s", video_id)
    run_id, stage = v["script"]["engine"]["run_id"], lambda text: _stage(video_id, text)
    try:
        card = await script_engine.decide_lookbook(run_id, decision, get_settings().manager_name, feedback, stage)
        card["made_by"] = card["made_by"] or (v["script"].get("lookbook") or {}).get("made_by", "")
        await db.execute("update videos set script = script || %s where id = %s", db.Jsonb({"lookbook": card}), video_id)
        if decision != "APPROVE":
            await db.execute("update videos set script = script - 'stage', status = 'lookbook_ready', error = null "
                             "where id = %s", video_id)
            return True
        kitchen = await db.fetchrow("select i.payload->'kitchen' k from videos v join ideas i on i.id = v.idea_id "
                                    "where v.id = %s", video_id)
        if kitchen and isinstance(kitchen["k"], dict):
            await kitchens.record(video_id, kitchen["k"])     # the next video chooses a different kitchen
        package = await script_engine.video_prompts(run_id, stage)
        seconds = int(v["script"]["final_script"].get("target_duration_seconds") or 30)
        plan = {"prompt": package.pop("higgsfield_prompt"), "model": "seedance_2_5",
                **_seedance(seconds), "aspect_ratio": package["aspect_ratio"]}
        await db.execute("update videos set script = (script - 'stage') || %s, status = 'package_ready', error = null "
                         "where id = %s", db.Jsonb({"package": package, "higgsfield": plan}), video_id)
        return True
    except Exception as e:  # noqa: BLE001 — back to the lookbook, which stays as it is
        log.exception("the lookbook step of video %s failed", video_id)
        what = "The video prompts could not be written: " if decision == "APPROVE" else "The lookbook could not be changed: "
        await db.execute("update videos set script = script - 'stage', status = 'lookbook_ready', error = %s where id = %s",
                         what + _why(e), video_id)
        return False


async def generate(video_id: int) -> bool:
    """Render the video on Higgsfield and save it for the dashboard. Spends Higgsfield credits."""
    try:
        await db.execute("update videos set status = 'generating', error = null, started_at = now() where id = %s",
                         video_id)
        v = await db.fetchrow("select script from videos where id = %s", video_id)
        plan = (v["script"] or {}).get("higgsfield") or await direct(video_id)
        urls, job_ids, remote = await media.generate("video", plan)
        await db.execute("update videos set video_urls = %s::text[] || video_urls, remote_urls = %s::text[] || remote_urls, "
                         "job_ids = %s::text[] || job_ids, status = 'ready' where id = %s",
                         urls, remote, job_ids, video_id)
        return True
    except Exception as e:  # noqa: BLE001
        log.exception("video %s failed", video_id)
        await db.execute("update videos set status = 'failed', error = %s where id = %s", str(e)[:600], video_id)
        return False
