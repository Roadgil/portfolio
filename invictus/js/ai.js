// ─────────────────────────────────────────────────────────────
//  적 AI: 아키타입별 공격 패턴·콤보·방어·회피·페인트·보스 페이즈
// ─────────────────────────────────────────────────────────────
import { ARCH, MOVE_DIRS, scaleEnemy, rand, pick } from './config.js';
import { swingSpec } from './gladiator.js';

// w: 예비동작, s: 타격, r: 회복 (초) / d: 데미지 배율 / red: 가드 불가 / grab: 잡기
const MOVES = {
  secutor: {
    slash: { dir: 'L2R', w: 0.62, s: 0.17, r: 0.5 }, back: { dir: 'R2L', w: 0.66, s: 0.17, r: 0.5 },
    over: { dir: 'T2B', w: 0.74, s: 0.16, r: 0.55, d: 1.2 }, rise: { dir: 'BL2TR', w: 0.66, s: 0.17, r: 0.5 },
    diag: { dir: 'TL2BR', w: 0.66, s: 0.17, r: 0.5 }, diag2: { dir: 'TR2BL', w: 0.68, s: 0.17, r: 0.5 },
    heavy: { dir: 'T2B', w: 0.95, s: 0.18, r: 0.8, d: 1.7, red: true, heavy: true, arc: 112 },
  },
  assassin: {
    r1: { dir: 'L2R', hand: 'R', w: 0.42, s: 0.13, r: 0.34, d: 1, lunge: 0.6 }, l1: { dir: 'R2L', hand: 'L', w: 0.42, s: 0.13, r: 0.34, lunge: 0.6 },
    dR: { dir: 'TL2BR', hand: 'R', w: 0.44, s: 0.13, r: 0.34 }, dL: { dir: 'TR2BL', hand: 'L', w: 0.44, s: 0.13, r: 0.34 },
    up: { dir: 'BL2TR', hand: 'R', w: 0.46, s: 0.13, r: 0.36 }, upL: { dir: 'BR2TL', hand: 'L', w: 0.46, s: 0.13, r: 0.36 },
    over: { dir: 'T2B', hand: 'L', w: 0.5, s: 0.13, r: 0.4, d: 1.15 },
    rend: { dir: 'B2T', hand: 'R', w: 0.7, s: 0.15, r: 0.6, d: 1.9, red: true, heavy: true, lunge: 0.75 },
  },
  berserker: {
    sweep: { dir: 'L2R', hand: '2H', w: 0.95, s: 0.22, r: 0.72, d: 1.0, arc: 112, lunge: 0.62, heavy: true },
    sweep2: { dir: 'R2L', hand: '2H', w: 0.95, s: 0.22, r: 0.72, d: 1.0, arc: 112, lunge: 0.62, heavy: true },
    cleave: { dir: 'TR2BL', hand: '2H', w: 0.95, s: 0.2, r: 0.7, d: 1.2, heavy: true }, cleave2: { dir: 'TL2BR', hand: '2H', w: 0.95, s: 0.2, r: 0.7, d: 1.2, heavy: true },
    upper: { dir: 'BL2TR', hand: '2H', w: 0.86, s: 0.2, r: 0.65, d: 1.1, heavy: true },
    smash: { dir: 'T2B', hand: '2H', w: 1.12, s: 0.2, r: 0.95, d: 1.55, red: true, heavy: true, arc: 116, lunge: 0.7 },
    grab: { grab: true, red: true, w: 0.78, s: 0.24, r: 0.8, d: 1.45 },
  },
  champion1: {
    slash: { dir: 'L2R', w: 0.56, s: 0.15, r: 0.45 }, back: { dir: 'R2L', w: 0.58, s: 0.15, r: 0.45 },
    over: { dir: 'T2B', w: 0.64, s: 0.15, r: 0.5, d: 1.2 }, rise: { dir: 'BL2TR', w: 0.58, s: 0.15, r: 0.45 },
    diag: { dir: 'TL2BR', w: 0.58, s: 0.15, r: 0.45 }, diag2: { dir: 'TR2BL', w: 0.58, s: 0.15, r: 0.45 },
    thrust: { dir: 'BR2TL', w: 0.85, s: 0.16, r: 0.7, d: 1.6, red: true, heavy: true },
  },
  champion2: {
    s1: { dir: 'L2R', hand: '2H', w: 0.55, s: 0.16, r: 0.42, d: 1.15, arc: 110 }, s2: { dir: 'R2L', hand: '2H', w: 0.55, s: 0.16, r: 0.42, d: 1.15, arc: 110 },
    s3: { dir: 'TL2BR', hand: '2H', w: 0.55, s: 0.16, r: 0.42, d: 1.15 }, s4: { dir: 'TR2BL', hand: '2H', w: 0.55, s: 0.16, r: 0.42, d: 1.15 },
    s5: { dir: 'BL2TR', hand: '2H', w: 0.55, s: 0.16, r: 0.42, d: 1.15 }, s6: { dir: 'T2B', hand: '2H', w: 0.62, s: 0.16, r: 0.5, d: 1.3 },
    red: { dir: 'T2B', hand: '2H', w: 0.9, s: 0.18, r: 0.8, d: 1.8, red: true, heavy: true, arc: 115, lunge: 0.7 },
    grab: { grab: true, red: true, w: 0.7, s: 0.22, r: 0.7, d: 1.5 },
  },
};
const COMBOS = {
  secutor: [{ m: ['slash'] }, { m: ['over'] }, { m: ['diag'] }, { m: ['rise'] }, { m: ['slash', 'back'] }, { m: ['diag', 'over'] }, { m: ['rise', 'diag2'] }, { m: ['back', 'slash', 'over'], minL: 4 }, { m: ['heavy'], minL: 2, red: true }, { m: ['diag', 'diag2', 'heavy'], minL: 6, red: true }],
  assassin: [{ m: ['r1', 'l1'] }, { m: ['r1', 'l1', 'over'] }, { m: ['dR', 'dL', 'up'] }, { m: ['l1', 'r1', 'dR'] }, { m: ['upL', 'up'] }, { m: ['r1', 'l1', 'dR', 'dL'], minL: 5 }, { m: ['rend'], minL: 2, red: true }, { m: ['r1', 'l1', 'rend'], minL: 6, red: true }],
  berserker: [{ m: ['sweep'] }, { m: ['cleave'] }, { m: ['upper'] }, { m: ['sweep', 'sweep2'] }, { m: ['cleave', 'cleave2'] }, { m: ['smash'], red: true }, { m: ['grab'], minL: 2, red: true }, { m: ['sweep2', 'cleave2', 'smash'], minL: 5, red: true }],
  champion1: [{ m: ['slash', 'back'] }, { m: ['diag', 'over'] }, { m: ['rise', 'diag2', 'slash'] }, { m: ['back', 'diag'] }, { m: ['thrust'], red: true }],
  champion2: [{ m: ['s1', 's2', 's6'] }, { m: ['s3', 's4', 's5'] }, { m: ['s2', 's1', 's3', 's6'] }, { m: ['red'], red: true }, { m: ['s1', 's2', 'red'], red: true }, { m: ['grab'], red: true }],
  champion3: [{ m: ['s1', 's2', 's3', 's4', 's6'] }, { m: ['s5', 's2', 's1', 'red'], red: true }, { m: ['s3', 's4', 's1', 's2'] }, { m: ['grab'], red: true }, { m: ['red', 's1', 's2'], red: true }],
};
const zoneOf = (dy) => (dy < -0.38 ? 'high' : dy > 0.38 ? 'low' : 'mid');

export class EnemyAI {
  constructor(battle, g, arch, lvl) {
    this.b = battle; this.g = g; this.arch = arch;
    this.A = ARCH[arch]; this.S = scaleEnemy(arch, lvl); this.lvl = lvl;
    this.state = 'intro'; this.timer = 0;
    this.phase = 1;
    this.moveSet = arch === 'champion' ? 'champion1' : arch;
    this.poiseMax = { secutor: 3, assassin: 2, berserker: 5, champion: 4 }[arch];
    this.poise = this.poiseMax;
    this.guardZone = null;
    this.combo = null; this.cur = null;
    this.history = [];
    this.lastAttackEnd = 0; this.lastWasAttack = false;
    this.canFeint = arch === 'secutor' || arch === 'champion' || lvl >= 5;
    this.counterQueued = false;
    this.clock = 0; this.lastHitT = -9; this.breakout = false;
  }
  get attacking() { return this.state === 'attack' && !!this.cur; }

  start() { this.state = 'idle'; this.timer = rand(0.7, 1.1); this.g.setStance('idle'); }
  setPhase(p) {
    this.phase = p;
    this.moveSet = p === 1 ? 'champion1' : p === 2 ? 'champion2' : 'champion3';
    if (p >= 2) { this.canFeint = true; this.poiseMax = 6; }
  }

  update(dt) {
    const g = this.g;
    this.timer -= dt; this.clock += dt;
    if (this.clock - this.lastHitT > 1.3 && this.poise < this.poiseMax) this.poise = this.poiseMax;
    switch (this.state) {
      case 'idle':
        if (g.stance !== 'idle') g.setStance('idle');
        if (this.timer <= 0) this.decide();
        break;
      case 'guard':
        if (this.timer <= 0) this.decide(true);
        break;
      case 'attack': this._updAttack(dt); break;
      case 'feint':
        if (this.cur) {
          this.cur.t += dt;
          if (this.cur.t >= this.cur.cancelAt) { g.cancelSwing(); this.b.onEnemyFeintEnd(); this.cur = null; this.state = 'idle'; this.timer = rand(0.25, 0.5); }
        }
        break;
      case 'recover': case 'hitstun': case 'dodge': case 'parried':
        if (this.timer <= 0) {
          if (this.counterQueued) { this.counterQueued = false; this.breakout = false; this.beginAttack(this._pickCombo(true), 0.62); }
          else { this.state = 'idle'; this.timer = rand(0.25, 0.6) * this.S.aggr; }
        }
        break;
      case 'stagger':
        if (this.timer <= 0) { g.setStance('idle'); this.state = 'recover'; this.timer = 0.3; this.poise = this.poiseMax; }
        break;
      case 'phase':
        if (this.timer <= 0) { g.setStance('idle'); this.state = 'idle'; this.timer = 0.4; }
        break;
    }
  }

  decide(fromGuard = false) {
    const A = this.A, g = this.g;
    const canGuard = g.hasShield || this.arch === 'champion';
    const r = Math.random();
    if (!fromGuard && canGuard && A.guard > 0 && r < A.guard * (this.lastWasAttack ? 0.9 : 0.4)) {
      this.guardZone = Math.random() < 0.5 ? 'high' : 'low';
      g.setStance(this.guardZone === 'high' ? 'guardHigh' : 'guardLow');
      this.state = 'guard'; this.timer = rand(0.9, 1.8) * (0.6 + this.S.aggr * 0.4);
      this.lastWasAttack = false;
      return;
    }
    this.guardZone = null;
    if (this.canFeint && Math.random() < 0.13 + this.lvl * 0.008) { this._fakeAttack(); return; }
    this.beginAttack(this._pickCombo(false));
  }

  _pickCombo(counter) {
    const list = COMBOS[this.moveSet].filter((c) => (c.minL || 0) <= this.lvl);
    const pb = this.b.playerBlockingLong();
    const redW = { secutor: 0.5, assassin: 0.45, berserker: 1, champion: 0.9 }[this.arch] * (pb ? 3 : 1);
    const weighted = [];
    for (const c of list) {
      let w = c.m.length > 1 ? 0.6 + Math.min(0.8, this.lvl * 0.08) : 1;
      if (c.red) w *= redW * (counter ? 0.3 : 1);
      if (counter && c.m.length > 2) w *= 0.5;
      weighted.push([c, w]);
    }
    let tot = weighted.reduce((a, [, w]) => a + w, 0), x = Math.random() * tot;
    for (const [c, w] of weighted) { if ((x -= w) <= 0) return c.m; }
    return list[0].m;
  }

  beginAttack(names, windMul = 1) {
    this.combo = { names, i: 0, windMul };
    this.state = 'attack'; this.lastWasAttack = true;
    this.g.setStance('idle');
    this._startMove();
  }

  _startMove() {
    const set = MOVES[this.moveSet], c = this.combo, m = set[c.names[c.i]];
    const chain = c.i > 0, last = c.i === c.names.length - 1;
    const wm = this.S.wind * (chain ? 0.62 : 1) * c.windMul * (this.phase >= 3 ? 0.88 : 1);
    let act;
    if (m.grab) act = this.g.grab({ windup: m.w * wm, strike: m.s, recover: m.r });
    else {
      const spec = swingSpec(MOVE_DIRS[m.dir], { hand: m.hand || 'R', windup: m.w * wm, strike: m.s, recover: last ? m.r : Math.min(0.14, m.r), arc: m.arc, lunge: m.lunge, red: m.red, heavy: m.heavy });
      act = this.g.swing(spec);
    }
    const pw = this.b.parryWindow(this.S.parryWin);
    this.cur = {
      m, act, t: 0, impactT: act.impactT, endT: act.endT, resolved: false,
      parryOpen: act.impactT - pw, red: !!m.red, grab: !!m.grab, dir: m.dir ? MOVE_DIRS[m.dir] : null,
      dmg: (m.d || 1) * this.S.dmg, heavy: !!m.heavy, superArmor: this.A.superArmor && (m.heavy || m.grab),
      feintSwitch: !m.grab && !m.red && this.phase >= 3 && Math.random() < 0.3 ? pick(Object.keys(MOVE_DIRS).filter((k) => k !== m.dir)) : null,
    };
    this.b.onEnemyWindup(this.cur);
  }

  _updAttack(dt) {
    const c = this.cur;
    if (!c) { this.state = 'recover'; this.timer = 0.2; return; }
    c.t += dt;
    // 챔피언 3페이즈: 예비동작 중 궤적 전환 페인트
    if (c.feintSwitch && c.t > c.impactT * 0.55 && !c.switched) {
      c.switched = true;
      const m = MOVES[this.moveSet][this.combo.names[this.combo.i]];
      const remain = Math.max(0.24, c.impactT - c.t);
      const spec = swingSpec(MOVE_DIRS[c.feintSwitch], { hand: m.hand || 'R', windup: remain * 0.9, strike: m.s, recover: 0.3, arc: m.arc });
      const act = this.g.swing(spec);
      c.act = act; c.dir = MOVE_DIRS[c.feintSwitch];
      c.impactT = c.t + act.impactT; c.endT = c.t + act.endT;
      c.parryOpen = c.impactT - this.b.parryWindow(this.S.parryWin) * 0.85;
      this.b.onEnemyFeintSwitch(c);
    }
    if (!c.resolved && c.t >= c.impactT) {
      c.resolved = true;
      this.b.resolveEnemyImpact(c);
    }
    if (c.t >= c.endT || (!this.g.action && c.resolved)) this._nextMove();
  }

  _nextMove() {
    const c = this.combo;
    if (this.state !== 'attack') return;
    if (c && c.i < c.names.length - 1 && !this.cur.broken) { c.i++; this._startMove(); return; }
    this.cur = null; this.combo = null;
    this.state = 'recover'; this.timer = rand(0.15, 0.35);
    this.b.onEnemyAttackEnd();
  }

  _fakeAttack() {
    const set = MOVES[this.moveSet], keys = Object.keys(set).filter((k) => !set[k].red && !set[k].grab);
    const m = set[pick(keys)];
    const spec = swingSpec(MOVE_DIRS[m.dir], { hand: m.hand || 'R', windup: m.w * this.S.wind, strike: m.s, recover: m.r });
    const act = this.g.swing(spec);
    this.cur = { m, act, t: 0, cancelAt: spec.windup * rand(0.5, 0.7), fake: true, impactT: act.impactT, dir: MOVE_DIRS[m.dir], red: false };
    this.state = 'feint';
    this.b.onEnemyWindup(this.cur);
  }

  // ── 외부 이벤트 ────────────────────────────────────────
  // 플레이어가 스와이프를 시작한 순간: 방어 반응 결정
  reactToSwing(sw) {
    const A = this.A, g = this.g;
    const zone = zoneOf(sw.dy);
    this.history.push(sw.dir8); if (this.history.length > 5) this.history.shift();
    const h = this.history, n = h.length;
    let predict = 0;
    if (n >= 2 && h[n - 1] === h[n - 2]) predict += 0.28;
    if (n >= 3 && h[n - 1] === h[n - 3]) predict += 0.1;
    if (this.state === 'feint') {
      // 페인트에 낚인 스와이프 → 막거나 피하고 즉시 반격
      g.cancelSwing(); this.b.onEnemyFeintEnd(); this.cur = null;
      this.counterQueued = true;
      if (g.hasShield) { this._raiseGuard(zone); this.state = 'recover'; this.timer = 0.32; return 'block'; }
      if (this.arch === 'assassin' || this.arch === 'champion') { this._dodge(); return 'dodge'; }
      this.state = 'recover'; this.timer = 0.1; return null;
    }
    if (this.state === 'guard') {
      if (!sw.feint && (zone === 'mid' || zone === this.guardZone)) return 'block';
      return null;
    }
    // 연속 피격으로 버티기(poise)가 바닥나면 콤보를 끊고 반격
    if (this.state === 'hitstun' || this.state === 'recover') {
      if (this.poise > 0 || this.b.p.bullet > 0) return null;
      this.poise = this.poiseMax; this.counterQueued = true;
      if (g.hasShield && !sw.feint) { this._raiseGuard(zone); this.timer = 0.35; return 'block'; }
      if (A.evade > 0) { this._dodge(); return 'dodge'; }
      if (A.eParry > 0 && !sw.feint) { this.state = 'recover'; this.timer = 0.3; return 'parry'; }
      this.breakout = true; this.state = 'recover'; this.timer = 0.08;
      return null;
    }
    if (this.state !== 'idle') return null;
    const reach = this.b.weaponReach();
    const poiseOut = this.poise <= 0;
    if (A.evade > 0) {
      const ch = (A.evade + this.lvl * 0.025 + predict) * (2 - reach) * (sw.feint ? 0.5 : 1);
      if (poiseOut || Math.random() < Math.min(0.7, ch)) { this._dodge(); this.counterQueued = Math.random() < 0.55; this.poise = this.poiseMax; return 'dodge'; }
    }
    if (g.hasShield && !sw.feint) {
      const ch = A.react + this.lvl * 0.025 + predict;
      if (poiseOut || Math.random() < Math.min(0.75, ch)) {
        this._raiseGuard(zone);
        this.poise = this.poiseMax;
        if (Math.random() < 0.5) this.counterQueued = true;
        return 'block';
      }
    }
    if (A.eParry > 0 && !sw.feint && Math.random() < A.eParry + predict * 0.5) {
      this.counterQueued = true; return 'parry';
    }
    return null;
  }
  _raiseGuard(zone) {
    this.guardZone = zone === 'mid' ? (Math.random() < 0.5 ? 'high' : 'low') : zone;
    this.g.setStance(this.guardZone === 'high' ? 'guardHigh' : 'guardLow');
    this.state = 'guard'; this.timer = rand(0.5, 0.9);
  }
  _dodge() {
    const side = Math.random() < 0.5 ? -1 : 1;
    this.g.dodge(side);
    this.state = 'dodge'; this.timer = 0.6;
  }
  // 플레이어 공격 적중
  onHit(heavy) {
    this.poise -= heavy ? 2 : 1; this.lastHitT = this.clock;
    if (this.breakout) return 'armor';
    if (this.state === 'attack' && this.cur && !this.cur.resolved) {
      if (this.cur.superArmor) return 'armor';
      if (this.cur.t < this.cur.parryOpen - 0.02) return 'committed';
      return 'committed';
    }
    if (this.state === 'stagger' || this.state === 'phase') return 'stagger';
    // 경직
    this.cur = null; this.combo = null;
    if (this.arch === 'berserker' && Math.random() < 0.5) return 'armor';
    this.state = 'hitstun'; this.timer = 0.36;
    if (this.poise <= 0) { this.counterQueued = true; this.timer = 0.3; }
    this.g.flinch(heavy ? 1.3 : 0.9);
    return 'stun';
  }
  onParried() {
    this.cur && (this.cur.broken = true);
    this.g.rebound('parried');
    this.combo = null; this.cur = null;
  }
  onBlockedByPlayer() {
    if (this.cur) this.g.rebound('blocked');
  }
  stagger(dur) {
    this.combo = null; this.cur = null; this.counterQueued = false;
    this.state = 'stagger'; this.timer = dur;
    this.g.setStance('stagger');
  }
  forceRecover(dur) {
    // 완벽 회피 후 불릿타임: 적은 빈틈 상태
    if (this.cur) this.cur.broken = true;
    this.combo = null; this.cur = null;
    this.g.cancelSwing();
    this.state = 'recover'; this.timer = dur; this.counterQueued = false;
    this.g.setStance('stun');
  }
  phaseChange(dur) {
    this.combo = null; this.cur = null; this.counterQueued = false;
    this.g.cancelSwing(); this.state = 'phase'; this.timer = dur;
    this.g.setStance('taunt');
  }
  kill() { this.state = 'dead'; this.cur = null; this.combo = null; }
}
