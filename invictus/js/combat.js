// ─────────────────────────────────────────────────────────────
//  전투 규칙: 스와이프 베기·콤보 배율·방향 일치 패링·방패/저스트 가드·
//  회피+불릿타임·그로기·처형 QTE·인빅투스·시네마틱 피니시·KO
// ─────────────────────────────────────────────────────────────
import * as THREE from 'three';
import {
  ENEMY_Z, EYE_H, ARCH, TIERS, TUNE, LIGHTS, MOVE_DIRS, weaponStats, shieldStats, armorStats, scaleEnemy,
  angleOf, angDiff, clamp, rand, pick, fightReward, POTION, ELIXIR,
} from './config.js';
import { Gladiator, makeLook, playerLook, swingSpec } from './gladiator.js';
import { EnemyAI } from './ai.js';

const V3 = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const _v = V3(), _w = V3();
const zoneOf = (dy) => (dy < -0.38 ? 'high' : dy > 0.38 ? 'low' : 'mid');

export class Battle {
  constructor(game, spec) {
    this.game = game; this.spec = spec;
    const s = game.save;
    this.tier = spec.mode === 'tour' ? TIERS[spec.tier] : { tol: 38, hint: false, qte: { n: 3, time: 3.0 }, name: '무한 아레나' };
    this.fight = spec.fight;
    this.light = LIGHTS[spec.light || this.tier.light || 'afternoon'];
    this.w = weaponStats(s.weapon, s.wlvl[s.weapon] || 1);
    this.sh = shieldStats(s.shieldLvl); this.ar = armorStats(s.armorLvl);
    const maxHp = this.ar.hp;
    this.p = {
      hp: spec.carryHp != null ? Math.min(maxHp, spec.carryHp) : maxHp, maxHp,
      shield: this.sh.max, rage: spec.carryRage || 0,
      state: 'intro', stateT: 0, swing: null, buffer: null,
      blockStart: -9, blockHeld: false, blockSince: 0, shieldBroken: false, shieldIdle: 0,
      dodgeT: -1, dodgeCd: 0, combo: 0, comboMul: 1, lastDir: -1, lastHitT: -9,
      counterBuff: 0, bullet: 0, hbT: 0,
      dmgTaken: 0, maxCombo: 0, parries: 0, perfects: 0, hits: 0, execs: 0,
    };
    this.t = 0; this.timers = []; this.active = false; this.over = false;
    this.execTried = false; this.qte = null;
  }

  // ── 시작 ────────────────────────────────────────────────
  start() {
    const G = this.game, F = this.fight;
    G.arena.setLighting(this.light);
    G.fx.clearDebris();
    const look = makeLook(F.arch, (F.name.length * 131 + F.lvl * 17 + (this.spec.wave || 0) * 7) | 0);
    this.enemy = new Gladiator(look, G.lib, { fx: G.fx });
    this.ez = -(ARCH[F.arch].dist || -ENEMY_Z);
    this.enemy.root.position.set(0, 0, this.ez);
    this.enemy.tipLimitZ = -0.42;
    this.enemy.addTo(G.scene);
    G.camRig.enemyZ = this.ez; G.camRig.focus.set(0, 1.26, this.ez); G.camRig.focusTarget.copy(G.camRig.focus);
    this.enemy.onThud = () => { G.audio.thud(1); G.fx.dust(this.enemy.chestPos(_v).setY(0.05), 26, { scale: 1.4 }); G.camRig.shake(0.15); };
    this.ai = new EnemyAI(this, this.enemy, F.arch, F.lvl);
    const S = scaleEnemy(F.arch, F.lvl);
    this.e = { hp: S.hp, maxHp: S.hp, guard: ARCH[F.arch].guardStam, guardMax: ARCH[F.arch].guardStam, shieldHP: ARCH[F.arch].shieldHP * (1 + 0.15 * (F.lvl - 1)), helmetHP: ARCH[F.arch].helmetHP * (1 + 0.15 * (F.lvl - 1)) };
    this.avatar = new Gladiator(playerLook(G.save), G.lib, { fx: G.fx });
    this.avatar.root.position.set(0, 0, 0.05); this.avatar.root.rotation.y = Math.PI;
    this.avatar.addTo(G.scene); this.avatar.setVisible(false);
    G.vm.equip(G.save); G.vm.setVisible(false);
    G.ui.battleHUD(true, { name: F.name, title: ARCH[F.arch].name, lvl: F.lvl, boss: !!F.boss });
    G.input.enabled = true;
    this._intro();
  }

  _intro() {
    const G = this.game, F = this.fight;
    this.p.state = 'intro';
    G.ui.vsCard(F, ARCH[F.arch], this.spec);
    G.audio.horn(); G.audio.cheer(0.9);
    this.enemy.setStance('taunt');
    this.after(0.7, () => G.audio.roar(ARCH[F.arch].voice), true);
    const c = V3(0, 1.25, this.ez);
    G.camRig.orbit({ center: c, a0: -2.5, a1: 0, r0: 3.1, r1: -this.ez, h0: 1.05, h1: EYE_H, lookY: 1.26, dur: 3.0, fov: 46 }, () => this._fightStart());
    this._introSkip = () => { if (G.camRig.orbitS) G.camRig.orbitS.t = Math.max(G.camRig.orbitS.t, G.camRig.orbitS.dur - 0.25); };
  }
  _fightStart() {
    if (this.active || this.over) return;
    const G = this.game;
    G.camRig.toFP(); G.vm.setVisible(true);
    G.ui.vsCard(null); G.ui.introMode(false); G.ui.bigText('싸워라!', 'go');
    G.audio.cheer(0.6);
    this.enemy.setStance('idle');
    this.ai.start();
    this.p.state = 'idle'; this.active = true;
    if (G.save.stats.wins === 0 && this.spec.mode === 'tour' && this.spec.tier === 0 && this.spec.fightIdx === 0) this.after(0.9, () => G.ui.toast('적의 궤적이 빛나는 순간, 반대 방향으로 그어 패링!'), true);
  }

  after(sec, fn, real = false) { this.timers.push({ t: sec, fn, real }); }

  // ── AI 콜백 ────────────────────────────────────────────
  parryWindow(base) { return Math.max(0.12, base + (this.w.parryWin || 0)); }
  weaponReach() { return this.w.reach; }
  playerBlockingLong() { return this.p.state === 'block' && this.t - this.p.blockStart > 0.6; }
  onEnemyWindup(c) {
    const G = this.game;
    if (!c.grab) G.fx.showTelegraph(c.act.tipPath(), c.red);
    else G.fx.hideTelegraph(false);
    if (c.red) {
      G.ui.warn(c.grab ? '⚠ 잡기 — 회피!' : '⚠ 가드 불가 — 회피!');
      G.audio.warn(); G.haptics.play('warn');
      this.enemy.setGlow(0xff2010, 0);
      if (c.grab) this.enemy.setArmorGlow(0.7);
    } else this.enemy.setGlow(0xff8a20, 0);
    if (!c.fake && Math.random() < (c.heavy ? 0.9 : 0.4)) G.audio.grunt(ARCH[this.fight.arch].voice, c.heavy ? 1.3 : 0.8);
  }
  onEnemyFeintEnd() { this.game.fx.hideTelegraph(); this.enemy.setGlow(null, 0); this.game.ui.hint(null); }
  onEnemyFeintSwitch(c) {
    const G = this.game;
    G.fx.showTelegraph(c.act.tipPath(), c.red);
    G.ui.popup('궤적 전환!', 'warn', 0.5, 0.36);
    G.audio.clang(0.25, 1.5);
  }
  onEnemyAttackEnd() { this.game.ui.hint(null); this.enemy.setArmorGlow(this.ai.phase >= 3 ? 0.45 : 0); }

  resolveEnemyImpact(c) {
    const G = this.game, p = this.p;
    G.fx.hideTelegraph(); G.ui.hint(null); G.ui.warn(null);
    this.enemy.setGlow(null, 0);
    if (c.grab) this.enemy.setArmorGlow(this.ai.phase >= 3 ? 0.45 : 0);
    if (p.state === 'dead' || this.over) return;
    // 회피
    if (p.state === 'dodge' && p.dodgeT >= TUNE.dodgeIFrom && p.dodgeT <= TUNE.dodgeITo) {
      const perfect = p.dodgeT <= TUNE.perfectDodge;
      if (perfect) {
        p.bullet = TUNE.bulletTime;
        G.slowmo(TUNE.bulletScale, TUNE.bulletTime);
        this.ai.forceRecover(TUNE.bulletTime * TUNE.bulletScale + 0.45);
        G.ui.bigText('회피! 반격 찬스', 'dodge'); G.ui.bullet(true);
        G.audio.slowIn(); G.haptics.play('dodge', true);
        this._rage(TUNE.rage.dodge);
        G.arena.setExcitement(0.5);
      } else G.ui.popup('회피', 'info', 0.5, 0.42);
      return;
    }
    // 방패 막기
    if (p.state === 'block' && !c.red && !c.grab) {
      const jg = this.t - p.blockStart <= this.sh.jg;
      this._shieldSparks(jg ? 34 : 18, jg);
      if (jg) {
        p.counterBuff = 2.0;
        G.ui.bigText('저스트 가드!', 'jg'); G.audio.shield(0.8); G.audio.clang(0.7, 1.35); G.haptics.play('justGuard', true);
        G.hitstop(TUNE.hitstop.block + 0.015); G.vm.blockHit(0.7); G.camRig.shake(0.12);
        this._rage(TUNE.rage.jg);
        G.arena.setExcitement(0.35);
      } else {
        p.shield -= c.dmg * (1 - this.sh.eff) * (c.heavy ? 2.1 : 1.6);
        G.audio.shield(c.heavy ? 1.2 : 0.9); G.haptics.play(c.heavy ? 'heavy' : 'block');
        G.vm.blockHit(c.heavy ? 1.6 : 1); G.camRig.push(0, 0, c.heavy ? 1.6 : 0.8); G.camRig.shake(c.heavy ? 0.3 : 0.14);
        G.hitstop(TUNE.hitstop.block);
        if (p.shield <= 0) {
          p.shield = 0; p.shieldBroken = true; p.shieldIdle = 0;
          G.vm.setBlock(false); p.state = 'stun'; p.stateT = TUNE.guardBreakStun;
          G.ui.bigText('가드 브레이크!', 'bad'); G.audio.guardBreak(1); G.haptics.play('guardBreak', true); G.camRig.shake(0.5);
        }
      }
      this.ai.onBlockedByPlayer();
      return;
    }
    // 피격
    this._playerHit(c);
  }

  _playerHit(c) {
    const G = this.game, p = this.p;
    const wasBlocking = p.state === 'block';
    const dmg = Math.round(c.dmg * (1 - this.ar.dr) * (c.grab ? 1.0 : 1));
    p.hp = Math.max(0, p.hp - dmg); p.dmgTaken += dmg;
    p.combo = 0; p.comboMul = 1; p.lastDir = -1;
    this._rage(dmg * TUNE.rage.taken);
    const k = Math.min(1, dmg / (p.maxHp * 0.25));
    G.ui.hurt(0.45 + k * 0.55); G.ui.popup('-' + dmg, 'pdmg', 0.5, 0.62);
    G.camRig.shake(0.3 + k * 0.4); G.camRig.push(c.dir ? c.dir[0] * 0.8 : 0, -0.3, 1.2 + k); G.camRig.kickRoll((c.dir ? -c.dir[0] : 0) * 2.2);
    G.vm.hurt(1 + k);
    G.audio.hit(0.8 + k * 0.4); G.haptics.play(c.heavy || c.grab ? 'heavy' : 'hurt', true);
    G.hitstop(c.heavy ? TUNE.hitstop.heavy : 0.05);
    G.fx.flash(G.camera.localToWorld(_v.set(0, -0.1, -0.6)), 0xff3020, 0.7);
    if (wasBlocking) { G.ui.popup('가드 불가!', 'bad', 0.5, 0.45); G.vm.setBlock(false); }
    if (c.grab) { G.ui.bigText('잡혔다!', 'bad'); G.audio.thud(1); G.camRig.push(0, 0.5, 2.4); }
    p.swing = null; p.buffer = null;
    if (p.hp <= 0) { this._playerDeath(); return; }
    p.state = 'stun'; p.stateT = c.heavy || c.grab ? 0.55 : 0.28;
    G.arena.setExcitement(0.25 + k * 0.4);
  }

  // ── 입력 ────────────────────────────────────────────────
  onTap() { if (this.p.state === 'intro' && this._introSkip) this._introSkip(); }
  onSwipe(sw) {
    const p = this.p, G = this.game;
    if (this.qte) { this._qteSwipe(sw); return; }
    if (p.state === 'intro') { this.onTap(); return; }
    if (!this.active || this.over) return;
    if (p.state === 'stun' || p.state === 'drink' || p.state === 'dead' || p.state === 'cine' || p.state === 'intro' || p.state === 'block') return;
    if (p.state === 'dodge') { if (p.dodgeT > 0.28) p.buffer = sw; return; }
    if (p.state === 'swing') { if (p.swing && p.swing.t > p.swing.dur * 0.38) p.buffer = sw; return; }
    // 방향 일치 패링 판정
    const c = this.ai.cur;
    if (c && !c.resolved && !c.fake && this.ai.state === 'attack' && c.t >= c.parryOpen && c.t <= c.impactT + 0.06) {
      if (c.red || c.grab) { this._deflect('red', sw); return; }
      const counter = angleOf(-c.dir[0], -c.dir[1]);
      const tol = this.tier.tol + (this.w.parryTol || 0);
      const diff = angDiff(sw.angle, counter);
      if (diff <= tol) { this._parry(sw, diff <= tol * 0.5 && c.impactT - c.t <= 0.13); return; }
      this._deflect('wrong', sw); return;
    }
    this._startSwing(sw);
  }
  onBlock(down) {
    const p = this.p, G = this.game;
    p.blockHeld = down;
    if (!this.active || this.over || this.qte) return;
    if (down) {
      if (p.shieldBroken) { G.ui.popup('방패 회복 중…', 'info', 0.5, 0.7); return; }
      if (p.state === 'idle' || (p.state === 'swing' && p.swing && p.swing.t > p.swing.dur * 0.55)) this._raiseBlock();
    } else if (p.state === 'block') { p.state = 'idle'; G.vm.setBlock(false); }
  }
  _raiseBlock() {
    const p = this.p, G = this.game;
    if (p.swing) p.swing = null;
    p.state = 'block'; p.blockStart = this.t; G.vm.setBlock(true);
    G.audio.whoosh(0.25, 1.6, 0);
  }
  onDodge(side) {
    const p = this.p, G = this.game;
    if (!this.active || this.over || this.qte) return;
    if (p.dodgeCd > 0 || ['stun', 'drink', 'dead', 'cine', 'intro', 'dodge'].includes(p.state)) return;
    if (p.state === 'block') G.vm.setBlock(false);
    p.swing = null; p.buffer = null;
    p.state = 'dodge'; p.dodgeT = 0; p.dodgeSide = side;
    G.camRig.dodge(side); G.vm.dodge(side); G.audio.dodge(); G.haptics.play('dodge');
    G.fx.dust(G.camera.getWorldPosition(_v).setY(0.05), 6, { scale: 0.8, a: 0.4 });
  }
  onPotion() {
    const p = this.p, G = this.game, s = G.save;
    if (!this.active || this.over || this.qte) return;
    if (p.state !== 'idle' && p.state !== 'block') return;
    if (p.hp >= p.maxHp) { G.ui.popup('체력이 가득하다', 'info', 0.5, 0.7); return; }
    let kind = null;
    if (s.potions > 0) { s.potions--; kind = 'potion'; } else if (s.elixirs > 0) { s.elixirs--; kind = 'elixir'; }
    if (!kind) { G.ui.popup('포션 없음', 'bad', 0.5, 0.7); G.audio.deny(); return; }
    G.saveNow();
    if (p.state === 'block') G.vm.setBlock(false);
    p.state = 'drink'; p.stateT = 0.95;
    G.vm.startDrink(); G.audio.drink(); G.haptics.play('potion');
    this.after(0.55, () => {
      const heal = Math.round(p.maxHp * (kind === 'potion' ? POTION.heal : ELIXIR.heal));
      p.healPending = (p.healPending || 0) + heal;
      if (kind === 'elixir') this._rage(ELIXIR.rage);
      G.fx.heal(); G.audio.heal();
      G.ui.popup('+' + heal, 'heal', 0.5, 0.6);
    });
  }
  onFinisher() {
    const p = this.p, G = this.game;
    if (!this.active || this.over || this.qte) return;
    if (p.rage < 100) { G.ui.popup('분노 부족', 'info', 0.5, 0.7); G.audio.deny(); return; }
    if (!['idle', 'block', 'swing'].includes(p.state)) return;
    this._startQTE('invictus');
  }
  onTrail(kind, x, y) {
    const fx = this.game.fx;
    if (kind === 'start') { fx.swipeColor = this.p.rage >= 100 ? 0xffc050 : this.p.counterBuff > 0 ? 0xffe08a : 0x9fd8ff; fx.swipeStart(x, y); }
    else if (kind === 'move') fx.swipeMove(x, y);
    else fx.swipeEnd();
  }

  // ── 플레이어 공격 ──────────────────────────────────────
  _startSwing(sw) {
    const p = this.p, G = this.game;
    const dur = this.w.swing * (p.bullet > 0 ? 0.85 : 1);
    p.state = 'swing';
    p.swing = { sw, t: 0, dur, impactAt: dur * G.vm.impactFrac, hit: false, reaction: this.ai.reactToSwing(sw) };
    G.vm.swing(sw.dx, sw.dy, dur, { color: p.rage >= 100 ? 0xffc040 : p.counterBuff > 0 ? 0xffe090 : 0xbfe4ff });
    const weight = this.game.save.weapon === 'axe' ? 1.5 : this.game.save.weapon === 'broadsword' ? 1.2 : 1;
    G.audio.whoosh(0.7 + Math.min(0.5, sw.speed / 4000), weight, sw.dx); G.haptics.play('swing');
    if (sw.feint) G.ui.popup('FEINT', 'feint', 0.5, 0.4);
  }

  _resolvePlayerHit(sw, reaction, second = false) {
    const G = this.game, p = this.p, g = this.enemy, e = this.e;
    if (g.dead || this.over) return;
    const hp = g.hitPoint(sw.dx, sw.dy, V3());
    if (reaction === 'dodge') {
      if (!second) { G.ui.popup('MISS', 'miss', 0.5, 0.4); p.combo = 0; p.comboMul = 1; }
      return;
    }
    const counter = p.counterBuff > 0;
    if (reaction === 'block' && !counter && !sw.feint && g.hasShield) {
      const sp = g.shieldPos(V3());
      G.fx.sparks(sp, _w.copy(G.camera.position).sub(sp), 18, { hdr: 4 }); G.fx.flash(sp, 0xffd0a0, 0.5);
      G.audio.blocked(1); G.haptics.play('blocked'); G.vm.deflect(); G.hitstop(TUNE.hitstop.block);
      G.ui.popup('막힘', 'block', 0.5, 0.42);
      p.combo = 0; p.comboMul = 1;
      e.guard -= 18 * this.w.guard; e.shieldHP -= this.w.dmg * this.w.guard * 1.25;
      this.enemy.hit(sw.dx * 0.4, 0, 0.35);
      if (e.shieldHP <= 0 && g.shield) {
        g.breakShield(sw.dx >= 0 ? 1 : -1);
        G.ui.bigText('방패 파괴!', 'good'); G.audio.guardBreak(1); G.audio.cheer(1.1); G.haptics.play('guardBreak', true);
        this._enemyStagger(TUNE.staggerGuardBreak + 0.3, 'break');
      } else if (e.guard <= 0) {
        e.guard = e.guardMax * 0.75;
        G.ui.bigText('가드 브레이크!', 'good'); G.audio.guardBreak(0.9); G.haptics.play('guardBreak', true);
        this._enemyStagger(TUNE.staggerGuardBreak, 'break');
      }
      return;
    }
    if (reaction === 'parry' && !counter && !second) {
      // 적이 내 공격을 패링
      G.fx.sparks(G.camera.localToWorld(_v.set(0, -0.05, -0.6)), _w.set(0, 0.3, 1).applyQuaternion(G.camera.quaternion), 30, { hdr: 5 });
      G.audio.parry(false); G.haptics.play('deflect', true); G.vm.deflect(); G.camRig.shake(0.3);
      G.ui.bigText('패링당했다!', 'bad');
      p.state = 'stun'; p.stateT = 0.55; p.swing = null; p.combo = 0; p.comboMul = 1;
      this.ai.state = 'recover'; this.ai.timer = 0.32; this.ai.counterQueued = true;
      this.enemy.hit(-sw.dx * 0.5, 0, 0.3);
      return;
    }
    // 적중
    const staggered = this.ai.state === 'stagger';
    if (!second) {
      if (this.t - p.lastHitT > TUNE.comboWindow) { p.combo = 0; p.comboMul = 1; p.lastDir = -1; }
      if (p.lastDir >= 0 && sw.dir8 !== p.lastDir) p.comboMul = Math.min(TUNE.comboMax, p.comboMul + TUNE.comboStep);
      else if (sw.dir8 === p.lastDir) p.comboMul = Math.max(1, p.comboMul - 0.25);
      p.lastDir = sw.dir8;
    }
    p.combo++; p.lastHitT = this.t; p.maxCombo = Math.max(p.maxCombo, p.combo); p.hits++;
    const heavy = this.game.save.weapon === 'axe';
    const outcome = this.ai.onHit(heavy || counter);
    const crit = counter || Math.random() < this.w.crit + (g.helmet ? 0 : 0.15);
    let mul = p.comboMul * (crit ? this.w.critMul : 1) * (staggered ? TUNE.staggerMul : 1) * (p.bullet > 0 ? TUNE.bulletMul : 1) * (sw.feint ? 1.3 : 1);
    mul *= clamp(0.9 + sw.speed / 9000, 0.9, 1.12);
    if (outcome === 'armor') { mul *= 0.65; if (!second) G.ui.popup('슈퍼아머', 'armor', 0.5, 0.33); }
    if (outcome === 'committed') mul *= 0.6;
    if (second) mul *= 0.85;
    const dmg = Math.max(1, Math.round(this.w.dmg * mul));
    e.hp = Math.max(0, e.hp - dmg);
    const pw = crit ? 1.4 : heavy ? 1.3 : 1;
    g.hit(sw.dx, sw.dy, pw * (outcome === 'armor' ? 0.4 : 1));
    const zone = zoneOf(sw.dy);
    const metal = (zone === 'high' && g.helmet) || g.look.cuirass;
    if (metal) { G.audio.armor(pw); G.fx.sparks(hp, _w.copy(G.camera.position).sub(hp), 14, { hdr: 4 }); }
    else G.audio.hit(pw, crit);
    G.fx.flash(hp, crit ? 0xfff0c0 : 0xffd8a8, crit ? 0.9 : 0.55);
    G.fx.sparks(hp, _w.set(sw.dx, sw.dy, 0.6), crit ? 22 : 10, { color: crit ? 0xfff0b0 : 0xffb070, hdr: crit ? 6 : 3.5, speed: [1.5, 4.5], life: [0.12, 0.3], size: 0.006 });
    G.hitstop(crit ? TUNE.hitstop.crit : TUNE.hitstop.light);
    G.camRig.push(sw.dx * 0.15, sw.dy * 0.1, -0.2); if (crit) G.camRig.shake(0.18);
    G.haptics.play(crit ? 'crit' : 'hit');
    const sp = G.ui.project(hp);
    G.ui.dmg(dmg, sp.x, sp.y, crit, staggered);
    if (crit && !second) G.ui.popup(counter ? 'COUNTER!' : 'CRIT!', 'crit', sp.x / innerWidth, sp.y / innerHeight - 0.06);
    this._rage(TUNE.rage.hit + (crit ? TUNE.rage.crit : 0));
    G.arena.setExcitement(Math.min(1, 0.12 + p.combo * 0.06));
    if (p.combo > 0 && p.combo % 5 === 0) G.audio.cheer(0.5 + Math.min(0.8, p.combo / 20));
    if (counter && !second) {
      p.counterBuff = 0;
      if (this.ai.state !== 'stagger') { G.ui.bigText('반격!', 'good'); this._enemyStagger(1.1, 'counter'); }
    }
    // 투구 파손
    if (zone === 'high' && g.helmet) {
      e.helmetHP -= dmg * (crit ? 1.5 : 1);
      if (e.helmetHP <= 0) { g.breakHelmet(sw.dx, -sw.dy); G.ui.bigText('투구 파괴!', 'good'); G.audio.clang(0.8, 0.7); G.audio.cheer(1.0); G.camRig.shake(0.2); }
    }
    if (e.hp <= 0) { this._koEnemy(sw); return; }
    this._checkPhase();
    if (this.ai.state === 'stagger' && !this.execTried && e.hp / e.maxHp <= ARCH[this.fight.arch].exec) this._startQTE('exec');
  }

  _parry(sw, perfect) {
    const G = this.game, p = this.p, c = this.ai.cur;
    c.resolved = true;
    G.fx.hideTelegraph(); G.ui.hint(null); this.enemy.setGlow(null, 0);
    this.ai.onParried();
    G.vm.swing(sw.dx, sw.dy, 0.16, { color: 0xfff0b0 }); G.vm.clash();
    const pt = G.camera.localToWorld(_v.set(c.dir[0] * 0.06, -0.03, -0.62));
    G.fx.sparks(pt, _w.set(0, 0.4, 1).applyQuaternion(G.camera.quaternion), perfect ? 60 : 38, { hdr: perfect ? 8 : 6, speed: [2, 8], spread: 1.1 });
    G.fx.flash(pt, 0xfff2d0, perfect ? 1.6 : 1.1);
    G.audio.parry(perfect); G.haptics.play(perfect ? 'perfect' : 'parry', true);
    G.hitstop(TUNE.hitstop.parry + (perfect ? 0.02 : 0)); G.slowmo(0.3, perfect ? 0.45 : 0.32);
    G.camRig.shake(perfect ? 0.38 : 0.28); G.camRig.punchFov(-5);
    G.ui.bigText(perfect ? 'PERFECT PARRY!' : 'PARRY!', perfect ? 'perfect' : 'parry');
    p.parries++; if (perfect) p.perfects++;
    this._rage(perfect ? TUNE.rage.perfect : TUNE.rage.parry);
    G.arena.setExcitement(perfect ? 0.8 : 0.55); G.audio.cheer(perfect ? 0.9 : 0.55);
    this._enemyStagger(perfect ? TUNE.staggerPerfect : TUNE.staggerParry, 'parry');
    if (!this.execTried && this.e.hp / this.e.maxHp <= ARCH[this.fight.arch].exec) this.after(0.28, () => { if (this.ai.state === 'stagger' && !this.qte && !this.over) this._startQTE('exec'); }, true);
  }
  _deflect(kind, sw) {
    const G = this.game, p = this.p;
    G.vm.swing(sw.dx, sw.dy, 0.18); G.vm.deflect();
    const pt = G.camera.localToWorld(_v.set(0, -0.06, -0.6));
    G.fx.sparks(pt, _w.set(-sw.dx, 0.3, 1).applyQuaternion(G.camera.quaternion), 16, { hdr: 3 });
    G.audio.clang(0.5, 0.7); G.haptics.play('deflect', true); G.camRig.shake(0.22);
    G.ui.bigText(kind === 'red' ? '가드 불가 공격!' : '튕겨냈다…', 'bad');
    p.state = 'stun'; p.stateT = TUNE.deflectStun; p.combo = 0; p.comboMul = 1;
  }
  _shieldSparks(n, jg) {
    const G = this.game;
    const pt = G.camera.localToWorld(_v.set(-0.02, -0.17, -0.62));
    G.fx.sparks(pt, _w.set(0, 0.35, 1).applyQuaternion(G.camera.quaternion), n, { hdr: jg ? 7 : 4.5, color: jg ? 0xcfe8ff : 0xffc060, speed: [2, 6.5], spread: 0.9 });
    G.fx.flash(pt, jg ? 0xd8f0ff : 0xffd6a0, jg ? 1.1 : 0.6);
  }
  _enemyStagger(dur, why) {
    const G = this.game;
    this.ai.stagger(dur);
    G.audio.stagger(); G.haptics.play('stagger');
    G.ui.stagger(true, dur);
    this.execTried = false;
  }
  _rage(v) {
    const p = this.p, was = p.rage;
    p.rage = clamp(p.rage + v, 0, 100);
    if (was < 100 && p.rage >= 100) { this.game.ui.popup('분노 MAX — 필살기!', 'rage', 0.5, 0.3); this.game.audio.clang(0.3, 1.8); this.game.haptics.play('ui'); }
  }

  _checkPhase() {
    if (this.fight.arch !== 'champion') return;
    const r = this.e.hp / this.e.maxHp, ai = this.ai, G = this.game, g = this.enemy;
    const go = (n) => {
      ai.phaseChange(1.7); ai.setPhase(n);
      G.audio.roar(0.85); G.audio.cheer(1.2); G.camRig.shake(0.35); G.camRig.push(0, 0, 1.4);
      this.after(0.45, () => {
        if (n === 2) { g.throwShield(1); g.style = 'sword2h'; g.twoHandOffset = -0.085; G.ui.bigText('2페이즈 — 방패를 버렸다!', 'boss'); }
        if (n === 3) { g.setArmorGlow(0.45); g.setGlow(0xff2010, 0.6); G.ui.bigText('3페이즈 — 광폭화!', 'boss'); }
      }, false);
    };
    if (ai.phase === 1 && r <= 0.66) go(2);
    else if (ai.phase === 2 && r <= 0.33) go(3);
  }

  // ── 처형 / 인빅투스 QTE ────────────────────────────────
  _startQTE(kind) {
    const G = this.game, p = this.p;
    if (this.qte || this.over) return;
    this.execTried = true;
    const n = this.tier.qte.n + (kind === 'invictus' ? 0 : 0);
    const arrows = [];
    let last = -1;
    for (let i = 0; i < n; i++) { let a; do { a = Math.floor(Math.random() * 8); } while (a === last || (this.tier.hint && a % 2 === 1 && Math.random() < 0.5)); last = a; arrows.push(a * 45); }
    this.qte = { kind, arrows, idx: 0, t: 0, time: this.tier.qte.time + (kind === 'invictus' ? 0.4 : 0), hits: [] };
    if (p.state === 'block') G.vm.setBlock(false);
    p.state = 'qte'; p.swing = null; p.buffer = null;
    if (kind === 'invictus') { p.rage = 0; G.audio.roar(1.25); }
    G.ui.clearBig();
    this.ai.stagger(99); G.fx.hideTelegraph(false); G.ui.hint(null); G.ui.warn(null);
    G.setSlow(0.12); G.audio.slowIn(); G.camRig.punchFov(-7); G.haptics.play('stagger', true);
    G.ui.qte(arrows, 0);
  }
  _qteSwipe(sw) {
    const q = this.qte, G = this.game, target = q.arrows[q.idx];
    if (angDiff(sw.angle, target) <= 40) {
      q.hits.push(sw); q.idx++;
      G.vm.swing(sw.dx, sw.dy, 0.2, { heavy: true, color: 0xffc040 });
      const hp = this.enemy.hitPoint(sw.dx, sw.dy, V3());
      G.fx.sparks(hp, _w.set(sw.dx, sw.dy, 0.5), 26, { color: 0xffe0a0, hdr: 6 }); G.fx.flash(hp, 0xffe8c0, 1.0);
      G.audio.execSlash(q.idx); G.haptics.play('crit', true); this.enemy.hit(sw.dx, sw.dy, 1.5); G.camRig.shake(0.22);
      G.ui.qte(q.arrows, q.idx);
      if (q.idx >= q.arrows.length) this._qteSuccess();
    } else this._qteFail();
  }
  _qteFail() {
    const G = this.game, q = this.qte, p = this.p;
    this.qte = null; G.ui.qte(null); G.setSlow(1); G.audio.slowOut();
    G.ui.bigText('실패…', 'bad');
    const dmg = Math.round(q.hits.length * this.w.dmg * 2.2);
    if (dmg > 0) { this.e.hp = Math.max(1, this.e.hp - dmg); const sp = G.ui.project(this.enemy.chestPos(V3())); G.ui.dmg(dmg, sp.x, sp.y, true, false); }
    p.state = 'idle';
    this.ai.stagger(0.45);
  }
  _qteSuccess() {
    const G = this.game, q = this.qte, e = this.e;
    this.qte = null; G.ui.qte(null);
    G.audio.cheer(1.2); G.arena.setExcitement(1);
    let lethal = q.kind === 'exec';
    let dmg = e.hp;
    if (!lethal) { dmg = Math.round(e.maxHp * TUNE.invictusDmg + this.w.dmg * 3); lethal = dmg >= e.hp; }
    this.p.execs++;
    this.after(0.12, () => this._cinematic(q.hits, lethal, dmg), true);
  }

  // 3연속 피니시 시네마틱
  _cinematic(hits, lethal, dmg) {
    const G = this.game, p = this.p, g = this.enemy, av = this.avatar;
    p.state = 'cine'; G.setSlow(0.85);
    G.vm.setVisible(false);
    av.root.position.set(0, 0, 0.05); av.setVisible(true); av.setStance('idle'); av.cape && (av.cape.ready = false);
    av.step(0, -(-this.ez - 1.5), 0.35);
    g.setStance('stagger');
    const dirs = hits.slice(0, 3).map((h) => [-h.dx, h.dy]);
    while (dirs.length < 3) dirs.push(pick([[1, 0], [-1, 0], [0, -1]]));
    const hand = G.save.weapon === 'dual' ? ['R', 'L', 'R'] : ['R', 'R', 'R'];
    const ez = this.ez, mz = (ez + 0.05) / 2 - 0.2, avz = 0.05 - (-ez - 1.5);
    const shots = [
      { dur: 1.0, from: { p: V3(2.5, 1.3, mz + 0.8), t: V3(0, 1.25, mz), fov: 44 }, to: { p: V3(2.25, 1.22, mz + 0.5), t: V3(0, 1.3, mz - 0.05), fov: 42 } },
      { dur: 0.95, from: { p: V3(-0.75, 1.78, ez - 1.6), t: V3(0, 1.45, avz + 0.2), fov: 40 }, to: { p: V3(-0.55, 1.7, ez - 1.35), t: V3(0, 1.45, avz + 0.1), fov: 38 } },
      { dur: 1.5, from: { p: V3(0.95, 0.55, ez + 1.2), t: V3(0, 1.45, ez), fov: 54 }, to: { p: V3(1.2, 0.5, ez + 1.45), t: V3(0, 1.5, ez), fov: 50 }, roll: 0.06 },
    ];
    const slash = (i) => {
      const [dx, dy] = dirs[i];
      const spec = swingSpec([dx, dy], { hand: hand[i], windup: 0.16, strike: 0.13, recover: i === 2 ? 0.5 : 0.25, lunge: 0.25, arc: 110 });
      const act = av.swing(spec);
      this.after(act.impactT, () => {
        const hp = g.hitPoint(-dx, dy, V3());
        G.fx.sparks(hp, _w.set(-dx, dy, 0.4), i === 2 ? 50 : 30, { color: 0xffe0a0, hdr: 7 }); G.fx.flash(hp, 0xfff0d0, i === 2 ? 1.8 : 1.1);
        G.audio.execSlash(i); G.haptics.play(i === 2 ? 'exec' : 'crit', true);
        g.hit(-dx, dy, 1.6); G.camRig.shake(i === 2 ? 0.45 : 0.25);
        G.hitstop(0.07);
        const part = i < 2 ? Math.round(dmg * 0.22) : 0;
        if (i < 2) { this.e.hp = Math.max(lethal ? 1 : 0, this.e.hp - part); }
        if (i === 2) {
          G.slowmo(0.12, 1.1);
          this.e.hp = lethal ? 0 : Math.max(1, this.e.hp - (dmg - 2 * Math.round(dmg * 0.22)));
          const sp = G.ui.project(hp); G.ui.dmg(dmg, sp.x, sp.y, true, true);
          if (lethal) { G.ui.flash(); this._koEnemy({ dx: -dx, dy }, true); }
          else { this.ai.stagger(1.6); G.ui.bigText('인빅투스!', 'rage'); }
        }
      }, false);
    };
    this.after(0.12, () => slash(0), true);
    this.after(1.05, () => slash(1), true);
    this.after(2.0, () => slash(2), true);
    G.camRig.playShots(shots, () => {
      if (lethal) return;
      av.setVisible(false); av.root.position.set(0, 0, 0.05);
      G.camRig.toFP(); G.vm.setVisible(true); G.setSlow(1);
      p.state = 'idle';
    });
  }

  // ── KO / 사망 ───────────────────────────────────────────
  _koEnemy(sw, cinematic = false) {
    const G = this.game, g = this.enemy;
    if (this.over) return;
    this.over = true; this.active = false;
    this.ai.kill(); g.ko(sw.dx || 1);
    G.fx.hideTelegraph(false); G.ui.hint(null); G.ui.warn(null); G.ui.stagger(false);
    G.audio.ko(); G.haptics.play('ko', true); G.arena.setExcitement(1);
    G.ui.bigText('KO!', 'ko');
    G.setSlow(0.2);
    const av = this.avatar;
    this.after(cinematic ? 0.6 : 0.3, () => {
      G.vm.setVisible(false);
      av.setVisible(true); av.setStance('victory');
      if (!cinematic) { av.root.position.set(0, 0, 0.05); av.cape && (av.cape.ready = false); }
      const c = V3(0, 1.0, this.ez);
      G.camRig.orbit({ center: c, a0: cinematic ? 0.9 : 0.12, a1: cinematic ? 2.3 : 1.95, r0: cinematic ? 2.2 : -this.ez, r1: 3.3, h0: cinematic ? 0.8 : 1.55, h1: 1.35, lookY: 0.85, dur: 2.8, fov: 48 });
    }, true);
    this.after(1.6, () => G.setSlow(1), true);
    this.after(3.9, () => this._finish(true), true);
  }
  _playerDeath() {
    const G = this.game, p = this.p, g = this.enemy;
    if (this.over) return;
    this.over = true; this.active = false; p.state = 'dead';
    G.fx.hideTelegraph(false); G.ui.hint(null); G.ui.warn(null);
    G.setSlow(0.3); G.audio.thud(1); G.audio.ooh(1); G.haptics.play('ko', true);
    G.vm.setVisible(false);
    const cp = G.camera.position.clone();
    G.camRig.playShots([{ dur: 1.4, from: { p: cp, t: V3(0, 1.3, this.ez), fov: G.engine.baseFov }, to: { p: V3(0.25, 0.35, 0.3), t: V3(0, 1.6, this.ez), fov: G.engine.baseFov + 6 }, roll: 0.5 }]);
    G.ui.death(true);
    this.after(0.6, () => { g.setStance('victory'); G.audio.roar(ARCH[this.fight.arch].voice); }, true);
    this.after(1.2, () => G.setSlow(1), true);
    this.after(2.6, () => this._finish(false), true);
  }

  _finish(victory) {
    const G = this.game, p = this.p, F = this.fight;
    if (this._done) return;
    this._done = true;
    const base = fightReward(F.lvl, F.boss);
    const perfectRun = victory && p.dmgTaken === 0;
    const res = {
      victory, mode: this.spec.mode, spec: this.spec,
      gold: victory ? Math.round(base.gold * (perfectRun ? 1.5 : 1) + p.maxCombo * 4) : Math.round(base.gold * 0.15 + p.hits * 2),
      gems: victory ? base.gems : 0,
      perfectRun, maxCombo: p.maxCombo, parries: p.parries, perfects: p.perfects, dmgTaken: Math.round(p.dmgTaken), execs: p.execs,
      hpLeft: p.hp, rageLeft: p.rage,
    };
    G.onBattleEnd(res);
  }

  dispose() {
    const G = this.game;
    this.enemy && this.enemy.dispose();
    this.avatar && this.avatar.dispose();
    G.fx.hideTelegraph(false);
    G.ui.stagger(false); G.ui.bullet(false); G.ui.death(false); G.ui.qte(null); G.ui.hint(null); G.ui.warn(null);
    G.ui.vsCard(null); G.ui.introMode(false); G.ui.clearBig();
  }

  // ── 매 프레임 ──────────────────────────────────────────
  update(dt, dtReal) {
    const G = this.game, p = this.p;
    this.t += dt;
    // 타이머
    for (let i = this.timers.length - 1; i >= 0; i--) {
      const tm = this.timers[i];
      tm.t -= tm.real ? dtReal : dt;
      if (tm.t <= 0) { this.timers.splice(i, 1); tm.fn(); }
    }
    if (this.active && !this.qte && p.state !== 'cine') this.ai.update(dt);
    this._updPlayer(dt, dtReal);
    // 예고 궤적 진행도·발광
    const c = this.ai && this.ai.cur;
    if (c && (this.ai.state === 'attack' || this.ai.state === 'feint') && !c.resolved) {
      const prog = clamp(c.t / c.impactT, 0, 1);
      const open = !c.fake && c.t >= c.parryOpen;
      G.fx.setTelegraph(prog, open ? 0.55 + 0.45 * Math.sin(this.t * 40) : 0);
      this.enemy.setGlow(null, (c.red ? 3.2 : 2.2) * prog * prog + (open ? 1.2 : 0));
      if (this.tier.hint && open && !c.red && !c.grab && c.dir) G.ui.hint(angleOf(-c.dir[0], -c.dir[1]));
    }
    // 적/아바타 애니메이션
    if (this.enemy) {
      this.enemy.update(dt);
      if (this.avatar.root.visible) this.avatar.update(dt);
    }
    // QTE 타이머 (실시간)
    if (this.qte) {
      this.qte.t += dtReal;
      G.ui.qteTimer(1 - this.qte.t / this.qte.time);
      if (this.qte.t >= this.qte.time) this._qteFail();
    }
    // HUD
    G.ui.hud({
      php: p.hp, pmax: p.maxHp, psh: p.shield, pshmax: this.sh.max, shBroken: p.shieldBroken, rage: p.rage,
      ehp: this.e ? this.e.hp : 0, emax: this.e ? this.e.maxHp : 1, combo: p.combo, mul: p.comboMul,
      comboAlive: this.t - p.lastHitT < TUNE.comboWindow, potions: G.save.potions, elixirs: G.save.elixirs,
      helmet: !!(this.enemy && this.enemy.helmet), shield: !!(this.enemy && this.enemy.shield), boss: !!this.fight.boss, phase: this.ai ? this.ai.phase : 1,
      counter: p.counterBuff > 0,
    });
    G.vm.setRage(p.rage >= 100 ? 1 : 0);
    if (p.rage >= 100 && Math.random() < dtReal * 12 && G.vm.root.visible) G.fx.embers(G.camera.localToWorld(_v.set(0.1 + Math.random() * 0.1, -0.15, -0.6)), 1, 0xffb040);
  }

  _updPlayer(dt, dtReal) {
    const p = this.p, G = this.game;
    if (p.counterBuff > 0) p.counterBuff -= dt;
    if (p.bullet > 0) { p.bullet -= dtReal; if (p.bullet <= 0) { G.ui.bullet(false); G.audio.slowOut(); } }
    if (p.dodgeCd > 0) p.dodgeCd -= dt;
    if (p.healPending > 0) { const h = Math.min(p.healPending, p.maxHp * 0.9 * dt); p.hp = Math.min(p.maxHp, p.hp + h); p.healPending -= h; }
    // 방패 내구도 회복
    if (p.state !== 'block') {
      p.shieldIdle += dt;
      if (p.shieldIdle > TUNE.shieldDelay || p.shieldBroken) p.shield = Math.min(this.sh.max, p.shield + this.sh.regen * dt * (p.shieldBroken ? 1.4 : 1));
      if (p.shieldBroken && p.shield >= this.sh.max * 0.3) { p.shieldBroken = false; G.ui.popup('방패 회복', 'info', 0.5, 0.7); }
    } else p.shieldIdle = 0;
    // 빈사 심장 박동
    const hr = p.hp / p.maxHp;
    G.ui.lowHP(hr < 0.3 && p.state !== 'dead');
    if (hr < 0.3 && p.state !== 'dead' && !this.over) {
      p.hbT -= dtReal;
      if (p.hbT <= 0) { G.audio.heartbeat(1 - hr * 2); p.hbT = 0.55 + hr * 1.6; }
    }
    switch (p.state) {
      case 'swing': {
        const s = p.swing;
        if (!s) { p.state = 'idle'; break; }
        s.t += dt;
        if (!s.hit && s.t >= s.impactAt) {
          s.hit = true;
          this._resolvePlayerHit(s.sw, s.reaction);
          if (G.save.weapon === 'dual' && p.state === 'swing') {
            const sw2 = s.sw, r2 = s.reaction;
            this.after(0.085, () => { if (!this.over) { G.vm.swing(sw2.dx, sw2.dy, 0.17, { hand: G.vm.swingL ? 'R' : 'L' }); this._resolvePlayerHit(sw2, r2, true); } });
          }
        }
        if (p.state === 'swing' && s.t >= s.dur) {
          p.swing = null; p.state = 'idle';
          if (p.buffer) { const b = p.buffer; p.buffer = null; this.onSwipe(b); }
          else if (p.blockHeld && !p.shieldBroken) this._raiseBlock();
        }
        break;
      }
      case 'dodge':
        p.dodgeT += dt;
        if (p.dodgeT >= TUNE.dodgeDur) {
          p.state = 'idle'; p.dodgeCd = TUNE.dodgeCd;
          if (p.buffer) { const b = p.buffer; p.buffer = null; this.onSwipe(b); }
          else if (p.blockHeld && !p.shieldBroken) this._raiseBlock();
        }
        break;
      case 'stun': case 'drink':
        p.stateT -= dt;
        if (p.stateT <= 0) { p.state = 'idle'; if (p.blockHeld && !p.shieldBroken) this._raiseBlock(); }
        break;
      case 'block':
        if (p.shieldBroken) { p.state = 'idle'; G.vm.setBlock(false); }
        break;
    }
  }
}
