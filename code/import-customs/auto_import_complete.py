import os
import re
import time
import shutil
import tempfile
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, date

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

# ============================================================
# Intransit → 수입신고실적(20260211) 신규 행 append (+ 옵션B: 기존행 빈칸 backfill)
#  - 기존 로직 유지
#  - 추가: Intransit의 "From Serial Number" → 수입신고실적 "From Serial Number"
#         Intransit의 "Lot Number"        → 수입신고실적 "SN/Lot"
#  - 옵션B: 신규 append가 0개여도, 기존행의 (SN/Lot, From Serial Number) 빈칸은 채움(덮어쓰기 X)
#  - 옵션B 보강: Delivery/SO가 비어있는 타겟행은 (ShipDate+ItemCode)로 "유일 후보"일 때만 채움
#               (후보 2개 이상이면 스킵 + 로그)
#
# [중요 개선]
#  - Delivery Number / SO Number 를 숫자/문자 섞여도 동일하게 인식
#    예) 9866516 == 9866516.0 == "9866516"
#  - 같은 Intransit 파일 내 중복 후보도 한 번만 append
# ============================================================

# ==============================
# ✅ 경로/시트 설정
# ==============================
INTRANSIT_DIR = r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입\Intransit Details Report"
TARGET_FILE   = r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입\수입신고실적(20260211)자동화.xlsx"
BACKUP_DIR    = r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입\백업"
SHEET_NAME    = "수입신고실적(20260211)"

# ==============================
# ✅ I/O 안전장치 설정
# ==============================
IO_RETRIES      = 5        # 파일 잠금(OneDrive/Excel) 시 재시도 횟수
IO_RETRY_WAIT   = 3.0      # 재시도 간 대기(초), 매 회 1.5배씩 증가
BACKUP_KEEP     = 100      # 백업 폴더에 보관할 최신 백업 개수(초과분 삭제). 0이면 보관(삭제 안 함)

# Intransit 파일에서 헤더가 들어있는 "행 번호" (현재 파일 포맷: 12행이 헤더)
# ⚠ 스냅샷마다 상단 Parameters 블록 줄 수가 달라 헤더 행 위치가 바뀔 수 있어서,
#   read_intransit() 안에서는 이 값을 "기본값/폴백"으로만 쓰고 실제로는 자동 탐지한다.
INTRANSIT_HEADER_ROW = 12
INTRANSIT_HEADER_SCAN_ROWS = 40  # 헤더 행 자동 탐지 시 이 범위(최대 행) 안에서 찾는다

# ==============================
# 유틸
# ==============================
def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

# ==============================
# I/O 안전장치
# ==============================
def is_valid_xlsx(path: str) -> bool:
    """파일이 '열 수 있는' 정상 xlsx인지 검사.
    - zip 구조가 온전한지(중앙디렉터리 존재) + xlsx 핵심 엔트리 존재 여부 확인.
    - 이번 사고(반쪽만 써진 파일)를 로드 전에 걸러내는 1차 방어선.
    """
    try:
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return False
        if not zipfile.is_zipfile(path):   # EOCD(중앙디렉터리) 없으면 False → 잘린 파일 탐지
            return False
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "[Content_Types].xml" not in names:
                return False
            # 워크북 본체가 있어야 진짜 스프레드시트
            if not any(n.startswith("xl/workbook") for n in names):
                return False
            bad = z.testzip()   # CRC 검사: 내부 압축 데이터 손상 탐지
            if bad is not None:
                return False
        return True
    except Exception:
        return False

def with_retry(fn, what: str):
    """OneDrive 동기화/Excel 열림 등으로 인한 일시적 잠금(PermissionError 등)을 재시도."""
    wait = IO_RETRY_WAIT
    last_err = None
    for attempt in range(1, IO_RETRIES + 1):
        try:
            return fn()
        except (PermissionError, OSError) as e:
            last_err = e
            if attempt < IO_RETRIES:
                log(f"[RETRY {attempt}/{IO_RETRIES}] {what} 실패({type(e).__name__}) → {wait:.0f}초 후 재시도")
                time.sleep(wait)
                wait *= 1.5
            else:
                log(f"[FAIL] {what} {IO_RETRIES}회 모두 실패")
    raise last_err

def safe_save_workbook(wb, target: str):
    """원자적 저장: 같은 폴더의 임시파일에 저장 → 무결성 검증 → os.replace 로 원자 교체.
    저장이 도중에 죽어도 원본(target)은 절대 손상되지 않는다.
    """
    folder = os.path.dirname(target) or "."
    os.makedirs(folder, exist_ok=True)

    fd, tmp = tempfile.mkstemp(prefix=".tmp_import_", suffix=".xlsx", dir=folder)
    os.close(fd)
    try:
        with_retry(lambda: wb.save(tmp), f"임시파일 저장({os.path.basename(tmp)})")

        # 방금 쓴 파일이 진짜 정상인지 검증 (이번 사고 재발 차단의 핵심)
        if not is_valid_xlsx(tmp):
            raise IOError("임시 저장 파일 무결성 검증 실패 — 저장 중단 (원본 보존됨)")

        # 원자적 교체 (동일 볼륨에서 os.replace 는 원자적)
        with_retry(lambda: os.replace(tmp, target), f"원본 교체({os.path.basename(target)})")
        log(f"저장 완료(원자적): {target}")
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception:
                pass

def safe_load_workbook(path: str, **kwargs):
    """로드 전에 무결성 검사 + 잠금 재시도."""
    if not is_valid_xlsx(path):
        raise zipfile.BadZipFile(f"손상되었거나 비정상 xlsx: {path}")
    return with_retry(lambda: openpyxl.load_workbook(path, **kwargs),
                      f"워크북 로드({os.path.basename(path)})")

def prune_backups():
    """백업 폴더에서 최신 BACKUP_KEEP 개만 남기고 정리. 정상 파일만 대상."""
    if not BACKUP_KEEP or BACKUP_KEEP <= 0:
        return
    try:
        files = []
        for fn in os.listdir(BACKUP_DIR):
            if fn.startswith("backup_") and fn.lower().endswith(".xlsx"):
                full = os.path.join(BACKUP_DIR, fn)
                try:
                    files.append((os.path.getmtime(full), full))
                except Exception:
                    continue
        files.sort(key=lambda x: x[0], reverse=True)  # 최신 우선
        for _, full in files[BACKUP_KEEP:]:
            try:
                os.remove(full)
            except Exception:
                pass
    except Exception as e:
        log(f"[WARN] 백업 정리 실패(무시): {e}")

def backup_target():
    """정상 파일일 때만 백업하고, 백업본 자체도 검증한다.
    ※ 손상된 원본을 백업해서 정상 백업 로테이션을 오염시키는 사고를 방지.
    반환: 백업 경로(str) 또는 None
    """
    os.makedirs(BACKUP_DIR, exist_ok=True)

    if not is_valid_xlsx(TARGET_FILE):
        log(f"[ABORT] 원본이 손상되어 백업하지 않음: {TARGET_FILE}")
        return None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"backup_{ts}.xlsx")

    with_retry(lambda: shutil.copy2(TARGET_FILE, backup_path), "원본 백업 복사")

    if not is_valid_xlsx(backup_path):
        # 복사가 깨졌으면 그 백업은 폐기
        try:
            os.remove(backup_path)
        except Exception:
            pass
        raise IOError(f"백업본 무결성 검증 실패: {backup_path}")

    log(f"백업 완료(검증됨): {backup_path}")
    prune_backups()
    return backup_path

def find_latest_valid_backup():
    """백업 폴더에서 가장 최신의 '정상' 백업 경로를 찾는다(복구 안내용)."""
    try:
        cands = []
        for fn in os.listdir(BACKUP_DIR):
            if fn.startswith("backup_") and fn.lower().endswith(".xlsx"):
                full = os.path.join(BACKUP_DIR, fn)
                try:
                    cands.append((os.path.getmtime(full), full))
                except Exception:
                    continue
        cands.sort(key=lambda x: x[0], reverse=True)
        for _, full in cands:
            if is_valid_xlsx(full):
                return full
    except Exception:
        pass
    return None

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

def set_date_cell(cell, d):
    """Write a python date into a cell with a consistent Excel date format."""
    cell.value = d
    cell.number_format = "yyyy-mm-dd"

def norm_str(v):
    return "" if v is None else str(v).strip()

def norm_hdr(s):
    return re.sub(r"\s+", "", str(s or "")).lower()

def norm_id(v):
    """
    Delivery Number / SO Number 같은 식별자 정규화
    - 9866516
    - 9866516.0
    - '9866516'
    - '9866516.0'
    -> 모두 '9866516' 로 통일 (비교/키 생성용 문자열)
    """
    if v is None:
        return ""

    # 이미 숫자인 경우
    if isinstance(v, int):
        return str(v)

    if isinstance(v, float):
        # 9866516.0 -> 9866516
        if v.is_integer():
            return str(int(v))
        # 혹시 소수점이 실제로 의미 있으면 최대한 보존
        s = f"{v:.15g}".strip()
        return s

    s = str(v).strip()
    if s == "":
        return ""

    # 쉼표 제거
    s = s.replace(",", "")

    # 문자열이 "12345.0" 형태면 정수 문자열화
    try:
        f = float(s)
        if f.is_integer():
            return str(int(f))
        return f"{f:.15g}"
    except:
        return s


def norm_id_numeric(v):
    """
    Delivery Number / SO Number / Line Number 를 엑셀 셀에 숫자(int)로 저장하기 위한 변환.
    - 순수 정수로 변환 가능하면 int 반환
    - 변환 불가(문자 포함 등)이면 문자열 반환
    - 빈 값이면 "" 반환
    """
    s = norm_id(v)
    if s == "":
        return ""
    try:
        return int(s)
    except ValueError:
        return s

def make_row_key(ship_d, item_code, delivery_no, so_no):
    """
    기존: 중복 판단용 키 (Backfill용으로 유지)
    """
    return (
        ship_d,
        norm_str(item_code).upper(),
        norm_id(delivery_no),
        norm_id(so_no),
    )

def make_unique_key(ship_d, item_code, delivery_no, so_no, sn_lot, from_serial, line_no=""):
    """
    신규: 신규 행 Append 시 시리얼 넘버 + Line Number까지 포함하여 완벽한 고유값으로 판단
    """
    return (
        ship_d,
        norm_str(item_code).upper(),
        norm_id(delivery_no),
        norm_id(so_no),
        norm_str(sn_lot),
        norm_str(from_serial),
        norm_id(line_no),  # 같은 Delivery 내 Line Number가 다른 행을 구분
    )

def find_header_row(ws, keyword="본사선적일자", max_scan_rows=40):
    kw = norm_hdr(keyword)
    for r in range(1, min(max_scan_rows, ws.max_row) + 1):
        for c in range(1, ws.max_column + 1):
            v = ws.cell(row=r, column=c).value
            if norm_hdr(v) == kw:
                return r
    return 1

def build_col_map(ws, header_row):
    m = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=header_row, column=c).value
        k = norm_hdr(v)
        if k:
            m[k] = c
    return m

def get_col(ws, col_map, *candidates):
    for name in candidates:
        k = norm_hdr(name)
        if k in col_map:
            return col_map[k]
    return None

def get_latest_intransit_file():
    if not os.path.isdir(INTRANSIT_DIR):
        return None
    candidates = []
    for fn in os.listdir(INTRANSIT_DIR):
        if fn.lower().endswith(".xlsx") and "intransit" in fn.lower():
            full = os.path.join(INTRANSIT_DIR, fn)
            try:
                candidates.append((os.path.getmtime(full), full))
            except:
                continue
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]

# 최근 N일 이내 스냅샷만 누적 처리 (0이면 전체). 휴가 등 공백을 메우려면 충분히 크게.
INTRANSIT_RECENT_DAYS = 30

def get_intransit_files(recent_days=INTRANSIT_RECENT_DAYS):
    """저장된 Intransit 스냅샷을 '날짜 오름차순(과거→최신)'으로 모두 반환.
    파일명의 _YYYYMMDD 를 우선 날짜키로 쓰고, 없으면 mtime 으로 대체.
    매일 1개씩 쌓인 스냅샷을 전부 replay 하기 위함 (사라진 Delivery 누락 방지).
    """
    if not os.path.isdir(INTRANSIT_DIR):
        return []

    cutoff = None
    if recent_days and recent_days > 0:
        cutoff = date.today() - timedelta(days=recent_days)

    cands = []
    for fn in os.listdir(INTRANSIT_DIR):
        if not (fn.lower().endswith(".xlsx") and "intransit" in fn.lower()):
            continue
        full = os.path.join(INTRANSIT_DIR, fn)

        fdate = None
        m = re.search(r"(\d{4})(\d{2})(\d{2})", fn)
        if m:
            try:
                fdate = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                fdate = None
        if fdate is None:
            try:
                fdate = datetime.fromtimestamp(os.path.getmtime(full)).date()
            except:
                continue

        if cutoff and fdate < cutoff:
            continue
        cands.append((fdate, full))

    cands.sort(key=lambda x: x[0])  # 과거 → 최신
    return [c[1] for c in cands]

def get_max_ship_date(ws: Worksheet):
    """수입신고실적의 본사선적일자(컬럼 B=2) 최댓값(date)
    ※ 컬럼 A(1)에 Ship From 추가로 본사선적일자가 B열(2)로 이동
    """
    max_d = None
    for r in range(2, ws.max_row + 1):
        d = norm_date(ws.cell(r, 2).value)  # B열 (본사선적일자)
        if d is None:
            continue
        if max_d is None or d > max_d:
            max_d = d
    return max_d

def build_existing_keys_target(ws: Worksheet) -> tuple:
    """
    수입신고실적 시트에 이미 존재하는 행들의 고유키 집합 (두 가지 반환)

    - full_counts : make_unique_key → 이미 존재하는 행의 "개수" (Counter)
                    ※ 2026-08-20: set → Counter 로 변경.
                      같은 키가 여러 행일 수 있기 때문(아래 read_intransit 주석 참고).
    - serial_keys : From Serial Number가 있으면 (ship, item, delivery, so, from_serial)
                    만으로 구성한 보조 키 집합.
                    Line Number가 None으로 저장된 기존 행과
                    Line Number=1 인 Intransit 신규 행이 달라 보이는 문제를 방지.
                    (시리얼은 개체당 유일하므로 개수 개념이 필요 없어 set 유지)
    """
    full_counts = Counter()
    serial_keys = set()  # from_serial 기반 보조 키

    for r in range(2, ws.max_row + 1):
        ship = norm_date(ws.cell(r, 2).value)            # B열(2)  본사선적일자 (A=Ship From으로 이동)
        item = norm_str(ws.cell(r, 9).value)             # I열(9)  자재코드
        sn_lot = norm_str(ws.cell(r, 19).value)          # S열(19) SN/Lot
        from_serial = norm_str(ws.cell(r, 20).value)     # T열(20) From Serial Number
        delivery = ws.cell(r, 21).value                  # U열(21) Delivery Number
        so = ws.cell(r, 22).value                        # V열(22) SO Number
        line_no = ws.cell(r, 24).value                   # X열(24) Line Number

        if ship is None and norm_str(item) == "" and norm_id(delivery) == "" and norm_id(so) == "":
            continue

        full_counts[make_unique_key(ship, item, delivery, so, sn_lot, from_serial, norm_id(line_no))] += 1

        # From Serial Number가 있으면 보조 키에도 등록 (Line Number 무관하게 중복 방지)
        if from_serial:
            serial_keys.add((ship, norm_str(item).upper(), norm_id(delivery), norm_id(so), from_serial))

    return full_counts, serial_keys

def find_intransit_header_row(ws, required_cols, max_scan_rows=INTRANSIT_HEADER_SCAN_ROWS):
    """Intransit 스냅샷의 실제 헤더 행을 자동으로 찾는다.
    상단 'Parameters' 블록 줄 수가 스냅샷마다 달라서 헤더가 항상 12행에 있다고
    가정하면 안전하지 않다 (실제로 이 때문에 배치가 통째로 죽은 사고가 있었음).
    'From Org' + 'To Org' 가 같은 행에 모두 존재하는 첫 행을 헤더 행으로 본다.
    못 찾으면 None을 반환하고, 호출부에서 INTRANSIT_HEADER_ROW로 폴백한다.
    """
    for r in range(1, min(max_scan_rows, ws.max_row) + 1):
        row_vals = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if v:
                row_vals[str(v).strip()] = c
        if "From Org" in row_vals and "To Org" in row_vals:
            return r
    return None

def read_intransit(file_path, max_ship_date, existing_counts, existing_serial_keys: set):
    """
    Intransit에서 row들을 읽는다.
      - new_rows: ship_date >= max_ship_date 인 행 중, 타겟에 아직 없는 만큼만 append 대상
      - all_rows: 날짜 상관없이 모두(옵션B backfill 대상)

    ────────────────────────────────────────────────────────────────
    [2026-08-20 수정] 같은 키가 여러 행인 경우를 '개수'로 판단하도록 변경.

    (배경) make_unique_key 는 (선적일, 자재코드, Delivery, TO, Lot, Serial, TO Line)
    이고 수량이 들어있지 않다. Lot/Serial 이 없는 부품(렌즈 등)이 같은 TO Line 에서
    수량만 다르게 두 줄로 쪼개져 오면(예: 1 EA + 4 EA) 키가 완전히 동일해진다.
    종전 로직은 `if key in seen_new_keys: continue` 로 뒤쪽 줄을 조용히 버렸고,
    실제로 신고번호 4482026721281M / 8050-00-9004 4 EA(143,364원) 가 유실됐다.

    (왜 수량을 키에 넣지 않는가) Qty In Transit 은 부분입고로 줄어든다(4→2).
    수량을 키에 넣으면 같은 행이 '새 행'으로 보여 중복 append 가 발생한다.

    (해결) 키의 '몇 번째 등장인지'로 판단한다.
      스냅샷에서 그 키의 N번째 행이면, 타겟에 이미 N개 이상 있을 때만 스킵.
      → 스냅샷 3줄 / 타겟 1줄이면 부족분 2줄만 추가된다.
      → 유실(종전 문제)도, 중복(수량을 키에 넣었을 때의 문제)도 함께 막힌다.
    ────────────────────────────────────────────────────────────────

    추가 안전장치:
      - 손상된 스냅샷은 예외 없이 ([], []) 반환하여 전체 런 중단을 막음
    """
    if not is_valid_xlsx(file_path):
        log(f"[SKIP] 손상되었거나 비정상 Intransit 스냅샷 → 건너뜀: {os.path.basename(file_path)}")
        return [], []
    try:
        wb = with_retry(lambda: openpyxl.load_workbook(file_path, data_only=True),
                        f"Intransit 로드({os.path.basename(file_path)})")
    except Exception as e:
        log(f"[SKIP] Intransit 로드 실패({type(e).__name__}) → 건너뜀: {os.path.basename(file_path)}")
        return [], []
    ws = wb.active

    required = [
        "From Org", "To Org",
        "Ship Date",
        "Item Code", "Item Description",
        "Qty In Transit",
        "Delivery",
        "Transfer order Number",
        "Transfer order Line Number",
        "From Serial Number",
        "Lot Number",
    ]

    header_row = find_intransit_header_row(ws, required) or INTRANSIT_HEADER_ROW

    headers = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(header_row, c).value
        if v:
            headers[str(v).strip()] = c

    missing = [x for x in required if x not in headers]
    if missing:
        raise ValueError(
            f"Intransit 파일에 필요한 컬럼이 없습니다(필수/추가 포함): {missing}\n"
            f"(헤더 행으로 추정한 행 번호: {header_row})\n"
            f"현재 컬럼: {list(headers.keys())}"
        )

    new_rows = []
    all_rows = []
    occ = defaultdict(int)       # 이 스냅샷에서 같은 키가 몇 번째로 등장했는지
    multi = {}                   # 같은 키가 2행 이상인 케이스 로그용: key -> (스냅샷개수, 타겟개수)
    max_d = max_ship_date

    for r in range(header_row + 1, ws.max_row + 1):
        ship_val = ws.cell(r, headers["Ship Date"]).value
        ship_d = norm_date(ship_val)
        if ship_d is None:
            continue

        from_org = norm_str(ws.cell(r, headers["From Org"]).value)
        to_org   = norm_str(ws.cell(r, headers["To Org"]).value)

        # 조건: From ORG는 KRP면 안되고, To ORG는 KRP이어야 함
        if from_org == "KRP":
            continue
        if to_org != "KRP":
            continue

        # 2026-09-15 사용자 요청: 같은 수입면장에 같이 신고돼야 하는 delivery를
        # 찾는 가장 정확한 기준은 본사선적일자가 아니라 WayBill/Tracking Number
        # (같은 물리적 화물이면 같은 번호)다. Intransit 리포트에 이미 있는 값이니
        # 신고 전(통관 전)부터 실적 파일의 'B/L번호' 컬럼에 미리 심어둔다.
        # 필수 컬럼으로 강제하진 않는다 - 이 값이 없어도 나머지 행 처리는
        # 그대로 진행돼야 하고(대체 로직: 본사선적일자 기준 대조), 옛 포맷
        # 스냅샷엔 이 컬럼이 없을 수도 있음. 나중에 통관이 끝나면
        # pdf_auto_updater.py가 실제 신고필증의 B/L(AWB)번호로 그대로
        # 덮어쓴다(overwrite_cols/fill_cols에 이미 포함, 신고번호 유무로만
        # 채움 여부를 판단하지 B/L번호 기존값 유무는 안 봄 - 확인 완료).
        waybill_col = headers.get("WayBill/Tracking Number")

        row_dict = {
            "Ship From": from_org,
            "본사선적일자": ship_d,
            "자재코드": norm_str(ws.cell(r, headers["Item Code"]).value),
            "자재명": norm_str(ws.cell(r, headers["Item Description"]).value),
            "수량": ws.cell(r, headers["Qty In Transit"]).value,
            "Delivery Number": norm_id(ws.cell(r, headers["Delivery"]).value),
            "SO Number": norm_id(ws.cell(r, headers["Transfer order Number"]).value),
            "Line Number": norm_id(ws.cell(r, headers["Transfer order Line Number"]).value),
            "From Serial Number": norm_str(ws.cell(r, headers["From Serial Number"]).value),
            "SN/Lot": norm_str(ws.cell(r, headers["Lot Number"]).value),
            "B/L번호": norm_str(ws.cell(r, waybill_col).value) if waybill_col else "",
        }

        if row_dict["자재코드"] == "" and row_dict["자재명"] == "":
            continue

        all_rows.append(row_dict)

        # 날짜 컷: max_ship_date보다 이전만 스킵 (같은 날짜는 후보 포함)
        if max_d is not None and ship_d < max_d:
            continue

        key = make_unique_key(
            row_dict["본사선적일자"],
            row_dict["자재코드"],
            row_dict["Delivery Number"],
            row_dict["SO Number"],
            row_dict["SN/Lot"],
            row_dict["From Serial Number"],
            row_dict["Line Number"],
        )

        # 이 스냅샷에서 이 키의 몇 번째 행인가 (1-based)
        occ[key] += 1
        nth = occ[key]
        have = existing_counts.get(key, 0) if existing_counts is not None else 0
        if nth > 1:
            multi[key] = (nth, have)

        # 타겟에 이미 nth개 이상 있으면 스킵.
        #  - 평소(키당 1행)에는 종전의 `key in existing_keys` 와 동일하게 동작한다.
        #  - 쪼개진 행(키당 2행 이상)은 부족한 개수만큼만 통과한다.
        if existing_counts is not None and have >= nth:
            continue

        # 보조 키 체크: From Serial Number가 있는 경우 Line Number 차이 무관하게 중복 방지
        # (기존 행에 Line Number=None으로 저장된 건과 Intransit의 Line Number=1 건이
        #  full key에서 다르게 보여도 같은 건으로 처리)
        if existing_serial_keys is not None and row_dict["From Serial Number"]:
            serial_key = (
                row_dict["본사선적일자"],
                norm_str(row_dict["자재코드"]).upper(),
                norm_id(row_dict["Delivery Number"]),
                norm_id(row_dict["SO Number"]),
                row_dict["From Serial Number"],
            )
            if serial_key in existing_serial_keys:
                continue

        new_rows.append(row_dict)

    # 같은 키가 2행 이상인 케이스는 드물지만(2026년 한국 수입건 1건) 조용히 넘어가면
    # 이번처럼 한참 뒤에야 발견된다 → 발생 자체를 로그로 남긴다.
    for key, (n, have) in sorted(multi.items(), key=lambda x: str(x[0])):
        log(f"[MULTI] 동일키 {n}행 (타겟 보유 {have}행) → {max(0, n - have)}행 추가 대상 | "
            f"자재={key[1]} Delivery={key[2]} TO={key[3]} Line={key[6]}")

    return new_rows, all_rows

# ==============================
# Append (신규행만)
# ==============================
def append_rows(ws: Worksheet, rows):
    last_row = ws.max_row

    for r in rows:
        last_row += 1

        # 컬럼 위치 (A열에 Ship From 추가 후 전체 +1)
        # A  Ship From          (1)  ← NEW
        # B  본사선적일자        (2)
        # E  B/L번호            (5)  ← NEW(2026-09-15, WayBill/Tracking Number 선반영)
        # I  자재코드            (9)
        # J  자재명             (10)
        # K  수량               (11)
        # S  SN/Lot             (19)
        # T  From Serial Number (20)
        # U  Delivery Number    (21)
        # V  SO Number          (22)
        # X  Line Number        (24)  ← 중복 방지용
        ws.cell(last_row, 1).value  = r.get("Ship From", "")
        set_date_cell(ws.cell(last_row, 2), r["본사선적일자"])
        if r.get("B/L번호"):
            ws.cell(last_row, 5).value = r["B/L번호"]
        ws.cell(last_row, 9).value  = r["자재코드"]
        ws.cell(last_row, 10).value = r["자재명"]
        ws.cell(last_row, 11).value = r["수량"]

        ws.cell(last_row, 19).value = r.get("SN/Lot", "")
        ws.cell(last_row, 20).value = r.get("From Serial Number", "")

        ws.cell(last_row, 21).value = norm_id_numeric(r["Delivery Number"])
        ws.cell(last_row, 22).value = norm_id_numeric(r["SO Number"])
        ws.cell(last_row, 24).value = norm_id_numeric(r["Line Number"])  # X열: 중복 방지용

    return len(rows)

# ==============================
# 옵션B: 기존행 backfill (덮어쓰기 X)
# ==============================
def backfill_existing(ws: Worksheet, all_rows):
    """
    기존 행 중 비어있는 칸만 채움(덮어쓰기 X)

    1) 정확 매칭 키:
       (본사선적일자, 자재코드, Delivery Number, SO Number)

    2) 보강(안전): 타겟행 Delivery/SO가 비어있으면
       (본사선적일자, 자재코드) 로 후보가 유일할 때만 채움
       - 후보 2개 이상이면 스킵 + 로그
    """
    header_row = find_header_row(ws, keyword="본사선적일자")
    col_map = build_col_map(ws, header_row)

    col_ship = get_col(ws, col_map, "본사선적일자")
    col_item = get_col(ws, col_map, "자재코드", "Item Code")
    col_delivery = get_col(ws, col_map, "Delivery Number", "Delivery #", "Delivery", "Delivery No", "Delivery Nu")
    col_so = get_col(ws, col_map, "SO Number", "SO#", "Transfer Order number", "Transfer order Number", "Transfer Order Number", "SO Nu")

    col_snlot = get_col(ws, col_map, "SN/Lot", "SN/LOT", "SN Lot")
    col_from_serial = get_col(ws, col_map, "From Serial Number", "From Serial", "From Serial No")
    col_ship_from = get_col(ws, col_map, "Ship From")
    col_bl = get_col(ws, col_map, "B/L번호", "B/L", "BL번호")

    if col_ship is None or col_item is None:
        log("[WARN] Option B(backfill) 스킵: 타겟 시트에 '본사선적일자' 또는 '자재코드' 컬럼이 없음")
        return 0

    full_lookup = {}
    loose_lookup = {}

    for it in all_rows:
        ship = norm_date(it.get("본사선적일자"))
        item = norm_str(it.get("자재코드"))
        delivery = norm_id(it.get("Delivery Number"))
        so = norm_id(it.get("SO Number"))

        full_key = make_row_key(ship, item, delivery, so)
        if full_key not in full_lookup:
            full_lookup[full_key] = it
        else:
            cur = full_lookup[full_key]
            if (not cur.get("From Serial Number") and it.get("From Serial Number")) or (not cur.get("SN/Lot") and it.get("SN/Lot")):
                full_lookup[full_key] = it

        loose_key = (ship, norm_str(item).upper())
        loose_lookup.setdefault(loose_key, []).append(it)

    updated = 0
    ambiguous = 0

    for r in range(header_row + 1, ws.max_row + 1):
        ship = norm_date(ws.cell(r, col_ship).value)
        item = norm_str(ws.cell(r, col_item).value)

        delivery = norm_id(ws.cell(r, col_delivery).value) if col_delivery else ""
        so = norm_id(ws.cell(r, col_so).value) if col_so else ""

        if ship is None and item == "":
            continue

        src = None

        # 1) full match 우선
        if col_delivery is not None and col_so is not None:
            src = full_lookup.get(make_row_key(ship, item, delivery, so))

        # 2) fallback: delivery/so가 비어있을 때만 loose match(유일 후보)
        if src is None and (delivery == "" or so == ""):
            cand = loose_lookup.get((ship, norm_str(item).upper()), [])
            if len(cand) == 1:
                src = cand[0]
            elif len(cand) > 1:
                ambiguous += 1
                log(f"[AMBIG] backfill 후보 2개 이상 → 스킵 (row={r}, ship={ship}, item={item}, 후보={len(cand)})")

        if not src:
            continue

        # Ship From: 빈칸만 채움
        if col_ship_from:
            cur = ws.cell(r, col_ship_from).value
            if (cur is None) or (str(cur).strip() == ""):
                val = src.get("Ship From")
                if val not in (None, ""):
                    ws.cell(r, col_ship_from).value = val
                    updated += 1

        # SN/Lot: 빈칸만 채움
        if col_snlot:
            cur = ws.cell(r, col_snlot).value
            if (cur is None) or (str(cur).strip() == ""):
                val = src.get("SN/Lot")
                if val not in (None, ""):
                    ws.cell(r, col_snlot).value = val
                    updated += 1

        # From Serial Number: 빈칸만 채움
        if col_from_serial:
            cur = ws.cell(r, col_from_serial).value
            if (cur is None) or (str(cur).strip() == ""):
                val = src.get("From Serial Number")
                if val not in (None, ""):
                    ws.cell(r, col_from_serial).value = val
                    updated += 1

        # B/L번호(=WayBill/Tracking Number): 빈칸만 채움(2026-09-15 추가)
        if col_bl:
            cur = ws.cell(r, col_bl).value
            if (cur is None) or (str(cur).strip() == ""):
                val = src.get("B/L번호")
                if val not in (None, ""):
                    ws.cell(r, col_bl).value = val
                    updated += 1

    if ambiguous:
        log(f"[INFO] backfill ambiguous 스킵 건수: {ambiguous}")

    return updated

def main():
    log("Intransit → 수입신고실적 append 시작")

    # ── 0) 원본 무결성 선검사: 깨졌으면 아무것도 건드리지 말고 즉시 중단 ──
    if not is_valid_xlsx(TARGET_FILE):
        log(f"[ABORT] 대상 파일이 손상되었거나 비정상입니다: {TARGET_FILE}")
        latest = find_latest_valid_backup()
        if latest:
            log(f"[복구안내] 가장 최신 정상 백업: {latest}")
            log(f"[복구안내] 위 파일을 '{os.path.basename(TARGET_FILE)}' 로 복사해 덮어쓴 뒤 다시 실행하세요.")
        else:
            log("[복구안내] 백업 폴더에 정상 백업이 없습니다. OneDrive 웹 → 우클릭 → '버전 기록'에서 이전 버전 복원하세요.")
        return

    backup_target()

    wb_t = safe_load_workbook(TARGET_FILE)
    if SHEET_NAME not in wb_t.sheetnames:
        raise ValueError(f"대상 시트 '{SHEET_NAME}'를 찾을 수 없습니다. 시트들: {wb_t.sheetnames}")
    ws_t = wb_t[SHEET_NAME]

    max_ship_date = get_max_ship_date(ws_t)
    log(f"수입신고실적 본사선적일자 최댓값: {max_ship_date}")

    intransit_files = get_intransit_files()
    if not intransit_files:
        log("Intransit 파일 없음")
        return

    log(f"읽을 스냅샷: {len(intransit_files)}개 (과거→최신 순으로 누적)")

    existing_counts, existing_serial_keys = build_existing_keys_target(ws_t)

    # 여러 스냅샷을 순회하며 누적.
    #  - 한 Delivery 가 여러 날짜 스냅샷에 등장해도 필요한 개수만큼만 append
    #    (running_counts 를 스냅샷마다 갱신해서 다음 스냅샷이 이미 넣은 분을 인식)
    #  - 어느 한 스냅샷에라도 잡혔으면 행이 생기므로, 휴가 중 떴다 사라진 건도 복구됨
    new_rows = []
    all_rows = []
    running_counts = Counter(existing_counts)   # 타겟 보유분 + 이번 런에서 넣기로 한 분
    seen_all_keys = set()

    for fp in intransit_files:
        log(f"  읽는 중: {os.path.basename(fp)}")
        try:
            nr, ar = read_intransit(fp, max_ship_date, running_counts, existing_serial_keys)
        except ValueError as e:
            # 한 스냅샷의 컬럼 포맷이 달라도(구버전 리포트 등) 전체 배치가 죽지 않도록
            # 해당 파일만 건너뛰고 계속 진행한다.
            log(f"[SKIP] 컬럼 포맷이 맞지 않는 Intransit 스냅샷 → 건너뜀: {os.path.basename(fp)}")
            log(f"        상세: {e}")
            continue

        # read_intransit 이 running_counts 대비 '부족분'만 돌려주므로, 받은 만큼 카운트를
        # 올려주면 다음 스냅샷에서 같은 행이 다시 잡히지 않는다.
        for row in nr:
            k = make_unique_key(
                row["본사선적일자"], row["자재코드"], row["Delivery Number"],
                row["SO Number"], row["SN/Lot"], row["From Serial Number"], row["Line Number"],
            )
            running_counts[k] += 1
            new_rows.append(row)

        # backfill 후보(all_rows)도 스냅샷 간 중복 제거 (ambiguous 오판 방지)
        for row in ar:
            k = make_unique_key(
                row["본사선적일자"], row["자재코드"], row["Delivery Number"],
                row["SO Number"], row["SN/Lot"], row["From Serial Number"], row["Line Number"],
            )
            if k in seen_all_keys:
                continue
            seen_all_keys.add(k)
            all_rows.append(row)

    # 신규 append만 날짜 기준 정렬
    new_rows.sort(key=lambda x: (
        x.get("본사선적일자") or date(9999, 12, 31),
        norm_str(x.get("자재코드", "")),
        norm_id(x.get("Delivery Number", "")),
        norm_id(x.get("SO Number", "")),
    ))

    inserted = 0
    if new_rows:
        inserted = append_rows(ws_t, new_rows)

    backfilled = backfill_existing(ws_t, all_rows)

    if inserted == 0 and backfilled == 0:
        log("추가/갱신할 데이터 없음")
        return

    safe_save_workbook(wb_t, TARGET_FILE)
    try:
        wb_t.close()
    except Exception:
        pass
    log(f"신규 추가 행 수: {inserted}")
    log(f"기존행 backfill(빈칸 채움) 건수: {backfilled}")
    log("완료")

if __name__ == "__main__":
    import sys
    try:
        main()
    except Exception as e:
        # 어떤 단계에서 실패하든 원본은 atomic-save 덕분에 보존됨.
        log(f"[ERROR] 실행 실패: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)   # Task Scheduler 가 실패를 인지하도록 비정상 종료코드 반환