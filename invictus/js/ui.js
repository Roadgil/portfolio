// ─────────────────────────────────────────────────────────────
//  한국어 UI: 메뉴·토너먼트·무기고·설정·HUD·팝업·QTE
// ─────────────────────────────────────────────────────────────
import * as THREE from 'three';
import {
  WEAPONS, WEAPON_ORDER, MAX_LVL, upgradeCost, weaponStats, shieldStats, armorStats, SHIELD_UP_BASE, ARMOR_UP_BASE,
  POTION, ELIXIR, TIERS, ARCH, VERSION, LIGHTS,
} from './config.js';

const $ = (id) => document.getElementById(id);
const ARROW_SVG = '<svg viewBox="0 0 100 40"><path d="M4 20h70M60 6l26 14-26 14" fill="none" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/></svg>';
const WEAPON_SVG = {
  gladius: '<svg viewBox="0 0 64 64"><path d="M32 4l5 9v28h-10V13z" fill="#d9dde4"/><path d="M32 4l5 9v28h-5z" fill="#9aa3ae"/><rect x="21" y="41" width="22" height="5" rx="2" fill="#c9a043"/><rect x="29" y="46" width="6" height="10" fill="#5a3a22"/><circle cx="32" cy="58" r="4" fill="#c9a043"/></svg>',
  broadsword: '<svg viewBox="0 0 64 64"><path d="M32 2l4 6v34h-8V8z" fill="#e2e6ec"/><path d="M32 2l4 6v34h-4z" fill="#9aa3ae"/><rect x="16" y="42" width="32" height="4" rx="2" fill="#c9a043"/><rect x="29.5" y="46" width="5" height="11" fill="#5a3a22"/><circle cx="32" cy="59" r="3.5" fill="#c9a043"/></svg>',
  dual: '<svg viewBox="0 0 64 64"><g transform="rotate(-28 32 32)"><path d="M32 6l3.5 7v24h-7V13z" fill="#d9dde4"/><rect x="24" y="37" width="16" height="4" rx="2" fill="#9a7a33"/><rect x="30" y="41" width="4" height="9" fill="#3a2a1a"/></g><g transform="rotate(28 32 32)"><path d="M32 6l3.5 7v24h-7V13z" fill="#c8ccd4"/><rect x="24" y="37" width="16" height="4" rx="2" fill="#9a7a33"/><rect x="30" y="41" width="4" height="9" fill="#3a2a1a"/></g></svg>',
  axe: '<svg viewBox="0 0 64 64"><rect x="30" y="6" width="5" height="54" rx="2" fill="#7a5230"/><path d="M34 10c10 0 18 4 22 12-4 8-12 12-22 12z" fill="#cfd4dc"/><path d="M34 10c10 0 18 4 22 12h-22z" fill="#a2a9b4"/><rect x="28" y="40" width="9" height="12" rx="2" fill="#3a2414"/></svg>',
  shield: '<svg viewBox="0 0 64 64"><path d="M14 8h36c2 0 3 1 3 3v40c0 2-1 3-3 3H14c-2 0-3-1-3-3V11c0-2 1-3 3-3z" fill="#8e1b16"/><path d="M14 8h36c2 0 3 1 3 3v40c0 2-1 3-3 3H14c-2 0-3-1-3-3V11c0-2 1-3 3-3z" fill="none" stroke="#d2a645" stroke-width="3"/><circle cx="32" cy="31" r="7" fill="#d2a645"/><path d="M32 12l3 9-3 3-3-3zM32 50l3-9-3-3-3 3z" fill="#d2a645"/></svg>',
  armor: '<svg viewBox="0 0 64 64"><path d="M20 8l12 6 12-6 10 8-4 12v26H14V28l-4-12z" fill="#b98a3e"/><path d="M24 26c4 3 12 3 16 0M24 34c4 3 12 3 16 0M26 42c3 2 9 2 12 0" fill="none" stroke="#6a4a1a" stroke-width="2.5" stroke-linecap="round"/><path d="M32 14v40" stroke="#e8c46a" stroke-width="1.5"/></svg>',
  potion: '<svg viewBox="0 0 64 64"><path d="M26 6h12v5h-2v11l12 20a8 8 0 0 1-7 12H23a8 8 0 0 1-7-12l12-20V11h-2z" fill="#cfe8ff" opacity=".85"/><path d="M19 42h26l3 5a5 5 0 0 1-4 7H20a5 5 0 0 1-4-7z" fill="#e01a2a"/></svg>',
  elixir: '<svg viewBox="0 0 64 64"><path d="M26 6h12v5h-2v11l12 20a8 8 0 0 1-7 12H23a8 8 0 0 1-7-12l12-20V11h-2z" fill="#e8f6ff" opacity=".85"/><path d="M19 38h26l5 8a5 5 0 0 1-4 8H18a5 5 0 0 1-4-8z" fill="#ffb52e"/><path d="M32 30l2 5 5 1-4 3 1 5-4-3-4 3 1-5-4-3 5-1z" fill="#fff6c0"/></svg>',
};
const fmt = (n) => Math.round(n).toLocaleString('ko-KR');

export class UI {
  constructor(game) {
    this.g = game;
    this.screens = {};
    for (const s of document.querySelectorAll('.screen')) this.screens[s.id] = s;
    this.stack = [];
    this.popPool = [];
    this.hudCache = {};
    $('ver').textContent = 'v' + VERSION;
    this._wire();
  }

  // ── 화면 전환 ──────────────────────────────────────────
  show(id, push = true) {
    for (const k in this.screens) this.screens[k].classList.remove('show');
    if (id) {
      this.screens[id].classList.add('show');
      if (push && this.stack[this.stack.length - 1] !== id) this.stack.push(id);
      if (id === 'scrMenu') this.renderMenu();
      if (id === 'scrTour') this.renderTour();
      if (id === 'scrArmory') this.renderArmory();
      if (id === 'scrSet') this.renderSettings();
    }
    if (this.g.onScreen) this.g.onScreen(id);
  }
  back() {
    this.g.audio.click();
    this.stack.pop();
    const prev = this.stack[this.stack.length - 1];
    if (prev) this.show(prev, false);
    else this.show(this.g.battle ? null : 'scrMenu');
  }
  current() { return this.stack[this.stack.length - 1]; }
  loading(p, label) { $('loadFill').style.width = Math.round(p * 100) + '%'; if (label) $('loadTxt').textContent = label; }
  loadError(msg) { const e = $('loadErr'); e.textContent = msg; e.classList.remove('hidden'); }

  _tap(el, fn) {
    if (typeof el === 'string') el = $(el);
    if (!el) return;
    el.addEventListener('click', (e) => { e.preventDefault(); this.g.audio.unlock(); fn(e); });
  }
  _hold(el, down, up) {
    el = $(el);
    const on = (e) => { e.preventDefault(); e.stopPropagation(); this.g.audio.unlock(); try { el.setPointerCapture(e.pointerId); } catch (err) { /* noop */ } el.classList.add('down'); down(e); };
    const off = (e) => { e.preventDefault(); e.stopPropagation(); if (!el.classList.contains('down')) return; el.classList.remove('down'); up && up(e); };
    el.addEventListener('pointerdown', on);
    el.addEventListener('pointerup', off); el.addEventListener('pointercancel', off); el.addEventListener('lostpointercapture', off);
    el.addEventListener('contextmenu', (e) => e.preventDefault());
  }

  _wire() {
    const G = this.g;
    document.querySelectorAll('[data-back]').forEach((b) => this._tap(b, () => this.back()));
    this._tap('mTour', () => { G.audio.click(); this.show('scrTour'); });
    this._tap('mEndless', () => { G.audio.click(); G.startEndless(); });
    this._tap('mArmory', () => { G.audio.click(); this.show('scrArmory'); });
    this._tap('mHow', () => { G.audio.click(); this.show('scrHow'); });
    this._tap('mSet', () => { G.audio.click(); this.show('scrSet'); });
    // 전투 버튼
    this._hold('btnShield', () => G.battle && G.battle.onBlock(true), () => G.battle && G.battle.onBlock(false));
    this._hold('btnDL', () => G.battle && G.battle.onDodge(-1));
    this._hold('btnDR', () => G.battle && G.battle.onDodge(1));
    this._hold('btnPotion', () => G.battle && G.battle.onPotion());
    this._hold('btnFin', () => G.battle && G.battle.onFinisher());
    this._hold('btnPause', () => G.pause());
    this._hold('btnMute', () => G.toggleSound());
    this._tap('pResume', () => G.resume());
    this._tap('pHow', () => this.show('scrHow'));
    this._tap('pMute', () => { G.toggleSound(); this.syncMute(); });
    this._tap('pQuit', () => G.forfeit());
    // 무기고 탭
    $('armTabs').addEventListener('click', (e) => {
      const b = e.target.closest('button'); if (!b) return;
      this.armTab = b.dataset.tab; G.audio.click();
      for (const x of $('armTabs').children) x.classList.toggle('on', x === b);
      this.renderArmory();
    });
    // 설정
    $('sSound').addEventListener('change', (e) => { G.setSetting('sound', e.target.checked); this.syncMute(); });
    $('sHaptic').addEventListener('change', (e) => { G.setSetting('haptics', e.target.checked); if (e.target.checked) G.haptics.play('parry', true); });
    $('sFull').addEventListener('change', (e) => G.setSetting('fullscreen', e.target.checked));
    $('sQuality').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) { G.setSetting('quality', b.dataset.v); this.renderSettings(); } });
    $('sFps').addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) { G.setSetting('fps', b.dataset.v); this.renderSettings(); } });
    this._tap('sReset', () => { if (confirm('모든 진행 상황(골드·무기·토너먼트)을 초기화할까요?')) G.resetProgress(); });
  }
  syncMute() {
    const on = this.g.save.settings.sound;
    $('btnMute').classList.toggle('muted', !on);
    $('pMute').textContent = on ? '사운드 끄기' : '사운드 켜기';
  }

  // ── 메뉴 ───────────────────────────────────────────────
  renderMenu() {
    const s = this.g.save;
    $('mGold').textContent = fmt(s.gold); $('mGems').textContent = fmt(s.gems); $('mPots').textContent = s.potions + (s.elixirs ? '+' + s.elixirs : '');
    $('mBest').textContent = s.bestWave ? `최고 ${s.bestWave}웨이브` : '';
    const nx = this.g.nextFight();
    const T = TIERS[nx.tier], F = T ? T.fights[nx.fight] : null;
    $('menuNext').innerHTML = F ? `${T.name} · ${nx.fight + 1}경기<br><b>${F.name}</b> — ${ARCH[F.arch].name} Lv${F.lvl}` : '<b>모든 리그 정복!</b><br>무한 아레나에서 불멸을 증명하라';
    $('mTour').textContent = F ? (nx.tier === 0 && nx.fight === 0 && !s.stats.wins ? '첫 경기 시작' : '다음 경기') : '토너먼트';
  }
  renderTour() {
    const s = this.g.save, list = $('tourList');
    const nx = this.g.nextFight();
    list.innerHTML = '';
    const medals = ['#c27a3a', '#c9ccd2', '#e8c46a', '#ff6a3a'];
    TIERS.forEach((T, ti) => {
      const unlocked = ti <= nx.tier || s.cleared.includes(T.id);
      const div = document.createElement('div');
      div.className = 'tier' + (unlocked ? '' : ' locked');
      div.innerHTML = `<h3><i class="medal" style="background:radial-gradient(circle at 35% 30%,#fff,${medals[ti]} 55%,#3a2a1a)"></i>${T.name}${s.cleared.includes(T.id) ? ' ✓' : ''}</h3><p>${T.sub} · ${LIGHTS[T.light].label} · 클리어 보상 ${fmt(T.clear.gold)}G, 젬 ${T.clear.gems}</p>`;
      const fl = document.createElement('div'); fl.className = 'fights';
      T.fights.forEach((F, fi) => {
        const key = `${ti}-${fi}`, done = !!s.beaten[key];
        const isNext = ti === nx.tier && fi === nx.fight;
        const avail = done || isNext;
        const b = document.createElement('button');
        b.className = 'fight' + (done ? ' done' : '') + (isNext ? ' next' : '') + (!avail ? ' lock' : '') + (F.boss ? ' boss' : '');
        b.innerHTML = `<span class="ic">${ARCH[F.arch].icon}</span><span class="nm"><b>${F.name}</b><small>${ARCH[F.arch].name} · Lv${F.lvl}${F.boss ? ' · 보스' : ''}</small></span><span class="st">${done ? '승리' : isNext ? '도전 ›' : '🔒'}</span>`;
        if (avail) this._tap(b, () => { this.g.audio.click(); this.g.startTour(ti, fi); });
        fl.appendChild(b);
      });
      div.appendChild(fl); list.appendChild(div);
    });
  }

  // ── 무기고 ─────────────────────────────────────────────
  renderArmory() {
    const G = this.g, s = G.save, list = $('armList');
    this.armTab = this.armTab || 'weapons';
    $('aGold').textContent = fmt(s.gold); $('aGems').textContent = fmt(s.gems);
    list.innerHTML = '';
    const costHtml = (c) => `<span class="cost">${c.gold ? fmt(c.gold) + 'G' : ''}${c.gems ? (c.gold ? ' · ' : '') + c.gems + '젬' : ''}</span>`;
    const afford = (c) => s.gold >= (c.gold || 0) && s.gems >= (c.gems || 0);
    const statBars = (rows) => `<div class="stats">${rows.map(([k, v, t]) => `<span>${k}</span><span class="sb" title="${t || ''}"><i style="width:${Math.round(Math.min(1, v) * 100)}%"></i></span>`).join('')}</div>`;
    const card = (pic, title, desc, extra, acts, equipped) => {
      const d = document.createElement('div'); d.className = 'item' + (equipped ? ' equipped' : '');
      d.innerHTML = `<div class="pic">${pic}</div><div><h4>${title}</h4><p>${desc}</p>${extra}<div class="acts"></div></div>`;
      const ac = d.querySelector('.acts');
      for (const a of acts) {
        const b = document.createElement('button'); b.className = a.cls || ''; b.innerHTML = a.label; b.disabled = !!a.disabled;
        if (!a.disabled) this._tap(b, () => a.fn());
        ac.appendChild(b);
      }
      list.appendChild(d);
    };
    if (this.armTab === 'weapons') {
      for (const id of WEAPON_ORDER) {
        const W = WEAPONS[id], owned = !!s.owned[id], lvl = s.wlvl[id] || 1, st = weaponStats(id, lvl);
        const eq = s.weapon === id;
        const title = `${W.name} ${owned ? `<span class="lv">Lv${lvl}</span>` : ''}${eq ? '<span class="eq">장착중</span>' : ''}`;
        const bars = statBars([['공격력', st.dmg * W.hits / 34], ['공격 속도', 0.15 / W.swing], ['사거리', W.reach / 1.3], ['치명타', st.crit / 0.3]]);
        const extra = bars + `<p style="margin:0 0 8px;font-size:11px;color:#c9b89a">피해 ${st.dmg.toFixed(1)}${W.hits > 1 ? ' ×2' : ''} · 치명 ${(st.crit * 100).toFixed(0)}% ×${W.critMul} · 가드 파괴 ×${W.guard}</p>`;
        const acts = [];
        if (!owned) acts.push({ label: `구매 ${costHtml(W.price)}`, cls: 'buy', disabled: !afford(W.price), fn: () => this._buy(W.price, () => { s.owned[id] = true; s.weapon = id; }) });
        else {
          if (!eq) acts.push({ label: '장착', fn: () => { s.weapon = id; G.saveNow(); G.audio.click(); this.renderArmory(); G.refreshMenuScene(); } });
          if (lvl < MAX_LVL) { const c = upgradeCost(W.upBase, lvl); acts.push({ label: `강화 → Lv${lvl + 1} ${costHtml(c)}`, cls: 'buy', disabled: !afford(c), fn: () => this._buy(c, () => { s.wlvl[id] = lvl + 1; }, true) }); }
          else acts.push({ label: '최대 강화', disabled: true });
        }
        card(WEAPON_SVG[id], title, W.desc, extra, acts, eq);
      }
    } else if (this.armTab === 'gear') {
      const sl = s.shieldLvl, ss = shieldStats(sl), sn = shieldStats(Math.min(MAX_LVL, sl + 1));
      const sc = upgradeCost(SHIELD_UP_BASE, sl);
      card(WEAPON_SVG.shield, `스쿠툼 방패 <span class="lv">Lv${sl}</span>`, '방패 내구도와 저스트 가드 판정이 늘어난다.',
        statBars([['내구도', ss.max / 190], ['회복', ss.regen / 17], ['저스트', ss.jg / 0.2]]) + `<p style="margin:0 0 8px;font-size:11px;color:#c9b89a">내구 ${ss.max} → ${sn.max} · 저스트 가드 ${(ss.jg * 1000).toFixed(0)}ms → ${(sn.jg * 1000).toFixed(0)}ms</p>`,
        [sl < MAX_LVL ? { label: `강화 ${costHtml(sc)}`, cls: 'buy', disabled: !afford(sc), fn: () => this._buy(sc, () => { s.shieldLvl++; }, true) } : { label: '최대 강화', disabled: true }]);
      const al = s.armorLvl, as = armorStats(al), an = armorStats(Math.min(MAX_LVL, al + 1));
      const acst = upgradeCost(ARMOR_UP_BASE, al);
      card(WEAPON_SVG.armor, `검투사 갑옷 <span class="lv">Lv${al}</span>`, '최대 체력과 피해 감소. 레벨이 오르면 마니카·정강이받이·흉갑이 장착된다.',
        statBars([['체력', as.hp / 250], ['피해 감소', as.dr / 0.32]]) + `<p style="margin:0 0 8px;font-size:11px;color:#c9b89a">체력 ${as.hp} → ${an.hp} · 피해 감소 ${(as.dr * 100).toFixed(0)}% → ${(an.dr * 100).toFixed(0)}%</p>`,
        [al < MAX_LVL ? { label: `강화 ${costHtml(acst)}`, cls: 'buy', disabled: !afford(acst), fn: () => this._buy(acst, () => { s.armorLvl++; G.refreshMenuScene(); }, true) } : { label: '최대 강화', disabled: true }]);
    } else {
      card(WEAPON_SVG.potion, `회복 포션 <span class="lv">${s.potions}/${POTION.max}</span>`, `전투 중 체력 ${POTION.heal * 100}% 회복. 하단 포션 버튼으로 사용.`, '',
        [{ label: `구매 ${costHtml({ gold: POTION.price })}`, cls: 'buy', disabled: s.potions >= POTION.max || s.gold < POTION.price, fn: () => this._buy({ gold: POTION.price }, () => { s.potions++; }) }]);
      card(WEAPON_SVG.elixir, `불멸의 엘릭서 <span class="lv">${s.elixirs}/${ELIXIR.max}</span>`, `체력 ${ELIXIR.heal * 100}% 회복 + 분노 ${ELIXIR.rage}. 포션이 없을 때 자동 사용.`, '',
        [{ label: `구매 ${costHtml({ gems: ELIXIR.price })}`, cls: 'buy', disabled: s.elixirs >= ELIXIR.max || s.gems < ELIXIR.price, fn: () => this._buy({ gems: ELIXIR.price }, () => { s.elixirs++; }) }]);
    }
  }
  _buy(c, apply, upgrade = false) {
    const G = this.g, s = G.save;
    if (s.gold < (c.gold || 0) || s.gems < (c.gems || 0)) { G.audio.deny(); return; }
    s.gold -= c.gold || 0; s.gems -= c.gems || 0;
    apply(); G.saveNow();
    upgrade ? G.audio.upgrade() : G.audio.coin(); G.haptics.play('ui');
    this.renderArmory();
  }

  renderSettings() {
    const st = this.g.save.settings;
    $('sSound').checked = st.sound; $('sHaptic').checked = st.haptics; $('sFull').checked = st.fullscreen;
    for (const b of $('sQuality').children) b.classList.toggle('on', b.dataset.v === st.quality);
    for (const b of $('sFps').children) b.classList.toggle('on', b.dataset.v === st.fps);
    const E = this.g.engine;
    $('sInfo').textContent = `해상도 배율 ${E.dpr.toFixed(2)}x · 주사율 ${E.refresh || '?'}Hz · ${E.fps ? E.fps.toFixed(0) + 'fps' : ''}${this.g.haptics.ok ? '' : ' · 이 기기는 진동 미지원'}`;
  }

  // ── 결과 ───────────────────────────────────────────────
  result(r, buttons) {
    $('rTitle').textContent = r.victory ? (r.mode === 'endless' ? `웨이브 ${r.spec.wave} 돌파!` : '승리!') : '패배';
    $('rTitle').classList.toggle('lose', !r.victory);
    $('rSub').textContent = r.sub || '';
    const rw = [];
    if (r.gold) rw.push(`<span><i style="background:radial-gradient(circle at 35% 30%,#fff3b0,#e0a020 55%,#8a5a08)"></i>+${fmt(r.gold)}</span>`);
    if (r.gems) rw.push(`<span><i style="background:linear-gradient(135deg,#b8f4ff,#3aa0ff 50%,#1a3a9a);border-radius:4px;transform:rotate(45deg) scale(.8)"></i>+${r.gems}</span>`);
    $('rRewards').innerHTML = rw.join('');
    $('rStats').innerHTML = `<span>최대 콤보</span><b>${r.maxCombo}</b><span>패링 (퍼펙트)</span><b>${r.parries} (${r.perfects})</b><span>처형·인빅투스</span><b>${r.execs}</b><span>받은 피해</span><b>${r.dmgTaken}</b>${r.perfectRun ? '<span>완벽한 승리</span><b>골드 ×1.5</b>' : ''}`;
    const bx = $('rBtns'); bx.innerHTML = '';
    for (const b of buttons) { const el = document.createElement('button'); el.className = 'btn ' + (b.cls || ''); el.textContent = b.label; this._tap(el, () => { this.g.audio.click(); b.fn(); }); bx.appendChild(el); }
    this.show('scrResult');
  }

  // ── 전투 HUD ───────────────────────────────────────────
  battleHUD(on, info) {
    $('hud').classList.toggle('hidden', !on);
    $('hud').classList.toggle('intro', on);
    if (!on) return;
    $('eName').textContent = info.name; $('eLvl').textContent = 'Lv' + info.lvl;
    document.querySelector('.ebar').classList.toggle('boss', !!info.boss);
    this.hudCache = {};
    this.syncMute();
  }
  _setBar(id, k) { const el = $(id); const v = Math.max(0, Math.min(1, k)); if (this.hudCache[id] !== v) { el.style.transform = `scaleX(${v})`; this.hudCache[id] = v; } }
  hud(h) {
    this._setBar('pFill', h.php / h.pmax); this._setBar('pGhost', h.php / h.pmax);
    this._setBar('sFill', h.psh / h.pshmax); this._setBar('rFill', h.rage / 100);
    this._setBar('eFill', h.ehp / h.emax); this._setBar('eGhost', h.ehp / h.emax);
    const c = this.hudCache;
    const ptxt = Math.ceil(h.php);
    if (c.ptxt !== ptxt) { $('pTxt').textContent = ptxt; c.ptxt = ptxt; }
    if (c.shb !== h.shBroken) { document.querySelector('.sbar').classList.toggle('broken', h.shBroken); $('btnShield').classList.toggle('broken', h.shBroken); c.shb = h.shBroken; }
    const full = h.rage >= 100;
    if (c.full !== full) { document.querySelector('.rbar').classList.toggle('full', full); $('btnFin').classList.toggle('ready', full); c.full = full; }
    const rr = Math.round(h.rage);
    if (c.rr !== rr) { $('btnFin').style.setProperty('--r', rr); c.rr = rr; }
    const comboOn = h.combo >= 2 && h.comboAlive;
    if (c.comboOn !== comboOn) { $('combo').classList.toggle('on', comboOn); c.comboOn = comboOn; }
    if (comboOn && c.combo !== h.combo) {
      $('comboN').textContent = h.combo; $('comboM').textContent = '×' + h.mul.toFixed(1); c.combo = h.combo;
      const el = $('combo'); el.classList.remove('bump'); void el.offsetWidth; el.classList.add('bump');
    }
    const pots = h.potions + h.elixirs;
    if (c.pots !== pots) { $('potN').textContent = h.potions + (h.elixirs ? '+' + h.elixirs : ''); $('btnPotion').classList.toggle('empty', pots <= 0); c.pots = pots; }
    const tags = `${h.helmet ? 1 : 0}${h.shield ? 1 : 0}${h.phase}`;
    if (c.tags !== tags) {
      let t = '';
      if (h.boss) t += `<span>페이즈 ${h.phase}</span>`;
      t += `<span class="${h.helmet ? '' : 'off'}">투구</span>`;
      if (h.shield || c.hadShield) t += `<span class="${h.shield ? '' : 'off'}">방패</span>`;
      c.hadShield = c.hadShield || h.shield;
      $('eTags').innerHTML = t; c.tags = tags;
    }
    if (c.counter !== h.counter) { $('counterTag').classList.toggle('on', h.counter); c.counter = h.counter; }
  }
  project(v) {
    const p = v.clone().project(this.g.camera);
    return { x: (p.x * 0.5 + 0.5) * innerWidth, y: (-p.y * 0.5 + 0.5) * innerHeight };
  }
  _pop(text, cls, x, y) {
    const el = this.popPool.pop() || document.createElement('div');
    el.className = 'pop ' + cls; el.textContent = text;
    el.style.left = x + 'px'; el.style.top = y + 'px';
    $('popups').appendChild(el);
    const life = cls.includes('ko') || cls.includes('boss') ? 1850 : cls.includes('big') ? 1100 : 950;
    setTimeout(() => { el.remove(); if (this.popPool.length < 40) this.popPool.push(el); }, life);
  }
  popup(text, cls = 'info', xf = 0.5, yf = 0.4) { this._pop(text, cls, xf * innerWidth, yf * innerHeight); }
  clearBig() { for (const el of document.querySelectorAll('#popups .pop.big')) el.remove(); }
  introMode(on) { $('hud').classList.toggle('intro', on); }
  bigText(text, cls = '') {
    for (const el of document.querySelectorAll('#popups .pop.big')) el.remove();
    this._pop(text, 'big ' + cls, innerWidth / 2, innerHeight * (cls === 'ko' ? 0.4 : 0.36));
  }
  dmg(n, x, y, crit, stag) { this._pop(String(n), 'dmg' + (crit ? ' crit' : '') + (stag ? ' stag' : ''), x + (Math.random() - 0.5) * 40, y - 20); }
  hurt(k) {
    const v = $('vignette');
    v.style.transition = 'none'; v.style.opacity = Math.min(1, k);
    void v.offsetWidth;
    v.style.transition = 'opacity .7s'; v.style.opacity = 0;
  }
  flash() { const f = $('flash'); f.style.transition = 'none'; f.style.opacity = 0.75; void f.offsetWidth; f.style.transition = 'opacity .5s'; f.style.opacity = 0; }
  lowHP(on) { if (this.hudCache.low !== on) { $('lowhp').classList.toggle('on', on); this.hudCache.low = on; } }
  bullet(on) { $('bulletTint').classList.toggle('on', on); }
  death(on) { $('deathTint').classList.toggle('on', on); }
  stagger(on, dur) {
    clearTimeout(this._stT);
    $('staggerTag').classList.toggle('on', !!on);
    if (on && dur) this._stT = setTimeout(() => $('staggerTag').classList.remove('on'), dur * 1000);
  }
  warn(text) { const w = $('warn'); if (text) { w.textContent = text; w.classList.add('on'); } else w.classList.remove('on'); }
  hint(angle) {
    const h = $('hint');
    if (angle == null) { if (this.hudCache.hint) { h.classList.remove('on'); this.hudCache.hint = false; } return; }
    h.querySelector('.harrow').style.transform = `rotate(${-angle}deg)`;
    if (!this.hudCache.hint) { h.classList.add('on'); this.hudCache.hint = true; }
  }
  toast(text, ms = 3200) {
    const t = $('toast'); t.textContent = text; t.classList.add('on');
    clearTimeout(this._toT); this._toT = setTimeout(() => t.classList.remove('on'), ms);
  }
  qte(arrows, idx) {
    const q = $('qte');
    if (!arrows) { q.classList.add('hidden'); return; }
    q.classList.remove('hidden');
    $('qteTitle').textContent = this.g.battle && this.g.battle.qte && this.g.battle.qte.kind === 'invictus' ? 'INVICTUS!' : '처형 기회!';
    const row = $('qteRow');
    row.innerHTML = arrows.map((a, i) => `<div class="${i < idx ? 'done' : i === idx ? 'cur' : ''}" style="--a:${a}"><span style="display:block;transform:rotate(${-a}deg)">${ARROW_SVG}</span></div>`).join('');
    const cur = arrows[Math.min(idx, arrows.length - 1)];
    $('qteBig').style.transform = `rotate(${-cur}deg)`;
    $('qteBig').style.opacity = idx >= arrows.length ? 0 : 1;
  }
  qteTimer(k) { $('qteBar').style.transform = `scaleX(${Math.max(0, k)})`; }
  vsCard(F, A, spec) {
    const v = $('vs');
    if (!F) { v.classList.add('hidden'); return; }
    v.classList.remove('hidden');
    $('vsLeague').textContent = spec.mode === 'endless' ? `무한 아레나 · 웨이브 ${spec.wave}` : `${TIERS[spec.tier].name} · ${spec.fightIdx + 1}경기${F.boss ? ' · 결승' : ''}`;
    $('vsName').textContent = F.name;
    $('vsTitle').textContent = `${A.name} · ${A.title} · Lv${F.lvl}`;
    $('vsTip').textContent = A.tip;
  }
}
