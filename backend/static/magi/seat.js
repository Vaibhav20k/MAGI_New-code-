// Sitting. The figures come with standing, walking and waving, but no chair. This lays a seated pose over whatever
// the figure is doing: the body drops to the seat, the thighs go forward, the shins hang, the feet rest flat, and the
// forearms reach the desk (and tap at it while typing). `w` blends it in and out as the person sits down or gets up.
import * as THREE from "./vendor/three.module.min.js";

const SEAT_Y = .43;                                        // how high the hips rest, in the figure's own units
const FLAT = {1: new THREE.Quaternion(.704, -.041, .041, .708).normalize(), [-1]: new THREE.Quaternion(.704, .041, -.041, .708).normalize()};
const UP = new THREE.Vector3(0, 1, 0), qm = new THREE.Quaternion(), qw = new THREE.Quaternion(), qp = new THREE.Quaternion(), arc = new THREE.Quaternion();
const cur = new THREE.Vector3(), want = new THREE.Vector3(), spot = new THREE.Vector3();

export function seatBones(model) {
  const g = n => model.getObjectByName(n), side = (u, l, f, s) => ({up: g(u), low: g(l), foot: g(f), s});
  const b = {model, body: g("Body"), legs: [side("UpperLegL", "LowerLegL", "FootL", 1), side("UpperLegR", "LowerLegR", "FootR", -1)],
             arms: [side("UpperArmL", "LowerArmL", null, 1), side("UpperArmR", "LowerArmR", null, -1)], type: 0};
  b.ok = !!(b.body && b.legs.every(l => l.up && l.low && l.foot) && b.arms.every(a => a.up && a.low));
  return b;
}

// Turn a bone so that it points along (x, y, z), given in the figure's own space (it faces +z), by the share w.
function aim(bone, x, y, z, w) {
  bone.getWorldQuaternion(qw); bone.parent.getWorldQuaternion(qp);
  cur.copy(UP).applyQuaternion(qw); want.set(x, y, z).normalize().applyQuaternion(qm);
  arc.setFromUnitVectors(cur, want).multiply(qw);                                        // where the bone should face, in the world
  bone.quaternion.slerp(qp.invert().multiply(arc), w);
}

export function applySeat(b, w, typing, t, phase) {
  if (!b.ok || w < .002) return;
  b.type += (typing - b.type) * .12;
  b.model.getWorldQuaternion(qm);
  b.body.position.y += (SEAT_Y - b.body.position.y) * w;
  for (const l of b.legs) {
    aim(l.up, l.s * .07, -.05, 1, w); aim(l.low, 0, -1, .14, w);
    l.foot.position.lerp(spot.set(l.s * .13, .023, .47), w); l.foot.quaternion.slerp(FLAT[l.s], w);
  }
  const k = b.type;
  for (const a of b.arms) {
    const tap = Math.sin(t * 13 + a.s * 1.7 + phase) * .05 * k;                           // the hands move a little while typing
    aim(a.up, a.s * (.15 + .03 * k), -.95 + .1 * k, .2 + .22 * k, w);
    aim(a.low, -a.s * (.05 + .07 * k), -.45 + .27 * k + tap, .9 + .1 * k, w);
  }
}
