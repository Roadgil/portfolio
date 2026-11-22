// ─────────────────────────────────────────────────────────────
//  렌더러 / 포스트프로세싱(Bloom) / PMREM 환경맵 / 동적 DPR 스케일링
// ─────────────────────────────────────────────────────────────
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';
import { QUALITY } from './config.js';

export class Engine {
  constructor(container, qualityName = 'auto') {
    this.container = container;
    this.qName = qualityName;
    this.q = QUALITY[qualityName === 'auto' ? 'high' : qualityName] || QUALITY.high;
    this.auto = qualityName === 'auto';

    const r = this.renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: 'high-performance', stencil: false, alpha: false });
    r.outputColorSpace = THREE.SRGBColorSpace;
    r.toneMapping = THREE.ACESFilmicToneMapping;
    r.toneMappingExposure = 1.0;
    r.shadowMap.enabled = true;
    r.shadowMap.type = THREE.PCFSoftShadowMap;
    r.setClearColor(0x120c08, 1);
    r.domElement.id = 'gl';
    container.appendChild(r.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(70, 1, 0.04, 900);
    this.scene.add(this.camera);

    this.maxDpr = Math.min(window.devicePixelRatio || 1, this.q.dprMax);
    this.minDpr = Math.min(1, this.maxDpr);
    this.dpr = this.maxDpr;
    this.targetFps = 60;
    this.fpsCap = 0;           // 0 = 디스플레이 주사율
    this._ft = []; this._lastAdj = 0; this._acc = 0;
    this.fps = 0;

    this._buildComposer();
    this.resize = this.resize.bind(this);
    window.addEventListener('resize', this.resize);
    if (window.visualViewport) window.visualViewport.addEventListener('resize', this.resize);
    this.resize();
    this.pmrem = new THREE.PMREMGenerator(r);
    this.envRT = null;
  }

  _buildComposer() {
    const r = this.renderer;
    const w = Math.max(1, window.innerWidth), h = Math.max(1, window.innerHeight);
    const rt = new THREE.WebGLRenderTarget(w * this.dpr, h * this.dpr, { type: THREE.HalfFloatType, samples: this.q.msaa });
    if (this.composer) { this.composer.dispose(); if (this.bloom) this.bloom.dispose(); }
    this.composer = new EffectComposer(r, rt);
    this.composer.setPixelRatio(this.dpr);
    this.renderPass = new RenderPass(this.scene, this.camera);
    this.bloom = new UnrealBloomPass(new THREE.Vector2(w, h), 0.62, 0.55, 1.15);
    this.output = new OutputPass();
    this.composer.addPass(this.renderPass);
    this.composer.addPass(this.bloom);
    this.composer.addPass(this.output);
  }

  setQuality(name) {
    this.qName = name; this.auto = name === 'auto';
    this.q = QUALITY[this.auto ? 'high' : name] || QUALITY.high;
    this.maxDpr = Math.min(window.devicePixelRatio || 1, this.q.dprMax);
    this.dpr = this.maxDpr;
    this._buildComposer();
    this.resize();
  }
  setFpsMode(mode) { this.fpsCap = mode === '60' ? 60 : 0; }

  // 세로 화면에서도 적의 어깨 폭이 화면에 들어오도록 수평 화각 기준으로 FOV 계산
  fovFor(aspect, hfov = 34) {
    const v = 2 * Math.atan(Math.tan(THREE.MathUtils.degToRad(hfov / 2)) / aspect);
    return THREE.MathUtils.clamp(THREE.MathUtils.radToDeg(v), 46, 68);
  }

  resize() {
    const w = Math.max(1, window.innerWidth), h = Math.max(1, window.innerHeight);
    this.w = w; this.h = h;
    this.renderer.setPixelRatio(this.dpr);
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = w + 'px';
    this.renderer.domElement.style.height = h + 'px';
    this.composer.setPixelRatio(this.dpr);
    this.composer.setSize(w, h);
    this.camera.aspect = w / h;
    this.baseFov = this.fovFor(w / h);
    this.camera.fov = this.baseFov;
    this.camera.updateProjectionMatrix();
  }

  // 주사율(60/90/120Hz) 감지
  measureRefresh(frames = 40) {
    return new Promise((res) => {
      const ts = []; let last = performance.now();
      const step = (t) => {
        ts.push(t - last); last = t;
        if (ts.length < frames) requestAnimationFrame(step);
        else {
          ts.sort((a, b) => a - b);
          const med = ts[Math.floor(ts.length / 2)] || 16.7;
          const hz = 1000 / med;
          this.refresh = [60, 90, 120, 144].reduce((a, b) => (Math.abs(b - hz) < Math.abs(a - hz) ? b : a), 60);
          this.targetFps = this.refresh;
          res(this.refresh);
        }
      };
      requestAnimationFrame(step);
    });
  }

  // 프레임 시간 기반 동적 해상도 (발열/프레임 방어)
  monitor(dtMs, now) {
    this._ft.push(dtMs);
    if (this._ft.length > 90) this._ft.shift();
    this._acc += dtMs;
    if (this._acc < 1000) return;
    this._acc = 0;
    const avg = this._ft.reduce((a, b) => a + b, 0) / this._ft.length;
    this.fps = 1000 / avg;
    const target = this.fpsCap || this.targetFps;
    if (!this.auto && this.dpr <= this.minDpr) return;
    if (this.fps < target * 0.86 && now - this._lastAdj > 1500 && this.dpr > this.minDpr + 0.01) {
      this.dpr = Math.max(this.minDpr, this.dpr - (this.fps < target * 0.6 ? 0.3 : 0.15));
      this._lastAdj = now; this.resize();
    } else if (this.fps > target * 0.97 && now - this._lastAdj > 5000 && this.dpr < this.maxDpr - 0.01) {
      this.dpr = Math.min(this.maxDpr, this.dpr + 0.1);
      this._lastAdj = now; this.resize();
    }
  }

  // PMREM 환경맵: 하늘 그라디언트 + 태양 + 횃불을 큐브로 구워 금속 반사에 사용
  buildEnvironment(L) {
    const s = new THREE.Scene();
    const geo = new THREE.SphereGeometry(50, 32, 16);
    const top = new THREE.Color(L.skyTop), hor = new THREE.Color(L.skyHor), gnd = new THREE.Color(0x8a6c4a).multiplyScalar(0.5);
    const col = [], pos = geo.attributes.position, c = new THREE.Color();
    for (let i = 0; i < pos.count; i++) {
      const y = pos.getY(i) / 50;
      if (y > 0) c.copy(hor).lerp(top, Math.pow(y, 0.6)); else c.copy(hor).lerp(gnd, Math.min(1, -y * 3));
      col.push(c.r, c.g, c.b);
    }
    geo.setAttribute('color', new THREE.Float32BufferAttribute(col, 3));
    s.add(new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ vertexColors: true, side: THREE.BackSide })));
    const wall = new THREE.Mesh(new THREE.CylinderGeometry(30, 30, 14, 32, 1, true), new THREE.MeshBasicMaterial({ color: new THREE.Color(L.fog).multiplyScalar(0.45), side: THREE.BackSide }));
    wall.position.y = 2; s.add(wall);
    const sun = new THREE.Mesh(new THREE.SphereGeometry(3, 16, 8), new THREE.MeshBasicMaterial({ color: new THREE.Color(L.sun).multiplyScalar(L.sunI * 9) }));
    sun.position.set(...L.sunDir).normalize().multiplyScalar(44); s.add(sun);
    const tc = new THREE.Color(0xff8a3a).multiplyScalar(6 * L.torch);
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2, t = new THREE.Mesh(new THREE.SphereGeometry(0.9, 8, 6), new THREE.MeshBasicMaterial({ color: tc }));
      t.position.set(Math.cos(a) * 26, 3, Math.sin(a) * 26); s.add(t);
    }
    if (this.envRT) this.envRT.dispose();
    this.envRT = this.pmrem.fromScene(s, 0.035);
    s.traverse((o) => { if (o.isMesh) { o.geometry.dispose(); o.material.dispose(); } });
    this.scene.environment = this.envRT.texture;
    if ('environmentIntensity' in this.scene) this.scene.environmentIntensity = L.env;
  }

  render() { this.composer.render(); }
}
