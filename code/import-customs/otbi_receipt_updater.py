# -*- coding: utf-8 -*-
"""
otbi_receipt_updater.py

Oracle Fusion OTBI Agent(스케줄 이메일, 매시간 발송)가 보내주는
"OTBI 용마입고 리포트" 첨부 엑셀을 읽어서, (TO번호, 자재코드) 조합별
실제 입고(Receipt) 트랜잭션 날짜를 뽑아내고,

1) 수입신고실적(20260211)자동화.xlsx 의 "실제입고일" 컬럼
   (SO Number = TO번호 + 자재코드 조합으로 매칭)
2) IR 신청목록 & Instransit(...).xlsx 의 Urgent Item 시트
   "실제입고일" 컬럼 (P/N + 최근선적일 → Intransit 시트에서 TO번호
   역추적 → (TO번호, P/N) 조합으로 매칭. 모호하면 skip)

TO 하나에 자재가 여러 개 있고 부분입고(자재별로 날짜가 다름)되는
경우가 있어서, TO 단위가 아니라 (TO, 자재코드) 단위로 매칭한다
(2026-07-07 요청사항 반영).

에 채워 넣는다. 1시간마다(스케줄러) 실행되는 것을 전제로,
매번 실행해도 안전(idempotent)하도록 값이 달라질 때만 덮어쓴다.

주의:
- urgent_item_freezer.py 가 Urgent Item 시트의 B/C/E/I/J/K 컬럼을
  전담하므로, 이 스크립트는 그 컬럼들을 절대 읽기 전용 이상으로
  건드리지 않는다 (새 컬럼 L에만 쓴다).
- 실적파일/IR파일 모두 쓰기 전 백업을 남긴다.
- 파일이 열려있어 저장이 안 되면(PermissionError) 에러를 남기고
  다음 실행 때 재시도하면 되므로 스크립트 자체는 죽지 않게 한다.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from datetime import datetime, timedelta, date

import openpyxl

# ==============================================================
# 경로 설정
# ==============================================================
ROOT = r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입"

REPORT_SAVE_DIR = os.path.join(ROOT, "OTBI 실입고 Report")

PERF_FILE_PATH = os.path.join(ROOT, "수입신고실적(20260211)자동화.xlsx")
PERF_BACKUP_DIR = os.path.join(ROOT, "백업")

IR_FILE_PATH = os.path.join(ROOT, "IR 신청목록 & Instransit(20260303~).xlsx")
IR_BACKUP_DIR = os.path.join(ROOT, "Intransit 내부공유", "백업")

LOG_PATH = os.path.join(os.path.dirname(__file__), "otbi_receipt_updater.log")

# Outlook: 받은편지함 하위 이 경로 폴더에서 이 제목을 포함하는 메일을 찾는다.
# (Fusion OTBI Agent > Delivery Content > Subject 에서 이 문자열로 설정해둠.
#  실제로 메일이 Inbox 바로 아래가 아니라 Operation\OTBI Report 하위폴더로
#  옴 - 2026-07-07 확인함)
OUTLOOK_FOLDER_PATH = ["Operation", "OTBI Report"]
MAIL_SUBJECT_CONTAINS = "OTBI 용마입고 리포트"
LOOKBACK_HOURS = 30  # 이 시간 이내 메일만 확인 (하루 조금 넘게, 공백 방지용 여유)

# 2026-07-07: 실적파일은 기존 "용마입고"(+2영업일 추정치) 컬럼을
# "용마 실제 입고"로 개명해서 그 자리에 실데이터를 채운다(추정치 로직은
# pdf_auto_updater.py에서 PROTECTED_COLS로 막아둠). 이미 존재하는 컬럼이므로
# 새로 만들지 않고 헤더명으로 찾기만 한다.
PERF_COL_NAME = "용마 실제 입고"
# IR통합파일 Urgent Item 시트는 기존 컬럼 건드리지 않고 새 컬럼만 추가.
IR_NEW_COL_NAME = "실제입고일"
FREEZE_VALUE = "입고됨"  # urgent_item_freezer.py 와 동일한 값 (Urgent Item K열)

# Urgent Item 시트에서 urgent_item_freezer.py 가 전담하는 컬럼(절대 안 씀,
# 읽기만 함 — B/C/E는 메일 내용 표시용으로 값만 읽는다)
URGENT_COL_PN = 2        # B
URGENT_COL_DESC = 3      # C: 품명
URGENT_COL_REQUESTER = 5  # E: 요청자
URGENT_COL_STATUS = 11   # K
URGENT_COL_SHIP = 9      # I (최근선적일, 계산된 값 기준)
URGENT_NEW_COL = 12      # L (이 스크립트가 쓰는 유일한 컬럼)

# urgent_item_freezer.py 와 동일한 수신자 (2026-07-07 요청)
URGENT_MAIL_TO = "ckserviceteam@candelamedical.com"
URGENT_MAIL_CC = "miaej@candelamedical.com; bohyunk@candelamedical.com"

# 2026-07-08: pdf_auto_updater.py의 "+2영업일 추정치" 기반 통관완료 알림을
# 대체 — 이제 OTBI 실입고(Receipt) 매칭 시점에 발송한다(pdf_auto_updater.py
# 쪽 발송 로직은 일시 중단됨). 감시 자재코드/수신자는 그쪽과 동일하게 유지.
ALERT_CODE_NAMES = {
    "9914-CE-9036": "GMPP",
    "9914-VT-0300": "Vbeam",
    "9SYS7751":     "놀리스",
    "9914-JB-9060": "피코웨이",
}
ALERT_MAIL_TO = [
    "ckserviceteam@candelamedical.com",
    "CKSalesTeam@candelamedical.com",
    "CK_clinical@syneron.onmicrosoft.com",
]
ALERT_MAIL_CC = [
    "CK-Operation@syneron.onmicrosoft.com",
]

# 2026-08-10 사용자 요청: 자동 발송/초안 메일 글꼴을 굴림 -> 맑은 고딕으로 통일.
# 평문(.Body)으로 만들면 Outlook의 평문 기본 글꼴을 따라가므로 HTML로 만든다.
MAIL_FONT_CSS = "font-family:'맑은 고딕',Malgun Gothic,sans-serif;font-size:10.0pt"


def mail_text_to_html(text: str) -> str:
    """평문 본문을 맑은 고딕 HTML로 감싼다.
    HTML은 연속 공백을 하나로 줄이므로, 품목 목록의 정렬이 뭉개지지 않도록
    2칸 이상 연속 공백은 &nbsp;로 보존한다."""
    import html as html_module
    import re as re_module
    esc = html_module.escape(str(text or ""))
    esc = esc.replace("\r\n", "\n").replace("\r", "\n")
    esc = re_module.sub(r"  +", lambda mm: "&nbsp;" * len(mm.group()), esc)
    esc = esc.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
    return f'<div style="{MAIL_FONT_CSS}">' + esc.replace("\n", "<br>") + "</div>"


# ==============================================================
# 유틸
# ==============================================================
def log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def norm_str(v) -> str:
    """숫자/문자 표기 차이(760049 vs 760049.0 등) 제거."""
    if v is None:
        return ""
    try:
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
    except Exception:
        pass
    s = str(v).strip()
    if s.endswith(".0") and s[:-2].isdigit():
        return s[:-2]
    return s


def norm_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d-%b-%Y", "%d-%b-%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None


def norm_hdr(s) -> str:
    return re.sub(r"\s+", "", str(s or "")).strip().lower()


def normalize_alert_code(item_val_norm: str) -> str:
    """자재코드 매칭용. item_val_norm은 이미 norm_str(...).upper() 처리된 값.
    '9SYS7751-CNDL' 같은 -CNDL 접미사만 제거(다른 감시 코드엔 없음)."""
    s = item_val_norm
    if s.endswith("-CNDL"):
        s = s[: -len("-CNDL")]
    return s


def _fmt_qty(v) -> str:
    try:
        f = float(str(v).replace(",", ""))
    except Exception:
        return str(v) if v is not None else "0"
    return str(int(f)) if f == int(f) else str(f)


def _fmt_dt(v) -> str:
    """입고일(datetime이면 시:분까지, date뿐이면 날짜만) 표시용 포맷."""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    if isinstance(v, date):
        return v.strftime("%Y-%m-%d")
    return str(v) if v is not None else ""


def build_header_map(ws, header_row: int = 1) -> dict:
    m = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(header_row, c).value
        k = norm_hdr(v)
        if k:
            m[k] = c
    return m


def get_col(col_map: dict, *candidates: str):
    for name in candidates:
        k = norm_hdr(name)
        if k in col_map:
            return col_map[k]
    return None


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def find_subfolder(parent_folder, target_name: str):
    target = target_name.strip().lower()
    for f in parent_folder.Folders:
        if str(f.Name).strip().lower() == target:
            return f
    return None


def get_folder_by_path(root_folder, path_list):
    cur = root_folder
    for name in path_list:
        nxt = find_subfolder(cur, name)
        if nxt is None:
            return None, name, cur
        cur = nxt
    return cur, None, None


def backup_file(path: str, backup_dir: str) -> str:
    os.makedirs(backup_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = os.path.join(backup_dir, f"backup_{ts}.xlsx")
    shutil.copy(path, out)
    log(f"백업 완료: {out}")
    return out


# ==============================================================
# 1) Outlook에서 최신 OTBI 리포트 메일 다운로드
# ==============================================================
def download_latest_otbi_mail() -> str | None:
    """받은편지함에서 최근 LOOKBACK_HOURS 이내, 제목에 MAIL_SUBJECT_CONTAINS가
    포함된 메일 중 가장 최근 것의 xlsx 첨부를 저장. 이미 저장된 시각(분 단위)
    이면 skip. 새로 저장했으면 경로 반환, 아니면 None."""
    import win32com.client

    os.makedirs(REPORT_SAVE_DIR, exist_ok=True)

    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    inbox = outlook.GetDefaultFolder(6)  # 받은편지함

    target_folder, missing_name, parent = get_folder_by_path(inbox, OUTLOOK_FOLDER_PATH)
    if target_folder is None:
        parent_name = "(Inbox)" if parent is None else str(parent.Name)
        raise RuntimeError(
            f"Outlook 폴더를 찾을 수 없음: '{missing_name}' (부모: {parent_name}). "
            f"경로 확인: Inbox -> " + " -> ".join(OUTLOOK_FOLDER_PATH)
        )

    items = target_folder.Items
    items.Sort("[ReceivedTime]", True)  # 최신순

    cutoff = datetime.now() - timedelta(hours=LOOKBACK_HOURS)

    for i in range(1, items.Count + 1):
        try:
            mail = items.Item(i)
        except Exception:
            continue
        if getattr(mail, "Class", None) != 43:  # MailItem
            continue

        received_dt = datetime(
            mail.ReceivedTime.year, mail.ReceivedTime.month, mail.ReceivedTime.day,
            mail.ReceivedTime.hour, mail.ReceivedTime.minute, mail.ReceivedTime.second,
        )
        if received_dt < cutoff:
            break  # 최신순 정렬이므로 여기부터는 더 볼 필요 없음

        subject = str(mail.Subject or "")
        if MAIL_SUBJECT_CONTAINS not in subject:
            continue

        # xlsx 첨부 찾기
        att_to_save = None
        for j in range(1, mail.Attachments.Count + 1):
            att = mail.Attachments.Item(j)
            if str(att.FileName).strip().lower().endswith(".xlsx"):
                att_to_save = att
                break
        if att_to_save is None:
            continue

        suffix = received_dt.strftime("%Y%m%d_%H%M")
        out_name = safe_filename(f"OTBI_용마입고_{suffix}.xlsx")
        out_path = os.path.join(REPORT_SAVE_DIR, out_name)

        if os.path.exists(out_path):
            log(f"이미 저장된 메일(스킵): {out_name}")
            return None  # 최신 메일이 이미 처리됨 → 더 볼 필요 없음

        att_to_save.SaveAsFile(out_path)
        log(f"메일 첨부 저장: {out_name}")
        return out_path

    log("조건에 맞는 신규 메일 없음")
    return None


def pick_latest_report_file() -> str | None:
    if not os.path.isdir(REPORT_SAVE_DIR):
        return None
    candidates = [
        os.path.join(REPORT_SAVE_DIR, f)
        for f in os.listdir(REPORT_SAVE_DIR)
        if f.lower().endswith(".xlsx")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def extract_report_time(report_path: str) -> datetime:
    """이번 실행에서 쓰는 리포트 파일이 도착(메일 수신)/저장된 시각을 구한다.
    파일명이 download_latest_otbi_mail()에서 만든 'OTBI_용마입고_YYYYMMDD_HHMM.xlsx'
    형식이면 그 안의 메일 ReceivedTime을 그대로 쓰고, 파싱이 안 되면(옛 파일 등)
    로컬 파일 저장 시각(mtime)으로 대체한다."""
    base = os.path.basename(report_path)
    m = re.search(r"(\d{8})_(\d{4})", base)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M")
        except Exception:
            pass
    return datetime.fromtimestamp(os.path.getmtime(report_path))


# ==============================================================
# 2) OTBI 리포트 → {TO번호: 최소 Receipt 날짜} 매핑
# ==============================================================
def find_header_row(ws, keyword: str = "Transaction Date", max_scan_rows: int = 20) -> int:
    """OTBI Agent 내보내기는 1행에 분석 제목, 그 아래 빈 행 후 진짜 헤더가
    오는 경우가 많다. keyword가 있는 행을 헤더 행으로 간주."""
    kw = norm_hdr(keyword)
    max_r = min(max_scan_rows, ws.max_row or 1)
    for r in range(1, max_r + 1):
        for c in range(1, ws.max_column + 1):
            if norm_hdr(ws.cell(r, c).value) == kw:
                return r
    return 1


def build_receipt_map(report_path: str) -> dict:
    wb = openpyxl.load_workbook(report_path, data_only=True, read_only=True)
    try:
        ws = wb.worksheets[0]
        header_row = find_header_row(ws, keyword="Transaction Date", max_scan_rows=20)
        col_map = build_header_map(ws, header_row=header_row)

        c_to = get_col(
            col_map,
            "Transaction Source Reference",  # 실제 확인된 헤더명 (2026-07-07)
            "거래 출처 참조", "Transaction Source Name", "Source Header Number",
            "Source Transaction Number", "Transfer Order Number", "TO Number",
        )
        c_date = get_col(col_map, "Transaction Date")
        c_type = get_col(col_map, "Transaction Type Description", "Transaction Type")
        c_item = get_col(col_map, "Item")  # 자재코드 형식 (예: 7122-00-9420)

        missing = []
        if c_to is None:
            missing.append("TO번호(거래 출처 참조)")
        if c_date is None:
            missing.append("Transaction Date")
        if c_item is None:
            missing.append("Item(자재코드)")
        if missing:
            raise ValueError(
                f"OTBI 리포트에서 필요한 컬럼을 못 찾음: {missing}\n"
                f"실제 헤더(row {header_row}): {list(col_map.keys())}\n"
                f"→ Fusion에서 해당 분석의 Criteria에 '거래 출처 참조'(TO번호) 컬럼을 "
                f"추가해서 다시 저장해야 함 (Agent는 저장된 분석을 그대로 참조하므로 "
                f"다음 스케줄 실행부터 자동으로 반영됨)."
            )

        # OTBI 내보내기는 같은 그룹(Transaction Source Type/Type 등)의 반복값을
        # 두 번째 줄부터 빈칸으로 표시한다 (엑셀 그룹 병합처럼). 컬럼별로
        # 마지막으로 본 값을 아래로 채워 내린다(forward-fill).
        last_seen: dict[int, object] = {}
        # 2026-07-20: 같은 (TO,자재) 키로 날짜가 여러 개 나올 수 있다(TO 재사용 +
        # 리포트가 과거 이벤트를 계속 포함하는 롤링 히스토리라서). 예전엔 그중
        # "가장 이른 날짜" 하나만 남기고 나머지를 버렸는데, 그러면 나중에 재사용된
        # TO의 신고건은 그 오래된 날짜 때문에 "신고일자보다 입고가 빠르다" 가드에
        # 영원히 걸려서, 실제로 리포트에 존재하는 더 최근의 정확한 입고일을 찾지도
        # 못하고 계속 빈칸으로 남는 문제가 있었다(TO 7694382/FIN101959 등 실측 확인).
        # 그래서 날짜 하나만 남기지 않고 전부 리스트로 모아뒀다가, 사용하는 쪽에서
        # 각 신고일자에 맞는 날짜를 골라 쓰도록 바꾼다.
        receipt_map: dict[tuple[str, str], list[date]] = {}
        for raw_row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            if all(v is None for v in raw_row):
                continue  # 완전히 빈 행

            row_vals = {}
            for c in range(1, len(raw_row) + 1):
                v = raw_row[c - 1]
                if v is not None:
                    last_seen[c] = v
                row_vals[c] = last_seen.get(c)

            to_val = norm_str(row_vals.get(c_to))
            item_val = norm_str(row_vals.get(c_item)).upper()
            if not to_val or not item_val:
                continue
            if c_type is not None:
                type_val = str(row_vals.get(c_type) or "")
                if "receipt" not in type_val.lower():
                    continue  # Shipment 등 다른 유형은 제외 (안전장치, 분석 필터가 이미 걸려있어도 이중 확인)
            d = norm_date(row_vals.get(c_date))
            if d is None:
                continue
            key = (to_val, item_val)
            receipt_map.setdefault(key, [])
            if d not in receipt_map[key]:
                receipt_map[key].append(d)

        for dates in receipt_map.values():
            dates.sort()

        return receipt_map
    finally:
        wb.close()


# ==============================================================
# 3) 실적파일 업데이트
# ==============================================================
def update_perf_file(receipt_map: dict, report_time: datetime | None = None) -> int:
    if not receipt_map:
        return 0
    try:
        wb = openpyxl.load_workbook(PERF_FILE_PATH)
    except PermissionError:
        log("[경고] 실적파일이 열려있어 접근 불가 (닫고 다음 실행 때 재시도됨)")
        return -1

    try:
        ws = wb.worksheets[0]
        col_map = build_header_map(ws, header_row=1)

        c_to = get_col(col_map, "SO Number")
        c_item = get_col(col_map, "자재코드")
        if c_to is None:
            raise ValueError(f"실적파일에서 'SO Number' 컬럼을 못 찾음: {list(col_map.keys())}")
        if c_item is None:
            raise ValueError(f"실적파일에서 '자재코드' 컬럼을 못 찾음: {list(col_map.keys())}")

        c_new = get_col(col_map, PERF_COL_NAME)
        if c_new is None:
            raise ValueError(
                f"실적파일에서 '{PERF_COL_NAME}' 컬럼을 못 찾음: {list(col_map.keys())}\n"
                f"→ 기존 '용마입고' 컬럼이 '{PERF_COL_NAME}'로 개명되어 있어야 함."
            )

        c_decl = get_col(col_map, "신고번호")
        c_decl_date = get_col(col_map, "신고일자")
        c_bl = get_col(col_map, "B/L번호")
        c_qty = get_col(col_map, "수량")
        if c_decl_date is None:
            raise ValueError(f"실적파일에서 '신고일자' 컬럼을 못 찾음: {list(col_map.keys())}")

        updated = 0
        skipped_no_decl = 0
        skipped_before_decl = 0
        alert_items = []
        for r in range(2, ws.max_row + 1):
            to_val = norm_str(ws.cell(r, c_to).value)
            item_val = norm_str(ws.cell(r, c_item).value).upper()
            key = (to_val, item_val)
            if not to_val or not item_val or key not in receipt_map:
                continue
            # 2026-07-08/13: 신고일자(통관)가 아직 없으면, 또는 실제입고일이
            # 신고일자보다 이르면 절대 입고일을 넣지 않는다. 통관 완료 이후에야
            # 실제 입고가 가능하므로(신고일자 <= 실제입고일), 이 순서가 깨지면
            # TO 재사용(같은 TO가 여러 신고번호로 쪼개져 나오는 경우가 흔함 —
            # 나중에 Delivery Number로 더 정밀하게 매칭할 예정) 때문에 생긴
            # 오매칭이다.
            decl_date_val = norm_date(ws.cell(r, c_decl_date).value)
            if decl_date_val is None:
                skipped_no_decl += 1
                continue
            # 2026-07-20: 같은 키에 날짜가 여러 개 있을 수 있으므로, 이 신고일자
            # 이후(당일 포함) 중 가장 이른 것을 이 신고건의 실제입고일로 본다.
            # (그 이전 날짜들은 더 앞선 신고건들이 이미 썼거나 관련 없는 이벤트)
            candidate_dates = [d for d in receipt_map[key] if d >= decl_date_val]
            if not candidate_dates:
                skipped_before_decl += 1
                continue
            new_date = min(candidate_dates)
            cell = ws.cell(r, c_new)
            # 2026-07-13: 이미 값이 있으면(날짜 불문) 절대 덮어쓰지 않는다.
            # 같은 (TO,자재코드) 키로 나중에 별개의 입고 이벤트가 또 잡혀도
            # (예: 7/12에 이미 확정된 건이, 한 달 뒤 8/13 다른 건과 같은 키를
            # 공유해서) 이미 기록된 실제입고일을 절대 갈아치우면 안 되기 때문.
            if cell.value is not None:
                continue
            # 2026-08-01: OTBI의 Transaction Date는 날짜만 있고 시각이 없다.
            # 이 날짜(new_date)에, 이 값을 확인하는 데 쓴 리포트(메일)가
            # 도착/저장된 시각(report_time)의 시:분을 붙여서 같은 셀에 기록한다
            # (실제 입고 시각 그 자체는 아니고 확인 시점의 근사치).
            if report_time is not None:
                cell.value = datetime.combine(new_date, report_time.time())
                cell.number_format = "yyyy-mm-dd hh:mm"
            else:
                cell.value = new_date
                cell.number_format = "yyyy-mm-dd"
            updated += 1
            mail_arrival = cell.value

            alert_code = normalize_alert_code(item_val)
            if alert_code in ALERT_CODE_NAMES:
                alert_items.append({
                    "신고번호": norm_str(ws.cell(r, c_decl).value) if c_decl else "",
                    "자재코드": alert_code,
                    "제품명": ALERT_CODE_NAMES[alert_code],
                    "수량": ws.cell(r, c_qty).value if c_qty else "",
                    "AWB": norm_str(ws.cell(r, c_bl).value) if c_bl else "",
                    "TO번호": to_val,
                    "입고일": mail_arrival,
                })

        if skipped_no_decl > 0:
            log(f"신고일자 없어 스킵(아직 통관 전, TO 재사용 오매칭 방지): {skipped_no_decl}건")
        if skipped_before_decl > 0:
            log(f"실제입고일이 신고일자보다 빨라서 스킵(TO 재사용 오매칭 방지): {skipped_before_decl}건")

        if updated > 0:
            backup_file(PERF_FILE_PATH, PERF_BACKUP_DIR)
            wb.save(PERF_FILE_PATH)
            log(f"실적파일 업데이트: {updated}건")
            if alert_items:
                try:
                    send_customs_arrival_draft(alert_items)
                except Exception as e:
                    log(f"[경고] 통관완료 알림 메일 초안 작성 실패: {e}")
        else:
            log("실적파일: 변경 없음")
        return updated
    finally:
        wb.close()


def send_customs_arrival_draft(items: list) -> None:
    """감시 자재코드(ALERT_CODE_NAMES)가 OTBI 실입고로 확인되면 메일 초안만 작성.
    2026-07-08: pdf_auto_updater.py의 옛 +2영업일 추정치 기반 알림(send_customs_alert,
    현재 호출 중단)을 대체 — '실제 입고 확인 시점'(OTBI Receipt 트랜잭션 매칭)에 발송한다.
    신고번호 단위로 메일 1통, AWB별 섹션으로 묶어 표시. 자동 발송 없이 초안(Save)만 남긴다."""
    if not items:
        return
    import win32com.client
    from collections import OrderedDict

    by_decl = OrderedDict()
    for it in items:
        decl = it["신고번호"] or "(신고번호 미상)"
        by_decl.setdefault(decl, []).append(it)

    outlook = win32com.client.Dispatch("Outlook.Application")
    divider = "─────────────────────"

    for decl, decl_items in by_decl.items():
        by_awb = OrderedDict()
        for it in decl_items:
            awb = it["AWB"] or "(AWB 미상)"
            by_awb.setdefault(awb, []).append(it)

        sections = []
        grouped_codes = []
        for awb, awb_items in by_awb.items():
            lines = [f"[AWB: {awb}]"]
            for it in awb_items:
                grouped_codes.append(it["자재코드"])
                lines.append(
                    f"  • {it['제품명']} ({it['자재코드']}) : {_fmt_qty(it['수량'])}대"
                    f" — 입고일시 {_fmt_dt(it['입고일'])}"
                )
            sections.append("\n".join(lines))
        item_block = f"\n{divider}\n".join(sections)

        mail = outlook.CreateItem(0)  # olMailItem
        mail.To = "; ".join(ALERT_MAIL_TO)
        mail.CC = "; ".join(ALERT_MAIL_CC)
        mail.Subject = "[통관 완료] 입고 안내"
        mail.HTMLBody = mail_text_to_html(
            f"Dear all,\n\n"
            f"아래 제품이 용마에 실제 입고된 것이 확인되었습니다(Fusion OTBI 확인).\n"
            f"업무에 참고 부탁드립니다.\n\n"
            f"{divider}\n"
            f"{item_block}\n"
            f"{divider}\n\n"
            f"감사합니다.\n"
            f"채윤길 드림"
        )
        mail.Save()  # 초안(임시보관함)만 저장 — 자동 발송 안 함
        log(f"✉️ 통관완료 알림 메일 초안 저장: {grouped_codes} | AWB {list(by_awb.keys())} | 신고번호 {decl}")


# ==============================================================
# 4) IR통합파일 Urgent Item 업데이트
#    (Intransit 시트에서 Item Code+Ship Date → TO번호 역인덱스 구축)
# ==============================================================
def build_intransit_index(ws_intransit) -> dict:
    col_map = build_header_map(ws_intransit, header_row=1)
    c_item = get_col(col_map, "Item Code")
    c_ship = get_col(col_map, "Ship Date")
    c_to = get_col(col_map, "Transfer order Number", "Transfer Order Number")
    if c_item is None or c_ship is None or c_to is None:
        raise ValueError(
            f"Intransit 시트에서 필요한 컬럼을 못 찾음 (Item Code/Ship Date/"
            f"Transfer order Number): {list(col_map.keys())}"
        )

    # read_only 모드에서는 ws.cell(r, c) 랜덤 접근이 매우 느리다(사실상
    # 매 호출마다 처음부터 다시 스캔하는 것과 비슷한 비용). 반드시
    # iter_rows(values_only=True)로 순차 접근해야 한다 (13,000+ 행에서
    # 랜덤 접근 시 몇 초 걸릴 일이 수십 분으로 늘어나는 것 실측 확인함).
    max_c = max(c_item, c_ship, c_to)
    index: dict[tuple, list] = {}
    for row in ws_intransit.iter_rows(min_row=2, max_col=max_c, values_only=True):
        item = norm_str(row[c_item - 1]).upper()
        ship = norm_date(row[c_ship - 1])
        to_num = norm_str(row[c_to - 1])
        if not item or ship is None or not to_num:
            continue
        key = (item, ship)
        index.setdefault(key, [])
        if to_num not in index[key]:
            index[key].append(to_num)
    return index


def update_ir_file(receipt_map: dict, report_time: datetime | None = None) -> int:
    if not receipt_map:
        return 0
    try:
        # 읽기 전용: 수식이 계산된 실제 값(날짜 등)을 봐야 하므로 data_only=True
        wb_read = openpyxl.load_workbook(IR_FILE_PATH, data_only=True, read_only=True)
    except PermissionError:
        log("[경고] IR통합파일이 열려있어 접근 불가 (닫고 다음 실행 때 재시도됨)")
        return -1

    try:
        ws_intransit_r = wb_read["Intransit"]
        ws_urgent_r = wb_read["Urgent Item"]

        intransit_index = build_intransit_index(ws_intransit_r)

        # (row_idx, to_number, pn, desc, requester) 목록만 뽑아둔다
        # (실제 쓰기는 별도 write 모드에서). 여기도 read_only 모드이므로
        # iter_rows로 순차 접근 (위와 동일한 이유)
        max_c = max(URGENT_COL_PN, URGENT_COL_DESC, URGENT_COL_REQUESTER,
                    URGENT_COL_STATUS, URGENT_COL_SHIP)
        to_write: list[tuple[int, str, str, str, str]] = []
        for r, row in enumerate(
            ws_urgent_r.iter_rows(min_row=2, max_col=max_c, values_only=True), start=2
        ):
            pn = norm_str(row[URGENT_COL_PN - 1]).upper()
            if not pn:
                continue
            status = str(row[URGENT_COL_STATUS - 1] or "").strip()
            if status == FREEZE_VALUE:
                continue  # urgent_item_freezer.py가 이미 확정 처리한 행은 건너뜀

            ship = norm_date(row[URGENT_COL_SHIP - 1])
            if ship is None:
                continue

            candidates = intransit_index.get((pn, ship), [])
            if len(candidates) != 1:
                continue  # 매칭 없음 또는 모호함 → skip (억지 매칭 안 함)

            to_num = candidates[0]
            if (to_num, pn) in receipt_map:
                desc = str(row[URGENT_COL_DESC - 1] or "")
                requester = str(row[URGENT_COL_REQUESTER - 1] or "")
                to_write.append((r, to_num, pn, desc, requester))
    finally:
        wb_read.close()

    if not to_write:
        log("IR통합파일: 매칭된 신규 건 없음")
        return 0

    wb_write = openpyxl.load_workbook(IR_FILE_PATH)
    try:
        ws_urgent_w = wb_write["Urgent Item"]

        header_cell = ws_urgent_w.cell(1, URGENT_NEW_COL)
        if norm_hdr(header_cell.value) != norm_hdr(IR_NEW_COL_NAME):
            header_cell.value = IR_NEW_COL_NAME
            log(f"Urgent Item 시트에 '{IR_NEW_COL_NAME}' 헤더 생성 (col {URGENT_NEW_COL})")

        updated = 0
        newly_arrived = []  # 이번 실행에서 처음 채워진 행만 메일 알림 대상
        for r, to_num, pn, desc, requester in to_write:
            new_date = min(receipt_map[(to_num, pn)])  # 신고일자 개념이 없으므로 가장 이른 날짜 사용(기존 동작 유지)
            cell = ws_urgent_w.cell(r, URGENT_NEW_COL)
            # 2026-07-13: 실적파일과 동일한 이유로 이미 값이 있으면 덮어쓰지 않음.
            if cell.value is not None:
                continue
            # 실적파일과 동일하게, 리포트(메일) 도착 시각의 시:분을 붙여서 기록
            # (실제 입고 시각 그 자체는 아니고 확인 시점의 근사치).
            if report_time is not None:
                cell.value = datetime.combine(new_date, report_time.time())
                cell.number_format = "yyyy-mm-dd hh:mm"
            else:
                cell.value = new_date
                cell.number_format = "yyyy-mm-dd"
            updated += 1
            newly_arrived.append({
                "pn": pn, "desc": desc, "requester": requester,
                "to_num": to_num, "arrival_date": cell.value,
            })

        if updated > 0:
            backup_file(IR_FILE_PATH, IR_BACKUP_DIR)
            wb_write.save(IR_FILE_PATH)
            log(f"IR통합파일(Urgent Item) 업데이트: {updated}건")
            try:
                send_urgent_arrival_draft(newly_arrived)
            except Exception as e:
                log(f"[경고] 입고 알림 메일 초안 작성 실패: {e}")
        else:
            log("IR통합파일: 변경 없음")
        return updated
    finally:
        wb_write.close()


def send_urgent_arrival_draft(items: list) -> None:
    """Urgent Item이 OTBI로 실제 입고 확인되면 메일 초안(임시보관함)만 작성한다.
    urgent_item_freezer.py의 알림 메일과 별개 트리거(K열 확정이 아니라 OTBI
    실데이터 매칭 시점)이며, 자동 발송(Send)이 아니라 초안 저장(Save)만 한다
    — 검증 전이라 사람이 확인 후 직접 보내도록 함(2026-07-07 요청)."""
    if not items:
        return
    import win32com.client

    today_str = datetime.now().strftime("%Y-%m-%d")
    rows_html = "".join(
        f'<tr>'
        f'<td style="padding:6px 12px;border:1px solid #ddd;">{it["pn"]}</td>'
        f'<td style="padding:6px 12px;border:1px solid #ddd;">{it["desc"]}</td>'
        f'<td style="padding:6px 12px;border:1px solid #ddd;text-align:center;">{it["requester"]}</td>'
        f'<td style="padding:6px 12px;border:1px solid #ddd;text-align:center;">{it["to_num"]}</td>'
        f'<td style="padding:6px 12px;border:1px solid #ddd;text-align:center;">{_fmt_dt(it["arrival_date"])}</td>'
        f'</tr>'
        for it in items
    )
    body_html = f"""
<html><body style="font-family:맑은 고딕,Arial,sans-serif;font-size:13px;color:#333;">
<p>안녕하세요,</p>
<p>요청하신 품목이 용마에 실제 입고된 것이 확인되었습니다.<br>업무에 참고 부탁드립니다.<br>감사합니다.</p>
<p>채윤길 드림</p>

<table style="border-collapse:collapse;margin-top:8px;">
  <thead>
    <tr style="background:#f0f0f0;">
      <th style="padding:7px 12px;border:1px solid #ddd;text-align:left;">Part Number</th>
      <th style="padding:7px 12px;border:1px solid #ddd;text-align:left;">품명</th>
      <th style="padding:7px 12px;border:1px solid #ddd;">요청자</th>
      <th style="padding:7px 12px;border:1px solid #ddd;">TO번호</th>
      <th style="padding:7px 12px;border:1px solid #ddd;">실제입고일시</th>
    </tr>
  </thead>
  <tbody>
    {rows_html}
  </tbody>
</table>

</body></html>
"""

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)  # olMailItem
    mail.To = URGENT_MAIL_TO
    mail.CC = URGENT_MAIL_CC
    mail.Subject = f"[Urgent part] {today_str} 용마 실제 입고 확인"
    mail.HTMLBody = body_html
    mail.Save()  # 초안(임시보관함)만 저장 — 자동 발송 안 함
    log(f"입고 알림 메일 초안 저장: {len(items)}건 → To:{URGENT_MAIL_TO} / CC:{URGENT_MAIL_CC}")


# ==============================================================
# main
# ==============================================================
def main():
    log("===== otbi_receipt_updater 시작 =====")

    try:
        download_latest_otbi_mail()
    except Exception as e:
        log(f"[에러] 메일 다운로드 실패: {e}")

    report_path = pick_latest_report_file()
    if report_path is None:
        log("처리할 OTBI 리포트 파일이 없음 (아직 메일이 안 왔거나 폴더가 빔). 종료.")
        return

    log(f"사용할 리포트 파일: {os.path.basename(report_path)}")

    report_time = extract_report_time(report_path)
    log(f"리포트 도착/저장 시각: {report_time.strftime('%Y-%m-%d %H:%M')}")

    try:
        receipt_map = build_receipt_map(report_path)
        log(f"Receipt 매핑 (TO+자재) 조합 건수: {len(receipt_map)}")
    except Exception as e:
        log(f"[에러] 리포트 파싱 실패: {e}")
        return

    try:
        update_perf_file(receipt_map, report_time)
    except Exception as e:
        log(f"[에러] 실적파일 업데이트 실패: {e}")

    try:
        update_ir_file(receipt_map, report_time)
    except Exception as e:
        log(f"[에러] IR통합파일 업데이트 실패: {e}")

    log("===== otbi_receipt_updater 종료 =====\n")


if __name__ == "__main__":
    main()
