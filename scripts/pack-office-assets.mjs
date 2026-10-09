// Prepares the office's 3D assets for the home screen, from two public-domain (CC0) packs:
//   people:    Quaternius "Ultimate Modular Men" and "Ultimate Modular Women"  https://quaternius.com
//   furniture: Kenney "Furniture Kit"                                          https://kenney.nl/assets/furniture-kit
// Each person arrives as a 3 MB .gltf carrying 24 animations (most of them fighting). This keeps the five an
// office needs, drops the pistol, and writes a compact .glb. Furniture is copied as it is.
//   node scripts/pack-office-assets.mjs <folder with the downloaded files>
// The folder holds m_*.gltf / w_*.gltf (see PEOPLE below) and kenney/Models/GLTF format/*.glb.
import {readFileSync, writeFileSync, mkdirSync, copyFileSync} from "node:fs";
import {fileURLToPath} from "node:url";
import path from "node:path";

const SRC = process.argv[2];
if (!SRC) { console.error("Give the folder with the downloaded packs."); process.exit(1); }
const OUT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../backend/static/magi/assets");
const KEEP = ["Idle", "Idle_Neutral", "Interact", "Walk", "Wave"];
const PEOPLE = {crawler: "m_Casual_Hoodie", filter: "w_Casual", knowledge: "m_Suit", strategist: "w_Suit", blog: "m_Casual_2", creative: "w_Formal", video: "m_Beach"};
const FURNITURE = ["desk", "chairDesk", "computerScreen", "computerKeyboard", "computerMouse", "laptop", "pottedPlant", "plantSmall1", "plantSmall2",
                   "kitchenCoffeeMachine", "kitchenBar", "kitchenCabinet", "loungeSofa", "loungeChair", "tableCoffee", "bookcaseOpen", "bookcaseOpenLow",
                   "books", "rugRectangle", "rugRound", "lampRoundFloor", "lampSquareTable", "televisionModern", "trashcan", "sideTable", "cardboardBoxClosed"];

function pack(name) {
  const j = JSON.parse(readFileSync(path.join(SRC, name + ".gltf"), "utf8"));
  const bufs = j.buffers.map(b => Buffer.from(b.uri.slice(b.uri.indexOf(",") + 1), "base64"));
  j.animations = (j.animations || []).filter(a => KEEP.includes(a.name));
  for (const n of j.nodes) if (/pistol|sword|gun/i.test(n.name || "")) delete n.mesh;
  // keep only the meshes still worn, then only the data they and the kept animations point at
  const meshUsed = [...new Set(j.nodes.filter(n => n.mesh != null).map(n => n.mesh))], meshMap = new Map(meshUsed.map((m, i) => [m, i]));
  j.meshes = meshUsed.map(i => j.meshes[i]);
  for (const n of j.nodes) if (n.mesh != null) n.mesh = meshMap.get(n.mesh);
  const acc = new Set();
  for (const m of j.meshes) for (const p of m.primitives) { Object.values(p.attributes).forEach(a => acc.add(a)); if (p.indices != null) acc.add(p.indices); }
  for (const s of j.skins || []) if (s.inverseBindMatrices != null) acc.add(s.inverseBindMatrices);
  for (const a of j.animations) for (const s of a.samplers) { acc.add(s.input); acc.add(s.output); }
  const accList = [...acc].sort((a, b) => a - b), accMap = new Map(accList.map((a, i) => [a, i]));
  const viewList = [...new Set(accList.map(a => j.accessors[a].bufferView))].sort((a, b) => a - b), viewMap = new Map(viewList.map((v, i) => [v, i]));
  const parts = []; let at = 0;
  const views = viewList.map(v => {
    const old = j.bufferViews[v], bytes = bufs[old.buffer].subarray(old.byteOffset || 0, (old.byteOffset || 0) + old.byteLength);
    const pad = (4 - at % 4) % 4; if (pad) { parts.push(Buffer.alloc(pad)); at += pad; }
    const next = {...old, buffer: 0, byteOffset: at}; parts.push(bytes); at += bytes.length; return next;
  });
  j.accessors = accList.map(a => ({...j.accessors[a], bufferView: viewMap.get(j.accessors[a].bufferView)}));
  j.bufferViews = views;
  for (const m of j.meshes) for (const p of m.primitives) { for (const k in p.attributes) p.attributes[k] = accMap.get(p.attributes[k]); if (p.indices != null) p.indices = accMap.get(p.indices); }
  for (const s of j.skins || []) if (s.inverseBindMatrices != null) s.inverseBindMatrices = accMap.get(s.inverseBindMatrices);
  for (const a of j.animations) for (const s of a.samplers) { s.input = accMap.get(s.input); s.output = accMap.get(s.output); }
  const bin = Buffer.concat(parts, at), binPad = (4 - bin.length % 4) % 4;
  j.buffers = [{byteLength: bin.length}];
  j.asset.copyright = "CC0 1.0, Quaternius (quaternius.com)";
  let json = Buffer.from(JSON.stringify(j), "utf8"); json = Buffer.concat([json, Buffer.alloc((4 - json.length % 4) % 4, 0x20)]);
  const head = Buffer.alloc(12), jh = Buffer.alloc(8), bh = Buffer.alloc(8);
  head.writeUInt32LE(0x46546C67, 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(12 + 8 + json.length + 8 + bin.length + binPad, 8);
  jh.writeUInt32LE(json.length, 0); jh.writeUInt32LE(0x4E4F534A, 4); bh.writeUInt32LE(bin.length + binPad, 0); bh.writeUInt32LE(0x004E4942, 4);
  return Buffer.concat([head, jh, json, bh, bin, Buffer.alloc(binPad)]);
}

mkdirSync(path.join(OUT, "people"), {recursive: true}); mkdirSync(path.join(OUT, "furniture"), {recursive: true});
for (const [role, file] of Object.entries(PEOPLE)) {
  const glb = pack(file); writeFileSync(path.join(OUT, "people", role + ".glb"), glb);
  console.log(`people/${role}.glb  ${(glb.length / 1024).toFixed(0)} KB  (from ${file})`);
}
for (const f of FURNITURE) copyFileSync(path.join(SRC, "kenney/Models/GLTF format", f + ".glb"), path.join(OUT, "furniture", f + ".glb"));
writeFileSync(path.join(OUT, "LICENSES.txt"),
  "people/*.glb     Quaternius, Ultimate Modular Men and Ultimate Modular Women. CC0 1.0 (public domain). https://quaternius.com\n" +
  "furniture/*.glb  Kenney, Furniture Kit 2.0. CC0 1.0 (public domain). https://kenney.nl/assets/furniture-kit\n" +
  "Animations were reduced to Idle, Idle_Neutral, Interact, Walk and Wave by scripts/pack-office-assets.mjs.\n");
console.log(`furniture: ${FURNITURE.length} models copied`);
