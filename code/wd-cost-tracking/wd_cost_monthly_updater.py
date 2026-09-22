# -*- coding: utf-8 -*-
"""
W&D Cost_Korea_{year}.xlsx (Summary 시트) 월별 벤더 비용 자동 기입.

매월 마지막 영업일 하루 전(D-1 영업일) 오후 4시에 한 번 실행되도록 스케줄러에
등록한다. Task Scheduler는 매일 16:00에 이 스크립트를 트리거하지만, 스크립트
내부에서 "오늘이 이번 달의 D-1 영업일인가"를 판단해 그 날짜가 아니면 즉시
종료한다(그룹 스크립트들의 날짜 가드 패턴과 동일).

데이터 소스: Outlook 받은편지함 > Finance 폴더의
  "[External] Action Required: Approval of Invoice <code> from <VENDOR> (<amount> KRW)"
  (발신자: ekkw.fa.sender@workflow.email.us-ashburn-1.ocs.oraclecloud.com, Oracle Fusion)
메일이 "수신된 달" = 해당 비용의 "사용달"(2026-07-23 사용자 확정 규칙).

대상 벤더(행)만 채운다 — 그 외(관세/부가세, FedEx)는 별도 프로세스/수기 검토 영역:
  YONGMA LOGIS            -> 용마비용
  INCHEON LOGIS           -> 인천로지스틱스
  DHL KOREA / DHL global forwarding Korea -> DHL (주 단위 여러 건 합산, 중복 제거)
  SEOUL LOGIS             -> 서울퀵
  JMEDI LOGIS             -> 제이메디로직스
  WECANDO                 -> 위캔두
  DAEHAN ENVIRON.         -> 대한환경개발
  EZPUB                   -> 한국환경공단(Others)  (2026-07-23 매칭 확인, 신규 벤더명 등장 시 로그로 확인 필요)

파일이 Excel에서 열려 있으면 저장이 막히므로, 실패 시 경고만 남기고 상태를
"완료"로 기록하지 않는다 -> 다음날 실행에서 캐치업 재시도.
"""

import os
import re
import json
import shutil
import calendar
from datetime import date, datetime
from collections import defaultdict

import openpyxl


# ── 경로 ──────────────────────────────────────────────────────────
def _script_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.getcwd()

SCRIPT_DIR = _script_dir()
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)  # "...\10. 수입"
OPERATION_DIR = os.path.dirname(ROOT_DIR)  # "...\Syneron-Candela Korea - Operation"
WD_DIR     = os.path.join(OPERATION_DIR, "기타")

RUN_LOG    = os.path.join(SCRIPT_DIR, "run_log.txt")
STATE_FILE = os.path.join(SCRIPT_DIR, "wd_cost_updater_state.json")

SENDER_ADDRESS = "ekkw.fa.sender@workflow.email.us-ashburn-1.ocs.oraclecloud.com"
FINANCE_FOLDER_NAME = "Finance"
MAILBOX = "yoongil.chae@candelamedical.com"
INBOX_NAME = "받은 편지함"

# 벤더명(subject의 "from <VENDOR>" 부분, 대문자 비교) -> W&D Summary 시트 행 번호
# FEDEX KOREA: 2026-07-23부터 rebalance/Zimmer 필터링 없이 전체 청구액을 사용하기로
# 확정(row7 라벨도 "Transportation for rebalance/Zimmer" -> "Transportation for Zimmer").
VENDOR_ROW_MAP = {
    "YONGMA LOGIS": 4,
    "INCHEON LOGIS": 5,
    "DHL KOREA": 6,
    "DHL GLOBAL FORWARDING KOREA": 6,
    "FEDEX KOREA": 7,
    "SEOUL LOGIS": 8,
    "JMEDI LOGIS": 9,
    "WECANDO": 10,
    "DAEHAN ENVIRON.": 11,
    "EZPUB": 12,
}

MONTH_COL = {m: chr(ord("C") + m - 1) for m in range(1, 13)}  # 1->C ... 12->N

# ── 한국 공휴일 (dhl_forwarder.py 와 동일 목록 유지) ────────────────
KR_HOLIDAYS = {
    "2026-01-01",
    "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-03-01", "2026-03-02",
    "2026-05-05",
    "2026-05-24", "2026-05-25",
    "2026-06-03",
    "2026-06-06",
    "2026-07-17",
    "2026-08-15", "2026-08-17",
    "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-28",
    "2026-10-03", "2026-10-05",
    "2026-10-09",
    "2026-12-25",
    "2027-01-01",
    "2027-02-05", "2027-02-06", "2027-02-07", "2027-02-08",
    "2027-03-01",
    "2027-05-05",
    "2027-05-13",
    "2027-06-06",
    "2027-07-17",
    "2027-08-15", "2027-08-16",
    "2027-09-14", "2027-09-15", "2027-09-16",
    "2027-10-03", "2027-10-04",
    "2027-10-09", "2027-10-11",
    "2027-12-25", "2027-12-27",
    "2028-01-01",
    "2028-01-25", "2028-01-26", "2028-01-27",
    "2028-03-01",
    "2028-04-12",
    "2028-05-02",
    "2028-05-05",
    "2028-06-06",
    "2028-07-17",
    "2028-08-15",
    "2028-10-02", "2028-10-03", "2028-10-04", "2028-10-05",
    "2028-10-09",
    "2028-12-25",
}


def log(msg):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [WD_Cost_Updater] {msg}"
    print(line, flush=True)
    try:
        with open(RUN_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def is_working_day(d):
    return d.weekday() < 5 and d.strftime("%Y-%m-%d") not in KR_HOLIDAYS


def last_working_day_minus1_of_month(year, month):
    """해당 월의 마지막 영업일에서 1영업일 전(=D-1 영업일) 날짜."""
    if month == 12:
        last_cal_day = date(year, 12, 31)
    else:
        last_cal_day = date(year, month + 1, 1) - __import__("datetime").timedelta(days=1)
    cur = last_cal_day
    working_days_found = []
    while len(working_days_found) < 2:
        if is_working_day(cur):
            working_days_found.append(cur)
        cur -= __import__("datetime").timedelta(days=1)
    # working_days_found[0] = 마지막 영업일, [1] = 그 전 영업일(D-1)
    return working_days_found[1]


# ── 상태 파일 ────────────────────────────────────────────────────
def load_state():
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"last_run_month": None, "history": []}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"[경고] 상태 파일 저장 실패: {e}")


# ── Outlook: Finance 폴더에서 Approval of Invoice 메일 수집 ────────
def fetch_invoice_mails(target_year, target_month):
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    root = ns.Folders[MAILBOX]
    inbox = root.Folders[INBOX_NAME]
    fin = inbox.Folders[FINANCE_FOLDER_NAME]

    items = fin.Items
    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:
        pass

    pat = re.compile(r"Approval of Invoice\s+(.+?)\s+from\s+(.+?)\s+\(([\d,]+)\s*KRW\)")

    rows = []
    for item in items:
        try:
            if item.Class != 43:
                continue
        except Exception:
            continue
        subject = getattr(item, "Subject", "") or ""
        if "Approval of Invoice" not in subject:
            continue
        try:
            sender = item.SenderEmailAddress or ""
        except Exception:
            sender = ""
        if sender.lower() != SENDER_ADDRESS.lower():
            continue

        recv = getattr(item, "ReceivedTime", None)
        if recv is None:
            continue
        try:
            ry, rm = recv.year, recv.month
        except Exception:
            continue
        # 지난달 말 그대로 두고, 훑는 범위를 살짝 넓혀 월 경계 근처 메일도 놓치지 않게(발견만, 합산은 월로 필터)
        if not (ry == target_year and rm == target_month):
            continue

        m = pat.search(subject)
        if not m:
            continue
        code, vendor, amt_s = m.group(1).strip(), m.group(2).strip(), m.group(3)
        rows.append({
            "received": recv.strftime("%Y-%m-%d %H:%M:%S"),
            "vendor": vendor,
            "amount": int(amt_s.replace(",", "")),
            "code": code,
        })
    return rows


def dedupe_and_sum_by_row(mails):
    """벤더 매핑 + 중복(같은 인보이스가 다른 이름으로 재수신) 제거 + 행별 합산."""
    seen = {}
    for m in mails:
        vendor_key = m["vendor"].upper()
        row = VENDOR_ROW_MAP.get(vendor_key)
        if row is None:
            continue
        date_match = re.search(r"\d{8}", m["code"])
        dedupe_key = (row, date_match.group(0) if date_match else m["code"], m["amount"])
        if dedupe_key not in seen:
            seen[dedupe_key] = m

    totals = defaultdict(int)
    detail = defaultdict(list)
    for (row, _, amount), m in seen.items():
        totals[row] += amount
        detail[row].append(m)
    return totals, detail


# ── 엑셀 갱신 (OneDrive 락 대응: 복사 → 편집 → 복사 되돌리기) ───────
def update_workbook(year, month, totals, detail):
    xlsx_path = os.path.join(WD_DIR, f"W&D Cost_Korea_{year}.xlsx")
    if not os.path.exists(xlsx_path):
        log(f"[오류] 파일 없음: {xlsx_path}")
        return False

    tmp_dir = os.path.join(SCRIPT_DIR, "_wd_cost_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_copy = os.path.join(tmp_dir, f"WD_{year}_work.xlsx")
    backup_path = os.path.join(
        WD_DIR, f"W&D Cost_Korea_{year}_backup_{datetime.now().strftime('%Y%m%d')}.xlsx"
    )

    try:
        shutil.copy2(xlsx_path, tmp_copy)
    except PermissionError:
        log("[대기] 원본 파일을 읽을 수 없습니다(엑셀에서 열려 있을 수 있음). 다음 실행에서 재시도합니다.")
        return False
    except Exception as e:
        log(f"[오류] 원본 복사 실패: {e}")
        return False

    if not os.path.exists(backup_path):
        try:
            shutil.copy2(xlsx_path, backup_path)
            log(f"[백업] {os.path.basename(backup_path)} 생성")
        except Exception as e:
            log(f"[경고] 백업 생성 실패(계속 진행): {e}")

    col = MONTH_COL[month]
    changed = []
    try:
        wb = openpyxl.load_workbook(tmp_copy)
        ws = wb["Summary"]
        for row, amount in totals.items():
            coord = f"{col}{row}"
            before = ws[coord].value
            if before == amount:
                continue
            ws[coord] = amount
            changed.append((coord, before, amount, [d["vendor"] for d in detail[row]]))
        wb.save(tmp_copy)
    except Exception as e:
        log(f"[오류] 엑셀 편집 실패: {e}")
        return False

    if not changed:
        log(f"[확인] {year}-{month:02d}: 계산값이 기존 시트와 이미 동일 — 변경 없음.")
        return True

    try:
        shutil.copy2(tmp_copy, xlsx_path)
    except PermissionError:
        log("[대기] 원본 파일이 열려 있어 저장하지 못했습니다. 다음 실행에서 재시도합니다.")
        return False
    except Exception as e:
        log(f"[오류] 원본 덮어쓰기 실패: {e}")
        return False

    for coord, before, after, vendors in changed:
        log(f"[반영] {coord}: {before!r} -> {after:,} ({'/'.join(vendors)})")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--test-month", help="YYYY-MM (가드/상태 무시하고 해당 월로 조회만 테스트)")
    parser.add_argument("--dry", action="store_true", help="엑셀에 실제로 쓰지 않고 계산만 출력")
    args = parser.parse_args()

    if args.test_month:
        ty, tm = map(int, args.test_month.split("-"))
        log(f"[테스트] {ty}-{tm:02d} 조회만 수행 (가드/상태 무시)")
        mails = fetch_invoice_mails(ty, tm)
        totals, detail = dedupe_and_sum_by_row(mails)
        for row, amount in sorted(totals.items()):
            vendors = [d["vendor"] for d in detail[row]]
            log(f"  row{row} = {amount:,}  <- {vendors}")
        if not args.dry and totals:
            update_workbook(ty, tm, totals, detail)
        return

    today = date.today()
    guard_day = last_working_day_minus1_of_month(today.year, today.month)

    state = load_state()
    this_month_key = f"{today.year}-{today.month:02d}"

    if state.get("last_run_month") == this_month_key:
        log(f"[스킵] 이번 달({this_month_key})은 이미 처리 완료.")
        return

    if today < guard_day:
        log(f"[대기] 오늘({today})은 이번 달 D-1 영업일({guard_day}) 이전 — 대기.")
        return

    log(f"[실행] 오늘({today}) >= 이번 달 D-1 영업일({guard_day}) — {this_month_key} 비용 집계 시작.")

    try:
        mails = fetch_invoice_mails(today.year, today.month)
    except ImportError:
        log("[오류] pywin32가 필요합니다: pip install pywin32")
        return
    except Exception as e:
        log(f"[오류] Outlook 조회 실패: {e}")
        return

    totals, detail = dedupe_and_sum_by_row(mails)
    if not totals:
        log(f"[알림] {this_month_key}: 매칭되는 벤더 인보이스 메일이 없습니다.")

    ok = update_workbook(today.year, today.month, totals, detail)
    if ok:
        state["last_run_month"] = this_month_key
        state.setdefault("history", []).append({
            "month": this_month_key,
            "run_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "totals": {str(k): v for k, v in totals.items()},
        })
        state["history"] = state["history"][-24:]
        save_state(state)
        log(f"[완료] {this_month_key} 처리 완료.")
    else:
        log(f"[미완료] {this_month_key} — 다음 실행에서 재시도 예정(상태 미기록).")


if __name__ == "__main__":
    main()
