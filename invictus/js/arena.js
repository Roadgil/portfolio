// ─────────────────────────────────────────────────────────────
//  로마 콜로세움 아레나: 모래 바닥, 포디움 벽, 아치형 석조 아케이드, 관중석,
//  황제석, 철문, 횃불/화로(포인트 라이트), 깃발, 먼지·불씨 입자, 하늘, 빛줄기
// ─────────────────────────────────────────────────────────────
import * as THREE from 'three';
import { genBanner } from './textures.js';

export const SHARED = {
  uTime: { value: 0 },
  uFogColor: { value: new THREE.Color(0xd6c6a8) },
  uFogDensity: { value: 0.012 },
  uSunDir: { value: new THREE.Vector3(0.4, 0.8, 0.4).normalize() },
  uSunColor: { value: new THREE.Color(1, 0.95, 0.85) },
  uAmbient: { value: new THREE.Color(0.35, 0.33, 0.3) },
  uPixel: { value: 1 },
};
const FOG_PARS = /* glsl */`
uniform vec3 uFogColor; uniform float uFogDensity;
vec3 applyFog(vec3 c, float depth){ float f = 1.0 - exp(-uFogDensity * uFogDensity * depth * depth); return mix(c, uFogColor, clamp(f, 0.0, 1.0)); }`;
const NOISE_GLSL = /* glsl */`
float hash12(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * 0.1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float vnoise(vec2 p){ vec2 i = floor(p), f = fract(p); vec2 u = f*f*(3.0-2.0*f);
  return mix(mix(hash12(i), hash12(i+vec2(1.0,0.0)), u.x), mix(hash12(i+vec2(0.0,1.0)), hash12(i+vec2(1.0,1.0)), u.x), u.y); }`;

// ── 셰이더 소스 (검증 스크립트에서도 import) ────────────────
export const SKY_VS = /* glsl */`
varying vec3 vDir;
void main(){ vDir = position; vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0); gl_Position = vec4(p.xy, p.w * 0.99995, p.w); }`;
export const SKY_FS = /* glsl */`
uniform vec3 uTop; uniform vec3 uHor; uniform vec3 uGround; uniform vec3 uGlow; uniform vec3 uSunDir; uniform float uStars; uniform float uTime; uniform float uSunSize;
varying vec3 vDir;
float h3(vec3 p){ p = fract(p * 0.3183099 + 0.1); p *= 17.0; return fract(p.x * p.y * p.z * (p.x + p.y + p.z)); }
void main(){
  vec3 d = normalize(vDir);
  float h = d.y;
  vec3 col = mix(uHor, uTop, pow(clamp(h, 0.0, 1.0), 0.55));
  col = mix(col, uGround, clamp(-h * 4.0, 0.0, 1.0));
  float s = max(dot(d, normalize(uSunDir)), 0.0);
  col += uGlow * (pow(s, 6.0) * 0.35 + pow(s, 48.0) * 0.9);
  col += uGlow * smoothstep(uSunSize, uSunSize + 0.0004, s) * 7.0;
  if (uStars > 0.0) {
    vec3 q = floor(d * 240.0);
    float st = step(0.9972, h3(q));
    col += vec3(0.9, 0.95, 1.0) * st * uStars * smoothstep(0.05, 0.35, h) * (0.55 + 0.45 * sin(uTime * 2.7 + h3(q + 3.1) * 40.0));
  }
  gl_FragColor = vec4(col, 1.0);
}`;
export const CROWD_VS = /* glsl */`
attribute vec4 aData; attribute vec3 aTint; attribute vec3 aSide;
uniform float uTime; uniform float uEx;
varying vec2 vUv; varying vec3 vTint; varying float vDepth; varying float vShade;
void main(){
  float ex = clamp(uEx, 0.0, 1.0);
  float isOn = step(aData.z, 0.25 + ex * 0.75);
  float freq = 4.0 + aData.z * 5.0;
  float jump = max(0.0, sin(uTime * freq + aData.x * 6.2831)) * (0.015 + 0.2 * ex) * isOn;
  float sway = sin(uTime * (1.2 + aData.z) + aData.x * 4.0) * 0.04;
  vec3 p = position + vec3(0.0, jump, 0.0) + aSide * sway;
  float cheer = step(aData.z * 0.85 + 0.12, ex);
  float frame = mix(aData.y, 2.0, cheer);
  vUv = vec2((frame + uv.x) * 0.25, uv.y);
  vTint = aTint; vShade = 0.55 + 0.45 * uv.y;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vDepth = -mv.z;
  gl_Position = projectionMatrix * mv;
}`;
export const CROWD_FS = /* glsl */`
uniform sampler2D uMap; uniform vec3 uAmbient; uniform vec3 uSunColor;
varying vec2 vUv; varying vec3 vTint; varying float vDepth; varying float vShade;
${FOG_PARS}
void main(){
  vec4 t = texture2D(uMap, vUv);
  if (t.a < 0.5) discard;
  vec3 c = t.rgb * vTint * (uAmbient * 1.4 + uSunColor * 0.22) * vShade;
  gl_FragColor = vec4(applyFog(c, vDepth), 1.0);
}`;
export const BANNER_VS = /* glsl */`
attribute float aPhase; attribute float aMode;
uniform float uTime;
varying vec2 vUv; varying vec3 vN; varying float vDepth; varying float vShade;
void main(){
  vUv = uv;
  float w = mix(1.0 - uv.y, uv.x, aMode);
  float t = uTime * (2.0 + aMode * 1.6) + aPhase;
  float wave = sin(t + uv.y * 4.0 + uv.x * 3.0) * 0.6 + sin(t * 1.7 + uv.x * 7.0 - uv.y * 2.0) * 0.3;
  float amp = mix(0.22, 0.35, aMode);
  vec3 p = position + normal * wave * w * amp;
  vShade = 0.82 + cos(t + uv.y * 4.0 + uv.x * 3.0) * 0.28 * w;
  vN = normalize(normalMatrix * normal);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vDepth = -mv.z;
  gl_Position = projectionMatrix * mv;
}`;
export const BANNER_FS = /* glsl */`
uniform sampler2D uMap; uniform vec3 uAmbient; uniform vec3 uSunColor; uniform vec3 uSunDir;
varying vec2 vUv; varying vec3 vN; varying float vDepth; varying float vShade;
${FOG_PARS}
void main(){
  vec4 t = texture2D(uMap, vUv);
  if (t.a < 0.5) discard;
  vec3 n = normalize(vN) * (gl_FrontFacing ? 1.0 : -1.0);
  vec3 l = normalize((viewMatrix * vec4(uSunDir, 0.0)).xyz);
  float lam = max(dot(n, l), 0.0) * 0.7 + 0.3;
  vec3 c = t.rgb * (uAmbient * 1.2 + uSunColor * lam * 0.9) * vShade;
  gl_FragColor = vec4(applyFog(c, vDepth), 1.0);
}`;
export const FLAME_VS = /* glsl */`
attribute vec3 aCenter; attribute vec2 aSize; attribute float aSeed;
varying vec2 vUv; varying float vSeed;
void main(){
  vUv = uv; vSeed = aSeed;
  vec4 mv = viewMatrix * vec4(aCenter, 1.0);
  mv.xy += position.xy * aSize;
  gl_Position = projectionMatrix * mv;
}`;
export const FLAME_FS = /* glsl */`
uniform float uTime; uniform float uIntensity;
varying vec2 vUv; varying float vSeed;
${NOISE_GLSL}
void main(){
  float t = uTime * 1.7 + vSeed * 13.0;
  float n = vnoise(vec2(vUv.x * 4.0 + vSeed, vUv.y * 3.0 - t * 2.3)) * 0.6 + vnoise(vec2(vUv.x * 9.0, vUv.y * 6.0 - t * 3.6)) * 0.4;
  float x = (vUv.x - 0.5) * 2.0 + (n - 0.5) * 0.35 * vUv.y;
  float width = 0.78 * pow(1.0 - vUv.y, 0.8) + 0.04;
  float shape = 1.0 - smoothstep(0.2, 1.0, abs(x) / width);
  float f = clamp(shape * (1.15 - vUv.y) * (0.45 + n * 1.1) * 1.5 - vUv.y * 0.3, 0.0, 1.0);
  vec3 col = mix(vec3(0.8, 0.12, 0.02), vec3(1.0, 0.5, 0.1), smoothstep(0.1, 0.45, f));
  col = mix(col, vec3(1.0, 0.9, 0.65), smoothstep(0.55, 0.95, f));
  gl_FragColor = vec4(col * f * uIntensity, f);
}`;
export const DUST_VS = /* glsl */`
attribute vec4 aD;
uniform float uTime; uniform float uSize; uniform float uPixel; uniform vec3 uBoxMin; uniform vec3 uBoxSize; uniform vec3 uWind;
varying float vA;
void main(){
  vec3 p = position + uWind * (uTime * aD.y) + vec3(sin(uTime * 0.5 + aD.x) * 0.35, sin(uTime * 0.7 + aD.x * 1.3) * 0.18, cos(uTime * 0.43 + aD.x) * 0.35);
  p = uBoxMin + mod(p - uBoxMin, uBoxSize);
  vec4 mv = viewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = aD.z * uSize * uPixel / max(0.4, -mv.z);
  float edge = smoothstep(0.0, 0.6, p.y - uBoxMin.y) * smoothstep(0.0, 1.5, uBoxMin.y + uBoxSize.y - p.y);
  vA = (0.35 + 0.65 * abs(sin(uTime * 0.6 + aD.w * 6.28))) * edge;
}`;
export const DUST_FS = /* glsl */`
uniform sampler2D uMap; uniform vec3 uColor; uniform float uOpacity;
varying float vA;
void main(){ float a = texture2D(uMap, gl_PointCoord).a * vA * uOpacity; gl_FragColor = vec4(uColor, a); }`;
export const EMBER_VS = /* glsl */`
attribute vec4 aD; attribute vec3 aBase;
uniform float uTime; uniform float uPixel;
varying float vA;
void main(){
  float life = 1.4 + aD.y;
  float t = mod(uTime + aD.x * life, life);
  float k = t / life;
  vec3 p = aBase + vec3(sin(t * 3.0 + aD.x * 9.0) * 0.12 * k, t * (0.7 + aD.z * 0.6), cos(t * 2.6 + aD.x * 7.0) * 0.12 * k);
  vec4 mv = viewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = (2.0 + aD.w * 3.0) * uPixel * (1.0 - k * 0.6) * 4.0 / max(0.5, -mv.z);
  vA = (1.0 - k) * smoothstep(0.0, 0.08, k);
}`;
export const EMBER_FS = /* glsl */`
uniform sampler2D uMap; uniform float uIntensity;
varying float vA;
void main(){ float a = texture2D(uMap, gl_PointCoord).a * vA; gl_FragColor = vec4(vec3(1.0, 0.55, 0.18) * uIntensity, a); }`;
export const SHAFT_VS = /* glsl */`
varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`;
export const SHAFT_FS = /* glsl */`
uniform vec3 uColor; uniform float uOpacity; uniform float uTime; varying vec2 vUv;
void main(){
  float edge = sin(vUv.x * 3.14159);
  float fade = smoothstep(0.0, 0.25, vUv.y) * smoothstep(1.0, 0.55, vUv.y);
  float flick = 0.85 + 0.15 * sin(uTime * 0.4 + vUv.y * 3.0);
  float a = edge * edge * fade * uOpacity * flick;
  gl_FragColor = vec4(uColor, a);
}`;

// ── 지오메트리 병합 유틸 ────────────────────────────────────
export function mergeGeos(list) {
  let total = 0;
  const geos = list.map((g) => { const n = g.index ? g.toNonIndexed() : g; total += n.attributes.position.count; return n; });
  const pos = new Float32Array(total * 3), nor = new Float32Array(total * 3), uv = new Float32Array(total * 2);
  let o = 0;
  for (const g of geos) {
    const c = g.attributes.position.count;
    pos.set(g.attributes.position.array, o * 3);
    if (g.attributes.normal) nor.set(g.attributes.normal.array, o * 3);
    if (g.attributes.uv) uv.set(g.attributes.uv.array, o * 2);
    o += c;
  }
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  out.setAttribute('normal', new THREE.BufferAttribute(nor, 3));
  out.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
  return out;
}
function repMat(mat, rx, ry) {
  const m = mat.clone();
  for (const k of ['map', 'normalMap', 'roughnessMap', 'metalnessMap']) if (m[k]) { m[k] = m[k].clone(); m[k].repeat.set(rx, ry); m[k].needsUpdate = true; }
  if (mat.metalnessMap && mat.metalnessMap === mat.roughnessMap) m.metalnessMap = m.roughnessMap;
  return m;
}
function plaqueTex() {
  const c = document.createElement('canvas'); c.width = 1024; c.height = 140;
  const g = c.getContext('2d');
  g.fillStyle = '#6e0f0f'; g.fillRect(0, 0, 1024, 140);
  g.strokeStyle = '#d8b04a'; g.lineWidth = 8; g.strokeRect(10, 10, 1004, 120);
  g.fillStyle = '#e2bd5a'; g.font = 'bold 84px Georgia, "Times New Roman", serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText('S · P · Q · R', 512, 76);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  return t;
}
function shaderMat(vs, fs, uniforms, extra = {}) {
  return new THREE.ShaderMaterial({ vertexShader: vs, fragmentShader: fs, uniforms, fog: false, ...extra });
}

const R_ARENA = 20, H_PODIUM = 4.2, STEP_D = 1.45, STEP_H = 1.2, STEPS = 6;

export class Arena {
  constructor(lib, engine, quality) {
    this.lib = lib; this.engine = engine; this.q = quality;
    this.group = new THREE.Group();
    engine.scene.add(this.group);
    this.excite = 0; this.exciteTarget = 0;
    this.torchLights = []; this.flameMeshes = [];
    const M = lib.M;

    this._sky();
    this._floor(M);
    this._podium(M);
    this._gates(M);
    this._tiers(M);
    this._arcade(M);
    this._pulvinar(M);
    this._crowd(lib.T.crowd);
    this._banners();
    this._fire(M, lib.T.dot);
    this._dust(lib.T.dot);
    this._shafts();
    this._lights();
  }

  _sky() {
    this.skyU = {
      uTop: { value: new THREE.Color() }, uHor: { value: new THREE.Color() }, uGround: { value: new THREE.Color(0x3a2a1c) },
      uGlow: { value: new THREE.Color() }, uSunDir: SHARED.uSunDir, uStars: { value: 0 }, uTime: SHARED.uTime, uSunSize: { value: 0.9994 },
    };
    const sky = new THREE.Mesh(new THREE.SphereGeometry(400, 40, 20), shaderMat(SKY_VS, SKY_FS, this.skyU, { side: THREE.BackSide, depthWrite: false }));
    sky.renderOrder = -1000; sky.frustumCulled = false;
    this.group.add(sky);
  }

  _floor(M) {
    const mat = repMat(M.sand, 11, 11);
    const floor = new THREE.Mesh(new THREE.CircleGeometry(R_ARENA + 0.2, 96), mat);
    floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true;
    this.group.add(floor);
    // 바닥 가장자리 어두운 모래(벽 그늘)
    const ring = new THREE.Mesh(new THREE.RingGeometry(R_ARENA - 2.5, R_ARENA + 0.1, 96, 1), new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.18, depthWrite: false }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.01; this.group.add(ring);
  }

  _podium(M) {
    const circ = 2 * Math.PI * R_ARENA;
    const wallMat = repMat(M.stone, circ / 4.2, 1);
    const wall = new THREE.Mesh(new THREE.CylinderGeometry(R_ARENA, R_ARENA, H_PODIUM, 128, 1, true), wallMat);
    wall.material.side = THREE.BackSide; wall.position.y = H_PODIUM / 2; wall.receiveShadow = true;
    this.group.add(wall);
    // 코니스(돌림띠)와 난간
    const trim = repMat(M.stone, circ / 2, 0.15); trim.color = new THREE.Color(0xe0d6c4); trim.side = THREE.BackSide;
    const cornice = new THREE.Mesh(new THREE.CylinderGeometry(R_ARENA - 0.25, R_ARENA - 0.1, 0.35, 128, 1, true), trim);
    cornice.position.y = H_PODIUM - 0.1; this.group.add(cornice);
    const base = new THREE.Mesh(new THREE.CylinderGeometry(R_ARENA - 0.18, R_ARENA - 0.05, 0.4, 128, 1, true), trim);
    base.position.y = 0.2; this.group.add(base);
    const para = new THREE.Mesh(new THREE.CylinderGeometry(R_ARENA - 0.05, R_ARENA - 0.05, 0.9, 128, 1, true), trim);
    para.position.y = H_PODIUM + 0.45; this.group.add(para);
  }

  _gates(M) {
    const frameMat = repMat(M.stone, 0.35, 0.35); frameMat.color = new THREE.Color(0xd8ccb6);
    const ironMat = M.darkIron;
    for (const z of [-1, 1]) {
      const g = new THREE.Group();
      const W = 3.4, H = 3.4, sp = H - W / 2;
      const outer = new THREE.Shape();
      outer.moveTo(-W / 2 - 0.55, 0); outer.lineTo(W / 2 + 0.55, 0); outer.lineTo(W / 2 + 0.55, H + 0.55); outer.lineTo(-W / 2 - 0.55, H + 0.55); outer.closePath();
      const hole = new THREE.Path();
      hole.moveTo(-W / 2, 0); hole.lineTo(-W / 2, sp); hole.absarc(0, sp, W / 2, Math.PI, 0, true); hole.lineTo(W / 2, 0); hole.closePath();
      outer.holes.push(hole);
      const fr = new THREE.Mesh(new THREE.ExtrudeGeometry(outer, { depth: 0.5, bevelEnabled: true, bevelThickness: 0.06, bevelSize: 0.06, bevelSegments: 2, curveSegments: 20 }), frameMat);
      fr.castShadow = false; fr.receiveShadow = true; g.add(fr);
      // 어두운 통로
      const vs = new THREE.Shape(); vs.moveTo(-W / 2, 0); vs.lineTo(-W / 2, sp); vs.absarc(0, sp, W / 2, Math.PI, 0, true); vs.lineTo(W / 2, 0); vs.closePath();
      const voidM = new THREE.Mesh(new THREE.ShapeGeometry(vs, 20), M.void); voidM.position.z = -0.28; g.add(voidM);
      // 쇠창살 문
      const bars = [];
      for (let i = -6; i <= 6; i++) {
        const x = i * (W / 13), top = Math.sqrt(Math.max(0, (W / 2) ** 2 - x * x)) + sp - 0.05;
        const b = new THREE.CylinderGeometry(0.035, 0.035, top, 6); b.translate(x, top / 2, -0.14); bars.push(b);
      }
      for (let k = 1; k <= 4; k++) { const b = new THREE.BoxGeometry(W, 0.07, 0.07); b.translate(0, k * 0.72, -0.14); bars.push(b); }
      const port = new THREE.Mesh(mergeGeos(bars), ironMat); g.add(port);
      g.position.set(0, 0, z * (R_ARENA - 0.42));
      g.rotation.y = z < 0 ? 0 : Math.PI;
      this.group.add(g);
    }
  }

  _tiers(M) {
    const geos = [];
    for (let k = 0; k < STEPS; k++) {
      const r0 = R_ARENA + 0.6 + k * STEP_D, y0 = H_PODIUM + k * STEP_H;
      const riser = new THREE.CylinderGeometry(r0, r0, STEP_H, 128, 1, true); riser.translate(0, y0 + STEP_H / 2, 0);
      // 안쪽을 향하도록 노멀 반전
      const n = riser.attributes.normal; for (let i = 0; i < n.count; i++) n.setXYZ(i, -n.getX(i), -n.getY(i), -n.getZ(i));
      const idx = riser.index.array; for (let i = 0; i < idx.length; i += 3) { const t = idx[i]; idx[i] = idx[i + 2]; idx[i + 2] = t; }
      const tread = new THREE.RingGeometry(r0, r0 + STEP_D, 128, 1); tread.rotateX(-Math.PI / 2); tread.translate(0, y0 + STEP_H, 0);
      geos.push(riser, tread);
    }
    const walk = new THREE.RingGeometry(R_ARENA - 0.05, R_ARENA + 0.6, 128, 1); walk.rotateX(-Math.PI / 2); walk.translate(0, H_PODIUM + 0.9, 0);
    geos.push(walk);
    const mat = repMat(M.stone, 60, 1.2); mat.color = new THREE.Color(0xb8ab96);
    const tiers = new THREE.Mesh(mergeGeos(geos), mat); tiers.receiveShadow = false;
    this.group.add(tiers);
  }

  _arcade(M) {
    const R = R_ARENA + 0.6 + STEPS * STEP_D + 0.3, N = 52, baseY = H_PODIUM + STEPS * STEP_H;
    const bayW = (2 * Math.PI * R) / N + 0.04, H = 4.2, hw = bayW * 0.3, sp = H * 0.62;
    const shape = new THREE.Shape();
    shape.moveTo(-bayW / 2, 0); shape.lineTo(bayW / 2, 0); shape.lineTo(bayW / 2, H); shape.lineTo(-bayW / 2, H); shape.closePath();
    const hole = new THREE.Path();
    hole.moveTo(-hw, 0.25); hole.lineTo(-hw, sp); hole.absarc(0, sp, hw, Math.PI, 0, true); hole.lineTo(hw, 0.25); hole.closePath();
    shape.holes.push(hole);
    const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.9, bevelEnabled: false, curveSegments: 10 });
    const mat = repMat(M.stone, 0.3, 0.3); mat.color = new THREE.Color(0xd2c4ad);
    const levels = 2, inst = new THREE.InstancedMesh(geo, mat, N * levels);
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(1, 1, 1), p = new THREE.Vector3(), up = new THREE.Vector3(0, 1, 0);
    let i = 0;
    for (let L = 0; L < levels; L++) for (let k = 0; k < N; k++) {
      const a = (k / N) * Math.PI * 2;
      p.set(Math.cos(a) * R, baseY + L * H, Math.sin(a) * R);
      q.setFromAxisAngle(up, -a - Math.PI / 2);
      m4.compose(p, q, s); inst.setMatrixAt(i++, m4);
    }
    inst.instanceMatrix.needsUpdate = true;
    this.group.add(inst);
    // 아치 너머 어두운 회랑 + 다락(attic) 벽
    const back = new THREE.Mesh(new THREE.CylinderGeometry(R + 2.2, R + 2.2, H * levels, 64, 1, true), new THREE.MeshStandardMaterial({ color: 0x2a221a, roughness: 1, side: THREE.BackSide }));
    back.position.y = baseY + H; this.group.add(back);
    const atticMat = repMat(M.stone, 80, 0.6); atticMat.color = new THREE.Color(0xc9bba3); atticMat.side = THREE.BackSide;
    const attic = new THREE.Mesh(new THREE.CylinderGeometry(R + 0.2, R + 0.2, 2.2, 128, 1, true), atticMat);
    attic.position.y = baseY + H * levels + 1.1; this.group.add(attic);
    this.arcade = { R, baseY, N, H, levels };
    // 아치 안쪽 횃불 불빛 (밤에 보임)
    this.archGlows = [];
  }

  _pulvinar(M) {
    // 황제석: 적 뒤편 포디움 위
    const g = new THREE.Group();
    const stone = repMat(M.stone, 0.5, 0.5); stone.color = new THREE.Color(0xe6dccb);
    const base = new THREE.Mesh(new THREE.BoxGeometry(7, 1.2, 2.4), stone); base.position.set(0, H_PODIUM + 0.6, -0.4); g.add(base);
    const roof = new THREE.Mesh(new THREE.BoxGeometry(7.4, 0.45, 3), stone); roof.position.set(0, H_PODIUM + 4.6, -0.6); g.add(roof);
    const tri = new THREE.Shape(); tri.moveTo(-3.7, 0); tri.lineTo(3.7, 0); tri.lineTo(0, 1.1); tri.closePath();
    const ped = new THREE.Mesh(new THREE.ExtrudeGeometry(tri, { depth: 0.5, bevelEnabled: false }), stone); ped.position.set(0, H_PODIUM + 4.82, 0.5); g.add(ped);
    for (const x of [-3.2, -1.1, 1.1, 3.2]) {
      const c = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.26, 3.4, 14), stone); c.position.set(x, H_PODIUM + 2.9, 0.6); g.add(c);
    }
    const drape = M.cloth.clone(); drape.color = new THREE.Color(0x8a1414);
    for (const x of [-2.15, 2.15]) {
      const d = new THREE.Mesh(new THREE.PlaneGeometry(1.6, 2.6, 6, 6), drape);
      const pp = d.geometry.attributes.position;
      for (let i = 0; i < pp.count; i++) pp.setZ(i, Math.sin(pp.getX(i) * 9) * 0.06);
      d.geometry.computeVertexNormals();
      d.position.set(x, H_PODIUM + 3.0, 0.55); g.add(d);
    }
    const rail = new THREE.Mesh(new THREE.BoxGeometry(7.1, 0.12, 0.14), M.gold); rail.position.set(0, H_PODIUM + 1.9, 0.75); g.add(rail);
    const banner = new THREE.Mesh(new THREE.PlaneGeometry(6.6, 0.9), new THREE.MeshStandardMaterial({ map: plaqueTex(), roughness: 0.75 }));
    banner.position.set(0, H_PODIUM + 0.6, 0.82); g.add(banner);
    g.position.set(0, 0, -(R_ARENA + 1.0));
    this.group.add(g);
  }

  _crowd(atlas) {
    const pos = [], uv = [], data = [], tint = [], side = [], idx = [];
    const palette = [0xe8e0cc, 0xd8cdb2, 0x9c2a22, 0xb8862e, 0x3c5a8a, 0x4a6a3a, 0x6a4a30, 0xcfc6b8, 0x7a2a5a].map((c) => new THREE.Color(c));
    let v = 0;
    const density = this.q.crowd;
    for (let k = 0; k < STEPS; k++) {
      const R = R_ARENA + 0.6 + k * STEP_D + 0.55, y = H_PODIUM + (k + 1) * STEP_H;
      const count = Math.floor((2 * Math.PI * R / 0.62) * density);
      for (let i = 0; i < count; i++) {
        const a = ((i + Math.random() * 0.5) / count) * Math.PI * 2;
        if (k < 3 && Math.abs(((a + Math.PI / 2) % (Math.PI * 2) + Math.PI * 2) % (Math.PI * 2) - Math.PI) > Math.PI - 0.2) continue; // 황제석 자리 비움
        if (Math.random() < 0.06) continue;
        const cx = Math.cos(a) * R, cz = Math.sin(a) * R, tx = -Math.sin(a), tz = Math.cos(a);
        const h = 0.95 + Math.random() * 0.3, w = h * 0.95;
        const corners = [[-w / 2, 0], [w / 2, 0], [w / 2, h], [-w / 2, h]];
        const ph = Math.random() * 10, variant = [0, 1, 3][Math.floor(Math.random() * 3)], rr = Math.random();
        const col = palette[Math.floor(Math.random() * palette.length)].clone().multiplyScalar(0.55 + Math.random() * 0.4);
        for (const [ox, oy] of corners) {
          pos.push(cx + tx * ox, y + oy, cz + tz * ox);
          data.push(ph, variant, rr, 0); tint.push(col.r, col.g, col.b); side.push(tx, 0, tz);
        }
        uv.push(0, 0, 1, 0, 1, 1, 0, 1);
        idx.push(v, v + 1, v + 2, v, v + 2, v + 3); v += 4;
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    g.setAttribute('aData', new THREE.Float32BufferAttribute(data, 4));
    g.setAttribute('aTint', new THREE.Float32BufferAttribute(tint, 3));
    g.setAttribute('aSide', new THREE.Float32BufferAttribute(side, 3));
    g.setIndex(idx);
    this.crowdU = { uMap: { value: atlas }, uTime: SHARED.uTime, uEx: { value: 0 }, uAmbient: SHARED.uAmbient, uSunColor: SHARED.uSunColor, uFogColor: SHARED.uFogColor, uFogDensity: SHARED.uFogDensity };
    const mesh = new THREE.Mesh(g, shaderMat(CROWD_VS, CROWD_FS, this.crowdU, { side: THREE.DoubleSide }));
    mesh.frustumCulled = false;
    this.group.add(mesh);
    this.crowdCount = v / 4;
  }

  _banners() {
    const geos = [], phases = [], modes = [];
    const add = (geo, phase, mode) => { const n = geo.attributes.position.count; geos.push(geo); for (let i = 0; i < n; i++) { phases.push(phase); modes.push(mode); } };
    // 포디움 벽에 늘어진 휘장
    const n = 14;
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 + 0.11;
      if (Math.abs(Math.sin(a)) > 0.97) continue; // 문 위 제외
      const pg = new THREE.PlaneGeometry(1.25, 2.5, 6, 12); pg.translate(0, -1.25, 0);
      const m = new THREE.Matrix4().makeRotationY(-a - Math.PI / 2);
      m.setPosition(Math.cos(a) * (R_ARENA - 0.22), H_PODIUM + 0.05, Math.sin(a) * (R_ARENA - 0.22));
      pg.applyMatrix4(m); add(pg, Math.random() * 6, 0);
    }
    // 다락 꼭대기의 깃발
    const R = this.arcade.R, top = this.arcade.baseY + this.arcade.H * this.arcade.levels + 2.2;
    const poles = [];
    for (let i = 0; i < 16; i++) {
      const a = (i / 16) * Math.PI * 2 + 0.2;
      const x = Math.cos(a) * (R - 0.4), z = Math.sin(a) * (R - 0.4);
      const fg = new THREE.PlaneGeometry(2.2, 1.3, 10, 5); fg.translate(1.1, 0, 0);
      const m = new THREE.Matrix4().makeRotationY(-a + 0.6); m.setPosition(x, top + 3.2, z);
      fg.applyMatrix4(m); add(fg, Math.random() * 6, 1);
      const pg = new THREE.CylinderGeometry(0.05, 0.05, 4.4, 5); pg.translate(x, top + 2.2, z); poles.push(pg);
    }
    const geo = mergeGeos(geos);
    geo.setAttribute('aPhase', new THREE.Float32BufferAttribute(phases, 1));
    geo.setAttribute('aMode', new THREE.Float32BufferAttribute(modes, 1));
    this.bannerU = {
      uMap: { value: genBanner('#8c1616', '#d9b24c') }, uTime: SHARED.uTime, uAmbient: SHARED.uAmbient, uSunColor: SHARED.uSunColor,
      uSunDir: SHARED.uSunDir, uFogColor: SHARED.uFogColor, uFogDensity: SHARED.uFogDensity,
    };
    const mesh = new THREE.Mesh(geo, shaderMat(BANNER_VS, BANNER_FS, this.bannerU, { side: THREE.DoubleSide }));
    mesh.frustumCulled = false; this.group.add(mesh);
    this.group.add(new THREE.Mesh(mergeGeos(poles), this.lib.M.darkIron));
  }

  _fire(M, dot) {
    // 화로 2개(적 뒤편) + 벽 횃불
    const centers = [], sizes = [], seeds = [];
    const emb = [], embD = [];
    const iron = M.darkIron;
    const addFlame = (x, y, z, w, h, s) => {
      centers.push([x, y, z]); sizes.push([w, h]); seeds.push(s);
      const n = Math.round(10 * w);
      for (let i = 0; i < n; i++) { emb.push(x + (Math.random() - 0.5) * w * 0.4, y + h * 0.3, z + (Math.random() - 0.5) * w * 0.4); embD.push(Math.random(), Math.random() * 1.2, Math.random(), Math.random()); }
    };
    this.lightSpots = [];
    const brazier = (x, z) => {
      const g = new THREE.Group();
      for (let i = 0; i < 3; i++) {
        const a = (i / 3) * Math.PI * 2, leg = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.03, 1.25, 6), iron);
        leg.position.set(Math.cos(a) * 0.22, 0.6, Math.sin(a) * 0.22); leg.rotation.set(Math.sin(a) * 0.28, 0, -Math.cos(a) * 0.28); leg.castShadow = true; g.add(leg);
      }
      const pts = [[0.05, 0], [0.32, 0.05], [0.46, 0.2], [0.5, 0.32], [0.47, 0.34]].map(([r, y]) => new THREE.Vector2(r, y));
      const bowl = new THREE.Mesh(new THREE.LatheGeometry(pts, 20), iron); bowl.position.y = 1.08; bowl.castShadow = true; g.add(bowl);
      const coal = new THREE.Mesh(new THREE.CircleGeometry(0.44, 16), new THREE.MeshStandardMaterial({ color: 0x220a04, emissive: 0xff4a10, emissiveIntensity: 2.2, roughness: 1 }));
      coal.rotation.x = -Math.PI / 2; coal.position.y = 1.36; g.add(coal);
      g.position.set(x, 0, z); this.group.add(g);
      addFlame(x, 1.32, z, 0.95, 1.55, Math.random());
      this.lightSpots.push({ pos: new THREE.Vector3(x, 1.95, z), base: 55, big: true });
    };
    brazier(-4.4, -8.8); brazier(4.4, -8.8);
    const wallTorch = (a) => {
      const R = R_ARENA - 0.32, x = Math.cos(a) * R, z = Math.sin(a) * R;
      const g = new THREE.Group();
      const arm = new THREE.Mesh(new THREE.BoxGeometry(0.08, 0.08, 0.5), iron); arm.position.set(0, 0, 0.18); g.add(arm);
      const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.08, 0.22, 10), iron); cup.position.set(0, 0.1, 0.42); g.add(cup);
      g.position.set(x, 2.85, z); g.lookAt(0, 2.85, 0); this.group.add(g);
      const fx = x - Math.cos(a) * 0.42, fz = z - Math.sin(a) * 0.42;
      addFlame(fx, 3.0, fz, 0.5, 0.9, Math.random());
      this.lightSpots.push({ pos: new THREE.Vector3(fx, 3.4, fz), base: 26, big: false });
    };
    const torchAngles = [-Math.PI / 2 - 0.42, -Math.PI / 2 + 0.42, -Math.PI / 2 - 1.0, -Math.PI / 2 + 1.0, 0.25, Math.PI - 0.25, Math.PI / 2 - 0.5, Math.PI / 2 + 0.5];
    torchAngles.forEach(wallTorch);
    // 아케이드 내부 불빛
    const { R, baseY, N } = this.arcade;
    for (let k = 0; k < N; k += 3) {
      const a = (k / N) * Math.PI * 2;
      addFlame(Math.cos(a) * (R + 1.2), baseY + 1.0, Math.sin(a) * (R + 1.2), 0.5, 0.8, Math.random());
    }
    // 병합 빌보드
    const pos = [], uv = [], aC = [], aS = [], aSeed = [], idx = [];
    centers.forEach((c, i) => {
      const b = i * 4;
      for (const [x, y] of [[-0.5, 0], [0.5, 0], [0.5, 1], [-0.5, 1]]) { pos.push(x, y, 0); aC.push(...c); aS.push(...sizes[i]); aSeed.push(seeds[i]); }
      uv.push(0, 0, 1, 0, 1, 1, 0, 1); idx.push(b, b + 1, b + 2, b, b + 2, b + 3);
    });
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2));
    g.setAttribute('aCenter', new THREE.Float32BufferAttribute(aC, 3));
    g.setAttribute('aSize', new THREE.Float32BufferAttribute(aS, 2));
    g.setAttribute('aSeed', new THREE.Float32BufferAttribute(aSeed, 1));
    g.setIndex(idx);
    this.flameU = { uTime: SHARED.uTime, uIntensity: { value: 3.2 } };
    const flames = new THREE.Mesh(g, shaderMat(FLAME_VS, FLAME_FS, this.flameU, { transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    flames.frustumCulled = false; flames.renderOrder = 10;
    this.group.add(flames);
    // 불씨
    const eg = new THREE.BufferGeometry();
    eg.setAttribute('position', new THREE.Float32BufferAttribute(new Array(emb.length).fill(0), 3));
    eg.setAttribute('aBase', new THREE.Float32BufferAttribute(emb, 3));
    eg.setAttribute('aD', new THREE.Float32BufferAttribute(embD, 4));
    this.emberU = { uTime: SHARED.uTime, uPixel: SHARED.uPixel, uMap: { value: dot }, uIntensity: { value: 3.0 } };
    const embers = new THREE.Points(eg, shaderMat(EMBER_VS, EMBER_FS, this.emberU, { transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    embers.frustumCulled = false; this.group.add(embers);
  }

  _dust(dot) {
    const n = this.q.dust, pos = new Float32Array(n * 3), d = new Float32Array(n * 4);
    const min = new THREE.Vector3(-9, 0.05, -14), size = new THREE.Vector3(18, 5.5, 17);
    for (let i = 0; i < n; i++) {
      pos[i * 3] = min.x + Math.random() * size.x; pos[i * 3 + 1] = min.y + Math.random() * size.y; pos[i * 3 + 2] = min.z + Math.random() * size.z;
      d[i * 4] = Math.random() * 10; d[i * 4 + 1] = 0.5 + Math.random(); d[i * 4 + 2] = 0.6 + Math.random() * 1.6; d[i * 4 + 3] = Math.random();
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    g.setAttribute('aD', new THREE.BufferAttribute(d, 4));
    this.dustU = {
      uTime: SHARED.uTime, uSize: { value: 2.2 }, uPixel: SHARED.uPixel, uBoxMin: { value: min }, uBoxSize: { value: size },
      uWind: { value: new THREE.Vector3(0.28, 0.02, 0.12) }, uMap: { value: dot }, uColor: { value: new THREE.Color(1.0, 0.85, 0.62) }, uOpacity: { value: 0.5 },
    };
    const pts = new THREE.Points(g, shaderMat(DUST_VS, DUST_FS, this.dustU, { transparent: true, depthWrite: false, blending: THREE.AdditiveBlending }));
    pts.frustumCulled = false; this.group.add(pts);
  }

  _shafts() {
    this.shaftU = { uColor: { value: new THREE.Color(1, 0.85, 0.6) }, uOpacity: { value: 0.05 }, uTime: SHARED.uTime };
    const mat = shaderMat(SHAFT_VS, SHAFT_FS, this.shaftU, { transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide });
    this.shafts = new THREE.Group();
    for (let i = 0; i < 4; i++) {
      const p = new THREE.Mesh(new THREE.PlaneGeometry(1.4 + Math.random() * 1.6, 34), mat);
      p.userData.base = new THREE.Vector3(-6 + i * 4 + Math.random() * 2, 0, -6 - Math.random() * 6);
      this.shafts.add(p);
    }
    this.group.add(this.shafts);
  }

  _lights() {
    const scene = this.engine.scene;
    this.hemi = new THREE.HemisphereLight(0xbcd2ff, 0x8a6a48, 0.7);
    scene.add(this.hemi);
    const sun = this.sun = new THREE.DirectionalLight(0xffffff, 3);
    sun.castShadow = true;
    sun.shadow.mapSize.set(this.q.shadow, this.q.shadow);
    const sc = sun.shadow.camera; sc.left = -5.5; sc.right = 5.5; sc.top = 5.5; sc.bottom = -5.5; sc.near = 1; sc.far = 80;
    sc.updateProjectionMatrix();
    sun.shadow.bias = -0.0004; sun.shadow.normalBias = 0.025;
    sun.target.position.set(0, 0, -1.3);
    scene.add(sun); scene.add(sun.target);
    // 가까운 순서대로 포인트 라이트 배정
    const spots = this.lightSpots.slice().sort((a, b) => a.pos.distanceTo(new THREE.Vector3(0, 1, -2)) - b.pos.distanceTo(new THREE.Vector3(0, 1, -2)));
    for (let i = 0; i < Math.min(this.q.lights, spots.length); i++) {
      const L = new THREE.PointLight(0xff8a3c, spots[i].base, 32, 2);
      L.position.copy(spots[i].pos);
      L.userData = { base: spots[i].base, seed: Math.random() * 100, origin: spots[i].pos.clone() };
      scene.add(L); this.torchLights.push(L);
    }
  }

  setLighting(L) {
    const scene = this.engine.scene;
    const sd = new THREE.Vector3(...L.sunDir).normalize();
    SHARED.uSunDir.value.copy(sd);
    this.sun.color.set(L.sun); this.sun.intensity = L.sunI;
    this.sun.position.copy(this.sun.target.position).addScaledVector(sd, 40);
    this.hemi.color.set(L.hemiSky); this.hemi.groundColor.set(L.hemiGround); this.hemi.intensity = L.hemiI;
    scene.fog = new THREE.FogExp2(L.fog, L.fogD * 1.8);
    SHARED.uFogColor.value.set(L.fog); SHARED.uFogDensity.value = L.fogD * 1.8;
    SHARED.uSunColor.value.set(L.sun).multiplyScalar(L.sunI * 0.35);
    SHARED.uAmbient.value.set(L.hemiSky).multiplyScalar(L.hemiI * 0.55);
    this.skyU.uTop.value.set(L.skyTop); this.skyU.uHor.value.set(L.skyHor); this.skyU.uGlow.value.set(L.glow);
    this.skyU.uStars.value = L.stars;
    this.skyU.uSunSize.value = L.stars > 0.5 ? 0.99965 : 0.9993;
    this.torchK = L.torch;
    this.flameU.uIntensity.value = 2.4 + L.torch * 1.2;
    this.emberU.uIntensity.value = 1.5 + L.torch * 1.5;
    this.dustU.uOpacity.value = 0.32 * L.dust;
    this.dustU.uColor.value.set(L.sun).lerp(new THREE.Color(1, 0.9, 0.75), 0.4);
    this.shafts.visible = L.stars < 0.5 && sd.y < 0.7;
    this.shaftU.uColor.value.set(L.sun);
    this.shaftU.uOpacity.value = L.stars > 0 ? 0.035 : 0.055;
    const toCam = new THREE.Vector3(0, 0, 1), zA = new THREE.Vector3(), xA = new THREE.Vector3(), m4 = new THREE.Matrix4();
    zA.copy(toCam).addScaledVector(sd, -toCam.dot(sd)).normalize();
    xA.crossVectors(sd, zA).normalize();
    m4.makeBasis(xA, sd, zA);
    this.shafts.children.forEach((p) => { p.quaternion.setFromRotationMatrix(m4); p.position.copy(p.userData.base).addScaledVector(sd, 17); });
    this.engine.renderer.toneMappingExposure = L.exp;
    this.engine.buildEnvironment(L);
  }

  setExcitement(v) { this.exciteTarget = Math.max(this.exciteTarget, Math.min(1, v)); }

  update(dt, t, camera) {
    SHARED.uTime.value = t;
    SHARED.uPixel.value = this.engine.dpr * (this.engine.h / 900) * 6.0;
    this.exciteTarget = Math.max(0, this.exciteTarget - dt * 0.12);
    this.excite += (this.exciteTarget - this.excite) * Math.min(1, dt * 3);
    this.crowdU.uEx.value = this.excite;
    const k = this.torchK ?? 1;
    for (const L of this.torchLights) {
      const s = L.userData.seed;
      const f = 0.78 + 0.14 * Math.sin(t * 9.1 + s) + 0.08 * Math.sin(t * 23.7 + s * 2.3) + 0.05 * Math.sin(t * 4.3 + s);
      L.intensity = L.userData.base * f * k;
      L.position.set(L.userData.origin.x + Math.sin(t * 7 + s) * 0.04, L.userData.origin.y + Math.sin(t * 5.3 + s) * 0.05, L.userData.origin.z);
    }
  }
}
