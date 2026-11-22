// ─────────────────────────────────────────────────────────────
//  카메라 리그: 1인칭(흔들림·반동·회피 스텝) + 시네마틱 샷/오빗
// ─────────────────────────────────────────────────────────────
import * as THREE from 'three';
import { EYE_H, ENEMY_Z } from './config.js';

const V3 = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const io = (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2);

export class CameraRig {
  constructor(camera, engine) {
    this.cam = camera; this.engine = engine;
    this.mode = 'fp';
    this.base = V3(0, EYE_H, 0);
    this.enemyZ = ENEMY_Z;
    this.focus = V3(0, 1.3, ENEMY_Z);
    this.focusTarget = V3(0, 1.3, ENEMY_Z);
    this.trauma = 0; this.t = 0;
    this.off = V3(); this.offV = V3();
    this.dodgeX = 0; this.dodgeT = -1; this.dodgeSide = 0;
    this.fovKick = 0; this.roll = 0; this.rollV = 0;
    this.shots = null; this.orbitS = null;
    this._p = V3(); this._l = V3();
  }
  shake(a) { this.trauma = Math.min(1, this.trauma + a); }
  push(x, y, z) { this.offV.x += x; this.offV.y += y; this.offV.z += z; }
  kickRoll(r) { this.rollV += r; }
  punchFov(d) { this.fovKick += d; }
  dodge(side) { this.dodgeT = 0; this.dodgeSide = side; }

  playShots(shots, onDone) { this.mode = 'cine'; this.shots = { list: shots, i: 0, t: 0, onDone }; this.orbitS = null; }
  orbit(o, onDone) { this.mode = 'orbit'; this.orbitS = { ...o, t: 0, onDone }; this.shots = null; }
  toFP() { this.mode = 'fp'; this.shots = null; this.orbitS = null; }

  update(dtReal, enemyFocus) {
    this.t += dtReal;
    const cam = this.cam, t = this.t;
    this.trauma = Math.max(0, this.trauma - dtReal * 1.7);
    const tr = this.trauma * this.trauma;
    const sx = (Math.sin(t * 37.1) + Math.sin(t * 23.3 + 1.7) * 0.6) * tr, sy = (Math.sin(t * 41.7 + 0.5) + Math.sin(t * 19.1 + 2.1) * 0.6) * tr, sr = (Math.sin(t * 29.3 + 3.3)) * tr;
    // 반동 스프링
    const h = Math.min(dtReal, 1 / 30);
    this.offV.addScaledVector(this.off, -140 * h).multiplyScalar(Math.max(0, 1 - 13 * h));
    this.off.addScaledVector(this.offV, h);
    this.rollV += (-this.roll * 120) * h; this.rollV *= Math.max(0, 1 - 12 * h); this.roll += this.rollV * h;
    this.fovKick *= Math.exp(-dtReal * 7);
    let dx = 0;
    if (this.dodgeT >= 0) {
      this.dodgeT += dtReal;
      const u = this.dodgeT / 0.46;
      dx = this.dodgeSide * 0.62 * (u < 0.35 ? Math.sin((u / 0.35) * Math.PI / 2) : Math.max(0, 1 - io((u - 0.35) / 0.65)));
      if (u >= 1) { this.dodgeT = -1; dx = 0; }
    }
    this.dodgeX = dx;
    if (this.mode === 'fp') {
      const ez = this.enemyZ;
      if (enemyFocus) this.focusTarget.set(enemyFocus.x * 0.45, 1.26 + (enemyFocus.y - 1.3) * 0.3, ez + (enemyFocus.z - ez) * 0.4);
      this.focus.lerp(this.focusTarget, 1 - Math.exp(-dtReal * 6));
      cam.position.set(this.base.x + dx + this.off.x + sx * 0.035, this.base.y + this.off.y + sy * 0.03 - Math.abs(dx) * 0.06, this.base.z + this.off.z);
      this._l.copy(this.focus); this._l.x += dx * 0.35 + sx * 0.05; this._l.y += sy * 0.04;
      cam.lookAt(this._l);
      cam.rotateZ(this.roll + sr * 0.04 - this.dodgeSide * 0.06 * Math.abs(dx) / 0.62);
      this._setFov(this.engine.baseFov + this.fovKick);
    } else if (this.mode === 'cine' && this.shots) {
      const S = this.shots, sh = S.list[S.i];
      S.t += dtReal;
      const u = Math.min(1, S.t / sh.dur), k = sh.ease === 'linear' ? u : io(u);
      this._p.lerpVectors(sh.from.p, sh.to.p, k); this._l.lerpVectors(sh.from.t, sh.to.t, k);
      cam.position.copy(this._p).add(V3(sx * 0.04, sy * 0.04, 0));
      cam.lookAt(this._l); cam.rotateZ(sr * 0.05 + (sh.roll || 0));
      this._setFov((sh.from.fov ?? 50) + ((sh.to.fov ?? sh.from.fov ?? 50) - (sh.from.fov ?? 50)) * k + this.fovKick);
      if (S.t >= sh.dur) {
        if (sh.onEnd) sh.onEnd();
        S.i++; S.t = 0;
        if (S.i >= S.list.length) { const cb = S.onDone; this.shots = null; if (cb) cb(); }
      }
    } else if (this.mode === 'orbit' && this.orbitS) {
      const O = this.orbitS; O.t += dtReal;
      const u = Math.min(1, O.t / O.dur), k = io(u);
      const a = O.a0 + (O.a1 - O.a0) * k, r = O.r0 + (O.r1 - O.r0) * k, y = O.h0 + (O.h1 - O.h0) * k;
      cam.position.set(O.center.x + Math.sin(a) * r + sx * 0.04, y + sy * 0.03, O.center.z + Math.cos(a) * r);
      this._l.copy(O.center); this._l.y = O.lookY ?? O.center.y;
      cam.lookAt(this._l); cam.rotateZ(sr * 0.04);
      this._setFov((O.fov ?? 48) + this.fovKick);
      if (u >= 1 && O.onDone) { const cb = O.onDone; O.onDone = null; cb(); }
    }
  }
  _setFov(f) {
    if (Math.abs(this.cam.fov - f) > 0.01) { this.cam.fov = f; this.cam.updateProjectionMatrix(); }
  }
}
