// The office as a whole: the stage, the camera, the light, and what is chosen. The page tells it what to show;
// it tells the page what was clicked and where things are on screen, so the labels can follow.
import * as THREE from "./vendor/three.module.min.js";
import {PALETTES, makeMaterials, applyPalette, buildPlatform, buildDesk, buildFigure, buildDais, buildBrain, box, BRAIN_Y, BRAIN_R} from "./office.js";
import {OFFICE, DESKS, furnish} from "./furnish.js";
import {createPeople} from "./people.js";

// The campus: the brain in the middle, the connected department large at the front, the others on a grid around it.
// Positions are across (u, to the viewer's right) and toward the viewer (v); each comes with the walkway that reaches it.
const BIG = {u: 0, v: 25, path: [0, 9, 0, 15]};
const SLOTS = [[26, 25, [14, 25, 19.5, 25]], [22, 0, [9, 0, 15.5, 0]], [22, -18, [22, -12.5, 22, -5.5]], [22, -35, [22, -29.5, 22, -23.5]], [0, -35, [0, -29.5, 0, -9]],
               [-22, -35, [-22, -29.5, -22, -23.5]], [-22, -18, [-22, -12.5, -22, -5.5]], [-22, 0, [-15.5, 0, -9, 0]], [-26, 25, [-19.5, 25, -14, 25]]].map(([u, v, path]) => ({u, v, path}));
const SPAN = {u: 36, v0: -41, v1: 35.5};
const VIEW_DIR = new THREE.Vector3(1, 1.3, 1).normalize();   // looking down at about 43 degrees

export function createScene(canvas, {still = false, onPick = () => {}, onHover = () => {}} = {}) {
  const renderer = new THREE.WebGLRenderer({canvas, antialias: true, alpha: true});      // throws where WebGL is missing; the page then shows its list
  let sharp = Math.min(2, devicePixelRatio || 1);
  renderer.setPixelRatio(sharp);
  renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFShadowMap;
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -400, 800);
  const hemi = new THREE.HemisphereLight(), key = new THREE.DirectionalLight();
  key.position.set(-46, 84, 26); key.castShadow = true; key.shadow.mapSize.set(2048, 2048); key.shadow.bias = -.0005; key.shadow.radius = 5;
  Object.assign(key.shadow.camera, {left: -62, right: 62, top: 62, bottom: -62, near: 1, far: 260});
  const groundMat = new THREE.ShadowMaterial({transparent: true});
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(420, 420), groundMat); ground.rotation.x = -Math.PI / 2; ground.position.y = -1.86; ground.receiveShadow = true;
  scene.add(hemi, key, ground);

  const mats = makeMaterials();
  let palette = PALETTES.dark, themeName = "dark";
  const brain = buildBrain(mats, still);
  const world = new THREE.Group(), office = new THREE.Group();
  office.rotation.y = Math.PI / 4;                          // the grid lies square to the viewer
  world.add(buildDais(mats), brain.group, office); scene.add(world);
  const marker = new THREE.Mesh(new THREE.TorusGeometry(1.15, .06, 8, 40), mats.copper); marker.rotation.x = Math.PI / 2; marker.visible = false; world.add(marker);

  let plats = [], figures = {}, pickables = [], deptSig = "", dotSig = "";
  let crew = null, room = null, team = {}, built = 0, screenDue = 0;         // the people and furniture of the connected department, once loaded
  let selected = -1, focus = null, role = null;
  let W = 1, H = 1, insets = {left: 0, right: 0, top: 0, bottom: 0};
  const cur = {x: 0, y: 2.5, z: 0, half: 60}, goal = {x: 0, y: 2.5, z: 0, half: 60};
  let settled = false;

  function clearOffice() {
    office.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.isLineSegments) o.material.dispose(); });
    office.clear(); plats = []; figures = {}; pickables = [];
    if (crew) crew.dispose(); if (room) room.dispose(); crew = room = null; built++;
  }
  function stoneSeats(p, seats, i, depth) {                // the plain stone desks and figures: shown if the real office cannot be loaded
    const rows = Math.max(1, Math.ceil(seats.length / 4));
    seats.forEach((r, s) => {
      const row = Math.floor(s / 4), inRow = Math.min(4, seats.length - row * 4), col = s - row * 4;
      const x = (col - (inRow - 1) / 2) * 5.6, z = (row - (rows - 1) / 2) * 6.6 + .7;
      const desk = buildDesk(mats), fig = buildFigure(mats);
      desk.position.set(x, 0, z); fig.position.set(x, 0, z - 1.35);
      const hit = new THREE.Mesh(new THREE.BoxGeometry(3.8, 3, 3.6), new THREE.MeshBasicMaterial({visible: false})); hit.position.set(x, 1.5, z - .6);
      hit.userData.pick = {type: "role", key: r.key, index: i};
      p.group.add(desk, fig, hit); pickables.push(hit);
      figures[r.key] = {fig, phase: s * 1.7, dept: i};
    });
  }
  async function moveIn(p, seats, i, depth) {               // furnish the connected department and bring its people in
    const mine = built;
    try {
      const [r, c] = await Promise.all([furnish(p.group, seats), createPeople(p.group, seats, {still, onLive: (key, on) => room && room.setLive(key, on)})]);
      if (mine !== built) { r.dispose(); c.dispose(); return; }
      room = r; crew = c; room.setTheme(themeName); room.drawAll();
      crew.hits.forEach(h => { h.userData.pick.index = i; pickables.push(h); });
      crew.setStates(team); for (const m of crew.people) room.setLive(m.key, m.mode === "work");
    } catch (e) { console.warn("The office could not be loaded; showing the plain desks.", e); if (mine === built) stoneSeats(p, seats, i, depth); }
  }
  function buildOffice(departments, roles) {
    clearOffice();
    let big = false, small = 0;
    departments.forEach((d, i) => {
      const seats = d.live ? roles : [];
      const real = d.live && !big && seats.length <= DESKS.length, rows = Math.max(1, Math.ceil(seats.length / 4));
      const slot = real ? BIG : SLOTS[small] || {u: (small % 5 - 2) * 20, v: -52 - Math.floor((small - SLOTS.length) / 5) * 17, path: null};   // more departments than places: further rows behind
      if (real) big = true; else small++;
      const w = real ? OFFICE.w : 13, depth = real ? OFFICE.depth : 11;
      const p = buildPlatform(mats, {live: !!d.live, w, d: depth, reach: 0});
      p.group.position.set(slot.u, 0, slot.v);
      if (slot.path) {
        const [u1, v1, u2, v2] = slot.path, way = box(Math.abs(u2 - u1) + (u1 === u2 ? 2.6 : .6), .3, Math.abs(v2 - v1) + (v1 === v2 ? 2.6 : .6), mats.walk, (u1 + u2) / 2, -.55, (v1 + v2) / 2);
        way.castShadow = false; office.add(way);
      }
      p.slab.userData.pick = {type: "dept", index: i};
      pickables.push(p.slab);
      if (real) moveIn(p, seats, i, depth); else if (d.live) stoneSeats(p, seats.slice(0, 2), i, depth);
      office.add(p.group);
      plats.push({...p, live: !!d.live, w, depth, lift: 0, glow: 0, at: new THREE.Vector3()});
    });
    world.updateMatrixWorld(true);
    plats.forEach(p => p.group.getWorldPosition(p.at));
    paintEdges();
  }
  function paintEdges() { plats.forEach(p => p.edge.material.color.setHex(p.live ? palette.copper : palette.silver)); }

  function aim() {                                          // where the camera should rest for what is chosen
    const Wf = Math.max(220, W - insets.left - insets.right), Hf = Math.max(220, H - insets.top - insets.bottom);
    const p = focus != null && plats[focus];
    if (p) {
      Object.assign(goal, {x: p.at.x, y: 1.2, z: p.at.z});
      goal.half = Math.max((p.w / 2 + 3.5) * H / Wf, (p.depth * .34 + 5.5) * H / Hf);
    } else {
      office.localToWorld(v.set(0, 3, (SPAN.v0 + SPAN.v1) / 2)); Object.assign(goal, {x: v.x, y: v.y, z: v.z});
      goal.half = Math.max(SPAN.u * H / Wf, ((SPAN.v1 - SPAN.v0) * .34 + 8) * H / Hf);
    }
  }
  function frameCamera() {
    const aspect = W / H, per = 2 * cur.half / H;
    const sx = (insets.left - insets.right) / 2 * per, sy = (insets.top - insets.bottom) / 2 * per;
    camera.left = -cur.half * aspect - sx; camera.right = cur.half * aspect - sx; camera.top = cur.half + sy; camera.bottom = -cur.half + sy;
    camera.position.set(cur.x, cur.y, cur.z).addScaledVector(VIEW_DIR, 220); camera.lookAt(cur.x, cur.y, cur.z);
    camera.updateProjectionMatrix(); camera.updateMatrixWorld();
  }
  const v = new THREE.Vector3();
  function toScreen(x, y, z) { v.set(x, y, z).project(camera); return {x: (v.x * .5 + .5) * W, y: (-v.y * .5 + .5) * H}; }

  // ---------- clicks ----------
  const ray = new THREE.Raycaster(), ndc = new THREE.Vector2();
  function hitAt(e) {
    const r = canvas.getBoundingClientRect();
    ndc.set((e.clientX - r.left) / r.width * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const hits = ray.intersectObjects(pickables, false);
    return hits.length ? hits[0].object.userData.pick : null;
  }
  // ---------- moving the view by hand: drag to slide it, scroll or pinch to zoom toward the pointer ----------
  const RIGHT = new THREE.Vector3(1, 0, -1).normalize(), AWAY = new THREE.Vector3(-1, 0, -1).normalize(), TILT = VIEW_DIR.y;   // TILT: how much the ground is foreshortened
  const touches = new Map();
  let down = null, hoverDue = null, hovered = null, dragged = false, pinch = 0;
  canvas.addEventListener("pointerleave", () => { if (hovered) onHover(hovered = null); });
  function slide(dx, dy) {                                  // by screen pixels; the ground follows the pointer
    const per = 2 * cur.half / H;
    for (const o of [cur, goal]) { o.x += (-RIGHT.x * dx + AWAY.x * dy / TILT) * per; o.z += (-RIGHT.z * dx + AWAY.z * dy / TILT) * per; }
    const far = Math.hypot(goal.x, goal.z); if (far > 70) for (const o of [cur, goal]) { o.x *= 70 / far; o.z *= 70 / far; }
  }
  function zoom(k, px, py) {                                // k > 1 comes closer; the point under (px, py) stays where it is
    const before = cur.half, after = Math.min(95, Math.max(7, before / k)); if (after === before) return;
    const r = canvas.getBoundingClientRect(), ox = px - r.left - (W + insets.left - insets.right) / 2, oy = py - r.top - (H + insets.top - insets.bottom) / 2;
    const d = 2 * (before - after) / H;
    for (const o of [cur, goal]) { o.x += (RIGHT.x * ox - AWAY.x * oy / TILT) * d; o.z += (RIGHT.z * ox - AWAY.z * oy / TILT) * d; o.half = after; }
  }
  const spread = () => { const [a, b] = [...touches.values()]; return Math.hypot(a.x - b.x, a.y - b.y); };
  canvas.addEventListener("pointerdown", e => {
    touches.set(e.pointerId, {x: e.clientX, y: e.clientY}); try { canvas.setPointerCapture(e.pointerId); } catch (_) {}
    if (touches.size === 1) { down = {x: e.clientX, y: e.clientY}; dragged = false; } else { dragged = true; pinch = spread(); }
  });
  canvas.addEventListener("pointermove", e => {
    const was = touches.get(e.pointerId);
    if (!was) { hoverDue = e; return; }
    const dx = e.clientX - was.x, dy = e.clientY - was.y; was.x = e.clientX; was.y = e.clientY;
    if (touches.size >= 2) { const now = spread(), [a, b] = [...touches.values()]; if (pinch > 0) zoom(now / pinch, (a.x + b.x) / 2, (a.y + b.y) / 2); pinch = now; return; }
    if (!dragged && down && Math.hypot(e.clientX - down.x, e.clientY - down.y) > 5) { dragged = true; canvas.style.cursor = "grabbing"; }
    if (dragged) slide(dx, dy);
  });
  const lift = e => {
    if (!touches.delete(e.pointerId)) return;
    if (!dragged && e.type === "pointerup") { const hit = hitAt(e); if (hit) onPick(hit); }
    if (!touches.size) { down = null; canvas.style.cursor = ""; } else pinch = 0;
  };
  canvas.addEventListener("pointerup", lift); canvas.addEventListener("pointercancel", lift);
  canvas.addEventListener("wheel", e => { e.preventDefault(); zoom(Math.exp(-e.deltaY * (e.ctrlKey ? .01 : .0016)), e.clientX, e.clientY); }, {passive: false});   // a trackpad pinch arrives as a wheel with ctrl
  canvas.addEventListener("dblclick", e => { if (!hitAt(e)) aim(); });                   // double-click empty space to put the view back

  // ---------- the loop ----------
  const listeners = [];
  let last = 0, slow = 0, t = 0, raf = 0;
  function frame(now) {
    raf = requestAnimationFrame(frame);
    if (document.visibilityState !== "visible") { last = 0; return; }                    // nothing is drawn for a hidden page
    const dt = last ? Math.min(.05, (now - last) / 1000) : .016;
    if (last && sharp > 1) { slow = now - last > 30 ? slow + 1 : Math.max(0, slow - 2); if (slow > 90) { sharp = 1; slow = 0; renderer.setPixelRatio(1); } }   // a slower machine gets a lighter picture
    last = now; t += dt;
    const k = still || !settled ? 1 : 1 - Math.exp(-dt * 5.5);
    for (const a of ["x", "y", "z", "half"]) cur[a] += (goal[a] - cur[a]) * k;
    settled = true;
    frameCamera();
    plats.forEach((p, i) => {
      const lift = i === selected ? .45 : 0, glow = i === selected ? 1 : p.live ? .5 : .16, q = still ? 1 : 1 - Math.exp(-dt * 9);
      p.lift += (lift - p.lift) * q; p.glow += (glow - p.glow) * q;
      p.group.position.y = p.lift; p.edge.material.opacity = p.glow;
    });
    if (!still) for (const key in figures) {                                             // people shift a little; nobody pretends to work
      const f = figures[key]; f.fig.userData.head.rotation.y = Math.sin(t * .45 + f.phase) * .4; f.fig.position.y = Math.sin(t * .9 + f.phase) * .025;
    }
    if (crew) { crew.update(dt, t); if (room && t > screenDue) { screenDue = t + .12; room.tick(t); } }
    const f = role && figures[role], m = role && crew && crew.anchor(role, v);
    marker.visible = !!(f || m);
    if (m) marker.position.set(v.x, .1, v.z);
    else if (f) { f.fig.getWorldPosition(v); marker.position.set(v.x, plats[f.dept].lift + .08, v.z); }
    if (hoverDue) {
      const hit = hitAt(hoverDue), key = hit && hit.type === "role" ? hit.key : null; hoverDue = null;
      canvas.style.cursor = hit ? "pointer" : "grab"; if (key !== hovered) onHover(hovered = key);
    }
    brain.tick(dt, camera);
    renderer.render(scene, camera);
    for (const fn of listeners) fn();
  }

  const api = {
    setData(map) {
      const roles = (map.marketing || []).filter(r => r.key !== "voice");                // MAGI's voice is the brain itself
      const ds = JSON.stringify([map.departments.map(d => [d.key, !!d.live]), roles.map(r => r.key)]);
      if (ds !== deptSig) { deptSig = ds; buildOffice(map.departments, roles); aim(); }
      const dots = map.dots || [], sig = dots.length + ":" + (dots[0] ? dots[0].id : "") + ":" + (dots.length ? dots[dots.length - 1].id : "") + ":" + map.total + ":" + map.waiting;
      if (sig !== dotSig) { dotSig = sig; brain.setDots(dots, map.waiting); }
    },
    setTheme(name) {
      themeName = name; palette = PALETTES[name] || PALETTES.dark;
      applyPalette(mats, palette); paintEdges();
      hemi.color.setHex(palette.hemiSky); hemi.groundColor.setHex(palette.hemiGround); hemi.intensity = palette.hemi;
      key.color.setHex(palette.key); key.intensity = palette.keyPower; groundMat.opacity = palette.shadow;
      mats.glass.opacity = name === "light" ? .3 : .24;
      brain.setTheme(name, palette); if (room) room.setTheme(name);
    },
    setTeam(states) { team = states || {}; if (crew) crew.setStates(team); },
    select(i) { selected = i; },
    focus(i) { focus = i; aim(); },
    setRole(key) { role = key; },
    setMood(mood, level) { brain.setMood(mood, level); },
    pulse(v) { brain.pulse(v); },
    setInsets(next) { insets = next; aim(); },
    resize() {
      const r = canvas.parentElement.getBoundingClientRect();
      W = Math.max(1, r.width); H = Math.max(1, r.height);
      renderer.setSize(W, H, false); aim(); if (still) Object.assign(cur, goal);
    },
    onFrame(fn) { listeners.push(fn); },
    deptAnchor(i) { const p = plats[i]; if (!p) return null; return toScreen(p.at.x, p.lift + (p.live && p.w > 20 ? 6.6 : .1), p.at.z); },
    roleAnchor(key) {
      if (crew && crew.anchor(key, v)) return toScreen(v.x, v.y, v.z);
      const f = figures[key]; if (!f) return null; f.fig.getWorldPosition(v); return toScreen(v.x, v.y + 3.15, v.z);
    },
    brainAnchor() { const c = toScreen(0, BRAIN_Y, 0); return {...c, r: BRAIN_R * 1.2 / (2 * cur.half / H)}; },
    get focused() { return focus; },
    get unit() { return H / (2 * cur.half); },                // how many pixels one step of the floor takes on screen
    get theme() { return themeName; },
    stop() { cancelAnimationFrame(raf); },
  };
  api.setTheme("dark");
  raf = requestAnimationFrame(frame);
  return api;
}
