# MAGI: handoff (read this first)

Last updated: 3 October 2026. The full guide is `README.md`.

## What this is
MAGI (said "Maggie") is the second brain of Magppie Kitchens: one screen where the company's knowledge
lives, with the departments around it. Marketing is the first department connected. It reads similar
brands every night, learns, and turns that into blog, creative and video ideas in the MAGPPIE voice.
Each idea is approved by a person before anything is made.

MAGPPIE builds wellness kitchens, wardrobes and vanities entirely from SILVERSTONE, a patented engineered
stone infused with silver and copper. Zero wood. Not steel. The brand rules are in `inputs/brand-guide.md`
and are enforced in code by `backend/app/brand.py`.

## Where it runs
- Server: Oracle Cloud, Mumbai, folder `~/marketing-mai`. Its address and login are in `SERVER.local.md`,
  which stays on this Mac and is never committed.
  It is on Oracle's trial credit, which ends around 31 October 2026.
- Open it on this Mac at http://localhost:8000 through the Terminal tab "MAI connection (keep open)".
- Screens: `/` MAGI home, `/marketing` the marketing dashboard (also opens inside MAGI).

## The files a person edits (`inputs/`)
| File | What it is |
|---|---|
| `company-kb.md` | The company knowledge that public content may use |
| `company-kb-internal.md` | Team-only knowledge (IPO, targets, hiring). MAGI may tell it; content agents never see it |
| `company-kb-website.md` | What magppie.com, our YouTube and our Instagram say (read 2 Oct 2026) |
| `brand-guide.md` | Brand identity and the rules that are never broken |
| `seed-sources.md` | Our own links, and the 15 similar brands the crawler starts from |
| `crawler-rules.md` | What the crawler looks for, and what is saved, held or never saved |
| `creative-styles.json` | The three creative kinds (story, poster, post) and their look |
| `magi.json` | The departments around MAGI |
| `approved-claims.md` | The claims register the video script engine checks every line against |
After changing a knowledge file: copy it to the server and call `POST /api/kb/reload`.

## How it is built
- `docker-compose.yml`: database (Postgres + pgvector), SearXNG, Crawl4AI, backend (FastAPI), voice (Kokoro),
  Hermes Agent (MAGI's reasoning). `docker-compose.cognee.yml`: the knowledge map. `docker-compose.public.yml`:
  the web link with login (parked).
- `backend/app/agents/`: crawler, filter, knowledge, ideas, blog, creative, video.
- `backend/app/magi.py` + `backend/static/magi.html`: the MAGI home screen.
- `backend/app/mcp_server.py`: what MAGI can do (17 abilities). `services/hermes/SOUL.md`: who MAGI is.
- AI brains: NVIDIA and Token Harbor for ideas, blogs and creatives, Gemini for MAGI's voice and the knowledge
  map, Groq for the night reading. Keys are added with `bash scripts/add-keys.sh`, never typed in chat.
- Video scripts: `backend/script_engine/` is the Magppie Content Intelligence Engine (from
  magppie-handover-v2.zip), kept as written except that its old company story is gone: prompts, built-in demo data and examples now come from the knowledge base. It runs on
  OpenRouter `nvidia/nemotron-3-super-120b-a12b:free`. `backend/app/script_engine.py` is the bridge: it writes
  the engine's knowledge from `company-kb.md`, `brand-guide.md` and `approved-claims.md` for every run, gives
  each agent its key (`OPENROUTER_KEY_EVIDENCE`, `_WRITER`, `_EDITOR`, `_LOOKBOOK`, `_VIDEO_PROMPT`; an empty
  one falls back to `OPENROUTER_API_KEY`), and keeps the runs in `/app/data/script-engine/runs`. All five agents
  are in the engine now (see `backend/script_engine/README.md`): script, your approval, lookbook (agent 4), your
  approval, video prompts and Edit Sheet (agent 5), then the price and the video. A video costs 5 to 9 free
  requests; a free OpenRouter account allows 50 a day, and about half of the long calls stall and are retried.
  If the engine cannot write a script the backup writer does; if it cannot make a lookbook or the prompts, the
  other brains do, and the card says so. Engine tests: `pytest backend/script_engine/tests`.
- A new Gemini key can be typed on the MAGI screen (AI KEY, top right): `backend/app/keys.py` checks it, keeps it
  in `/app/data/keys.json` and uses it at once. MAGI's deeper agent (Hermes) and Cognee still read `.env`.
- The space bar switches MAGI's microphone on and off.
- Images and videos: Higgsfield (credits are spent only when a person approves).

## Deploying a change
1. `rsync -az -e "ssh -i <key>" ./ <user>@<server>:~/marketing-mai/` (see `SERVER.local.md`) (never with `--delete`).
2. On the server: `sudo docker compose up -d --build backend`.
3. A rebuild stops the night crawl: `curl -X POST localhost:8000/api/crawl/start -H 'Content-Type: application/json' -d '{}'`.
Check `/api/content` first: restarting while an image or video is being made loses it.

## Open
- Logo files (the wordmark is drawn as text until they arrive).
- The website and the brand file disagree on a few facts (listed at the end of `company-kb-internal.md`).
- The web link with a login is built but switched off; it needs a password and two Oracle firewall rules.
- Move off the Oracle trial before the credit ends.
