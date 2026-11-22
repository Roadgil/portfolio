// INVICTUS 서비스 워커 — 앱 셸 사전 캐시 + CDN(three.js) 런타임 캐시 → 오프라인 플레이
const VERSION = 'invictus-v1.0.0';
const SHELL = [
  './', './index.html', './manifest.json', './css/style.css',
  './js/main.js', './js/config.js', './js/save.js', './js/audio.js', './js/input.js', './js/textures.js',
  './js/engine.js', './js/arena.js', './js/gladiator.js', './js/viewmodel.js', './js/fx.js', './js/camera.js',
  './js/ai.js', './js/combat.js', './js/ui.js',
  './icons/icon-192.png', './icons/icon-512.png', './icons/maskable-512.png', './icons/apple-touch-icon.png',
];
const CDN = 'https://cdn.jsdelivr.net/npm/three@0.170.0/';
const CDN_FILES = [
  'build/three.module.min.js',
  'examples/jsm/postprocessing/EffectComposer.js', 'examples/jsm/postprocessing/RenderPass.js',
  'examples/jsm/postprocessing/UnrealBloomPass.js', 'examples/jsm/postprocessing/OutputPass.js',
  'examples/jsm/postprocessing/ShaderPass.js', 'examples/jsm/postprocessing/MaskPass.js', 'examples/jsm/postprocessing/Pass.js',
  'examples/jsm/shaders/CopyShader.js', 'examples/jsm/shaders/LuminosityHighPassShader.js', 'examples/jsm/shaders/OutputShader.js',
].map((f) => CDN + f);

self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(VERSION);
    await c.addAll(SHELL);
    // CDN은 실패해도 설치를 막지 않음 (첫 실행 시 런타임 캐시로 보완)
    await Promise.all(CDN_FILES.map((u) => c.add(new Request(u, { mode: 'cors' })).catch(() => {})));
    self.skipWaiting();
  })());
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const isCdn = url.hostname === 'cdn.jsdelivr.net' || url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com';
  if (isCdn) {
    // 버전 고정 URL → 캐시 우선
    e.respondWith((async () => {
      const c = await caches.open(VERSION);
      const hit = await c.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res && (res.ok || res.type === 'opaque')) c.put(req, res.clone());
      return res;
    })());
    return;
  }
  if (url.origin !== location.origin) return;
  if (req.mode === 'navigate') {
    // 페이지는 네트워크 우선 (업데이트 즉시 반영), 오프라인이면 캐시
    e.respondWith((async () => {
      try {
        const res = await fetch(req);
        const c = await caches.open(VERSION); c.put('./index.html', res.clone());
        return res;
      } catch (err) {
        return (await caches.match('./index.html')) || (await caches.match('./')) || Response.error();
      }
    })());
    return;
  }
  // 정적 자원: stale-while-revalidate
  e.respondWith((async () => {
    const c = await caches.open(VERSION);
    const hit = await c.match(req, { ignoreSearch: true });
    const net = fetch(req).then((res) => { if (res && res.ok) c.put(req, res.clone()); return res; }).catch(() => null);
    return hit || (await net) || Response.error();
  })());
});
