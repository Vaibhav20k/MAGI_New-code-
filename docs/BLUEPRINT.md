# MAGI: full project blueprint

MAGI is MAGPPIE's marketing "second brain". It reads the web at night, keeps a company knowledge base, proposes
ideas every day and, after a person approves them, writes blogs, makes social creatives and directs videos. Everything
runs in Docker on one machine. AI work runs on **free tiers only**: anything that spends money (Higgsfield) runs only
after a click that shows the price.

> Written 17 Oct 2026 from the code on branch `Vaibhav_AGENT_changes`. Key **names** only: no key values appear
> here, and none belong in any committed file. Real keys live in `.env` (git-ignored) and `data/keys.json`.

---

## 1. Run it

| What | Where |
|---|---|
| Start | Open Docker Desktop, then `docker compose up -d` in `MAGI/` (Cognee add-on: `docker compose -f docker-compose.yml -f docker-compose.cognee.yml up -d cognee`) |
| After Python changes | `docker compose build backend && docker compose up -d --no-deps --force-recreate backend` |
| After a new migration | `docker compose exec -T db psql -v ON_ERROR_STOP=1 -U postgres -d postgres -q < supabase/migrations/<file>.sql` |
| After editing knowledge files | `POST /api/kb/reload` |
| MAGI home (3D office) | http://localhost:8000/ (or http://127.0.0.1:8000) |
| Marketing dashboard | http://localhost:8000/marketing |
| Tests | `python -m pytest backend/tests backend/script_engine/tests -q` (48 tests, no keys or DB needed) |
| First-time setup | `scripts/setup.sh` (creates `.env`, fills internal secrets) then `scripts/add-keys.sh` (asks for each key, hidden) |

---

## 2. Architecture

```text
 Browser ──► backend :8000 (FastAPI, APScheduler, all agents, both screens, /mcp tools)
               │  ├─► db :5432            Postgres 17 + pgvector (knowledge, learnings, ideas, content, references)
               │  ├─► searxng :8888→8080   private web search
               │  ├─► crawl4ai :11235      headless browser page reader → markdown
               │  ├─► voice (internal 8880) Kokoro text-to-speech, local and free
               │  ├─► hermes :8642         MAGI/MAI chat agent (Hermes) ──► calls back into backend /mcp (18 tools)
               │  └─► cognee :8100         optional knowledge graph (add-on compose file)
               └─► outside: Gemini · Groq · NVIDIA · Token Harbor · OpenRouter · (Cerebras · xAI) · Apify ·
                   Higgsfield (paid, OAuth) · Bloom (context only) · Google Drive (reference library, read-only)
 Public link (parked): Caddy :80/:443 (docker-compose.public.yml) → backend, with password login (auth.py)
```

| Service | Image | Host port | Data | Notes |
|---|---|---|---|---|
| `db` | pgvector/pgvector:pg17 | 127.0.0.1:5432 | volume `db-data` | `services/db/init.sh` creates `cognee_db` and runs all migrations on first start only |
| `searxng` | searxng/searxng | 127.0.0.1:8888 | `services/searxng/settings.yml` | secret `SEARXNG_SECRET` |
| `crawl4ai` | unclecode/crawl4ai | 127.0.0.1:11235 | none | Bearer `CRAWL4AI_API_TOKEN`; robots.txt respected |
| `backend` | build `backend/Dockerfile` (python 3.12, ffmpeg) | 127.0.0.1:8000 | `inputs/` (ro), `backend/static/` (ro), volume `backend-data` → `/app/data` | reads `.env` |
| `voice` | remsky/kokoro-fastapi-cpu | internal only | none | voice `af_heart` |
| `hermes-init` / `hermes` | nousresearch/hermes-agent | 127.0.0.1:8642 | volume `hermes-data` | persona `services/hermes/SOUL.md`, models `services/hermes/config.yaml` |
| `cognee` (add-on) | build `services/cognee` | 127.0.0.1:8100 | volume `cognee-data` | Gemini `gemini-3.1-flash-lite`, 1 call / 10 s |
| `web` (parked) | caddy:2 | 0.0.0.0:80/443 | `services/caddy/Caddyfile` | adds header `X-MAI-Public: 1` |

`/app/data` holds `keys.json` (Gemini key typed on the dashboard), `higgsfield.json` (OAuth tokens), `bloom_skill.json`,
`models/` (embedding model), `media/` (served at `/media`: creatives, references, video files) and `script-engine/runs/`.

---

## 3. The agents

| # | Agent | File | Job | AI tier | Tools / services |
|---|---|---|---|---|---|
| 01 | **MAGI / MAI** (coordinator) | Hermes container; `backend/app/quick.py`, `mcp_server.py`, `main.py /api/mai/chat` | Talks (text and voice), answers from the knowledge base, opens screens, runs any job through 18 MCP tools; asks before producing or spending | quick lane: Gemini lite → Groq → Token Harbor; Hermes: Gemini lite → Token Harbor → OpenRouter | Hermes, Groq Whisper, Kokoro |
| 02 | **Discovery** | `agents/crawler.py discovery_round` | Plans web searches from the knowledge base and `crawler-rules.md` §1 | fast | SearXNG |
| 03 | **Crawler** | `agents/crawler.py run` | Night crawl 20:00 to 08:00 from seed sites outward (depth 3, 3 s per site); YouTube; Instagram and Facebook | none | Crawl4AI, yt-dlp, youtube-transcript-api, Apify |
| 04 | **Filter** | `agents/filter.py` | Keeps a page if it is close to the knowledge base and far from off-topic (local embeddings) | none | fastembed, pgvector |
| 05 | **Knowledge** | `agents/knowledge.py` | Turns kept pages into learnings; sorts them auto / hold (manager) / never; a general claim needs a 2nd source | fast | (Cognee sync at 08:10) |
| 06 | **Adapt** | `agents/ideas.py ADAPT_SYSTEM` | Rewrites outside signals as MAGPPIE ideas, 5 per type, suggests a video type | careful (temp 0.9) | Bloom context |
| 07 | **Strategist** | `agents/ideas.py PICK_SYSTEM` | Scores fit, trend, novelty, feasibility; picks 2 blog + 2 creative + 2 video | careful (temp 0.2) | |
| 08 | **Blog writer** | `agents/blog.py` | 1,200+ word blog with cited [S#] sources | careful, long | SearXNG, Crawl4AI |
| 09 | **Creative / art director** | `agents/creative.py` | Words, caption, hashtags, house-style image prompt; Higgsfield draws; real logo stamped after | careful | Higgsfield (paid), Bloom, Pillow (`brandmark.py`) |
| 10 | **Video** | `agents/video.py` + bridge `backend/app/script_engine.py` | Runs the 5-agent script engine below, then the Higgsfield video | engine on OpenRouter; backup on careful | OpenRouter, Higgsfield (paid) |
| 11 | Feedback loop | `docs/architecture.html` only | Learn from post performance | not built | |

**Video script engine** (`backend/script_engine/`, model `SCRIPT_ENGINE_MODEL` = `nvidia/nemotron-3-super-120b-a12b:free` on OpenRouter):

| Engine agent | Prompt file | Output | Key |
|---|---|---|---|
| 1 Evidence and Intelligence | `agents/research-intelligence.md` | research dossier, claim ledger, 3+ hooks (`research-dossier.json`) | `OPENROUTER_KEY_EVIDENCE` |
| 2 Director-Writer | `agents/master-content-writer.md` | directed script: continuity bible, 30 s scenes, 5 timed beats, entry/exit frames, voice direction | `OPENROUTER_KEY_WRITER` |
| 3 Executive Editor | `agents/executive-editor.md` | edited final script, approval brief, issues (CRITICAL to PASS) | `OPENROUTER_KEY_EDITOR` |
| 4 Lookbook Director | `agents/lookbook-director.md` | lookbook: palette, mood, bible cards, 3 keyframes per scene, product moment, sound | `OPENROUTER_KEY_LOOKBOOK` |
| 5 Video Prompt Engineer | `agents/video-prompt-engineer.md` | one prompt per scene + Edit Sheet (`video-prompts.json/.md`, `edit-sheet.md`) | `OPENROUTER_KEY_VIDEO_PROMPT` |

An empty per-agent key falls back to `OPENROUTER_API_KEY`. Agents 4 and 5 fall back to MAGI's own careful brains if
OpenRouter fails; agents 1 to 3 fall back to MAGI's backup writer (`agents/video.py`) when the free daily quota is gone.

The office on the home screen (`team.py`, `magi.py`) shows 7 people (crawler, filter, knowledge, strategist, blog,
creative, video) who sit and type when **working**, wave when **waiting** for you, and wander when **idle**.

---

## 4. End-to-end flow

```text
 07:30 references.sync (Drive → ref_assets, Gemini vision describes)   08:05 knowledge.housekeeping   08:10 cognee sync
 18:00 review reminder (dashboard notification)                         20:00 night crawl (until 08:00)

 NIGHT  Discovery → crawl_queue → Crawler → Filter → pages(kept) → Knowledge → learnings
                                   (+ YouTube, Instagram/Facebook via Apify)       │ auto → knowledge base (doc learned)
                                                                                    │ hold → APPROVALS tab
 GATE 1  you approve / reject / edit held learnings → FINALISE REVIEW → knowledge base
         (Teach MAGI: add knowledge, never use, block or trust a site)
                                                     ▼
 IDEAS   "Get new ideas" → Adapt (5 per type) → brand check → repeat check (0.86) → Strategist picks 2+2+2
         video ideas get a suggested video type (12 makeable types) and 6 real MAGPPIE kitchens to choose from
 GATE 2  APPROVE (with creative words / video type + kitchen) or SKIP          idea: proposed → finalising → finalised
                                                     ▼
   BLOG: blog.write → blogs row (copy from Content tab)
   CREATIVE: creative.write → brief_ready → [Higgsfield connected] generate → stamp real logo → ready
   VIDEO: script engine A1 → A2 → hook gate + continuity gate → A3 → videos.status script_ready
 GATE 3  APPROVE SCRIPT (locks it, SHA-256) or ASK FOR CHANGES (once)
         → A4 lookbook → lookbook_ready
 GATE 4  APPROVE LOOKBOOK (hash-bound) or REQUEST CHANGES (once) → kitchen use recorded → A5 prompts → package_ready
 GATE 5  SEE PRICE (Higgsfield quote, spends nothing) → pick length → GENERATE (spends credits) → generating → ready
                                                     ▼
 CONTENT tab: download / copy. No auto-posting exists.
```

**Statuses**
- `ideas`: candidate · proposed · finalising · finalised · selected (production failed, can retry) · rejected · discarded.
- `creatives`: writing · brief_ready · generating · ready · failed.
- `videos`: writing · script_ready · lookbook · lookbook_ready · prompting · package_ready · generating · ready · failed.
- `learnings`: pending (waits for 2nd source) · active · held · approved · rejected (also after 14 days) · expired (60 days) · discarded.
- `sources`: seed · discovered · trusted · blocked. `crawl_runs`: running · finished · failed · stopped.
- Engine run states: CONTENT_REQUEST → RESEARCHING → MASTER_DRAFTING → DIVERSITY_CHECK → CONTINUITY_CHECK →
  EDITOR_REVIEWING → HUMAN_APPROVAL_REQUIRED → SCRIPT_LOCKED/MVP_COMPLETE → LOOKBOOK_DRAFTING → LOOKBOOK_APPROVAL_REQUIRED
  → LOOKBOOK_APPROVED → VIDEO_PROMPTS_DRAFTING → PRODUCTION_PACKAGE_COMPLETE (or FAILED, resumable).
- On restart, anything caught mid-way is reset (writing/generating → failed, lookbook → script_ready, prompting → lookbook_ready).

---

## 5. Video production in detail

**Rules** (`backend/script_engine/SKILL.md`, rule log 1.3):
1. Full directions per scene and 5 timed beats (0-5, 5-12, 12-20, 20-27, 27-30 s).
2. Must never look AI-made (behaviour not labels, real light and lenses, no text in frames, fixed negative prompt).
3. One continuous world: exit frame of scene N = entry frame of scene N+1; no hard cuts, wipes or fades (except the end).
4. 30-second scene units; 70 to 75 words of voice-over per scene.
5. Lookbook first; no video without approval.
6. The voice must sound human (one narrator, voice direction per scene, delivery per line).
7. Every video follows its video type (`inputs/video-types.json`).
8. The kitchen is a real MAGPPIE kitchen from the reference library; its finish name and stone colour are never spoken.

**Gates in code**: hook gate (`workflows/diversity_gate.py` + `hook_ledger.py`: no repeated hook wording or banned
angle/opening pair, one retry); continuity gate (`workflows/continuity_gate.py`: timing, beats, frames, words, one retry);
lookbook and package gates (`workflows/production.py`); script and lookbook approvals bound to SHA-256 hashes
(`workflows/approval_manager.py`): an edited lookbook invalidates its approval. Bridge-only checks: voice gate, brand
check (`brand.violations`, one automatic revision), untraced figures, stone colours named in the voice-over.

**Run folder** `/app/data/script-engine/runs/<run_id>/`: request.json, run-state.json, hook-history.json,
research-dossier.json/.md, master-draft.json/.md (+ rejected/revised drafts), editorial-review.json/.md,
final-script.md, approval-brief.txt, approval.json, locked-script.md, directed-script.json, knowledge/ (written per run
from `inputs/`), lookbook.json/.html (+ lookbook-v<n>.json), lookbook-approval.json, video-prompts.json/.md, edit-sheet.md.
Shared: `runs/_memory/hook-ledger.json` (last 40 hooks).

**Add-ons built in Oct 2026 (video upgrade plan, phases 1 to 4)**
| Piece | Files | What it does |
|---|---|---|
| Reference library | `references.py`, `vision.py`, `inputs/reference-library.json`, migration `20261015000000` | Copies the public Drive folder (read-only) into `/media/references`, thumbnails and video stills, Gemini vision describes each picture (finish, layout, flags), search by meaning; References tab to review |
| Real logo | `brandmark.py`, `inputs/logo-black.png`, `creative-styles.json logo_slot` | The image model leaves space; the real logo is stamped after, black or white by brightness |
| Video types | `video_types.py`, `inputs/video-types.json` | 17 types (12 makeable, 5 need real footage); Strategist suggests one with a reason; dropdown on the card; engine Rule 7 |
| Kitchen pick | `kitchens.py` | 6 real kitchens that fit the idea, real and reviewed first, not the last 4 videos' kitchens or finishes; engine Rule 8 |

Not built yet: storyboard frames (phase 5), clips from approved frames (6), automatic assembly with voice-over, text,
logo and end card (7). Higgsfield is the only paid step and its credits are used up, so videos are made by hand in
Google Flow from the engine's per-scene prompts, then joined locally (ffmpeg + Kokoro voice); see `flow-pack/` beside the repo.

---

## 6. AI brains: which model does which task

`backend/app/llm.py` builds two lists of "slots" (provider + model); a slot exists only if its key is set.

| List | Order | Used by |
|---|---|---|
| **careful** | NVIDIA `nemotron-3-ultra-550b-a55b` → Token Harbor `deepseek-v4.1-flash:free`, `qwen3.8-flash:free`, `mimo-v2.6-flash:free` → Gemini `3.8-flash`, `3.7-flash`, `3.6-flash`, `3-flash-preview`, `3.1-flash-lite` → Groq `openai/gpt-oss-120b` → Cerebras → OpenRouter `nemotron-3-super-120b-a12b:free`, `gemma-4-31b-it:free` → xAI | Adapt, Strategist, blog, creative, video backup writer and director, engine agents 4-5 fallback |
| **fast** | Groq `gpt-oss-120b` → NVIDIA `openai/gpt-oss-20b` → `GEMINI_FAST_MODELS` (empty) | Discovery searches, Knowledge learnings, `/api/kb/ask`. Never falls back onto careful, so the crawler can't use up the content brains |
| quick chat lane (`quick.py`) | Gemini `flash-lite-latest` → Gemini `3.1-flash-lite` → Groq → Token Harbor `qwen3.8-flash:free` | MAGI's short answers; hands harder turns to Hermes |
| Hermes (`services/hermes/config.yaml`) | Gemini `3.1-flash-lite-preview` → Gemini `flash-lite-latest` → Token Harbor qwen, deepseek → OpenRouter nemotron | MAGI chat with tools |
| Vision (`vision.py`) | Gemini `3.5-flash-lite` → `3.1-flash-lite-preview` (300 calls a day cap) | Describing reference pictures |
| Script engine | OpenRouter `SCRIPT_ENGINE_MODEL` (free models only; paid models refused in code) | Engine agents 1-5 |
| Embeddings (`embed.py`) | local `BAAI/bge-small-en-v1.5`, 384 dims | Knowledge search, filter, repeat checks, references, kitchens, brain map |
| Speech | STT: Groq `whisper-large-v3-turbo`; TTS: Kokoro `af_heart` (local) → Groq `canopylabs/orpheus-v1-english` → browser voice | Voice chat |
| Cognee | Gemini `gemini-3.1-flash-lite` + local embeddings | Knowledge graph (`connected_knowledge`) |

Fallback rules (`llm.chat`): up to 4 passes; 2 requests at a time per slot; 80 s per request (170 s long). A rate limit
rests the slot for its Retry-After (30+ minutes when a daily allowance is spent); 401/402 rest a day, 403 ten minutes,
other errors 20 s. A model that rejects JSON mode is asked without it.

---

## 7. API keys and outside services (names only)

| Key / setting | Service | Used for | Free tier | State on 15 Oct 2026 |
|---|---|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio | careful brains, quick chat, Hermes, vision, Cognee | free per-model daily limits (bigger models about 20 a day, lite models about 500) | set, working (3.8 and 3.7 were overloaded) |
| `GROQ_API_KEY` | Groq | fast brains, careful fallback, Whisper STT, Orpheus TTS fallback | free | set, working |
| `NVIDIA_API_KEY` | build.nvidia.com | first careful brain, crawler's second fast brain | free, per minute (about 40) | set; small model working, big model often overloaded |
| `TOKENHARBOR_API_KEY` | tokenharbor.ai | careful brains, quick chat, Hermes | free models, 60 a minute, weekly allowance | set, **blocked until the account email is verified** |
| `OPENROUTER_API_KEY` | openrouter.ai | script engine (all 5 agents), last careful fallback, Hermes fallback | `:free` models, about 50 a day per account | set, working |
| `OPENROUTER_KEY_EVIDENCE` / `_WRITER` / `_EDITOR` / `_LOOKBOOK` / `_VIDEO_PROMPT` | openrouter.ai | one key per engine agent (same account shares one daily limit) | as above | empty (use the main key) |
| `CEREBRAS_API_KEY` | Cerebras | extra careful brain | free | empty |
| `XAI_API_KEY` | xAI Grok | extra careful brain | **paid**: keep empty | empty |
| `MISTRAL_API_KEY` | none | not read by any code | | empty |
| `APIFY_API_TOKEN` | Apify | Instagram and Facebook posts for the crawler | $5 a month credit; MAGI stops at $4 | set, working |
| `BLOOM_API_KEY`, `BLOOM_BRAND_ID` | trybloom.ai | brand direction as context for ideas and creatives (never makes images) | reading costs no credits | empty |
| Higgsfield (OAuth, no key) | mcp.higgsfield.ai | creative images (1.5 credits each), video clips | **paid credits**; quote first, click to spend | credits used up |
| Google Drive (no key) | public folder `1jWOfLoYWxiWz6tEJL-DD3xxjiQ_HibZT` | reference library | free, read-only | working |
| `CRAWL4AI_API_TOKEN`, `SEARXNG_SECRET`, `HERMES_API_KEY`, `MCP_TOKEN`, `SESSION_SECRET` | internal | secrets between containers (made by `setup.sh`) | | set |
| `DB_PASSWORD` | internal | the real Postgres password (also used by Cognee) | | set |
| `DASHBOARD_PASSWORD`, `PUBLIC_HOST` | internal | public login (parked) | | empty |
| `MANAGER_NAME` / `MANAGER_EMAIL`, `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD` | | name on decisions / email is **not implemented** | | empty |

Not read by the backend: `GEMINI_MODEL`, `GEMINI_MODEL_FAST` (config wants `GEMINI_MODELS`, `GEMINI_FAST_MODELS`),
the GPT Researcher block (`GOOGLE_API_KEY`, `FAST_LLM`, `SMART_LLM`, `STRATEGIC_LLM`, `RETRIEVER`, `SEARX_URL`,
`DOC_PATH`, `TOTAL_WORDS`, `LANGUAGE`). Cognee's `LLM_*`, `EMBEDDING_*`, `DB_*`, `VECTOR_DB_*` are overridden in its compose file.

Other settings (non-secret, `backend/app/config.py`): `GEMINI_MODELS`, `GEMINI_FAST_MODELS`, `GEMINI_VISION_MODELS`,
`VISION_DAILY_CAP` 300, `GROQ_MODEL`, `CEREBRAS_MODEL`, `XAI_MODEL`, `OPENROUTER_MODEL`, `SCRIPT_ENGINE_MODEL`,
`NVIDIA_MODELS`, `NVIDIA_FAST_MODEL`, `TOKENHARBOR_MODELS`, `DATABASE_URL`, `SEARXNG_URL`, `CRAWL4AI_URL`, `HERMES_URL`,
`KOKORO_URL`, `KOKORO_VOICE` af_heart, `STT_MODEL`, `TTS_MODEL`, `TTS_VOICE`, `COGNEE_URL`, `HIGGSFIELD_MCP_URL`,
`HIGGSFIELD_REDIRECT_URI`, `INPUTS_DIR` /app/inputs, `DATA_DIR` /app/data, `TIMEZONE` Asia/Kolkata, `EMBED_MODEL`.
A Gemini key typed under **AI KEY** on the home screen is saved to `data/keys.json` and overrides `.env` for the backend only.

---

## 8. Schedule and start-up

| Time (IST) | Job | Code |
|---|---|---|
| 07:30 | Reference library sync from Drive | `references.sync` |
| 08:05 | Knowledge housekeeping (expire, auto-reject old held items) | `agents/knowledge.housekeeping` |
| 08:10 | Cognee sync | `cognee_sync.sync` |
| 18:00 | Review reminder (notification only) | `main.review_reminder` |
| 20:00 | Night crawl until 08:00 | `main.night_crawl` → `agents/crawler.run` |

Start-up (`main.lifespan`): open DB pool → load saved Gemini key → reset half-finished items → load knowledge files if
empty → sync seed sources → start the scheduler and the MCP server.

---

## 9. HTTP API (main routes)

| Area | Routes |
|---|---|
| Status, knowledge | `GET /api/status`, `POST /api/kb/reload`, `POST /api/kb/ask` |
| Crawler | `POST /api/crawl/start`, `/api/crawl/stop`, `GET /api/crawl/runs`, `GET /api/sources`, `POST /api/sources/{id}`, `POST /api/inspiration`, `GET /api/learnings` |
| Approvals | `GET /api/review`, `POST /api/review/item/{id}`, `/api/review/rule`, `/api/review/finalise` |
| Ideas | `POST /api/ideas/generate`, `GET /api/ideas/latest`, `POST /api/ideas/{id}/approve`, `/reject`, `POST /api/finalise` |
| Content | `GET /api/content`, `POST /api/creatives/{id}/generate` (spends), `POST /api/videos/{id}/script-changes`, `/approve-script`, `/lookbook/decision`, `GET /api/videos/{id}/files/{name}`, `POST /api/videos/{id}/quote` (free), `/generate` (spends), `/plan`, `POST /api/higgsfield/cost` |
| References | `GET /api/references` (`?kind&reviewed&q`), `/status`, `/finishes`, `POST /api/references/sync`, `POST /api/references/{id}` |
| MAGI home | `GET /api/magi/map`, `/team`, `POST /api/magi/drop` (.md/.txt/.csv into knowledge) |
| Voice and chat | `POST /api/mai/chat`, `/api/mai/stt`, `/api/mai/tts` |
| Keys, logins | `GET /api/keys`, `POST /api/keys/gemini`, `GET /api/higgsfield/login`, `/callback`, `/status`, `/tools`, `/login`, `POST /api/login`, `/api/logout` |
| Other | `GET /api/bloom/status`, `POST /api/bloom/refresh`, `GET /api/cognee/status`, `POST /api/cognee/sync`, `GET /api/notifications`, `POST /api/notifications/read` |
| Mounts | `/` home, `/marketing` dashboard, `/media/*`, `/static/*`, `/mcp/` (Bearer `MCP_TOKEN`) |

**MCP tools for MAGI (18)**: open_screen, team_status, system_status, overnight_summary, search_company_knowledge,
connected_knowledge, current_ideas, generate_new_ideas, produce_content, finished_content, approval_list,
decide_approval, finalise_review, start_crawl, stop_crawl, add_inspiration_link, add_company_knowledge, never_use.

---

## 10. Database (`supabase/migrations/`, all embeddings `vector(384)`)

| Table | Holds |
|---|---|
| `sources`, `crawl_runs`, `crawl_queue`, `pages` | sites, night runs, the resumable queue, every page read (relevance, kept, processed) |
| `kb_chunks` | the knowledge base by `doc`: core, brand, internal (team only), script_bank, learned, manager (HNSW index) |
| `learnings`, `review_sessions`, `manager_rules` | what MAGI learned, your review rounds, your rules (add_knowledge, never_use, block_site, trust_site) |
| `idea_batches`, `ideas` | daily batches and each idea (`payload` carries creative words, `video_type`, `kitchen`) |
| `blogs`, `creatives`, `videos` | finished content (`videos.script` jsonb holds the engine run, lookbook, package, stage) |
| `ref_assets`, `ref_uses` | the reference library and which reference went into which output |
| `notifications`, `settings` | alerts; crawl window, crawl limits, budgets (`crawl_limits`, `cognee_budget`, ...) |

SQL functions: `match_kb`, `similar_ideas`, `similar_learnings`, `match_refs`. Migration order: core schema (1 Oct) →
pending learnings + crawl queue → generation flow statuses → Cognee sync columns → creative formats → internal
knowledge → production phases (lookbook, prompting, package_ready) → reference library (15 Oct).

---

## 11. File map

**`backend/app/`** (core)
| File | Feature |
|---|---|
| `main.py` | the app: every route, scheduler, start-up repair, production pipeline (`_produce`), MAI chat, mounts |
| `config.py` | all settings (section 7) |
| `db.py` | Postgres pool and helpers |
| `llm.py` | text AI chain with fallback and cooldowns |
| `keys.py` | save and check a Gemini key from the dashboard |
| `embed.py` | local embeddings |
| `kb.py` | knowledge base: chunk, load `inputs/`, search |
| `inputs.py` | reads the instruction files and seed sources |
| `brand.py` | brand rules: banned claims, no dashes, violation check |
| `brandmark.py` | stamps the real logo on images |
| `auth.py` | password login for the public address |
| `bloom.py` | Bloom brand context |
| `cognee_sync.py` | knowledge graph sync and search |
| `higgsfield.py`, `media.py` | Higgsfield OAuth, cost quotes, generation, downloads |
| `mcp_server.py` | MAGI's 18 tools |
| `quick.py` | quick chat answers |
| `services.py` | Crawl4AI, SearXNG, YouTube clients |
| `social.py` | Apify Instagram and Facebook |
| `team.py`, `magi.py` | office state, home screen API, departments |
| `voice.py` | speech to text, text to speech |
| `vision.py` | Gemini picture reading |
| `references.py` | reference library |
| `kitchens.py` | kitchen and finish pick |
| `video_types.py` | video type library |
| `script_engine.py` | bridge to the video engine: per-agent keys, request building, brand check, backup brains, package to Higgsfield |

**`backend/app/agents/`**: `crawler.py` (Discovery, Crawler, YouTube, social), `filter.py`, `knowledge.py`, `ideas.py`
(Adapt, Strategist, idea cards), `blog.py`, `creative.py`, `video.py` (script, revise, lookbook, decide, direct, generate).

**`backend/script_engine/`**: `SKILL.md` (rules 1-8), `agents/*.md` (5 prompts), `workflows/content_pipeline.py`
(orchestrator), `production.py` (lookbook and package building and checks), `approval_manager.py` (hashes),
`continuity_gate.py`, `diversity_gate.py`, `hook_ledger.py`, `openrouter_client.py` (free-model-only client), `config.py`,
`schema_validator.py`; `corpus_gate.py` and `brand_corpus.py` exist but are not wired in. `schemas/` (content-request,
research-dossier, script, review, approval, run-state, lookbook, lookbook-approval, video-prompts; `v1/`, `v2/` history).
`knowledge/references/` (angle taxonomy, evidence index (empty), source hierarchy).

**`backend/static/`**: `magi.html` + `magi/` (3D office home: three.js, Quaternius people, Kenney furniture, brain of
knowledge dots, voice with wake phrase "hey MAGI", departments, AI KEY panel, file drop), `index.html` (marketing
dashboard: IDEAS, CONTENT, APPROVALS, CRAWLER, REFERENCES tabs), `mai.html` (old chat page), `login.html`.

**`inputs/`** (read-only in the container)
| File | Configures |
|---|---|
| `company-kb.md`, `company-kb-website.md` | company knowledge (doc core) |
| `company-kb-internal.md` | team-only knowledge (git-ignored; template `.example.md`) |
| `brand-guide.md` | voice, rules, colours (#0B0B0D, copper #C77B4A, silver #C9CED6), font Lato, CTAs |
| `approved-claims.md` | claims CLM-001 to 031 and rejected REJ-001 to 010 (the engine may only use these) |
| `seed-sources.md` | own links and 15 similar brands to crawl |
| `crawler-rules.md` | what to look for, skip, limits, approval buckets |
| `output-formats.md` | blog, creative, video formats |
| `creative-styles.json` | image model, formats (story, poster, post), logo slots |
| `video-types.json` | 17 video types with beats, hooks, camera, voice, cautions |
| `reference-library.json` | Drive folder and folder-to-kind rules |
| `magi.json` | the 10 departments on the home screen |
| `prompt-bank.json` | earlier Higgsfield prompts as style references |
| `logo-black.png` | the real logo |

**Elsewhere**: `docker-compose*.yml`, `services/` (caddy, cognee, db init, hermes persona and models, searxng),
`supabase/` (migrations, CLI config), `scripts/` (`setup.sh`, `add-keys.sh`, `pack-office-assets.mjs`),
`tests/home/mock-server.mjs` (home screen without a backend, port 8765), `docs/` (`AGENT_OFFICE_MODELS.md`,
`architecture.html` (historical), this file), `README.md`, `HANDOFF.md`.

---

## 12. Limits and safety

- **Money**: only Higgsfield costs money. Quotes spend nothing; generation needs an explicit click. Apify stops at $4 of
  the $5 free credit. The engine's OpenRouter client refuses paid models.
- **Crawl**: depth 3, 3 s between hits per site, up to 4 sites at once, 30,000 pages, relevance 0.05; Knowledge reads up
  to 240 pages a night.
- **Ideas**: 2 per type per batch; repeat threshold 0.86. **Revisions**: 1 per script and 1 per lookbook.
- **Vision**: 300 calls a day. **Cognee**: 150 passages and 300 learnings per run.
- **Brand rules** (`brand.py`, `SOUL.md`): SILVERSTONE stone, zero wood, never steel; no health or germ-killing claims;
  no em or en dashes; ahimsa wording; never attack competitors; main-board IPO, never "SME"; team-only knowledge never in public content.

---

## 13. Known gaps (found while mapping)

1. `POST /api/videos/{id}/plan` skips the lookbook gate (not used by the UI).
2. The automatic brand check can use the script's only revision, hiding ASK FOR CHANGES.
3. `ref_uses` is written but kitchen rotation reads `ideas.payload`; re-running prompts records a use twice.
4. `video_types.choose` can return a type already used in the batch.
5. `class Decision` is defined twice in `main.py`.
6. A creative interrupted while writing can fail later on GENERATE (no image prompts saved).
7. The References tab can't be opened by voice (`refs` missing in `magi/app.js` and `SOUL.md`).
8. Stale docs: README (17 abilities, 4 tabs, old home), SKILL.md frontmatter version 1.1, `config.py` says agent 4
   "not built yet", HANDOFF logo item; `.env.example` and the `config.py` default point at port 54322 while compose uses 5432.
9. Unused settings: `MISTRAL_API_KEY`, `MANAGER_EMAIL`, `GMAIL_*`, GPT Researcher block, `GEMINI_MODEL(_FAST)`.
10. Video upgrade phases 5 to 7 (storyboard, clips, assembly) are not built in MAGI yet; Phase 0 Higgsfield test is waiting for credits.
