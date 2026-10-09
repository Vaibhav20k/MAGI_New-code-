// The marketing office itself: where the desks, the coffee counter, the board and the lounge stand, the furniture
// placed there (Kenney's public-domain Furniture Kit, recoloured to MAGPPIE's stone, wood and copper), and the
// screens on the desks. Everything is laid out in the platform's own space: +z is the edge nearest the viewer.
import * as THREE from "./vendor/three.module.min.js";
import {GLTFLoader} from "./vendor/loaders/GLTFLoader.js";

export const OFFICE = {w: 28, depth: 20};
const FS = 3.2;                                            // the kit is modelled at half scale against the people
const DESK_H = 1;
const BACK = -3.6, FRONT = 4.2;
const CHAIR_TURN = Math.PI;                                // the kit's chair faces +z; ours face their desks
// One desk per seat, in the order the roles arrive. A person sits on the near side, facing the screens; `stand` is
// where they get up to, beside the chair, and `visit` is where a colleague stops to talk.
export const DESKS = [[-10.5, BACK], [-3.5, BACK], [3.5, BACK], [10.5, BACK], [-9, FRONT], [-2.5, FRONT], [4, FRONT]].map(([x, z]) => {
  const aisle = z < 0 ? "mid" : "front";
  return {x, z, seat: {x, z: z + 1.3}, stand: {x: x + 1.2, z: z + 1.9, yaw: Math.PI, aisle}, visit: {x: x + 2.1, z: z + 2.1, yaw: -Math.PI / 2, aisle}};
});
// Places people go when they are not at a desk. Two people at the same place talk to each other.
export const SPOTS = [
  {key: "coffee", place: "coffee", x: -10.6, z: -7.0, yaw: Math.PI, aisle: "back", use: "pour"},
  {key: "board1", place: "board", x: -1.0, z: -7.0, yaw: 2.6, aisle: "back", use: "look"},
  {key: "board2", place: "board", x: 2.0, z: -7.0, yaw: -2.6, aisle: "back", use: "look"},
  {key: "books", place: "books", x: 9.6, z: -7.1, yaw: Math.PI, aisle: "back", use: "pour"},
  {key: "lounge1", place: "lounge", x: 8.9, z: 3.6, yaw: 0.35, aisle: "front", use: "look"},
  {key: "lounge2", place: "lounge", x: 9.6, z: 7.2, yaw: 2.8, aisle: "front", use: "look"},
];
const AISLE = {back: -6.9, mid: 1.0, front: 7.7};
const GAPS = {"back|mid": [-7, 0, 7], "mid|front": [-5.75, 0.75, 7.2]};
// The way from one standing place to another: out to the aisle, along it, through a gap between desks, and in.
export function route(from, to) {
  const order = ["back", "mid", "front"], a = order.indexOf(from.aisle), b = order.indexOf(to.aisle), pts = [];
  let x = from.x; pts.push({x, z: AISLE[from.aisle]});
  for (let i = a; i !== b; i += Math.sign(b - a)) {
    const next = i + Math.sign(b - a), gaps = GAPS[[order[Math.min(i, next)], order[Math.max(i, next)]].join("|")];
    const gx = gaps.reduce((best, g) => Math.abs(g - x) + Math.abs(g - to.x) < Math.abs(best - x) + Math.abs(best - to.x) ? g : best);
    pts.push({x: gx, z: AISLE[order[i]]}, {x: gx, z: AISLE[order[next]]}); x = gx;
  }
  pts.push({x: to.x, z: AISLE[to.aisle]}, {x: to.x, z: to.z});
  return pts.filter((p, i) => i === 0 || Math.hypot(p.x - pts[i - 1].x, p.z - pts[i - 1].z) > .05);
}

const TONES = {
  dark: {wood: 0x8A6242, woodDark: 0x5E412B, metal: 0x9EA4AE, metalDark: 0x1C1D21, metalMedium: 0x4A4D57, carpet: 0x3A3C45, carpetDarker: 0x2C2D34, carpetWhite: 0xD9DDE3,
         carpetBlue: 0x596070, plant: 0x4F7A52, lamp: 0xFFD79A, _defaultMat: 0xC9CED6, rug: 0x5A4638, rugEdge: 0x3E3028, board: 0xE8EAEE, note: 0xD98A55},
  light: {wood: 0xC9A27A, woodDark: 0x9A7650, metal: 0xD5D8DC, metalDark: 0x2A2B30, metalMedium: 0x6C7078, carpet: 0x4A4C55, carpetDarker: 0x3A3B43, carpetWhite: 0xFAF8F4,
          carpetBlue: 0x7C8494, plant: 0x5F8A5C, lamp: 0xFFE2A8, _defaultMat: 0xECE7DD, rug: 0xC9B79E, rugEdge: 0xA8926F, board: 0xFFFFFF, note: 0xB5622E},
};
const loader = new GLTFLoader(), BASE = new URL("./assets/", import.meta.url), cache = {};
export const loadModel = file => cache[file] || (cache[file] = loader.loadAsync(new URL(file, BASE).href));

export async function furnish(parent, roles) {
  const names = ["desk", "chairDesk", "computerScreen", "computerKeyboard", "computerMouse", "laptop", "pottedPlant", "plantSmall1", "kitchenCoffeeMachine", "kitchenBar", "loungeSofa", "loungeChair",
                 "tableCoffee", "bookcaseOpen", "books", "rugRound", "rugRectangle", "lampRoundFloor", "trashcan", "sideTable"];
  const models = Object.fromEntries(await Promise.all(names.map(async n => [n, (await loadModel(`furniture/${n}.glb`)).scene])));
  const mats = {}, room = new THREE.Group();
  const mat = name => mats[name] || (mats[name] = new THREE.MeshStandardMaterial({roughness: name.startsWith("metal") ? .45 : .85, metalness: name === "metal" ? .35 : .02}));
  // A model, centred on its own footprint and standing on the floor, at x, z, turned by rot. `as` recolours carpet parts.
  function put(name, x, z, rot = 0, {y = 0, sy = 1, s = 1, as = null} = {}) {
    const m = models[name].clone(true), box = new THREE.Box3().setFromObject(m), c = box.getCenter(new THREE.Vector3());
    m.position.set(-c.x, -box.min.y, -c.z);
    m.traverse(o => { if (!o.isMesh) return; const n = o.material.name; o.material = mat(as && /^carpet$/.test(n) ? as : n in TONES.dark ? n : "_defaultMat"); o.castShadow = o.receiveShadow = true; });
    const g = new THREE.Group(); g.add(m); g.scale.set(FS * s, FS * s * sy, FS * s); g.position.set(x, y, z); g.rotation.y = rot; room.add(g);
    return g;
  }
  const slab = (w, h, d, name, x, y, z, rot = 0) => { const b = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat(name)); b.position.set(x, y, z); b.rotation.y = rot; b.castShadow = b.receiveShadow = true; room.add(b); return b; };

  const screens = {};
  DESKS.slice(0, roles.length).forEach((d, i) => {
    put("desk", d.x, d.z, 0, {sy: DESK_H});
    const top = .38 * FS * DESK_H;
    put("computerKeyboard", d.x, d.z + .35, 0, {y: top}); put("computerMouse", d.x + .75, d.z + .35, 0, {y: top});
    const pair = [-.72, .72].map(off => {                   // two screens, turned in a little, so the person does not hide them
      const g = put("computerScreen", d.x + off, d.z - .42, off < 0 ? .22 : -.22, {y: top, s: 1.12});
      const tex = new THREE.CanvasTexture(Object.assign(document.createElement("canvas"), {width: 160, height: 112})); tex.colorSpace = THREE.SRGBColorSpace;
      const face = new THREE.Mesh(new THREE.PlaneGeometry(.335, .2), new THREE.MeshBasicMaterial({map: tex, toneMapped: false}));
      face.position.set(0, .178, .052); g.add(face);       // sits just in front of the glass, in the kit's own units
      return {tex, face};
    });
    screens[roles[i].key] = pair;
    if (i % 3 === 1) put("plantSmall1", d.x - 1.0, d.z - .1, 0, {y: top});
    put("chairDesk", d.seat.x, d.seat.z + .12, CHAIR_TURN, {as: "carpet"});
  });
  // the back wall: coffee, the board, the books
  put("kitchenBar", -11.6, -8.8, 0); put("kitchenBar", -10.2, -8.8, 0); put("kitchenCoffeeMachine", -11.4, -8.8, 0, {y: .42 * FS});
  slab(.12, 2.6, .12, "metalMedium", -2.1, 1.3, -9.1); slab(.12, 2.6, .12, "metalMedium", 3.1, 1.3, -9.1);
  slab(5.6, 2.3, .1, "board", .5, 2.35, -9.1); slab(5.8, .1, .16, "note", .5, 1.17, -9.08);
  [[-1.4, 2.9], [-.7, 2.3], [.3, 2.95], [1.5, 2.5], [2.3, 3.0]].forEach(([x, y], i) => slab(.5, .5, .04, i % 2 ? "lamp" : "note", x, y, -9.03));
  put("bookcaseOpen", 9.0, -9.0, 0); put("bookcaseOpen", 10.4, -9.0, 0);
  [[9.0, .12], [10.4, .12], [9.0, 1.0], [10.4, 1.9]].forEach(([x, y]) => put("books", x, -9.0, 0, {y: y * 1}));
  // the lounge, near the viewer on the right
  put("rugRound", 10.4, 5.6, 0, {as: "rug", s: 1.25}); put("loungeSofa", 12.4, 5.6, -Math.PI / 2, {as: "carpet"}); put("tableCoffee", 10.2, 5.6, Math.PI / 2);
  put("laptop", 10.2, 5.4, .5, {y: .23 * FS, s: .7}); put("lampRoundFloor", 12.9, 8.9, 0, {s: 1.1});
  put("pottedPlant", -13, 8.7, 0, {s: 1.2}); put("pottedPlant", 13, -8.9, 0, {s: 1.2}); put("pottedPlant", -13.1, -5.6, 0); put("trashcan", -8.9, -8.9, 0, {s: .55});
  parent.add(room);

  // ---------- what the screens show: a page being read while the role really works, a dim standby otherwise ----------
  const live = {};
  function drawScreen(key, t, theme) {
    const pair = screens[key]; if (!pair) return;
    const on = !!live[key];
    pair.forEach(({tex}, side) => {
      const c = tex.image, x = c.getContext("2d"), W = c.width, H = c.height;
      x.fillStyle = on ? "#F7F5F0" : "#15161A"; x.fillRect(0, 0, W, H);
      if (!on) { x.fillStyle = "#C77B4A"; x.fillRect(W / 2 - 16, H / 2 - 1, 32, 2); tex.needsUpdate = true; return; }
      x.fillStyle = "#E3DED4"; x.fillRect(0, 0, W, 16); x.fillStyle = "#FFFFFF"; x.fillRect(22, 4, W - 60, 8);
      x.fillStyle = "#C77B4A"; x.fillRect(6, 5, 6, 6);
      const scroll = (t * (side ? 9 : 14) + side * 40) % 60;                             // the page moves as it is read
      for (let r = 0; r < 9; r++) {
        const y = 24 + r * 15 - scroll; if (y < 18 || y > H - 6) continue;
        const kind = (r + side) % 4;
        if (kind === 0) { x.fillStyle = "#1B1A18"; x.fillRect(10, y, 70 + (r * 17) % 40, 5); }
        else if (kind === 3 && side) { x.fillStyle = "#D9C9B2"; x.fillRect(10, y, 46, 12); x.fillStyle = "#A8A29A"; x.fillRect(62, y + 1, 70, 3); x.fillRect(62, y + 7, 52, 3); }
        else { x.fillStyle = "#A8A29A"; x.fillRect(10, y, 100 + (r * 29) % 40, 3); x.fillRect(10, y + 6, 70 + (r * 13) % 50, 3); }
      }
      tex.needsUpdate = true;
    });
  }
  return {
    room,
    setTheme(name) { const t = TONES[name] || TONES.dark; for (const k in mats) mats[k].color.setHex(t[k] ?? t._defaultMat); mat("lamp").emissive.setHex(t.lamp); mat("lamp").emissiveIntensity = name === "dark" ? .9 : .25; },
    setLive(key, on) { if (!!live[key] !== !!on) { live[key] = !!on; drawScreen(key, 0); } },
    tick(t) { for (const key in live) if (live[key]) drawScreen(key, t); },
    drawAll() { for (const key in screens) drawScreen(key, 0); },
    dispose() { room.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material && o.material.map) o.material.map.dispose(); }); for (const k in mats) mats[k].dispose(); parent.remove(room); },
  };
}
