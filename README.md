# MAGI: the second brain of Magppie Kitchens

MAGI (said "Maggie") is one screen where the company's knowledge lives, with the departments around it.
**Marketing** is the first department connected. Every night it reads similar brands, keeps what is relevant,
learns from it, and turns it into blog, creative and video ideas in the MAGPPIE voice. A person approves
every idea, every script, every lookbook and every paid generation. You can talk to MAGI by voice.

MAGPPIE builds wellness kitchens, wardrobes and vanities entirely from **SILVERSTONE**, a patented engineered
stone infused with silver and copper. Zero wood. Not steel. Every agent is held to that by code.

State of this guide: 3 October 2026.

---

## 1. What it does, in one picture

```text
                 8 PM to 8 AM, every night
seed brands ─► CRAWLER ─► FILTER ─► KNOWLEDGE ─► the knowledge base (the "brain")
(websites,     reads      keeps      learns;            │
 YouTube,      pages      what       doubts wait        │
 Instagram,               fits       for the manager    ▼
 Facebook)                                         STRATEGIST: 2 blog, 2 creative, 2 video ideas
                                                        │   (you approve the ones you like)
                         ┌──────────────────────────────┼──────────────────────────────┐
                         ▼                              ▼                              ▼
                   BLOG WRITER                    ART DIRECTOR                    VIDEO TEAM
                   full blog with                 brief, then the image           5 agents, 3 approvals,
                   sources                        on Higgsfield                   then the video on Higgsfield

MAGI (voice + chat) sits on top: answers from the knowledge, opens screens, and can run every job.
```

Nothing is published anywhere by the system. It prepares content; people post it.

---

## 2. The screens

| Address | What it is |
|---|---|
| `/` | **MAGI home.** A round stone table: MAGI's brain in the middle (each dot is a real piece of knowledge), ten departments on the rim. Only Marketing is connected. |
| `/marketing` | **Marketing dashboard.** Tabs: Ideas, Content, Approvals, Crawler. It also opens inside MAGI, so the voice keeps listening. |

On the MAGI home screen:

- `A` / `D` or the arrow keys turn the table. `Enter` steps into the chosen department.
- **Space bar** switches MAGI's microphone on and off. Say "wake up time", then ask.
- Type a fact in the top box to add it to the knowledge, or drop a `.md`, `.txt` or `.csv` file anywhere.
- **AI KEY** (top right): paste a new Gemini key when the free one runs out. It is checked with Google,
  saved on the server and never shown again.

On the Marketing dashboard:

- **Ideas:** six ideas per batch. Approve the ones to make. A creative's words can be edited before approving.
- **Content:** finished blogs, creatives and videos, each with its progress and its approvals.
- **Approvals:** learnings the system was not sure about. The manager decides them (reminder at 6 PM).
- **Crawler:** start or stop a crawl, add a link to read first, see what was learned.

---

## 3. How a video is made (the five-agent engine)

The video team is the **Magppie Content Intelligence Engine** in `backend/script_engine/`
(its own notes: `backend/script_engine/README.md`). It runs on OpenRouter, model
`nvidia/nemotron-3-super-120b-a12b:free`.

```text
Agent 1  Evidence and Intelligence      gathers what may be said, from the knowledge only
Agent 2  Director-Writer                writes the shooting script: one continuous world, ten directions,
                                        five timed beats per 30-second scene, voice direction for every line
   gates  is the hook new · do timing, beats and frames add up · is the voice directed
Agent 3  Executive Editor               checks every claim, repairs, reports what it changed
   YOU    APPROVE SCRIPT  (or ASK FOR CHANGES, once)              → the script is locked with a fingerprint
Agent 4  Lookbook Director              palette, continuity cards, 3 keyframes per scene, product moment, sound
   YOU    APPROVE LOOKBOOK (or ASK FOR CHANGES, once)             → approval is bound to that exact lookbook
Agent 5  Video Prompt Engineer          the prompt for every scene and the Edit Sheet
          PRODUCTION PACKAGE COMPLETE
   YOU    choose a length and price                               → Higgsfield makes the video (credits)
```

What the code guarantees, whatever the model writes:

- no lookbook before the script is locked, no video prompt before the lookbook is approved;
- in every scene prompt: the Continuity Bible word for word, the rulebook's negative prompt exactly, the locked
  voice-over, the locked entry and exit frames;
- on-screen text is an instruction for the editor, never asked of the video model;
- a brand check (`backend/app/brand.py`) on everything, and a flag for any figure or stone colour that is not
  in the knowledge.

A script is one 30-second scene (one Higgsfield clip). Longer films need stitching, which is not built.

---

## 4. What runs where

Everything runs in Docker (`docker-compose.yml`). All ports listen on `127.0.0.1` only.

| Service | What it is | Port |
|---|---|---|
| `db` | Postgres 17 with pgvector: knowledge, learnings, ideas, content | 5432 |
| `searxng` | Private web search for the crawler and the blog writer | 8888 |
| `crawl4ai` | Reads web pages | 11235 |
| `backend` | FastAPI: all agents, both screens, MAGI's tools (MCP) | 8000 |
| `voice` | Kokoro, MAGI's speaking voice, on our own server | internal |
| `hermes-init`, `hermes` | Hermes Agent: MAGI's deeper reasoning when she has to act | 8642 |
| `cognee` (add-on) | Connects knowledge into one map: `docker-compose.cognee.yml` | 8100 |
| `web` (add-on, switched off) | Caddy with a login in front, for a public web link: `docker-compose.public.yml` | 80, 443 |

Outside services (all on free plans except Higgsfield): Gemini, Groq, NVIDIA, Token Harbor, OpenRouter (AI
brains), Apify (reads public Instagram and Facebook), Higgsfield (images and videos, paid credits), Bloom
(brand creative direction, read as context only).

---

## 5. Folder map

```text
backend/
  app/
    main.py            the web server: routes, schedule (crawl 8 PM, review reminder 6 PM), start-up repair
    agents/            crawler.py  filter.py  knowledge.py  ideas.py  blog.py  creative.py  video.py
    script_engine.py   bridge between the dashboard and the five-agent video engine
    brand.py           the brand rules as code: clean(), violations(), RULES
    llm.py             which AI brain is asked, in which order, with cooldowns
    quick.py           MAGI's quick lane: knowledge search + one fast call (about a second)
    mcp_server.py      MAGI's 17 abilities (open a screen, team status, new ideas, approvals, crawl, ...)
    magi.py            the home screen's data: knowledge dots, departments, the marketing tree
    kb.py  embed.py    the knowledge base: loading inputs/, chunking, embedding, search
    media.py  higgsfield.py   image and video generation, the Higgsfield connection
    voice.py           speech to text (Groq Whisper) and text to speech (Kokoro)
    keys.py            a new Gemini key typed on the dashboard
    social.py  bloom.py  cognee_sync.py  auth.py  inputs.py  config.py  db.py
  script_engine/       the Magppie Content Intelligence Engine (agents, schemas, workflows, rulebook, tests)
  static/              magi.html (home screen), index.html (marketing dashboard), login.html
inputs/                what a person edits: knowledge, brand guide, seed brands, crawler rules, styles
services/              hermes (MAGI's persona and config), searxng, cognee, caddy, db init
supabase/migrations/   the database, as SQL files in order
scripts/               setup.sh (first start), add-keys.sh (keys, typed hidden)
docs/architecture.html the first design drawing (historical: it predates MAGI and the video engine)
HANDOFF.md             the short working note for whoever runs the live server
```

---

## 6. The files a person edits (`inputs/`)

| File | What it is |
|---|---|
| `company-kb.md` | Company knowledge that public content may use |
| `company-kb-internal.md` | Team-only knowledge. **Not in this repository.** Copy `company-kb-internal.example.md` and ask the owner for the content. MAGI may tell it to the team; content agents never see it |
| `company-kb-website.md` | What the company's own website, YouTube and Instagram say |
| `brand-guide.md` | Brand identity and the rules that are never broken |
| `approved-claims.md` | The claims register the video engine checks every line against |
| `seed-sources.md` | The company's own links, and the similar brands the crawler starts from |
| `crawler-rules.md` | What the crawler looks for; what is saved, held for the manager, or never saved |
| `creative-styles.json` | The three creative kinds (story, poster, post) and their look |
| `magi.json` | The departments around MAGI |
| `prompt-bank.json` | Image and video prompts the team wrote before, used as style examples |

After changing a knowledge file on a running system: `curl -X POST localhost:8000/api/kb/reload`.

### Brand rules every output must pass

No em dashes or en dashes. Stone, never steel or wood. Only what the material physically does (does not burn,
does not swell, does not stain, zero formaldehyde by composition): no health claims. Ahimsa: nothing "kills";
termites find nothing to eat. Compare against materials, never against a named brand. Money matters and other
team-only subjects never appear in content. `brand.py` rejects text that breaks these, and agents rewrite it.

---

## 7. Run it on a new machine

Needs: Docker with Compose, about 8 GB of memory, and the free keys below.

```bash
git clone https://github.com/satyaabhardwaj/MAGI.git && cd MAGI
bash scripts/setup.sh          # makes .env and fills in the internal passwords
bash scripts/add-keys.sh       # asks for each key; what you paste stays hidden
docker compose up -d --build   # first start also creates the database from supabase/migrations/
```

Then open http://localhost:8000. The first start downloads several images and an embedding model, so give it
a few minutes. To add the knowledge map: `docker compose -f docker-compose.yml -f docker-compose.cognee.yml up -d --build`.

### Keys (`.env`, never committed)

| Key | For | Where |
|---|---|---|
| `GEMINI_API_KEY` | MAGI's talk, knowledge map, a fallback for content. Required | aistudio.google.com/apikey |
| `GROQ_API_KEY` | The night reading, speech to text. Required | console.groq.com/keys |
| `NVIDIA_API_KEY` | First brain for ideas, blogs, creatives | build.nvidia.com |
| `TOKENHARBOR_API_KEY` | Second brain for content | tokenharbor.ai |
| `OPENROUTER_API_KEY` | The video engine (all five agents) | openrouter.ai/settings/keys |
| `OPENROUTER_KEY_EVIDENCE`, `_WRITER`, `_EDITOR`, `_LOOKBOOK`, `_VIDEO_PROMPT` | Optional key per video agent; empty ones use `OPENROUTER_API_KEY`. Keys of one account share one daily limit | same |
| `APIFY_API_TOKEN` | Reading public Instagram and Facebook posts | console.apify.com |
| `BLOOM_API_KEY` | Brand creative direction, context only | trybloom.ai |
| `MANAGER_NAME` | The name written on approvals | you |
| `DASHBOARD_PASSWORD`, `PUBLIC_HOST` | Only for the public web link (switched off) | you |

Higgsfield has no key: press **Connect Higgsfield** on the dashboard and sign in once.

Keys are never typed in chat and never committed. `.env` is in `.gitignore`.

---

## 8. Which AI brain does what

| Work | Order tried |
|---|---|
| Ideas, blogs, creative briefs, backup script writer | NVIDIA (`nemotron-3-ultra`) → Token Harbor (DeepSeek, Qwen, MiMo) → Gemini → Groq → OpenRouter |
| The crawler's bulk reading | Groq → NVIDIA (`gpt-oss-20b`). Nothing else, so it cannot empty the content brains |
| MAGI's quick answers | Gemini flash-lite → Groq → Token Harbor |
| MAGI when she has to act | Hermes Agent on Gemini, with fallbacks |
| Video engine, agents 1 to 5 | OpenRouter `nvidia/nemotron-3-super-120b-a12b:free`; agents 4 and 5 fall back to the other brains |

A brain that is busy or over its limit rests for a while and the next one is asked (`backend/app/llm.py`).

---

## 9. Changing and updating a running server

1. Copy the project to the server (never with `--delete`):
   `rsync -az --exclude .git --exclude __pycache__ ./ <user>@<server>:~/marketing-mai/`
2. On the server: `sudo docker compose up -d --build backend`
3. A rebuild stops a running crawl: `curl -X POST localhost:8000/api/crawl/start -H 'Content-Type: application/json' -d '{}'`

Good to know:

- Check `curl localhost:8000/api/content` first. A restart while something is being made loses it.
- `backend/static/` and `inputs/` are mounted, not built: copying them is enough (plus `/api/kb/reload` for knowledge).
- A new file in `supabase/migrations/` is applied by hand on an existing database:
  `sudo docker compose exec -T db psql -U postgres -d postgres < supabase/migrations/<file>.sql`
- MAGI's persona (`services/hermes/`): copy it, then `sudo docker compose up -d --force-recreate hermes-init hermes`.
- The live server's address and login are not in this repository. Ask the owner.

---

## 10. Tests

```bash
cd backend/script_engine
pip install pytest jsonschema httpx python-dotenv pydantic
python -m pytest tests -q        # 20 tests for the lookbook and video-prompt phases, no key needed
```

The rest of the system was tested by running it; there is no automated suite for the dashboard yet.

---

## 11. Main addresses of the server (API)

| Address | What it does |
|---|---|
| `GET /api/status` | Counts and what is running |
| `POST /api/crawl/start`, `/api/crawl/stop` | The crawler |
| `POST /api/ideas/generate`, `GET /api/ideas/latest` | A new batch of ideas; the current one |
| `POST /api/ideas/{id}/approve`, `/reject` | Approve an idea (it gets made) or drop it |
| `GET /api/content` | Blogs, creatives, videos and their state |
| `POST /api/creatives/{id}/generate` | Make the image (Higgsfield credits) |
| `POST /api/videos/{id}/script-changes` | Ask for changes to a script (once) |
| `POST /api/videos/{id}/approve-script` | Lock the script; agent 4 makes the lookbook |
| `POST /api/videos/{id}/lookbook/decision` | `APPROVE` (agent 5 follows) or `REQUEST_CHANGES` |
| `GET /api/videos/{id}/files/{name}` | `lookbook.html`, `lookbook.json`, `video-prompts.md`, `video-prompts.json`, `edit-sheet.md` |
| `POST /api/videos/{id}/quote`, `/generate` | Price, then the video (Higgsfield credits) |
| `GET /api/review`, `POST /api/review/item/{id}`, `/api/review/finalise` | The manager's approval list |
| `POST /api/kb/reload`, `/api/kb/ask` | Reload the knowledge files; ask the knowledge |
| `POST /api/mai/chat`, `/api/mai/stt`, `/api/mai/tts` | Talk to MAGI |
| `GET /api/keys`, `POST /api/keys/gemini` | Whether Gemini has a working key; save a new one |
| `GET /api/magi/map`, `POST /api/magi/drop` | The home screen's data; a dropped document |

---

## 12. Known limits (as of 3 October 2026)

- **The free video model stalls.** About half of its long calls hang or return nothing. Each is dropped after
  200 seconds and asked again, so a step takes 2 to 6 minutes. A full video uses 5 to 9 of the 50 free
  requests an OpenRouter account gets per day (1,000 after a one-time $10 credit).
- **Agents still invent small things.** Seen so far: a stone colour, a "polymer matrix". The checks flag
  colours and figures that are not in the knowledge, and agent 4 lists its own assumptions. Read before approving.
- **A changed script is not re-checked for length** (the engine's revision path skips that gate).
- **MAGI's deeper agent and the knowledge map read their Gemini key from `.env`**, not from the AI KEY box.
- **YouTube** blocks detail reads from servers: the crawler falls back to titles and views.
- **Higgsfield** accounts in a "grace period" have a small daily limit; the card says so when it is hit.
- **One 30-second scene per video.** Stitching several scenes into one film is not built.
- **Only Marketing is connected.** The other nine departments are shown, with what MAGI already knows for them.
- No automated tests outside the video engine. No user accounts: the dashboard is meant for a private address.

## 13. What is not in this repository

Keys (`.env`), the team-only knowledge file, the live server's address, the database, generated images and
videos, and rendered media under `videos/`.
