/*
 * DCD 캔 서비스 웹앱
 * 신청자 폼(RequestForm)은 2026-09-21부터 빈캔 회수 / 불량캔 신고만 접수.
 * DCD 구매 주문(order)은 신청 폼에서 제거했지만, 과거 접수 이력 조회를 위해
 * 백엔드(TYPES/시트/관리자 페이지)는 그대로 남겨둠 — 새 주문은 들어오지 않음.
 *
 * ===== 코드 수정 후 =====
 * Apps Script에서 저장(Ctrl+S)만 하면 끝이 아니라,
 * 배포 > 배포 관리 > 연필(수정) > 버전: 새 버전 > 배포 까지 해야
 * 실제 웹앱 링크에 반영된다.
 *
 * ===== 최초 설치 시 =====
 * 함수 선택 드롭다운에서 initSetup 선택 후 실행 (권한 요청 허용)
 * -> 시트 3개(예약/불량접수/구매요청) 자동 생성 + 초기 데이터 + 매일 16시 메일 트리거 설치
 */

const SHEET_ID = '1urjnp_oQSzNVJf3uK7bt7jw6C3SpkRluK9jpsgaDI8o';
// ADMIN_TOKEN/KAKAO_KEY는 코드에 하드코딩하지 않고 Apps Script 프로젝트 설정의
// Script Properties에서 읽어온다 (2026-09-22, 포트폴리오 공개 저장소에 평문 노출됐던
// 사고 이후 수정). Apps Script 편집기 > 프로젝트 설정(⚙) > 스크립트 속성에서
// ADMIN_TOKEN, KAKAO_KEY 키를 등록해둘 것. 카카오 키는 재발급 필요(기존 값은 유출됨).
const ADMIN_TOKEN = PropertiesService.getScriptProperties().getProperty('ADMIN_TOKEN');
const MAIL_TO = ['y7221063@yongmalogis.co.kr', 'y7225055@yongmalogis.co.kr']; // 김기훈, 유용호
const MAIL_HOUR = 16;
// 카카오 키는 여기(서버 쪽 Code.gs)에만 있음 — 브라우저로 전달되는 HTML에는 절대 넣지 않는다.
// (2026-09-21: 예전엔 RequestForm.html에서 브라우저가 직접 카카오 API를 호출해서 키가 페이지 소스에 노출됐음. 이제 서버가 대신 호출.)
const KAKAO_KEY = PropertiesService.getScriptProperties().getProperty('KAKAO_KEY');

const HEADERS = ['타임스탬프', '병원명', '주소', '우편번호', '수량', '비고', '상태', '메일발송여부', '처리메모'];

const TYPES = {
  recover:   { sheetName: '예약',     label: '빈캔 회수 예약',  qtyLabel: '박스 개수',      noteLabel: '특이사항',  statuses: ['접수됨', '주소확인필요', '택배발송완료'] },
  defective: { sheetName: '불량접수', label: '불량캔 신고',     qtyLabel: '불량 캔 개수',   noteLabel: '불량 내용', statuses: ['접수됨', '확인중', '교환완료'] },
  order:     { sheetName: '구매요청', label: 'DCD 구매 주문',   qtyLabel: '주문 박스 개수', noteLabel: '요청사항',  statuses: ['접수됨', '주소확인필요', '배송완료'] }
};

function getSheet_(type) {
  const cfg = TYPES[type];
  if (!cfg) throw new Error('알 수 없는 종류: ' + type);
  const ss = SpreadsheetApp.openById(SHEET_ID);
  let sh = ss.getSheetByName(cfg.sheetName);
  if (!sh) sh = ss.insertSheet(cfg.sheetName);
  if (sh.getLastRow() === 0) {
    sh.appendRow(HEADERS);
    sh.setFrozenRows(1);
  }
  return sh;
}

function doGet(e) {
  const page = (e.parameter.admin === ADMIN_TOKEN) ? 'AdminList' : 'RequestForm';
  const tpl = HtmlService.createTemplateFromFile(page);
  return tpl.evaluate()
    .setTitle('Vbeam/Gentlemax 냉매가스(DCD)')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}

/** 탭별 설정(라벨 등)을 프론트에 내려줌 */
function getTypeConfig() {
  const out = {};
  Object.keys(TYPES).forEach(k => {
    const c = TYPES[k];
    out[k] = { label: c.label, qtyLabel: c.qtyLabel, noteLabel: c.noteLabel, statuses: c.statuses };
  });
  return out;
}

/** 신청자 폼에서 호출 — 병원명 키워드로 카카오 로컬 검색 (키는 서버 쪽에만 있음) */
function kakaoSearchHospital(query) {
  const url = 'https://dapi.kakao.com/v2/local/search/keyword.json?size=15&query=' + encodeURIComponent(query);
  const res = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'KakaoAK ' + KAKAO_KEY },
    muteHttpExceptions: true
  });
  if (res.getResponseCode() !== 200) return [];
  const data = JSON.parse(res.getContentText());
  return (data.documents || []).map(d => ({
    name: d.place_name || '',
    addr: d.road_address_name || d.address_name || ''
  }));
}

/** 신청자 폼에서 호출 — 선택된 주소의 우편번호 조회 (키는 서버 쪽에만 있음) */
function kakaoZipForAddress(addr) {
  if (!addr) return '';
  const url = 'https://dapi.kakao.com/v2/local/search/address.json?query=' + encodeURIComponent(addr);
  const res = UrlFetchApp.fetch(url, {
    headers: { Authorization: 'KakaoAK ' + KAKAO_KEY },
    muteHttpExceptions: true
  });
  if (res.getResponseCode() !== 200) return '';
  const data = JSON.parse(res.getContentText());
  const doc = (data.documents || [])[0];
  return (doc && doc.road_address && doc.road_address.zone_no) || '';
}

/** 신청자 폼에서 호출 — 1건 저장. type: 'recover' | 'defective' | 'order' */
function saveEntry(type, data) {
  const sh = getSheet_(type);
  sh.appendRow([
    new Date(),
    (data.hospital || '').trim(),
    (data.address || '').trim(),
    (data.zip || '').trim(),
    Number(data.qty) || 0,
    (data.note || '').trim(),
    '접수됨',
    false,
    ''
  ]);
  return { ok: true };
}

/** 관리자 페이지에서 호출 — 해당 탭 전체 목록 */
function getEntries(type) {
  const sh = getSheet_(type);
  const last = sh.getLastRow();
  if (last < 2) return [];
  const rows = sh.getRange(2, 1, last - 1, HEADERS.length).getValues();
  return rows.map((r, i) => ({
    row: i + 2,
    timestamp: Utilities.formatDate(new Date(r[0]), 'Asia/Seoul', 'yyyy-MM-dd HH:mm'),
    hospital: r[1],
    address: r[2],
    zip: r[3],
    qty: r[4],
    note: r[5],
    status: r[6],
    mailed: r[7],
    memo: r[8]
  })).reverse();
}

/** 관리자 페이지에서 호출 — 상태/메모 업데이트 */
function updateEntry(type, row, status, memo) {
  const sh = getSheet_(type);
  sh.getRange(row, 7).setValue(status);
  sh.getRange(row, 9).setValue(memo || '');
  return { ok: true };
}

/** 최초 1회 설치 함수 */
function initSetup() {
  Object.keys(TYPES).forEach(t => getSheet_(t));
  seedInitialData();
  installDailyTrigger();
  Logger.log('설치 완료. Web App 배포 후 URL을 확인하세요.');
}

/** 최초 요청 당시 이미 전화로 접수돼 있던 대기 건 (주소 미확인, 회수 탭에만) */
function seedInitialData() {
  const sh = getSheet_('recover');
  if (sh.getLastRow() > 1) return; // 이미 데이터 있으면 건너뜀 (중복 방지)
  const seed = [
    ['의정부 리밋', 3],
    ['라라피부과', 1],
    ['셀린 다산', 2],
    ['영등포계피부과', 1],
    ['레스트의원', 1],
    ['모던스탠다드', 1]
  ];
  seed.forEach(([hospital, qty]) => {
    sh.appendRow([new Date(), hospital, '', '', qty, '(전화 접수분 - 주소 확인 필요)', '주소확인필요', false, '']);
  });
}

function installDailyTrigger() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'sendDailySummaryEmail') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('sendDailySummaryEmail')
    .timeBased()
    .atHour(MAIL_HOUR)
    .everyDays(1)
    .create();
}

/** 매일 16시 실행 — 3개 탭 통틀어 아직 미발송인 건을 모아 김기훈/유용호에게 한 통으로 발송 */
function sendDailySummaryEmail() {
  const sections = [];

  Object.keys(TYPES).forEach(type => {
    const cfg = TYPES[type];
    const sh = getSheet_(type);
    const last = sh.getLastRow();
    if (last < 2) return;
    const rows = sh.getRange(2, 1, last - 1, HEADERS.length).getValues();

    const pending = [];
    rows.forEach((r, i) => { if (r[7] !== true) pending.push({ rowIndex: i + 2, data: r }); });
    if (pending.length === 0) return;

    const lines = pending.map(p => {
      const r = p.data;
      return `- ${r[1]} / ${cfg.qtyLabel} ${r[4]}개 / 주소: ${r[2] || '(미확인)'} ${r[3] ? '(' + r[3] + ')' : ''} / ${cfg.noteLabel}: ${r[5] || '-'}`;
    });
    sections.push(`■ ${cfg.label} (${pending.length}건)\n` + lines.join('\n'));
    pending.forEach(p => sh.getRange(p.rowIndex, 8).setValue(true));
  });

  if (sections.length === 0) {
    Logger.log('발송할 신규 건 없음.');
    return;
  }

  const subject = `[DCD 서비스] ${Utilities.formatDate(new Date(), 'Asia/Seoul', 'yyyy-MM-dd')} 신청 현황`;
  const body =
    '안녕하세요, DCD 서비스 신청 현황 안내드립니다.\n\n' +
    sections.join('\n\n') +
    '\n\n확인 후 처리 부탁드립니다.\n\n(이 메일은 자동 발송되었습니다.)';

  MAIL_TO.forEach(addr => MailApp.sendEmail(addr, subject, body));
  Logger.log('메일 발송 완료.');
}
