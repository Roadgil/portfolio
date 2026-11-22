// ─────────────────────────────────────────────────────────────
//  1인칭 뷰모델: 오른손 무기(스와이프 각도 베기) + 왼손 방패(또는 쌍검)
// ─────────────────────────────────────────────────────────────
import * as THREE from 'three';
import { buildWeapon, buildShield } from './gladiator.js';
import { tinted } from './textures.js';

const V3 = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const _m = new THREE.Matrix4(), _x = V3(), _e = V3(), _b = V3(), _p = V3(), _t = V3(), _up = V3(0, 1, 0);
const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);

function limbUp(len, r0, r1) {
  const pts = [];
  for (let i = 0; i <= 8; i++) { const t = i / 8; pts.push(new THREE.Vector2(r0 + (r1 - r0) * t + 0.004 * Math.sin(t * Math.PI), t * len)); }
  pts.unshift(new THREE.Vector2(0.001, -0.005)); pts.push(new THREE.Vector2(0.001, len + 0.005));
  return new THREE.LatheGeometry(pts, 14);
}
class HandState {
  constructor() { this.p = V3(); this.b = V3(0, 1, 0); this.e = V3(0, 0, -1); }
  set(p, b, e) { this.p.copy(p); this.b.copy(b).normalize(); this.e.copy(e); return this; }
  damp(o, k) { this.p.lerp(o.p, k); this.b.lerp(o.b, k).normalize(); this.e.lerp(o.e, k); return this; }
}

export class Viewmodel {
  constructor(camera, lib, fx) {
    this.camera = camera; this.lib = lib; this.fx = fx;
    this.root = new THREE.Group(); camera.add(this.root);
    this.t = 0; this.blocking = false; this.rage = 0;
    this.swingR = null; this.swingL = null;
    this.jolt = { p: V3(), v: V3(), r: V3(), rv: V3() };
    this.curR = new HandState(); this.curL = new HandState(); this.tgt = new HandState();
    this.drink = 0; this.dodgeT = 0; this.dodgeSide = 0;
    this.visibleWanted = true;
  }

  equip(save) {
    const libMats = new Set(Object.values(this.lib.M));
    while (this.root.children.length) {
      const c = this.root.children[0];
      c.traverse((o) => { if (o.isMesh) { o.geometry.dispose(); for (const m of [].concat(o.material)) if (!libMats.has(m)) m.dispose(); } });
      this.root.remove(c);
    }
    const M = this.lib.M, wid = save.weapon;
    this.dual = wid === 'dual';
    this.weaponId = wid;
    const metal = save.armorLvl >= 8 ? M.gold : save.armorLvl >= 4 ? M.brass : M.iron;
    this.skin = tinted(M.skin, 0xcf9a74);
    const mk = (side) => {
      const hand = new THREE.Group(); this.root.add(hand);
      const fist = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.088, 0.075), this.skin); fist.position.z = -0.004; hand.add(fist);
      const fore = new THREE.Group(); this.root.add(fore);
      fore.add(new THREE.Mesh(limbUp(0.3, 0.034, 0.05), this.skin));
      const brace = new THREE.Mesh(new THREE.CylinderGeometry(0.043, 0.039, 0.13, 14, 1, true), M.leatherDark); brace.position.y = 0.08; fore.add(brace);
      if (save.armorLvl >= 3 && side > 0) {
        for (let i = 0; i < 4; i++) { const b = new THREE.Mesh(new THREE.CylinderGeometry(0.05 + i * 0.003, 0.048 + i * 0.003, 0.065, 14, 1, true), metal); b.position.y = 0.06 + i * 0.058; fore.add(b); }
      }
      return { hand, fore };
    };
    this.R = mk(1); this.L = mk(-1);
    const type = { gladius: 'gladius', broadsword: 'spatha', dual: 'gladius', axe: 'axe1h' }[wid];
    const lvl = save.wlvl[wid] || 1;
    const w = buildWeapon(type, M, { fit: lvl >= 7 ? M.gold : M.brass });
    this.R.hand.add(w.group); this.wR = w;
    this.bladeMats = [w.bladeMat];
    if (lvl >= 5) w.bladeMat.emissiveIntensity = 1;
    this.runeLvl = lvl;
    if (this.dual) {
      const w2 = buildWeapon('gladius', M, {}); this.L.hand.add(w2.group); this.wL = w2; this.bladeMats.push(w2.bladeMat);
      this.shield = null;
    } else {
      this.wL = null;
      const face = this.lib.shieldFace ? this.lib.shieldFace('scutum', ['#8e1b16', '#d2a645'], 7) : null;
      this.shield = buildShield('scutum', M, ['#8e1b16', '#d2a645'], 7, face);
      this.shield.scale.setScalar(0.5);
      this.L.hand.add(this.shield);
    }
    // 포션
    const vial = this.vial = new THREE.Group();
    const glass = new THREE.MeshPhysicalMaterial({ color: 0xcfe8ff, roughness: 0.05, metalness: 0, transparent: true, opacity: 0.35, clearcoat: 1 });
    const pts = [[0.001, 0], [0.035, 0.002], [0.045, 0.03], [0.044, 0.07], [0.02, 0.1], [0.014, 0.13], [0.016, 0.14]].map(([r, y]) => new THREE.Vector2(r, y));
    vial.add(new THREE.Mesh(new THREE.LatheGeometry(pts, 16), glass));
    const liquid = new THREE.Mesh(new THREE.LatheGeometry(pts.slice(0, 4).map((v) => new THREE.Vector2(v.x * 0.88, v.y * 0.9)), 16), new THREE.MeshStandardMaterial({ color: 0x8a0010, emissive: 0xff1a2a, emissiveIntensity: 1.6, roughness: 0.2 }));
    vial.add(liquid);
    const cork = new THREE.Mesh(new THREE.CylinderGeometry(0.014, 0.012, 0.025, 8), M.wood); cork.position.y = 0.15; vial.add(cork);
    vial.visible = false; this.root.add(vial);
    this.root.traverse((o) => { if (o.isMesh) { o.castShadow = false; o.receiveShadow = false; } });
    this.curR.set(this._idleR(0), this._idleRb, this._idleRe);
    this.curL.set(this._idleL(0), this._idleLb, this._idleLe);
  }

  // ── 기본 포즈 ───────────────────────────────────────────
  _idleR(t) {
    const br = Math.sin(t * 1.7) * 0.006;
    this._idleRb = this.dual ? V3(-0.35, 0.5, -0.8) : this.weaponId === 'axe' ? V3(-0.25, 0.8, -0.45) : V3(-0.3, 0.45, -0.85);
    this._idleRe = V3(-0.6, -0.3, 0.2);
    return V3(0.105, -0.2 + br, -0.42);
  }
  _idleL(t) {
    const br = Math.sin(t * 1.7 + 0.6) * 0.006;
    if (this.dual) { this._idleLb = V3(0.35, 0.5, -0.8); this._idleLe = V3(0.6, -0.3, 0.2); return V3(-0.105, -0.205 + br, -0.42); }
    this._idleLb = V3(0.3, 1, 0.1); this._idleLe = V3(0.35, 0.05, -1);
    return V3(-0.2, -0.33 + br, -0.5);
  }

  // ── 동작 ────────────────────────────────────────────────
  swing(ux, uy, dur, opts = {}) {
    const hand = this.dual ? (opts.hand || (ux > 0.25 ? 'L' : ux < -0.25 ? 'R' : (this._alt = !this._alt) ? 'L' : 'R')) : 'R';
    const sw = { ux, uy, dur, t: 0, heavy: !!opts.heavy, arc: (opts.heavy ? 92 : 80) * Math.PI / 180, hand, id: hand + Math.random(), stop: -1 };
    if (hand === 'L') this.swingL = sw; else this.swingR = sw;
    if (this.fx) this.fx.trailBegin(sw.id, opts.color || (this.rage >= 1 ? 0xffc040 : 0xbfe4ff));
    return sw;
  }
  get impactFrac() { return 0.35; }
  clash() { const s = this.swingR || this.swingL; if (s) { s.t = Math.max(s.t, s.dur * 0.42); s.stop = s.t; } this.kick(0, 0, 0.03, 0.12, 0, 0); }
  deflect() { const s = this.swingR || this.swingL; if (s) { s.t = Math.max(s.t, s.dur * 0.3); s.stop = s.t; } this.kick(0.03, 0.02, 0.05, 0.3, -0.2, 0.25); }
  hurt(p = 1) { this.kick(0, -0.03 * p, 0.05 * p, -0.15 * p, 0, (Math.random() - 0.5) * 0.3 * p); }
  blockHit(p = 1) { this.kick(0, -0.02 * p, 0.04 * p, -0.08 * p, 0, 0); }
  kick(x, y, z, rx, ry, rz) { this.jolt.v.x += x * 30; this.jolt.v.y += y * 30; this.jolt.v.z += z * 30; this.jolt.rv.x += rx * 30; this.jolt.rv.y += ry * 30; this.jolt.rv.z += rz * 30; }
  setBlock(on) { this.blocking = on; }
  startDrink() { this.drink = 0.0001; this.vial.visible = true; }
  dodge(side) { this.dodgeT = 0.0001; this.dodgeSide = side; }
  setRage(k) { this.rage = k; }
  setVisible(v) { this.root.visible = v; }

  _swingPose(sw, out) {
    const { ux, uy } = sw;
    let s = clamp(sw.t / sw.dur, 0, 1);
    if (sw.stop >= 0 && sw.t > sw.stop) s = clamp(sw.stop / sw.dur - (sw.t - sw.stop) / sw.dur * 0.6, 0, 1);
    const k = 1 - Math.pow(1 - s, 1.6);
    const th = -sw.arc + 2 * sw.arc * k;
    const sn = Math.sin(th), cs = Math.cos(th);
    const side = sw.hand === 'L' ? -1 : 1;
    const travel = sw.heavy ? 0.26 : 0.2;
    out.p.set(side * 0.03 + ux * travel * Math.sin(th * 0.85), -0.12 + uy * travel * Math.sin(th * 0.85) + (sw.heavy ? 0.02 : 0), -0.47 - 0.06 * cs);
    out.b.set(ux * sn, uy * sn, -cs).normalize();
    out.e.set(ux * cs, uy * cs, sn);
    return out;
  }

  _applyHand(H, st, tipLen) {
    _b.copy(st.b).normalize();
    _e.copy(st.e).addScaledVector(_b, -st.e.dot(_b));
    if (_e.lengthSq() < 1e-6) _e.set(0, 0, -1).addScaledVector(_b, _b.z);
    _e.normalize();
    _x.crossVectors(_b, _e).normalize();
    _m.makeBasis(_x, _b, _e);
    H.hand.position.copy(st.p);
    H.hand.quaternion.setFromRotationMatrix(_m);
    // 아래팔: 손목 → 화면 아래 바깥쪽 팔꿈치 방향
    const sideX = H === this.R ? 1 : -1;
    _t.set(0.32 * sideX, -0.62, 0.7).normalize();
    _t.addScaledVector(_b, -0.25).normalize();
    H.fore.position.copy(st.p);
    H.fore.quaternion.setFromUnitVectors(_up, _t);
  }

  update(dt, dtReal) {
    this.t += dtReal;
    const t = this.t;
    // 오른손
    const tgt = this.tgt;
    for (const side of ['R', 'L']) {
      const isR = side === 'R', cur = isR ? this.curR : this.curL;
      const sw = isR ? this.swingR : this.swingL;
      const W = isR ? this.wR : this.wL;
      if (sw) {
        sw.t += dt;
        this._swingPose(sw, cur);
        if (this.fx && W && W.blade) {
          const hand = (isR ? this.R : this.L).hand;
          hand.updateMatrixWorld(true);
          this.fx.trailPush(sw.id, hand.localToWorld(_p.set(0, 0.14, 0)), hand.localToWorld(_t.set(0, W.tip, 0)));
          if (this.fx.ghost && sw.t < sw.dur * 0.7 && sw.stop < 0) this.fx.ghost(W.blade, sw.id);
        }
        if (sw.t >= sw.dur * 1.05) {
          if (this.fx) this.fx.trailEnd(sw.id);
          if (isR) this.swingR = null; else this.swingL = null;
        }
        continue;
      }
      if (isR) {
        tgt.p.copy(this._idleR(t)); tgt.b.copy(this._idleRb).normalize(); tgt.e.copy(this._idleRe);
        if (this.blocking && this.dual) { tgt.p.set(0.05, -0.15, -0.42); tgt.b.set(-0.75, 0.62, -0.25).normalize(); tgt.e.set(0, 0.3, -1); }
        if (this.drink > 0) tgt.p.y -= 0.12 * Math.sin(Math.min(1, this.drink / 0.25) * Math.PI * 0.5);
      } else {
        tgt.p.copy(this._idleL(t)); tgt.b.copy(this._idleLb).normalize(); tgt.e.copy(this._idleLe);
        if (this.blocking) {
          if (this.dual) { tgt.p.set(-0.05, -0.15, -0.42); tgt.b.set(0.75, 0.62, -0.25).normalize(); tgt.e.set(0, 0.3, -1); }
          else { tgt.p.set(-0.015, -0.29, -0.56); tgt.b.set(0.02, 1, 0.06).normalize(); tgt.e.set(0, 0.03, -1); }
        }
        if (this.drink > 0) tgt.p.y -= 0.2 * Math.sin(Math.min(1, this.drink / 0.25) * Math.PI * 0.5);
      }
      cur.damp(tgt, 1 - Math.exp(-dtReal * (this.blocking ? 26 : 13)));
    }
    if (this.R) this._applyHand(this.R, this.curR, this.wR ? this.wR.tip : 0.6);
    if (this.L) this._applyHand(this.L, this.curL, this.wL ? this.wL.tip : 0.5);
    // 포션 마시기
    if (this.drink > 0) {
      this.drink += dtReal;
      const d = this.drink, up = clamp(d / 0.3, 0, 1), down = clamp((d - 0.75) / 0.3, 0, 1);
      this.vial.position.set(0.02, -0.42 + 0.3 * up - 0.3 * down, -0.32);
      this.vial.rotation.set(-0.3 - 1.6 * clamp((d - 0.3) / 0.35, 0, 1) * (1 - down), 0, 0.2);
      if (d > 1.1) { this.drink = 0; this.vial.visible = false; }
    }
    // 회피 기울임
    let roll = 0;
    if (this.dodgeT > 0) {
      this.dodgeT += dtReal;
      const k = Math.sin(clamp(this.dodgeT / 0.45, 0, 1) * Math.PI);
      roll = -this.dodgeSide * 0.12 * k;
      if (this.dodgeT > 0.45) this.dodgeT = 0;
    }
    // 반동 스프링
    const J = this.jolt, kS = 160, cS = 14, h = Math.min(dtReal, 1 / 30);
    J.v.addScaledVector(J.p, -kS * h).multiplyScalar(Math.max(0, 1 - cS * h)); J.p.addScaledVector(J.v, h);
    J.rv.addScaledVector(J.r, -kS * h).multiplyScalar(Math.max(0, 1 - cS * h)); J.r.addScaledVector(J.rv, h);
    this.root.position.copy(J.p);
    this.root.rotation.set(J.r.x, J.r.y, J.r.z + roll);
    // 분노 게이지 가득: 칼날 금빛 발광
    const glow = this.rage >= 1 ? 1.4 + 0.6 * Math.sin(t * 8) : this.runeLvl >= 5 ? 0.25 + 0.1 * Math.sin(t * 2) : 0;
    for (const m of this.bladeMats) m.emissive.setRGB(1.0 * glow, 0.62 * glow, 0.18 * glow);
  }
}
