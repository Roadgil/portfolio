// ─────────────────────────────────────────────────────────────
//  INVICTUS — 부트스트랩, 게임 루프, 시간 제어(히트스톱·슬로우모션), 화면 흐름
// ─────────────────────────────────────────────────────────────
import * as THREE from 'three';
import { Engine } from './engine.js';
import { buildLibrary, genShieldFace } from './textures.js';
import { Arena } from './arena.js';
import { FX } from './fx.js';
import { CameraRig } from './camera.js';
import { Viewmodel } from './viewmodel.js';
import { Gladiator, makeLook, playerLook } from './gladiator.js';
import { Battle } from './combat.js';
import { UI } from './ui.js';
import { SwipeInput } from './input.js';
import { AudioFX, Haptics } from './audio.js';
import { loadSave, writeSave, flushSave, resetSave } from './save.js';
import { TIERS, LIGHTS, QUALITY, endlessFight, sector8 } from './config.js';

const $ = (id) => document.getElementById(id);
const nextFrame = () => new Promise((r) => requestAnimationFrame(() => r()));

class Game {
  constructor() {
    this.battle = null; this.paused = false;
    this.timeScale = 1; this.slowTarget = 1; this.pulse = null; this.freeze = 0;
    this.arenaT = 0; this.last = 0; this.menuT = 0;
  }

  async boot() {
    const s = this.save = loadSave();
    this.audio = new AudioFX(); this.audio.on = s.settings.sound;
    this.haptics = new Haptics(); this.haptics.on = s.settings.haptics;
    this.ui = new UI(this);
    const unlock = () => this.audio.unlock();
    for (const ev of ['pointerdown', 'touchend', 'keydown']) window.addEventListener(ev, unlock, { capture: true, passive: true });

    this.ui.loading(0.04, '렌더러 초기화…');
    const E = this.engine = new Engine($('stage'), s.settings.quality);
    E.setFpsMode(s.settings.fps);
    const refreshP = E.measureRefresh();
    this.scene = E.scene; this.camera = E.camera;
    const texSize = (QUALITY[s.settings.quality] || QUALITY.high).tex;
    this.lib = await buildLibrary(E.renderer, texSize, (p) => this.ui.loading(0.05 + p * 0.7, '절차적 텍스처 생성 중…'));
    const faceCache = new Map();
    this.lib.shieldFace = (type, colors, seed) => {
      const k = type + colors.join() + seed;
      if (!faceCache.has(k)) faceCache.set(k, genShieldFace(type, colors[0], colors[1], seed));
      return faceCache.get(k);
    };
    this.ui.loading(0.8, '콜로세움 건설 중…'); await nextFrame();
    this.arena = new Arena(this.lib, E, E.q);
    this.fx = new FX(this.scene, this.camera, E);
    this.fx.onBounce = (d, k) => this.audio.clang(0.18 * k, 0.55);
    this.camRig = new CameraRig(this.camera, E);
    this.vm = new Viewmodel(this.camera, this.lib, this.fx);
    this.vm.equip(s); this.vm.setVisible(false);
    this.input = new SwipeInput($('touch'), {
      onSwipe: (sw) => this.battle && this.battle.onSwipe(sw),
      onTrail: (k, x, y) => this.battle && this.battle.onTrail(k, x, y),
      onTap: (x, y) => this.battle && this.battle.onTap(x, y),
    });
    this.arena.setLighting(LIGHTS.golden);
    this.refreshMenuScene();
    this.ui.loading(0.9, '셰이더 컴파일 중…'); await nextFrame();
    this._precompile();
    await refreshP;
    this.ui.loading(1, '');
    window.__gameBooted = true; clearTimeout(window.__bootT);
    this.ui.show('scrMenu');
    this._wireSystem();
    requestAnimationFrame((t) => { this.last = t; this._loop(t); });
  }

  _precompile() {
    // 파티클/트레일/예고 메시를 잠시 보이게 하여 셰이더를 미리 컴파일 → 전투 중 끊김 방지
    const hidden = [];
    this.scene.traverse((o) => { if ((o.isMesh || o.isPoints) && !o.visible) { hidden.push(o); o.visible = true; } });
    const tmp = new Gladiator(makeLook('champion', 1), this.lib, {});
    tmp.addTo(this.scene); tmp.root.position.set(0, 0, -30);
    try { this.engine.renderer.compile(this.scene, this.camera); } catch (e) { console.warn('precompile', e); }
    tmp.dispose();
    for (const o of hidden) o.visible = false;
  }

  _wireSystem() {
    // 뒤로가기 제스처 → 일시정지/이전 화면
    history.pushState({ g: 1 }, '');
    window.addEventListener('popstate', () => {
      if (this.battle && !this.battle.over) { history.pushState({ g: 1 }, ''); this.paused ? this.resume() : this.pause(); return; }
      const cur = this.ui.current();
      if (cur && cur !== 'scrMenu') { history.pushState({ g: 1 }, ''); this.ui.back(); }
    });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) { if (this.battle && !this.battle.over) this.pause(); if (this.audio.ctx) this.audio.ctx.suspend().catch(() => {}); flushSave(this.save); }
      else if (this.audio.ctx && this.save.settings.sound) this.audio.ctx.resume().catch(() => {});
    });
    document.addEventListener('contextmenu', (e) => e.preventDefault());
    document.addEventListener('gesturestart', (e) => e.preventDefault());
    document.addEventListener('touchmove', (e) => { if (!e.target.closest || !e.target.closest('.screen')) e.preventDefault(); }, { passive: false });
    document.addEventListener('dblclick', (e) => e.preventDefault());
    // 키보드
    const KEYDIR = { Numpad6: 0, Numpad9: 45, Numpad8: 90, Numpad7: 135, Numpad4: 180, Numpad1: 225, Numpad2: 270, Numpad3: 315, KeyL: 0, KeyO: 45, KeyI: 90, KeyU: 135, KeyJ: 180, KeyM: 225, KeyK: 270, Period: 315, Comma: 270 };
    window.addEventListener('keydown', (e) => {
      if (e.repeat) return;
      const B = this.battle;
      if (e.code === 'Escape' || e.code === 'KeyP') { if (B && !B.over) this.paused ? this.resume() : this.pause(); return; }
      if (!B || this.paused) return;
      if (e.code === 'ArrowLeft' || e.code === 'KeyA') B.onDodge(-1);
      else if (e.code === 'ArrowRight' || e.code === 'KeyD') B.onDodge(1);
      else if (e.code === 'Space' || e.code === 'KeyS' || e.code === 'ArrowDown') { e.preventDefault(); B.onBlock(true); }
      else if (e.code === 'KeyQ') B.onPotion();
      else if (e.code === 'KeyE' || e.code === 'KeyF') B.onFinisher();
      else if (e.code in KEYDIR) { const a = KEYDIR[e.code], r = a * Math.PI / 180; B.onSwipe({ angle: a, dir8: sector8(a), feint: false, dx: Math.cos(r), dy: Math.sin(r), speed: 1500, len: 150, dur: 0.1 }); }
      else if (e.code === 'Enter') B.onTap();
    });
    window.addEventListener('keyup', (e) => {
      if (this.battle && (e.code === 'Space' || e.code === 'KeyS' || e.code === 'ArrowDown')) this.battle.onBlock(false);
    });
    if ('serviceWorker' in navigator && (location.protocol === 'https:' || location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
      navigator.serviceWorker.register('./sw.js').catch(() => {});
    }
  }

  // ── 시간 제어 ──────────────────────────────────────────
  hitstop(sec) { this.freeze = Math.max(this.freeze, sec); }
  slowmo(scale, dur) { this.pulse = { scale, t: dur }; }
  setSlow(scale) { this.slowTarget = scale; }

  _loop(now) {
    requestAnimationFrame((t) => this._loop(t));
    const E = this.engine;
    const rawMs = now - this.last;
    if (E.fpsCap && rawMs < 1000 / E.fpsCap - 2.5) return;
    this.last = now;
    const dtReal = Math.min(0.05, Math.max(0.0001, rawMs / 1000));
    let target = this.slowTarget;
    if (this.pulse) { this.pulse.t -= dtReal; target = Math.min(target, this.pulse.scale); if (this.pulse.t <= 0) this.pulse = null; }
    if (target < this.timeScale) this.timeScale = target;
    else this.timeScale += (target - this.timeScale) * Math.min(1, dtReal * 7);
    if (Math.abs(this.timeScale - (this._lastSlow ?? 1)) > 0.04) { this.audio.setSlow(this.timeScale); this._lastSlow = this.timeScale; }
    let dt = dtReal * this.timeScale;
    if (this.freeze > 0) { this.freeze -= dtReal; dt = 0; }
    if (this.paused) dt = 0;
    const dtR = this.paused ? 0 : dtReal;
    if (this.battle) this.battle.update(dt, dtR);
    else this._menuUpdate(dt, dtReal);
    this.fx.update(dt, dtR);
    this.vm.update(dt, dtR);
    if (this.battle) this.camRig.update(dtR, this.battle.enemy ? this.battle.enemy.chestPos(new THREE.Vector3()) : null);
    this.arenaT += dt;
    this.arena.update(dt, this.arenaT, this.camera);
    this.audio.setCrowd(this.arena.excite);
    E.render();
    E.monitor(rawMs, now);
  }

  // ── 메뉴 배경 (다음 상대 또는 무기고에서 내 검투사) ─────
  refreshMenuScene(who) {
    if (this.battle) return;
    if (this.menuG) { this.menuG.dispose(); this.menuG = null; }
    this.fx.clearDebris();
    const nx = this.nextFight();
    const T = TIERS[Math.min(nx.tier, TIERS.length - 1)];
    const F = T.fights[Math.min(nx.fight, T.fights.length - 1)];
    const showPlayer = who === 'player' || (!who && this.ui.current() === 'scrArmory');
    this.menuWho = showPlayer ? 'player' : 'enemy';
    const look = showPlayer ? playerLook(this.save) : makeLook(F.arch, (F.name.length * 131 + F.lvl * 17) | 0);
    this.menuG = new Gladiator(look, this.lib, { fx: this.fx });
    this.menuG.root.position.set(0, 0, -2.2);
    this.menuG.addTo(this.scene);
    this.menuG.setStance('idle');
    this.menuLight = T.light;
    this.arena.setLighting(LIGHTS[T.light]);
    this.vm.equip(this.save);
  }
  _menuUpdate(dt, dtReal) {
    this.menuT += dtReal;
    const g = this.menuG;
    if (g) {
      if (Math.random() < dtReal * 0.08 && g.stance === 'idle') { g.setStance('taunt'); setTimeout(() => g.stance === 'taunt' && g.setStance('idle'), 1800); }
      g.update(dt);
    }
    const a = this.menuT * 0.09 + 0.6, r = 4.4;
    this.camera.position.set(Math.sin(a) * r, 1.55 + Math.sin(this.menuT * 0.27) * 0.18, -2.2 + Math.cos(a) * r);
    this.camera.lookAt(0, 1.15, -2.2);
    if (Math.abs(this.camera.fov - 48) > 0.01) { this.camera.fov = 48; this.camera.updateProjectionMatrix(); }
  }
  onScreen(id) {
    if (this.battle || !this.menuG || (id !== 'scrArmory' && id !== 'scrMenu')) return;
    const who = id === 'scrArmory' ? 'player' : 'enemy';
    if (who !== this.menuWho) this.refreshMenuScene(who);
  }

  // ── 진행 ───────────────────────────────────────────────
  nextFight() { return { tier: this.save.tier, fight: this.save.fight }; }
  startTour(ti, fi) {
    const T = TIERS[ti], F = T.fights[fi];
    this._beginBattle({ mode: 'tour', tier: ti, fightIdx: fi, fight: F, light: T.light });
  }
  startEndless(carry) {
    const wave = carry ? carry.wave + 1 : 1;
    const F = endlessFight(wave);
    this._beginBattle({ mode: 'endless', wave, fight: F, light: F.light, carryHp: carry ? carry.hp : null, carryRage: carry ? carry.rage : 0 });
  }
  _beginBattle(spec) {
    if (this.battle) this._endBattle();
    if (this.menuG) { this.menuG.dispose(); this.menuG = null; }
    this.ui.stack = []; this.ui.show(null);
    this.paused = false; this.timeScale = 1; this.slowTarget = 1; this.pulse = null; this.freeze = 0;
    this._tryFullscreen();
    this.audio.unlock();
    this.battle = new Battle(this, spec);
    this.battle.start();
  }
  _tryFullscreen() {
    if (!this.save.settings.fullscreen) return;
    const standalone = matchMedia('(display-mode: fullscreen)').matches || matchMedia('(display-mode: standalone)').matches;
    const d = document.documentElement;
    if (!standalone && !document.fullscreenElement && d.requestFullscreen && matchMedia('(pointer: coarse)').matches) {
      d.requestFullscreen({ navigationUI: 'hide' }).then(() => { if (screen.orientation && screen.orientation.lock) screen.orientation.lock('portrait').catch(() => {}); }).catch(() => {});
    }
  }
  onBattleEnd(res) {
    const s = this.save, spec = res.spec, B = this.battle;
    s.gold += res.gold; s.gems += res.gems;
    s.stats.parries += res.parries; s.stats.perfect += res.perfects; s.stats.executions += res.execs;
    s.stats.maxCombo = Math.max(s.stats.maxCombo, res.maxCombo);
    if (res.victory) s.stats.wins++; else s.stats.losses++;
    const buttons = [];
    if (spec.mode === 'tour') {
      const T = TIERS[spec.tier], key = `${spec.tier}-${spec.fightIdx}`;
      if (res.victory) {
        const first = !s.beaten[key];
        s.beaten[key] = true;
        if (first) { const g = spec.fight.boss ? 5 : 1; s.gems += g; res.gems += g; }
        if (spec.tier === s.tier && spec.fightIdx === s.fight) { s.fight++; if (s.fight >= T.fights.length) { s.tier++; s.fight = 0; } }
        if (T.fights.every((_, i) => s.beaten[`${spec.tier}-${i}`]) && !s.cleared.includes(T.id)) {
          s.cleared.push(T.id); s.gold += T.clear.gold; s.gems += T.clear.gems; res.gold += T.clear.gold; res.gems += T.clear.gems;
          res.sub = `${T.name} 정복! 클리어 보너스 지급` + (spec.fight.boss ? ' — 당신은 이제 콜로세움의 챔피언이다.' : '');
        } else res.sub = res.perfectRun ? '무결점 승리! 관중이 열광한다' : `${spec.fight.name}을(를) 쓰러뜨렸다`;
        const nx = this.nextFight();
        if (TIERS[nx.tier]) buttons.push({ label: '다음 경기 ›', cls: 'primary', fn: () => this.startTour(nx.tier, nx.fight) });
        else buttons.push({ label: '무한 아레나 도전', cls: 'primary', fn: () => this.startEndless() });
      } else {
        res.sub = '모래 위에 쓰러졌다… 장비를 강화하고 다시 도전하라';
        buttons.push({ label: '다시 도전', cls: 'primary', fn: () => this.startTour(spec.tier, spec.fightIdx) });
      }
      buttons.push({ label: '무기고', fn: () => { this._endBattle(); this.ui.stack = ['scrMenu']; this.ui.show('scrArmory'); this.refreshMenuScene('player'); } });
      buttons.push({ label: '메인 메뉴', cls: 'ghost', fn: () => this.toMenu() });
    } else {
      if (res.victory) {
        s.bestWave = Math.max(s.bestWave, spec.wave);
        if (spec.wave % 5 === 0) { s.gems += 2; res.gems += 2; }
        res.sub = `체력 일부 회복 후 다음 상대가 입장한다 (최고 기록 ${s.bestWave})`;
        const carry = { wave: spec.wave, hp: Math.min(B.p.maxHp, res.hpLeft + B.p.maxHp * 0.3), rage: res.rageLeft };
        buttons.push({ label: `웨이브 ${spec.wave + 1} ›`, cls: 'primary', fn: () => this.startEndless(carry) });
        buttons.push({ label: '여기서 그만두기', cls: 'ghost', fn: () => this.toMenu() });
      } else {
        res.sub = `웨이브 ${spec.wave}에서 전사 · 최고 기록 ${s.bestWave}웨이브`;
        buttons.push({ label: '처음부터 다시', cls: 'primary', fn: () => this.startEndless() });
        buttons.push({ label: '메인 메뉴', cls: 'ghost', fn: () => this.toMenu() });
      }
    }
    flushSave(s);
    this.ui.battleHUD(false);
    this.ui.result(res, buttons);
    this.haptics.play(res.victory ? 'perfect' : 'hurt', true);
  }
  _endBattle() {
    if (!this.battle) return;
    this.battle.dispose(); this.battle = null;
    this.fx.clearDebris();
    this.ui.battleHUD(false); this.vm.setVisible(false);
    this.camRig.toFP(); this.paused = false;
    this.timeScale = 1; this.slowTarget = 1; this.pulse = null;
    this.audio.setSlow(1);
  }
  toMenu() { this._endBattle(); this.ui.stack = []; this.ui.show('scrMenu'); this.refreshMenuScene('enemy'); }

  pause() {
    if (!this.battle || this.battle.over || this.paused) return;
    this.paused = true; this.battle.onBlock(false);
    this.ui.stack = []; this.ui.show('scrPause');
  }
  resume() { this.paused = false; this.ui.stack = []; this.ui.show(null); }
  forfeit() {
    if (!this.battle) return;
    this.paused = false; this.ui.show(null);
    const B = this.battle; B.over = true; B.active = false;
    B._finish(false);
  }

  // ── 설정 ───────────────────────────────────────────────
  saveNow() { writeSave(this.save); }
  setSetting(k, v) {
    const st = this.save.settings; st[k] = v;
    if (k === 'sound') this.audio.setEnabled(v);
    if (k === 'haptics') this.haptics.on = v;
    if (k === 'quality') { this.engine.setQuality(v); this.ui.toast('텍스처 해상도는 다음 실행 때 적용됩니다'); }
    if (k === 'fps') this.engine.setFpsMode(v);
    this.saveNow();
  }
  toggleSound() { this.setSetting('sound', !this.save.settings.sound); this.ui.syncMute(); }
  resetProgress() {
    const keep = this.save.settings;
    this.save = resetSave(); this.save.settings = keep;
    flushSave(this.save);
    this.ui.stack = []; this.ui.show('scrMenu'); this.refreshMenuScene('enemy');
    this.ui.toast('진행 데이터를 초기화했습니다');
  }
}

const game = new Game();
window.__game = game;
game.boot().catch((e) => {
  console.error(e);
  const msg = (e && e.message) || String(e);
  const el = document.getElementById('loadErr');
  if (el) { el.textContent = '초기화 실패: ' + msg + ' — WebGL2를 지원하는 최신 Chrome에서 실행해 주세요.'; el.classList.remove('hidden'); }
});
