// ─────────────────────────────────────────────────────────────
//  INVICTUS — 게임 데이터 & 튜닝 상수
// ─────────────────────────────────────────────────────────────
export const VERSION = '1.0.0';
export const ENEMY_Z = -2.35;          // 적 기본 위치 (플레이어는 원점, -Z 바라봄)
export const EYE_H = 1.62;             // 1인칭 눈높이

// 화면 기준 공격 궤적 (dx, dy) — y는 위가 +
export const MOVE_DIRS = {
  L2R: [1, 0], R2L: [-1, 0], T2B: [0, -1], B2T: [0, 1],
  TL2BR: [0.7071, -0.7071], TR2BL: [-0.7071, -0.7071],
  BL2TR: [0.7071, 0.7071], BR2TL: [-0.7071, 0.7071],
};
const ARROWS = ['→', '↗', '↑', '↖', '←', '↙', '↓', '↘'];
export const angleOf = (dx, dy) => Math.atan2(dy, dx) * 180 / Math.PI;
export const angDiff = (a, b) => { let d = (a - b) % 360; if (d > 180) d -= 360; if (d < -180) d += 360; return Math.abs(d); };
export const arrowFor = (deg) => ARROWS[((Math.round(deg / 45) % 8) + 8) % 8];
export const sector8 = (deg) => ((Math.round(deg / 45) % 8) + 8) % 8;
export const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
export const lerp = (a, b, t) => a + (b - a) * t;
export const rand = (a, b) => a + Math.random() * (b - a);
export const pick = (arr) => arr[(Math.random() * arr.length) | 0];

// ── 무기 ─────────────────────────────────────────────────────
export const WEAPONS = {
  gladius: {
    id: 'gladius', name: '글라디우스', desc: '균형 잡힌 로마 단검. 빠르고 다루기 쉽다.',
    dmg: 9, swing: 0.22, reach: 1.0, crit: 0.12, critMul: 1.8, guard: 1.0, parryTol: 0, parryWin: 0, hits: 1,
    price: { gold: 0, gems: 0 }, upBase: 120,
  },
  broadsword: {
    id: 'broadsword', name: '브로드소드', desc: '넓고 긴 칼날. 사거리가 길어 패링 판정이 넉넉하다.',
    dmg: 13, swing: 0.29, reach: 1.25, crit: 0.08, critMul: 1.85, guard: 1.35, parryTol: 8, parryWin: 0.03, hits: 1,
    price: { gold: 900, gems: 0 }, upBase: 170,
  },
  dual: {
    id: 'dual', name: '쌍검', desc: '한 번 그으면 두 번 벤다. 치명타가 잦지만 사거리가 짧고 방어가 약하다.',
    dmg: 6, swing: 0.19, reach: 0.85, crit: 0.18, critMul: 1.7, guard: 0.7, parryTol: -5, parryWin: -0.01, hits: 2,
    price: { gold: 1600, gems: 5 }, upBase: 210,
  },
  axe: {
    id: 'axe', name: '배틀액스', desc: '느리지만 묵직한 한 방. 상대의 방어를 순식간에 부순다.',
    dmg: 20, swing: 0.40, reach: 1.1, crit: 0.10, critMul: 2.3, guard: 2.4, parryTol: 0, parryWin: 0, hits: 1,
    price: { gold: 2400, gems: 10 }, upBase: 250,
  },
};
export const WEAPON_ORDER = ['gladius', 'broadsword', 'dual', 'axe'];
export const MAX_LVL = 10;
export const upgradeCost = (base, lvl) => ({
  gold: Math.round(base * Math.pow(1.55, lvl - 1) / 10) * 10,
  gems: lvl >= 5 ? lvl - 3 : 0,
});
export const weaponStats = (id, lvl) => {
  const w = WEAPONS[id];
  return { ...w, dmg: w.dmg * (1 + 0.11 * (lvl - 1)), crit: w.crit + 0.006 * (lvl - 1) };
};
export const shieldStats = (lvl) => ({
  max: 60 + (lvl - 1) * 14, regen: 7 + lvl * 0.9, jg: 0.13 + (lvl - 1) * 0.006, eff: Math.min(0.55, 0.22 + lvl * 0.033),
});
export const armorStats = (lvl) => ({ hp: 100 + (lvl - 1) * 16, dr: Math.min(0.32, (lvl - 1) * 0.035) });
export const SHIELD_UP_BASE = 140;
export const ARMOR_UP_BASE = 160;
export const POTION = { heal: 0.4, price: 140, max: 5 };
export const ELIXIR = { heal: 0.75, rage: 50, price: 4, max: 2 };

// ── 적 아키타입 ──────────────────────────────────────────────
export const ARCH = {
  secutor: {
    name: '검방패병', title: '방패의 벽', icon: '🛡', hp: 125, dmg: 11, guardStam: 100, shieldHP: 150, helmetHP: 40,
    parryWin: 0.30, idle: [0.85, 1.6], guard: 0.55, evade: 0, react: 0.38, eParry: 0.1, superArmor: false,
    exec: 0.35, style: 'sword_shield', voice: 1.0, scale: 1.0, dist: 2.35,
    tip: '방패가 높으면 아래에서 올려 베고, 낮으면 내려 베라. 꺾어 긋는 페인트는 방패를 무시한다.',
  },
  assassin: {
    name: '쌍검 암살자', title: '그림자 칼날', icon: '⚔', hp: 95, dmg: 7, guardStam: 0, shieldHP: 0, helmetHP: 28,
    parryWin: 0.24, idle: [0.55, 1.15], guard: 0, evade: 0.34, react: 0, eParry: 0, superArmor: false,
    exec: 0.35, style: 'dual', voice: 1.25, scale: 0.96, dist: 2.3,
    tip: '빠른 3연타를 패링하라. 같은 방향만 고집하면 옆으로 흘려 피한다.',
  },
  berserker: {
    name: '도끼 광전사', title: '북방의 야수', icon: '🪓', hp: 175, dmg: 17, guardStam: 0, shieldHP: 0, helmetHP: 55,
    parryWin: 0.33, idle: [1.0, 1.8], guard: 0, evade: 0, react: 0, eParry: 0, superArmor: true,
    exec: 0.3, style: 'axe2h', voice: 0.72, scale: 1.1, dist: 2.75,
    tip: '강공격 중엔 경직되지 않는다(슈퍼아머). 붉은 공격은 반드시 회피하고 빈틈을 노려라.',
  },
  champion: {
    name: '챔피언', title: '콜로세움의 왕', icon: '👑', hp: 330, dmg: 13, guardStam: 120, shieldHP: 170, helmetHP: 70,
    parryWin: 0.26, idle: [0.6, 1.2], guard: 0.42, evade: 0.1, react: 0.3, eParry: 0.14, superArmor: false,
    exec: 0.22, style: 'sword_shield', voice: 0.88, scale: 1.05, dist: 2.45,
    tip: '체력이 줄수록 방패를 버리고 광폭해진다. 궤적이 바뀌는 페인트 공격에 주의!',
  },
};
export function scaleEnemy(arch, lvl) {
  const a = ARCH[arch];
  return {
    hp: Math.round(a.hp * (1 + 0.27 * (lvl - 1))),
    dmg: a.dmg * (1 + 0.14 * (lvl - 1)),
    wind: Math.max(0.62, 1 - 0.045 * (lvl - 1)),
    parryWin: Math.max(0.15, a.parryWin - 0.014 * (lvl - 1)),
    aggr: Math.max(0.45, 1 - 0.06 * (lvl - 1)),
    lvl,
  };
}

// ── 토너먼트 ─────────────────────────────────────────────────
export const TIERS = [
  {
    id: 'bronze', name: '브론즈 리그', sub: '모래 위의 첫 피', light: 'afternoon', hint: true, tol: 44,
    qte: { n: 3, time: 3.6 }, clear: { gold: 300, gems: 5 },
    fights: [
      { arch: 'secutor', lvl: 1, name: '루키우스' },
      { arch: 'assassin', lvl: 1, name: '닉스' },
      { arch: 'berserker', lvl: 2, name: '브루노' },
    ],
  },
  {
    id: 'silver', name: '실버 리그', sub: '관중이 이름을 부르기 시작한다', light: 'golden', hint: false, tol: 40,
    qte: { n: 3, time: 3.1 }, clear: { gold: 600, gems: 8 },
    fights: [
      { arch: 'assassin', lvl: 3, name: '세베라' },
      { arch: 'secutor', lvl: 3, name: '가이우스' },
      { arch: 'berserker', lvl: 4, name: '고르가스' },
      { arch: 'secutor', lvl: 5, name: '옥타비우스' },
    ],
  },
  {
    id: 'gold', name: '골드 리그', sub: '황혼의 결투', light: 'dusk', hint: false, tol: 37,
    qte: { n: 3, time: 2.8 }, clear: { gold: 1000, gems: 12 },
    fights: [
      { arch: 'berserker', lvl: 5, name: '라그나르' },
      { arch: 'assassin', lvl: 6, name: '카시우스' },
      { arch: 'secutor', lvl: 6, name: '티투스' },
      { arch: 'berserker', lvl: 7, name: '볼그' },
    ],
  },
  {
    id: 'champion', name: '챔피언 리그', sub: '횃불 아래, 불멸을 위하여', light: 'night', hint: false, tol: 34,
    qte: { n: 4, time: 3.0 }, clear: { gold: 2000, gems: 20 },
    fights: [
      { arch: 'assassin', lvl: 8, name: '베스페르' },
      { arch: 'secutor', lvl: 8, name: '세르비우스' },
      { arch: 'berserker', lvl: 9, name: '모르탄' },
      { arch: 'champion', lvl: 10, name: '황금의 아퀼라', boss: true },
    ],
  },
];
export const ENDLESS_NAMES = ['데키무스', '플라쿠스', '루푸스', '마르켈루스', '크라수스', '스피쿨루스', '플람마', '프리스쿠스', '베루스', '카르포', '아티쿠스', '드루수스', '렌투스', '셉티무스', '브리간투스'];
export function endlessFight(wave) {
  const lvl = Math.min(14, 2 + Math.floor(wave * 0.55));
  const boss = wave > 0 && wave % 10 === 0;
  const arch = boss ? 'champion' : pick(['secutor', 'assassin', 'berserker']);
  return { arch, lvl: boss ? lvl + 1 : lvl, name: boss ? '아레나의 군주' : pick(ENDLESS_NAMES), boss, light: ['afternoon', 'golden', 'dusk', 'night'][Math.floor(wave / 3) % 4] };
}
export const fightReward = (lvl, boss) => ({ gold: 50 + 35 * lvl + (boss ? 400 : 0), gems: boss ? 5 : 0 });

// ── 조명 프리셋 (단계별 시간대) ──────────────────────────────
export const LIGHTS = {
  afternoon: {
    label: '한낮', sunDir: [0.42, 0.8, 0.45], sun: 0xfff0d6, sunI: 3.3, hemiSky: 0xbcd2ff, hemiGround: 0x8a6a48, hemiI: 0.85,
    skyTop: 0x3f78c8, skyHor: 0xe6d5b8, glow: 0xfff3d6, fog: 0xd6c6a8, fogD: 0.0065, torch: 0.5, exp: 1.0, env: 1.0, stars: 0, dust: 0.7,
  },
  golden: {
    label: '황금빛 오후', sunDir: [0.62, 0.42, 0.38], sun: 0xffcc8a, sunI: 3.1, hemiSky: 0xa8b8e6, hemiGround: 0x8a5a38, hemiI: 0.7,
    skyTop: 0x4565ac, skyHor: 0xf2b578, glow: 0xffc37a, fog: 0xd8b088, fogD: 0.0075, torch: 0.8, exp: 1.03, env: 0.9, stars: 0, dust: 1.0,
  },
  dusk: {
    label: '황혼', sunDir: [-0.78, 0.2, 0.32], sun: 0xff9356, sunI: 2.6, hemiSky: 0x7f87c8, hemiGround: 0x6a3a28, hemiI: 0.6,
    skyTop: 0x22305f, skyHor: 0xf27a45, glow: 0xff8a4a, fog: 0xa86a52, fogD: 0.0085, torch: 1.25, exp: 1.08, env: 0.75, stars: 0.25, dust: 1.0,
  },
  night: {
    label: '횃불의 밤', sunDir: [0.35, 0.82, 0.42], sun: 0x9fb2ff, sunI: 0.95, hemiSky: 0x3a4a8a, hemiGround: 0x2a1a14, hemiI: 0.45,
    skyTop: 0x050916, skyHor: 0x1e2244, glow: 0x9aa8ff, fog: 0x1a1a2e, fogD: 0.009, torch: 2.3, exp: 1.18, env: 0.55, stars: 1, dust: 0.8,
  },
};

// ── 그래픽 품질 ──────────────────────────────────────────────
export const QUALITY = {
  high: { label: '높음', dprMax: 2.0, msaa: 4, shadow: 2048, lights: 4, crowd: 1.0, dust: 700, tex: 1024 },
  medium: { label: '중간', dprMax: 1.6, msaa: 2, shadow: 1536, lights: 3, crowd: 0.75, dust: 450, tex: 1024 },
  low: { label: '낮음', dprMax: 1.25, msaa: 0, shadow: 1024, lights: 2, crowd: 0.5, dust: 260, tex: 512 },
};

// ── 전투 튜닝 ────────────────────────────────────────────────
export const TUNE = {
  comboWindow: 1.15, comboStep: 0.15, comboMax: 2.5,
  hitstop: { light: 0.045, crit: 0.06, parry: 0.07, block: 0.04, heavy: 0.07 },
  staggerParry: 1.6, staggerPerfect: 2.1, staggerGuardBreak: 1.5, staggerMul: 2.0,
  dodgeDur: 0.46, dodgeIFrom: 0.02, dodgeITo: 0.36, dodgeCd: 0.22, perfectDodge: 0.32,
  bulletTime: 1.5, bulletScale: 0.32, bulletMul: 1.5,
  deflectStun: 0.45, guardBreakStun: 0.9, shieldDelay: 1.2,
  rage: { hit: 4, crit: 3, parry: 18, perfect: 26, jg: 12, dodge: 15, taken: 0.45 },
  invictusDmg: 0.45,
};
