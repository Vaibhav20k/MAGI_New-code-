// The pieces of the office: stone platforms, walkways, desks, the people of a department, and MAGI's brain.
import * as THREE from "./vendor/three.module.min.js";

export const KIND = {core: ["Company knowledge", "#D98A55"], brand: ["Brand identity", "#F0C9A8"], internal: ["Team only", "#8E96A3"],
                     learned: ["Learned from the web", "#C9CED6"], manager: ["Added by the team", "#FFFFFF"], script_bank: ["Scripts and prompts", "#A8794F"]};
// On ivory stone the pale kinds would vanish, so the light theme uses deeper tones of the same family.
const KIND_LIGHT = {core: "#B5622E", brand: "#C28A5E", internal: "#6F7783", learned: "#8A9099", manager: "#2B2A28", script_bank: "#7A5632"};

export const PALETTES = {
  dark: {top: 0x4A4C55, base: 0x2A2B31, idleTop: 0x383A41, idleBase: 0x222328, walk: 0x33353B, dais: 0x3E4047, desk: 0x5A5C66, deskTop: 0x777A85,
         slate: 0x15161A, body: 0x6B6F7B, head: 0xD9DDE3, copper: 0xD98A55, silver: 0xC9CED6, glass: 0x241E2A, vein: 0xD68C5C,
         hemiSky: 0xAAB2C2, hemiGround: 0x17171B, hemi: 1.5, key: 0xFFE4C8, keyPower: 3.1, shadow: .5},
  light: {top: 0xF4F0E8, base: 0xD9D2C4, idleTop: 0xE9E4DA, idleBase: 0xD3CCBE, walk: 0xE4DED2, dais: 0xECE7DD, desk: 0xCFC7B8, deskTop: 0xFBF8F2,
          slate: 0x3A3B41, body: 0x8A8F98, head: 0xF1E9DD, copper: 0xB5622E, silver: 0x8A9099, glass: 0xD9D2C4, vein: 0xB5622E,
          hemiSky: 0xFFFFFF, hemiGround: 0xD8D2C6, hemi: 1.05, key: 0xFFF4E4, keyPower: 2.1, shadow: .16},
};

export function makeMaterials() {
  const std = (o = {}) => new THREE.MeshStandardMaterial({roughness: .82, metalness: .04, ...o});
  return {
    top: std(), base: std(), idleTop: std(), idleBase: std(), walk: std(), dais: std(), desk: std(), deskTop: std({roughness: .6}),
    slate: std({roughness: .35, metalness: .2}), body: std(), head: std({roughness: .7}),
    copper: std({roughness: .38, metalness: .65}), silver: std({roughness: .4, metalness: .6}),
    glass: std({transparent: true, opacity: .24, roughness: .08, metalness: .25, depthWrite: false}),
    edgeLive: new THREE.LineBasicMaterial({transparent: true}), edgeIdle: new THREE.LineBasicMaterial({transparent: true}),
  };
}
export function applyPalette(m, p) {
  for (const k of ["top", "base", "idleTop", "idleBase", "walk", "dais", "desk", "deskTop", "slate", "body", "head", "copper", "silver", "glass"]) m[k].color.setHex(p[k]);
  m.edgeLive.color.setHex(p.copper); m.edgeIdle.color.setHex(p.silver);
}

export const box = (w, h, d, mat, x = 0, y = 0, z = 0) => { const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat); b.position.set(x, y, z); b.castShadow = b.receiveShadow = true; return b; };

// A raised slab with its own walkway to the centre. Local +z points away from the brain.
export function buildPlatform(m, {live, w, d, reach}) {
  const g = new THREE.Group();
  const slab = box(w, .5, d, live ? m.top : m.idleTop, 0, -.25, 0);
  g.add(slab, box(w - .7, 1.3, d - .7, live ? m.base : m.idleBase, 0, -1.15, 0));
  const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(w + .04, .54, d + .04)), (live ? m.edgeLive : m.edgeIdle).clone());
  edge.position.y = -.25; g.add(edge);
  if (reach > 0) { const path = box(2.6, .3, reach, m.walk, 0, -.55, -(d / 2 + reach / 2)); path.castShadow = false; g.add(path); }
  if (live) g.add(box(w - 3, .06, .16, m.copper, 0, .03, -d / 2 + .9));     // the copper vein along the inner edge
  return {group: g, slab, edge};
}

export function buildDesk(m) {
  const g = new THREE.Group();
  g.add(box(3.4, .18, 1.6, m.deskTop, 0, 1.5, 0), box(.2, 1.42, 1.4, m.desk, -1.5, .71, 0), box(.2, 1.42, 1.4, m.desk, 1.5, .71, 0),
        box(2.8, .9, .1, m.desk, 0, .95, .6));
  const slate = box(1.3, .07, .9, m.slate, 0, 1.63, .05);                  // a slate lying on the desk, not a screen full of pretend work
  slate.rotation.x = -.12; g.add(slate);
  return g;
}

// A stone figure, more chess piece than person: tapered body, copper collar, round head.
export function buildFigure(m) {
  const g = new THREE.Group();
  const body = new THREE.Mesh(new THREE.CylinderGeometry(.3, .62, 1.5, 20), m.body); body.position.y = 1.05;
  const foot = new THREE.Mesh(new THREE.CylinderGeometry(.68, .72, .22, 20), m.body); foot.position.y = .21;
  const collar = new THREE.Mesh(new THREE.TorusGeometry(.33, .07, 8, 24), m.copper); collar.rotation.x = Math.PI / 2; collar.position.y = 1.82;
  const head = new THREE.Mesh(new THREE.SphereGeometry(.42, 24, 16), m.head); head.position.y = 2.3;
  for (const p of [body, foot, collar, head]) { p.castShadow = true; g.add(p); }
  g.userData.head = head;
  return g;
}

export function buildDais(m) {
  const g = new THREE.Group();
  const low = new THREE.Mesh(new THREE.CylinderGeometry(9, 9.3, 1.7, 56), m.dais); low.position.y = -.95;
  const mid = new THREE.Mesh(new THREE.CylinderGeometry(6.2, 6.5, .7, 56), m.top); mid.position.y = .25;
  const rim = new THREE.Mesh(new THREE.TorusGeometry(6.2, .06, 8, 72), m.copper); rim.rotation.x = Math.PI / 2; rim.position.y = .6;
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(.5, 1.6, 3, 24), m.base); stem.position.y = 2.1;
  for (const p of [low, mid, stem]) { p.castShadow = p.receiveShadow = true; g.add(p); }
  g.add(rim);
  return g;
}

// ---------- the brain: every dot is one piece of knowledge, every line joins two that are close in meaning ----------
function rng(seed) { let s = seed >>> 0 || 1; return () => (s = (s * 1664525 + 1013904223) >>> 0) / 4294967296; }
function hash(str) { let h = 2166136261; for (const c of String(str)) h = Math.imul(h ^ c.charCodeAt(0), 16777619); return h >>> 0; }
export function dotPositions(dots) {                       // the same placement the old home used: topics gather into clusters
  const sizes = {};
  dots.forEach(d => { const k = d.doc + "|" + d.section; sizes[k] = (sizes[k] || 0) + 1; });
  return dots.map(d => {
    const key = d.doc + "|" + d.section, parts = Math.ceil(sizes[key] / 14);
    const group = rng(hash(key + "|" + d.id % parts)), own = rng(d.id * 7919 + 13);
    const unit = r => { const u = r() * 2 - 1, a = r() * Math.PI * 2, s = Math.sqrt(1 - u * u); return [s * Math.cos(a), u, s * Math.sin(a)]; };
    const c = unit(group), o = unit(own), spread = .16 + own() * .3, far = .35 + group() * .42;
    let p = [c[0] * far + o[0] * spread, c[1] * far + o[1] * spread, c[2] * far + o[2] * spread];
    const len = Math.hypot(...p); if (len > .97) p = p.map(v => v / len * .97);
    return p;
  });
}

export const BRAIN_Y = 10.4, BRAIN_R = 6.4;
export function buildBrain(m, still) {
  const group = new THREE.Group(); group.position.y = BRAIN_Y;
  const glass = new THREE.Mesh(new THREE.SphereGeometry(BRAIN_R, 48, 32), m.glass); glass.renderOrder = 1;
  const spin = new THREE.Group();
  const pointsMat = new THREE.PointsMaterial({size: 5, sizeAttenuation: false, vertexColors: true, transparent: true, depthWrite: false});
  const points = new THREE.Points(new THREE.BufferGeometry(), pointsMat);
  const linesMat = new THREE.LineBasicMaterial({transparent: true, opacity: .26, depthWrite: false});
  const lines = new THREE.LineSegments(new THREE.BufferGeometry(), linesMat);
  spin.add(lines, points);
  const waitMat = new THREE.PointsMaterial({size: 2.4, sizeAttenuation: false, transparent: true, opacity: .55, depthWrite: false});
  const waiting = new THREE.Points(new THREE.BufferGeometry(), waitMat);        // doubts wait outside until the manager approves them
  const face = new THREE.Group();                                               // always turned to the viewer
  const ringMat = new THREE.MeshBasicMaterial({transparent: true, depthWrite: false});
  const ring = new THREE.Mesh(new THREE.TorusGeometry(BRAIN_R * 1.13, .06, 8, 120), ringMat);
  const ripples = [0, 1, 2].map(() => { const r = new THREE.Mesh(ring.geometry, new THREE.MeshBasicMaterial({transparent: true, opacity: 0, depthWrite: false})); r.userData.life = 0; face.add(r); return r; });
  face.add(ring);
  group.add(glass, spin, waiting, face);

  let palette = PALETTES.dark, theme = "dark", lastDots = [], mood = "off", level = 1, t = 0, sinceRipple = 0;
  function colour() {
    linesMat.color.setHex(palette.vein); waitMat.color.setHex(palette.silver);
    ripples.forEach(r => r.material.color.setHex(palette.copper));
    paint();
  }
  function paint() {
    const n = lastDots.length, col = new Float32Array(n * 3), c = new THREE.Color();
    lastDots.forEach((d, i) => { c.set(theme === "light" ? KIND_LIGHT[d.doc] || KIND_LIGHT.core : (KIND[d.doc] || KIND.core)[1]); col.set([c.r, c.g, c.b], i * 3); });
    points.geometry.setAttribute("color", new THREE.BufferAttribute(col, 3));
  }
  return {
    group,
    setTheme(name, p) { theme = name; palette = p; colour(); },
    setDots(dots, waitingCount) {
      lastDots = dots;
      const pos = dotPositions(dots), at = {}, flat = new Float32Array(dots.length * 3);
      const R = BRAIN_R * .92;
      dots.forEach((d, i) => { at[d.id] = i; flat.set(pos[i].map(v => v * R), i * 3); });
      points.geometry.dispose(); points.geometry = new THREE.BufferGeometry();
      points.geometry.setAttribute("position", new THREE.BufferAttribute(flat, 3));
      const seg = [];
      dots.forEach((d, i) => (d.links || []).forEach(id => { const j = at[id]; if (j != null) seg.push(flat[i * 3], flat[i * 3 + 1], flat[i * 3 + 2], flat[j * 3], flat[j * 3 + 1], flat[j * 3 + 2]); }));
      lines.geometry.dispose(); lines.geometry = new THREE.BufferGeometry();
      lines.geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(seg), 3));
      const w = Math.min(110, waitingCount || 0), wp = new Float32Array(w * 3);
      for (let i = 0; i < w; i++) { const a = i * 2.39996, rr = BRAIN_R * (1.3 + (i % 7) * .02); wp.set([Math.cos(a) * rr, ((i % 5) - 2) * .22, Math.sin(a) * rr], i * 3); }
      waiting.geometry.dispose(); waiting.geometry = new THREE.BufferGeometry();
      waiting.geometry.setAttribute("position", new THREE.BufferAttribute(wp, 3));
      paint();
    },
    setMood(s, l) { mood = s; level = l; },
    pulse(v = 1) { const r = ripples.find(x => x.userData.life <= 0) || ripples[0]; r.userData.life = v; },
    tick(dt, camera) {
      t += dt;
      if (!still) { spin.rotation.y += dt * (mood === "thinking" ? .84 : .13); waiting.rotation.y -= dt * .05; }
      face.quaternion.copy(camera.quaternion);
      const live = mood !== "off" && mood !== "asleep";
      ringMat.color.setHex(live ? palette.copper : palette.silver);
      ringMat.opacity = live ? (mood === "thinking" ? .55 + .4 * Math.sin(t * 8.5) : .98) : mood === "asleep" ? .7 : .45;
      const s = mood === "hearing" || mood === "listening" ? level : 1;
      ring.scale.setScalar(ring.scale.x + (s - ring.scale.x) * Math.min(1, dt * 18));
      if (mood === "speaking" && !still) { sinceRipple += dt; if (sinceRipple > .43) { sinceRipple = 0; this.pulse(.8); } }
      for (const r of ripples) {
        if (r.userData.life <= 0) { r.material.opacity = 0; continue; }
        r.scale.setScalar(1 + (1 - r.userData.life) * .5); r.material.opacity = r.userData.life * .9;
        r.userData.life -= dt * .84;
      }
    },
  };
}
