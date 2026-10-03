'use strict';
/* The Turmeric Test: a 30 second drawn film for MAGPPIE.
   Every frame is drawn from the time alone, so the preview and the exported file are the same picture. */

const W = 1080, H = 1920, FPS = 30, DUR = 30;
const OBS = '#0B0B0D', COP = '#C77B4A', COPL = '#E8A878', SIL = '#C9CED6';
const P = { x: 540, y: 880 };          // where the paste lands on the stone
const LX = 14, LY = 18;                // shadows fall this way: the sun is at the upper left

const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v));
const lerp = (a, b, k) => a + (b - a) * k;
const seg = (t, a, b) => clamp((t - a) / (b - a));
const ease = k => k * k * (3 - 2 * k);
const easeOut = k => 1 - Math.pow(1 - k, 3);
const easeIn = k => k * k * k;
const easeIO = k => k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
const easeBack = k => 1 + 2.2 * Math.pow(k - 1, 3) + 1.2 * Math.pow(k - 1, 2);
function rng(seed) {
  return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let v = Math.imul(seed ^ seed >>> 15, 1 | seed);
    v = v + Math.imul(v ^ v >>> 7, 61 | v) ^ v; return ((v ^ v >>> 14) >>> 0) / 4294967296; };
}
function mk(w, h) { const c = document.createElement('canvas'); c.width = Math.round(w); c.height = Math.round(h); return c; }

let STONE, LIGHT, LEAVES, PASTE, SPOON, HAND, CLOTH, STAIN, KITCHEN, GRAIN, BUF, LOGO_B, LOGO_W, CAPS = [];

/* ---------- shapes ---------- */

function blob(x, R, k, ph, sy = 0.95) {            // an uneven round outline
  x.beginPath();
  for (let i = 0; i <= 96; i++) {
    const a = i / 96 * Math.PI * 2;
    const rr = R * (1 + k * (0.075 * Math.sin(3 * a + ph) + 0.045 * Math.sin(5 * a + ph * 2.3) + 0.022 * Math.sin(9 * a + ph * 4.1)));
    const px = Math.cos(a) * rr, py = Math.sin(a) * rr * sy;
    i ? x.lineTo(px, py) : x.moveTo(px, py);
  }
  x.closePath();
}

function vein(x, r, x0, y0, ang, len, col, wid) {  // a mineral vein that wanders
  const pts = [[x0, y0]]; let a = ang, px = x0, py = y0;
  for (let d = 0; d < len; d += 26) {
    a += (r() - 0.5) * 0.5; px += Math.cos(a) * 26; py += Math.sin(a) * 26; pts.push([px, py]); a += (ang - a) * 0.15;
  }
  const stroke = (lw, al, blur) => {
    x.save(); x.filter = blur ? `blur(${blur}px)` : 'none'; x.strokeStyle = `rgba(${col},${al})`; x.lineWidth = lw;
    x.lineJoin = x.lineCap = 'round'; x.beginPath(); x.moveTo(pts[0][0], pts[0][1]);
    for (let i = 1; i < pts.length - 1; i++) {
      x.quadraticCurveTo(pts[i][0], pts[i][1], (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2);
    }
    x.stroke(); x.restore();
  };
  stroke(wid * 9, 0.035, 8); stroke(wid * 3, 0.07, 2); stroke(wid, 0.2, 0);
}

function slab(x, r, rx, ry, rw, rh, base, light = 0.5) {   // a stone face with a little life in it
  x.save(); x.beginPath(); x.rect(rx, ry, rw, rh); x.clip();
  x.fillStyle = base; x.fillRect(rx, ry, rw, rh);
  const n = Math.round(rw * rh / 240);
  for (let i = 0; i < n; i++) {
    x.fillStyle = r() < light ? `rgba(255,255,255,${0.04 + r() * 0.10})` : `rgba(0,0,0,${0.03 + r() * 0.07})`;
    x.fillRect(rx + r() * rw, ry + r() * rh, 1 + r() * 1.5, 1 + r() * 1.5);
  }
  x.restore();
}

/* ---------- things that are drawn once ---------- */

function buildStone() {
  const S = 2, c = mk(W * S, H * S), x = c.getContext('2d'), r = rng(11);
  x.scale(S, S);
  x.fillStyle = '#EFEBE4'; x.fillRect(0, 0, W, H);
  for (let i = 0; i < 90; i++) {
    const cx = r() * W, cy = r() * H, rad = 140 + r() * 420, dark = r() < 0.5, col = dark ? '128,118,104' : '255,255,255';
    const g = x.createRadialGradient(cx, cy, 0, cx, cy, rad);
    g.addColorStop(0, `rgba(${col},${dark ? 0.055 : 0.12})`); g.addColorStop(1, `rgba(${col},0)`);
    x.fillStyle = g; x.fillRect(cx - rad, cy - rad, rad * 2, rad * 2);
  }
  vein(x, r, -40, 330, 0.16, 1250, '150,152,160', 1.5);
  vein(x, r, -40, 372, 0.13, 760, '199,123,74', 1.0);
  vein(x, r, 1120, 1250, 2.62, 900, '150,152,160', 1.3);
  vein(x, r, 1120, 1296, 2.66, 520, '199,123,74', 0.9);
  vein(x, r, 180, 1960, -1.05, 620, '150,152,160', 1.1);
  for (let i = 0; i < 46000; i++) {
    const px = r() * W, py = r() * H, s = 0.4 + r() * r() * 1.6, k = r();
    x.fillStyle = k < 0.55 ? `rgba(110,102,92,${0.05 + r() * 0.13})` : k < 0.93 ? `rgba(255,255,255,${0.25 + r() * 0.4})`
      : k < 0.97 ? `rgba(199,123,74,${0.22 + r() * 0.3})` : `rgba(150,156,168,${0.3 + r() * 0.3})`;
    x.fillRect(px, py, s, s);
  }
  return c;
}

function buildLight() {                             // the shadow of the window frame on the counter
  const M = 140, c = mk(W + M * 2, H + M * 2), x = c.getContext('2d');
  x.fillStyle = 'rgb(70,54,38)'; x.fillRect(0, 0, c.width, c.height);
  x.globalCompositeOperation = 'destination-out'; x.filter = 'blur(26px)'; x.translate(M, M);
  const u = [640, 64], v = [210, 700], o = [-160, -30];
  for (let j = -1; j < 4; j++) for (let i = -1; i < 3; i++) {
    const px = o[0] + i * u[0] + j * v[0], py = o[1] + i * u[1] + j * v[1];
    x.beginPath(); x.moveTo(px, py); x.lineTo(px + u[0] * 0.92, py + u[1] * 0.92);
    x.lineTo(px + u[0] * 0.92 + v[0] * 0.91, py + u[1] * 0.92 + v[1] * 0.91); x.lineTo(px + v[0] * 0.91, py + v[1] * 0.91);
    x.closePath(); x.fill();
  }
  return c;
}

function buildLeaves() {                            // soft leaf shadows from the garden outside
  const M = 140, c = mk(W + M * 2, H + M * 2), x = c.getContext('2d'), r = rng(31);
  x.filter = 'blur(20px)'; x.fillStyle = 'rgb(60,56,40)'; x.translate(M, M);
  for (let i = 0; i < 26; i++) {
    const px = -60 + r() * 520, py = 80 + r() * 1500 * r();
    x.beginPath(); x.ellipse(px, py, 30 + r() * 60, 14 + r() * 26, r() * 3, 0, 7); x.fill();
  }
  return c;
}

function buildPaste() {
  const R2 = 2, c = mk(460 * R2, 460 * R2), x = c.getContext('2d'), r = rng(5);
  c.res = R2; x.scale(R2, R2); x.translate(230, 230);
  const tier = (R, k, ph, ox, oy, c0, c1, c2, shade) => {
    x.save(); x.translate(ox, oy);
    if (shade) { x.shadowColor = 'rgba(110,62,0,0.42)'; x.shadowBlur = R * 0.24 * R2; x.shadowOffsetX = R * 0.10 * R2; x.shadowOffsetY = R * 0.13 * R2; }
    const g = x.createRadialGradient(-R * 0.38, -R * 0.45, R * 0.05, 0, 0, R * 1.12);
    g.addColorStop(0, c0); g.addColorStop(0.5, c1); g.addColorStop(1, c2);
    x.fillStyle = g; blob(x, R, k, ph); x.fill(); x.restore();
  };
  tier(128, 1, 0.6, 0, 0, '#F7C128', '#E5A20C', '#B87604', false);
  x.save(); blob(x, 128, 1, 0.6); x.clip();          // the thick edge
  x.filter = 'blur(12px)'; x.strokeStyle = 'rgba(140,82,0,0.34)'; x.lineWidth = 18; blob(x, 128, 1, 0.6); x.stroke();
  x.restore();
  tier(88, 1.3, 2.2, -8, -10, '#FBC932', '#ECAC12', '#C88708', true);
  tier(46, 1.6, 4.0, -17, -21, '#FFD64A', '#F2B51A', '#D4940A', true);
  x.lineCap = 'round';                                // ridges left by the spoon
  for (const [rad, a0, sp] of [[108, 3.5, 1.5], [116, 0.4, 1.1], [70, 2.9, 1.7], [63, 5.6, 1.0], [30, 3.2, 1.6]]) {
    x.strokeStyle = 'rgba(132,78,0,0.20)'; x.lineWidth = 3; x.beginPath(); x.ellipse(-8, -10, rad, rad * 0.94, 0, a0, a0 + sp); x.stroke();
    x.strokeStyle = 'rgba(255,238,160,0.34)'; x.lineWidth = 1.6; x.beginPath(); x.ellipse(-10, -12, rad, rad * 0.94, 0, a0, a0 + sp); x.stroke();
  }
  x.save(); blob(x, 124, 1, 0.6); x.clip();
  for (let i = 0; i < 520; i++) {                     // the grain of the spice
    const a = r() * 7, d = Math.sqrt(r()) * 124, s = 1 + r() * 1.8;
    x.fillStyle = r() < 0.6 ? `rgba(128,70,0,${0.08 + r() * 0.16})` : `rgba(255,236,150,${0.12 + r() * 0.2})`;
    x.fillRect(Math.cos(a) * d, Math.sin(a) * d * 0.95, s, s);
  }
  x.restore();
  x.filter = 'blur(4px)'; x.fillStyle = 'rgba(255,252,228,0.62)';   // wet shine
  for (const [hx, hy, a, b, rot] of [[-56, -66, 27, 11, -0.65], [-40, -46, 15, 6, -0.6], [-30, -34, 9, 4, -0.6], [-84, -22, 8, 16, 0.2]]) {
    x.beginPath(); x.ellipse(hx, hy, a, b, rot, 0, 7); x.fill();
  }
  return c;
}

function buildSpoon() {                             // origin: the middle of the bowl; the handle runs to the right
  const c = mk(1120, 330), x = c.getContext('2d');
  x.translate(170, 165);
  const steel = x.createLinearGradient(0, -34, 0, 34);
  [[0, '#FBFBFC'], [0.28, '#C6CBD3'], [0.52, '#8B929C'], [0.74, '#D6DAE0'], [1, '#F2F3F5']].forEach(([p, col]) => steel.addColorStop(p, col));
  x.fillStyle = steel; x.beginPath();
  x.moveTo(96, -18); x.bezierCurveTo(270, -11, 540, -13, 872, -25); x.quadraticCurveTo(918, -25, 918, 0);
  x.quadraticCurveTo(918, 25, 872, 25); x.bezierCurveTo(540, 13, 270, 11, 96, 18); x.closePath(); x.fill();
  x.strokeStyle = 'rgba(255,255,255,0.75)'; x.lineWidth = 2.5; x.lineCap = 'round';
  x.beginPath(); x.moveTo(140, -7); x.bezierCurveTo(300, -4, 560, -5, 880, -12); x.stroke();
  let g = x.createLinearGradient(-110, -90, 110, 90);
  [[0, '#FDFDFE'], [0.4, '#C2C8D0'], [0.72, '#848B96'], [1, '#D9DDE2']].forEach(([p, col]) => g.addColorStop(p, col));
  x.fillStyle = g; x.beginPath(); x.ellipse(0, 0, 130, 93, 0, 0, 7); x.fill();
  g = x.createRadialGradient(26, 26, 8, 0, 0, 122);
  g.addColorStop(0, '#737A85'); g.addColorStop(0.6, '#A9B0B9'); g.addColorStop(1, '#E4E7EB');
  x.fillStyle = g; x.beginPath(); x.ellipse(0, 0, 113, 78, 0, 0, 7); x.fill();
  x.filter = 'blur(1.5px)'; x.strokeStyle = 'rgba(255,255,255,0.85)'; x.lineWidth = 5;
  x.beginPath(); x.ellipse(0, 0, 99, 65, 0, Math.PI * 1.04, Math.PI * 1.46); x.stroke();
  return c;
}

function buildHand() {                              // her right hand from above; origin: the wrist; fingers point down the frame
  const OY = 1100, R2 = 2, c = mk(640 * R2, (OY + 430) * R2), x = c.getContext('2d');
  c.res = R2; x.scale(R2, R2); x.translate(320, OY);
  const skin = x.createLinearGradient(-110, 0, 120, 0);
  skin.addColorStop(0, '#CF9167'); skin.addColorStop(0.5, '#BC7D53'); skin.addColorStop(1, '#9E6241');
  const dark = a => `rgba(92,50,26,${a})`;
  // forearm
  x.fillStyle = skin; x.beginPath(); x.moveTo(-56, 8); x.lineTo(-72, -560); x.lineTo(72, -560); x.lineTo(56, 8); x.closePath(); x.fill();
  // sleeve of the kurti (plain cotton)
  const cot = x.createLinearGradient(-125, 0, 125, 0);
  cot.addColorStop(0, '#98AA8C'); cot.addColorStop(0.5, '#819575'); cot.addColorStop(1, '#66795D');
  let g = x.createLinearGradient(0, -252, 0, -196); g.addColorStop(0, dark(0.38)); g.addColorStop(1, dark(0));
  x.fillStyle = g; x.beginPath(); x.moveTo(-66, -252); x.lineTo(66, -252); x.lineTo(62, -196); x.lineTo(-62, -196); x.closePath(); x.fill();
  x.fillStyle = cot; x.beginPath(); x.moveTo(-93, -252); x.quadraticCurveTo(0, -232, 93, -252); x.lineTo(126, -OY); x.lineTo(-126, -OY); x.closePath(); x.fill();
  for (const [fx, al] of [[-52, 0.11], [8, 0.07], [58, 0.12]]) {
    x.strokeStyle = `rgba(38,52,34,${al})`; x.lineWidth = 7; x.lineCap = 'round';
    x.beginPath(); x.moveTo(fx, -300); x.quadraticCurveTo(fx + 14, -700, fx * 1.35, -OY); x.stroke();
  }
  x.strokeStyle = 'rgba(236,241,228,0.6)'; x.lineWidth = 5; x.beginPath(); x.moveTo(-91, -263); x.quadraticCurveTo(0, -244, 91, -263); x.stroke();
  x.setLineDash([7, 6]); x.lineWidth = 1.6; x.strokeStyle = 'rgba(255,255,255,0.55)';
  x.beginPath(); x.moveTo(-93, -281); x.quadraticCurveTo(0, -262, 93, -281); x.stroke(); x.setLineDash([]);
  // fingers and thumb go under the back of the hand
  const finger = (rx, ry, len, w, ang, nail = true) => {
    x.save(); x.translate(rx, ry); x.rotate(ang * Math.PI / 180);
    const fg = x.createLinearGradient(-w / 2, 0, w / 2, 0);
    fg.addColorStop(0, '#CB8D63'); fg.addColorStop(0.45, '#BE8056'); fg.addColorStop(1, '#9C6040');
    x.fillStyle = fg; x.beginPath(); x.roundRect(-w / 2, -20, w, len + 20, w / 2); x.fill();
    x.strokeStyle = dark(0.2); x.lineWidth = 1.6; x.lineCap = 'round';
    for (const k of [0.34, 0.385, 0.67]) { x.beginPath(); x.moveTo(-w * 0.28, len * k); x.quadraticCurveTo(0, len * k + 4, w * 0.28, len * k); x.stroke(); }
    if (nail) {
      const nw = w * 0.6, nh = w * 0.68, ny = len - nh - 5;
      x.fillStyle = '#EDCBB8'; x.beginPath(); x.roundRect(-nw / 2, ny, nw, nh, [nw * 0.3, nw * 0.3, nw * 0.5, nw * 0.5]); x.fill();
      x.strokeStyle = 'rgba(255,255,255,0.55)'; x.lineWidth = 2; x.beginPath(); x.moveTo(-nw * 0.22, ny + 5); x.lineTo(-nw * 0.22, ny + nh * 0.6); x.stroke();
      x.strokeStyle = dark(0.18); x.lineWidth = 1; x.beginPath(); x.roundRect(-nw / 2, ny, nw, nh, [nw * 0.3, nw * 0.3, nw * 0.5, nw * 0.5]); x.stroke();
    }
    x.restore();
  };
  finger(76, 66, 152, 52, -47);                       // thumb
  finger(-70, 180, 118, 38, 8); finger(-25, 196, 158, 43, 3); finger(22, 200, 170, 45, -1); finger(68, 190, 153, 43, -6);
  // back of the hand
  x.fillStyle = skin; x.beginPath(); x.moveTo(-56, 0);
  x.bezierCurveTo(-70, 40, -96, 70, -98, 120); x.bezierCurveTo(-100, 160, -97, 182, -90, 198);
  x.quadraticCurveTo(0, 222, 91, 208);
  x.bezierCurveTo(100, 172, 104, 132, 100, 100); x.bezierCurveTo(96, 60, 70, 40, 56, 0); x.closePath(); x.fill();
  for (const [kx, ky, kr] of [[-70, 176, 22], [-25, 192, 25], [22, 196, 26], [68, 186, 25]]) {   // knuckles
    g = x.createRadialGradient(kx - 4, ky - 4, 2, kx, ky, kr);
    g.addColorStop(0, 'rgba(222,166,128,0.55)'); g.addColorStop(1, 'rgba(222,166,128,0)');
    x.fillStyle = g; x.beginPath(); x.arc(kx, ky, kr, 0, 7); x.fill();
    x.strokeStyle = dark(0.16); x.lineWidth = 1.5; x.beginPath(); x.arc(kx, ky + 3, kr * 0.62, 0.5, 2.6); x.stroke();
  }
  x.strokeStyle = dark(0.10); x.lineWidth = 3;        // the tendons, barely there
  for (const [a, b] of [[-28, -62], [-6, -22], [12, 20], [30, 62]]) { x.beginPath(); x.moveTo(a, 40); x.quadraticCurveTo((a + b) / 2, 110, b, 162); x.stroke(); }
  for (const by of [-30, -47]) {                      // two thin bangles
    x.strokeStyle = '#B4862A'; x.lineWidth = 8; x.lineCap = 'round';
    x.beginPath(); x.moveTo(-60, by); x.quadraticCurveTo(0, by + 13, 60, by); x.stroke();
    x.strokeStyle = '#F5DD90'; x.lineWidth = 2.4; x.beginPath(); x.moveTo(-50, by + 1); x.quadraticCurveTo(-12, by + 9, 18, by + 6); x.stroke();
  }
  c.oy = OY;
  return c;
}

function clothPath(x, k = 1) {
  x.beginPath();
  for (let i = 0; i < 120; i++) {
    const a = i / 120 * Math.PI * 2, ca = Math.cos(a), sa = Math.sin(a), e = 0.26;
    const wob = k * (1 + 0.012 * Math.sin(a * 7 + 1) + 0.008 * Math.sin(a * 13 + 2));
    const px = 185 * Math.sign(ca) * Math.pow(Math.abs(ca), e) * wob, py = 165 * Math.sign(sa) * Math.pow(Math.abs(sa), e) * wob;
    i ? x.lineTo(px, py) : x.moveTo(px, py);
  }
  x.closePath();
}

function buildCloth() {
  const c = mk(480, 440), x = c.getContext('2d'), r = rng(9);
  x.translate(240, 220);
  const g = x.createLinearGradient(-185, -165, 185, 165);
  g.addColorStop(0, '#AEC0D0'); g.addColorStop(1, '#788EA4');
  x.fillStyle = g; clothPath(x); x.fill();
  x.save(); clothPath(x); x.clip();
  for (let i = -200; i < 200; i += 11) {              // the weave
    x.fillStyle = 'rgba(255,255,255,0.10)'; x.fillRect(i, -200, 2, 400); x.fillRect(-200, i, 400, 2);
    x.fillStyle = 'rgba(30,50,70,0.07)'; x.fillRect(i + 5, -200, 2, 400); x.fillRect(-200, i + 5, 400, 2);
  }
  for (let i = 0; i < 12; i++) {                      // damp patches
    const cx = (r() - 0.5) * 340, cy = (r() - 0.5) * 300, rad = 40 + r() * 80, gg = x.createRadialGradient(cx, cy, 0, cx, cy, rad);
    gg.addColorStop(0, 'rgba(50,72,96,0.13)'); gg.addColorStop(1, 'rgba(50,72,96,0)'); x.fillStyle = gg; x.fillRect(cx - rad, cy - rad, rad * 2, rad * 2);
  }
  x.filter = 'blur(4px)'; x.strokeStyle = 'rgba(30,50,70,0.2)'; x.lineWidth = 7;       // the fold
  x.beginPath(); x.moveTo(-200, 34); x.quadraticCurveTo(0, 22, 200, 40); x.stroke();
  x.strokeStyle = 'rgba(255,255,255,0.3)'; x.lineWidth = 5; x.beginPath(); x.moveTo(-200, 26); x.quadraticCurveTo(0, 14, 200, 32); x.stroke();
  x.restore();
  x.strokeStyle = 'rgba(50,72,96,0.45)'; x.lineWidth = 3; clothPath(x); x.stroke();
  x.setLineDash([7, 6]); x.strokeStyle = 'rgba(255,255,255,0.5)'; x.lineWidth = 1.8; clothPath(x, 0.93); x.stroke();
  return c;
}

function buildStain() {                             // what the cloth picked up
  const c = mk(480, 440), x = c.getContext('2d'), r = rng(13);
  x.translate(240, 220); clothPath(x); x.clip(); x.filter = 'blur(9px)';
  for (let i = 0; i < 16; i++) {
    x.fillStyle = `rgba(226,160,10,${0.35 + r() * 0.4})`;
    x.beginPath(); x.ellipse(120 + r() * 70, -110 + r() * 220, 14 + r() * 30, 10 + r() * 26, r() * 3, 0, 7); x.fill();
  }
  return c;
}

function buildGrain() {
  const c = mk(512, 512), x = c.getContext('2d'), d = x.createImageData(512, 512), r = rng(77);
  for (let i = 0; i < d.data.length; i += 4) { const v = r() < 0.5 ? 0 : 255; d.data[i] = d.data[i + 1] = d.data[i + 2] = v; d.data[i + 3] = r() * 26; }
  x.putImageData(d, 0, 0);
  return c;
}

function buildKitchen() {                           // the wide view: a kitchen built in stone, morning sun from the left
  const S = 1.3, KH = H + 220, c = mk(W * S, KH * S), x = c.getContext('2d'), r = rng(23);
  c.kh = KH; x.scale(S, S);
  const FLOOR = 1262;
  let g = x.createLinearGradient(0, 0, W, 0); g.addColorStop(0, '#F4EEE3'); g.addColorStop(1, '#DCD4C7');
  x.fillStyle = g; x.fillRect(0, 0, W, FLOOR);
  g = x.createLinearGradient(0, FLOOR, 0, KH); g.addColorStop(0, '#B9B1A4'); g.addColorStop(1, '#D6CFC3');
  x.fillStyle = g; x.fillRect(0, FLOOR, W, KH - FLOOR);
  x.strokeStyle = 'rgba(90,80,68,0.18)'; x.lineWidth = 1.5;
  for (let i = -9; i <= 9; i++) { x.beginPath(); x.moveTo(540 + i * 70, FLOOR); x.lineTo(540 + i * 330, KH); x.stroke(); }
  for (const fy of [1296, 1350, 1440, 1590, 1840, 2060]) { x.beginPath(); x.moveTo(0, fy); x.lineTo(W, fy); x.stroke(); }

  // the window and the garden behind it
  g = x.createRadialGradient(265, 590, 120, 265, 590, 640); g.addColorStop(0, 'rgba(255,243,210,0.85)'); g.addColorStop(1, 'rgba(255,243,210,0)');
  x.fillStyle = g; x.fillRect(0, 0, W, FLOOR);
  g = x.createLinearGradient(0, 300, 0, 880); g.addColorStop(0, '#FFFCF1'); g.addColorStop(0.55, '#FCF7E6'); g.addColorStop(1, '#E3EDD4');
  x.fillStyle = g; x.fillRect(80, 300, 370, 580);
  x.save(); x.beginPath(); x.rect(80, 300, 370, 580); x.clip(); x.filter = 'blur(15px)';
  for (let i = 0; i < 22; i++) {
    x.fillStyle = `rgba(${130 + r() * 40},${168 + r() * 30},${104 + r() * 30},${0.35 + r() * 0.3})`;
    x.beginPath(); x.ellipse(70 + r() * 400, 720 + r() * 190, 40 + r() * 60, 30 + r() * 50, 0, 0, 7); x.fill();
  }
  x.restore();
  x.strokeStyle = '#3B342D'; x.lineWidth = 12; x.strokeRect(80, 300, 370, 580);
  x.lineWidth = 6; x.beginPath(); x.moveTo(265, 300); x.lineTo(265, 880); x.moveTo(80, 493); x.lineTo(450, 493); x.moveTo(80, 686); x.lineTo(450, 686); x.stroke();

  // the back run under the window: dark stone fronts, white stone top
  slab(x, r, 40, 886, 572, 80, '#EDE8E0', 0.5);
  vein(x, r, 40, 930, 0.02, 560, '199,123,74', 0.8);
  slab(x, r, 40, 990, 572, FLOOR - 990, '#2C2C30', 0.75);
  slab(x, r, 30, 962, 590, 28, '#F3EFE8', 0.5);
  x.fillStyle = 'rgba(255,255,255,0.9)'; x.fillRect(30, 962, 590, 2);
  g = x.createLinearGradient(0, 990, 0, 1022); g.addColorStop(0, 'rgba(0,0,0,0.5)'); g.addColorStop(1, 'rgba(0,0,0,0)');
  x.fillStyle = g; x.fillRect(40, 990, 572, 32);
  for (const gx of [230, 421]) { x.fillStyle = 'rgba(0,0,0,0.6)'; x.fillRect(gx, 990, 3, FLOOR - 990); x.fillStyle = 'rgba(255,255,255,0.07)'; x.fillRect(gx + 3, 990, 1, FLOOR - 990); }
  x.fillStyle = COP; for (const hx of [96, 286, 477]) x.fillRect(hx, 1030, 84, 5);
  // things on the back counter
  x.strokeStyle = '#4A3F33'; x.lineWidth = 7; x.lineCap = 'round';                    // tap
  x.beginPath(); x.moveTo(520, 962); x.lineTo(520, 890); x.quadraticCurveTo(520, 858, 488, 858); x.lineTo(476, 858); x.lineTo(476, 874); x.stroke();
  x.fillStyle = '#B9895A'; x.beginPath(); x.moveTo(118, 962); x.lineTo(126, 916); x.lineTo(176, 916); x.lineTo(184, 962); x.closePath(); x.fill();   // clay pot
  x.strokeStyle = '#6F8F5E'; x.lineWidth = 4;
  for (const [lx, ly] of [[112, 846], [136, 818], [158, 834], [186, 852], [150, 800]]) { x.beginPath(); x.moveTo(151, 916); x.quadraticCurveTo(151, (916 + ly) / 2, lx, ly); x.stroke(); x.fillStyle = '#7FA06C'; x.beginPath(); x.ellipse(lx, ly, 16, 8, Math.atan2(ly - 916, lx - 151), 0, 7); x.fill(); }
  g = x.createLinearGradient(330, 0, 400, 0); g.addColorStop(0, '#E3BC62'); g.addColorStop(0.5, '#B98A2E'); g.addColorStop(1, '#8A6520');   // brass pot
  x.fillStyle = g; x.beginPath(); x.ellipse(365, 934, 36, 28, 0, 0, 7); x.fill(); x.fillRect(349, 896, 32, 16); x.beginPath(); x.ellipse(365, 896, 22, 5, 0, 0, 7); x.fill();

  // the tall units: dark stone, floor to ceiling
  slab(x, r, 612, 250, 428, FLOOR - 250, '#2A2A2E', 0.75);
  x.save(); x.beginPath(); x.rect(612, 250, 428, FLOOR - 250); x.clip();
  vein(x, r, 600, 420, 0.5, 620, '199,123,74', 1.2); vein(x, r, 600, 462, 0.47, 520, '201,206,214', 1.0);
  x.restore();
  g = x.createLinearGradient(612, 0, 1040, 0); g.addColorStop(0, 'rgba(255,225,170,0.10)'); g.addColorStop(1, 'rgba(0,0,0,0.25)');
  x.fillStyle = g; x.fillRect(612, 250, 428, FLOOR - 250);
  const gap = (gx, gy, gw, gh) => { x.fillStyle = 'rgba(0,0,0,0.65)'; x.fillRect(gx, gy, gw, gh); x.fillStyle = 'rgba(255,255,255,0.07)'; gw < gh ? x.fillRect(gx + gw, gy, 1, gh) : x.fillRect(gx, gy + gh, gw, 1); };
  gap(825, 250, 3, FLOOR - 250); gap(612, 560, 428, 3); gap(612, 800, 213, 3);
  // the open niche with a warm light
  x.fillStyle = '#151517'; x.fillRect(630, 578, 180, 210);
  g = x.createLinearGradient(0, 578, 0, 700); g.addColorStop(0, 'rgba(255,214,150,0.85)'); g.addColorStop(1, 'rgba(255,214,150,0)');
  x.fillStyle = g; x.fillRect(630, 578, 180, 122);
  x.fillStyle = '#EDE8E0'; x.fillRect(630, 782, 180, 6);
  g = x.createLinearGradient(655, 0, 705, 0); g.addColorStop(0, '#E8C46C'); g.addColorStop(1, '#94701F');
  x.fillStyle = g; x.beginPath(); x.ellipse(680, 756, 26, 26, 0, 0, 7); x.fill(); x.fillRect(669, 716, 22, 18);
  x.fillStyle = '#F1ECE4'; for (let i = 0; i < 3; i++) { x.beginPath(); x.ellipse(760, 776 - i * 9, 30 - i * 2, 6, 0, 0, 7); x.fill(); }
  x.fillStyle = COP; x.fillRect(812, 400, 5, 120); x.fillRect(834, 400, 5, 120); x.fillRect(812, 900, 5, 150); x.fillRect(834, 840, 5, 210);

  // the island: white stone top, white stone fronts
  x.save(); x.filter = 'blur(22px)'; x.fillStyle = 'rgba(50,40,30,0.42)'; x.beginPath(); x.ellipse(600, 1834, 480, 34, 0, 0, 7); x.fill(); x.restore();
  x.fillStyle = '#191818'; x.fillRect(150, 1800, 780, 30);
  slab(x, r, 128, 1428, 824, 372, '#ECE7DE', 0.5);
  x.save(); x.beginPath(); x.rect(128, 1428, 824, 372); x.clip();
  vein(x, r, 110, 1700, -0.32, 900, '150,152,160', 1.3); vein(x, r, 110, 1742, -0.34, 520, '199,123,74', 0.9);
  x.restore();
  g = x.createLinearGradient(128, 0, 952, 0); g.addColorStop(0, 'rgba(255,238,200,0.32)'); g.addColorStop(0.55, 'rgba(255,238,200,0)'); g.addColorStop(1, 'rgba(70,60,48,0.16)');
  x.fillStyle = g; x.fillRect(128, 1428, 824, 372);
  g = x.createLinearGradient(0, 1428, 0, 1478); g.addColorStop(0, 'rgba(60,48,36,0.36)'); g.addColorStop(1, 'rgba(60,48,36,0)');
  x.fillStyle = g; x.fillRect(128, 1428, 824, 50);
  for (const gx of [402, 677]) { x.fillStyle = 'rgba(70,60,50,0.5)'; x.fillRect(gx, 1428, 3, 372); x.fillStyle = 'rgba(255,255,255,0.6)'; x.fillRect(gx + 3, 1428, 1, 372); }
  x.fillStyle = 'rgba(70,60,50,0.5)'; x.fillRect(128, 1566, 824, 3); x.fillStyle = 'rgba(255,255,255,0.6)'; x.fillRect(128, 1569, 824, 1);
  x.fillStyle = COP; for (const hx of [220, 495, 770]) { x.fillRect(hx, 1500, 92, 5); x.fillRect(hx, 1612, 92, 5); }
  // the top of the island, seen a little from above
  x.save(); x.beginPath(); x.moveTo(190, 1300); x.lineTo(890, 1300); x.lineTo(970, 1400); x.lineTo(110, 1400); x.closePath(); x.clip();
  g = x.createLinearGradient(110, 0, 970, 0); g.addColorStop(0, '#FFFDF8'); g.addColorStop(1, '#E7E2D9');
  x.fillStyle = g; x.fillRect(100, 1296, 880, 108);
  vein(x, r, 100, 1338, 0.03, 900, '150,152,160', 1.0);
  x.filter = 'blur(10px)'; x.fillStyle = 'rgba(255,255,255,0.9)'; x.beginPath(); x.ellipse(420, 1352, 170, 22, 0, 0, 7); x.fill();
  x.restore();
  slab(x, r, 110, 1400, 860, 28, '#E4DFD6', 0.5);
  x.fillStyle = 'rgba(255,255,255,0.95)'; x.fillRect(110, 1400, 860, 2);
  // on the island: the little bowl of turmeric and the folded cloth
  x.fillStyle = 'rgba(60,48,36,0.25)'; x.beginPath(); x.ellipse(672, 1362, 46, 9, 0, 0, 7); x.fill();
  g = x.createLinearGradient(620, 0, 706, 0); g.addColorStop(0, '#E8C46C'); g.addColorStop(1, '#94701F');
  x.fillStyle = g; x.beginPath(); x.moveTo(620, 1338); x.quadraticCurveTo(664, 1384, 708, 1338); x.closePath(); x.fill();
  x.beginPath(); x.ellipse(664, 1338, 44, 11, 0, 0, 7); x.fill();
  x.fillStyle = '#E9A70E'; x.beginPath(); x.ellipse(664, 1338, 35, 7.5, 0, 0, 7); x.fill();
  x.fillStyle = 'rgba(60,48,36,0.22)'; x.beginPath(); x.moveTo(752, 1372); x.lineTo(846, 1372); x.lineTo(832, 1346); x.lineTo(746, 1346); x.closePath(); x.fill();
  x.fillStyle = '#8FA4B8'; x.beginPath(); x.moveTo(744, 1366); x.lineTo(838, 1366); x.lineTo(824, 1340); x.lineTo(738, 1340); x.closePath(); x.fill();
  x.fillStyle = '#7A90A5'; x.fillRect(744, 1366, 94, 6);

  // two pendants over the island
  for (const px of [330, 750]) {
    const py = 462;                                   // top of the shade
    x.strokeStyle = '#2C2622'; x.lineWidth = 2.5; x.beginPath(); x.moveTo(px, 0); x.lineTo(px, py); x.stroke();
    g = x.createRadialGradient(px, py + 80, 10, px, py + 80, 210); g.addColorStop(0, 'rgba(255,224,170,0.5)'); g.addColorStop(1, 'rgba(255,224,170,0)');
    x.fillStyle = g; x.fillRect(px - 210, py - 130, 420, 420);
    g = x.createLinearGradient(px - 60, 0, px + 60, 0); g.addColorStop(0, '#8A6A4C'); g.addColorStop(0.5, '#5A4534'); g.addColorStop(1, '#2F2620');
    x.fillStyle = g; x.beginPath(); x.moveTo(px - 16, py); x.lineTo(px + 16, py); x.quadraticCurveTo(px + 62, py + 20, px + 64, py + 66); x.lineTo(px - 64, py + 66); x.quadraticCurveTo(px - 62, py + 20, px - 16, py); x.closePath(); x.fill();
    x.fillStyle = '#FFE9C2'; x.beginPath(); x.ellipse(px, py + 66, 62, 7, 0, 0, 7); x.fill();
  }

  // the morning sun coming in
  x.save(); x.globalCompositeOperation = 'screen'; x.filter = 'blur(34px)';
  g = x.createLinearGradient(260, 500, 900, 1500); g.addColorStop(0, 'rgba(255,236,190,0.34)'); g.addColorStop(1, 'rgba(255,236,190,0)');
  x.fillStyle = g;
  x.beginPath(); x.moveTo(90, 310); x.lineTo(258, 310); x.lineTo(900, 1620); x.lineTo(420, 1760); x.closePath(); x.fill();
  x.beginPath(); x.moveTo(272, 310); x.lineTo(442, 310); x.lineTo(1150, 1380); x.lineTo(940, 1560); x.closePath(); x.fill();
  x.restore();
  g = x.createRadialGradient(540, 1150, 540, 540, 1150, 1300); g.addColorStop(0, 'rgba(20,14,8,0)'); g.addColorStop(1, 'rgba(20,14,8,0.34)');
  x.fillStyle = g; x.fillRect(0, 0, W, KH);
  return c;
}

/* ---------- the camera over the counter ---------- */

function camera(t) {
  let z, cx = 540, cy;
  if (t < 4.75) { z = lerp(1.0, 1.07, ease(seg(t, 0, 4.75))); cy = 960; }
  else if (t < 11.15) {
    const k = easeIO(seg(t, 4.75, 7.7));
    z = lerp(1.07, 1.82, k) + seg(t, 7.7, 11.15) * 0.1; cy = lerp(960, 880, k);
  } else if (t < 16.6) {
    const k = easeIO(seg(t, 11.15, 12.1));
    z = lerp(1.92, 1.0, k) + seg(t, 12.1, 16.6) * 0.03; cy = lerp(880, 960, k);
  } else {
    const k = easeIO(seg(t, 16.6, 17.5));
    z = lerp(1.03, 1.5, k) + seg(t, 17.5, 22.4) * 0.1; cy = lerp(960, 1000, k);
  }
  return { z, x: cx, y: cy };
}
const toScreen = (cam, wx, wy) => [(wx - cam.x) * cam.z + W / 2, (wy - cam.y) * cam.z + H / 2];
function look(x, cam) { x.translate(W / 2, H / 2); x.scale(cam.z, cam.z); x.translate(-cam.x, -cam.y); }

function sprite(x, img, px, py, opt) {              // one sprite with one shadow under it
  const res = img.res || 1, iw = img.width / res, ih = img.height / res;
  const { s = 1, sy = s, rot = 0, ox = iw / 2, oy = ih / 2, z = 1, lift = 0, dark = 0.34, soft = 14, alpha = 1 } = opt;
  x.save(); x.translate(px, py); x.rotate(rot); x.scale(s, sy); x.globalAlpha = alpha;
  x.shadowColor = `rgba(52,36,18,${dark})`; x.shadowBlur = soft * (1 + lift * 2.2) * z;
  x.shadowOffsetX = LX * (1 + lift * 6) * z; x.shadowOffsetY = LY * (1 + lift * 6) * z;
  x.drawImage(img, -ox, -oy, iw, ih);
  x.restore();
}

/* ---------- what happens on the counter ---------- */

const T_SLIDE = 1.2, T_REL = 1.5, T_HIT = 1.9;
const DROPS = [[-170, -42, 9], [152, -98, 6], [178, 50, 11], [-124, 116, 7], [64, 148, 5]];

function spoonPose(t) {
  const inn = easeOut(seg(t, 0.12, 1.05)), out = easeIO(seg(t, 1.98, 3.0));
  const px = lerp(lerp(1260, 636, inn), 1460, out), py = lerp(lerp(210, 748, inn), 60, out);
  const tilt = ease(seg(t, 1.0, 1.5)) * (1 - ease(seg(t, 1.95, 2.5)));
  return { x: px, y: py, rot: -0.62 - tilt * 0.2, sy: 1 - tilt * 0.12 };
}

function wipe(t) {                                  // where the cloth is, and how far it is off the stone
  if (t < 11.45 || t > 14.98) return null;
  if (t < 12.45) { const k = easeOut(seg(t, 11.45, 12.45)); return { x: lerp(120, 190, k), y: lerp(-430, 900, k), lift: 1 - ease(seg(t, 11.9, 12.45)) }; }
  if (t < 12.65) return { x: 190, y: 900, lift: 0 };
  if (t < 14.2) { const k = easeIO(seg(t, 12.65, 14.2)); return { x: lerp(190, 930, k), y: 900 - 8 * Math.sin(Math.PI * k), lift: 0, wiping: true }; }
  const k = easeIn(seg(t, 14.2, 14.98));
  return { x: lerp(930, 1010, k), y: lerp(900, -470, k), lift: ease(seg(t, 14.2, 14.6)) };
}
const armAngle = (wx, wy) => -Math.atan2(wx - 620, wy + 1500);

function drawCounter(x, t) {
  const cam = camera(t), z = cam.z;
  x.save(); look(x, cam);
  x.drawImage(STONE, 0, 0, W, H);
  const k = wipe(t);

  // the damp path the cloth leaves, drying
  if (t > 12.65 && t < 16.6) {
    const reach = k && k.wiping ? k.x + 150 : 1090, a = 1 - ease(seg(t, 14.3, 16.5));
    x.save(); x.beginPath(); x.rect(0, 700, reach, 400); x.clip();
    x.globalAlpha = a; x.filter = 'blur(12px)'; x.fillStyle = 'rgba(96,110,126,0.13)';
    x.beginPath(); x.roundRect(10, 742, 1100, 316, 60); x.fill();
    x.filter = 'blur(3px)'; x.strokeStyle = 'rgba(255,255,255,0.5)'; x.lineWidth = 3;
    for (const sy of [768, 812, 874, 951, 1012]) { x.beginPath(); x.moveTo(30, sy); x.quadraticCurveTo(540, sy - 9, 1070, sy + 3); x.stroke(); }
    x.restore();
  }

  // the paste
  if (t >= T_HIT && t < 14.2) {
    x.save();
    if (k && k.wiping) { x.beginPath(); x.rect(k.x + 60, 0, W, H); x.clip(); }
    const u = t - T_HIT, s = lerp(0.78, 1, easeBack(seg(u, 0, 0.36)));
    for (const [dx, dy, dr] of DROPS) {
      const f = easeOut(seg(u, 0, 0.2));
      x.save(); x.translate(P.x + dx * f, P.y + dy * f);
      x.shadowColor = 'rgba(70,45,10,0.4)'; x.shadowBlur = 4 * z; x.shadowOffsetX = 3 * z; x.shadowOffsetY = 4 * z;
      const g = x.createRadialGradient(-dr * 0.3, -dr * 0.3, 1, 0, 0, dr); g.addColorStop(0, '#FAC935'); g.addColorStop(1, '#C88708');
      x.fillStyle = g; blob(x, dr, 1.4, dx); x.fill(); x.restore();
    }
    sprite(x, PASTE, P.x, P.y, { s, z, dark: 0.4, soft: 15 });
    x.restore();
  }
  // a soft bloom on the clean stone once the cloth has gone
  if (t > 14.3 && t < 17.2) {
    const a = ease(seg(t, 14.3, 15.2)) * (1 - ease(seg(t, 16.0, 17.2)));
    const g = x.createRadialGradient(P.x, P.y, 20, P.x, P.y, 330); g.addColorStop(0, `rgba(255,255,255,${0.5 * a})`); g.addColorStop(1, 'rgba(255,255,255,0)');
    x.fillStyle = g; x.fillRect(P.x - 340, P.y - 340, 680, 680);
  }

  // the spoon, held above the stone
  if (t < 3.05) {
    const sp = spoonPose(t), SS = 1.28, c = Math.cos(sp.rot), sn = Math.sin(sp.rot);
    sprite(x, SPOON, sp.x, sp.y, { s: SS, sy: SS * sp.sy, rot: sp.rot, ox: 170, oy: 165, z, lift: 1, dark: 0.2, soft: 12 });
    if (t >= T_REL) {                                  // what stays in the bowl
      x.save(); x.translate(sp.x, sp.y); x.rotate(sp.rot); x.scale(SS, SS * sp.sy); x.filter = 'blur(4px)';
      x.fillStyle = 'rgba(232,166,14,0.6)'; x.beginPath(); x.ellipse(-22, 6, 58, 34, 0.2, 0, 7); x.fill(); x.restore();
    }
    if (t < T_HIT) {                                   // the paste in the bowl, sliding to the tip, then falling
      const slide = ease(seg(t, T_SLIDE, T_REL)), fall = easeIn(seg(t, T_REL, T_HIT));
      const bx = sp.x - c * 122 * slide, by = sp.y - sn * 122 * slide;
      const px = lerp(bx, P.x, fall), py = lerp(by, P.y, fall), lift = 1 - fall;
      sprite(x, PASTE, px, py, { s: lerp(0.64, 0.78, fall), z, lift: t < T_REL ? 0 : lift, dark: t < T_REL ? 0.0 : 0.3, soft: 14 });
    }
  }

  // the cloth and her hand
  if (k) {
    const sc = 1 + k.lift * 0.07, wx = k.x, wy = k.y - 215, rot = armAngle(wx, wy);
    sprite(x, CLOTH, k.x, k.y, { s: sc, rot: rot * 0.6, z, lift: k.lift * 0.5, dark: 0.3, soft: 12 });
    const st = ease(seg(k.x, 420, 640)) * (k.wiping || t > 14.2 ? 1 : 0);
    if (st > 0) { x.save(); x.translate(k.x, k.y); x.rotate(rot * 0.6); x.scale(sc, sc); x.globalAlpha = st * 0.6; x.drawImage(STAIN, -240, -220); x.restore(); }
    sprite(x, HAND, wx, wy, { s: sc, rot, ox: 320, oy: HAND.oy, z, lift: 0.25 + k.lift * 0.5, dark: 0.3, soft: 14 });
  }

  // her fingertips glide over the clean spot
  if (t > 16.85 && t < 22.4) {
    const inn = easeOut(seg(t, 16.9, 17.75)), go = easeIO(seg(t, 17.6, 21.5)), out = easeIn(seg(t, 21.5, 22.3));
    const wx = lerp(lerp(350, 380, inn), 720, go) + out * 40, wy = lerp(lerp(40, 512, inn), 512, go) - out * 520 + 5 * Math.sin(t * 1.3);
    const tip = [wx, wy + 372];
    const g = x.createRadialGradient(tip[0] - 60, tip[1] + 30, 10, tip[0] - 60, tip[1] + 30, 260);     // the sheen she leaves
    g.addColorStop(0, `rgba(255,255,255,${0.42 * inn * (1 - out)})`); g.addColorStop(1, 'rgba(255,255,255,0)');
    x.fillStyle = g; x.fillRect(tip[0] - 330, tip[1] - 240, 660, 540);
    sprite(x, HAND, wx, wy, { s: 1, rot: armAngle(wx, wy), ox: 320, oy: HAND.oy, z, lift: 0.12, dark: 0.3, soft: 12 });
  }

  drawSun(x, t);
  // a slow glint across the stone on "pure, safe stone that lasts"
  if (t > 19.5 && t < 21.6) {
    const kx = lerp(-500, 1500, easeIO(seg(t, 19.5, 21.6))), g = x.createLinearGradient(kx - 220, 0, kx + 220, 160);
    g.addColorStop(0, 'rgba(255,255,255,0)'); g.addColorStop(0.5, 'rgba(255,255,255,0.22)'); g.addColorStop(1, 'rgba(255,255,255,0)');
    x.fillStyle = g; x.fillRect(0, 0, W, H);
  }
  x.restore();
}

function drawSun(x, t) {                            // warm morning light, the window's shadow, the leaves moving
  x.save();
  x.fillStyle = 'rgba(255,222,165,0.10)'; x.fillRect(0, 0, W, H);
  x.globalAlpha = 0.17; x.drawImage(LIGHT, -140 + Math.sin(t * 0.21) * 5, -140 + Math.cos(t * 0.17) * 4);
  x.globalAlpha = 0.11; x.drawImage(LEAVES, -140 + Math.sin(t * 0.9) * 9 + Math.sin(t * 2.3) * 3, -140 + Math.cos(t * 0.7) * 6);
  x.restore();
}

/* ---------- water on the stone ---------- */

const BEADS = [[330, 1290, 44, 0.05], [560, 1210, 30, 0.22], [470, 1440, 36, 0.4], [680, 1380, 52, 0.58], [250, 1500, 22, 0.72],
  [600, 1560, 26, 0.86], [390, 1150, 18, 1.0], [760, 1230, 20, 1.12], [520, 1330, 14, 1.25], [300, 1400, 12, 1.36], [700, 1530, 15, 1.48]];

function bead(x, px, py, r, z, k, ph) {
  x.save(); x.translate(px, py); x.scale(1 + (1 - k) * 0.7, 1 + (1 - k) * 0.7); x.globalAlpha = k;
  x.save(); x.shadowColor = 'rgba(40,44,52,0.42)'; x.shadowBlur = r * 0.4 * z; x.shadowOffsetX = r * 0.16 * z; x.shadowOffsetY = r * 0.24 * z;
  x.fillStyle = 'rgba(238,241,245,0.6)'; blob(x, r, 0.5, ph, 1); x.fill(); x.restore();
  let g = x.createRadialGradient(-r * 0.2, -r * 0.25, r * 0.1, 0, 0, r);
  g.addColorStop(0, 'rgba(255,255,255,0.04)'); g.addColorStop(0.72, 'rgba(120,136,152,0.12)'); g.addColorStop(1, 'rgba(64,80,96,0.46)');
  x.fillStyle = g; blob(x, r, 0.5, ph, 1); x.fill();
  x.save(); blob(x, r, 0.5, ph, 1); x.clip();
  g = x.createRadialGradient(r * 0.36, r * 0.42, 0, r * 0.36, r * 0.42, r * 0.62); g.addColorStop(0, 'rgba(255,255,255,0.85)'); g.addColorStop(1, 'rgba(255,255,255,0)');
  x.fillStyle = g; x.fillRect(-r, -r, r * 2, r * 2); x.restore();
  x.fillStyle = 'rgba(255,255,255,0.96)'; x.beginPath(); x.ellipse(-r * 0.36, -r * 0.42, r * 0.21, r * 0.11, -0.7, 0, 7); x.fill();
  x.restore();
}

function drawWater(x, t) {
  const u = t - 22.0, cam = { z: 1.5 + u * 0.05, x: 500, y: 1250 - u * 8 };
  x.save(); look(x, cam);
  x.drawImage(STONE, 0, 0, W, H);
  BEADS.forEach(([bx, by, br, t0], i) => {
    const k = easeOut(seg(u, t0, t0 + 0.22));
    if (k > 0) bead(x, bx, by - 110 + (i === 3 ? Math.max(0, u - 0.9) * 26 : 0), br, cam.z, k, bx);
  });
  drawSun(x, t);
  x.restore();
}

/* ---------- the wide view ---------- */

function drawKitchen(x, t) {
  const zk = lerp(1.27, 1.0, easeOut(seg(t, 23.6, 28.4))) + (30 - t) * 0.004;
  x.save(); x.translate(540, 1150); x.scale(zk, zk); x.translate(-540, -1340);
  x.drawImage(KITCHEN, 0, 0, W, KITCHEN.kh);
  x.restore();
}

/* ---------- words on the picture ---------- */

function text(x, s, px, py, font, fill, align = 'center', space = '0px', alpha = 1) {
  x.save(); x.font = font; x.fillStyle = fill; x.textAlign = align; x.textBaseline = 'alphabetic'; x.letterSpacing = space; x.globalAlpha *= alpha;
  x.fillText(s, px, py); x.restore();
}

function drawBrandTop(x, t) {                       // the logo, and the name of the test while the paste drops
  const a = ease(seg(t, 0.2, 0.8)) * (1 - ease(seg(t, 10.9, 11.3)));
  if (a > 0 && LOGO_B) { x.save(); x.globalAlpha = a * 0.92; x.drawImage(LOGO_B, 40, 170, 1200, 260, 400, 212, 280, 280 * 260 / 1200); x.restore(); }
  const b = ease(seg(t, 0.35, 0.9)) * (1 - ease(seg(t, 4.3, 4.75)));
  if (b > 0) {
    x.save(); x.globalAlpha = b; x.translate(0, (1 - b) * 10);
    x.fillStyle = COP; x.fillRect(W / 2 - 22, 312, 44, 3);
    text(x, 'THE TURMERIC TEST', W / 2 + 5, 366, '900 34px Lato', OBS, 'center', '9px');
    x.restore();
  }
}

function drawCallout(x, t) {                        // names the stone while the camera moves in
  const a = ease(seg(t, 5.15, 5.45)) * (1 - ease(seg(t, 7.7, 8.0)));
  if (a <= 0) return;
  const [sx, sy] = toScreen(camera(t), P.x + 92, P.y - 86), ly = 640, ex = sx + (sy - ly) * 0.72, k = easeOut(seg(t, 5.2, 5.75));
  x.save(); x.globalAlpha = a;
  x.strokeStyle = COP; x.lineWidth = 3; x.lineCap = 'round'; x.lineJoin = 'round';
  const total = Math.hypot(ex - sx, ly - sy) + (984 - ex), d = total * k, l1 = Math.hypot(ex - sx, ly - sy);
  x.beginPath(); x.moveTo(sx, sy);
  if (d <= l1) x.lineTo(sx + (ex - sx) * d / l1, sy + (ly - sy) * d / l1); else { x.lineTo(ex, ly); x.lineTo(ex + (d - l1), ly); }
  x.stroke();
  x.fillStyle = '#fff'; x.beginPath(); x.arc(sx, sy, 10, 0, 7); x.fill(); x.stroke();
  text(x, 'SILVERSTONE', 986, ly - 70, '900 56px Lato', OBS, 'right', '5px', ease(seg(t, 5.4, 5.8)));
  text(x, 'Non-porous engineered stone', 984, ly - 22, '400 33px Lato', '#2B2B30', 'right', '0.5px', ease(seg(t, 6.15, 6.55)));
  x.restore();
}

function drawSection(x, t) {                        // a look from the side: the paste rests on top
  const a = ease(seg(t, 7.95, 8.4)) * (1 - ease(seg(t, 10.85, 11.2)));
  if (a <= 0) return;
  x.save(); x.globalAlpha = a; x.translate(0, (1 - a) * -22);
  x.save(); x.shadowColor = 'rgba(0,0,0,0.35)'; x.shadowBlur = 40; x.shadowOffsetY = 16;
  x.fillStyle = 'rgba(11,11,13,0.95)'; x.beginPath(); x.roundRect(110, 322, 860, 372, 34); x.fill(); x.restore();
  x.strokeStyle = 'rgba(201,206,214,0.28)'; x.lineWidth = 1.5; x.beginPath(); x.roundRect(110, 322, 860, 372, 34); x.stroke();
  text(x, 'SEEN FROM THE SIDE', 160, 384, '700 22px Lato', SIL, 'left', '5px');
  const top = 530;
  // the slab
  x.save(); x.beginPath(); x.roundRect(160, top, 760, 104, 5); x.clip();
  x.drawImage(STONE, 300, 2600, 1520, 208, 160, top, 760, 104);
  let g = x.createLinearGradient(0, top, 0, top + 104); g.addColorStop(0, 'rgba(255,255,255,0.25)'); g.addColorStop(1, 'rgba(40,36,30,0.28)');
  x.fillStyle = g; x.fillRect(160, top, 760, 104);
  x.restore();
  text(x, 'SILVERSTONE', 540, top + 66, '900 26px Lato', 'rgba(11,11,13,0.72)', 'center', '10px');
  // the paste on top
  const land = easeBack(seg(t, 8.3, 8.75));
  x.save(); x.translate(540, top); x.scale(1, land);
  g = x.createRadialGradient(-50, -70, 6, 0, 0, 170); g.addColorStop(0, '#FFD64A'); g.addColorStop(0.5, '#E9A810'); g.addColorStop(1, '#BC7A04');
  x.fillStyle = g; x.beginPath(); x.moveTo(-158, 0); x.bezierCurveTo(-150, -44, -86, -86, -6, -88); x.bezierCurveTo(70, -90, 150, -40, 158, 0); x.closePath(); x.fill();
  x.filter = 'blur(2px)'; x.fillStyle = 'rgba(255,252,228,0.6)'; x.beginPath(); x.ellipse(-58, -58, 30, 9, -0.5, 0, 7); x.fill();
  x.restore();
  // the surface: the line nothing crosses
  const ln = easeOut(seg(t, 8.7, 9.3)), pulse = 0.6 + 0.4 * Math.sin((t - 9.6) * 9) * seg(t, 9.6, 9.9) * (1 - seg(t, 10.5, 10.9));
  x.save(); x.shadowColor = COPL; x.shadowBlur = 14 * pulse; x.strokeStyle = COPL; x.lineWidth = 4; x.lineCap = 'round';
  x.beginPath(); x.moveTo(540 - 380 * ln, top); x.lineTo(540 + 380 * ln, top); x.stroke(); x.restore();
  // the paste tries to go down, and stays
  for (let i = 0; i < 3; i++) {
    const t0 = 9.55 + i * 0.12, k = seg(t, t0, t0 + 0.5); if (k <= 0 || k >= 1) continue;
    const d = Math.sin(Math.min(1, k * 2.2) * Math.PI / 2) * 22 * (1 - ease(seg(k, 0.45, 1))), ax = 470 + i * 70;
    x.save(); x.globalAlpha *= 1 - ease(seg(k, 0.6, 1)); x.strokeStyle = '#7A4A00'; x.lineWidth = 4; x.lineCap = x.lineJoin = 'round';
    x.beginPath(); x.moveTo(ax, top - 46 + d); x.lineTo(ax, top - 16 + d); x.moveTo(ax - 9, top - 26 + d); x.lineTo(ax, top - 16 + d); x.lineTo(ax + 9, top - 26 + d); x.stroke(); x.restore();
  }
  text(x, 'Stays on the surface', 160, 668, '400 28px Lato', '#E9ECF0', 'left', '0.5px', ease(seg(t, 9.0, 9.4)));
  x.restore();
}

function drawEnd(x, t) {                            // the logo and what to do next
  const a = ease(seg(t, 26.35, 27.0));
  if (a <= 0) return;
  x.save();
  x.fillStyle = `rgba(11,11,13,${0.86 * a})`; x.fillRect(0, 0, W, H);
  const b = easeOut(seg(t, 26.7, 27.3));
  if (LOGO_W) { x.globalAlpha = b; const lw = 600, lh = lw * 246 / 1080; x.drawImage(LOGO_W, (W - lw) / 2, 690 + (1 - b) * 16, lw, lh); }
  const v = easeOut(seg(t, 26.9, 27.7));              // the copper and silver vein
  const g = x.createLinearGradient(W / 2 - 150, 0, W / 2 + 150, 0); g.addColorStop(0, COP); g.addColorStop(1, SIL);
  x.globalAlpha = 1; x.strokeStyle = g; x.lineWidth = 2.5; x.lineCap = 'round';
  x.beginPath(); x.moveTo(W / 2 - 150 * v, 902); x.lineTo(W / 2 + 150 * v, 902); x.stroke();
  const c1 = easeOut(seg(t, 27.1, 27.6)), c2 = easeOut(seg(t, 27.3, 27.8)), c3 = easeOut(seg(t, 27.6, 28.1));
  text(x, 'Book a free consultation.', W / 2, 1000 + (1 - c1) * 14, '700 62px Lato', '#FFFFFF', 'center', '0px', c1);
  text(x, 'A design expert calls within 24 hours.', W / 2, 1072 + (1 - c2) * 14, '400 38px Lato', SIL, 'center', '0px', c2);
  text(x, 'MAGPPIE.COM', W / 2 + 4, 1180, '700 28px Lato', COPL, 'center', '8px', c3);
  x.restore();
}

const SHOWN = [
  ['In Indian kitchens,', 'turmeric leaves stubborn stains', 'that linger for days.'],
  ['But on SILVERSTONE,', 'the non-porous engineered stone,', 'the paste sits on the surface,', 'never sinking in.'],
  ['A single wipe with a damp cloth', 'lifts the residue,', "revealing the stone's original white."],
  ['No swelling, no staining,', 'zero formaldehyde,', 'just pure, safe stone that lasts.'],
  ['It also resists water,', 'and termites find nothing to eat,', 'giving families peace of mind', 'for generations every single day.'],
];
const STRESS = /^(stubborn|SILVERSTONE,?|non-porous|No|no|zero|peace)$/;

function buildCaptions(timings) {
  const caps = [];
  timings.lines.forEach((line, li) => {
    const words = line.words.filter(w => /[A-Za-z]/.test(w.w));
    let i = 0;
    SHOWN[li].forEach(textOf => {
      const n = textOf.split(' ').length;
      caps.push({ text: textOf, start: words[i].s, last: words[Math.min(words.length, i + n) - 1].e });
      i += n;
    });
    if (i !== words.length) console.warn('caption words do not match the voice on line', li + 1, i, words.length);
  });
  caps.forEach((c, i) => { c.end = i + 1 < caps.length ? Math.min(caps[i + 1].start, c.last + 0.5) : c.last + 0.45; });
  return caps;
}

function drawCaption(x, t) {
  const cap = CAPS.find(c => t >= c.start - 0.04 && t < c.end);
  if (!cap) return;
  const a = easeOut(seg(t, cap.start - 0.04, cap.start + 0.14)) * (1 - ease(seg(t, cap.end - 0.1, cap.end)));
  x.save(); x.font = '700 58px Lato'; x.textBaseline = 'alphabetic';
  const sp = x.measureText(' ').width, words = cap.text.split(' ').map(word => [word, x.measureText(word).width]);
  const wide = r => r.reduce((s, w) => s + w[1], 0) + sp * (r.length - 1);
  let rows = [words];
  if (wide(words) > 860) {
    let best = 1, gap = Infinity;
    for (let i = 1; i < words.length; i++) { const d = Math.abs(wide(words.slice(0, i)) - wide(words.slice(i))); if (d < gap) { gap = d; best = i; } }
    rows = [words.slice(0, best), words.slice(best)];
  }
  const widths = rows.map(wide);
  const bw = Math.max(...widths) + 84, LH = 76, bh = rows.length * LH + 40, cy = 1436;
  x.globalAlpha = a; x.translate(0, (1 - a) * 14);
  x.save(); x.shadowColor = 'rgba(0,0,0,0.28)'; x.shadowBlur = 26; x.shadowOffsetY = 8;
  x.fillStyle = 'rgba(11,11,13,0.86)'; x.beginPath(); x.roundRect((W - bw) / 2, cy - bh / 2, bw, bh, 28); x.fill(); x.restore();
  rows.forEach((row, ri) => {
    let px = (W - widths[ri]) / 2; const py = cy - bh / 2 + 20 + LH * ri + 56;
    row.forEach(([word, ww]) => { x.fillStyle = STRESS.test(word) ? COPL : '#FFFFFF'; x.textAlign = 'left'; x.fillText(word, px, py); px += ww + sp; });
  });
  x.restore();
}

/* ---------- one frame ---------- */

const SCENES = [[0, drawCounter], [22.0, drawWater], [23.6, drawKitchen]], FADE = 0.4;

function frame(x, t) {
  x.setTransform(1, 0, 0, 1, 0, 0); x.globalAlpha = 1; x.filter = 'none'; x.globalCompositeOperation = 'source-over';
  let i = SCENES.length - 1; while (i > 0 && t < SCENES[i][0]) i--;
  const since = t - SCENES[i][0];
  if (i > 0 && since < FADE) {                         // the cut is a short dissolve
    SCENES[i - 1][1](x, t);
    const b = BUF.getContext('2d'); b.setTransform(1, 0, 0, 1, 0, 0); b.globalAlpha = 1; b.filter = 'none';
    SCENES[i][1](b, t);
    x.globalAlpha = ease(since / FADE); x.drawImage(BUF, 0, 0); x.globalAlpha = 1;
  } else SCENES[i][1](x, t);
  drawBrandTop(x, t); drawCallout(x, t); drawSection(x, t); drawEnd(x, t); drawCaption(x, t);
  const n = Math.round(t * FPS), r = rng(n * 7919 + 1), ox = Math.floor(r() * 512), oy = Math.floor(r() * 512);   // film grain
  x.save(); x.globalAlpha = 0.26;
  for (let gy = -oy; gy < H; gy += 512) for (let gx = -ox; gx < W; gx += 512) x.drawImage(GRAIN, gx, gy);
  x.restore();
}

/* ---------- start ---------- */

function loadImage(src) { return new Promise(res => { const im = new Image(); im.onload = () => res(im); im.onerror = () => res(null); im.src = src; }); }

async function setup() {
  const [timings, lb, lw] = await Promise.all([fetch('timings.json').then(r => r.json()), loadImage('logo-black.png'), loadImage('logo-white.svg')]);
  await Promise.all(['400 30px Lato', '700 30px Lato', '900 30px Lato'].map(f => document.fonts.load(f)));
  LOGO_B = lb; LOGO_W = lw; CAPS = buildCaptions(timings);
  STONE = buildStone(); LIGHT = buildLight(); LEAVES = buildLeaves(); PASTE = buildPaste(); SPOON = buildSpoon(); HAND = buildHand();
  CLOTH = buildCloth(); STAIN = buildStain(); GRAIN = buildGrain(); KITCHEN = buildKitchen(); BUF = mk(W, H);
}
