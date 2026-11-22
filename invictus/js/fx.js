// ─────────────────────────────────────────────────────────────
//  이펙트: 스파크(속도 늘림 파티클), 발광/먼지 입자, 검기 리본 트레일,
//  손가락 스와이프 리본, 잔상, 공격 예고 궤적, 파편(투구·방패) 물리
// ─────────────────────────────────────────────────────────────
import * as THREE from 'three';

const V3 = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const _a = V3(), _b = V3(), _c = V3(), _d = V3(), _q = new THREE.Quaternion();
const rnd = (a, b) => a + Math.random() * (b - a);

export const SPARK_VS = /* glsl */`
attribute vec3 aPos; attribute vec3 aVel; attribute vec4 aCol; attribute float aSize;
varying vec4 vCol; varying vec2 vUv;
void main(){
  vec4 a = viewMatrix * vec4(aPos, 1.0);
  vec4 b = viewMatrix * vec4(aPos - aVel * 0.03, 1.0);
  vec2 d = a.xy - b.xy; float l = length(d);
  d = l > 1e-5 ? d / l : vec2(1.0, 0.0);
  vec2 n = vec2(-d.y, d.x);
  vec4 p = mix(b, a, position.x);
  p.xy += n * position.y * aSize;
  vUv = position.xy; vCol = aCol;
  gl_Position = projectionMatrix * p;
}`;
export const SPARK_FS = /* glsl */`
varying vec4 vCol; varying vec2 vUv;
void main(){
  float e = 1.0 - abs(vUv.y);
  float a = e * e * smoothstep(0.0, 0.35, vUv.x) * vCol.a;
  gl_FragColor = vec4(vCol.rgb, a);
}`;
export const GLOW_VS = /* glsl */`
attribute vec3 aColor; attribute float aAlpha; attribute float aSize;
uniform float uScale;
varying vec3 vC; varying float vA;
void main(){
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = aSize * uScale / max(0.05, -mv.z);
  vC = aColor; vA = aAlpha;
}`;
export const GLOW_FS = /* glsl */`
varying vec3 vC; varying float vA;
void main(){
  float d = length(gl_PointCoord - vec2(0.5)) * 2.0;
  float a = smoothstep(1.0, 0.0, d); a *= a * vA;
  if (a < 0.003) discard;
  gl_FragColor = vec4(vC, a);
}`;
export const RIBBON_VS = /* glsl */`
attribute float aAlpha; attribute float aSide;
varying float vA; varying float vS;
void main(){ vA = aAlpha; vS = aSide; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
export const RIBBON_FS = /* glsl */`
uniform vec3 uColor; uniform float uBoost; uniform float uMode;
varying float vA; varying float vS;
void main(){
  float a, core;
  if (uMode < 0.5) { a = vA * smoothstep(0.0, 1.0, vS); core = smoothstep(0.75, 1.0, vS); }
  else { float e = 1.0 - abs(vS); a = vA * (0.25 + 0.75 * smoothstep(0.0, 0.85, e)); core = smoothstep(0.55, 1.0, e); }
  vec3 c = mix(uColor, vec3(1.0), core * 0.85);
  gl_FragColor = vec4(c * uBoost, a);
}`;
export const TELE_VS = /* glsl */`
varying vec2 vUv;
void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
export const TELE_FS = /* glsl */`
uniform vec3 uColor; uniform float uProgress; uniform float uFlash; uniform float uTime; uniform float uAlpha;
varying vec2 vUv;
void main(){
  float across = 1.0 - abs(vUv.y);
  float core = smoothstep(0.0, 0.7, across);
  float filled = step(vUv.x, uProgress);
  float flow = 0.5 + 0.5 * sin(vUv.x * 16.0 - uTime * 12.0);
  float head = smoothstep(0.0, 0.18, vUv.x);
  float a = (0.22 + 0.48 * filled + 0.3 * flow * filled) * core * head;
  a += uFlash * 0.45 * core * head;
  vec3 c = mix(uColor, vec3(1.0, 0.96, 0.85), uFlash * 0.65 + smoothstep(0.85, 1.0, across) * 0.4);
  gl_FragColor = vec4(c * 2.4, clamp(a * uAlpha, 0.0, 1.0));
}`;

function shader(vs, fs, uniforms, extra) {
  return new THREE.ShaderMaterial({ vertexShader: vs, fragmentShader: fs, uniforms, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, ...extra });
}

class Ribbon {
  constructor(scene, max = 40, mode = 0) {
    this.max = max; this.pts = []; this.mode = mode;
    this.pos = new Float32Array(max * 2 * 3); this.alpha = new Float32Array(max * 2); this.side = new Float32Array(max * 2);
    const idx = [];
    for (let i = 0; i < max - 1; i++) { const a = i * 2; idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
    const g = this.geo = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(this.pos, 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('aAlpha', new THREE.BufferAttribute(this.alpha, 1).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('aSide', new THREE.BufferAttribute(this.side, 1));
    g.setIndex(idx);
    for (let i = 0; i < max; i++) { this.side[i * 2] = mode === 0 ? 0 : -1; this.side[i * 2 + 1] = 1; }
    this.u = { uColor: { value: new THREE.Color(0xbfe4ff) }, uBoost: { value: 2.2 }, uMode: { value: mode } };
    this.mesh = new THREE.Mesh(g, shader(RIBBON_VS, RIBBON_FS, this.u, { side: THREE.DoubleSide }));
    this.mesh.frustumCulled = false; this.mesh.renderOrder = 30; this.mesh.visible = false;
    scene.add(this.mesh);
    this.active = false; this.id = null; this.life = 0.14;
  }
  begin(id, color, life = 0.14) { this.id = id; this.active = true; this.pts.length = 0; this.u.uColor.value.set(color); this.life = life; this.mesh.visible = true; }
  push(a, b, t) {
    this.pts.push({ a: a.clone(), b: b.clone(), t });
    if (this.pts.length > this.max) this.pts.shift();
  }
  update(t) {
    while (this.pts.length && t - this.pts[0].t > this.life) this.pts.shift();
    const n = this.pts.length;
    if (!n) { if (!this.active) this.mesh.visible = false; this.geo.setDrawRange(0, 0); return; }
    for (let i = 0; i < n; i++) {
      const p = this.pts[i], k = 1 - (t - p.t) / this.life;
      this.pos.set([p.a.x, p.a.y, p.a.z, p.b.x, p.b.y, p.b.z], i * 6);
      const fade = Math.max(0, k) * Math.min(1, (i + 1) / Math.max(2, n * 0.35));
      this.alpha[i * 2] = fade; this.alpha[i * 2 + 1] = fade;
    }
    this.geo.attributes.position.needsUpdate = true; this.geo.attributes.aAlpha.needsUpdate = true;
    this.geo.setDrawRange(0, Math.max(0, (n - 1) * 6));
  }
}

export class FX {
  constructor(scene, camera, engine) {
    this.scene = scene; this.camera = camera; this.engine = engine;
    this.t = 0; this.tReal = 0;
    this._initSparks(); this._initGlow(); this._initDust();
    this.ribbons = [new Ribbon(scene, 40, 0), new Ribbon(scene, 40, 0), new Ribbon(scene, 40, 0)];
    // 손가락 스와이프 리본(카메라 공간)
    this.swipe = new Ribbon(camera, 64, 1);
    this.swipe.u.uColor.value.set(0x9fd8ff); this.swipe.u.uBoost.value = 2.6; this.swipe.mesh.renderOrder = 60;
    this.swipe.mesh.material.depthTest = false;
    this.swipeLife = 0.2;
    // 잔상
    this.ghosts = [];
    for (let i = 0; i < 14; i++) {
      const m = new THREE.Mesh(new THREE.BufferGeometry(), new THREE.MeshBasicMaterial({ color: 0x9fd0ff, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false }));
      m.matrixAutoUpdate = false; m.visible = false; m.frustumCulled = false; m.renderOrder = 25;
      scene.add(m); this.ghosts.push({ m, life: 0 });
    }
    this._ghostLast = {};
    this.gi = 0;
    // 예고 궤적
    this.teleU = { uColor: { value: new THREE.Color(1, 0.55, 0.1) }, uProgress: { value: 0 }, uFlash: { value: 0 }, uTime: { value: 0 }, uAlpha: { value: 1 } };
    this.teleMat = shader(TELE_VS, TELE_FS, this.teleU, { side: THREE.DoubleSide, depthTest: false });
    this.tele = new THREE.Mesh(new THREE.BufferGeometry(), this.teleMat);
    this.tele.frustumCulled = false; this.tele.renderOrder = 50; this.tele.visible = false; scene.add(this.tele);
    this.debris = [];
    this.chunks = [];
    this._initChunks();
    this.colorSpark = new THREE.Color();
  }

  // ── 스파크 ──────────────────────────────────────────────
  _initSparks() {
    const N = this.sN = 320;
    const pos = new Float32Array(N * 4 * 3), idx = [];
    const aPos = new Float32Array(N * 4 * 3), aVel = new Float32Array(N * 4 * 3), aCol = new Float32Array(N * 4 * 4), aSize = new Float32Array(N * 4);
    for (let i = 0; i < N; i++) {
      const c = [[0, -1], [1, -1], [1, 1], [0, 1]];
      for (let k = 0; k < 4; k++) { pos[(i * 4 + k) * 3] = c[k][0]; pos[(i * 4 + k) * 3 + 1] = c[k][1]; }
      const b = i * 4; idx.push(b, b + 1, b + 2, b, b + 2, b + 3);
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('aPos', new THREE.BufferAttribute(aPos, 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('aVel', new THREE.BufferAttribute(aVel, 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('aCol', new THREE.BufferAttribute(aCol, 4).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('aSize', new THREE.BufferAttribute(aSize, 1).setUsage(THREE.DynamicDrawUsage));
    g.setIndex(idx);
    this.sGeo = g;
    this.sp = Array.from({ length: N }, () => ({ life: 0, max: 1, p: V3(), v: V3(), c: new THREE.Color(), size: 0.01, g: 6, drag: 1.5 }));
    this.sNext = 0;
    const m = new THREE.Mesh(g, shader(SPARK_VS, SPARK_FS, {}, { side: THREE.DoubleSide }));
    m.frustumCulled = false; m.renderOrder = 40; this.scene.add(m);
  }
  sparks(pos, dir, n = 20, o = {}) {
    const col = this.colorSpark.set(o.color ?? 0xffc060).multiplyScalar(o.hdr ?? 5);
    for (let i = 0; i < n; i++) {
      const s = this.sp[this.sNext]; this.sNext = (this.sNext + 1) % this.sN;
      s.p.copy(pos);
      _a.set(rnd(-1, 1), rnd(-1, 1), rnd(-1, 1)).normalize().multiplyScalar(o.spread ?? 0.8);
      s.v.copy(dir).normalize().add(_a).normalize().multiplyScalar(rnd(o.speed?.[0] ?? 2.5, o.speed?.[1] ?? 7));
      s.max = s.life = rnd(o.life?.[0] ?? 0.18, o.life?.[1] ?? 0.45);
      s.c.copy(col).multiplyScalar(rnd(0.6, 1.2));
      s.size = (o.size ?? 0.007) * rnd(0.6, 1.3);
      s.g = o.gravity ?? 7; s.drag = o.drag ?? 1.2;
    }
  }
  _updSparks(dt) {
    const g = this.sGeo, P = g.attributes.aPos.array, Vv = g.attributes.aVel.array, C = g.attributes.aCol.array, S = g.attributes.aSize.array;
    for (let i = 0; i < this.sN; i++) {
      const s = this.sp[i];
      let a = 0;
      if (s.life > 0) {
        s.life -= dt;
        s.v.y -= s.g * dt; s.v.multiplyScalar(Math.max(0, 1 - s.drag * dt));
        s.p.addScaledVector(s.v, dt);
        a = Math.max(0, s.life / s.max);
      }
      for (let k = 0; k < 4; k++) {
        const j = i * 4 + k;
        P[j * 3] = s.p.x; P[j * 3 + 1] = s.p.y; P[j * 3 + 2] = s.p.z;
        Vv[j * 3] = s.v.x; Vv[j * 3 + 1] = s.v.y; Vv[j * 3 + 2] = s.v.z;
        C[j * 4] = s.c.r; C[j * 4 + 1] = s.c.g; C[j * 4 + 2] = s.c.b; C[j * 4 + 3] = a;
        S[j] = s.size;
      }
    }
    g.attributes.aPos.needsUpdate = true; g.attributes.aVel.needsUpdate = true; g.attributes.aCol.needsUpdate = true; g.attributes.aSize.needsUpdate = true;
  }

  // ── 발광 / 먼지 포인트 ─────────────────────────────────
  _mkPoints(N, blending, order) {
    const g = new THREE.BufferGeometry();
    const pos = new Float32Array(N * 3), col = new Float32Array(N * 3), al = new Float32Array(N), sz = new Float32Array(N);
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('aColor', new THREE.BufferAttribute(col, 3).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('aAlpha', new THREE.BufferAttribute(al, 1).setUsage(THREE.DynamicDrawUsage));
    g.setAttribute('aSize', new THREE.BufferAttribute(sz, 1).setUsage(THREE.DynamicDrawUsage));
    const u = { uScale: { value: 400 } };
    const pts = new THREE.Points(g, shader(GLOW_VS, GLOW_FS, u, { blending }));
    pts.frustumCulled = false; pts.renderOrder = order; this.scene.add(pts);
    return { g, u, N, next: 0, ps: Array.from({ length: N }, () => ({ life: 0, max: 1, p: V3(), v: V3(), c: new THREE.Color(), s0: 0.1, s1: 0.2, a: 1, g: 0, drag: 1 })) };
  }
  _initGlow() { this.gl = this._mkPoints(220, THREE.AdditiveBlending, 41); }
  _initDust() { this.du = this._mkPoints(160, THREE.NormalBlending, 20); }
  _emit(sys, pos, o) {
    const s = sys.ps[sys.next]; sys.next = (sys.next + 1) % sys.N;
    s.p.copy(pos); s.v.copy(o.v || _d.set(0, 0, 0));
    s.max = s.life = o.life ?? 0.3; s.c.set(o.color ?? 0xffffff).multiplyScalar(o.hdr ?? 1);
    s.s0 = o.s0 ?? 0.1; s.s1 = o.s1 ?? s.s0; s.a = o.a ?? 1; s.g = o.g ?? 0; s.drag = o.drag ?? 1;
  }
  glow(pos, color = 0xffd090, size = 0.35, life = 0.18, hdr = 4) { this._emit(this.gl, pos, { color, hdr, s0: size * 0.6, s1: size, life, a: 1 }); }
  dust(pos, n = 10, o = {}) {
    for (let i = 0; i < n; i++) {
      _b.set(rnd(-1, 1), rnd(0.1, 0.6), rnd(-1, 1)).normalize().multiplyScalar(rnd(0.4, o.speed ?? 1.6));
      _c.copy(pos).add(_d.set(rnd(-0.15, 0.15), rnd(0, 0.05), rnd(-0.15, 0.15)));
      this._emit(this.du, _c, { v: _b.clone(), color: o.color ?? 0xb89a72, hdr: 1, s0: rnd(0.12, 0.25), s1: rnd(0.5, 0.9) * (o.scale ?? 1), life: rnd(0.6, 1.3), a: o.a ?? 0.55, g: -0.15, drag: 2.2 });
    }
  }
  embers(pos, n = 6, color = 0xffa040) {
    for (let i = 0; i < n; i++) this._emit(this.gl, _c.copy(pos).add(_d.set(rnd(-0.08, 0.08), rnd(-0.05, 0.1), rnd(-0.08, 0.08))), { v: _b.set(rnd(-0.3, 0.3), rnd(0.4, 1.0), rnd(-0.3, 0.3)).clone(), color, hdr: 3, s0: 0.02, s1: 0.005, life: rnd(0.4, 0.8), g: -0.5, drag: 1 });
  }
  heal() {
    this.camera.updateMatrixWorld();
    for (let i = 0; i < 26; i++) {
      _c.set(rnd(-0.35, 0.35), rnd(-0.45, 0.1), rnd(-0.9, -0.5)).applyMatrix4(this.camera.matrixWorld);
      this._emit(this.gl, _c, { v: _b.set(0, rnd(0.3, 0.8), 0).clone(), color: i % 2 ? 0xff5060 : 0xffd080, hdr: 2.5, s0: 0.03, s1: 0.012, life: rnd(0.6, 1.1), g: -0.3 });
    }
  }
  flash(pos, color = 0xffe0b0, size = 0.9) { this.glow(pos, color, size, 0.12, 6); }
  _updPoints(sys, dt) {
    const P = sys.g.attributes.position.array, C = sys.g.attributes.aColor.array, A = sys.g.attributes.aAlpha.array, S = sys.g.attributes.aSize.array;
    for (let i = 0; i < sys.N; i++) {
      const s = sys.ps[i];
      if (s.life > 0) {
        s.life -= dt;
        s.v.y -= s.g * dt; s.v.multiplyScalar(Math.max(0, 1 - s.drag * dt)); s.p.addScaledVector(s.v, dt);
        const k = 1 - Math.max(0, s.life) / s.max;
        P[i * 3] = s.p.x; P[i * 3 + 1] = s.p.y; P[i * 3 + 2] = s.p.z;
        C[i * 3] = s.c.r; C[i * 3 + 1] = s.c.g; C[i * 3 + 2] = s.c.b;
        A[i] = s.a * (1 - k) * Math.min(1, k * 8 + 0.3); S[i] = s.s0 + (s.s1 - s.s0) * k;
      } else { A[i] = 0; S[i] = 0; }
    }
    for (const k of ['position', 'aColor', 'aAlpha', 'aSize']) sys.g.attributes[k].needsUpdate = true;
  }

  // ── 무기 트레일 / 잔상 ──────────────────────────────────
  trailBegin(id, color = 0xbfe4ff, life) {
    const r = this.ribbons.find((x) => !x.active) || this.ribbons[0];
    r.begin(id, color, life);
  }
  trailPush(id, base, tip) { const r = this.ribbons.find((x) => x.id === id && x.active); if (r) r.push(base, tip, this.tReal); }
  trailEnd(id) { const r = this.ribbons.find((x) => x.id === id); if (r) { r.active = false; r.id = null; } }
  ghost(bladeMesh, id) {
    const last = this._ghostLast[id] || 0;
    if (this.tReal - last < 1 / 70) return;
    this._ghostLast[id] = this.tReal;
    const g = this.ghosts[this.gi]; this.gi = (this.gi + 1) % this.ghosts.length;
    bladeMesh.updateWorldMatrix(true, false);
    g.m.geometry = bladeMesh.geometry; g.m.matrix.copy(bladeMesh.matrixWorld); g.m.matrixWorldNeedsUpdate = true;
    g.m.visible = true; g.life = 0.13; g.m.material.opacity = 0.32;
  }

  // ── 손가락 스와이프 리본 (화면 좌표 → 카메라 공간) ─────
  _screenToCam(x, y, out, depth = 0.6) {
    const c = this.camera, w = window.innerWidth, h = window.innerHeight;
    const ty = Math.tan(THREE.MathUtils.degToRad(c.fov / 2)), tx = ty * c.aspect;
    return out.set(((x / w) * 2 - 1) * tx * depth, (1 - (y / h) * 2) * ty * depth, -depth);
  }
  swipeStart(x, y) { this.swipe.begin('swipe', this.swipeColor || 0x9fd8ff, this.swipeLife); this._sw = { last: this._screenToCam(x, y, V3()) }; this._swipePt(x, y); }
  swipeMove(x, y) { if (this._sw) this._swipePt(x, y); }
  _swipePt(x, y) {
    const p = this._screenToCam(x, y, V3());
    const last = this._sw.last;
    _a.subVectors(p, last); _a.z = 0;
    if (_a.lengthSq() < 1e-8 && this.swipe.pts.length) return;
    _a.normalize();
    const n = this.swipe.pts.length, w = 0.0085 * Math.min(1, 0.4 + n * 0.12);
    const side = V3(-_a.y, _a.x, 0).multiplyScalar(w);
    this.swipe.push(p.clone().add(side), p.clone().sub(side), this.tReal);
    this._sw.last = p;
  }
  swipeEnd() { this.swipe.active = false; this._sw = null; }

  // ── 공격 예고 궤적 ─────────────────────────────────────
  showTelegraph(points, red = false) {
    const n = points.length, cam = this.camera.getWorldPosition(V3());
    const pos = [], uv = [], idx = [];
    for (let i = 0; i < n; i++) {
      const p = points[i], a = points[Math.max(0, i - 1)], b = points[Math.min(n - 1, i + 1)];
      _a.subVectors(b, a).normalize();
      _b.subVectors(cam, p).normalize();
      const w = (0.016 + 0.034 * (i / (n - 1))) * (red ? 1.25 : 1);
      _c.crossVectors(_a, _b).normalize().multiplyScalar(w);
      pos.push(p.x + _c.x, p.y + _c.y, p.z + _c.z, p.x - _c.x, p.y - _c.y, p.z - _c.z);
      uv.push(i / (n - 1), 1, i / (n - 1), -1);
      if (i < n - 1) { const k = i * 2; idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2); }
    }
    // 화살촉
    const e = points[n - 1]; _a.subVectors(e, points[n - 3]).normalize(); _b.subVectors(cam, e).normalize();
    _c.crossVectors(_a, _b).normalize().multiplyScalar(0.11 * (red ? 1.2 : 1));
    const base = pos.length / 3;
    pos.push(e.x + _c.x, e.y + _c.y, e.z + _c.z, e.x - _c.x, e.y - _c.y, e.z - _c.z, e.x + _a.x * 0.16, e.y + _a.y * 0.16, e.z + _a.z * 0.16);
    uv.push(0.97, 0.8, 0.97, -0.8, 0.99, 0);
    idx.push(base, base + 1, base + 2);
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    g.setIndex(idx);
    this.tele.geometry.dispose(); this.tele.geometry = g;
    this.teleU.uColor.value.set(red ? 0xff1a10 : 0xff8a1a);
    this.teleU.uProgress.value = 0; this.teleU.uFlash.value = 0; this.teleU.uAlpha.value = 1;
    this.tele.visible = true; this.teleFade = 0;
  }
  setTelegraph(progress, flash) { this.teleU.uProgress.value = progress; this.teleU.uFlash.value = flash; }
  hideTelegraph(fade = true) { if (fade) this.teleFade = 0.12; else this.tele.visible = false; }

  // ── 파편 물리 ──────────────────────────────────────────
  detach(obj, vel, ang, radius = 0.1) {
    obj.updateWorldMatrix(true, false);
    this.scene.attach(obj);
    obj.traverse((o) => { if (o.isMesh) o.castShadow = true; });
    this.debris.push({ obj, vel: vel.clone(), ang: ang.clone(), r: radius, rest: false, bounces: 0 });
  }
  _initChunks() {
    const geo = new THREE.BoxGeometry(0.06, 0.02, 0.02);
    const mat = new THREE.MeshStandardMaterial({ color: 0x8a5a32, roughness: 0.8 });
    this.chunkMesh = new THREE.InstancedMesh(geo, mat, 48);
    this.chunkMesh.frustumCulled = false; this.chunkMesh.castShadow = true;
    this.chunkData = Array.from({ length: 48 }, () => ({ life: 0, p: V3(), v: V3(), r: new THREE.Euler(), rv: V3(), s: 1 }));
    this.chunkNext = 0; this.scene.add(this.chunkMesh);
    this._m4 = new THREE.Matrix4(); this._zero = new THREE.Matrix4().makeScale(0, 0, 0);
    for (let i = 0; i < 48; i++) this.chunkMesh.setMatrixAt(i, this._zero);
  }
  splinters(pos, n = 16, color) {
    if (color) this.chunkMesh.material.color.set(color);
    for (let i = 0; i < n; i++) {
      const c = this.chunkData[this.chunkNext]; this.chunkNext = (this.chunkNext + 1) % 48;
      c.life = rnd(1.5, 2.5); c.p.copy(pos).add(_a.set(rnd(-0.15, 0.15), rnd(-0.2, 0.2), rnd(-0.05, 0.05)));
      c.v.set(rnd(-2.5, 2.5), rnd(1, 4), rnd(-0.5, 2.5)); c.r.set(rnd(0, 6), rnd(0, 6), rnd(0, 6)); c.rv.set(rnd(-15, 15), rnd(-15, 15), rnd(-15, 15)); c.s = rnd(0.6, 1.6);
    }
  }
  _updDebris(dt) {
    for (const d of this.debris) {
      if (d.rest) continue;
      d.vel.y -= 9.8 * dt;
      d.obj.position.addScaledVector(d.vel, dt);
      const al = d.ang.length();
      if (al > 1e-4) { _q.setFromAxisAngle(_a.copy(d.ang).divideScalar(al), al * dt); d.obj.quaternion.premultiply(_q); }
      if (d.obj.position.y < d.r) {
        d.obj.position.y = d.r;
        if (d.vel.y < -0.6 && this.onBounce) this.onBounce(d, Math.min(1, -d.vel.y / 6));
        d.vel.y = -d.vel.y * 0.32; d.vel.x *= 0.55; d.vel.z *= 0.55; d.ang.multiplyScalar(0.5); d.bounces++;
        if (d.bounces > 1 && Math.abs(d.vel.y) < 0.4) { d.vel.set(0, 0, 0); d.ang.multiplyScalar(0.0); d.rest = true; if (this.onSettle) this.onSettle(d); }
      }
      // 아레나 벽
      const r = Math.hypot(d.obj.position.x, d.obj.position.z);
      if (r > 19.5) { d.obj.position.multiplyScalar(19.5 / r); d.vel.x *= -0.4; d.vel.z *= -0.4; }
    }
    let any = false;
    for (let i = 0; i < 48; i++) {
      const c = this.chunkData[i];
      if (c.life <= 0) continue;
      any = true; c.life -= dt;
      c.v.y -= 9.8 * dt; c.p.addScaledVector(c.v, dt);
      if (c.p.y < 0.01) { c.p.y = 0.01; c.v.multiplyScalar(0.3); c.v.y = Math.abs(c.v.y) * 0.3; c.rv.multiplyScalar(0.4); }
      c.r.x += c.rv.x * dt; c.r.y += c.rv.y * dt; c.r.z += c.rv.z * dt;
      const sc = c.life < 0.3 ? c.life / 0.3 : 1;
      this._m4.makeRotationFromEuler(c.r).scale(_b.set(c.s * sc, sc, sc)).setPosition(c.p);
      this.chunkMesh.setMatrixAt(i, c.life > 0 ? this._m4 : this._zero);
    }
    if (any || this._chunkDirty) { this.chunkMesh.instanceMatrix.needsUpdate = true; this._chunkDirty = any; }
  }
  clearDebris() {
    for (const d of this.debris) {
      d.obj.removeFromParent();
      d.obj.traverse((o) => { if (o.isMesh && o.geometry && !o.userData.keepGeo) o.geometry.dispose(); });
    }
    this.debris.length = 0;
  }

  // ── 매 프레임 ──────────────────────────────────────────
  update(dt, dtReal) {
    this.t += dt; this.tReal += dtReal;
    const h = this.engine.h * this.engine.dpr;
    const scale = h * 0.5 / Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
    this.gl.u.uScale.value = scale; this.du.u.uScale.value = scale;
    this._updSparks(dt);
    this._updPoints(this.gl, dt); this._updPoints(this.du, dt);
    for (const r of this.ribbons) r.update(this.tReal);
    this.swipe.update(this.tReal);
    for (const g of this.ghosts) {
      if (g.life <= 0) continue;
      g.life -= dtReal; g.m.material.opacity = Math.max(0, g.life / 0.13) * 0.32;
      if (g.life <= 0) g.m.visible = false;
    }
    this.teleU.uTime.value = this.tReal;
    if (this.teleFade > 0) {
      this.teleFade -= dtReal;
      this.teleU.uAlpha.value = Math.max(0, this.teleFade / 0.12);
      if (this.teleFade <= 0) this.tele.visible = false;
    }
    this._updDebris(dt);
  }
}
