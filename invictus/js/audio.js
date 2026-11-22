// ─────────────────────────────────────────────────────────────
//  Web Audio 다층 신디사이저 + Android 햅틱
//  모든 효과음은 샘플 없이 오실레이터/노이즈/필터로 실시간 합성
// ─────────────────────────────────────────────────────────────
const rnd = (a, b) => a + Math.random() * (b - a);

export class AudioFX {
  constructor() {
    this.ctx = null;
    this.on = true;
    this.k = 1;            // 슬로우모션 피치 계수
    this.crowdEx = 0;
  }

  unlock() {
    if (!this.ctx) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      try { this.ctx = new AC({ latencyHint: 'interactive' }); } catch (e) { return; }
      this._build();
    }
    if (this.ctx.state === 'suspended' && this.on) this.ctx.resume().catch(() => {});
  }
  get ready() { return !!this.ctx && this.ctx.state === 'running'; }

  setEnabled(on) {
    this.on = on;
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.master.gain.cancelScheduledValues(t);
    this.master.gain.setTargetAtTime(on ? 0.9 : 0, t, 0.05);
    if (on && this.ctx.state === 'suspended') this.ctx.resume().catch(() => {});
  }

  _build() {
    const c = this.ctx;
    this.master = c.createGain(); this.master.gain.value = this.on ? 0.9 : 0;
    this.comp = c.createDynamicsCompressor();
    this.comp.threshold.value = -16; this.comp.knee.value = 14; this.comp.ratio.value = 4;
    this.comp.attack.value = 0.003; this.comp.release.value = 0.22;
    this.lp = c.createBiquadFilter(); this.lp.type = 'lowpass'; this.lp.frequency.value = 18000; this.lp.Q.value = 0.5;
    this.sfx = c.createGain(); this.sfx.gain.value = 1;
    this.amb = c.createGain(); this.amb.gain.value = 0.05;
    this.reverb = c.createConvolver(); this.reverb.buffer = this._impulse(2.4, 2.6);
    this.revOut = c.createGain(); this.revOut.gain.value = 0.55;
    this.sfx.connect(this.lp); this.amb.connect(this.lp);
    this.reverb.connect(this.revOut); this.revOut.connect(this.lp);
    this.lp.connect(this.comp); this.comp.connect(this.master); this.master.connect(c.destination);

    const sr = c.sampleRate, len = sr * 2;
    this.noiseBuf = c.createBuffer(1, len, sr);
    const d = this.noiseBuf.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    this.curve = new Float32Array(1024);
    for (let i = 0; i < 1024; i++) { const x = i / 511.5 - 1; this.curve[i] = Math.tanh(x * 4.5); }
    this._startCrowd();
  }

  _impulse(sec, decay) {
    const c = this.ctx, len = Math.floor(c.sampleRate * sec), buf = c.createBuffer(2, len, c.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const d = buf.getChannelData(ch);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, decay) * (i < 120 ? i / 120 : 1);
    }
    return buf;
  }

  // ── 빌딩 블록 ──────────────────────────────────────────────
  _bus(pan = 0, rev = 0.15) {
    const c = this.ctx, g = c.createGain();
    let node = g;
    if (pan && c.createStereoPanner) { const p = c.createStereoPanner(); p.pan.value = Math.max(-1, Math.min(1, pan)); g.connect(p); node = p; }
    node.connect(this.sfx);
    if (rev > 0) { const s = c.createGain(); s.gain.value = rev; node.connect(s); s.connect(this.reverb); }
    return g;
  }
  _ns(t, dur) {
    const s = this.ctx.createBufferSource();
    s.buffer = this.noiseBuf; s.loop = true;
    s.start(t, Math.random() * 1.8); s.stop(t + dur + 0.05);
    return s;
  }
  _env(g, t, peak, a, d) {
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(Math.max(0.0002, peak), t + Math.max(0.001, a));
    g.gain.exponentialRampToValueAtTime(0.0001, t + a + d);
  }
  _osc(type, f0, f1, t, a, d, peak, out, glide) {
    const c = this.ctx, o = c.createOscillator(), g = c.createGain();
    o.type = type; o.frequency.setValueAtTime(Math.max(1, f0), t);
    if (f1 && f1 !== f0) o.frequency.exponentialRampToValueAtTime(Math.max(1, f1), t + (glide || a + d));
    this._env(g, t, peak, a, d);
    o.connect(g); g.connect(out); o.start(t); o.stop(t + a + d + 0.05);
    return o;
  }
  _noise(t, dur, type, freq, q, a, peak, out) {
    const c = this.ctx, n = this._ns(t, a + dur), f = c.createBiquadFilter(), g = c.createGain();
    f.type = type; f.frequency.value = freq; f.Q.value = q;
    this._env(g, t, peak, a, dur);
    n.connect(f); f.connect(g); g.connect(out);
    return f;
  }
  _go(fn) { if (!this.ctx || !this.on) return; try { fn(this.ctx, this.ctx.currentTime, this.k); } catch (e) { /* 오디오 오류는 게임을 멈추지 않음 */ } }

  // ── 슬로우모션 / 관중 ──────────────────────────────────────
  setSlow(scale) {
    this.k = scale < 0.9 ? 0.62 + 0.38 * scale : 1;
    if (!this.ctx) return;
    const t = this.ctx.currentTime;
    this.lp.frequency.cancelScheduledValues(t);
    this.lp.frequency.setTargetAtTime(scale < 0.9 ? 900 + 4000 * scale : 18000, t, 0.08);
  }
  _startCrowd() {
    const c = this.ctx, src = c.createBufferSource();
    src.buffer = this.noiseBuf; src.loop = true;
    const bands = [[380, 0.7, 0.9], [980, 1.1, 0.6], [2300, 1.8, 0.25]];
    bands.forEach(([f, q, lv], i) => {
      const bp = c.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = f; bp.Q.value = q;
      const g = c.createGain(); g.gain.value = lv;
      const lfo = c.createOscillator(); lfo.frequency.value = 0.07 + i * 0.05;
      const lg = c.createGain(); lg.gain.value = lv * 0.35;
      lfo.connect(lg); lg.connect(g.gain); lfo.start();
      src.connect(bp); bp.connect(g); g.connect(this.amb);
    });
    src.start();
  }
  setCrowd(ex) {
    this.crowdEx = ex;
    if (!this.ctx) return;
    this.amb.gain.setTargetAtTime(0.035 + 0.09 * Math.min(1, ex), this.ctx.currentTime, 0.4);
  }

  // ── 무기/전투 ──────────────────────────────────────────────
  whoosh(p = 1, weight = 1, dirX = 0) {
    this._go((c, t, k) => {
      const dur = (0.15 + 0.12 * weight) / k;
      const out = this._bus(0, 0.06);
      let tail = out;
      if (c.createStereoPanner) {
        const pn = c.createStereoPanner(); pn.connect(out); tail = pn;
        pn.pan.setValueAtTime(-0.7 * dirX, t); pn.pan.linearRampToValueAtTime(0.7 * dirX, t + dur);
      }
      const n = this._ns(t, dur), bp = c.createBiquadFilter(), g = c.createGain();
      bp.type = 'bandpass'; bp.Q.value = 1.3;
      const lo = 360 / weight * k, hi = 2700 / weight * k;
      bp.frequency.setValueAtTime(lo, t);
      bp.frequency.exponentialRampToValueAtTime(hi, t + dur * 0.45);
      bp.frequency.exponentialRampToValueAtTime(lo * 1.5, t + dur);
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(0.6 * p, t + dur * 0.42);
      g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      n.connect(bp); bp.connect(g); g.connect(tail);
      this._noise(t + dur * 0.15, dur * 0.4, 'highpass', 5200 * k, 0.7, dur * 0.2, 0.1 * p, tail);
    });
  }
  clang(p = 1, pitch = 1) {
    this._go((c, t, k) => {
      const out = this._bus(rnd(-0.25, 0.25), 0.5);
      const f0 = 560 * pitch * k * rnd(0.95, 1.05);
      [1, 2.41, 3.93, 5.38, 6.99, 8.61, 11.2].forEach((r, i) => {
        const dec = (1.45 / (1 + i * 0.42)) / k;
        this._osc(i < 2 ? 'triangle' : 'sine', f0 * r * rnd(0.995, 1.005), 0, t, 0.002, dec, 0.3 * p / Math.pow(i + 1, 0.55), out);
      });
      this._noise(t, 0.05, 'highpass', 2400, 0.8, 0.002, 0.7 * p, out);
    });
  }
  shield(p = 1) {
    this._go((c, t, k) => {
      const out = this._bus(0, 0.22);
      this._osc('sine', 150 * k, 46 * k, t, 0.003, 0.24 / k, 0.95 * p, out, 0.16 / k);
      this._noise(t, 0.12 / k, 'bandpass', 320 * k, 3, 0.002, 0.8 * p, out);
      this._noise(t, 0.26 / k, 'lowpass', 1400 * k, 0.6, 0.004, 0.32 * p, out);
      this._osc('triangle', 830 * k, 0, t, 0.002, 0.2, 0.07 * p, out);
    });
  }
  hit(p = 1, crit = false) {
    this._go((c, t, k) => {
      const out = this._bus(rnd(-0.2, 0.2), 0.14);
      this._osc('sine', 115 * k, 40 * k, t, 0.002, 0.2 / k, 0.9 * p, out, 0.14 / k);
      const n = this._ns(t, 0.12), bp = c.createBiquadFilter(), ws = c.createWaveShaper(), g = c.createGain();
      bp.type = 'bandpass'; bp.frequency.value = 1100 * k; bp.Q.value = 0.9; ws.curve = this.curve;
      this._env(g, t, 0.45 * p, 0.002, 0.09 / k);
      n.connect(bp); bp.connect(ws); ws.connect(g); g.connect(out);
      this._noise(t, 0.04, 'highpass', 2600, 0.7, 0.001, 0.28 * p, out);
      if (crit) {
        this._osc('sine', 1760 * k, 0, t + 0.01, 0.002, 0.4 / k, 0.13 * p, out);
        this._noise(t, 0.16, 'bandpass', 6200 * k, 4, 0.002, 0.18 * p, out);
        this._osc('sine', 62 * k, 32 * k, t, 0.003, 0.4 / k, 0.7 * p, out);
      }
    });
  }
  armor(p = 1) { this.clang(0.45 * p, 0.55); this.hit(0.7 * p); }
  blocked(p = 1) {
    this._go((c, t, k) => {
      const out = this._bus(rnd(-0.2, 0.2), 0.25);
      this._osc('sine', 190 * k, 70 * k, t, 0.002, 0.18 / k, 0.7 * p, out, 0.12 / k);
      this._noise(t, 0.1, 'bandpass', 420 * k, 2.5, 0.002, 0.6 * p, out);
    });
    this.clang(0.28 * p, 0.8);
  }
  guardBreak(p = 1) {
    this._go((c, t, k) => {
      const out = this._bus(0, 0.35);
      this._noise(t, 0.08, 'highpass', 1200, 0.7, 0.001, 1.0 * p, out);
      for (let i = 0; i < 6; i++) this._noise(t + rnd(0, 0.14), 0.025, 'bandpass', rnd(1800, 5200), 3, 0.001, rnd(0.2, 0.45) * p, out);
      this._osc('sine', 72 * k, 28 * k, t, 0.004, 0.65 / k, 1.0 * p, out, 0.5 / k);
      this._noise(t, 0.35, 'bandpass', 700 * k, 2, 0.003, 0.4 * p, out);
    });
  }
  parry(perfect = false) {
    this.clang(1.1, 1.0);
    if (perfect) {
      this.clang(0.55, 1.62);
      this._go((c, t, k) => {
        const out = this._bus(0, 0.6);
        [2637, 3520, 4186].forEach((f, i) => this._osc('sine', f * k, 0, t + 0.03 + i * 0.03, 0.004, 0.9, 0.05, out));
      });
    }
  }
  dodge() {
    this.whoosh(0.7, 1.35, 0);
    this._go((c, t) => {
      const out = this._bus(0, 0.05);
      this._noise(t + 0.02, 0.05, 'lowpass', 520, 0.7, 0.002, 0.35, out);
      this._noise(t + 0.09, 0.07, 'lowpass', 460, 0.7, 0.002, 0.28, out);
    });
  }
  step(p = 0.5) { this._go((c, t) => { this._noise(t, 0.06, 'lowpass', 480, 0.7, 0.002, 0.3 * p, this._bus(0, 0.04)); }); }
  thud(p = 1) {
    this._go((c, t, k) => {
      const out = this._bus(0, 0.3);
      this._osc('sine', 75 * k, 28 * k, t, 0.004, 0.5 / k, 1.0 * p, out, 0.35 / k);
      this._noise(t, 0.35 / k, 'lowpass', 320 * k, 0.6, 0.004, 0.6 * p, out);
    });
  }
  stagger() {
    this._go((c, t, k) => {
      const out = this._bus(0, 0.4);
      this._osc('sine', 196 * k, 0, t, 0.004, 0.8, 0.2, out);
      this._osc('sine', 294 * k, 0, t + 0.01, 0.004, 0.7, 0.14, out);
    });
    this.ooh(0.7);
  }
  heartbeat(p = 1) {
    this._go((c, t) => {
      const out = this._bus(0, 0);
      this._osc('sine', 62, 40, t, 0.006, 0.13, 0.75 * p, out, 0.1);
      this._osc('sine', 52, 36, t + 0.2, 0.006, 0.16, 0.55 * p, out, 0.12);
    });
  }
  warn() {
    this._go((c, t, k) => {
      const out = this._bus(0, 0.3), lp = c.createBiquadFilter();
      lp.type = 'lowpass'; lp.frequency.value = 800; lp.connect(out);
      this._osc('sawtooth', 98 * k, 92 * k, t, 0.01, 0.5, 0.22, lp);
      this._osc('sawtooth', 104 * k, 97 * k, t, 0.01, 0.5, 0.18, lp);
      const f = this._noise(t, 0.4, 'bandpass', 3400, 8, 0.02, 0.12, out);
      f.frequency.setValueAtTime(3400, t); f.frequency.exponentialRampToValueAtTime(900, t + 0.42);
    });
  }
  grunt(voice = 1, power = 1) {
    this._go((c, t, k) => {
      const dur = (0.22 + 0.16 * power) / k, f0 = 128 * voice * k * rnd(0.94, 1.06);
      const out = this._bus(0, 0.18), mix = c.createGain(); mix.gain.value = 1;
      const o = c.createOscillator(); o.type = 'sawtooth';
      o.frequency.setValueAtTime(f0 * 1.3, t); o.frequency.exponentialRampToValueAtTime(f0 * 0.82, t + dur);
      const vib = c.createOscillator(), vg = c.createGain(); vib.frequency.value = 7; vg.gain.value = f0 * 0.035;
      vib.connect(vg); vg.connect(o.frequency);
      const g = c.createGain();
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.32 * power, t + 0.03);
      g.gain.setValueAtTime(0.3 * power, t + dur * 0.6); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(g);
      [[680 * voice, 7, 1], [1180 * voice, 8, 0.6], [2550, 9, 0.25]].forEach(([f, q, lv]) => {
        const bp = c.createBiquadFilter(); bp.type = 'bandpass'; bp.frequency.value = f * k; bp.Q.value = q;
        const bg = c.createGain(); bg.gain.value = lv * 3;
        g.connect(bp); bp.connect(bg); bg.connect(mix);
      });
      mix.connect(out);
      this._noise(t, dur * 0.8, 'bandpass', 1500 * k, 0.7, 0.03, 0.08 * power, out);
      o.start(t); vib.start(t); o.stop(t + dur + 0.05); vib.stop(t + dur + 0.05);
    });
  }
  roar(voice = 1) { this.grunt(voice * 0.85, 3.2); this._go((c, t) => this._noise(t, 1.0, 'lowpass', 900, 0.7, 0.08, 0.25, this._bus(0, 0.3))); }

  // ── 관중 ───────────────────────────────────────────────────
  cheer(p = 1) {
    this._go((c, t) => {
      const out = this._bus(0, 0.25), dur = 2.2 + p * 0.8;
      [[640, 2.5], [1120, 3], [2500, 4]].forEach(([f, q]) => {
        const n = this._ns(t, dur), bp = c.createBiquadFilter(), g = c.createGain();
        bp.type = 'bandpass'; bp.frequency.value = f * rnd(0.92, 1.08); bp.Q.value = q;
        bp.frequency.linearRampToValueAtTime(f * rnd(0.95, 1.15), t + dur);
        g.gain.setValueAtTime(0.0001, t);
        g.gain.exponentialRampToValueAtTime(0.45 * p, t + 0.35);
        g.gain.setValueAtTime(0.42 * p, t + 0.9);
        g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
        n.connect(bp); bp.connect(g); g.connect(out);
      });
      const nw = Math.round(1 + p * 3);
      for (let i = 0; i < nw; i++) { const s = t + rnd(0.1, 1.2); this._osc('sine', rnd(1700, 2100), rnd(2300, 2900), s, 0.03, 0.28, 0.045 * p, out); }
      const nc = Math.round(8 + p * 14);
      for (let i = 0; i < nc; i++) this._noise(t + rnd(0.05, 1.6), 0.015, 'highpass', 1500, 0.7, 0.001, rnd(0.08, 0.18) * p, out);
    });
    this.setCrowd(Math.min(1, this.crowdEx + 0.3 * p));
  }
  ooh(p = 1) {
    this._go((c, t) => {
      const out = this._bus(0, 0.25);
      [[340, 3], [880, 4]].forEach(([f, q]) => {
        const n = this._ns(t, 1.3), bp = c.createBiquadFilter(), g = c.createGain();
        bp.type = 'bandpass'; bp.frequency.value = f; bp.Q.value = q;
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.35 * p, t + 0.25);
        g.gain.exponentialRampToValueAtTime(0.0001, t + 1.3);
        n.connect(bp); bp.connect(g); g.connect(out);
      });
    });
  }
  horn() {
    this._go((c, t) => {
      const out = this._bus(0, 0.45), lp = c.createBiquadFilter();
      lp.type = 'lowpass'; lp.frequency.value = 1500; lp.connect(out);
      [[293.7, 0, 0.32], [440, 0.34, 0.3], [587.3, 0.66, 0.95]].forEach(([f, s, d]) => {
        this._osc('sawtooth', f, 0, t + s, 0.04, d, 0.16, lp);
        this._osc('sawtooth', f * 1.004, 0, t + s, 0.05, d, 0.1, lp);
      });
    });
  }

  // ── UI / 기타 ──────────────────────────────────────────────
  click() { this._go((c, t) => { const o = this._bus(0, 0); this._osc('sine', 900, 600, t, 0.002, 0.04, 0.09, o); }); }
  coin() { this._go((c, t) => { const o = this._bus(0, 0.15); this._osc('sine', 1320, 0, t, 0.002, 0.09, 0.14, o); this._osc('sine', 1760, 0, t + 0.08, 0.002, 0.16, 0.14, o); }); }
  upgrade() { this._go((c, t) => { const o = this._bus(0, 0.3); [523, 659, 784, 1046].forEach((f, i) => this._osc('triangle', f, 0, t + i * 0.08, 0.004, 0.14, 0.13, o)); }); }
  deny() { this._go((c, t) => { const o = this._bus(0, 0); this._osc('square', 180, 150, t, 0.004, 0.16, 0.06, o); }); }
  drink() {
    this._go((c, t) => {
      const o = this._bus(0, 0.08);
      for (let i = 0; i < 3; i++) this._osc('sine', 240, 150, t + i * 0.15, 0.01, 0.09, 0.3, o);
      for (let i = 0; i < 6; i++) this._osc('sine', rnd(600, 1100), rnd(1100, 1500), t + rnd(0, 0.5), 0.003, 0.035, 0.05, o);
    });
  }
  heal() { this._go((c, t) => { const o = this._bus(0, 0.5); [880, 1320, 1760].forEach((f, i) => this._osc('sine', f, 0, t + i * 0.04, 0.02, 1.0, 0.06, o)); }); }
  slowIn() {
    this._go((c, t) => {
      const o = this._bus(0, 0.3);
      const f = this._noise(t, 0.6, 'lowpass', 4000, 1, 0.02, 0.35, o);
      f.frequency.setValueAtTime(4000, t); f.frequency.exponentialRampToValueAtTime(180, t + 0.6);
      this._osc('sine', 58, 30, t, 0.01, 0.8, 0.55, o);
    });
  }
  slowOut() {
    this._go((c, t) => {
      const o = this._bus(0, 0.2);
      const f = this._noise(t, 0.35, 'lowpass', 300, 1, 0.05, 0.22, o);
      f.frequency.setValueAtTime(300, t); f.frequency.exponentialRampToValueAtTime(3200, t + 0.35);
    });
  }
  execSlash(i = 0) { this.whoosh(1.2, 1.2, i % 2 ? -1 : 1); this.hit(1.25, true); this.clang(0.45, 0.8 + i * 0.12); }
  ko() { this.thud(1.2); this.cheer(1.6); }
}

// ── 햅틱 (navigator.vibrate) ────────────────────────────────
const PATTERNS = {
  ui: 8, swing: 5, hit: 18, crit: [22, 18, 38], blocked: [12, 20, 12], parry: [10, 22, 34],
  perfect: [14, 18, 14, 18, 60], heavy: 60, hurt: [40, 30, 90], block: 22, justGuard: [8, 14, 8],
  guardBreak: [90, 40, 160], dodge: 9, stagger: [30, 40, 30], exec: [24, 26, 24, 26, 120],
  ko: [80, 50, 220], warn: [16, 60, 16], potion: [10, 40, 10], deflect: [50, 30, 50],
};
export class Haptics {
  constructor() {
    this.on = true; this.last = 0;
    this.ok = typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function';
  }
  play(name, force = false) {
    if (!this.on || !this.ok) return;
    const now = performance.now();
    if (!force && now - this.last < 40) return;
    this.last = now;
    try { navigator.vibrate(PATTERNS[name] || 10); } catch (e) { /* 지원 안 함 */ }
  }
}
