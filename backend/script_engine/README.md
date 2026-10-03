# Magppie Content Intelligence Engine (as it runs inside MAGI)

The engine handed over as `magppie-handover-v2.zip`, with its old company story removed and agents 4 and 5
built from the "Agents 4 & 5 Implementation Master Prompt". `backend/app/script_engine.py` is the bridge to
the MAGI dashboard; this folder is the engine itself.

## The pipeline that exists

```text
Agent 1  Evidence and Intelligence
  → Agent 2  Director-Writer
  → Diversity Gate → Continuity Gate
  → Agent 3  Executive Editor
  → Human script approval            HUMAN_APPROVAL_REQUIRED → SCRIPT_LOCKED (comes to rest on MVP_COMPLETE)
  → Agent 4  Lookbook Director       LOOKBOOK_DRAFTING → LOOKBOOK_APPROVAL_REQUIRED
  → Human lookbook approval          LOOKBOOK_APPROVED (bound to the lookbook's SHA-256)
  → Agent 5  Video Prompt Engineer   VIDEO_PROMPTS_DRAFTING → PRODUCTION_PACKAGE_COMPLETE
```

Four artifacts, kept apart: the script (what happens and what is said), the lookbook (what it should look
like), the video prompts (what the video model is told), the Edit Sheet (how the clips are assembled).

## Where things are

| Part | File |
|---|---|
| Rulebook (Rules 1 to 6, Phase 3 format) | `SKILL.md` |
| Agent prompts | `agents/` (`lookbook-director.md`, `video-prompt-engineer.md` are agents 4 and 5) |
| Phases and agents | `workflows/content_pipeline.py`: `run_pipeline`, `apply_approval_decision`, `run_lookbook_phase`, `apply_lookbook_decision`, `run_video_prompt_phase` |
| What code does without a model | `workflows/production.py`: the directed script, the exact parts of a prompt, both production gates, the HTML and Markdown |
| Lookbook approval and hashing | `workflows/approval_manager.py`: `process_lookbook_decision` |
| Formats | `schemas/lookbook.schema.json`, `video-prompts.schema.json`, `lookbook-approval.schema.json`, `run-state.schema.json` |
| Tests (no key needed) | `tests/test_production_phases.py` |

## Rules the code enforces, not the model

- No lookbook before a person locks the script; no video prompt before a person approves the lookbook.
- An approval holds only for the exact lookbook approved. A changed lookbook goes back for approval.
- One request for changes per lookbook, then approve (the script phase's own limit, reused).
- A lookbook inherits the script's scenes; the next scene's entry keyframe is the previous exit keyframe.
- In every scene prompt: the Continuity Bible word for word, Rule 2.5's negative prompt exactly, the locked
  voice-over, the locked entry and exit frames, the locked beat timings. Agent 5 writes none of them.
- On-screen text is an instruction for the editor. A frame that asks for lettering is rejected.
- Generate, validate, one corrective regeneration, then the failure is shown. Nothing invalid is saved as approved.

## Files of one run (`runs/<run-id>/`)

`request.json`, `research-dossier.json`, `master-draft.json`, `editorial-review.json`, `approval.json`,
`locked-script.md`, `directed-script.json`, `lookbook.json`, `lookbook.html`, `lookbook-v<n>.json` (a version
that was sent back), `lookbook-approval.json`, `video-prompts.json`, `video-prompts.md`, `edit-sheet.md`.

## Not carried over from the zip

Its own dashboard, CLI, benchmark and steel-era knowledge and documents. The MAGI dashboard does that work,
and the knowledge is written for every run from `inputs/company-kb.md`, `brand-guide.md` and `approved-claims.md`.
