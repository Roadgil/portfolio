// localStorage 자동 저장 (예외 안전)
const KEY = 'invictus.save.v1';

export const DEFAULT_SAVE = {
  v: 1,
  gold: 300, gems: 5, potions: 2, elixirs: 0,
  weapon: 'gladius',
  owned: { gladius: true },
  wlvl: { gladius: 1, broadsword: 1, dual: 1, axe: 1 },
  shieldLvl: 1, armorLvl: 1,
  tier: 0, fight: 0, cleared: [], beaten: {},
  bestWave: 0,
  tutorialSeen: false,
  settings: { sound: true, haptics: true, quality: 'auto', fps: 'auto', fullscreen: true },
  stats: { wins: 0, losses: 0, parries: 0, perfect: 0, executions: 0, maxCombo: 0 },
};

const clone = (o) => JSON.parse(JSON.stringify(o));
function merge(base, extra) {
  if (!extra || typeof extra !== 'object') return base;
  for (const k of Object.keys(base)) {
    if (!(k in extra)) continue;
    const bv = base[k], ev = extra[k];
    if (bv && typeof bv === 'object' && !Array.isArray(bv)) base[k] = merge(bv, ev);
    else if (typeof ev === typeof bv || (Array.isArray(bv) && Array.isArray(ev))) base[k] = ev;
  }
  // 동적 키(맵 형태) 보존
  for (const k of ['owned', 'beaten']) if (extra[k] && typeof extra[k] === 'object') base[k] = { ...base[k], ...extra[k] };
  return base;
}

export function loadSave() {
  let raw = null;
  try { raw = localStorage.getItem(KEY); } catch (e) { /* 사생활 보호 모드 등 */ }
  if (!raw) return clone(DEFAULT_SAVE);
  try { return merge(clone(DEFAULT_SAVE), JSON.parse(raw)); } catch (e) { return clone(DEFAULT_SAVE); }
}

let pending = 0;
export function writeSave(data) {
  clearTimeout(pending);
  pending = setTimeout(() => {
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (e) { /* 저장 공간 없음 */ }
  }, 120);
}
export function flushSave(data) {
  clearTimeout(pending);
  try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (e) { /* ignore */ }
}
export function resetSave() {
  try { localStorage.removeItem(KEY); } catch (e) { /* ignore */ }
  return clone(DEFAULT_SAVE);
}
