import os
import shutil
import time
from datetime import datetime, timedelta, date

import re

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

# ============================================================
# APAC Candela Intransit Details Report → "IR 신청목록 & Instransit 현황.xlsx" 의 [Intransit] 시트에 append
#
# ✅ 기존 데이터(원래 있던 행) 순서는 절대 건드리지 않음
# ✅ 새로 append 되는 행들만 Ship Date 오름차순으로 정렬해서 "맨 아래"에 추가
#
# 매핑 규칙 (요청사항)
# - From Org                     <- From Org
# - Ship Date                    <- Ship Date
# - Delivery                     <- Delivery
# - WayBill/Tracking Number      <- WayBill/Tracking Number (비어있으면 Tracking Notes)
# - Transfer order Number        <- Transfer order Number
# - Item Code                    <- Item Code
# - Item Desc (또는 Item Description) <- Item Description
# - Qty In Transit               <- Qty In Transit
# - 본사 선적일자                <- Ship Date (동일 값)
# - 용마 입고 예정 일자          <- Ship Date + 10 days
# ============================================================

# ==============================
# ✅ 경로 설정 (사용자 PC 환경에 맞게 수정)
# ==============================
INTRANSIT_DIR = r"C:\\Users\\yoongil.chae\\OneDrive - Candela\\Syneron-Candela Korea - Operation\\10. 수입\\Intransit Details Report"
# 가장 최신 Intransit 리포트(xlsx)를 자동 선택
# (파일명에 "Intransit" 또는 "Intransit Details Report"가 포함된 xlsx를 대상으로 함)
INTRANSIT_FILE = None
TARGET_FILE = r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입\IR 신청목록 & Instransit(20260303~).xlsx"
TARGET_SHEET   = "Intransit"

BACKUP_DIR = r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입\Intransit 내부공유\백업"

# ==============================
# 유틸
# ==============================
def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def backup_target():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"backup_{ts}.xlsx")
    shutil.copy(TARGET_FILE, backup_path)
    log(f"백업 완료: {backup_path}")

def get_latest_intransit_file(intransit_dir: str):
    if not os.path.isdir(intransit_dir):
        return None
    candidates = []
    for fn in os.listdir(intransit_dir):
        if not fn.lower().endswith(".xlsx"):
            continue
        low = fn.lower()
        if ("intransit" not in low) and ("intransit details report" not in low):
            continue
        full = os.path.join(intransit_dir, fn)
        try:
            candidates.append((os.path.getmtime(full), full))
        except:
            continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

def norm_str(v):
    """
    문자열 정규화 (중복 방지용 핵심)
    - 9864163.0 같은 float / '9864163.0' 문자열을 '9864163'으로 통일
    - 공백 제거
    """
    if v is None:
        return ""
    # float인데 정수처럼 보이면 int로
    try:
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
    except Exception:
        pass
    s = str(v).strip()
    # "123.0" 같은 문자열 정규화
    if s.endswith(".0"):
        s2 = s[:-2]
        if s2.isdigit():
            return s2
    return s

def norm_date(v):
    """엑셀/오픈파이엑셀의 날짜 값을 date로 정규화"""
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
        except:
            pass
    return None

def set_date_cell(cell, d: date):
    """Write a python date into a cell with a consistent Excel date format."""
    cell.value = d
    cell.number_format = "yyyy-mm-dd"

# ==============================
# Intransit 리포트 헤더 유틸 (헤더 행 자동 탐색 + 헤더명 정규화)
# ==============================
def norm_hdr(s):
    # 공백/줄바꿈/탭 등 제거 + 소문자 (헤더 비교용)
    return re.sub(r"\s+", "", str(s or "")).lower()

def find_header_row(ws: Worksheet, keyword: str = "Ship Date", max_scan_rows: int = 60) -> int:
    # keyword 셀을 찾은 행을 헤더 행으로 간주
    kw = norm_hdr(keyword)
    max_r = min(max_scan_rows, ws.max_row or 1)
    for r in range(1, max_r + 1):
        for c in range(1, ws.max_column + 1):
            if norm_hdr(ws.cell(r, c).value) == kw:
                return r
    return 1

def build_col_map_norm(ws: Worksheet, header_row: int) -> dict:
    m = {}
    for c in range(1, ws.max_column + 1):
        k = norm_hdr(ws.cell(header_row, c).value)
        if k:
            m[k] = c
    return m

def get_col_norm(col_map: dict, *candidates: str):
    for name in candidates:
        k = norm_hdr(name)
        if k in col_map:
            return col_map[k]
    return None

def build_header_map(ws: Worksheet, header_row: int = 1):
    m = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(header_row, c).value
        if v is None:
            continue
        key = str(v).strip()
        if key:
            m[key] = c
    return m

def get_col(col_map, name: str):
    return col_map.get(name)

def get_max_existing_shipdate(ws: Worksheet, col_shipdate: int, start_row: int = 2):
    """타겟 시트에서 '본사 선적일자' 컬럼의 최댓값(date)"""
    max_d = None
    for r in range(start_row, ws.max_row + 1):
        d = norm_date(ws.cell(r, col_shipdate).value)
        if d is None:
            continue
        if max_d is None or d > max_d:
            max_d = d
    return max_d

def build_existing_keys(ws: Worksheet, col_delivery: int, col_item: int, col_to_num: int, col_hq_ship: int, start_row: int = 2) -> set:
    """타겟 시트에 이미 존재하는 행들의 고유키 집합을 만든다.
    키 = (delivery, item_code, transfer_order_number, hq_ship_date)
    ※ delivery/to/item은 norm_str로 정규화하여 타입 차이(9864163 vs 9864163.0)를 제거
    """
    keys = set()
    for r in range(start_row, ws.max_row + 1):
        delivery = norm_str(ws.cell(r, col_delivery).value)
        item     = norm_str(ws.cell(r, col_item).value).upper()
        to_num   = norm_str(ws.cell(r, col_to_num).value)
        d        = norm_date(ws.cell(r, col_hq_ship).value)
        if delivery == "" and item == "" and to_num == "" and d is None:
            continue
        keys.add((delivery, item, to_num, d))
    return keys

# ==============================
# 타겟(Intransit 시트) 헤더 유틸 (헤더 행 자동 탐색)
# ==============================
def find_target_header_row(ws: Worksheet, max_scan_rows: int = 80) -> int:
    r = find_header_row(ws, keyword="본사 선적일자", max_scan_rows=max_scan_rows)
    if r == 1:
        r = find_header_row(ws, keyword="Ship Date", max_scan_rows=max_scan_rows)
    return r

# ==============================
# ✅ [추가] 타겟 시트에서 "첫 빈 데이터 행" 찾기 (서식만 깔린 빈 행을 max_row로 잡는 문제 해결)
# ==============================
def find_first_empty_row(ws: Worksheet, header_row: int, key_cols: list[int]) -> int:
    """
    핵심 컬럼(key_cols)이 전부 빈 행을 '첫 빈 데이터 행'으로 판단한다.
    - 서식만 있는 행(값은 None/빈문자열)도 "빈 데이터 행"으로 간주하여
      그 지점부터 append되게 한다. (서식 유지)
    """
    start = header_row + 1
    for r in range(start, ws.max_row + 1):
        if all(ws.cell(r, c).value in (None, "") for c in key_cols):
            return r
    return ws.max_row + 1

# ==============================
# Intransit report 읽기
# ==============================
def read_intransit_report(file_path: str, max_ship_date: date | None, existing_keys: set | None = None):
    wb = openpyxl.load_workbook(file_path, data_only=True)
    ws = wb.active

    # ✅ 헤더가 1행이 아닐 수 있으므로 자동 탐색 (예: 위에 타이틀/설명행 존재)
    header_row = find_header_row(ws, keyword="Ship Date", max_scan_rows=60)
    col_map = build_col_map_norm(ws, header_row)

    # ✅ 헤더명은 공백/줄바꿈이 섞이는 경우가 많아서 후보를 여러 개 둠
    c_from_org = get_col_norm(col_map, "From Org", "From Organization", "From Org.")
    c_to_org   = get_col_norm(col_map, "To Org", "To Organization", "To Org.")
    c_ship     = get_col_norm(col_map, "Ship Date", "Shipment Date", "Shipped Date")
    c_delivery = get_col_norm(col_map, "Delivery", "Delivery Number", "Delivery No", "Delivery#")
    c_waybill  = get_col_norm(
        col_map,
        "WayBill/Tracking Number", "Waybill/Tracking Number",
        "WayBill / Tracking Number", "Waybill", "Tracking Number",
    )
    c_tracknts = get_col_norm(col_map, "Tracking Notes", "Tracking Note", "Notes", "Remark", "Remarks")
    c_to_num   = get_col_norm(
        col_map,
        "Transfer order Number", "Transfer Order Number",
        "Transfer Order", "TO Number", "Transfer order No",
    )
    c_item     = get_col_norm(col_map, "Item Code", "Item", "Item Number", "Item No")
    c_desc     = get_col_norm(col_map, "Item Description", "Item Desc", "Description")
    c_qty      = get_col_norm(col_map, "Qty In Transit", "Quantity In Transit", "Qty", "Quantity")

    missing = []
    for name, col in [
        ("From Org", c_from_org), ("To Org", c_to_org), ("Ship Date", c_ship),
        ("Delivery", c_delivery), ("WayBill/Tracking Number", c_waybill),
        ("Tracking Notes", c_tracknts), ("Transfer order Number", c_to_num),
        ("Item Code", c_item), ("Item Description", c_desc), ("Qty In Transit", c_qty),
    ]:
        if col is None:
            missing.append(name)

    if missing:
        raise ValueError(
            f"Intransit report에 필요한 컬럼이 없습니다: {missing}\n"
            f"(DEBUG) header_row={header_row}, 현재 컬럼(정규화): {list(col_map.keys())}"
        )

    rows = []
    for r in range(header_row + 1, ws.max_row + 1):
        from_org = norm_str(ws.cell(r, c_from_org).value)
        to_org   = norm_str(ws.cell(r, c_to_org).value)

        # - From Org가 KRP면 제외
        # - To Org는 KRP만
        if from_org == "KRP":
            continue
        if to_org != "KRP":
            continue

        ship_d = norm_date(ws.cell(r, c_ship).value)
        if ship_d is None:
            continue

        if max_ship_date is not None and ship_d < max_ship_date:
            # 이미 반영된 날짜(그 이전)는 스킵 (기존 데이터 순서 보호)
            continue

        # ✅ 날짜가 같더라도 이미 타겟에 있는 (Delivery+Item+TO+ShipDate) 조합은 스킵
        if existing_keys is not None:
            delivery_val = norm_str(ws.cell(r, c_delivery).value)
            item_val     = norm_str(ws.cell(r, c_item).value).upper()
            to_val       = norm_str(ws.cell(r, c_to_num).value)
            key = (delivery_val, item_val, to_val, ship_d)
            if key in existing_keys:
                continue

        waybill = norm_str(ws.cell(r, c_waybill).value)
        if waybill == "":
            waybill = norm_str(ws.cell(r, c_tracknts).value)

        row = {
            "From Org": from_org,
            "Ship Date": ship_d,
            "Delivery": norm_str(ws.cell(r, c_delivery).value),
            "WayBill/Tracking Number": waybill,
            "Transfer order Number": norm_str(ws.cell(r, c_to_num).value),
            "Item Code": norm_str(ws.cell(r, c_item).value),
            "Item Description": norm_str(ws.cell(r, c_desc).value),
            "Qty In Transit": ws.cell(r, c_qty).value,
        }
        rows.append(row)

    # ✅ 새로 append 될 것만 날짜 오름차순 정렬
    rows.sort(key=lambda x: (
        x.get("Ship Date") or date(9999, 12, 31),
        x.get("Item Code", ""),
        x.get("Delivery", ""),
        x.get("Transfer order Number", ""),
    ))
    return rows

# ==============================
# 타겟에 append
# ==============================
def append_to_target(ws: Worksheet, rows):
    header_row_t = find_target_header_row(ws, max_scan_rows=80)
    hdr_norm = build_col_map_norm(ws, header_row_t)
    # (주의) 기존 데이터 행 순서는 건드리지 않고, 맨 아래에만 append 합니다.

    # 타겟 컬럼 찾기(헤더 후보 다중)
    c_from_org = get_col_norm(hdr_norm, "From Org", "From")
    c_shipdate = get_col_norm(hdr_norm, "Ship Date", "Shipment Date")
    c_delivery = get_col_norm(hdr_norm, "Delivery", "Delivery Number", "Delivery No")
    c_waybill  = get_col_norm(hdr_norm, "WayBill/Tracking Number", "WayBill", "Tracking Number")
    c_to_num   = get_col_norm(hdr_norm, "Transfer order Number", "Transfer Order Number", "TO Number")
    c_item     = get_col_norm(hdr_norm, "Item Code", "Item")
    c_desc     = get_col_norm(hdr_norm, "Item Desc", "Item Description", "Description")
    c_qty      = get_col_norm(hdr_norm, "Qty In Transit", "Qty", "Quantity")

    c_hq_ship  = get_col_norm(hdr_norm, "본사 선적일자", "본사선적일자", "본사 선적\n일자")
    c_yongma   = get_col_norm(hdr_norm, "용마 입고\n예정 일자", "용마 입고 예정 일자")

    needed = {
        "From Org": c_from_org, "Ship Date": c_shipdate, "Delivery": c_delivery,
        "WayBill/Tracking Number": c_waybill, "Transfer order Number": c_to_num,
        "Item Code": c_item, "Item Desc/Description": c_desc, "Qty In Transit": c_qty,
        "본사 선적일자": c_hq_ship, "용마 입고 예정 일자": c_yongma
    }
    missing = [k for k, v in needed.items() if v is None]
    if missing:
        raise ValueError(f"타겟 시트에서 필요한 컬럼을 찾지 못했습니다: {missing}")

    # ✅ [변경] ws.max_row 대신 "첫 빈 데이터 행" 기준으로 append 시작점 결정
    first_empty = find_first_empty_row(
        ws,
        header_row_t,
        key_cols=[c_delivery, c_item, c_shipdate]
    )
    last_row = first_empty - 1

    inserted = 0

    for it in rows:
        last_row += 1

        # ✅ [추가] 바로 윗행 서식을 새 행 전체 컬럼에 복사 (Description 뒤 컬럼 서식까지 유지)
        for col in range(1, ws.max_column + 1):
            ws.cell(last_row, col)._style = ws.cell(last_row - 1, col)._style

        ws.cell(last_row, c_from_org).value = it["From Org"]
        set_date_cell(ws.cell(last_row, c_shipdate), it["Ship Date"])
        ws.cell(last_row, c_delivery).value = it["Delivery"]
        ws.cell(last_row, c_waybill).value = it["WayBill/Tracking Number"]
        ws.cell(last_row, c_to_num).value = it["Transfer order Number"]
        ws.cell(last_row, c_item).value = it["Item Code"]
        ws.cell(last_row, c_desc).value = it["Item Description"]
        ws.cell(last_row, c_qty).value = it["Qty In Transit"]

        # 요청사항: 본사 선적일자 = Ship Date
        set_date_cell(ws.cell(last_row, c_hq_ship), it["Ship Date"])

        # 요청사항: 용마 입고 예정 일자 = Ship Date + 10
        set_date_cell(ws.cell(last_row, c_yongma), it["Ship Date"] + timedelta(days=10))

        inserted += 1

    return inserted

def main():
    log("Intransit report → 타겟(Intransit) append 시작")
    backup_target()

    wb_t = openpyxl.load_workbook(TARGET_FILE)
    if TARGET_SHEET not in wb_t.sheetnames:
        raise ValueError(f"대상 시트 '{TARGET_SHEET}'를 찾을 수 없습니다. 시트들: {wb_t.sheetnames}")
    ws_t = wb_t[TARGET_SHEET]

    # max ship date는 타겟의 '본사 선적일자'로 판단 (헤더 행 자동 탐색)
    header_row_t = find_target_header_row(ws_t, max_scan_rows=80)
    hdr_norm_t = build_col_map_norm(ws_t, header_row_t)
    start_row_t = header_row_t + 1

    c_hq_ship = get_col_norm(hdr_norm_t, "본사 선적일자", "본사선적일자", "본사 선적\n일자")
    if c_hq_ship is None:
        raise ValueError("타겟 시트에서 '본사 선적일자' 컬럼을 찾지 못했습니다.")
    max_ship = get_max_existing_shipdate(ws_t, c_hq_ship, start_row=start_row_t)
    log(f"타겟 '본사 선적일자' 최댓값: {max_ship}")

    global INTRANSIT_FILE
    if INTRANSIT_FILE is None:
        INTRANSIT_FILE = get_latest_intransit_file(INTRANSIT_DIR)
    if not INTRANSIT_FILE:
        raise ValueError(f"Intransit 리포트 파일을 찾지 못했습니다. 폴더를 확인하세요: {INTRANSIT_DIR}")
    log(f"Intransit 리포트 선택: {os.path.basename(INTRANSIT_FILE)}")

    # ✅ 중복 방지용 기존 키 생성 (헤더 기준으로 컬럼 찾기)
    c_delivery_t = get_col_norm(hdr_norm_t, "Delivery", "Delivery Number", "Delivery No")
    c_item_t     = get_col_norm(hdr_norm_t, "Item Code", "Item")
    c_to_t       = get_col_norm(hdr_norm_t, "Transfer order Number", "Transfer Order Number", "TO Number")
    if c_delivery_t is None or c_item_t is None or c_to_t is None:
        raise ValueError("타겟 시트에서 중복 방지용 컬럼(Delivery/Item Code/Transfer order Number)을 찾지 못했습니다.")
    existing_keys = build_existing_keys(ws_t, c_delivery_t, c_item_t, c_to_t, c_hq_ship, start_row=start_row_t)

    rows = read_intransit_report(INTRANSIT_FILE, max_ship, existing_keys)
    if not rows:
        log("추가할 신규 데이터 없음")
        return

    inserted = append_to_target(ws_t, rows)

    wb_t.save(TARGET_FILE)
    log(f"신규 추가 행 수: {inserted}")
    log("완료")

if __name__ == "__main__":
    # 2026-09-08: 통합파일이 그 순간 열려있으면 PermissionError로 append 단계
    # 전체가 스킵되던 문제 재발 방지용 재시도. backup_target()이 main()의
    # 가장 첫 동작이라, 실패 시 아무 것도 반영되지 않은 상태이므로 통째로
    # 재시도해도 안전하다.
    MAX_RETRIES = 5
    RETRY_WAIT_SEC = 60
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            main()
            break
        except PermissionError:
            if attempt < MAX_RETRIES:
                log(f"파일이 열려 있어 접근 실패 ({attempt}/{MAX_RETRIES}). {RETRY_WAIT_SEC}초 후 재시도.")
                time.sleep(RETRY_WAIT_SEC)
            else:
                log("FAILED: 파일이 열려 있음(재시도 소진). 닫고 다시 실행하세요.")
                raise