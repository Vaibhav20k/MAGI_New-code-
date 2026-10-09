// A stand-in for MAGI's backend, for checking the home screen without Docker, keys or a database.
// It serves backend/static as the real server does and answers the home screen's API calls from fixtures.
// Nothing here reaches a real service: mutations are recorded in memory and listed at /__mock/calls.
//   node tests/home/mock-server.mjs            → http://localhost:8765  (home = backend/static/magi.html)
//   node tests/home/mock-server.mjs magi/home.html   → serve another file as the home page
//   /__mock/mode?m=normal|empty|fail|expired   → switch what /api/magi/map answers
import http from "node:http";
import {readFile} from "node:fs/promises";
import {fileURLToPath} from "node:url";
import path from "node:path";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const STATIC = path.join(ROOT, "backend/static");
const PORT = +(process.env.PORT || 8765), HOME_PAGE = process.argv[2] || process.env.HOME_PAGE || "magi.html";
const TYPES = {".glb": "model/gltf-binary", ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json"};

let mode = "normal", extra = 0, team = "quiet";
const idle = line => ({state: "idle", line}), working = line => ({state: "working", line}), waiting = (line, opens) => ({state: "waiting", line, opens});
const TEAMS = {                                             // /__mock/team?m=quiet|crawl|waiting|busy  (the shapes backend/app/team.py returns)
  quiet: {},
  crawl: {crawler: working("Reading the web now · 41 pages this run"), filter: working("Sorting what the crawler finds · 9 kept this run"), knowledge: working("Turning pages into learnings")},
  waiting: {knowledge: waiting("3 learnings wait for the manager", "approvals"), strategist: waiting("6 ideas wait for your approval", "ideas"), video: waiting("1 video waits for your approval", "content")},
  busy: {strategist: working("Choosing new ideas"), blog: working("Writing 1 blog"), creative: working("Making 1 creative"), video: working("Agent 2 of 5 · writing and directing the script")},
};
const REST = {crawler: "Resting until 8 PM, when the night's reading starts", filter: "Nothing to sort until the crawler reads", knowledge: "Every page read so far has been learned from",
              strategist: "No idea run in progress", blog: "No blog being written", creative: "No creative in progress", video: "No script or video in progress"};
const calls = [];

async function fixtureMap() {
  const depts = JSON.parse(await readFile(path.join(ROOT, "inputs/magi.json"), "utf8")).departments;
  const knows = {marketing: ["Go Check Your Kitchen", "Brand voice", "Campaign calendar"], sales: ["Experience centres", "The Proof Lab"], factory: ["SILVERSTONE", "Approve, produce, install"]};
  const kinds = mode === "empty" ? {} : {core: 65 + extra, brand: 9, internal: 4, script_bank: 15};
  const dots = [];
  let id = 1;
  for (const [doc, n] of Object.entries(kinds)) for (let i = 0; i < n; i++, id++) {
    dots.push({id, doc, section: `${doc} > Topic ${1 + (i % 7)}`, body: `Fixture passage ${id}. SILVERSTONE is engineered stone, with zero wood inside the kitchen.`, links: []});
  }
  dots.forEach((d, i) => { d.links = [dots[(i + 7) % dots.length], dots[(i + 14) % dots.length]].filter(o => o.doc === d.doc && o.id !== d.id).map(o => o.id); });   // same topic, as nearest neighbours would be
  const total = dots.length;
  const role = (key, name, job, does, tools, stat, detail) => ({key, name, job, does, tools, stat, detail});
  return {
    dots, kinds, total, waiting: mode === "empty" ? 0 : 12, pending: 0, pages: mode === "empty" ? 0 : 1840, sites: mode === "empty" ? 0 : 73, newest: null,
    departments: depts.map(({ask, ...d}) => ({...d, knows: knows[d.key] || []})),
    marketing: [
      role("crawler", "Crawler", "Reads similar sites every night", "Starts from the seed sites at 8 PM, follows links, finds new sites by itself and stops at 8 AM.", ["Crawl4AI", "SearXNG", "yt-dlp", "Apify"], "1,840 pages", "1,840 pages read on 73 sites"),
      role("filter", "Filter", "Keeps only what fits the company", "Compares every page with MAGI's knowledge and throws away what is off-topic.", ["fastembed", "pgvector"], "412 kept", "412 of 1,840 pages kept as relevant"),
      role("knowledge", "Knowledge", "Learns, and holds doubts for the manager", "Pulls learnings out of the kept pages. Sure ones join MAGI. Doubtful ones wait for the manager's 6 PM review.", ["Groq", "Cognee", "Postgres"], "96 learned", "96 learnings in MAGI · 12 waiting for the manager"),
      role("strategist", "Strategist", "Picks 2 blog, 2 creative, 2 video ideas", "Turns what is working elsewhere into ideas shaped to the company, scores them and never repeats one.", ["Token Harbor", "Gemini", "Bloom"], "18 ideas", "18 ideas shown so far"),
      role("blog", "Blog writer", "Writes the full blog with sources", "Researches the approved idea and writes the blog from the company's own knowledge.", ["Token Harbor", "SearXNG"], "4 blogs", "4 blogs written"),
      role("creative", "Art director", "Makes the story, poster or post", "Takes the approved words and makes the finished image in the house style.", ["Token Harbor", "Bloom", "Higgsfield"], "3 made", "3 creatives made"),
      role("video", "Video team", "Writes the script, then the video", "Five agents. Three write the script, with rule gates between them. After you approve the script and the lookbook, the video is made.", ["Script engine", "OpenRouter", "Higgsfield"], "2 scripts", "2 scripts written · 1 videos made"),
      role("voice", "MAGI's voice", "Talks, answers and acts for you", "Say \"wake up time\" and ask anything, or tell MAGI what to open or do.", ["Hermes", "Gemini", "Whisper", "Kokoro"], "17 abilities", "17 abilities, from reading the status to opening screens"),
    ],
    tools: {"Crawl4AI": "Reads web pages like a person would.", "SearXNG": "Private web search, on our own server.", "Gemini": "Google's brain: quick answers when you talk to MAGI.", "Higgsfield": "Makes the images and the videos.", "Hermes": "The agent that lets MAGI use its abilities."},
  };
}

function body(req) { return new Promise(done => { const parts = []; req.on("data", c => parts.push(c)); req.on("end", () => done(Buffer.concat(parts))); }); }
const json = (res, code, data, headers = {}) => { res.writeHead(code, {"Content-Type": "application/json", "Cache-Control": "no-store", ...headers}); res.end(JSON.stringify(data)); };

async function api(req, res, url) {
  const p = url.pathname, post = req.method === "POST";
  const raw = post ? await body(req) : null;
  const sent = () => { try { return JSON.parse(raw.toString() || "{}"); } catch (_) { return {}; } };
  if (post) calls.push({path: p, bytes: raw.length, body: /json/.test(req.headers["content-type"] || "") ? sent() : null});
  if (p === "/api/magi/map") {
    if (mode === "fail") return json(res, 503, {detail: "The database is not answering."});
    if (mode === "expired") return json(res, 401, {detail: "Please sign in."}, {"X-MAI-Login": "1"});
    return json(res, 200, await fixtureMap());
  }
  if (p === "/api/magi/team") return json(res, 200, {roles: Object.fromEntries(Object.keys(REST).map(k => [k, (TEAMS[team] || {})[k] || idle(REST[k])]))});
  if (p === "/api/keys") return json(res, 200, {gemini: {saved: true, from_dashboard: false, resting: false}});
  if (p === "/api/keys/gemini") return sent().value === "bad" ? json(res, 400, {detail: "Google did not accept that key."}) : json(res, 200, {saved: true});
  if (p === "/api/review/rule") { extra++; return json(res, 200, {ok: true}); }
  if (p === "/api/magi/drop") { extra += 3; return json(res, 200, {added: 3, file: "fixture.md"}); }
  if (p === "/api/mai/chat") {
    const m = (sent().message || "").toLowerCase();
    const actions = /approval/.test(m) ? ["approvals"] : /crawler/.test(m) ? ["crawler"] : /team|agents/.test(m) ? ["marketing_map"] : [];
    return json(res, 200, {reply: actions.length ? "Here it is." : "MAGPPIE makes kitchens from SILVERSTONE. This is a fixture answer.", actions, lane: "quick"});
  }
  if (p === "/api/mai/stt") return json(res, 200, {text: ""});
  if (p === "/api/mai/tts") return json(res, 503, {detail: "No voice in the mock."});
  // enough for the unchanged marketing dashboard to draw itself inside the iframe
  if (p === "/api/status") return json(res, 200, {counts: {kb_core: 65, kb_learned: 0, scripts: 15, seed_sources: 73, discovered_sources: 0, pages: 0, pages_kept: 0, learnings: 0, pending: 0, held: 0, queued: 0}, crawl_running: false, last_run: null, brains: [], manager: "", now: new Date().toISOString()});
  if (p === "/api/ideas/latest") return json(res, 200, {batch: null, ideas: [], creative: {credits_each: 0, formats: {}}});
  if (p === "/api/content") return json(res, 200, {blogs: [], creatives: [], videos: [], in_progress: []});
  if (p === "/api/higgsfield/status") return json(res, 200, {connected: false});
  if (/^\/api\/(notifications|review|learnings|sources|crawl\/runs)$/.test(p)) return json(res, 200, []);
  return json(res, 404, {detail: "Not in the mock."});
}

http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  try {
    if (url.pathname === "/__mock/mode") { mode = url.searchParams.get("m") || "normal"; return json(res, 200, {mode}); }
    if (url.pathname === "/__mock/team") { team = url.searchParams.get("m") || "quiet"; return json(res, 200, {team}); }
    if (url.pathname === "/__mock/calls") return json(res, 200, calls);
    if (url.pathname.startsWith("/api/")) return await api(req, res, url);
    const file = url.pathname === "/" ? HOME_PAGE : url.pathname === "/marketing" ? "index.html" : url.pathname === "/login" ? "login.html"
               : url.pathname.startsWith("/static/") ? url.pathname.slice(8) : null;
    const full = file && path.join(STATIC, file);
    if (!full || !full.startsWith(STATIC)) { res.writeHead(404); return res.end("Not found"); }
    const data = await readFile(full);
    res.writeHead(200, {"Content-Type": TYPES[path.extname(full)] || "application/octet-stream", "Cache-Control": "no-store"}); res.end(data);
  } catch (e) { res.writeHead(e.code === "ENOENT" ? 404 : 500); res.end(String(e.message)); }
}).listen(PORT, "127.0.0.1", () => console.log(`MAGI home mock on http://localhost:${PORT}  (home page: ${HOME_PAGE})`));
