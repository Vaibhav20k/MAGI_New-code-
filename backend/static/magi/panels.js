// The panels around the office: the department list and details, the knowledge numbers, the knowledge explorer,
// the fact box, the file drop and the AI key. They only read MAGI's map and call the page back when something is chosen.
import {KIND} from "./office.js";

const $ = id => document.getElementById(id);
export const fmt = n => Number(n || 0).toLocaleString("en-IN");
const cut = (s, n) => s.length > n ? s.slice(0, n - 1) + "…" : s;
function make(tag, text, cls) { const e = document.createElement(tag); if (text != null) e.textContent = text; if (cls) e.className = cls; return e; }

let toastTimer;
export function toast(msg) { const t = $("toast"); t.textContent = msg; t.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => t.hidden = true, 5000); }

// ---------- departments ----------
export function drawDepts(map, pick, onChoose) {
  const box = $("depts");
  if (box.children.length !== map.departments.length) {
    box.replaceChildren(...map.departments.map((d, i) => {
      const b = make("button", d.name); b.type = "button"; b.addEventListener("click", () => onChoose(i)); return b;
    }));
  }
  map.departments.forEach((d, i) => {
    const b = box.children[i];
    b.textContent = d.name; b.className = d.live ? "live" : ""; b.setAttribute("aria-pressed", i === pick);
    b.setAttribute("aria-label", d.live ? `${d.name}, connected` : `${d.name}, not connected`);
  });
}

export function drawDetail(state, act) {
  const box = $("detail"), {map, pick, role, view, failed, team = {}} = state;
  const NOW = {working: "WORKING NOW", waiting: "WAITING FOR YOU", idle: "AT REST"};
  if (!map) {
    if (failed) box.replaceChildren(make("h2", "MAGI IS NOT REACHABLE"), make("p", "The office cannot be shown until MAGI answers.", "dim"));
    else box.replaceChildren(make("h2", "LOADING THE OFFICE"), make("div", null, "skel"), make("div", null, "skel"), make("div", null, "skel"));
    return;
  }
  const d = map.departments[pick]; if (!d) return box.replaceChildren();
  const r = d.live && role && map.marketing.find(a => a.key === role);
  const out = [];
  if (r) {
    const back = make("button", "← " + d.name.toUpperCase(), "back"); back.type = "button"; back.addEventListener("click", () => act.role(null));
    out.push(back, make("div", r.name, "name"));
    const st = team[r.key];
    if (st) {
      out.push(make("div", NOW[st.state] || NOW.idle, "state " + st.state), make("p", st.line, "about"));
      if (st.state === "waiting" && st.opens) { const b = make("button", "OPEN " + st.opens.toUpperCase() + " →", "hbtn solid wide"); b.type = "button"; b.addEventListener("click", () => act.open(st.opens)); out.push(b); }
    }
    out.push(make("p", r.job, st ? "dim" : "about"), make("p", r.does, "dim"), make("p", r.detail || r.stat, "stat"));
    if ((r.tools || []).length) {
      out.push(make("small", "TOOLS"));
      r.tools.forEach(t => { const p = make("p", null, "tool"); p.append(make("b", t), " · " + ((map.tools || {})[t] || "")); out.push(p); });
    }
  } else {
    out.push(make("div", d.name, "name"), make("div", d.live ? "DEPARTMENT OPEN" : "NOT CONNECTED", "state" + (d.live ? " live" : "")));
    if (d.about) out.push(make("p", d.about, "about"));
    if (d.live) {
      const open = make("button", "OPEN MARKETING DASHBOARD →", "hbtn solid wide"); open.type = "button"; open.addEventListener("click", act.dashboard);
      out.push(open);
      if (view !== "dept") { const see = make("button", "SEE THE TEAM", "hbtn wide"); see.type = "button"; see.addEventListener("click", act.enter); out.push(see); }
      out.push(make("small", "THE TEAM"));
      const list = make("div", null, "roles");
      map.marketing.forEach(a => {
        const b = make("button"); b.type = "button"; b.setAttribute("aria-pressed", "false");
        const st = team[a.key]; if (st && st.state !== "idle") b.className = st.state;
        b.append(make("b", a.name), make("span", a.stat), make("em", st && st.state !== "idle" ? st.line : a.job)); b.addEventListener("click", () => act.role(a.key));
        list.appendChild(b);
      });
      out.push(list);
    } else {
      out.push(make("small", "MAGI ALREADY KNOWS"));
      if ((d.knows || []).length) { const ul = make("ul"); d.knows.forEach(k => ul.appendChild(make("li", k))); out.push(ul); }
      else out.push(make("p", "Nothing filed for this department yet.", "dim"));
      out.push(make("p", "Its agents come next. There is nothing to run here yet.", "dim"));
    }
  }
  box.replaceChildren(...out);
}

// ---------- the numbers beside the brain ----------
export function drawStats(map, onExplore) {
  const s = $("stats");
  if (!map) return s.replaceChildren(make("h2", "KNOWLEDGE BRAIN"), make("div", null, "skel"), make("div", null, "skel"));
  const out = [make("h2", "KNOWLEDGE BRAIN"), make("div", fmt(map.total), "big")];
  if (!map.total) out.push(make("p", "MAGI is empty. Drop the knowledge base to begin."));
  else out.push(make("p", "pieces of knowledge" + (map.total > map.dots.length ? ` · ${fmt(map.dots.length)} drawn` : "")));
  const bars = make("div", null, "bars"), max = Math.max(1, ...Object.values(map.kinds || {}));
  for (const k in KIND) {
    const n = (map.kinds || {})[k] || 0; if (!n) continue;
    const b = make("div", null, "bar"), line = make("i");
    line.style.setProperty("--w", Math.max(3, n / max * 100) + "%"); line.style.setProperty("--c", KIND[k][1]);
    b.append(make("span", KIND[k][0]), make("b", fmt(n)), line); bars.appendChild(b);
  }
  out.push(bars);
  const w = make("p"); w.append(make("b", fmt(map.waiting)), " doubts waiting outside, unused until the manager approves");
  const r = make("p"); r.append(make("b", fmt(map.pages)), " pages read · ", make("b", fmt(map.sites)), " sites");
  const go = make("button", "EXPLORE KNOWLEDGE", "hbtn wide"); go.type = "button"; go.disabled = !map.dots.length; go.addEventListener("click", onExplore);
  out.push(w, r, go);
  s.replaceChildren(...out);
}

// ---------- reading the knowledge, one piece at a time ----------
export function createExplorer() {
  const box = $("explore"), q = $("find"), kinds = $("kinds"), list = $("entries");
  let dots = [], kind = null, opener = null;
  function draw() {
    const words = q.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const hits = dots.filter(d => (!kind || d.doc === kind) && words.every(w => (d.section + " " + d.body).toLowerCase().includes(w)));
    $("count").textContent = !dots.length ? "" : hits.length > 80 ? `Showing 80 of ${fmt(hits.length)}. Search to narrow it down.` : `${fmt(hits.length)} of ${fmt(dots.length)} drawn pieces`;
    if (!hits.length) return list.replaceChildren(make("li", dots.length ? "Nothing matches that search." : "MAGI holds no knowledge yet.", "none"));
    list.replaceChildren(...hits.slice(0, 80).map(d => {
      const li = make("li"), b = make("b", (KIND[d.doc] || KIND.core)[0].toUpperCase() + (d.section ? " · " + cut(d.section, 70) : ""));
      li.append(b, d.body + (d.body.length >= 240 ? "…" : "")); return li;
    }));
  }
  function chips() {
    const have = [...new Set(dots.map(d => d.doc))];
    if (kind && !have.includes(kind)) kind = null;
    kinds.replaceChildren(...Object.keys(KIND).filter(k => have.includes(k)).map(k => {
      const b = make("button", KIND[k][0]); b.type = "button"; b.style.setProperty("--c", KIND[k][1]); b.setAttribute("aria-pressed", kind === k);
      b.addEventListener("click", () => { kind = kind === k ? null : k; chips(); draw(); }); return b;
    }));
  }
  q.addEventListener("input", draw);
  const close = () => { if (box.hidden) return false; box.hidden = true; if (opener) opener.focus(); return true; };
  $("explore-close").addEventListener("click", close);
  return {
    open() { opener = document.activeElement; box.hidden = false; chips(); draw(); q.focus(); },
    close,
    get isOpen() { return !box.hidden; },
    setDots(next) { dots = next; if (!box.hidden) { chips(); draw(); } },
  };
}

// ---------- adding knowledge: a typed fact, or a dropped file ----------
export function wireKnowledge(reload) {
  $("dump").addEventListener("submit", async e => {
    e.preventDefault();
    const v = $("fact").value.trim(); if (v.length < 8) return toast("Type the fact in a full sentence first.");
    try {
      const r = await fetch("/api/review/rule", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({kind: "add_knowledge", content: v})});
      if (!r.ok) return toast("MAGI could not take that in. Try again.");
    } catch (_) { return toast("MAGI could not take that in. Try again."); }
    $("fact").value = ""; reload();
  });
  const stage = $("stage");
  addEventListener("dragover", e => { e.preventDefault(); stage.classList.add("over"); });
  addEventListener("dragleave", e => { if (!e.relatedTarget) stage.classList.remove("over"); });
  addEventListener("drop", async e => {
    e.preventDefault(); stage.classList.remove("over");
    const f = e.dataTransfer.files[0]; if (!f) return;
    const body = new FormData(); body.append("file", f); toast(`MAGI is reading ${f.name}…`);
    try {
      const r = await fetch("/api/magi/drop", {method: "POST", body}), d = await r.json().catch(() => ({}));
      if (!r.ok) return toast(d.detail || "MAGI could not read that file.");
    } catch (_) { return toast("MAGI could not read that file."); }
    reload();
  });
}

// ---------- a new AI key, typed here when the free one runs out ----------
export function wireKeys() {
  async function keyState() {
    try {
      const g = (await (await fetch("/api/keys")).json()).gemini, b = $("keybtn");
      const plain = g.saved && !g.resting;
      b.classList.toggle("warn", !plain); b.classList.toggle("accent", plain);
      b.textContent = !g.saved ? "ADD A GEMINI KEY" : g.resting ? "GEMINI IS USED UP · ADD A KEY" : "AI KEY";
    } catch (e) { /* the button stays as it is */ }
  }
  const box = $("keybox");
  const close = () => { if (box.hidden) return false; box.hidden = true; $("keyval").value = ""; $("keybtn").setAttribute("aria-expanded", "false"); return true; };
  $("keybtn").addEventListener("click", () => { box.hidden = !box.hidden; $("keybtn").setAttribute("aria-expanded", !box.hidden); if (!box.hidden) $("keyval").focus(); });
  $("keyclose").addEventListener("click", close);
  box.addEventListener("submit", async e => {
    e.preventDefault();
    const value = $("keyval").value.trim();
    if (!value) return;
    $("keynote").textContent = "Checking the key with Google…";
    let r, d = {};
    try {
      r = await fetch("/api/keys/gemini", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({value})});
      d = await r.json().catch(() => ({}));
    } catch (_) { r = {ok: false}; }
    $("keyval").value = "";
    if (!r.ok) { $("keynote").textContent = d.detail || "The key could not be saved."; return; }
    $("keynote").textContent = "Saved. MAGI is using the new key now.";
    setTimeout(close, 1800);
    keyState();
  });
  keyState(); setInterval(keyState, 60000);
  return {close};
}
