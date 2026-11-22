// ─────────────────────────────────────────────────────────────
//  다관절 3D 검투사 (목·어깨·팔꿈치·손목·척추·고관절·무릎 + 망토 물리)
//  - 2본 IK로 손/발 타깃 해석, 스윙 궤적은 회전축 기반 프로시저럴 생성
//  - 스프링 피격 리액션, 투구/방패 파손 분리, 슬로우모션 KO
// ─────────────────────────────────────────────────────────────
import * as THREE from 'three';
import { tinted } from './textures.js';

const V3 = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const _a = V3(), _b = V3(), _c = V3(), _d = V3(), _e = V3(), _f = V3(), _g = V3(), _h = V3(), _s = V3(), _t = V3(), _u = V3(), _w = V3(), _y = V3(), _z = V3();
const _q = new THREE.Quaternion(), _q2 = new THREE.Quaternion(), _q3 = new THREE.Quaternion(), _qr = new THREE.Quaternion(), _hq = new THREE.Quaternion(), _fq = new THREE.Quaternion();
const UP = new THREE.Vector3(0, 1, 0);
const _m = new THREE.Matrix4(), _sc = V3();
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
const lerp = (a, b, t) => a + (b - a) * t;
const ss = (t) => { t = clamp(t, 0, 1); return t * t * (3 - 2 * t); };
const io3 = (t) => { t = clamp(t, 0, 1); return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2; };
const o3 = (t) => 1 - Math.pow(1 - clamp(t, 0, 1), 3);

// ── 지오메트리 헬퍼 ─────────────────────────────────────────
function lathe(profile, seg = 18, v0 = 0, v1 = 1) {
  if (profile[0][1] > profile[profile.length - 1][1]) profile = profile.slice().reverse();
  const g = new THREE.LatheGeometry(profile.map(([r, y]) => new THREE.Vector2(r, y)), seg, Math.PI, Math.PI * 2);
  if (v0 !== 0 || v1 !== 1) { const uv = g.attributes.uv; for (let i = 0; i < uv.count; i++) uv.setY(i, v0 + uv.getY(i) * (v1 - v0)); }
  return g;
}
// 관절에서 -Y로 뻗는 근육형 사지
function limb(len, r0, r1, bulge = 0, at = 0.35, seg = 14) {
  const pts = [];
  const N = 9;
  for (let i = 0; i <= N; i++) {
    const t = i / N;
    const r = lerp(r0, r1, t) + bulge * Math.exp(-Math.pow((t - at) / 0.22, 2));
    pts.push([Math.max(0.001, r), -t * len]);
  }
  pts.unshift([0.001, 0.012]); pts.push([0.001, -len - 0.01]);
  return lathe(pts.reverse(), seg);
}
function taperTube(points, r0, r1, seg = 16, rad = 8) {
  const curve = new THREE.CatmullRomCurve3(points);
  const frames = curve.computeFrenetFrames(seg, false);
  const pos = [], idx = [];
  for (let i = 0; i <= seg; i++) {
    const t = i / seg, p = curve.getPointAt(t), r = lerp(r0, r1, Math.pow(t, 0.9));
    const N = frames.normals[i], B = frames.binormals[i];
    for (let j = 0; j <= rad; j++) {
      const a = (j / rad) * Math.PI * 2, c = Math.cos(a), s = Math.sin(a);
      pos.push(p.x + r * (c * N.x + s * B.x), p.y + r * (c * N.y + s * B.y), p.z + r * (c * N.z + s * B.z));
    }
  }
  for (let i = 0; i < seg; i++) for (let j = 0; j < rad; j++) {
    const a = i * (rad + 1) + j, b = a + rad + 1;
    idx.push(a, b, a + 1, b, b + 1, a + 1);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx); g.computeVertexNormals();
  return g;
}
function bentBox(w, h, t, R, segX = 18) {
  const g = new THREE.BoxGeometry(w, h, t, segX, 1, 1);
  const p = g.attributes.position;
  for (let i = 0; i < p.count; i++) {
    const x = p.getX(i), z = p.getZ(i), ang = x / R, r = R + z;
    p.setX(i, r * Math.sin(ang)); p.setZ(i, r * Math.cos(ang) - R);
  }
  g.computeVertexNormals();
  return g;
}
// 칼날: 길이 +Y, 날 ±Z, 면 ±X
function bladeGeo(len, w0, wMid, thick, start, curve = 0) {
  const s = new THREE.Shape(), N = 10, L = [], Rr = [];
  for (let i = 0; i <= N; i++) {
    const t = i / N, cx = curve * t * t * len, y = t * len;
    const w = (t < 0.3 ? lerp(w0, wMid, t / 0.3) : wMid * Math.pow(1 - (t - 0.3) / 0.7, 0.75)) * 0.5;
    L.push([cx - w, y]); Rr.push([cx + w, y]);
  }
  s.moveTo(L[0][0], L[0][1]);
  for (let i = 1; i <= N; i++) s.lineTo(L[i][0], L[i][1]);
  for (let i = N - 1; i >= 0; i--) s.lineTo(Rr[i][0], Rr[i][1]);
  s.closePath();
  const g = new THREE.ExtrudeGeometry(s, { depth: thick * 0.25, bevelEnabled: true, bevelThickness: thick * 0.38, bevelSize: Math.min(w0, wMid) * 0.16, bevelSegments: 1, curveSegments: 4 });
  g.translate(0, 0, -thick * 0.125);
  g.rotateY(Math.PI / 2);
  g.translate(0, start, 0);
  return g;
}
const M3 = (geo, mat, cast = true) => { const m = new THREE.Mesh(geo, mat); m.castShadow = cast; m.receiveShadow = true; return m; };

// ── 무기 / 방패 팩토리 ──────────────────────────────────────
export function buildWeapon(type, M, opts = {}) {
  const g = new THREE.Group();
  const bladeMat = (opts.gilded ? M.gold : M.steel).clone();
  bladeMat.emissive = new THREE.Color(0x000000); bladeMat.emissiveIntensity = 1;
  const grip = M.leatherDark, fit = opts.fit || M.brass;
  let tip = 0.6, bladeMesh = null;
  const add = (geo, mat, x = 0, y = 0, z = 0) => { const m = M3(geo, mat); m.position.set(x, y, z); g.add(m); return m; };
  if (type === 'gladius' || type === 'spatha') {
    const long = type === 'spatha';
    add(new THREE.CylinderGeometry(0.017, 0.019, 0.11, 10), grip, 0, 0, 0);
    add(new THREE.SphereGeometry(0.03, 12, 8), fit, 0, -0.075, 0).scale.set(1, 0.75, 1);
    add(new THREE.BoxGeometry(0.03, 0.026, long ? 0.15 : 0.085), fit, 0, 0.068, 0);
    const len = long ? 0.76 : 0.52;
    bladeMesh = add(bladeGeo(len, long ? 0.05 : 0.054, long ? 0.052 : 0.06, 0.012, 0.08), bladeMat);
    tip = 0.08 + len;
  } else if (type === 'sica') {
    add(new THREE.CylinderGeometry(0.016, 0.018, 0.1, 8), grip, 0, 0, 0);
    add(new THREE.BoxGeometry(0.028, 0.02, 0.06), fit, 0, 0.06, 0);
    bladeMesh = add(bladeGeo(0.46, 0.04, 0.046, 0.01, 0.07, 0.16), bladeMat);
    // 휜 방향을 날(+Z) 쪽으로
    bladeMesh.rotation.y = Math.PI;
    tip = 0.52;
  } else if (type === 'axe2h' || type === 'axe1h') {
    const two = type === 'axe2h', H = two ? 1.18 : 0.66, base = two ? -0.14 : -0.08;
    const haft = add(new THREE.CylinderGeometry(0.02, 0.024, H, 10), M.wood, 0, base + H / 2, 0);
    haft.castShadow = true;
    add(new THREE.CylinderGeometry(0.026, 0.026, 0.16, 10), grip, 0, 0.02, 0);
    const s = new THREE.Shape(), k = two ? 1.25 : 0.9;
    s.moveTo(0.03 * k, -0.07 * k); s.lineTo(-0.05 * k, -0.05 * k);
    s.quadraticCurveTo(-0.15 * k, -0.11 * k, -0.22 * k, -0.18 * k);
    s.quadraticCurveTo(-0.29 * k, 0, -0.22 * k, 0.18 * k);
    s.quadraticCurveTo(-0.15 * k, 0.11 * k, -0.05 * k, 0.05 * k);
    s.lineTo(0.03 * k, 0.07 * k); s.closePath();
    const hg = new THREE.ExtrudeGeometry(s, { depth: 0.012, bevelEnabled: true, bevelThickness: 0.009, bevelSize: 0.008, bevelSegments: 1, curveSegments: 10 });
    hg.translate(0, 0, -0.006); hg.rotateY(Math.PI / 2);
    const top = base + H - 0.13;
    bladeMesh = add(hg, bladeMat, 0, top, 0);
    add(new THREE.BoxGeometry(0.05, 0.12, 0.06), M.darkIron, 0, top, 0);
    const spike = add(new THREE.ConeGeometry(0.022, 0.12, 8), M.darkIron, 0, top, -0.08); spike.rotation.x = -Math.PI / 2;
    tip = top + 0.08;
    g.userData.twoHandOffset = 0.36;
  }
  return { group: g, tip, bladeMat, blade: bladeMesh };
}

export function buildShield(type, M, colors = ['#8e1b16', '#d2a645'], seed = 3, faceTex = null) {
  const g = new THREE.Group();
  const tex = faceTex;
  const face = new THREE.MeshStandardMaterial({
    map: tex ? tex.map : null, normalMap: tex ? tex.normalMap : null, roughnessMap: tex ? tex.orm : null, metalnessMap: tex ? tex.orm : null,
    color: tex ? 0xffffff : colors[0], roughness: 1, metalness: tex ? 1 : 0,
  });
  const back = M.wood, rim = M.brass;
  let radius = 0.4;
  if (type === 'scutum') {
    const geo = bentBox(0.64, 0.98, 0.035, 0.6, 20);
    const m = M3(geo, [rim, rim, rim, rim, face, back]); m.position.z = 0.06; g.add(m);
    const boss = M3(new THREE.SphereGeometry(0.085, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2), M.brass);
    boss.rotation.x = Math.PI / 2; boss.scale.set(1, 0.55, 1); boss.position.z = 0.078; g.add(boss);
    for (const sx of [-1, 1]) { const e = M3(new THREE.BoxGeometry(0.02, 0.98, 0.045), rim); e.position.set(sx * 0.3, 0, 0.022); e.rotation.y = -sx * 0.52; g.add(e); }
    radius = 0.5;
  } else {
    const R = type === 'parma' ? 0.34 : 0.3;
    const geo = new THREE.CylinderGeometry(R, R, 0.03, 40); geo.rotateX(Math.PI / 2);
    const m = M3(geo, [rim, face, back]); m.position.z = 0.055; g.add(m);
    const ring = M3(new THREE.TorusGeometry(R, 0.014, 6, 40), rim); ring.position.z = 0.055; g.add(ring);
    const boss = M3(new THREE.SphereGeometry(0.075, 16, 10, 0, Math.PI * 2, 0, Math.PI / 2), M.gold);
    boss.rotation.x = Math.PI / 2; boss.scale.set(1, 0.6, 1); boss.position.z = 0.07; g.add(boss);
    radius = R;
  }
  const handle = M3(new THREE.BoxGeometry(0.11, 0.025, 0.025), M.leatherDark); handle.position.z = 0.02; g.add(handle);
  g.userData.radius = radius;
  return g;
}

// ── 외형 프리셋 ─────────────────────────────────────────────
const SKINS = [0xe0b08a, 0xcf9a74, 0xb57e58, 0x9a6444, 0x7a4c34, 0xd9a37e];
const CLOTHS = [0x8a1c1c, 0x1c3f8a, 0x5e1a6a, 0x2a5a2a, 0x8a6a1c, 0x3a3a3a, 0x7a3a14];
function srand(seed) { let s = (seed * 9301 + 49297) % 233280; return () => ((s = (s * 9301 + 49297) % 233280) / 233280); }
export function makeLook(arch, seed = 1) {
  const r = srand(seed + 7), pk = (a) => a[Math.floor(r() * a.length)];
  const skin = pk(SKINS), cloth = pk(CLOTHS);
  switch (arch) {
    case 'secutor': return {
      style: 'sword_shield', weapon: 'gladius', shield: 'scutum', helmet: 'murmillo', metal: pk(['brass', 'bronze', 'iron']), skin, cloth,
      crest: cloth, manica: 'R', greave: true, shieldColors: [pk(['#8e1b16', '#1d3c7a', '#5a1a5e', '#2c5a24']), '#d6ad4c'], scale: 1, seed,
    };
    case 'assassin': return {
      style: 'dual', weapon: 'sica', offWeapon: 'sica', helmet: 'masked', metal: 'dark', skin, cloth: pk([0x2a2a2e, 0x3a1a1a, 0x1a2a3a]),
      cape: { len: 0.62, color: pk([0x241a1a, 0x1a1a24, 0x3a1010]) }, bracers: true, scale: 0.96, seed,
    };
    case 'berserker': return {
      style: 'axe2h', weapon: 'axe2h', helmet: 'horned', metal: 'iron', skin: pk([0xe0b08a, 0xd9a37e, 0xcf9a74]), cloth: pk([0x4a3a2a, 0x3a2a1a, 0x5a4a3a]),
      fur: true, cape: { len: 0.78, color: 0x6a5a48, fur: true }, beard: true, straps: true, scale: 1.1, seed,
    };
    case 'champion': return {
      style: 'sword_shield', weapon: 'spatha', shield: 'parma', helmet: 'galea', metal: 'gold', skin, cloth: 0x7a0e0e,
      crest: 0xb01010, cuirass: true, cape: { len: 1.02, color: 0x9a1010 }, manica: 'R', greave: true, shieldColors: ['#6e0d0d', '#e2bb55'], scale: 1.05, seed, boss: true,
    };
    default: return makeLook('secutor', seed);
  }
}
export function playerLook(save) {
  const a = save.armorLvl, w = save.weapon;
  const metal = a >= 8 ? 'gold' : a >= 4 ? 'brass' : 'iron';
  return {
    style: w === 'dual' ? 'dual' : 'sword_shield',
    weapon: { gladius: 'gladius', broadsword: 'spatha', dual: 'gladius', axe: 'axe1h' }[w],
    offWeapon: w === 'dual' ? 'gladius' : null,
    shield: w === 'dual' ? null : 'scutum', helmet: 'galea', metal, skin: 0xcf9a74, cloth: 0x8a1c1c, crest: 0xc8a040,
    manica: a >= 3 ? 'R' : null, greave: a >= 5, cuirass: a >= 7, cape: a >= 2 ? { len: 0.9, color: 0x8a1414 } : null,
    shieldColors: ['#8e1b16', '#d2a645'], scale: 1.02, seed: 99, player: true,
  };
}

// ── 포즈 ────────────────────────────────────────────────────
class Hand { constructor() { this.p = V3(); this.b = V3(0, 1, 0); this.e = V3(0, 0, 1); } }
class Pose {
  constructor() {
    this.body = V3(); this.hips = V3(); this.spine = V3(); this.chest = V3(); this.neck = V3(); this.head = V3();
    this.R = new Hand(); this.L = new Hand(); this.fL = V3(0.12, 0, 0.15); this.fR = V3(-0.12, 0, -0.12);
    this.fall = V3(); this.fk = 0;
    this.aR = V3(); this.eR = V3(); this.aL = V3(); this.eL = V3(); this.tR = V3(); this.kR = V3(); this.tL = V3(); this.kL = V3();
  }
  copy(o) {
    for (const k of ['body', 'hips', 'spine', 'chest', 'neck', 'head', 'fL', 'fR', 'fall', 'aR', 'eR', 'aL', 'eL', 'tR', 'kR', 'tL', 'kL']) this[k].copy(o[k]);
    for (const h of ['R', 'L']) { this[h].p.copy(o[h].p); this[h].b.copy(o[h].b); this[h].e.copy(o[h].e); }
    this.fk = o.fk; return this;
  }
  lerp(o, t) {
    for (const k of ['body', 'hips', 'spine', 'chest', 'neck', 'head', 'fL', 'fR', 'fall', 'aR', 'eR', 'aL', 'eL', 'tR', 'kR', 'tL', 'kL']) this[k].lerp(o[k], t);
    for (const h of ['R', 'L']) { this[h].p.lerp(o[h].p, t); this[h].b.lerp(o[h].b, t).normalize(); this[h].e.lerp(o[h].e, t); }
    this.fk = lerp(this.fk, o.fk, t); return this;
  }
}
const setH = (h, px, py, pz, bx, by, bz, ex, ey, ez) => { h.p.set(px, py, pz); h.b.set(bx, by, bz).normalize(); h.e.set(ex, ey, ez); };

// 스탠스 포즈 생성
function stancePose(o, style, stance, t, g) {
  const br = Math.sin(t * (style === 'axe2h' ? 1.5 : 1.8)), sway = Math.sin(t * 0.63);
  o.fall.set(0, 0, 0); o.fk = 0;
  o.body.set(sway * 0.018, -0.065 + br * 0.006, 0);
  o.hips.set(0, -0.28, 0); o.spine.set(0.02, 0.1, 0); o.chest.set(br * 0.025, 0.08, 0); o.neck.set(0, 0.05, 0); o.head.set(0.05, 0.05, 0);
  o.fL.set(0.14, 0, 0.2); o.fR.set(-0.14, 0, -0.17);
  const hasShield = g.hasShield;
  if (style === 'dual') {
    const bob = Math.sin(t * 4.4) * 0.012;
    o.body.y += bob; o.hips.y = -0.12; o.spine.y = 0.06; o.chest.y = 0.04;
    o.fL.set(0.17, 0, 0.16); o.fR.set(-0.17, 0, -0.12);
    setH(o.R, -0.21, 1.12 + bob, 0.3, 0.3, 0.68, 0.7, 0, 1, -0.6);
    setH(o.L, 0.21, 1.08 + bob, 0.32, -0.3, 0.62, 0.72, 0, 1, -0.6);
  } else if (style === 'axe2h' || style === 'sword2h') {
    o.body.y -= 0.05; o.hips.y = -0.36; o.spine.y = 0.12; o.chest.y = 0.1; o.chest.x += br * 0.02;
    o.fL.set(0.2, 0, 0.22); o.fR.set(-0.18, 0, -0.2);
    setH(o.R, -0.1, 1.0, 0.26, 0.48, 0.84, 0.26, 0, 0.2, 1);
    o.L.p.copy(o.R.p).addScaledVector(o.R.b, g.twoHandOffset); o.L.b.copy(o.R.b); o.L.e.copy(o.R.e);
  } else {
    setH(o.R, -0.24, 1.02, 0.26, 0.25, 0.55, 0.8, 0, 1, -0.6);
    if (hasShield) setH(o.L, 0.1, 1.16, 0.36, -0.1, 1, 0, 0.15, 0, 1);
    else setH(o.L, 0.2, 1.1, 0.3, 0, 1, 0.3, 0, 0, 1);
  }
  switch (stance) {
    case 'guardHigh':
      o.body.y -= 0.05;
      if (hasShield) { setH(o.L, 0.02, 1.47, 0.37, 0, 1, 0.08, 0, 0.12, 1); setH(o.R, -0.27, 1.18, 0.02, 0.15, 0.25, 0.95, 0, 1, -0.2); }
      else if (style === 'dual') { setH(o.R, -0.08, 1.38, 0.34, 0.75, 0.55, 0.35, 0, 0.2, 1); setH(o.L, 0.08, 1.36, 0.35, -0.75, 0.55, 0.35, 0, 0.2, 1); }
      break;
    case 'guardLow':
      o.body.y -= 0.04;
      if (hasShield) { setH(o.L, 0.04, 0.98, 0.37, 0, 1, 0, 0, -0.1, 1); setH(o.R, -0.2, 1.62, 0.04, 0.2, -0.35, 0.9, 0, 1, 0.4); }
      break;
    case 'stagger': case 'stun': {
      const w = Math.sin(t * 7.3), w2 = Math.sin(t * 3.1);
      o.body.set(w2 * 0.05, -0.11, -0.04); o.spine.x = 0.16; o.chest.set(0.42, 0.05 + w * 0.06, w * 0.08); o.head.set(0.32, w2 * 0.2, w * 0.1);
      setH(o.R, -0.3, 0.84, 0.14, 0, -0.5, 0.85, 0, 0.85, 0.5);
      if (style === 'axe2h' || style === 'sword2h') { setH(o.R, -0.2, 0.75, 0.2, 0.3, -0.6, 0.7, 0, 0.7, 0.6); o.L.p.copy(o.R.p).addScaledVector(o.R.b, g.twoHandOffset); o.L.b.copy(o.R.b); o.L.e.copy(o.R.e); }
      else if (hasShield) setH(o.L, 0.33, 0.86, 0.12, 0.3, 1, 0.2, 0.6, 0, 0.8);
      else setH(o.L, 0.3, 0.84, 0.14, 0, -0.5, 0.85, 0, 0.85, 0.5);
      break;
    }
    case 'taunt':
      o.chest.x = -0.22; o.head.x = -0.32; o.spine.x = -0.05; o.hips.y = 0; o.spine.y = 0; o.chest.y = 0; o.neck.y = 0; o.head.y = 0;
      setH(o.R, -0.62, 1.5, 0.12, -0.5, 0.86, 0.1, 0, 0, 1);
      if (style !== 'axe2h' && style !== 'sword2h') setH(o.L, 0.6, 1.48, 0.12, hasShield ? 0 : 0.5, 1, hasShield ? 0 : 0.1, hasShield ? 0.7 : 0, 0, hasShield ? 0.7 : 1);
      else { setH(o.R, -0.05, 1.75, 0.1, 0.1, 1, 0, 0, 0, 1); o.L.p.copy(o.R.p).addScaledVector(o.R.b, g.twoHandOffset); o.L.b.copy(o.R.b); o.L.e.copy(o.R.e); }
      break;
    case 'victory':
      o.chest.x = -0.12; o.head.x = -0.2; o.hips.y = 0; o.spine.y = 0; o.chest.y = 0;
      setH(o.R, -0.3, 1.95, 0.1, 0.05, 1, 0.1, 0, 0, 1);
      break;
  }
  // 머리는 정면(상대) 응시: 몸통 비틀림 상쇄
  o.head.y -= o.hips.y + o.spine.y + o.chest.y + o.neck.y;
}

// ── 행동(Action) ────────────────────────────────────────────
// 스윙: 화면 기준 궤적 (dx,dy)에 수직인 축을 중심으로 칼날 방향을 회전
export function swingSpec(dir, o = {}) {
  const [dx, dy] = dir;
  return {
    dx, dy, hand: o.hand || 'R', windup: o.windup ?? 0.6, strike: o.strike ?? 0.17, recover: o.recover ?? 0.45,
    arc: (o.arc ?? 104) * Math.PI / 180, reach: o.reach ?? 0.47, lunge: (o.lunge ?? 0.54) * 0.78, red: !!o.red,
    pivotY: o.pivotY ?? (1.42 - 0.1 * Math.max(0, dy)), pivotX: o.pivotX, heavy: !!o.heavy, tremble: o.tremble ?? (o.heavy ? 1 : 0),
  };
}
function swingFrame(spec, theta, outHand, outBlade, outEdge, g) {
  const { dx, dy } = spec, s = Math.sin(theta), c = Math.cos(theta);
  outBlade.set(dx * s, dy * s, c);
  const ta = theta * 0.74, sa = Math.sin(ta), ca = Math.cos(ta);
  const side = spec.hand === 'L' ? 1 : -1;
  const px = spec.pivotX ?? (side * (spec.hand === '2H' ? 0.02 : 0.05) + dx * 0.02);
  outHand.set(px + dx * sa * spec.reach, spec.pivotY + dy * sa * spec.reach, 0.14 + ca * spec.reach);
  outEdge.set(dx * c, dy * c, -s);
}
const lungeAt = (u, L) => L * ss(u / 0.55) * (1 - 0.35 * ss((u - 0.75) / 0.25));

class SwingAction {
  constructor(g, spec) {
    this.g = g; this.spec = spec; this.t = 0;
    this.start = new Pose().copy(g.pose);
    this.th0 = -spec.arc * 1.12; this.th1 = spec.arc;
    // θ=0(충돌 순간)이 되는 진행도 계산
    const target = (0 - this.th0) / (this.th1 - this.th0);
    let lo = 0, hi = 1;
    for (let i = 0; i < 24; i++) { const mid = (lo + hi) / 2; if (ss(mid) < target) lo = mid; else hi = mid; }
    this.impactFrac = (lo + hi) / 2;
    this.impactT = spec.windup + spec.strike * this.impactFrac;
    this.endT = spec.windup + spec.strike + spec.recover;
    this.tmp = new Pose(); this.base = new Pose();
    this.cancelled = false;
  }
  thetaAt(t) {
    const { windup: W, strike: S } = this.spec;
    if (t < W) return this.th0;
    return lerp(this.th0, this.th1, ss((t - W) / S));
  }
  progressU(theta) { return (theta - this.th0) / (this.th1 - this.th0); }
  poseAt(out, theta, u) {
    const g = this.g, sp = this.spec;
    stancePose(out, g.style, g.stance === 'taunt' ? 'idle' : g.stance, g.time, g);
    const hand = sp.hand === 'L' ? out.L : out.R;
    swingFrame(sp, theta, hand.p, hand.b, hand.e, g);
    const lz = lungeAt(u, sp.lunge);
    hand.p.z += lz;
    if (sp.hand === '2H') { out.L.p.copy(hand.p).addScaledVector(hand.b, g.twoHandOffset); out.L.b.copy(hand.b); out.L.e.copy(hand.e); }
    else if (g.hasShield && sp.hand === 'R') { out.L.p.set(0.16, 1.1, 0.3 + lz * 0.6); out.L.b.set(0.25, 1, 0).normalize(); out.L.e.set(0.45, 0, 1); }
    const k = Math.sin(theta * 0.74);
    const side = sp.hand === 'L' ? -1 : 1;
    out.hips.y = -0.15 + side * k * sp.dx * 0.22; out.spine.y = side * k * sp.dx * 0.2; out.chest.y = side * k * sp.dx * 0.25;
    out.spine.x = k * -sp.dy * 0.12; out.chest.x = k * -sp.dy * 0.22 + 0.04;
    out.body.z = lz * 0.85; out.body.y = -0.075 - Math.abs(k) * 0.03 - lz * 0.07;
    out.fL.z = 0.2 + lz * 0.9; out.fR.z = -0.17 + lz * 0.5;
    out.head.y = -(out.hips.y + out.spine.y + out.chest.y + out.neck.y);
    return out;
  }
  update(dt) {
    this.t += dt;
    const sp = this.spec, g = this.g, t = this.t;
    if (t < sp.windup) {
      const th = this.th0, k = io3(t / sp.windup);
      this.poseAt(this.tmp, th, 0);
      if (sp.tremble && t > sp.windup * 0.55) { const a = Math.sin(t * 60) * 0.012 * sp.tremble; this.tmp.R.p.x += a; this.tmp.chest.z += a; }
      g.pose.copy(this.start).lerp(this.tmp, k);
    } else if (t < sp.windup + sp.strike) {
      const th = this.thetaAt(t);
      this.poseAt(g.pose, th, this.progressU(th));
    } else {
      const k = io3((t - sp.windup - sp.strike) / sp.recover);
      this.poseAt(this.tmp, this.th1, 1);
      stancePose(this.base, g.style, g.stance, g.time, g);
      g.pose.copy(this.tmp).lerp(this.base, k);
    }
    return t >= this.endT;
  }
  // 예고 궤적용 칼끝 경로 (월드 좌표)
  tipPath(n = 34) {
    const g = this.g, pts = [];
    const hand = V3(), blade = V3(), edge = V3();
    for (let i = 0; i <= n; i++) {
      const u = i / n, th = lerp(this.th0 * 0.92, this.th1 * 0.92, u);
      swingFrame(this.spec, th, hand, blade, edge, g);
      hand.z += lungeAt(this.progressU(th), this.spec.lunge);
      const tipLen = this.spec.hand === 'L' ? g.offTip : g.tip;
      const p = hand.clone().addScaledVector(blade, tipLen * 0.96);
      pts.push(g.root.localToWorld(p));
    }
    return pts;
  }
}

// 스냅샷에서 목표 포즈로 이동 후 유지/복귀 (회피, 경직, 반동 등)
class PoseAction {
  constructor(g, dur, fn, opts = {}) {
    this.g = g; this.dur = dur; this.fn = fn; this.t = 0; this.opts = opts;
    this.start = new Pose().copy(g.pose); this.tmp = new Pose();
  }
  update(dt) {
    this.t += dt;
    const u = clamp(this.t / this.dur, 0, 1);
    stancePose(this.tmp, this.g.style, this.g.stance, this.g.time, this.g);
    const w = this.fn(this.tmp, u, this.t);   // fn이 tmp를 수정하고 블렌드 가중치 반환
    this.g.pose.copy(this.start).lerp(this.tmp, w);
    return u >= 1;
  }
}

// ── 망토 물리 (Verlet) ──────────────────────────────────────
class Cape {
  constructor(g, mat, len, width = 0.4, cols = 6, rows = 8) {
    this.g = g; this.cols = cols; this.rows = rows; this.n = cols * rows;
    this.dx = width / (cols - 1); this.dy = len / (rows - 1);
    this.p = new Float32Array(this.n * 3); this.o = new Float32Array(this.n * 3);
    this.geo = new THREE.PlaneGeometry(width, len, cols - 1, rows - 1);
    this.mesh = new THREE.Mesh(this.geo, mat);
    this.mesh.frustumCulled = false; this.mesh.matrixAutoUpdate = false; this.mesh.castShadow = true;
    this.anchorL = V3(0.15, 0.2, -0.15); this.anchorR = V3(-0.15, 0.2, -0.15);
    this.ready = false; this.wind = 0;
  }
  _anchors(aL, aR) { aL.copy(this.anchorL).applyMatrix4(this.g.chestJ.matrixWorld); aR.copy(this.anchorR).applyMatrix4(this.g.chestJ.matrixWorld); }
  reset() {
    this._anchors(_a, _b);
    _c.set(0, 0, -1).applyQuaternion(this.g.root.quaternion);
    for (let r = 0; r < this.rows; r++) for (let c = 0; c < this.cols; c++) {
      const i = (r * this.cols + c) * 3, k = c / (this.cols - 1);
      _d.copy(_a).lerp(_b, k).addScaledVector(_c, 0.02 * r); _d.y -= r * this.dy;
      this.p[i] = this.o[i] = _d.x; this.p[i + 1] = this.o[i + 1] = _d.y; this.p[i + 2] = this.o[i + 2] = _d.z;
    }
    this.ready = true;
  }
  step(dt, time) {
    if (!this.ready) this.reset();
    const sub = Math.min(4, Math.max(1, Math.ceil(dt / (1 / 110))));
    const h = dt / sub, p = this.p, o = this.o, C = this.cols, s = this.g.scaleK;
    this._anchors(_a, _b);
    const chest = _e.setFromMatrixPosition(this.g.chestJ.matrixWorld); chest.y += 0.02 * s;
    const hips = _f.setFromMatrixPosition(this.g.hipsJ.matrixWorld);
    const fwd = _g.set(0, 0, 1).transformDirection(this.g.chestJ.matrixWorld);
    const wx = (0.5 + Math.sin(time * 0.7) * 0.4) * this.wind, wz = (0.2 + Math.sin(time * 1.3) * 0.3) * this.wind;
    for (let it = 0; it < sub; it++) {
      for (let i = C; i < this.n; i++) {
        const j = i * 3;
        for (let a = 0; a < 3; a++) {
          const cur = p[j + a], v = (cur - o[j + a]) * 0.985;
          o[j + a] = cur;
          p[j + a] = cur + v + (a === 1 ? -9.8 : a === 0 ? wx : wz) * h * h;
        }
      }
      for (let c = 0; c < C; c++) { const k = c / (C - 1), j = c * 3; _d.copy(_a).lerp(_b, k); p[j] = o[j] = _d.x; p[j + 1] = o[j + 1] = _d.y; p[j + 2] = o[j + 2] = _d.z; }
      for (let iter = 0; iter < 4; iter++) {
        for (let r = 0; r < this.rows; r++) for (let c = 0; c < C; c++) {
          const i = r * C + c;
          if (c < C - 1) this._link(i, i + 1, this.dx);
          if (r < this.rows - 1) this._link(i, i + C, this.dy);
          if (r < this.rows - 2) this._link(i, i + 2 * C, this.dy * 2);
        }
        for (let i = C; i < this.n; i++) {
          const j = i * 3;
          _d.set(p[j], p[j + 1], p[j + 2]);
          this._sphere(_d, chest, 0.2 * s); this._sphere(_d, hips, 0.19 * s);
          const dd = _h.copy(_d).sub(chest).dot(fwd), lim = -0.1 * s;
          if (dd > lim) _d.addScaledVector(fwd, lim - dd);
          if (_d.y < 0.02) _d.y = 0.02;
          p[j] = _d.x; p[j + 1] = _d.y; p[j + 2] = _d.z;
        }
      }
    }
    const pos = this.geo.attributes.position;
    for (let i = 0; i < this.n; i++) pos.setXYZ(i, p[i * 3], p[i * 3 + 1], p[i * 3 + 2]);
    pos.needsUpdate = true;
    this.geo.computeVertexNormals();
  }
  _link(a, b, rest) {
    const p = this.p, ia = a * 3, ib = b * 3;
    const dx = p[ib] - p[ia], dy = p[ib + 1] - p[ia + 1], dz = p[ib + 2] - p[ia + 2];
    const d = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1e-6, diff = (d - rest) / d;
    const pinA = a < this.cols, pinB = b < this.cols;
    const wa = pinA ? 0 : pinB ? 1 : 0.5, wb = pinB ? 0 : pinA ? 1 : 0.5;
    p[ia] += dx * diff * wa; p[ia + 1] += dy * diff * wa; p[ia + 2] += dz * diff * wa;
    p[ib] -= dx * diff * wb; p[ib + 1] -= dy * diff * wb; p[ib + 2] -= dz * diff * wb;
  }
  _sphere(v, c, r) {
    _h.copy(v).sub(c); const d = _h.length();
    if (d < r && d > 1e-5) v.copy(c).addScaledVector(_h, r / d);
  }
}

// ── 스프링 ──────────────────────────────────────────────────
class Spring {
  constructor(k = 170, c = 13) { this.x = 0; this.v = 0; this.k = k; this.c = c; }
  step(dt) { const a = -this.k * this.x - this.c * this.v; this.v += a * dt; this.x += this.v * dt; }
  kick(v) { this.v += v; }
}

// ── 검투사 ──────────────────────────────────────────────────
export class Gladiator {
  constructor(look, lib, opts = {}) {
    this.look = look; this.lib = lib; this.fx = opts.fx || null;
    this.style = look.style;
    this.baseStyle = look.style;
    this.scaleK = look.scale || 1;
    this.hasShield = !!look.shield;
    this.stance = 'idle';
    this.time = Math.random() * 10;
    this.pose = new Pose();
    this.target = new Pose();
    this.action = null;
    this.springs = { roll: new Spring(150, 11), yaw: new Spring(150, 11), pitch: new Spring(160, 12), head: new Spring(200, 10), bx: new Spring(120, 13), bz: new Spring(120, 13) };
    this.glow = 0; this.glowColor = new THREE.Color(1, 0.5, 0.1); this.glowTarget = 0;
    this.armorGlow = 0;
    this.dead = false;
    this.lookTarget = null;
    this._build();
    stancePose(this.pose, this.style, 'idle', this.time, this);
    this._apply();
  }

  _build() {
    const L = this.look, M = this.lib.M;
    const metalMat = { brass: M.brass, gold: M.gold, iron: M.iron, bronze: M.bronze, dark: M.darkIron }[L.metal] || M.brass;
    this.metalMat = metalMat;
    this.skinMat = tinted(M.skin, L.skin);
    this.torsoMat = tinted(M.torso, L.skin);
    this.clothMat = tinted(M.cloth, L.cloth);
    this.allMats = [this.skinMat, this.torsoMat];
    const s = this.scaleK;
    const root = this.root = new THREE.Group(); root.scale.setScalar(s);
    const fall = this.fallPivot = new THREE.Group(); root.add(fall);
    const body = this.bodyJ = new THREE.Group(); fall.add(body);
    const J = (parent, x, y, z) => { const j = new THREE.Group(); j.position.set(x, y, z); parent.add(j); return j; };
    this.hipsJ = J(body, 0, 1.0, 0);
    this.spineJ = J(this.hipsJ, 0, 0.11, 0);
    this.chestJ = J(this.spineJ, 0, 0.21, 0);
    this.neckJ = J(this.chestJ, 0, 0.18, 0.005);
    this.headJ = J(this.neckJ, 0, 0.085, 0.01);
    this.uArmR = J(this.chestJ, -0.19, 0.15, -0.01); this.fArmR = J(this.uArmR, 0, -0.29, 0); this.handR = J(this.fArmR, 0, -0.27, 0);
    this.uArmL = J(this.chestJ, 0.19, 0.15, -0.01); this.fArmL = J(this.uArmL, 0, -0.29, 0); this.handL = J(this.fArmL, 0, -0.27, 0);
    this.thighR = J(this.hipsJ, -0.095, -0.05, 0); this.shinR = J(this.thighR, 0, -0.45, 0); this.footR = J(this.shinR, 0, -0.43, 0);
    this.thighL = J(this.hipsJ, 0.095, -0.05, 0); this.shinL = J(this.thighL, 0, -0.43 - 0.02, 0); this.footL = J(this.shinL, 0, -0.43, 0);
    this.shinL.position.y = -0.45;
    this.lenU = 0.29; this.lenF = 0.27; this.lenT = 0.45; this.lenS = 0.43;

    const add = (parent, geo, mat, x = 0, y = 0, z = 0, cast = true) => { const m = M3(geo, mat, cast); m.position.set(x, y, z); parent.add(m); return m; };
    // 몸통 (복부 + 가슴, 근육 노멀맵)
    const abd = add(this.spineJ, lathe([[0.001, -0.15], [0.128, -0.14], [0.142, -0.07], [0.134, 0.03], [0.128, 0.11], [0.142, 0.2], [0.001, 0.21]], 22, 0.08, 0.6), this.torsoMat);
    abd.scale.set(1.28, 1, 0.82);
    const chest = add(this.chestJ, lathe([[0.001, -0.13], [0.132, -0.12], [0.152, -0.04], [0.176, 0.06], [0.181, 0.13], [0.162, 0.19], [0.11, 0.232], [0.05, 0.245], [0.001, 0.246]], 24, 0.52, 1.0), this.torsoMat);
    chest.scale.set(1.3, 1, 0.8);
    for (const sx of [-1, 1]) add(this.chestJ, new THREE.SphereGeometry(0.066, 14, 10), this.skinMat, sx * 0.19, 0.155, -0.005).scale.set(1, 0.9, 1);
    add(this.neckJ, new THREE.CylinderGeometry(0.052, 0.06, 0.12, 12), this.skinMat, 0, 0.04, 0);
    // 머리 (투구가 벗겨지면 보임)
    const head = this.headMesh = new THREE.Group(); this.headJ.add(head);
    add(head, new THREE.SphereGeometry(0.1, 20, 16), this.skinMat, 0, 0.1, 0.01).scale.set(0.9, 1.08, 1);
    const hair = tinted(M.cloth, 0x2a1c12, { sheen: 0 });
    add(head, new THREE.SphereGeometry(0.104, 18, 10, 0, Math.PI * 2, 0, Math.PI * 0.55), hair, 0, 0.11, -0.005).scale.set(0.92, 1.05, 1.02);
    add(head, new THREE.ConeGeometry(0.018, 0.05, 6), this.skinMat, 0, 0.09, 0.105).rotation.x = Math.PI / 2;
    for (const sx of [-1, 1]) { add(head, new THREE.SphereGeometry(0.013, 8, 6), M.void, sx * 0.034, 0.115, 0.088, false); add(head, new THREE.SphereGeometry(0.02, 8, 6), this.skinMat, sx * 0.092, 0.1, 0.0).scale.set(0.5, 1, 0.8); }
    if (L.beard) add(head, new THREE.SphereGeometry(0.075, 14, 10, 0, Math.PI * 2, Math.PI * 0.45, Math.PI * 0.55), hair, 0, 0.085, 0.03).scale.set(1.05, 1.2, 1);
    // 허리띠·샅바(subligaculum)
    const pelvis = new THREE.Group(); pelvis.scale.set(1.28, 1, 0.82); this.hipsJ.add(pelvis);
    add(pelvis, new THREE.CylinderGeometry(0.152, 0.148, 0.1, 22, 1, true), L.cuirass ? M.leatherDark : metalMat, 0, 0.0, 0);
    add(pelvis, new THREE.CylinderGeometry(0.15, 0.17, 0.17, 22, 1, true), this.clothMat, 0, -0.12, 0);
    const flap = add(this.hipsJ, new THREE.PlaneGeometry(0.15, 0.3, 1, 3), this.clothMat, 0, -0.18, 0.13); flap.rotation.x = -0.08;
    if (L.cuirass) {
      const cu = add(this.chestJ, lathe([[0.001, -0.15], [0.14, -0.14], [0.16, -0.05], [0.186, 0.06], [0.19, 0.13], [0.17, 0.19], [0.115, 0.236], [0.06, 0.25], [0.001, 0.252]], 24, 0.45, 1.0), new THREE.MeshPhysicalMaterial({ map: metalMat.map, normalMap: M.torso.normalMap, normalScale: new THREE.Vector2(2.2, 2.2), roughnessMap: metalMat.roughnessMap, metalnessMap: metalMat.metalnessMap, roughness: 1, metalness: 1, clearcoat: 0.6, clearcoatRoughness: 0.2 }));
      cu.scale.set(1.32, 1, 0.84);
      for (let i = 0; i < 12; i++) {
        const a = (i / 12) * Math.PI * 2, strip = add(this.hipsJ, new THREE.BoxGeometry(0.06, 0.2, 0.012), M.leather, Math.sin(a) * 0.19, -0.1, Math.cos(a) * 0.125);
        strip.rotation.y = a; strip.rotation.x = 0.12 * Math.cos(a);
      }
    }
    if (L.straps) {
      const st = add(this.chestJ, new THREE.TorusGeometry(0.2, 0.014, 6, 28), M.leather, 0, 0.06, 0); st.scale.set(1.18, 1.25, 0.82); st.rotation.set(0, Math.PI / 2, 0.75);
    }
    if (L.fur) {
      const fur = add(this.chestJ, new THREE.TorusGeometry(0.17, 0.075, 10, 24), M.fur, 0, 0.2, -0.01); fur.rotation.x = Math.PI / 2; fur.scale.set(1.35, 1.0, 0.8);
    }
    // 팔
    const armSet = (u, f, h, side, mani) => {
      add(u, limb(0.29, 0.054, 0.042, 0.009, 0.4), this.skinMat);
      add(f, new THREE.SphereGeometry(0.042, 12, 8), this.skinMat);
      add(f, limb(0.27, 0.046, 0.033, 0.006, 0.25), this.skinMat);
      add(h, new THREE.BoxGeometry(0.05, 0.088, 0.075), this.skinMat, 0, 0, -0.005).scale.set(1, 1, 1);
      if (mani) {
        for (let i = 0; i < 4; i++) add(u, new THREE.CylinderGeometry(0.062 - i * 0.003, 0.064 - i * 0.003, 0.07, 14, 1, true), metalMat, 0, -0.04 - i * 0.065, 0);
        for (let i = 0; i < 4; i++) add(f, new THREE.CylinderGeometry(0.053 - i * 0.004, 0.055 - i * 0.004, 0.07, 14, 1, true), metalMat, 0, -0.04 - i * 0.06, 0);
        add(u, new THREE.SphereGeometry(0.08, 14, 8, 0, Math.PI * 2, 0, Math.PI * 0.5), metalMat, 0, 0.01, 0).scale.set(1, 0.8, 1.1);
      } else if (L.bracers) {
        add(f, new THREE.CylinderGeometry(0.044, 0.05, 0.16, 12, 1, true), M.leatherDark, 0, -0.16, 0);
      }
    };
    armSet(this.uArmR, this.fArmR, this.handR, -1, L.manica === 'R' || L.manica === 'both');
    armSet(this.uArmL, this.fArmL, this.handL, 1, L.manica === 'both');
    // 다리
    const legSet = (th, sh, ft, side, greave) => {
      add(th, limb(0.45, 0.085, 0.056, 0.01, 0.3), this.skinMat);
      add(sh, new THREE.SphereGeometry(0.053, 12, 8), this.skinMat);
      add(sh, limb(0.43, 0.054, 0.036, 0.012, 0.28), this.skinMat);
      add(sh, new THREE.CylinderGeometry(0.043, 0.05, 0.2, 12, 1, true), M.leather, 0, -0.32, 0);
      const foot = add(ft, new THREE.BoxGeometry(0.088, 0.06, 0.24), M.leatherDark, 0, -0.035, 0.06);
      foot.scale.set(1, 1, 1);
      if (greave) add(sh, new THREE.CylinderGeometry(0.066, 0.06, 0.34, 14, 1, true, -1.7, 3.4), metalMat, 0, -0.22, 0.006);
    };
    legSet(this.thighR, this.shinR, this.footR, -1, false);
    legSet(this.thighL, this.shinL, this.footL, 1, !!L.greave);
    // 투구
    this.helmet = this._buildHelmet(L.helmet, metalMat, M);
    if (this.helmet) this.headJ.add(this.helmet);
    // 무기
    const w = buildWeapon(L.weapon, M, { fit: L.metal === 'gold' ? M.gold : M.brass });
    this.weapon = w.group; this.tip = w.tip; this.bladeMats = [w.bladeMat]; this.handR.add(this.weapon);
    this.twoHandOffset = w.group.userData.twoHandOffset || 0.36;
    this.offTip = 0.5;
    if (L.offWeapon) {
      const w2 = buildWeapon(L.offWeapon, M, {});
      this.offWeapon = w2.group; this.offTip = w2.tip; this.bladeMats.push(w2.bladeMat); this.handL.add(this.offWeapon);
    }
    if (L.shield) {
      const face = this.lib.shieldFace ? this.lib.shieldFace(L.shield, L.shieldColors, L.seed) : null;
      this.shield = buildShield(L.shield, M, L.shieldColors, L.seed, face);
      this.handL.add(this.shield);
    }
    // 망토
    if (L.cape) {
      const mat = L.cape.fur ? M.fur : tinted(M.cloth, L.cape.color);
      this.cape = new Cape(this, mat, L.cape.len, L.cape.fur ? 0.46 : 0.42);
      this.cape.wind = L.cape.fur ? 0.4 : 1;
    }
  }

  _buildHelmet(type, metalBase, M) {
    if (!type || type === 'none') return null;
    const metal = metalBase.clone(); metal.side = THREE.DoubleSide;
    const g = new THREE.Group(), L = this.look;
    const add = (geo, mat, x = 0, y = 0, z = 0) => { const m = M3(geo, mat); m.position.set(x, y, z); g.add(m); return m; };
    const crestMat = tinted(M.cloth, L.crest || 0xa01010, { sheen: 0.3 });
    if (type === 'murmillo') {
      add(lathe([[0.001, 0.222], [0.05, 0.218], [0.092, 0.195], [0.121, 0.145], [0.13, 0.075], [0.128, 0.0], [0.133, -0.02]], 24), metal);
      add(lathe([[0.128, 0.02], [0.17, 0.0], [0.205, -0.032], [0.212, -0.048], [0.2, -0.05]], 28), metal);
      add(new THREE.CylinderGeometry(0.132, 0.13, 0.13, 18, 1, true, -0.95, 1.9), M.grille, 0, 0.075, 0);
      const fin = new THREE.Shape();
      fin.moveTo(0.11, 0.17); fin.quadraticCurveTo(0.06, 0.33, -0.03, 0.34); fin.quadraticCurveTo(-0.15, 0.32, -0.18, 0.2); fin.lineTo(-0.1, 0.19); fin.quadraticCurveTo(0.0, 0.25, 0.08, 0.16); fin.closePath();
      const fg = new THREE.ExtrudeGeometry(fin, { depth: 0.024, bevelEnabled: true, bevelThickness: 0.006, bevelSize: 0.006, bevelSegments: 1 });
      fg.translate(0, 0, -0.012); fg.rotateY(-Math.PI / 2);
      add(fg, metal);
      const plume = new THREE.ExtrudeGeometry(fin, { depth: 0.05, bevelEnabled: false }); plume.translate(0, 0.035, -0.025); plume.rotateY(-Math.PI / 2);
      add(plume, crestMat).scale.set(1, 1.04, 0.92);
    } else if (type === 'masked') {
      const hood = tinted(M.cloth, this.look.cloth, { sheen: 0.2 });
      add(new THREE.SphereGeometry(0.127, 18, 12, 0, Math.PI * 2, 0, Math.PI * 0.62), hood, 0, 0.1, -0.01).scale.set(1, 1.08, 1.04);
      add(new THREE.SphereGeometry(0.116, 18, 10, 0, Math.PI * 2, 0, Math.PI * 0.42), metal, 0, 0.11, 0.0);
      add(new THREE.CylinderGeometry(0.118, 0.105, 0.15, 16, 1, true, -1.1, 2.2), metal, 0, 0.08, 0.004);
      for (const sx of [-1, 1]) add(new THREE.BoxGeometry(0.04, 0.012, 0.02), M.void, sx * 0.04, 0.115, 0.112);
      add(new THREE.CylinderGeometry(0.075, 0.1, 0.1, 14, 1, true), hood, 0, -0.03, 0);
    } else if (type === 'horned') {
      add(new THREE.SphereGeometry(0.12, 18, 12, 0, Math.PI * 2, 0, Math.PI * 0.5), metal, 0, 0.1, 0);
      add(new THREE.TorusGeometry(0.12, 0.013, 6, 24), metal, 0, 0.1, 0).rotation.x = Math.PI / 2;
      add(new THREE.BoxGeometry(0.022, 0.1, 0.018), metal, 0, 0.08, 0.122);
      const bone = new THREE.MeshStandardMaterial({ color: 0xe8dcc0, roughness: 0.45, metalness: 0 });
      for (const sx of [-1, 1]) add(taperTube([V3(sx * 0.105, 0.15, 0), V3(sx * 0.2, 0.2, 0.02), V3(sx * 0.255, 0.32, 0.06), V3(sx * 0.23, 0.43, 0.11)], 0.032, 0.004, 14, 8), bone);
      add(new THREE.TorusGeometry(0.115, 0.03, 8, 24), M.fur, 0, 0.06, 0).rotation.x = Math.PI / 2;
    } else if (type === 'galea') {
      add(lathe([[0.001, 0.225], [0.06, 0.22], [0.1, 0.19], [0.123, 0.14], [0.127, 0.08], [0.124, 0.03]], 24), metal);
      add(new THREE.TorusGeometry(0.124, 0.012, 6, 26), metal, 0, 0.1, 0.0).rotation.x = Math.PI / 2;
      for (const sx of [-1, 1]) { const ch = add(new THREE.CylinderGeometry(0.127, 0.12, 0.12, 10, 1, true, sx > 0 ? 0.55 : -1.7, 1.15), metal, 0, 0.035, 0); ch.rotation.x = 0.05; }
      add(lathe([[0.122, 0.03], [0.15, 0.01], [0.16, -0.01]], 24), metal);
      const arc = new THREE.Shape();
      arc.moveTo(0.1, 0.2); arc.quadraticCurveTo(0.08, 0.42, -0.08, 0.43); arc.quadraticCurveTo(-0.24, 0.4, -0.26, 0.1); arc.lineTo(-0.16, 0.14); arc.quadraticCurveTo(-0.1, 0.27, 0.06, 0.19); arc.closePath();
      const cg = new THREE.ExtrudeGeometry(arc, { depth: 0.055, bevelEnabled: true, bevelThickness: 0.012, bevelSize: 0.01, bevelSegments: 2 });
      cg.translate(0, 0, -0.0275); cg.rotateY(-Math.PI / 2);
      add(cg, crestMat);
    }
    return g;
  }

  // ── 상태 API ────────────────────────────────────────────
  setStance(s) { this.stance = s; }
  get busy() { return !!this.action; }
  swing(spec) {
    if (this.tipLimitZ != null) {
      // 칼끝이 카메라에 너무 붙지 않도록 돌진 거리 제한 (적은 +Z를 바라봄)
      const tipLen = spec.hand === 'L' ? this.offTip : this.tip;
      const allowed = (this.tipLimitZ - this.root.position.z) / this.scaleK - (0.14 + spec.reach + tipLen);
      spec.lunge = Math.max(0.05, Math.min(spec.lunge, allowed));
    }
    const a = new SwingAction(this, spec);
    this.action = a; this.swingAct = a;
    return a;
  }
  // 패링·막힘에 의한 튕김
  rebound(kind = 'parried') {
    const sw = this.swingAct;
    const back = kind === 'parried' ? 0.9 : 0.5, dur = kind === 'parried' ? 0.32 : 0.22;
    const spec = sw ? sw.spec : null;
    const th = sw ? sw.thetaAt(sw.t) : 0;
    this.action = new PoseAction(this, dur, (tmp, u) => {
      if (spec) {
        const hand = spec.hand === 'L' ? tmp.L : tmp.R;
        swingFrame(spec, th - back * o3(u) * Math.sign(spec.arc), hand.p, hand.b, hand.e, this);
        if (spec.hand === '2H') { tmp.L.p.copy(hand.p).addScaledVector(hand.b, this.twoHandOffset); tmp.L.b.copy(hand.b); tmp.L.e.copy(hand.e); }
        tmp.body.z = -0.12 * o3(u); tmp.chest.x = -0.2 * Math.sin(u * Math.PI);
      }
      return o3(Math.min(1, u * 2.2));
    });
    this.swingAct = null;
    this.springs.pitch.kick(-3); this.springs.bz.kick(-0.9);
  }
  // 잡기: 왼손을 뻗어 돌진 (가드 불가, 회피로만 대응)
  grab(spec) {
    const W = spec.windup, S = spec.strike, R = spec.recover;
    this.swingAct = null;
    const act = new PoseAction(this, W + S + R, (tmp, u, t) => {
      let k;
      if (t < W) {
        k = io3(t / W);
        tmp.body.z = -0.14 * k; tmp.body.y -= 0.07 * k; tmp.chest.x = -0.12 * k; tmp.hips.y = -0.4 * k;
        tmp.L.p.set(0.32, 1.2, -0.02); tmp.L.b.set(0, 1, 0.2); tmp.L.e.set(0, 0, 1);
      } else if (t < W + S) {
        k = o3((t - W) / S);
        tmp.body.z = -0.14 + 1.0 * k; tmp.chest.x = 0.3 * k; tmp.hips.y = -0.4 + 0.5 * k; tmp.fL.z = 0.2 + 0.85 * k; tmp.fR.z = -0.17 + 0.5 * k;
        tmp.L.p.set(0.08, 1.45, 0.3 + 1.05 * k); tmp.L.b.set(0, 0.2, 1); tmp.L.e.set(0, 1, 0);
      } else {
        k = io3((t - W - S) / R);
        tmp.body.z = 0.86 * (1 - k); tmp.chest.x = 0.3 * (1 - k); tmp.fL.z = 0.2 + 0.85 * (1 - k); tmp.fR.z = -0.17 + 0.5 * (1 - k);
        if (k < 0.6) { tmp.L.p.set(0.08, 1.45, 1.35 - k); tmp.L.b.set(0, 0.2, 1); tmp.L.e.set(0, 1, 0); }
      }
      if (this.style === 'axe2h' || this.style === 'sword2h') { tmp.R.p.set(-0.25, 1.05, 0.15 + (tmp.body.z || 0) * 0.6); tmp.R.b.set(0.2, 0.9, 0.3); tmp.R.e.set(0, 0, 1); }
      tmp.head.y = -(tmp.hips.y + tmp.spine.y + tmp.chest.y + tmp.neck.y);
      return Math.min(1, t / 0.12);
    });
    act.impactT = W + S * 0.8; act.endT = W + S + R;
    this.action = act;
    return act;
  }
  cancelSwing() { if (this.swingAct) { this.swingAct = null; this.action = null; } }
  dodge(side) {
    this.swingAct = null;
    const sx = side;   // +1: 적 기준 왼쪽(화면 오른쪽)
    this.action = new PoseAction(this, 0.62, (tmp, u) => {
      const k = u < 0.32 ? o3(u / 0.32) : 1 - io3((u - 0.55) / 0.45) * (u > 0.55 ? 1 : 0);
      tmp.body.x += sx * 0.68 * k; tmp.body.y -= 0.08 * Math.sin(Math.min(1, u / 0.32) * Math.PI);
      tmp.chest.z = -sx * 0.28 * k; tmp.spine.z = -sx * 0.1 * k;
      tmp.fL.x += sx * 0.6 * k; tmp.fR.x += sx * 0.62 * k;
      tmp.fL.y = Math.max(0, Math.sin(clamp(u / 0.3, 0, 1) * Math.PI)) * 0.08;
      return 1;
    });
  }
  flinch(power = 1) {
    if (this.dead) return;
    this.swingAct = null;
    this.action = new PoseAction(this, 0.34 + 0.1 * power, (tmp, u) => {
      const k = Math.sin(u * Math.PI);
      tmp.body.z -= 0.08 * k * power; tmp.chest.x += 0.18 * k; tmp.head.x += 0.2 * k; tmp.body.y -= 0.04 * k;
      return 1;
    });
  }
  hit(dx, dy, power = 1) {
    const S = this.springs;
    S.roll.kick(-dx * 3.2 * power); S.yaw.kick(dx * 2.4 * power); S.pitch.kick((-dy * 1.6 - 1.2) * power);
    S.head.kick((dy * 2 - 2.5) * power); S.bx.kick(dx * 0.5 * power); S.bz.kick(-0.75 * power);
  }
  step(dx, dz, dur = 0.35) {
    const sx = dx, sz = dz;
    const start = this.root.position.clone();
    this._stepAnim = { t: 0, dur, from: start, to: start.clone().add(V3(sx, 0, sz)) };
  }
  throwShield(dirX = 1) {
    if (!this.shield) return;
    const sh = this.shield; this.shield = null; this.hasShield = false;
    if (this.fx) this.fx.detach(sh, V3(dirX * 3.2, 2.6, 1.5), V3(4, 9, 3), sh.userData.radius * 0.6);
    else sh.removeFromParent();
  }
  breakShield(dirX = 1) {
    if (!this.shield) return;
    const sh = this.shield; this.shield = null; this.hasShield = false;
    if (this.fx) { this.fx.splinters(sh.getWorldPosition(V3()), 18); this.fx.detach(sh, V3(dirX * 2.4, 2.2, 2.2), V3(6, 4, 8), sh.userData.radius * 0.6); }
    else sh.removeFromParent();
  }
  breakHelmet(dx = 0.5, dy = 0.5) {
    if (!this.helmet) return;
    const h = this.helmet; this.helmet = null;
    if (this.fx) this.fx.detach(h, V3(dx * 2.6, 3.2 + dy, 1.8), V3(8 * dy, 10 * dx, 5), 0.13);
    else h.removeFromParent();
  }
  dropWeapons() {
    for (const w of [this.weapon, this.offWeapon]) if (w && w.parent && this.fx) this.fx.detach(w, V3((Math.random() - 0.5) * 1.5, 1.2, 0.8), V3(6, 3, 9), 0.05);
  }
  setGlow(color, k) { if (color) this.glowColor.set(color); this.glowTarget = k; }
  setArmorGlow(k) { this.armorGlow = k; }
  ko(dx = 0) {
    if (this.dead) return;
    this.dead = true; this.swingAct = null;
    const side = dx >= 0 ? 1 : -1;
    this.setGlow(null, 0);
    setTimeout(() => this.dropWeapons(), 60);
    const start = new Pose().copy(this.pose);
    this.action = {
      t: 0, g: this, tmp: new Pose(),
      update(dt) {
        this.t += dt; const t = this.t, o = this.tmp, g = this.g;
        o.copy(start);
        const a = clamp(t / 0.35, 0, 1), b = clamp((t - 0.3) / 0.6, 0, 1), c = clamp((t - 0.85) / 0.75, 0, 1);
        o.body.z = start.body.z - 0.18 * o3(a); o.chest.x = lerp(start.chest.x, -0.35, o3(a)); o.head.x = -0.45 * o3(a);
        o.body.y = lerp(o.body.y, -0.42, io3(b)); o.chest.x = lerp(o.chest.x, 0.55, io3(b)); o.head.x = lerp(o.head.x, 0.4, io3(b));
        o.fk = t > 0.28 ? 1 : 0;
        if (t <= 0.28) { o.R.p.lerp(_s.set(-0.42, 0.9, 0.05), a); o.L.p.lerp(_s.set(0.42, 0.9, 0.05), a); }
        o.aR.set(0.2, 0, -0.35 - 0.9 * b); o.eR.set(-0.3, 0, 0); o.aL.set(0.2, 0, 0.35 + 0.9 * b); o.eL.set(-0.3, 0, 0);
        o.tR.set(-1.0 * b, 0, -0.08); o.kR.set(1.6 * b, 0, 0); o.tL.set(-0.9 * b, 0, 0.08); o.kL.set(1.5 * b, 0, 0);
        const fallK = c * c;
        o.fall.set(-0.25 * fallK, 0, side * 1.42 * fallK);
        if (c >= 1 && !this.thudded) { this.thudded = true; if (g.onThud) g.onThud(); }
        if (c >= 1) { const bnc = Math.exp(-(t - 1.6) * 6) * Math.sin((t - 1.6) * 22) * 0.05; o.fall.z += side * bnc; }
        o.aR.z -= 0.6 * c; o.aL.z += 0.6 * c; o.eR.x = -0.2; o.eL.x = -0.2;
        g.pose.copy(o);
        return false;
      },
    };
  }

  // ── 위치 질의 ───────────────────────────────────────────
  headPos(out) { return out.set(0, 0.1, 0.02).applyMatrix4(this.headJ.matrixWorld); }
  chestPos(out) { return out.set(0, 0.05, 0.1).applyMatrix4(this.chestJ.matrixWorld); }
  shieldPos(out) { return this.shield ? this.shield.getWorldPosition(out) : this.chestPos(out); }
  weaponTip(out, off = false) {
    const w = off ? this.offWeapon : this.weapon;
    if (!w || !w.parent) return this.chestPos(out);
    return w.localToWorld(out.set(0, off ? this.offTip : this.tip, 0));
  }
  hitPoint(dx, dy, out) {
    this.chestPos(out);
    _a.set(-dx * 0.08, dy < -0.3 ? 0.08 : dy > 0.3 ? -0.18 : -0.02, 0.06).applyQuaternion(this.root.quaternion);
    return out.add(_a);
  }

  // ── 프레임 갱신 ─────────────────────────────────────────
  update(dt) {
    this.time += dt;
    if (this._stepAnim) {
      const s = this._stepAnim; s.t += dt;
      const k = io3(s.t / s.dur);
      this.root.position.lerpVectors(s.from, s.to, k);
      if (s.t >= s.dur) this._stepAnim = null;
    }
    if (this.action) {
      const done = this.action.update(dt);
      if (done) { this.action = null; this.swingAct = null; }
    } else {
      stancePose(this.target, this.style, this.stance, this.time, this);
      this.pose.lerp(this.target, 1 - Math.exp(-dt * (this.stance === 'stagger' ? 7 : 10)));
    }
    for (const k in this.springs) this.springs[k].step(Math.min(dt, 1 / 30));
    this.glow += (this.glowTarget - this.glow) * Math.min(1, dt * 14);
    for (const m of this.bladeMats) { m.emissive.copy(this.glowColor).multiplyScalar(this.glow); }
    if (this.armorGlow > 0 || this._ag) {
      this._ag = this.armorGlow > 0;
      const k = this.armorGlow * (0.6 + 0.4 * Math.sin(this.time * 12));
      for (const m of this.allMats) { m.emissive = m.emissive || new THREE.Color(); m.emissive.setRGB(0.9 * k, 0.28 * k, 0.05 * k); }
    }
    this._apply();
    if (this.cape) this.cape.step(dt, this.time);
  }

  _apply() {
    const P = this.pose, S = this.springs;
    this.fallPivot.rotation.set(P.fall.x, P.fall.y, P.fall.z);
    this.bodyJ.position.set(P.body.x + S.bx.x * 0.12, P.body.y, P.body.z + S.bz.x * 0.12);
    this.hipsJ.rotation.set(P.hips.x, P.hips.y, P.hips.z);
    this.spineJ.rotation.set(P.spine.x + S.pitch.x * 0.08, P.spine.y + S.yaw.x * 0.06, P.spine.z + S.roll.x * 0.06);
    this.chestJ.rotation.set(P.chest.x + S.pitch.x * 0.12, P.chest.y + S.yaw.x * 0.1, P.chest.z + S.roll.x * 0.1);
    this.neckJ.rotation.set(P.neck.x, P.neck.y, P.neck.z);
    this.headJ.rotation.set(P.head.x + S.head.x * 0.12, P.head.y, P.head.z + S.roll.x * 0.05);
    this.root.updateMatrixWorld(true);
    if (P.fk < 0.5) {
      const rq = this.root.getWorldQuaternion(_qr), s = this.scaleK;
      this._legIK(this.thighR, this.shinR, this.footR, P.fR, -1, rq, s);
      this._legIK(this.thighL, this.shinL, this.footL, P.fL, 1, rq, s);
      this._armIK(this.uArmR, this.fArmR, this.handR, P.R, -1, rq, s);
      this._armIK(this.uArmL, this.fArmL, this.handL, P.L, 1, rq, s);
    } else {
      this.uArmR.rotation.set(P.aR.x, P.aR.y, P.aR.z); this.fArmR.rotation.set(P.eR.x, P.eR.y, P.eR.z);
      this.uArmL.rotation.set(P.aL.x, P.aL.y, P.aL.z); this.fArmL.rotation.set(P.eL.x, P.eL.y, P.eL.z);
      this.thighR.rotation.set(P.tR.x, P.tR.y, P.tR.z); this.shinR.rotation.set(P.kR.x, P.kR.y, P.kR.z);
      this.thighL.rotation.set(P.tL.x, P.tL.y, P.tL.z); this.shinL.rotation.set(P.kL.x, P.kL.y, P.kL.z);
      this.handR.rotation.set(0.6, 0, 0); this.handL.rotation.set(0.6, 0, 0);
      this.footR.rotation.set(0, 0, 0); this.footL.rotation.set(0, 0, 0);
    }
    this.root.updateMatrixWorld(true);
  }

  // 2본 IK: rootJ(어깨/고관절) → midJ(팔꿈치/무릎) → endJ(손목/발목)
  _solve(rootJ, midJ, endJ, lenA, lenB, target, pole, endQuat) {
    const parent = rootJ.parent;
    parent.matrixWorld.decompose(_s, _q, _sc);
    const S = _t.setFromMatrixPosition(rootJ.matrixWorld);
    const D = _u.subVectors(target, S);
    let dist = D.length();
    dist = clamp(dist, Math.abs(lenA - lenB) + 1e-3, (lenA + lenB) * 0.999);
    const u = D.normalize();
    const v = _w.subVectors(pole, S); v.addScaledVector(u, -v.dot(u));
    if (v.lengthSq() < 1e-8) v.set(0, 0, 1);
    v.normalize();
    const cosA = clamp((lenA * lenA + dist * dist - lenB * lenB) / (2 * lenA * dist), -1, 1), sinA = Math.sqrt(1 - cosA * cosA);
    const E = _a.copy(S).addScaledVector(u, lenA * cosA).addScaledVector(v, lenA * sinA);
    const T = _b.copy(S).addScaledVector(u, dist);
    const a1 = _c.subVectors(E, S).normalize(), a2 = _d.subVectors(T, E).normalize();
    const hng = _e.crossVectors(a1, a2);
    if (hng.lengthSq() < 1e-8) hng.crossVectors(a1, v);
    hng.normalize();
    _y.copy(a1).negate(); _z.crossVectors(hng, _y).normalize();
    _m.makeBasis(hng, _y, _z); _q2.setFromRotationMatrix(_m);                 // 위팔 월드 회전
    rootJ.quaternion.copy(_q).invert().multiply(_q2);
    _y.copy(a2).negate(); _z.crossVectors(hng, _y).normalize();
    _m.makeBasis(hng, _y, _z); _q3.setFromRotationMatrix(_m);                 // 아래팔 월드 회전
    midJ.quaternion.copy(_q2).invert().multiply(_q3);
    if (endQuat) endJ.quaternion.copy(_q3).invert().multiply(endQuat);
  }
  _armIK(u, f, h, hand, side, rq, s) {
    const tgt = _f.copy(hand.p).applyMatrix4(this.root.matrixWorld);
    const sh = _g.setFromMatrixPosition(u.matrixWorld);
    const pole = _h.set(side * 0.45, -0.55, -0.4).applyQuaternion(rq).multiplyScalar(s).add(sh);
    // 손 방향: Y=칼날(혹은 방패 위), Z=날(방패 정면)
    const b = _s.copy(hand.b).applyQuaternion(rq).normalize();
    const e = _w.copy(hand.e).applyQuaternion(rq);
    e.addScaledVector(b, -e.dot(b));
    if (e.lengthSq() < 1e-6) e.set(0, 0, 1).addScaledVector(b, -b.z);
    e.normalize();
    const x = _sc.crossVectors(b, e).normalize();
    _m.makeBasis(x, b, e);
    _hq.setFromRotationMatrix(_m);
    this._solve(u, f, h, this.lenU * s, this.lenF * s, tgt, pole, _hq);
  }
  _legIK(th, sh, ft, foot, side, rq, s) {
    const tgt = _f.set(foot.x, foot.y + 0.075, foot.z).applyMatrix4(this.root.matrixWorld);
    const hip = _g.setFromMatrixPosition(th.matrixWorld);
    const pole = _h.set(side * 0.08, -0.3, 1.0).applyQuaternion(rq).multiplyScalar(s).add(hip);
    _fq.setFromAxisAngle(UP, side * 0.22).premultiply(rq);
    this._solve(th, sh, ft, this.lenT * s, this.lenS * s, tgt, pole, _fq);
  }

  addTo(scene) { scene.add(this.root); if (this.cape) { scene.add(this.cape.mesh); this.cape.ready = false; } }
  removeFrom() {
    this.root.removeFromParent();
    if (this.cape) this.cape.mesh.removeFromParent();
  }
  setVisible(v) { this.root.visible = v; if (this.cape) this.cape.mesh.visible = v; }
  dispose() {
    this.removeFrom();
    const libMats = new Set(Object.values(this.lib.M));
    const objs = [this.root]; if (this.cape) objs.push(this.cape.mesh);
    for (const r of objs) r.traverse((o) => { if (o.isMesh) { o.geometry.dispose(); for (const m of [].concat(o.material)) if (!libMats.has(m)) m.dispose(); } });
  }
}
