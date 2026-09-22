/**
 * 장비 워런티/정기점검(PM) 관리 웹앱
 * DB: 이 스크립트가 바인딩된 구글 시트 (시트: 장비, PM일정)
 *
 * 규칙 (2026-09-07 확정):
 * - 장비구입(워런티 1년): 시작일 기준 +5개월, +10개월 PM (2건)
 * - 컨트랙(2년/3년 무관): 시작일 기준 +3, +7, +10개월 PM, 전체기간 통틀어 딱 3건
 */

const SHEET_EQUIP = '장비';
const SHEET_PM = 'PM일정';
const MAIL_HOUR = 8; // 매주 월요일 오전 8시 발송

// 실제 배포된 웹앱 exec 주소를 고정값으로 사용 (ScriptApp.getService().getUrl()은
// 트리거/수동실행 시 dev 링크를 반환하는 함정이 있어 사용하지 않음).
// 나중에 "새 배포"로 URL 자체가 바뀌면 이 값도 같이 업데이트해야 함 ("새 버전"은 URL 안 바뀌므로 무관)
const WEB_APP_URL = 'https://script.google.com/macros/s/AKfycbzB7el2VVuchdYvx3jMQcoI7XaCbs_Ws4UcPZIGhhUnstXjInCHXQdT7U8BgZswJA/exec';

// Brick(권역)별 담당 FSE 이메일 (2026-09-07 확정). Brick4는 담당자 2명 공동.
const BRICK_FSE_MAP = {
  'Brick1': 'benl@candelamedical.com',
  'Brick2': 'junyeoly@candelamedical.com',
  'Brick3': 'dasungj@candelamedical.com',
  'Brick4': 'joohyungh@candelamedical.com,jungonp@candelamedical.com',
  'Brick5': 'jaepilj@candelamedical.com',
  'Brick6': 'jongseongc@candelamedical.com',
  'Brick7': 'changsiks@candelamedical.com'
};

function fseEmailForBrick_(brick) {
  const num = String(brick || '').replace(/[^0-9]/g, '');
  return BRICK_FSE_MAP['Brick' + num] || '';
}

// 장비 시트의 기존 행들을 Brick(참고) 컬럼 기준으로 담당FSE이메일을 강제로 다시 채움
// (원인 불문하고 현재 비어있거나 잘못된 값을 Brick 매핑값으로 덮어씀, 여러 번 실행해도 안전)
function backfillFseEmails() {
  const sh = getSheet_(SHEET_EQUIP);
  const last = sh.getLastRow();
  if (last < 2) return { updated: 0, total: 0 };

  const range = sh.getRange(2, 1, last - 1, 12);
  const rows = range.getValues();
  let updated = 0;

  rows.forEach((r, i) => {
    const brick = r[10]; // Brick(참고) 컬럼 (K열)
    if (!brick) return;
    const correctEmail = fseEmailForBrick_(brick);
    if (correctEmail && r[8] !== correctEmail) {
      sh.getRange(i + 2, 9).setValue(correctEmail); // 담당FSE이메일 컬럼 (I열)
      updated++;
    }
  });

  const result = { updated: updated, total: rows.length };
  Logger.log('backfillFseEmails 결과: ' + JSON.stringify(result));
  return result;
}

// 진단용: 단순 카운트만 반환 (직렬화 문제 여부를 getPmSchedule()과 분리해서 확인)
function getDiagCounts() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const equipRows = getSheet_(SHEET_EQUIP).getLastRow();
  const pmRows = getSheet_(SHEET_PM).getLastRow();
  return {
    name: ss.getName(),
    id: ss.getId(),
    equipRows: equipRows,
    pmRows: pmRows
  };
}

// 장비/PM일정 시트를 완전히 초기화 (헤더만 남기고 데이터 전부 삭제)
// Q3 CSV + ISB 등 여러 번 업로드하다 중복이 쌓였을 때 한 번 깨끗하게 리셋하는 용도
function resetAllData() {
  const equipSh = getSheet_(SHEET_EQUIP);
  const pmSh = getSheet_(SHEET_PM);
  const equipLast = equipSh.getLastRow();
  const pmLast = pmSh.getLastRow();

  let equipCleared = 0, pmCleared = 0;
  if (equipLast >= 2) {
    equipCleared = equipLast - 1;
    equipSh.getRange(2, 1, equipCleared, equipSh.getLastColumn()).clearContent();
  }
  if (pmLast >= 2) {
    pmCleared = pmLast - 1;
    pmSh.getRange(2, 1, pmCleared, pmSh.getLastColumn()).clearContent();
  }

  const result = { equipCleared: equipCleared, pmCleared: pmCleared };
  Logger.log('resetAllData 결과: ' + JSON.stringify(result));
  return result;
}

// 특정 날짜 이전(예정일 기준) PM일정 기록을 삭제. 대량 과거 데이터 업로드 후
// "이 시점부터 추적 시작"으로 정리할 때 한 번 실행하는 용도. cutoffDateStr: 'YYYY-MM-DD'
function purgeOldPmRecords(cutoffDateStr) {
  const pmSh = getSheet_(SHEET_PM);
  const last = pmSh.getLastRow();
  if (last < 2) return { kept: 0, removed: 0 };

  const cutoff = new Date(cutoffDateStr);
  if (isNaN(cutoff.getTime())) {
    // 편집기에서 이 함수를 인자 없이 직접 "실행"하면 cutoffDateStr가 undefined가 되어
    // 전체 삭제되는 사고가 났었음(2026-09-14) - 이제는 여기서 막고 에러를 던짐.
    // 반드시 아래처럼 별도 함수로 감싸서 인자를 넣어 실행할 것:
    //   function runPurge() { purgeOldPmRecords('2026-10-01'); }
    throw new Error('cutoffDateStr가 올바른 날짜가 아닙니다: ' + cutoffDateStr + ' - 인자를 넣어 감싼 함수로 실행하세요.');
  }
  cutoff.setHours(0, 0, 0, 0);

  const rows = pmSh.getRange(2, 1, last - 1, 7).getValues();
  const kept = rows.filter(r => {
    const due = new Date(r[3]);
    return due >= cutoff;
  });

  pmSh.getRange(2, 1, last - 1, 7).clearContent();
  if (kept.length > 0) {
    pmSh.getRange(2, 1, kept.length, 7).setValues(kept);
  }

  const result = { kept: kept.length, removed: rows.length - kept.length };
  Logger.log('purgeOldPmRecords 결과 (cutoff=' + cutoffDateStr + '): ' + JSON.stringify(result));
  return result;
}

// ProductID 기준으로 장비 시트 중복 제거 (같은 파일을 실수로 두 번 업로드했을 때).
// ProductID가 없는 행(수동 등록 등)은 중복 판단이 불가하므로 그대로 유지.
function dedupeEquipment() {
  const equipSh = getSheet_(SHEET_EQUIP);
  const last = equipSh.getLastRow();
  if (last < 2) return { before: 0, after: 0, removed: 0 };

  const rows = equipSh.getRange(2, 1, last - 1, 12).getValues();
  const seen = new Set();
  const kept = [];

  rows.forEach(r => {
    const productId = r[11];
    if (!productId) {
      kept.push(r);
      return;
    }
    if (seen.has(productId)) return;
    seen.add(productId);
    kept.push(r);
  });

  equipSh.getRange(2, 1, last - 1, 12).clearContent();
  if (kept.length > 0) {
    equipSh.getRange(2, 1, kept.length, 12).setValues(kept);
  }

  const result = { before: rows.length, after: kept.length, removed: rows.length - kept.length };
  Logger.log('dedupeEquipment 결과: ' + JSON.stringify(result));
  return result;
}

// purgeOldPmRecords는 인자가 필요해서 편집기에서 직접 실행이 안 됨(인자 전달 불가) ->
// 이 함수를 대신 선택해서 실행하면 2026-10-01 이전 PM일정을 정리함
function runPurge() {
  purgeOldPmRecords('2026-10-01');
}

// 장비 시트는 그대로 있는데 PM일정이 비어있거나 잘못 지워졌을 때, 장비 시트의
// 구매유형/시작일 기준으로 PM일정을 처음부터 다시 생성. 기존 PM일정은 먼저 전부 지움
// (완료/건너뜀 등 응답 이력은 복구 불가 - 순수 예정일만 재계산).
function regeneratePmSchedule() {
  const equipSh = getSheet_(SHEET_EQUIP);
  const pmSh = getSheet_(SHEET_PM);

  const equipLast = equipSh.getLastRow();
  if (equipLast < 2) return { created: 0 };

  const pmLast = pmSh.getLastRow();
  if (pmLast >= 2) {
    pmSh.getRange(2, 1, pmLast - 1, pmSh.getLastColumn()).clearContent();
  }

  const equipRows = equipSh.getRange(2, 1, equipLast - 1, 7).getValues(); // ID,병원명,장비명,모델,구매유형,계약기간,시작일
  let nextPmId = 1;
  const newPmRows = [];

  equipRows.forEach(r => {
    const equipId = r[0];
    const purchaseType = r[4];
    const startDate = r[6];
    if (!equipId || !startDate) return;
    pmOffsets_(purchaseType).forEach(m => {
      const pmId = nextPmId++;
      newPmRows.push([pmId, equipId, m, addMonths_(startDate, m), '대기', '', '']);
    });
  });

  if (newPmRows.length > 0) {
    pmSh.getRange(2, 1, newPmRows.length, 7).setValues(newPmRows);
  }

  const result = { equipCount: equipRows.length, created: newPmRows.length };
  Logger.log('regeneratePmSchedule 결과: ' + JSON.stringify(result));
  return result;
}

function doGet(e) {
  const t = HtmlService.createTemplateFromFile('Index');
  t.brick = (e && e.parameter && e.parameter.brick) ? e.parameter.brick : '';
  return t.evaluate()
    .setTitle('Monthly Visit')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function include(filename) {
  return HtmlService.createHtmlOutputFromFile(filename).getContent();
}

function getSheet_(name) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(name);
  if (!sh) {
    sh = ss.insertSheet(name);
    if (name === SHEET_EQUIP) {
      sh.appendRow(['ID', '병원명', '장비명', '모델', '구매유형', '계약기간(년)', '시작일', '담당FSE명', '담당FSE이메일', '등록일시', 'Brick(참고)', 'ProductID(참고)']);
    } else if (name === SHEET_PM) {
      sh.appendRow(['ID', '장비ID', '회차(개월)', '예정일', '상태', '방문일시', '비고']);
    }
  }
  return sh;
}

function nextId_(sheet) {
  const last = sheet.getLastRow();
  if (last < 2) return 1;
  const ids = sheet.getRange(2, 1, last - 1, 1).getValues().flat().filter(v => typeof v === 'number');
  return ids.length ? Math.max(...ids) + 1 : 1;
}

function pmOffsets_(purchaseType) {
  if (purchaseType === '컨트랙') return [3, 7, 10];
  return [5, 10];
}

function addMonths_(date, months) {
  const d = new Date(date);
  d.setMonth(d.getMonth() + months);
  return d;
}

function addEquipment(data) {
  const id = addEquipmentRow_(data);
  return { ok: true, id: id };
}

// addEquipment(단건 폼)과 bulkAddEquipment(CSV 일괄업로드)가 공유하는 핵심 로직
function addEquipmentRow_(data) {
  const sh = getSheet_(SHEET_EQUIP);
  const id = nextId_(sh);
  const startDate = new Date(data.startDate);
  sh.appendRow([
    id, data.hospital, data.equipName, data.model,
    data.purchaseType, data.contractYears || '', startDate,
    data.fseName || '', data.fseEmail || '', new Date(),
    data.brick || '', data.productId || ''
  ]);

  const pmSh = getSheet_(SHEET_PM);
  const offsets = pmOffsets_(data.purchaseType);
  offsets.forEach(m => {
    const pmId = nextId_(pmSh);
    pmSh.appendRow([pmId, id, m, addMonths_(startDate, m), '대기', '', '']);
  });

  return id;
}

// 클라이언트에서 이미 표준 형식으로 정규화한 행 배열을 받아 일괄 등록 (웹앱 파일 업로드 시 호출)
// 우리 CSV 템플릿이든, ISB 리포트(Account/Billing Type/Model 등)든 클라이언트 쪽에서
// 아래 형태로 맞춰서 넘겨줌: {hospital, equipName, model, purchaseType, contractYears,
// startDate, fseName, fseEmail, brick, productId}
// appendRow를 행마다 부르지 않고 한 번에 batch write해서 대량 업로드(수백~천 단위)도 빠르게 처리
function bulkAddEquipmentRows(rows) {
  const equipSh = getSheet_(SHEET_EQUIP);
  const pmSh = getSheet_(SHEET_PM);

  // 이미 등록된 ProductID 집합을 미리 읽어둬서, 전체 리스트를 다시 올려도
  // 기존과 겹치는 장비는 중복 추가하지 않고 건너뜀 (ProductID 없는 행은 판단 불가라 그대로 추가)
  const equipLast = equipSh.getLastRow();
  const existingProductIds = new Set();
  if (equipLast >= 2) {
    equipSh.getRange(2, 12, equipLast - 1, 1).getValues().forEach(r => {
      if (r[0]) existingProductIds.add(String(r[0]));
    });
  }

  let nextEquipId = nextId_(equipSh);
  let nextPmId = nextId_(pmSh);

  const newEquipRows = [];
  const newPmRows = [];
  const errors = [];
  let added = 0;
  let skippedDuplicate = 0;

  rows.forEach((data, i) => {
    const rowNum = i + 2;
    const hospital = String(data.hospital || '').trim();
    const equipName = String(data.equipName || data.model || '').trim();
    const model = String(data.model || equipName).trim();
    let purchaseType = String(data.purchaseType || '').trim();
    const contractYears = String(data.contractYears || '').trim();
    const startDateRaw = String(data.startDate || '').trim();
    const fseName = String(data.fseName || '').trim();
    let fseEmail = String(data.fseEmail || '').trim();
    const brick = String(data.brick || '').trim();
    const productId = String(data.productId || '').trim();

    if (!hospital || !equipName || !startDateRaw) {
      errors.push(rowNum + '행: 병원명/장비명/시작일 누락 - 건너뜀');
      return;
    }
    if (productId && existingProductIds.has(productId)) {
      skippedDuplicate++;
      return;
    }
    purchaseType = purchaseType.indexOf('컨트랙') >= 0 ? '컨트랙' : '장비구입';
    if (!fseEmail && brick) fseEmail = fseEmailForBrick_(brick);

    const startDate = new Date(startDateRaw);
    if (isNaN(startDate.getTime())) {
      errors.push(rowNum + '행: 시작일 형식을 인식 못함(' + startDateRaw + ') - 건너뜀');
      return;
    }

    const equipId = nextEquipId++;
    if (productId) existingProductIds.add(productId);
    newEquipRows.push([
      equipId, hospital, equipName, model, purchaseType, contractYears,
      startDate, fseName, fseEmail, new Date(), brick, productId
    ]);

    pmOffsets_(purchaseType).forEach(m => {
      const pmId = nextPmId++;
      newPmRows.push([pmId, equipId, m, addMonths_(startDate, m), '대기', '', '']);
    });

    added++;
  });

  if (newEquipRows.length > 0) {
    equipSh.getRange(equipSh.getLastRow() + 1, 1, newEquipRows.length, 12).setValues(newEquipRows);
  }
  if (newPmRows.length > 0) {
    pmSh.getRange(pmSh.getLastRow() + 1, 1, newPmRows.length, 7).setValues(newPmRows);
  }

  const result = { added: added, total: rows.length, errors: errors };
  Logger.log('bulkAddEquipmentRows 결과: added=' + added + '/' + rows.length + ', errors=' + errors.length);
  return result;
}

function getEquipmentList() {
  const sh = getSheet_(SHEET_EQUIP);
  const last = sh.getLastRow();
  if (last < 2) return [];
  const rows = sh.getRange(2, 1, last - 1, 11).getValues();
  return rows.map(r => ({
    id: r[0], hospital: r[1], equipName: r[2], model: r[3],
    purchaseType: r[4], contractYears: r[5], startDate: r[6],
    fseName: r[7], fseEmail: r[8], brick: r[10]
  }));
}

function getPmSchedule() {
  const sh = getSheet_(SHEET_PM);
  const last = sh.getLastRow();
  if (last < 2) return [];
  const rows = sh.getRange(2, 1, last - 1, 7).getValues();
  const equipMap = {};
  getEquipmentList().forEach(e => equipMap[e.id] = e);

  const result = rows.map((r, i) => {
    const equip = equipMap[r[1]] || {};
    return {
      rowIndex: i + 2,
      id: r[0], equipId: r[1], monthOffset: r[2],
      dueDate: (r[3] instanceof Date) ? r[3].toISOString() : String(r[3]),
      status: r[4],
      visitedAt: (r[5] instanceof Date) ? r[5].toISOString() : (r[5] || ''),
      note: r[6],
      hospital: equip.hospital, equipName: equip.equipName,
      fseName: equip.fseName, fseEmail: equip.fseEmail, brick: equip.brick,
      purchaseType: equip.purchaseType,
      wcStartDate: (equip.startDate instanceof Date) ? equip.startDate.toISOString() : String(equip.startDate || ''),
      category: (equip.purchaseType === '컨트랙' ? 'C ' : 'W ') + r[2] + 'month'
    };
  });
  Logger.log('getPmSchedule 반환 건수: ' + result.length + ' / 샘플: ' + JSON.stringify(result.slice(0, 2)));
  return result;
}

// 오늘 기준 아직 대기중이면서 예정일이 도래/경과한 항목 (웹앱 열었을 때 팝업 알람용)
// brick 파라미터(웹앱 URL의 ?brick=N)로 담당자를 구분한다 - 로그인 계정으로는 구분 불가
// (회사 이메일은 M365, 이 앱 로그인은 구글 계정이라 서로 다른 계정이기 때문)
// brick이 없는 기본 링크는 관리자용 - 목록은 다 보이지만 팝업 알람은 뜨지 않음(빈 배열 반환)
function getDuePmItems(brick) {
  if (!brick) return [];

  const key = 'Brick' + String(brick).replace(/[^0-9]/g, '');
  const emails = (BRICK_FSE_MAP[key] || '').toLowerCase().split(',').map(s => s.trim()).filter(Boolean);
  if (emails.length === 0) return [];

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return getPmSchedule().filter(p => {
    if (p.status === '완료') return false; // 완료만 진짜 해결된 것으로 침, 건너뜀은 다시 알림 대상
    const due = new Date(p.dueDate);
    due.setHours(0, 0, 0, 0);
    if (due > today) return false;
    const pe = (p.fseEmail || '').toLowerCase().split(',').map(s => s.trim());
    return pe.some(e => emails.includes(e));
  });
}

function recordPmVisit(pmRowIndex, visited, note) {
  const sh = getSheet_(SHEET_PM);
  const status = visited ? '완료' : '건너뜀';
  // 3번 따로 쓰지 않고 한 번에 묶어서 써서(5~7열) 응답 속도를 높임
  sh.getRange(pmRowIndex, 5, 1, 3).setValues([[status, visited ? new Date() : '', note || '']]);
  return { ok: true };
}

// 진단용: weeklyReminder와 완전히 동일한 필터로 브릭별(fseEmail별) 대기건수를 집계
function getPerFseWeeklyCounts() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const weekLater = new Date(today);
  weekLater.setDate(weekLater.getDate() + 7);

  const all = getPmSchedule();
  const targets = all.filter(p => {
    if (p.status === '완료') return false; // 완료만 진짜 해결된 것으로 침, 건너뜀은 다시 알림 대상
    const due = new Date(p.dueDate);
    return due <= weekLater;
  });

  const counts = {};
  targets.forEach(p => {
    const key = p.fseEmail || '(이메일없음)';
    counts[key] = (counts[key] || 0) + 1;
  });

  const result = { totalRows: all.length, targetCount: targets.length, byFse: counts };
  Logger.log('getPerFseWeeklyCounts 결과: ' + JSON.stringify(result));
  return result;
}

// 매주 월요일 오전 실행: 이번주 도래분 + 지연분을 담당FSE별로 묶어 메일 발송
function weeklyReminder() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const weekLater = new Date(today);
  weekLater.setDate(weekLater.getDate() + 7);

  const targets = getPmSchedule().filter(p => {
    if (p.status === '완료') return false; // 완료만 진짜 해결된 것으로 침, 건너뜀은 다시 알림 대상
    const due = new Date(p.dueDate);
    return due <= weekLater;
  });

  if (targets.length === 0) return;

  const byFse = {};
  targets.forEach(p => {
    const key = p.fseEmail || '';
    if (!key) return;
    if (!byFse[key]) byFse[key] = [];
    byFse[key].push(p);
  });

  const webAppUrl = WEB_APP_URL;
  const tz = Session.getScriptTimeZone();

  Object.keys(byFse).forEach(fseEmail => {
    const items = byFse[fseEmail];
    const brickNum = brickNumberForFseEmail_(fseEmail);
    const link = webAppUrl + (brickNum ? ('?brick=' + brickNum) : '');
    Logger.log('링크생성 - fseEmail=[' + fseEmail + '] brickNum=[' + brickNum + '] link=' + link);

    let html = '<p>이번 주 정기점검(PM) 예정/지연 건입니다.</p>';
    html += '<table border="1" cellpadding="6" style="border-collapse:collapse;">';
    html += '<tr><th>병원</th><th>장비</th><th>예정일</th><th>상태</th></tr>';
    items.forEach(p => {
      const due = new Date(p.dueDate);
      const overdue = due < today;
      html += '<tr><td>' + p.hospital + '</td><td>' + p.equipName + '</td><td>' +
        Utilities.formatDate(due, tz, 'yyyy-MM-dd') + '</td><td>' + (overdue ? '지연' : '예정') + '</td></tr>';
    });
    html += '</table>';
    html += '<p><a href="' + link + '">여기를 눌러 방문 처리(Yes/No) 및 비고 입력</a></p>';

    try {
      MailApp.sendEmail({
        to: fseEmail,
        subject: '[정기점검 알림] 이번주 PM 예정/지연 ' + items.length + '건',
        htmlBody: html
      });
      Logger.log('발송 성공: ' + fseEmail + ' (' + items.length + '건)');
    } catch (e) {
      Logger.log('발송 실패: ' + fseEmail + ' - ' + e.message);
    }
  });
}

// fseEmail 값(BRICK_FSE_MAP의 값과 동일한 문자열)으로 역으로 브릭 번호를 찾음
// (수동 등록된 장비처럼 매핑에 없는 이메일이면 빈 문자열 반환 -> 기본 링크로 폴백)
function brickNumberForFseEmail_(fseEmail) {
  const target = (fseEmail || '').toLowerCase();
  const found = Object.keys(BRICK_FSE_MAP).find(k => BRICK_FSE_MAP[k].toLowerCase() === target);
  return found ? found.replace(/[^0-9]/g, '') : '';
}

// 최초 1회 수동 실행: Q3 Visit 리포트(SeedData.gs) 데이터를 장비/PM일정 시트에 반영
// 여러 번 실행해도 중복 삽입되지 않도록 ProductID / (장비ID+회차+예정일) 기준으로 건너뜀
function importSeedData() {
  const equipSh = getSheet_(SHEET_EQUIP);
  const pmSh = getSheet_(SHEET_PM);
  const tz = Session.getScriptTimeZone();

  const existingEquipLast = equipSh.getLastRow();
  const existingProductIds = new Set();
  const productIdToEquipId = {};
  if (existingEquipLast >= 2) {
    equipSh.getRange(2, 1, existingEquipLast - 1, 12).getValues().forEach(r => {
      const pid = r[11];
      if (pid) {
        existingProductIds.add(pid);
        productIdToEquipId[pid] = r[0];
      }
    });
  }

  let nextEquipId = nextId_(equipSh);
  const newEquipRows = [];
  EQUIPMENT_SEED.forEach(e => {
    if (existingProductIds.has(e.productId)) return;
    const id = nextEquipId++;
    productIdToEquipId[e.productId] = id;
    existingProductIds.add(e.productId);
    newEquipRows.push([
      id, e.hospital, e.equipName, e.model, e.purchaseType, '',
      new Date(e.startDate), '', fseEmailForBrick_(e.brick), new Date(), e.brick, e.productId
    ]);
  });
  if (newEquipRows.length > 0) {
    equipSh.getRange(equipSh.getLastRow() + 1, 1, newEquipRows.length, 12).setValues(newEquipRows);
  }

  const existingPmLast = pmSh.getLastRow();
  const existingPmKeys = new Set();
  if (existingPmLast >= 2) {
    pmSh.getRange(2, 1, existingPmLast - 1, 7).getValues().forEach(r => {
      existingPmKeys.add(r[1] + '|' + r[2] + '|' + Utilities.formatDate(new Date(r[3]), tz, 'yyyy-MM-dd'));
    });
  }

  let nextPmId = nextId_(pmSh);
  const newPmRows = [];
  PM_SEED.forEach(p => {
    const equipId = productIdToEquipId[p.productId];
    if (!equipId) return;
    const key = equipId + '|' + p.monthOffset + '|' + p.dueDate;
    if (existingPmKeys.has(key)) return;
    existingPmKeys.add(key);
    const id = nextPmId++;
    newPmRows.push([
      id, equipId, p.monthOffset, new Date(p.dueDate), p.status,
      p.visitedAt ? new Date(p.visitedAt) : '', '[' + p.type + '] ' + p.note
    ]);
  });
  if (newPmRows.length > 0) {
    pmSh.getRange(pmSh.getLastRow() + 1, 1, newPmRows.length, 7).setValues(newPmRows);
  }

  const result = { equipmentAdded: newEquipRows.length, pmAdded: newPmRows.length };
  Logger.log('importSeedData 결과: ' + JSON.stringify(result));
  return result;
}

// 최초 1회 수동 실행: 매주 월요일 트리거 설치
function initSetup() {
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === 'weeklyReminder') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('weeklyReminder')
    .timeBased()
    .onWeekDay(ScriptApp.WeekDay.MONDAY)
    .atHour(MAIL_HOUR)
    .create();
}
