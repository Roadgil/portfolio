// ─────────────────────────────────────────────────────────────
//  절차적 PBR 텍스처 (Canvas로 Albedo / Normal / Roughness·Metalness 직접 생성)
//  + 머티리얼 라이브러리
// ─────────────────────────────────────────────────────────────
import * as THREE from 'three';

const yieldFrame = () => new Promise((r) => requestAnimationFrame(() => r()));
const sstep = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const clamp01 = (x) => (x < 0 ? 0 : x > 1 ? 1 : x);

// ── 주기적(타일링) 노이즈 ───────────────────────────────────
export class Noise {
  constructor(seed = 1) {
    let s = (seed * 2654435761) >>> 0 || 1;
    this.rnd = () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) / 4294967296);
    this.p = new Uint16Array(512); this.v = new Float32Array(256);
    const perm = Array.from({ length: 256 }, (_, i) => i);
    for (let i = 255; i > 0; i--) { const j = Math.floor(this.rnd() * (i + 1)); [perm[i], perm[j]] = [perm[j], perm[i]]; }
    for (let i = 0; i < 512; i++) this.p[i] = perm[i & 255];
    for (let i = 0; i < 256; i++) this.v[i] = this.rnd();
    this.cellOut = { f1: 0, f2: 0, id: 0 };
  }
  n(x, y, P) {
    const xi = Math.floor(x), yi = Math.floor(y), xf = x - xi, yf = y - yi;
    const x0 = ((xi % P) + P) % P, y0 = ((yi % P) + P) % P, x1 = (x0 + 1) % P, y1 = (y0 + 1) % P;
    const p = this.p, v = this.v;
    const a = v[p[p[x0] + y0]], b = v[p[p[x1] + y0]], c = v[p[p[x0] + y1]], d = v[p[p[x1] + y1]];
    const u = xf * xf * (3 - 2 * xf), w = yf * yf * (3 - 2 * yf);
    return a + (b - a) * u + (c - a) * w + (a - b - c + d) * u * w;
  }
  fbm(x, y, P, oct = 4, gain = 0.5) {
    let s = 0, a = 1, f = 1, norm = 0;
    for (let i = 0; i < oct; i++) { s += this.n(x * f, y * f, P * f) * a; norm += a; a *= gain; f *= 2; }
    return s / norm;
  }
  cell(x, y, N) {
    const xi = Math.floor(x), yi = Math.floor(y);
    let f1 = 9, f2 = 9, id = 0;
    for (let j = -1; j <= 1; j++) for (let i = -1; i <= 1; i++) {
      const cx = xi + i, cy = yi + j;
      const wx = ((cx % N) + N) % N, wy = ((cy % N) + N) % N;
      const h = this.p[this.p[wx & 255] + (wy & 255)];
      const dx = cx + this.v[h] - x, dy = cy + this.v[(h * 7 + 13) & 255] - y;
      const d = dx * dx + dy * dy;
      if (d < f1) { f2 = f1; f1 = d; id = h; } else if (d < f2) f2 = d;
    }
    const o = this.cellOut; o.f1 = Math.sqrt(f1); o.f2 = Math.sqrt(f2); o.id = id; return o;
  }
  hash(x, y) { return this.v[this.p[this.p[x & 255] + (y & 255)]]; }
}

// ── 캔버스 유틸 ─────────────────────────────────────────────
export function canvas(w, h) { const c = document.createElement('canvas'); c.width = w; c.height = h; return c; }
let ANISO = 4;
function tex(cv, srgb, rep = 1) {
  const t = new THREE.CanvasTexture(cv);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  if (srgb) t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = ANISO;
  t.repeat.set(rep, rep);
  t.needsUpdate = true;
  return t;
}
function putRGBA(S, H, data) { const c = canvas(S, H); const ctx = c.getContext('2d'); const img = ctx.createImageData(S, H); img.data.set(data); ctx.putImageData(img, 0, 0); return c; }

// 높이맵 → 노멀맵 (랩어라운드 중앙차분)
function normalFromHeight(h, W, H, strength, wrap = true) {
  const out = new Uint8ClampedArray(W * H * 4);
  for (let y = 0; y < H; y++) {
    const ym = wrap ? (y - 1 + H) % H : Math.max(0, y - 1), yp = wrap ? (y + 1) % H : Math.min(H - 1, y + 1);
    for (let x = 0; x < W; x++) {
      const xm = wrap ? (x - 1 + W) % W : Math.max(0, x - 1), xp = wrap ? (x + 1) % W : Math.min(W - 1, x + 1);
      const dx = (h[y * W + xp] - h[y * W + xm]) * strength;
      const dy = (h[yp * W + x] - h[ym * W + x]) * strength;
      let nx = -dx, ny = dy, nz = 1;
      const l = 1 / Math.sqrt(nx * nx + ny * ny + nz * nz);
      const i = (y * W + x) * 4;
      out[i] = (nx * l * 0.5 + 0.5) * 255; out[i + 1] = (ny * l * 0.5 + 0.5) * 255; out[i + 2] = (nz * l * 0.5 + 0.5) * 255; out[i + 3] = 255;
    }
  }
  return out;
}
function ormFrom(rough, metal, W, H) {
  const out = new Uint8ClampedArray(W * H * 4);
  for (let i = 0, j = 0; i < W * H; i++, j += 4) {
    out[j] = 255; out[j + 1] = clamp01(rough[i]) * 255; out[j + 2] = clamp01(metal ? metal[i] : 0) * 255; out[j + 3] = 255;
  }
  return out;
}
function finish(W, H, alb, h, rough, metal, nStrength, rep = 1, wrap = true) {
  return {
    map: tex(putRGBA(W, H, alb), true, rep),
    normalMap: tex(putRGBA(W, H, normalFromHeight(h, W, H, nStrength, wrap)), false, rep),
    orm: tex(putRGBA(W, H, ormFrom(rough, metal, W, H)), false, rep),
  };
}
// 타일링되는 스크래치 마스크
function scratchMask(S, n, count, maxLen, seed = 1) {
  const c = canvas(S, S), ctx = c.getContext('2d');
  ctx.fillStyle = '#000'; ctx.fillRect(0, 0, S, S); ctx.lineCap = 'round';
  for (let i = 0; i < count; i++) {
    const x = n.rnd() * S, y = n.rnd() * S, a = n.rnd() * Math.PI * 2, l = (0.2 + n.rnd()) * maxLen;
    ctx.strokeStyle = `rgba(255,255,255,${0.15 + n.rnd() * 0.45})`;
    ctx.lineWidth = 0.6 + n.rnd() * 1.4 * (S / 512);
    for (let ox = -S; ox <= S; ox += S) for (let oy = -S; oy <= S; oy += S) {
      ctx.beginPath(); ctx.moveTo(x + ox, y + oy);
      ctx.quadraticCurveTo(x + ox + Math.cos(a + 0.2) * l * 0.5, y + oy + Math.sin(a + 0.2) * l * 0.5, x + ox + Math.cos(a) * l, y + oy + Math.sin(a) * l);
      ctx.stroke();
    }
  }
  const d = ctx.getImageData(0, 0, S, S).data, m = new Float32Array(S * S);
  for (let i = 0; i < S * S; i++) m[i] = d[i * 4] / 255;
  return m;
}

// ── 개별 재질 생성기 ────────────────────────────────────────
function genSand(S) {
  const n = new Noise(11), N = S * S;
  const alb = new Uint8ClampedArray(N * 4), h = new Float32Array(N), r = new Float32Array(N);
  for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) {
    const u = x / S, v = y / S, i = y * S + x;
    const big = n.fbm(u * 4, v * 4, 4, 3);
    const mid = n.fbm(u * 16, v * 16, 16, 2);
    const rip = Math.sin((u * 14 + v * 6) * 6.2832 + n.fbm(u * 8, v * 8, 8, 2) * 5) * 0.5 + 0.5;
    const c = n.cell(u * 28, v * 28, 28);
    const peb = c.f1 < 0.2 && n.v[c.id] > 0.6 ? 1 - c.f1 / 0.2 : 0;
    const grain = n.hash(x, y);
    const H = big * 0.4 + mid * 0.25 + rip * 0.14 * (0.4 + big) + grain * 0.06 + peb * 0.45;
    h[i] = H;
    const shade = 0.78 + big * 0.32 + (mid - 0.5) * 0.12 + (grain - 0.5) * 0.08;
    const stain = sstep(0.62, 0.8, n.fbm(u * 6 + 3, v * 6, 6, 3));
    let R = 196 * shade, G = 162 * shade, B = 116 * shade;
    R = R * (1 - stain * 0.28); G = G * (1 - stain * 0.32); B = B * (1 - stain * 0.3);
    if (peb > 0) { const pc = 0.7 + n.v[(c.id * 3) & 255] * 0.4; R = R * (1 - peb) + 150 * pc * peb; G = G * (1 - peb) + 138 * pc * peb; B = B * (1 - peb) + 120 * pc * peb; }
    alb[i * 4] = R; alb[i * 4 + 1] = G; alb[i * 4 + 2] = B; alb[i * 4 + 3] = 255;
    r[i] = 0.93 - peb * 0.35 - rip * 0.05 + stain * 0.04;
  }
  return finish(S, S, alb, h, r, null, S / 64, 1);
}

function genStone(S) {
  const n = new Noise(23), N = S * S;
  const alb = new Uint8ClampedArray(N * 4), h = new Float32Array(N), r = new Float32Array(N);
  const rows = 4, rowH = S / rows, rowsDef = [];
  for (let k = 0; k < rows; k++) {
    const cnt = 2 + Math.floor(n.rnd() * 2); const ws = []; let sum = 0;
    for (let j = 0; j < cnt; j++) { const w = 0.6 + n.rnd() * 0.8; ws.push(w); sum += w; }
    const cum = []; let acc = 0; for (const w of ws) { acc += (w / sum) * S; cum.push(acc); }
    rowsDef.push({ off: n.rnd() * S, cum, tints: ws.map(() => 0.86 + n.rnd() * 0.24) });
  }
  const mortar = Math.max(2, S / 256) * 1.6, bevel = S / 48;
  for (let y = 0; y < S; y++) {
    const row = rowsDef[Math.floor(y / rowH) % rows], ly = y % rowH;
    for (let x = 0; x < S; x++) {
      const i = y * S + x, u = x / S, v = y / S;
      const xs = ((x - row.off) % S + S) % S;
      let bi = 0; while (bi < row.cum.length - 1 && xs > row.cum[bi]) bi++;
      const left = bi === 0 ? 0 : row.cum[bi - 1], right = row.cum[bi];
      const ex = Math.min(xs - left, right - xs), ey = Math.min(ly, rowH - ly), e = Math.min(ex, ey);
      const pits = sstep(0.68, 0.8, n.n(u * 48, v * 12, 48)) * 0.6 + sstep(0.72, 0.85, n.n(u * 96 + 7, v * 24, 96)) * 0.4;
      const surf = n.fbm(u * 8, v * 8, 8, 4);
      const isM = e < mortar;
      const bev = isM ? 0 : sstep(mortar, mortar + bevel, e);
      h[i] = isM ? 0.05 + surf * 0.05 : bev * (0.75 + surf * 0.25) - pits * 0.18 + n.hash(x, y) * 0.02;
      const streak = n.fbm(u * 24, v * 3, 24, 3);
      const tint = row.tints[bi] * (0.9 + surf * 0.2) * (1 - sstep(0.55, 0.8, streak) * 0.25) * (1 - pits * 0.25);
      let R = 190 * tint, G = 174 * tint, B = 150 * tint;
      if (isM) { R = 118; G = 106; B = 92; }
      const moss = sstep(0.7, 0.85, n.fbm(u * 5 + 9, v * 5, 5, 3)) * (1 - v) * 0.35;
      R *= 1 - moss * 0.3; B *= 1 - moss * 0.4;
      alb[i * 4] = R; alb[i * 4 + 1] = G; alb[i * 4 + 2] = B; alb[i * 4 + 3] = 255;
      r[i] = isM ? 0.97 : 0.82 + surf * 0.1 + pits * 0.06;
    }
  }
  return finish(S, S, alb, h, r, null, S / 40, 1);
}

const METALS = {
  iron: { c: [148, 148, 154], r: 0.36, rust: 0.8 },
  steel: { c: [196, 198, 204], r: 0.2, rust: 0 },
  brass: { c: [208, 162, 78], r: 0.3, rust: 0.25 },
  gold: { c: [240, 194, 96], r: 0.2, rust: 0 },
  bronze: { c: [184, 122, 72], r: 0.34, rust: 0.4 },
  dark: { c: [70, 70, 76], r: 0.45, rust: 0.6 },
};
function genMetal(S, kind, seed) {
  const n = new Noise(seed), N = S * S, M = METALS[kind];
  const alb = new Uint8ClampedArray(N * 4), h = new Float32Array(N), r = new Float32Array(N), m = new Float32Array(N);
  const sc = scratchMask(S, n, Math.round(S * 0.28), S * 0.18, seed);
  for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) {
    const u = x / S, v = y / S, i = y * S + x;
    const c = n.cell(u * 10, v * 10, 10);
    const dimple = c.f1 * c.f1;
    const grime = sstep(0.56, 0.76, n.fbm(u * 6, v * 6, 6, 4));
    const rust = M.rust ? sstep(0.64, 0.82, n.fbm(u * 10 + 5, v * 10, 10, 4)) * M.rust : 0;
    const fine = n.fbm(u * 32, v * 32, 32, 2);
    const s = sc[i];
    h[i] = -dimple * 0.35 - s * 0.22 + rust * (n.hash(x, y) * 0.3 + 0.2) + fine * 0.05;
    const k = (0.88 + fine * 0.18 + s * 0.12) * (1 - grime * 0.45);
    let R = M.c[0] * k, G = M.c[1] * k, B = M.c[2] * k;
    if (rust > 0) { R = R * (1 - rust) + 122 * rust; G = G * (1 - rust) + 62 * rust; B = B * (1 - rust) + 34 * rust; }
    alb[i * 4] = R; alb[i * 4 + 1] = G; alb[i * 4 + 2] = B; alb[i * 4 + 3] = 255;
    r[i] = M.r + grime * 0.32 + rust * 0.5 + s * 0.12 + (fine - 0.5) * 0.08;
    m[i] = 1 - rust * 0.75 - grime * 0.22;
  }
  return finish(S, S, alb, h, r, m, S / 90, 1);
}

function genLeather(S) {
  const n = new Noise(37), N = S * S;
  const alb = new Uint8ClampedArray(N * 4), h = new Float32Array(N), r = new Float32Array(N);
  for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) {
    const u = x / S, v = y / S, i = y * S + x;
    const c = n.cell(u * 36, v * 36, 36);
    const crease = sstep(0.0, 0.12, c.f2 - c.f1);
    const f = n.fbm(u * 8, v * 8, 8, 3);
    const wear = sstep(0.6, 0.8, n.fbm(u * 4 + 2, v * 4, 4, 3));
    h[i] = crease * 0.5 + f * 0.35;
    const k = (0.72 + f * 0.4) * (0.82 + crease * 0.18) * (1 + wear * 0.25);
    alb[i * 4] = 118 * k; alb[i * 4 + 1] = 74 * k; alb[i * 4 + 2] = 42 * k; alb[i * 4 + 3] = 255;
    r[i] = 0.55 + (1 - crease) * 0.22 - wear * 0.1;
  }
  return finish(S, S, alb, h, r, null, S / 80, 1);
}

function genCloth(S) {
  const n = new Noise(41), N = S * S, T = Math.max(32, S / 4);
  const alb = new Uint8ClampedArray(N * 4), h = new Float32Array(N), r = new Float32Array(N);
  for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) {
    const u = x / S, v = y / S, i = y * S + x;
    const cu = u * T, cv = v * T;
    const chk = (Math.floor(cu) + Math.floor(cv)) & 1;
    const warp = Math.sin((cu % 1) * Math.PI), weft = Math.sin((cv % 1) * Math.PI);
    const th = chk ? warp : weft;
    const slub = n.fbm(u * 16, v * 2, 16, 2);
    const dirt = sstep(0.55, 0.8, n.fbm(u * 5, v * 5, 5, 3));
    h[i] = th * 0.6 + slub * 0.3;
    const k = (0.72 + th * 0.22 + slub * 0.12) * (1 - dirt * 0.3);
    alb[i * 4] = 240 * k; alb[i * 4 + 1] = 236 * k; alb[i * 4 + 2] = 228 * k; alb[i * 4 + 3] = 255;
    r[i] = 0.9 + th * 0.05;
  }
  return finish(S, S, alb, h, r, null, S / 70, 1);
}

function genWood(S) {
  const n = new Noise(53), N = S * S;
  const alb = new Uint8ClampedArray(N * 4), h = new Float32Array(N), r = new Float32Array(N);
  for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) {
    const u = x / S, v = y / S, i = y * S + x;
    const g = Math.sin((u * 24 + n.fbm(u * 4, v * 16, 4, 3) * 4) * 6.2832) * 0.5 + 0.5;
    const fine = n.n(u * 128, v * 8, 128);
    const knot = sstep(0.82, 0.92, n.fbm(u * 6, v * 3, 6, 2));
    h[i] = g * 0.5 + fine * 0.3 - knot * 0.3;
    const k = 0.7 + g * 0.3 + fine * 0.1 - knot * 0.25;
    alb[i * 4] = 132 * k; alb[i * 4 + 1] = 90 * k; alb[i * 4 + 2] = 52 * k; alb[i * 4 + 3] = 255;
    r[i] = 0.68 + fine * 0.1;
  }
  return finish(S, S, alb, h, r, null, S / 100, 1);
}

function genSkin(S) {
  const n = new Noise(61), N = S * S;
  const alb = new Uint8ClampedArray(N * 4), h = new Float32Array(N), r = new Float32Array(N);
  for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) {
    const u = x / S, v = y / S, i = y * S + x;
    const pore = n.hash(x, y), f = n.fbm(u * 6, v * 6, 6, 4), blot = n.fbm(u * 20, v * 20, 20, 2);
    h[i] = pore * 0.12 + f * 0.25 + blot * 0.1;
    const k = 0.9 + (f - 0.5) * 0.14 + (blot - 0.5) * 0.06;
    alb[i * 4] = 250 * k; alb[i * 4 + 1] = 238 * k; alb[i * 4 + 2] = 230 * k; alb[i * 4 + 3] = 255;
    r[i] = 0.5 + pore * 0.12 + (1 - f) * 0.08;
  }
  return finish(S, S, alb, h, r, null, S / 128, 1);
}

// 근육 몸통 (Lathe UV: u=0.5가 정면, v가 높이)
function genTorso(W, H) {
  const c = canvas(W, H), ctx = c.getContext('2d');
  ctx.fillStyle = '#808080'; ctx.fillRect(0, 0, W, H);
  ctx.filter = `blur(${Math.round(W / 64)}px)`;
  const blob = (u, v, rx, ry, lv) => { ctx.fillStyle = `rgb(${lv},${lv},${lv})`; ctx.beginPath(); ctx.ellipse(u * W, (1 - v) * H, rx * W, ry * H, 0, 0, Math.PI * 2); ctx.fill(); };
  // 가슴(대흉근)
  blob(0.43, 0.76, 0.075, 0.09, 200); blob(0.57, 0.76, 0.075, 0.09, 200);
  // 복근 3단
  for (let k = 0; k < 3; k++) { blob(0.475, 0.56 - k * 0.1, 0.024, 0.04, 175); blob(0.525, 0.56 - k * 0.1, 0.024, 0.04, 175); }
  // 복사근, 등근육(광배근), 척추 홈
  blob(0.37, 0.42, 0.04, 0.14, 160); blob(0.63, 0.42, 0.04, 0.14, 160);
  blob(0.2, 0.7, 0.08, 0.16, 185); blob(0.8, 0.7, 0.08, 0.16, 185);
  ctx.fillStyle = 'rgb(70,70,70)'; ctx.fillRect(0, 0, W * 0.012, H); ctx.fillRect(W * 0.988, 0, W * 0.012, H);
  ctx.fillRect(W * 0.497, H * 0.2, W * 0.006, H * 0.42);
  blob(0.5, 0.3, 0.008, 0.012, 60); // 배꼽
  ctx.filter = 'none';
  const d = ctx.getImageData(0, 0, W, H).data, N = W * H;
  const h = new Float32Array(N), alb = new Uint8ClampedArray(N * 4), r = new Float32Array(N), n = new Noise(71);
  for (let i = 0; i < N; i++) {
    const x = i % W, y = (i / W) | 0;
    h[i] = d[i * 4] / 255 + n.hash(x, y) * 0.01;
    const ao = 0.82 + (d[i * 4] / 255) * 0.25;
    const f = n.fbm(x / W * 6, y / H * 6, 6, 3);
    const k = Math.min(1.05, ao * (0.94 + f * 0.08));
    alb[i * 4] = 250 * k; alb[i * 4 + 1] = 238 * k; alb[i * 4 + 2] = 230 * k; alb[i * 4 + 3] = 255;
    r[i] = 0.48 + (1 - d[i * 4] / 255) * 0.1;
  }
  return finish(W, H, alb, h, r, null, W / 26, 1, true);
}

function genFur(S) {
  const n = new Noise(83), N = S * S;
  const alb = new Uint8ClampedArray(N * 4), h = new Float32Array(N), r = new Float32Array(N);
  for (let y = 0; y < S; y++) for (let x = 0; x < S; x++) {
    const u = x / S, v = y / S, i = y * S + x;
    const s = n.n(u * 128 + n.fbm(u * 4, v * 4, 4, 2) * 6, v * 8, 128);
    const clump = n.fbm(u * 16, v * 4, 16, 2);
    h[i] = s * 0.7 + clump * 0.3;
    const k = 0.45 + s * 0.6 * (0.6 + clump * 0.5);
    alb[i * 4] = 120 * k; alb[i * 4 + 1] = 98 * k; alb[i * 4 + 2] = 76 * k; alb[i * 4 + 3] = 255;
    r[i] = 0.96;
  }
  return finish(S, S, alb, h, r, null, S / 50, 1);
}

// ── 그림 텍스처: 방패 문양, 깃발, 관중, 그릴, 파티클 ────────
function weather(ctx, W, H, n, amount) {
  for (let i = 0; i < 40 * amount; i++) {
    ctx.fillStyle = `rgba(${150 + n.rnd() * 40},${110 + n.rnd() * 30},${70 + n.rnd() * 20},${0.35 + n.rnd() * 0.4})`;
    const x = n.rnd() * W, y = n.rnd() * H, s = 2 + n.rnd() * 7;
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + s, y + s * 0.3); ctx.lineTo(x + s * 0.4, y + s); ctx.closePath(); ctx.fill();
  }
  ctx.lineCap = 'round';
  for (let i = 0; i < 60 * amount; i++) {
    ctx.strokeStyle = `rgba(30,20,10,${0.08 + n.rnd() * 0.18})`; ctx.lineWidth = 0.6 + n.rnd();
    const x = n.rnd() * W, y = n.rnd() * H, a = n.rnd() * 6.28, l = 6 + n.rnd() * 30;
    ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(x + Math.cos(a) * l, y + Math.sin(a) * l); ctx.stroke();
  }
  const g = ctx.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.3, W / 2, H / 2, Math.max(W, H) * 0.7);
  g.addColorStop(0, 'rgba(0,0,0,0)'); g.addColorStop(1, 'rgba(25,15,5,0.45)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
}
function bolt(ctx, x, y, ang, len, w) {
  ctx.save(); ctx.translate(x, y); ctx.rotate(ang);
  ctx.beginPath();
  ctx.moveTo(0, -w * 0.5); ctx.lineTo(len * 0.45, -w * 0.9); ctx.lineTo(len * 0.4, -w * 0.1); ctx.lineTo(len, -w * 0.25);
  ctx.lineTo(len * 0.55, w * 0.9); ctx.lineTo(len * 0.6, w * 0.15); ctx.lineTo(0, w * 0.5); ctx.closePath(); ctx.fill();
  ctx.restore();
}
function wing(ctx, x, y, dir, s) {
  for (let k = 0; k < 5; k++) {
    ctx.beginPath();
    ctx.ellipse(x + dir * (k * s * 0.16), y - k * s * 0.07, s * (0.5 - k * 0.06), s * 0.07, dir * (-0.35 - k * 0.12), 0, Math.PI * 2);
    ctx.fill();
  }
}
// 방패 앞면: 알베도 + 높이(금장 돋움) + 금속도(금박) 마스크
export function genShieldFace(style, colorA, colorB, seed = 3) {
  const round = style !== 'scutum';
  const W = 512, H = round ? 512 : 768;
  const c = canvas(W, H), ctx = c.getContext('2d'), n = new Noise(seed);
  const m = canvas(W, H), mx = m.getContext('2d');   // 금장 마스크
  ctx.fillStyle = colorA; ctx.fillRect(0, 0, W, H);
  for (let i = 0; i < 3000; i++) { ctx.fillStyle = `rgba(0,0,0,${n.rnd() * 0.05})`; ctx.fillRect(n.rnd() * W, n.rnd() * H, 2 + n.rnd() * 6, 1 + n.rnd() * 3); }
  mx.fillStyle = '#000'; mx.fillRect(0, 0, W, H);
  const draw = (fn) => { ctx.fillStyle = colorB; ctx.strokeStyle = colorB; fn(ctx); mx.fillStyle = '#fff'; mx.strokeStyle = '#fff'; fn(mx); };
  if (!round) {
    draw((g) => { g.lineWidth = 16; g.strokeRect(22, 22, W - 44, H - 44); g.lineWidth = 4; g.strokeRect(50, 50, W - 100, H - 100); });
    draw((g) => { for (let k = 0; k < 4; k++) bolt(g, W / 2, H / 2, k * Math.PI / 2 + Math.PI / 4, 190, 26); });
    draw((g) => { wing(g, W / 2 - 60, H / 2 - 120, -1, 150); wing(g, W / 2 + 60, H / 2 - 120, 1, 150); wing(g, W / 2 - 60, H / 2 + 150, -1, 130); wing(g, W / 2 + 60, H / 2 + 150, 1, 130); });
    draw((g) => { g.lineWidth = 10; g.beginPath(); g.arc(W / 2, H / 2, 92, 0, Math.PI * 2); g.stroke(); });
  } else {
    draw((g) => { g.lineWidth = 18; g.beginPath(); g.arc(W / 2, H / 2, W / 2 - 18, 0, Math.PI * 2); g.stroke(); g.lineWidth = 5; g.beginPath(); g.arc(W / 2, H / 2, W / 2 - 52, 0, Math.PI * 2); g.stroke(); });
    draw((g) => {
      for (let k = 0; k < 16; k++) {
        const a = k * Math.PI / 8; g.beginPath();
        g.moveTo(W / 2 + Math.cos(a - 0.09) * 90, H / 2 + Math.sin(a - 0.09) * 90);
        g.lineTo(W / 2 + Math.cos(a) * (k % 2 ? 175 : 200), H / 2 + Math.sin(a) * (k % 2 ? 175 : 200));
        g.lineTo(W / 2 + Math.cos(a + 0.09) * 90, H / 2 + Math.sin(a + 0.09) * 90); g.fill();
      }
    });
    draw((g) => { g.lineWidth = 8; g.beginPath(); g.arc(W / 2, H / 2, 86, 0, Math.PI * 2); g.stroke(); });
  }
  weather(ctx, W, H, n, 1.2);
  const md = mx.getImageData(0, 0, W, H).data, N = W * H;
  const h = new Float32Array(N), r = new Float32Array(N), mt = new Float32Array(N);
  for (let i = 0; i < N; i++) { const g = md[i * 4] / 255; h[i] = g * 0.6 + n.hash(i % W, (i / W) | 0) * 0.04; r[i] = 0.58 - g * 0.28; mt[i] = g * 0.85; }
  return {
    map: (() => { const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = ANISO; return t; })(),
    normalMap: (() => { const t = new THREE.CanvasTexture(putRGBA(W, H, normalFromHeight(h, W, H, 6, false))); t.anisotropy = ANISO; return t; })(),
    orm: (() => { const t = new THREE.CanvasTexture(putRGBA(W, H, ormFrom(r, mt, W, H))); return t; })(),
  };
}

export function genBanner(color, gold) {
  const W = 256, H = 512, c = canvas(W, H), ctx = c.getContext('2d'), n = new Noise(97);
  ctx.fillStyle = color; ctx.fillRect(0, 0, W, H);
  for (let i = 0; i < 1500; i++) { ctx.fillStyle = `rgba(0,0,0,${n.rnd() * 0.06})`; ctx.fillRect(n.rnd() * W, n.rnd() * H, 1 + n.rnd() * 3, 1 + n.rnd() * 8); }
  ctx.strokeStyle = gold; ctx.fillStyle = gold;
  ctx.lineWidth = 10; ctx.strokeRect(14, 14, W - 28, H - 70);
  ctx.save(); ctx.translate(W / 2, H * 0.4);
  for (let k = 0; k < 22; k++) {
    const a = -Math.PI * 0.5 + (k / 21) * Math.PI * 1.6 - Math.PI * 0.3;
    for (const side of [-1, 1]) {
      ctx.save(); ctx.rotate(side * a); ctx.translate(0, -78);
      ctx.beginPath(); ctx.ellipse(10 * side, 0, 12, 5, side * 0.6, 0, Math.PI * 2); ctx.fill(); ctx.restore();
    }
  }
  ctx.font = 'bold 54px Georgia, "Times New Roman", serif'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText('SPQR', 0, 4);
  ctx.restore();
  // 하단 술 장식 (알파)
  ctx.globalCompositeOperation = 'destination-out';
  for (let x = 0; x < W; x += 24) { ctx.beginPath(); ctx.moveTo(x, H); ctx.lineTo(x + 12, H - 40); ctx.lineTo(x + 24, H); ctx.closePath(); ctx.fill(); }
  ctx.globalCompositeOperation = 'source-over';
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = ANISO;
  return t;
}

export function genCrowdAtlas() {
  const F = 128, c = canvas(F * 4, F), ctx = c.getContext('2d');
  const person = (ox, armL, armR, seated) => {
    ctx.save(); ctx.translate(ox + F / 2, 0);
    const g = ctx.createLinearGradient(0, 10, 0, F); g.addColorStop(0, '#fff'); g.addColorStop(1, '#9a9a9a');
    ctx.fillStyle = g; ctx.strokeStyle = g; ctx.lineCap = 'round';
    const top = seated ? 30 : 16;
    ctx.beginPath(); ctx.arc(0, top + 12, 11, 0, Math.PI * 2); ctx.fill();          // 머리
    ctx.beginPath(); ctx.moveTo(-20, top + 30); ctx.quadraticCurveTo(0, top + 22, 20, top + 30);
    ctx.lineTo(24, F); ctx.lineTo(-24, F); ctx.closePath(); ctx.fill();          // 몸통(토가)
    ctx.lineWidth = 9;
    const arm = (side, up) => {
      ctx.beginPath(); ctx.moveTo(side * 17, top + 32);
      if (up > 0.5) ctx.quadraticCurveTo(side * 30, top + 10, side * 24 * (1.2 - up * 0.3), top - 18 * up);
      else ctx.quadraticCurveTo(side * 26, top + 52, side * 20, top + 70);
      ctx.stroke();
    };
    arm(-1, armL); arm(1, armR);
    ctx.restore();
  };
  person(0, 0, 0, false); person(F, 0, 1, false); person(F * 2, 1, 1, false); person(F * 3, 0, 0, true);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = ANISO;
  return t;
}

function genGrille() {
  const W = 256, H = 128, c = canvas(W, H), ctx = c.getContext('2d');
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, W, H);
  ctx.globalCompositeOperation = 'destination-out';
  for (let y = 10; y < H - 6; y += 13) for (let x = 8 + ((y / 13) % 2) * 6; x < W - 6; x += 12) { ctx.beginPath(); ctx.arc(x, y, 4.2, 0, Math.PI * 2); ctx.fill(); }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping;
  return t;
}
function genDot() {
  const S = 64, c = canvas(S, S), ctx = c.getContext('2d');
  const g = ctx.createRadialGradient(S / 2, S / 2, 0, S / 2, S / 2, S / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)'); g.addColorStop(0.35, 'rgba(255,255,255,0.55)'); g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g; ctx.fillRect(0, 0, S, S);
  return new THREE.CanvasTexture(c);
}

// ── 머티리얼 라이브러리 ─────────────────────────────────────
export async function buildLibrary(renderer, size, progress = () => {}) {
  ANISO = Math.min(8, renderer.capabilities.getMaxAnisotropy ? renderer.capabilities.getMaxAnisotropy() : 4);
  const S = size, s2 = Math.min(512, size);
  const T = {};
  const steps = [
    ['sand', () => genSand(S)], ['stone', () => genStone(S)],
    ['iron', () => genMetal(s2, 'iron', 101)], ['steel', () => genMetal(s2, 'steel', 103)],
    ['brass', () => genMetal(s2, 'brass', 107)], ['gold', () => genMetal(s2, 'gold', 109)],
    ['bronze', () => genMetal(s2, 'bronze', 113)], ['dark', () => genMetal(s2, 'dark', 127)],
    ['leather', () => genLeather(s2)], ['cloth', () => genCloth(s2)], ['wood', () => genWood(s2)],
    ['skin', () => genSkin(Math.min(256, s2))], ['torso', () => genTorso(s2, s2)], ['fur', () => genFur(s2)],
  ];
  for (let i = 0; i < steps.length; i++) {
    T[steps[i][0]] = steps[i][1]();
    progress((i + 1) / (steps.length + 2), steps[i][0]);
    await yieldFrame();
  }
  T.grille = genGrille(); T.dot = genDot(); T.crowd = genCrowdAtlas();
  progress(1, 'done');

  const std = (t, o = {}) => new THREE.MeshStandardMaterial({
    map: t.map, normalMap: t.normalMap, roughnessMap: t.orm, metalnessMap: o.metal ? t.orm : null,
    roughness: o.rough ?? 1, metalness: o.metal ? 1 : 0, color: o.color ?? 0xffffff,
    normalScale: new THREE.Vector2(o.ns ?? 1, o.ns ?? 1), envMapIntensity: o.env ?? 1, side: o.side ?? THREE.FrontSide,
  });
  const phys = (t, o = {}) => new THREE.MeshPhysicalMaterial({
    map: t.map, normalMap: t.normalMap, roughnessMap: t.orm, metalnessMap: t.orm, roughness: 1, metalness: 1,
    color: o.color ?? 0xffffff, clearcoat: o.cc ?? 0.35, clearcoatRoughness: 0.25, normalScale: new THREE.Vector2(o.ns ?? 1, o.ns ?? 1),
  });
  const M = {
    sand: std(T.sand, { ns: 1.3 }),
    stone: std(T.stone, { ns: 1.2 }),
    iron: std(T.iron, { metal: true }),
    steel: std(T.steel, { metal: true, ns: 0.5 }),
    brass: phys(T.brass, { cc: 0.25 }),
    gold: phys(T.gold, { cc: 0.5 }),
    bronze: std(T.bronze, { metal: true }),
    darkIron: std(T.dark, { metal: true }),
    leather: std(T.leather, { ns: 1.2 }),
    leatherDark: std(T.leather, { color: 0x6a4c3a, ns: 1.2 }),
    cloth: new THREE.MeshPhysicalMaterial({ map: T.cloth.map, normalMap: T.cloth.normalMap, roughnessMap: T.cloth.orm, roughness: 1, metalness: 0, sheen: 0.6, sheenRoughness: 0.8, sheenColor: new THREE.Color(0xffffff), side: THREE.DoubleSide }),
    wood: std(T.wood),
    skin: std(T.skin, { ns: 0.6 }),
    torso: std(T.torso, { ns: 1 }),
    fur: std(T.fur, { ns: 1.4, side: THREE.DoubleSide }),
    void: new THREE.MeshBasicMaterial({ color: 0x050403 }),
    grille: new THREE.MeshStandardMaterial({ map: T.iron.map, normalMap: T.iron.normalMap, roughnessMap: T.iron.orm, metalnessMap: T.iron.orm, roughness: 1, metalness: 1, alphaMap: T.grille, alphaTest: 0.5, side: THREE.DoubleSide }),
  };
  // 텍스처 반복 스케일을 달리한 변형
  const rep = (mat, r) => {
    const m = mat.clone();
    for (const k of ['map', 'normalMap', 'roughnessMap', 'metalnessMap']) if (m[k]) { m[k] = m[k].clone(); m[k].repeat.set(r, r); m[k].needsUpdate = true; }
    if (m.roughnessMap && mat.metalnessMap === mat.roughnessMap) m.metalnessMap = m.roughnessMap;
    return m;
  };
  return { T, M, rep };
}

// 개체별 색상 변형 (텍스처 공유)
export function tinted(mat, color, extra = {}) {
  const m = mat.clone();
  m.color = new THREE.Color(color);
  Object.assign(m, extra);
  return m;
}
