// MAGI's home: the office, what is chosen in it, and the way in and out of the marketing dashboard.
import {createScene} from "./scene.js";
import {createVoice} from "./voice.js";
import {fmt, toast, drawDepts, drawDetail, drawStats, createExplorer, wireKnowledge, wireKeys} from "./panels.js";

const $ = id => document.getElementById(id);
const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
const narrow = matchMedia("(max-width: 900px)");
const TABS = ["ideas", "content", "approvals", "crawler"];

let map = null, pick = 0, view = "home", role = null, failed = false, lastTotal = null, loadedAt = null, team = {};

// ---------- the scene (or, where WebGL is missing, the list on its own) ----------
let sc;
try { sc = createScene($("cv"), {still, onPick, onHover: key => { for (const k in roleEls) roleEls[k].classList.toggle("hover", k === key); }}); }
catch (_) { sc = new Proxy({}, {get: () => () => null}); document.body.classList.add("nogl"); $("nogl").hidden = false; }
function onPick(hit) {
  if (hit.type === "role") return selectRole(hit.key);
  hit.index === pick ? openPick() : choose(hit.index, true);
}

// ---------- labels that follow the scene ----------
const labels = $("labels");
let deptEls = [], roleEls = {}, brainBtn = null, brainNote = null, labelSig = "";
function buildLabels() {
  const roles = map.marketing.filter(r => r.key !== "voice");
  const sig = JSON.stringify([map.departments.map(d => [d.key, d.name, !!d.live]), roles.map(r => [r.key, r.name])]);
  if (sig === labelSig) return;
  labelSig = sig; labels.replaceChildren(); roleEls = {};
  deptEls = map.departments.map((d, i) => {
    const b = document.createElement("button"), n = document.createElement("b"), s = document.createElement("i");
    b.type = "button"; b.className = "dl" + (d.live ? " live" : ""); n.textContent = d.name.toUpperCase(); s.textContent = d.live ? "OPEN" : "NOT CONNECTED";
    b.append(n, s); b.setAttribute("aria-label", d.live ? `${d.name}, open` : `${d.name}, not connected`);
    b.addEventListener("click", () => i === pick ? openPick() : choose(i, true));
    labels.appendChild(b); return b;
  });
  roles.forEach(r => {
    const b = document.createElement("button"); b.type = "button"; b.className = "rl"; b.textContent = r.name;
    b.setAttribute("aria-label", `${r.name}: ${r.job}`); b.addEventListener("click", () => selectRole(r.key));
    labels.appendChild(b); roleEls[r.key] = b;
  });
  brainBtn = document.createElement("button"); brainBtn.id = "brainbtn"; brainBtn.type = "button";
  brainBtn.setAttribute("aria-label", "Talk to MAGI: switch the microphone on, wake or sleep");
  brainBtn.addEventListener("click", () => voice.brainClick());
  brainNote = document.createElement("p"); brainNote.id = "brainnote";
  labels.append(brainBtn, brainNote);
}
function placeLabels() {
  if (!map || !brainBtn) return;
  labels.classList.toggle("far", (sc.unit || 0) < 11);
  deptEls.forEach((b, i) => { const a = sc.deptAnchor(i); if (a) b.style.transform = `translate(${a.x.toFixed(1)}px,${a.y.toFixed(1)}px) translate(-50%,${b.classList.contains("live") ? "-100%" : "-50%"})`; });
  for (const key in roleEls) { const a = sc.roleAnchor(key); if (a) roleEls[key].style.transform = `translate(${a.x.toFixed(1)}px,${a.y.toFixed(1)}px) translate(-50%,-100%)`; }
  const c = sc.brainAnchor(); if (!c) return;
  brainBtn.style.width = brainBtn.style.height = (c.r * 2).toFixed(0) + "px";
  brainBtn.style.transform = `translate(${(c.x - c.r).toFixed(1)}px,${(c.y - c.r).toFixed(1)}px)`;
  brainNote.style.transform = `translate(${(c.x - 110).toFixed(1)}px,${(c.y + c.r + 8).toFixed(1)}px)`;
}
sc.onFrame(() => { sc.setMood(voice.mood, voice.level); placeLabels(); });

// ---------- what is chosen ----------
function paint() {
  document.body.classList.toggle("dept", view === "dept");
  deptEls.forEach((b, i) => b.classList.toggle("on", i === pick));
  for (const key in roleEls) { const b = roleEls[key], st = (team[key] || {}).state; b.classList.toggle("on", key === role); b.classList.toggle("working", st === "working"); b.classList.toggle("waiting", st === "waiting"); }
  if (map) drawDepts(map, pick, i => choose(i, true));
  drawDetail({map, pick, role, view, failed, team}, {role: selectRole, enter, dashboard: () => go("ideas"), open: go});
  const d = map && map.departments[pick];
  $("enter").hidden = $("enter-label").hidden = !(d && d.live) || view === "dept";
  $("esc").hidden = $("esc-label").hidden = view !== "dept";
}
function choose(i, show) {
  if (!map) return;
  const n = map.departments.length; pick = ((i % n) + n) % n; role = null;
  if (view === "dept") { view = "home"; sc.focus(null); setHash(""); }
  sc.select(pick); sc.setRole(null);
  if (show) openSide();
  paint();
}
function enter() {
  const d = map && map.departments[pick]; if (!d || !d.live) return;
  view = "dept"; sc.focus(pick); setHash(d.key); paint();
}
function leave() { view = "home"; role = null; sc.focus(null); sc.setRole(null); setHash(""); paint(); }
function openPick() {
  const d = map && map.departments[pick]; if (!d) return;
  if (!d.live) return toast(`${d.name} is not connected yet. MAGI already holds its knowledge; its agents come next.`);
  if (view !== "dept") enter();
}
function selectRole(key) {
  const m = map && map.departments.findIndex(d => d.live); if (m == null || m < 0) return;
  if (pick !== m) { pick = m; sc.select(pick); }
  role = key && key !== role ? key : null;
  if (role && view !== "dept") { view = "dept"; sc.focus(pick); setHash(map.departments[pick].key); }
  sc.setRole(role === "voice" ? null : role);
  if (role) openSide();
  paint();
}
function setHash(h) { try { history.replaceState(null, "", "#" + h); } catch (_) {} }

// ---------- the side panel, and the room the scene has ----------
const side = $("side");
function openSide() { side.classList.remove("shut"); $("sidetab").hidden = true; room(); }
function shutSide() { side.classList.add("shut"); $("sidetab").hidden = false; room(); }
$("sideshut").addEventListener("click", shutSide);
$("sidetab").addEventListener("click", openSide);
function room() {                                           // the scene centres itself in what the panels leave free
  const small = narrow.matches, talk = $("talk");
  sc.setInsets({
    top: 64, bottom: small ? 70 : 54,
    left: small || side.classList.contains("shut") ? 0 : side.offsetWidth + 32,
    right: small || talk.classList.contains("mini") ? 0 : talk.offsetWidth + 32,
  });
}
function resize() { sc.resize(); room(); }
addEventListener("resize", resize);
$("mini").addEventListener("click", () => { $("talk").classList.toggle("mini"); room(); });
if (narrow.matches) { side.classList.add("shut"); $("sidetab").hidden = false; $("talk").classList.add("mini"); }

// ---------- theme ----------
function setTheme(name) {
  document.documentElement.dataset.theme = name; sc.setTheme(name);
  $("theme").setAttribute("aria-label", name === "light" ? "Switch to the dark theme" : "Switch to the light theme");
  try { localStorage.setItem("magi-theme", name); } catch (_) {}
}
$("theme").addEventListener("click", () => setTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light"));
setTheme(document.documentElement.dataset.theme === "light" ? "light" : "dark");

// ---------- opening screens: the marketing dashboard opens inside MAGI, so MAGI keeps listening ----------
const shell = $("shell");
let shellOpen = false, shellTimer = null;
function openShell(tab) {
  if (shellOpen) { try { shell.contentWindow.location.hash = tab; } catch (_) { shell.src = "/marketing#" + tab; } return; }
  shellOpen = true; shell.src = "/marketing#" + tab; shell.hidden = false; $("close").hidden = false;
  document.body.classList.add("shell"); $("talk").classList.add("mini"); explorer.close();
}
function closeShell() {
  clearTimeout(shellTimer);
  if (!shellOpen) return;
  shellOpen = false; shell.hidden = true; shell.src = "about:blank"; $("close").hidden = true;
  document.body.classList.remove("shell"); if (!narrow.matches) $("talk").classList.remove("mini"); room();
}
function go(screen) {
  const m = map ? map.departments.findIndex(d => d.live) : -1;
  if (screen === "home") { closeShell(); if (view !== "home") leave(); return; }
  if (m < 0) return;
  if (pick !== m) { pick = m; role = null; sc.select(pick); }
  if (screen === "marketing_map") { closeShell(); if (view !== "dept") enter(); else paint(); return; }
  const tab = TABS.includes(screen) ? screen : "ideas";
  if (shellOpen) return openShell(tab);
  const wasIn = view === "dept";
  if (!wasIn) enter();                                      // show the team on the way in
  clearTimeout(shellTimer);
  shellTimer = setTimeout(() => openShell(tab), still || wasIn ? 0 : 1100);
}
$("close").addEventListener("click", () => go("home"));

// ---------- talking to MAGI ----------
const voice = createVoice({go, pulse: v => sc.pulse(v)});
function spaceForMic(e) {                                   // the space bar switches the microphone on and off
  if (e.code !== "Space" || e.repeat || e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return false;
  const el = document.activeElement;
  if (el && (/^(INPUT|TEXTAREA|SELECT|BUTTON|A|SUMMARY)$/.test(el.tagName) || el.isContentEditable)) return false;
  e.preventDefault();
  voice.micToggle();
  return true;
}
addEventListener("message", e => {                          // the dashboard inside MAGI passes its space bar on
  if (e.origin === location.origin && e.data === "magi-mic") voice.micToggle();
});
addEventListener("keydown", e => {
  if (spaceForMic(e)) return;
  if (e.key === "Escape") {
    if (keys.close() || explorer.close()) return;
    if (shellOpen) return closeShell();
    if (role) return selectRole(null);
    if (view !== "home") leave();
    return;
  }
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || e.metaKey || e.ctrlKey || e.altKey || !map || shellOpen || explorer.isOpen) return;
  const k = e.key.toLowerCase();                            // A and D (or the arrows) change department; Enter steps inside
  if (k === "a" || k === "arrowleft") { e.preventDefault(); choose(pick - 1); }
  else if (k === "d" || k === "arrowright") { e.preventDefault(); choose(pick + 1); }
  else if (k === "enter" && document.activeElement.tagName !== "BUTTON") { e.preventDefault(); openPick(); }
});
$("keys").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  b.dataset.turn ? choose(pick + +b.dataset.turn) : b.id === "esc" ? leave() : openPick();
});

// ---------- data ----------
const explorer = createExplorer(), keys = wireKeys();
function status(msg) { $("status").hidden = !msg; $("status-text").textContent = msg || ""; }
async function load() {
  let fresh;
  try {
    const r = await fetch("/api/magi/map"); if (!r.ok) throw new Error("map " + r.status);
    fresh = await r.json();
  } catch (e) {
    failed = true;
    status(map ? `MAGI is not answering. Showing what was loaded at ${loadedAt.toLocaleTimeString("en-IN", {hour: "2-digit", minute: "2-digit"})}.`
               : "MAGI is not reachable. Check that it is running, then try again.");
    if (!map) paint();
    throw e;
  }
  failed = false; loadedAt = new Date(); status("");
  const first = !map;
  const changed = first || fresh.dots.length !== map.dots.length || fresh.total !== map.total || fresh.waiting !== map.waiting || fresh.pages !== map.pages ||
                  JSON.stringify(fresh.marketing) !== JSON.stringify(map.marketing) || JSON.stringify(fresh.departments) !== JSON.stringify(map.departments);
  if (lastTotal != null && fresh.total > lastTotal) { sc.pulse(1); toast(`MAGI learned ${fmt(fresh.total - lastTotal)} new piece${fresh.total - lastTotal > 1 ? "s" : ""} of knowledge.`); }
  lastTotal = fresh.total;
  const chosen = map && map.departments[pick] ? map.departments[pick].key : null;
  map = fresh;
  if (!changed) return;
  sc.setData(map); buildLabels(); explorer.setDots(map.dots);
  if (first) {
    pick = Math.max(0, map.departments.findIndex(x => x.live));
    const want = location.hash.slice(1), d = map.departments.findIndex(x => x.key === want && x.live);
    if (d >= 0) { pick = d; view = "dept"; sc.focus(pick); }
  } else {                                                  // a refresh keeps what you had chosen
    const at = map.departments.findIndex(x => x.key === chosen); pick = at >= 0 ? at : 0;
    if (view === "dept" && !(map.departments[pick] || {}).live) { view = "home"; role = null; sc.focus(null); }
    if (view === "dept") sc.focus(pick);
  }
  sc.select(pick);
  brainNote.textContent = map.dots.length ? "" : "MAGI is empty. Drop the knowledge base to begin.";
  drawStats(map, () => explorer.open());
  const held = document.activeElement && $("detail").contains(document.activeElement);
  paint();
  if (held) { const b = $("detail").querySelector("button"); if (b) b.focus(); }
}
// What each role is doing right now. An older MAGI has no such answer; then everyone is simply shown at rest.
async function loadTeam() {
  let next = {};
  try { const r = await fetch("/api/magi/team"); if (r.ok) next = (await r.json()).roles || {}; } catch (_) {}
  if (JSON.stringify(next) === JSON.stringify(team)) return;
  team = next; sc.setTeam(team);
  if (map && !$("detail").contains(document.activeElement)) paint();
}
const reload = () => load().catch(() => {});
wireKnowledge(reload);
$("retry").addEventListener("click", reload);

drawStats(null); paint(); resize();
load().catch(() => {}).finally(() => setTimeout(() => $("boot").classList.add("off"), still ? 0 : 700));
setInterval(() => { if (document.visibilityState === "visible") reload(); }, 20000);
loadTeam(); setInterval(() => { if (document.visibilityState === "visible") loadTeam(); }, 10000);
