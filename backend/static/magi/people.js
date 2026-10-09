// The people of a department: rigged figures (Quaternius, public domain) who sit at their desks, walk the aisles,
// talk at the board or over coffee, and stand and wave when something waits for you. What each one does follows
// what MAGI says that role is really doing: nobody types at a page unless the role is working.
import * as THREE from "./vendor/three.module.min.js";
import {clone as cloneRig} from "./vendor/utils/SkeletonUtils.js";
import {loadModel, DESKS, SPOTS, route} from "./furnish.js";
import {seatBones, applySeat} from "./seat.js";

const HEIGHT = 3, SCALE = HEIGHT / 1.86, SPEED = 2.5, TURN = 5;
const LOOKS = {crawler: [0xC99A72, 0x2B2320], filter: [0xE6C3A0, 0xB58F4E], knowledge: [0x8D5B3F, 0x1F1A18], strategist: [0xB98562, 0x30241E],
               blog: [0xE1B894, 0x6B4A2E], creative: [0x9C6B4A, 0x241C19], video: [0xD7A982, 0x8A4B2A]};
const rand = (a, b) => a + Math.random() * (b - a);
const turnTo = (from, to, max) => { const d = ((to - from + Math.PI) % (2 * Math.PI) + 2 * Math.PI) % (2 * Math.PI) - Math.PI; return Math.abs(d) <= max ? to : from + Math.sign(d) * max; };

// ---------- the small signs over a head: talking, waiting for you, coffee ----------
const signs = {};
function sign(kind) {
  if (signs[kind]) return signs[kind];
  const c = Object.assign(document.createElement("canvas"), {width: 96, height: 96}), x = c.getContext("2d");
  x.fillStyle = kind === "alert" ? "#D98A55" : "#FFFDF9"; x.strokeStyle = "rgba(27,26,24,.35)"; x.lineWidth = 3;
  x.beginPath(); x.arc(48, 42, 34, 0, 7); x.fill(); x.stroke();
  x.beginPath(); x.moveTo(38, 72); x.lineTo(48, 92); x.lineTo(58, 72); x.fill();
  x.fillStyle = x.strokeStyle = kind === "alert" ? "#FFFFFF" : "#1B1A18"; x.lineCap = "round";
  if (kind === "talk") for (const dx of [-14, 0, 14]) { x.beginPath(); x.arc(48 + dx, 42, 4.5, 0, 7); x.fill(); }
  else if (kind === "alert") { x.fillRect(44, 20, 8, 28); x.beginPath(); x.arc(48, 59, 5, 0, 7); x.fill(); }
  else { x.lineWidth = 5; x.strokeRect(33, 32, 24, 22); x.beginPath(); x.arc(60, 42, 7, -1.4, 1.4); x.stroke(); }   // a cup
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return signs[kind] = t;
}

function makePerson(role, index, gltf) {
  const model = cloneRig(gltf.scene), root = new THREE.Group(), [skin, hair] = LOOKS[role.key] || LOOKS.blog, own = {};
  model.scale.setScalar(SCALE); root.add(model);
  let eyes = null;
  model.traverse(o => {
    if (!o.isMesh) return;
    o.castShadow = true; o.frustumCulled = false;
    const n = o.material.name, m = own[n] || (own[n] = o.material.clone()); o.material = m; m.roughness = .9; m.metalness = 0;
    if (/^Skin/.test(n)) m.color.setHex(skin).multiplyScalar(n === "Skin_Darker" ? .9 : 1);
    if (/^Hair/.test(n) || n === "Eyebrows") m.color.setHex(hair);
    if (n === "Eye") eyes = o;
  });
  const mixer = new THREE.AnimationMixer(model), actions = {};
  gltf.animations.forEach(c => { actions[c.name] = mixer.clipAction(c); });
  const head = model.getObjectByName("Head");

  // a mouth and two eyelids, laid on the face, so it can smile, talk and blink (only where the model names its eyes)
  const face = {mouth: null, lids: []};
  if (eyes && eyes.isSkinnedMesh && head) {
    const inv = eyes.skeleton.boneInverses[eyes.skeleton.bones.indexOf(head)];
    if (inv) {
      eyes.geometry.computeBoundingBox(); const b = eyes.geometry.boundingBox, cy = (b.min.y + b.max.y) / 2, q = new THREE.Quaternion().setFromRotationMatrix(inv);
      const lay = (mesh, x, y, z) => { mesh.position.set(x, y, z).applyMatrix4(inv); mesh.quaternion.copy(q); head.add(mesh); return mesh; };
      face.mouth = lay(new THREE.Mesh(new THREE.PlaneGeometry(.05, .012), new THREE.MeshBasicMaterial({color: 0x4A241C})), 0, cy - .082, b.max.z + .012);
      const lid = new THREE.MeshBasicMaterial({color: own.Skin ? own.Skin.color.clone().multiplyScalar(.82) : 0xB08A68});
      for (const s of [-1, 1]) { const l = lay(new THREE.Mesh(new THREE.PlaneGeometry(.036, .03), lid), s * (b.max.x - .014), cy, b.max.z + .004); l.visible = false; face.lids.push(l); }
    }
  }
  const bubble = new THREE.Sprite(new THREE.SpriteMaterial({map: sign("talk"), transparent: true, opacity: 0, depthTest: false})); bubble.scale.setScalar(1.25); bubble.position.y = HEIGHT + 1.15; bubble.renderOrder = 5;
  const hit = new THREE.Mesh(new THREE.BoxGeometry(1.6, HEIGHT + .3, 1.6), new THREE.MeshBasicMaterial({visible: false})); hit.position.y = HEIGHT / 2; hit.userData.pick = {type: "role", key: role.key};
  root.add(bubble, hit);
  const desk = DESKS[index], home = desk.stand;
  root.position.set(desk.seat.x, 0, desk.seat.z); root.rotation.y = home.yaw;
  return {key: role.key, index, root, model, mixer, actions, head, face, bubble, hit, home, seat: desk.seat, at: home, queue: [], step: null, mode: "idle", playing: null,
          place: null, spot: null, arrived: false, guest: null, expr: "calm", sign: null, blink: rand(1, 5), phase: index * 1.3,
          sit: 1, sitGoal: 1, typing: 0, bones: seatBones(model)};
}

export async function createPeople(parent, roles, {still = false, onLive = () => {}} = {}) {
  const files = await Promise.all(roles.map(r => loadModel(`people/${r.key}.glb`)));
  const group = new THREE.Group(), people = roles.map((r, i) => makePerson(r, i, files[i])), by = Object.fromEntries(people.map(p => [p.key, p]));
  people.forEach(p => group.add(p.root)); parent.add(group);
  const taken = {}, LINE = ["crawler", "filter", "knowledge"];

  function play(p, name, fade = .3) {
    if (p.playing === name || !p.actions[name]) return;
    const next = p.actions[name], prev = p.actions[p.playing];
    next.reset().setEffectiveWeight(1).play(); if (prev) prev.crossFadeTo(next, still ? 0 : fade, false); p.playing = name;
  }
  const walk = (from, to) => ({t: "walk", path: route(from, to), to});
  const act = (anim, dur, more = {}) => ({t: "do", anim, dur, left: dur, ...more});
  function free(p) { if (p.spot) { delete taken[p.spot.key]; p.spot = null; } p.place = null; p.arrived = false; }
  const sitDown = p => p.queue.push({t: "turn", yaw: p.home.yaw}, {t: "sit"});
  function goHome(p) { free(p); p.queue.push(walk(p.at, p.home)); sitDown(p); }
  const seated = p => p.at === p.home && p.sitGoal === 1;
  function plan(p) {
    const home = p.at === p.home;
    if (!home) return goHome(p);
    if (p.mode === "wait") {                                // something of theirs needs you: they stand, turn to you and wave
      if (p.sitGoal) p.queue.push({t: "rise"});
      return p.queue.push({t: "turn", yaw: 0}, act("Wave", 1.67, {expr: "smile", sign: "alert"}), act("Idle_Neutral", rand(2.5, 4), {expr: "smile", sign: "alert"}));
    }
    if (!p.sitGoal) return sitDown(p);
    if (p.mode === "work") {
      const mates = LINE.filter(k => k !== p.key && by[k] && by[k].mode === "work" && seated(by[k]) && !by[k].guest);
      if (LINE.includes(p.key) && mates.length && Math.random() < .14) {                                            // the night's reading passes down this line, so they confer
        const mate = by[mates[Math.floor(Math.random() * mates.length)]], spot = DESKS[mate.index].visit; mate.guest = p;
        return p.queue.push({t: "rise"}, walk(p.home, spot), {t: "turn", yaw: spot.yaw}, act("Idle_Neutral", rand(3.5, 5.5), {talk: mate, expr: "smile"}), {t: "leave", mate}, walk(spot, p.home), {t: "turn", yaw: p.home.yaw}, {t: "sit"});
      }
      return p.queue.push(act("Idle", rand(3, 6), {expr: "focus", typing: 1}), act("Idle", rand(1.5, 3), {expr: "focus", typing: 0}));
    }
    const open = SPOTS.filter(s => !taken[s.key]);
    if (open.length && Math.random() < .4) {
      const s = open[Math.floor(Math.random() * open.length)]; taken[s.key] = p.key; p.spot = s; p.place = s.place;
      p.queue.push({t: "rise"}, walk(p.home, s), {t: "turn", yaw: s.yaw}, {t: "arrive"});
      if (s.use === "pour") p.queue.push(act("Interact", 2, {expr: "calm"}), act("Idle_Neutral", rand(3, 5), {expr: "smile", sign: s.place === "coffee" ? "cup" : null}));
      else p.queue.push(act("Idle_Neutral", rand(6, 10), {social: true, expr: "calm"}));
      return p.queue.push({t: "free"}, walk(s, p.home), {t: "turn", yaw: p.home.yaw}, {t: "sit"});
    }
    p.queue.push(act("Idle_Neutral", rand(4, 8), {expr: "calm", typing: 0}));                                        // at rest in the chair
  }
  function setMode(p, mode) {
    if (p.mode === mode) return;
    p.mode = mode; p.queue = []; if (p.step && p.step.t === "do") p.step = null;      // a walk in progress is finished first
    for (const o of people) if (o.guest === p) o.guest = null;
    if (p.at !== p.home) free(p);
    onLive(p.key, mode === "work");
  }

  const dir = new THREE.Vector3();
  function advance(p, dt) {
    if (!p.step) { if (!p.queue.length) plan(p); p.step = p.queue.shift(); if (!p.step) return; if (p.step.t === "walk") p.at = p.step.to; }
    const s = p.step;
    if (s.t === "walk") {
      play(p, "Walk", .2); p.expr = "calm"; p.sign = null; p.typing = 0;
      const next = s.path[0]; if (!next) { p.step = null; return; }
      dir.set(next.x - p.root.position.x, 0, next.z - p.root.position.z); const d = dir.length(), go = SPEED * dt;
      if (d <= go) { p.root.position.x = next.x; p.root.position.z = next.z; s.path.shift(); if (!s.path.length) p.step = null; return; }
      p.root.position.addScaledVector(dir, go / d); p.root.rotation.y = turnTo(p.root.rotation.y, Math.atan2(dir.x, dir.z), TURN * 1.6 * dt);
    } else if (s.t === "turn") {
      play(p, "Idle_Neutral"); p.root.rotation.y = turnTo(p.root.rotation.y, s.yaw, TURN * dt);
      if (Math.abs(Math.sin((p.root.rotation.y - s.yaw) / 2)) < .02) p.step = null;
    } else if (s.t === "sit" || s.t === "rise") {
      play(p, "Idle"); p.sitGoal = s.t === "sit" ? 1 : 0; p.typing = 0;
      if (Math.abs(p.sit - p.sitGoal) < .03) p.step = null;
    } else if (s.t === "do") {
      play(p, s.anim); p.expr = s.expr || "calm"; p.sign = s.sign || null; p.typing = s.typing || 0;
      if (s.talk && !s.told) {                              // the colleague being visited swivels round to listen
        s.told = true; const m = s.talk;
        m.queue = [{t: "turn", yaw: Math.atan2(p.root.position.x - m.root.position.x, p.root.position.z - m.root.position.z)}, act("Idle_Neutral", s.left, {with: p, expr: "smile"}), {t: "turn", yaw: m.home.yaw}]; m.step = null;
      }
      if ((s.left -= dt) <= 0) p.step = null;
    } else {
      if (s.t === "arrive") p.arrived = true;
      if (s.t === "free") free(p);
      if (s.t === "leave" && s.mate.guest === p) s.mate.guest = null;
      p.step = null;
    }
  }
  function settle(p, dt) {                                  // easing into and out of the chair
    p.sit += (p.sitGoal - p.sit) * Math.min(1, dt * 4.5); p.bubble.position.y = HEIGHT + 1.15 - p.sit * .95;
    if (p.at === p.home && (!p.step || p.step.t !== "walk")) {
      const k = p.sit * p.sit * (3 - 2 * p.sit);
      p.root.position.x = p.home.x + (p.seat.x - p.home.x) * k; p.root.position.z = p.home.z + (p.seat.z - p.home.z) * k;
    }
  }
  function partner(p) {                                     // who this person is talking with right now, if anyone
    const s = p.step; if (!s || s.t !== "do") return null;
    if (s.talk) return s.talk; if (s.with) return s.with;
    return s.social && p.arrived ? people.find(o => o !== p && o.place === p.place && o.arrived && o.step && o.step.social) || null : null;
  }
  function express(p, dt, t) {
    const mate = partner(p), speaking = mate && Math.floor(t / 1.7 + Math.min(p.index, mate.index)) % 2 === (p.index < mate.index ? 0 : 1);
    if (p.face.mouth) {
      const m = p.face.mouth.scale, wide = p.expr === "smile" ? 1.35 : p.expr === "focus" ? .7 : 1;
      const open = speaking ? 1.6 + 1.6 * Math.abs(Math.sin(t * 9 + p.phase)) : p.expr === "smile" ? 1.5 : 1;
      m.x += (wide * (speaking ? .8 : 1) - m.x) * Math.min(1, dt * 10); m.y += (open - m.y) * Math.min(1, dt * 14);
    }
    if ((p.blink -= dt) < 0) p.blink = rand(2.2, 5.5);
    p.face.lids.forEach(l => l.visible = p.blink < .13);
    if (p.head && mate) p.head.rotation.x += speaking ? Math.sin(t * 3.1 + p.phase) * .05 : Math.sin(t * 2.2 + p.phase) * .09 + .04;   // the listener nods
    const want = mate ? (speaking ? "talk" : null) : p.sign, mat = p.bubble.material;
    if (want && mat.map !== sign(want) && mat.opacity < .05) mat.map = sign(want);
    mat.opacity += ((want && mat.map === sign(want) ? 1 : 0) - mat.opacity) * Math.min(1, dt * 8);
  }

  people.forEach(p => { play(p, "Idle", 0); p.mixer.update(p.phase); });
  return {
    group, people,
    setStates(states) { for (const p of people) setMode(p, {working: "work", waiting: "wait"}[(states[p.key] || {}).state] || "idle"); },
    update(dt, t) {
      for (const p of people) {
        if (still) {                                         // reduced motion: everyone holds a pose that still says what they are doing
          const up = p.mode === "wait"; p.sit = up ? 0 : 1; p.root.position.set(up ? p.home.x : p.seat.x, 0, up ? p.home.z : p.seat.z);
          p.root.rotation.y = up ? 0 : p.home.yaw; p.bubble.material.map = sign("alert"); p.bubble.material.opacity = up ? 1 : 0;
          p.mixer.setTime(p.phase); applySeat(p.bones, p.sit, p.mode === "work" ? 1 : 0, 0, p.phase); continue;
        }
        advance(p, dt); settle(p, dt); p.mixer.update(dt); applySeat(p.bones, p.sit, p.typing, t, p.phase); express(p, dt, t);
      }
    },
    anchor(key, out) { const p = by[key]; if (!p) return null; return p.root.getWorldPosition(out).add(dir.set(0, HEIGHT + .55 - p.sit * .95, 0)); },
    hits: people.map(p => p.hit),
    dispose() { people.forEach(p => { p.mixer.stopAllAction(); p.bubble.material.dispose(); }); parent.remove(group); },
  };
}
