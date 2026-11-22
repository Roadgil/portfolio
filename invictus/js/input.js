// ─────────────────────────────────────────────────────────────
//  8방향 스와이프 인식 (터치 + 마우스 드래그) / 페인트(꺾어 긋기) 감지
// ─────────────────────────────────────────────────────────────
import { angleOf, angDiff, sector8 } from './config.js';

export class SwipeInput {
  constructor(el, { onSwipe, onTrail, onTap }) {
    this.el = el;
    this.onSwipe = onSwipe; this.onTrail = onTrail; this.onTap = onTap;
    this.active = null;
    this.enabled = true;
    this._down = this._down.bind(this); this._move = this._move.bind(this);
    this._up = this._up.bind(this); this._cancel = this._cancel.bind(this);
    el.addEventListener('pointerdown', this._down, { passive: false });
    el.addEventListener('pointermove', this._move, { passive: false });
    el.addEventListener('pointerup', this._up, { passive: false });
    el.addEventListener('pointercancel', this._cancel, { passive: false });
    el.addEventListener('lostpointercapture', this._cancel);
  }
  get minLen() { return Math.max(26, Math.min(window.innerWidth, window.innerHeight) * 0.065); }

  _down(e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    e.preventDefault();
    if (this.active) return;
    try { this.el.setPointerCapture(e.pointerId); } catch (err) { /* 일부 브라우저 */ }
    const t = performance.now();
    this.active = { id: e.pointerId, pts: [{ x: e.clientX, y: e.clientY, t }] };
    if (this.enabled) this.onTrail && this.onTrail('start', e.clientX, e.clientY);
  }
  _move(e) {
    const a = this.active;
    if (!a || e.pointerId !== a.id) return;
    e.preventDefault();
    const list = (typeof e.getCoalescedEvents === 'function' && e.getCoalescedEvents().length) ? e.getCoalescedEvents() : [e];
    for (const ce of list) {
      const last = a.pts[a.pts.length - 1];
      const dx = ce.clientX - last.x, dy = ce.clientY - last.y;
      if (dx * dx + dy * dy < 4) continue;
      a.pts.push({ x: ce.clientX, y: ce.clientY, t: performance.now() });
      if (this.enabled) this.onTrail && this.onTrail('move', ce.clientX, ce.clientY);
    }
    if (a.pts.length > 240) a.pts.splice(1, a.pts.length - 240);
    // 너무 오래 끌면 자동 확정
    if (performance.now() - a.pts[0].t > 650) this._finish();
  }
  _up(e) {
    const a = this.active;
    if (!a || e.pointerId !== a.id) return;
    e.preventDefault();
    a.pts.push({ x: e.clientX, y: e.clientY, t: performance.now() });
    this._finish();
  }
  _cancel(e) {
    if (!this.active || (e && e.pointerId !== undefined && e.pointerId !== this.active.id)) return;
    this._finish();
  }
  _finish() {
    const a = this.active;
    if (!a) return;
    this.active = null;
    if (this.onTrail) this.onTrail('end', 0, 0);
    const s = classifySwipe(a.pts, this.minLen);
    if (!this.enabled) return;
    if (s) this.onSwipe && this.onSwipe(s);
    else this.onTap && this.onTap(a.pts[0].x, a.pts[0].y);
  }
}

export function classifySwipe(pts, minLen) {
  if (!pts || pts.length < 2) return null;
  const p0 = pts[0], pn = pts[pts.length - 1];
  let k = 0, dmax = 0;
  for (let i = 1; i < pts.length; i++) {
    const dx = pts[i].x - p0.x, dy = pts[i].y - p0.y, d = Math.hypot(dx, dy);
    if (d > dmax) { dmax = d; k = i; }
  }
  if (dmax < minLen) return null;
  const pk = pts[k];
  const back = Math.hypot(pn.x - pk.x, pn.y - pk.y);
  let feint = false, angle, fromAngle = null;
  if (k < pts.length - 1 && back > 0.42 * dmax && back > minLen * 1.15 && dmax > minLen * 1.15) {
    const a1 = angleOf(pk.x - p0.x, -(pk.y - p0.y));
    const a2 = angleOf(pn.x - pk.x, -(pn.y - pk.y));
    if (angDiff(a1, a2) > 95) { feint = true; fromAngle = a1; angle = a2; }
  }
  if (!feint) angle = angleOf(pk.x - p0.x, -(pk.y - p0.y));
  const dur = Math.max(0.016, (pn.t - p0.t) / 1000);
  const len = dmax + (feint ? back : 0);
  return {
    angle, dir8: sector8(angle), feint, fromAngle, len, dur,
    speed: len / dur,
    dx: Math.cos(angle * Math.PI / 180), dy: Math.sin(angle * Math.PI / 180),
    x0: p0.x, y0: p0.y, x1: pn.x, y1: pn.y,
  };
}
