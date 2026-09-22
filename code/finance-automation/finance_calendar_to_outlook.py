# -*- coding: utf-8 -*-
"""
finance_calendar_to_outlook.py  (OCR 버전)

재무팀 월간 'Finance Calendar' 메일은 달력이 '이미지'로 들어온다.
메일에서 달력 이미지를 추출 → OCR(easyocr)로 글자+좌표 인식 →
'지급요청' 셀의 날짜 헤더(예: 24-Jun)를 같은 열·바로 위에서 찾아 마감일을 확정한다.

등록 일정 (마감일 기준 영업일 역산):
  D-2 영업일 : 서울퀵·인천로지스틱스·용마 내역서/세금계산서 수취
  D-1 영업일 : PRPO 승인 완료
  D-day      : 당월 2차 지급요청 마감

특징
  - 마감일: (1) 명령행 인자가 있으면 그 날짜, (2) 캐시에 있으면 캐시,
            (3) 없으면 이미지 OCR로 추출 후 캐시에 저장.
  - OCR은 무겁다 → 메일 EntryID로 캐시하여 같은 메일은 OCR 1회만 (하루 5회 실행해도 월 1회).
  - 주말·한국 공휴일 제외 영업일 역산(holidays).
  - 동일 제목·동일 날짜 일정이 이미 있으면 건너뜀(idempotent).

의존성:  pip install pywin32 holidays easyocr paddleocr paddlepaddle
         OCR은 PaddleOCR(korean) 1순위, 실패 시 easyocr 폴백.
         (easyocr 최초 실행 시 모델 자동 다운로드 → 인터넷 1회 필요, 이후 오프라인)
"""

import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")  # easyocr/torch OpenMP 중복(libiomp5md) 충돌 회피

import re
import sys
import json
import calendar
import datetime as dt

import win32com.client
import holidays

# ───────────────────────── 설정 ─────────────────────────
SUBJECT_HINT    = "Finance Calendar"
SENDER_HINT     = "eunpyeongc"        # 빈 문자열이면 미사용
ACCOUNT_HINT    = "yoongil.chae@candelamedical.com"
INBOX_SUBFOLDER = "Finance"
SEARCH_DAYS     = 60

# 등록할 일정: (영업일 오프셋, 제목, 시각(시), 알림(분 전), 본문)
EVENTS = [
    (-2, "[재무] 서울퀵·인천로지스틱스·용마·제이메디로지스 내역서/세금계산서 수취 (D-2)", 9, 0,
        "서울퀵, 인천로지스틱스, 용마, 제이메디로지스로부터 내역서 및 세금계산서 수취."),
    (-1, "[재무] PRPO 승인 완료 (D-1)", 9, 0,
        "2차 지급요청 마감 전일까지 PRPO 승인 완료."),
    (0,  "[재무] 당월 2차 지급요청 마감 (by EOD / 승인완료 PRPO 한정)", 9, 0,
        "PRPO 승인 완료건에 한해 지급요청 메일 발송. 승인된 PRPO 첨부 필수."),
]

# ─── 담당자 cutoff 안내 메일 설정 ───
COMPANY        = "시너론켄델라코리아"
SENDER_NAME    = "채윤길"
SUBJECT_PREFIX = f"[{COMPANY}]"
SEND_MODE      = False   # False=초안 저장(Drafts에서 검토 후 수동 발송), True=실제 자동 발송
MAIL_OFFSET    = -2      # 메일에 안내할 cutoff = 2차 마감 기준 D-2(거래명세서 수취일)

# 각 업체에 개별 메일 발송. (이름, To, [CC...])
VENDORS = [
    {"name": "서울퀵",        "to": "hih2284@naver.com",          "cc": []},
    {"name": "제이메디로지스", "to": "heejeong.jeong@jmedilogis.com",
     "cc": ["bohyunk@candelamedical.com", "kates@candelamedical.com", "eunpyeongc@candelamedical.com"]},
    {"name": "인천로지스틱스", "to": "iclforwar@icbl.kr",
     "cc": ["eunpyeongc@candelamedical.com", "kates@candelamedical.com"]},
    {"name": "용마로지스",     "to": "y7221063@yongmalogis.co.kr", "cc": []},
]

KR_HOLIDAYS = holidays.SouthKorea(years=range(2025, 2030))
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}
WD = ["월", "화", "수", "목", "금", "토", "일"]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_PATH = os.path.join(SCRIPT_DIR, "_fin_cal_cache.json")
IMG_DIR    = os.path.join(SCRIPT_DIR, "_cal_tmp")
ANOMALY_LOG_PATH = os.path.join(SCRIPT_DIR, "_fin_cal_anomalies.log")

# OCR 결과 이상치 검증(안전장치) — vendor/헤더 인식이 약해 OCR이 그냥 감으로 찍은
# 값도 '성공'으로 캐시에 들어가는 문제(2026-08 1차 지급일 오인식 사고)를 막기 위해,
# 상식적인 폴백 추정치와 너무 차이나면 그 필드는 버리고 다운스트림(dhl_forwarder.py
# 등)이 자체 폴백 규칙을 쓰게 한다. None으로 남기면 자동으로 그렇게 동작한다.
FIRST_PAY_FALLBACK_DAY   = 10   # 1차 vendor 지급 폴백: 매월 10일 (dhl_forwarder.py와 동일 규칙)
FIRST_PAY_TOLERANCE_DAYS = 6    # OCR 1차 지급일이 폴백과 이 이상 차이나면 이상치로 판단
SECOND_NTH_LAST_WD       = 3    # 2차 마감 폴백: 월말에서 N번째 영업일
SECOND_TOLERANCE_DAYS    = 10   # 2차 폴백 자체가 부정확할 수 있어 더 느슨하게 허용

# Outlook 상수
OL_FOLDER_INBOX    = 6
OL_FOLDER_CALENDAR = 9
OL_APPOINTMENT     = 1
OL_MAIL_ITEM       = 0
OL_MAIL_CLASS      = 43
OL_BUSY_FREE       = 0

# OCR 패턴
# 월 3글자 표기 오독 보정: 'Aug'의 마지막 g가 easyocr에서 q/a로 자주 오독됨(Auq, Aua 등).
# 매칭된 토큰은 _norm_month()로 정규 월 번호로 환산한다.
_MONTH_ALT = r"jan|feb|mar|apr|may|jun|jul|au[a-z]|sep|oct|nov|dec"


def _norm_month(tok: str):
    """퍼지 매칭된 월 토큰(예: 'auq','aua')을 월 번호(1~12)로 환산."""
    t = tok.lower()
    if t.startswith("au"):
        return MONTHS["Aug"]
    return MONTHS.get(t[:3].title())


HEADER_RE = re.compile(
    r"(\d{1,2})\s*[-–—~]?\s*(" + _MONTH_ALT + r")", re.I)
# 날짜 헤더 오독 보정: 숫자 자리에 낀 글자(0→O/U/D/Q, 1→l/I/|)를 숫자로 복원한 뒤 매칭
HEADER_FUZZY_RE = re.compile(
    r"([0-9OoUuDQlI|]{1,2})[-–—~. ]?(" + _MONTH_ALT + r")", re.I)
_DAY_FIX = str.maketrans({"O": "0", "o": "0", "U": "0", "u": "0", "D": "0", "Q": "0",
                          "l": "1", "I": "1", "|": "1"})
# 타이틀("2026. Aug" 등)이 우연히 HEADER_RE에 걸려 가짜 날짜 헤더가 되는 것을 막기 위한 필터.
# 실제 날짜 헤더는 4자리 연도를 포함하지 않으므로, 연도 패턴이 보이면 헤더 후보에서 제외.
_YEAR_RE = re.compile(r"20\d{2}")
# 2차 지급요청 마감 셀 식별 앵커 — easyocr 오독(요→으, 마→가, 차→자, P→F, 청→점/정 등)에 견디게 퍼지.
#   지급요청: '지급' + (가운데 0~2글자 오독 허용) + '청/점/정'   → '지급으청','지급요점' 등 매칭
#   PRPO   : 'PR' + (가운데 1글자 오독) + 'O/0'                  → 'PRFO','PRPO' 매칭
KW_RE = re.compile(r"지\s*급\s*.{0,2}\s*[청점정]|P\s*R\s*.\s*[O0OQ]", re.I)
# 보조 앵커(클러스터 폴백): '2차'와 '마감'도 오독 허용
KW_2CHA_RE  = re.compile(r"2\s*[차자]")
KW_MAGAM_RE = re.compile(r"[마가]\s*감")
VENDOR_RE = re.compile(r"[vy]e[nr]d[o0]r", re.I)  # 'N차 vendor 지급' 셀 식별(vendor↔verdor/yendor 오독 흡수)
# 2026-09: '2차'의 차와 '마감'이 동시에 깨지는 달이 있어(2차+마감 클러스터 실패),
# 마감 셀에 항상 붙는 '(by EOD ...)' 표기 자체를 3차 앵커로 사용. EOD↔ECD 오독 허용.
EOD_RE = re.compile(r"by\s*E[O0CQ]D", re.I)

_READER = None  # easyocr 리더 캐시


# ───────────────────────── 영업일 ─────────────────────────
def add_business_days(base: dt.date, offset: int) -> dt.date:
    if offset == 0:
        return base
    step = 1 if offset > 0 else -1
    remaining, cur = abs(offset), base
    while remaining > 0:
        cur += dt.timedelta(days=step)
        if cur.weekday() < 5 and cur not in KR_HOLIDAYS:
            remaining -= 1
    return cur


# ───────────────────────── Outlook 메일 ─────────────────────────
def _outlook_dt(d: dt.datetime) -> str:
    return d.strftime("%m/%d/%Y %I:%M %p")


def get_finance_folder():
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    if ACCOUNT_HINT:
        for store in ns.Stores:
            try:
                if ACCOUNT_HINT.lower() in (store.DisplayName or "").lower():
                    return store.GetDefaultFolder(OL_FOLDER_INBOX).Folders[INBOX_SUBFOLDER]
            except Exception:
                continue
    return ns.GetDefaultFolder(OL_FOLDER_INBOX).Folders[INBOX_SUBFOLDER]


def get_calendar_folder():
    """메일을 읽는 스토어(ACCOUNT_HINT)와 '같은' 계정의 기본 캘린더를 반환.
    이렇게 하지 않으면 CreateItem/GetDefaultFolder가 Outlook '기본 계정'의
    캘린더에 일정을 넣어, 실제로 보는 candela 캘린더엔 안 뜰 수 있음."""
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    if ACCOUNT_HINT:
        for store in ns.Stores:
            try:
                if ACCOUNT_HINT.lower() in (store.DisplayName or "").lower():
                    return store.GetDefaultFolder(OL_FOLDER_CALENDAR)
            except Exception:
                continue
    return ns.GetDefaultFolder(OL_FOLDER_CALENDAR)


def _sender_smtp(msg) -> str:
    try:
        addr = msg.SenderEmailAddress or ""
        if "@" in addr:
            return addr
        exch = msg.Sender.GetExchangeUser()
        return (exch.PrimarySmtpAddress or addr) if exch else addr
    except Exception:
        return ""


def find_latest_calendar_mail():
    items = get_finance_folder().Items
    items.Sort("[ReceivedTime]", True)
    cutoff = dt.datetime.now() - dt.timedelta(days=SEARCH_DAYS)
    try:
        items = items.Restrict("[ReceivedTime] >= '" + _outlook_dt(cutoff) + "'")
        items.Sort("[ReceivedTime]", True)
    except Exception:
        pass
    for msg in items:
        try:
            if getattr(msg, "Class", None) != OL_MAIL_CLASS:
                continue
            if SUBJECT_HINT.lower() not in (msg.Subject or "").lower():
                continue
            if SENDER_HINT:
                s = _sender_smtp(msg).lower()
                if s and SENDER_HINT.lower() not in s:
                    continue
            return msg
        except Exception:
            continue
    return None


def parse_subject_ym(subject: str):
    """제목에서 (연, 월). 예: 'Finance Calendar Jun. 2026' → (2026, 6)."""
    s = subject or ""
    m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*(20\d{2})",
                  s, re.I)
    if m:
        return int(m.group(2)), MONTHS[m.group(1).title()]
    y = re.search(r"(20\d{2})", s)
    year = int(y.group(1)) if y else dt.date.today().year
    mo = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", s, re.I)
    month = MONTHS[mo.group(1).title()] if mo else dt.date.today().month
    return year, month


# ───────────────────────── 이미지 추출 ─────────────────────────
def extract_calendar_images(msg) -> list:
    """첨부 이미지를 저장하고 파일 크기 큰 순으로 경로 반환(달력이 가장 큼)."""
    os.makedirs(IMG_DIR, exist_ok=True)
    # 이전 임시 이미지 정리
    for f in os.listdir(IMG_DIR):
        try:
            os.remove(os.path.join(IMG_DIR, f))
        except Exception:
            pass
    exts = (".png", ".jpg", ".jpeg", ".gif", ".bmp")
    saved = []
    for att in msg.Attachments:
        try:
            fn = (att.FileName or "")
            if not fn.lower().endswith(exts):
                continue
            path = os.path.join(IMG_DIR, f"cal_{len(saved)}_{fn}")
            att.SaveAsFile(path)
            saved.append(path)
        except Exception:
            continue
    saved.sort(key=lambda p: os.path.getsize(p), reverse=True)
    return saved


# ───────────────────────── OCR ─────────────────────────
def _center(bbox):
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _cluster_1d(values, gap):
    """정렬된 좌표들을 gap 이상 벌어지면 새 그룹으로 나눠 클러스터링. 그룹별 평균 좌표 반환."""
    groups = []
    for v in sorted(set(values)):
        if not groups or v - groups[-1][-1] > gap:
            groups.append([v])
        else:
            groups[-1].append(v)
    return [sum(g) / len(g) for g in groups]


def _reconcile_grid_headers(headers, tol=2):
    """달력은 Mon~Fri 5열 그리드로 각 행이 연속된 날짜(같은 열 간격=1일 증가)이므로,
    한 행에서 인식된 헤더가 하나라도 있으면 그 열 기준으로 나머지 열의 날짜를 역산해
    (1) 통째로 깨져 인식 자체가 안 된 헤더를 채우고, (2) 자릿수 오독(예: 13→73, 6→5)을
    같은 행 내 다른 헤더와의 정합성으로 교정한다. 다른 달로 넘어가는 셀(달력 앞뒤 패딩)은
    월 정보가 다르면 건드리지 않고, 역산한 날짜가 그 달의 실제 일수를 넘으면 채우지 않는다."""
    if not headers:
        return headers
    col_centers = _cluster_1d([h[0] for h in headers], gap=40)
    row_centers = _cluster_1d([h[1] for h in headers], gap=40)
    if not col_centers or not row_centers:
        return headers

    def nearest(centers, v):
        return min(range(len(centers)), key=lambda i: abs(centers[i] - v))

    grid = {}
    for h in headers:
        r, c = nearest(row_centers, h[1]), nearest(col_centers, h[0])
        grid.setdefault(r, {})[c] = h

    def days_in(month):
        return calendar.monthrange(2024, ((month - 1) % 12) + 1)[1]  # 연도 불명 → 윤년 기준(2/29 허용)

    out = []
    for r, cols in grid.items():
        anchor_c = min(cols)
        _, _, aday, amonth = cols[anchor_c]
        base = aday - anchor_c
        for c, h in cols.items():
            cx, cy, oday, omonth = h
            if omonth != amonth:
                out.append(h)                      # 다른 달 헤더(패딩 칸)는 그대로 둠
                continue
            day_est = base + c
            if 1 <= day_est <= days_in(amonth) and (not (1 <= oday <= 31) or abs(oday - day_est) <= tol):
                out.append((cx, cy, day_est, amonth))   # 보정 또는 확인된 값으로 교체
            else:
                out.append(h)                      # 근거 부족(큰 불일치) → 원본 유지
        for c in range(len(col_centers)):
            if c in cols:
                continue
            day_est = base + c
            if 1 <= day_est <= days_in(amonth):
                out.append((col_centers[c], row_centers[r], day_est, amonth))  # 인식 자체 실패한 헤더 채움
    return out


def _build_headers(results):
    """날짜 헤더 목록 (cx,cy,day,month) 생성.
    easyocr가 '27'과 'Jul'을 별개 박스로 쪼갠 경우도 근접 병합해 헤더로 복원."""
    headers, day_boxes, mon_boxes = [], [], []
    for b, t, _c in results:
        cx, cy = _center(b)
        s = t.replace(" ", "")
        if _YEAR_RE.search(s):
            # "2026. Aug" 같은 타이틀 텍스트가 우연히 날짜 헤더로 오인되는 것을 방지.
            continue
        m = HEADER_RE.search(s)
        if m:
            mo = _norm_month(m.group(2))
            if mo:
                headers.append((cx, cy, int(m.group(1)), mo))
                continue
        mf = HEADER_FUZZY_RE.search(s)          # 오독 보정(1U-Jul→10-Jul, Auq→Aug 등)
        if mf:
            dtok = mf.group(1).translate(_DAY_FIX)
            mo = _norm_month(mf.group(2))
            if dtok.isdigit() and 1 <= int(dtok) <= 31 and mo:
                headers.append((cx, cy, int(dtok), mo))
                continue
        dm = re.fullmatch(r"(\d{1,2})[-–—~.]?", s)
        if dm and 1 <= int(dm.group(1)) <= 31:
            day_boxes.append((cx, cy, int(dm.group(1))))
        mm = re.fullmatch(r"[-–—~.]?(" + _MONTH_ALT + r")", s, re.I)
        if mm:
            mo = _norm_month(mm.group(1))
            if mo:
                mon_boxes.append((cx, cy, mo))
    for dx, dy, day in day_boxes:                 # 쪼개진 day 숫자에 근처 month 결합
        cand = [(abs(my - dy) + abs(mx - dx), mo)
                for mx, my, mo in mon_boxes
                if abs(my - dy) < 18 and -10 <= (mx - dx) < 90]
        if cand:
            cand.sort()
            headers.append((dx, dy, day, cand[0][1]))
    return _reconcile_grid_headers(headers)


def _is_header_text(t):
    s = t.replace(" ", "")
    return bool(HEADER_RE.search(s)
                or re.fullmatch(r"(\d{1,2})[-–—~.]?", s)
                or re.fullmatch(r"[-–—~.]?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
                                s, re.I))


def _deadline_cell_boxes(results):
    """2차 지급요청 마감 셀에 속하는 (cx,cy) 목록.
      (a) 박스 단위 퍼지 앵커(지급요청/PRPO)
      (b) 실패 시: 근접 박스를 셀 단위로 묶어 '2차'+'마감' 동시 포함 셀 탐색
          (줄바꿈으로 '2차'와 '마감'이 다른 박스로 갈려도 잡힘)"""
    boxes = [(_center(b)[0], _center(b)[1], t) for b, t, _c in results]
    hits = [(cx, cy) for cx, cy, t in boxes if KW_RE.search(t)]
    if hits:
        return hits
    # 클러스터 폴백: 헤더성 박스는 셀 내용이 아니므로 제외(기준 y가 헤더로 끌려가는 것 방지)
    content = [(cx, cy, t) for cx, cy, t in boxes if not _is_header_text(t)]
    used = [False] * len(content)
    for i, (cx, cy, t) in enumerate(content):
        if used[i]:
            continue
        group = [(cx, cy, t)]
        used[i] = True
        for j, (ox, oy, ot) in enumerate(content):   # 같은 셀 추정 근접 박스 묶기
            if not used[j] and abs(ox - cx) < 120 and abs(oy - cy) < 90:
                group.append((ox, oy, ot)); used[j] = True
        txt = "".join(g[2] for g in group)
        if KW_2CHA_RE.search(txt) and KW_MAGAM_RE.search(txt):
            return [(g[0], g[1]) for g in group]
    # 3차 폴백: '(by EOD' 표기가 살아있으면 그 박스가 마감 셀 안에 있다 (2026-09 추가)
    eod = [(cx, cy) for cx, cy, t in boxes if EOD_RE.search(t)]
    if eod:
        return eod
    return []


def _pick_deadline_day(results, month):
    """마감 셀의 '일(day)'과 헤더텍스트 반환. 열(column) 매칭을 최우선으로 견고화."""
    if not results:
        return None, None
    img_w = max(p[0] for b, _, _ in results for p in b)
    col_w = img_w / 5.0  # Mon~Fri 5열

    headers = _build_headers(results)
    kw = _deadline_cell_boxes(results)
    if os.environ.get("CAL_DEBUG"):
        print(f"    [DBG] headers={len(headers)}  kw_boxes={len(kw)}  "
              f"kw={[(round(x),round(y)) for x,y in kw][:6]}")
    if not kw or not headers:
        return None, None

    kx = sorted(p[0] for p in kw)[len(kw) // 2]   # 키워드 조각들의 중앙 x
    ky = min(p[1] for p in kw)                     # 셀 내용의 맨 위 y

    def result(h):
        name = [k for k, v in MONTHS.items() if v == h[3]][0]
        return h[2], f"{h[2]}-{name}"

    def in_col(h):
        return abs(h[0] - kx) < col_w * 0.6

    # 1) 같은달·같은열·위 → 바로 위
    c = [h for h in headers if h[3] == month and in_col(h) and h[1] < ky]
    if c:
        c.sort(key=lambda h: ky - h[1]); return result(c[0])
    # 2) 같은열·위 → 바로 위
    c = [h for h in headers if in_col(h) and h[1] < ky]
    if c:
        c.sort(key=lambda h: ky - h[1]); return result(c[0])
    # 3) 같은열에서 y가 가장 가까운 헤더(헤더가 키워드와 같은 박스/행에 섞인 경우 대비)
    c = [h for h in headers if in_col(h)]
    if c:
        c.sort(key=lambda h: (0 if h[3] == month else 1, abs(h[1] - ky)))
        return result(c[0])
    # 4) 최후: 위쪽 헤더 중 x 최근접
    c = [h for h in headers if h[1] < ky]
    if c:
        c.sort(key=lambda h: (abs(h[0] - kx), ky - h[1])); return result(c[0])
    return None, None


def _header_above(headers, cx, cy, col_w):
    """(cx,cy) 셀의 같은 열 바로 위 헤더 반환. 없으면 None."""
    cands = [h for h in headers if h[1] < cy and abs(h[0] - cx) < col_w * 0.6]
    if not cands:
        return None
    cands.sort(key=lambda h: cy - h[1])   # 바로 위
    return cands[0]


def _earliest_day(found, month):
    """[(day,month)...] 에서 같은 달 우선, 가장 이른 날 반환."""
    if not found:
        return None, None
    same = [f for f in found if f[1] == month]
    pool = same if same else found
    pool.sort(key=lambda f: f[0])
    return pool[0]


def _pick_first_pay_day(results, month):
    """
    1차 지급일(= '1차 vendor 지급', 매월 10일 규칙) 추출. 영어 'vendor' OCR이 약하므로
    한글·헤더 신호로 다단계 시도(앞이 실패하면 다음):
      1) 'vendor' 박스 → 헤더일(같은 달 최소 = 1차)
      2) '1차'+'지급' 칸(세금계산서 '발행' 제외) → 헤더일(같은 달 최소)
      3) 백스톱: 그 달 '10일' 헤더 (1차=10일 규칙; 헤더 OCR은 가장 안정적)
      4) 그래도 없으면 그 달 헤더 중 10에 가장 가까운 날
    """
    if not results:
        return None, None
    img_w = max(p[0] for b, _, _ in results for p in b)
    col_w = img_w / 5.0

    headers = _build_headers(results)   # 퍼지 복원된 헤더(1U-Jul→10-Jul 등) 공유
    vboxes, ilcha = [], []
    for b, t, _c in results:
        cx, cy = _center(b)
        tt = t.replace(" ", "")
        if VENDOR_RE.search(t):
            vboxes.append((cx, cy))
        # '1차' + '지급' 동시 포함, 단 '발행'(세금계산서) 칸은 제외 (차→자 오독 허용)
        if re.search(r"1\s*[차자]", t) and ("지급" in tt) and ("발행" not in tt):
            ilcha.append((cx, cy))

    if not headers:
        return None, None

    def days_from(boxes):
        out = []
        for bx, by in boxes:
            h = _header_above(headers, bx, by, col_w)
            if h:
                out.append((h[2], h[3]))
        return out

    # 전략 1, 2
    for boxes in (vboxes, ilcha):
        day, mo = _earliest_day(days_from(boxes), month)
        if day:
            return day, mo

    # 전략 3: 그 달 10일 헤더
    if any(h[3] == month and h[2] == 10 for h in headers):
        return 10, month

    # 전략 4: 그 달 헤더 중 10에 가장 가까운 날
    same = [h for h in headers if h[3] == month]
    if same:
        same.sort(key=lambda h: abs(h[2] - 10))
        return same[0][2], same[0][3]
    return None, None


def _mk_date(year, month, day):
    if not day or not (1 <= day <= 31):
        return None
    try:
        return dt.date(year, month, day)
    except ValueError:
        return None


_PADDLE = None  # paddleocr 파이프라인 캐시


def _paddle_results(img):
    """PaddleOCR(korean, PP-OCRv5)로 인식 → easyocr과 동일한 (bbox, text, conf) 형태로 변환.
    2026-09 A/B 테스트: easyocr 대비 avg conf 0.62~0.71 → 0.965, 날짜 헤더·'N차 vendor
    지급'·'메일마감(by EOD)'을 정확히 읽어냄. mkldnn은 이 머신에서 추론 크래시(OneDNN
    PIR 미지원 버그)를 일으키므로 반드시 비활성."""
    global _PADDLE
    if _PADDLE is None:
        os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
        from paddleocr import PaddleOCR
        _PADDLE = PaddleOCR(lang="korean",
                            use_doc_orientation_classify=False,
                            use_doc_unwarping=False,
                            use_textline_orientation=False,
                            enable_mkldnn=False)
    res = _PADDLE.predict(img)
    out = []
    for page in res:
        d = page if isinstance(page, dict) else getattr(page, "json", {}).get("res", page)
        texts = d.get("rec_texts") or []
        scores = d.get("rec_scores") or []
        boxes = d.get("rec_boxes")              # numpy 배열 — truthiness 평가 금지!
        if boxes is None:
            boxes = []
        for i, txt in enumerate(texts):
            bx = boxes[i]
            bbox = [[bx[0], bx[1]], [bx[2], bx[1]], [bx[2], bx[3]], [bx[0], bx[3]]]
            out.append((bbox, txt, float(scores[i])))
    return out


def ocr_find_dates(image_path, year, month):
    """이미지 1장에서 (1차 지급일, 2차 지급요청 마감일, 2차 헤더텍스트) 추출."""
    global _READER
    import numpy as np
    import cv2
    # cv2.imread는 윈도우 한글/유니코드 경로를 못 읽으므로 직접 바이트로 읽어 디코드
    with open(image_path, "rb") as f:
        data = f.read()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None, None, None
    try:
        results = _paddle_results(img)          # 1순위: PaddleOCR(정확도 우수)
    except Exception as e:
        print(f"    [폴백] PaddleOCR 실패({type(e).__name__}: {e}) → easyocr로 재시도")
        import easyocr
        if _READER is None:
            _READER = easyocr.Reader(['ko', 'en'], gpu=False, verbose=False)
        results = _READER.readtext(img)         # 2순위: 기존 easyocr
    sday, shtext = _pick_deadline_day(results, month)        # 2차 지급요청 마감
    # 인식 실패 시 자동 진단 덤프(다음 실행 로그로 원인 파악) — CAL_DEBUG 없어도 찍힘
    if sday is None or os.environ.get("CAL_DEBUG"):
        tag = "인식실패-진단" if sday is None else "CAL_DEBUG"
        print(f"    [{tag}] OCR 박스 {len(results)}개 (cx,cy conf | text):")
        for b, t, c in results:
            cx = sum(p[0] for p in b) / 4.0
            cy = sum(p[1] for p in b) / 4.0
            print(f"      ({cx:5.0f},{cy:5.0f}) {c:.2f} | {t!r}")
    fday, _fm = _pick_first_pay_day(results, month)          # 1차 지급(10일)
    return _mk_date(year, month, fday), _mk_date(year, month, sday), shtext


# ───────────────────────── OCR 결과 검증(안전장치) ─────────────────────────
def _is_business_day(d: dt.date) -> bool:
    return d.weekday() < 5 and d not in KR_HOLIDAYS


def _fallback_first_anchor(year: int, month: int) -> dt.date:
    """1차 vendor 지급 폴백: 매월 10일(휴일이면 직전 영업일)."""
    d = dt.date(year, month, FIRST_PAY_FALLBACK_DAY)
    while not _is_business_day(d):
        d -= dt.timedelta(days=1)
    return d


def _fallback_second_anchor(year: int, month: int) -> dt.date:
    """2차 마감 폴백: 월말에서 N번째 영업일."""
    if month == 12:
        d = dt.date(year, 12, 31)
    else:
        d = dt.date(year, month + 1, 1) - dt.timedelta(days=1)
    cnt = 0
    while True:
        if _is_business_day(d):
            cnt += 1
            if cnt == SECOND_NTH_LAST_WD:
                return d
        d -= dt.timedelta(days=1)


def _log_anomaly(subject: str, message: str) -> None:
    """OCR 이상치를 별도 로그에 남긴다. 정상 실행 시 print 출력은 상위 러너가
    캡처하지 않아 조용히 사라질 수 있으므로(2026-08 사고 원인), 파일로 반드시 남긴다."""
    try:
        with open(ANOMALY_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {subject!r} - {message}\n")
    except Exception:
        pass


def _sanity_check(first, second, year, month, subject):
    """OCR로 뽑은 first/second가 상식적인 범위를 벗어나면 그 필드를 버리고(None)
    사유를 출력+로그한다. 버려진 필드는 다운스트림 폴백 규칙에 맡긴다."""
    if first:
        fb = _fallback_first_anchor(year, month)
        diff = abs((first - fb).days)
        if diff > FIRST_PAY_TOLERANCE_DAYS:
            msg = (f"1차 지급일 이상치: OCR={first} vs 폴백(매월{FIRST_PAY_FALLBACK_DAY}일)={fb} "
                   f"(차이 {diff}일) → OCR값 폐기, 폴백 규칙 사용")
            print(f"  [경고] {msg}")
            _log_anomaly(subject, msg)
            first = None
    if second:
        fb2 = _fallback_second_anchor(year, month)
        diff2 = abs((second - fb2).days)
        if diff2 > SECOND_TOLERANCE_DAYS:
            msg = (f"2차 마감일 이상치: OCR={second} vs 폴백(월말 {SECOND_NTH_LAST_WD}번째 영업일)={fb2} "
                   f"(차이 {diff2}일) → 이 이미지 결과 폐기(캐시 안 함)")
            print(f"  [경고] {msg}")
            _log_anomaly(subject, msg)
            second = None
        elif first and second <= first:
            msg = f"2차 마감({second})이 1차 지급일({first})보다 빠름 → 순서 오류, 이 이미지 결과 폐기(캐시 안 함)"
            print(f"  [경고] {msg}")
            _log_anomaly(subject, msg)
            second = None
    return first, second


# ───────────────────────── 캐시 ─────────────────────────
def load_cache():
    try:
        with open(CACHE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(d):
    try:
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ───────────────────────── 캘린더 등록 ─────────────────────────
def calendar_has(subject: str, date: dt.date) -> bool:
    items = get_calendar_folder().Items
    items.IncludeRecurrences = True
    items.Sort("[Start]")
    start = dt.datetime(date.year, date.month, date.day, 0, 0)
    end = start + dt.timedelta(days=1)
    try:
        items = items.Restrict(
            "[Start] >= '" + _outlook_dt(start) + "' AND [Start] < '" + _outlook_dt(end) + "'")
    except Exception:
        pass
    for it in items:
        try:
            if (it.Subject or "").strip() == subject.strip():
                s = it.Start
                if s.year == date.year and s.month == date.month and s.day == date.day:
                    return True
        except Exception:
            continue
    return False


def create_event(subject, date, hour=9, reminder=0, body=""):
    folder = get_calendar_folder()
    appt = folder.Items.Add(OL_APPOINTMENT)   # 해당 스토어 캘린더에 직접 생성
    appt.Subject = subject
    appt.Start = dt.datetime(date.year, date.month, date.day, hour, 0)
    appt.Duration = 30
    if body:
        appt.Body = body
    appt.ReminderSet = True
    appt.ReminderMinutesBeforeStart = reminder
    appt.BusyStatus = OL_BUSY_FREE
    appt.Save()


# 2026-08-10 사용자 요청: 자동 발송/초안 메일 글꼴을 굴림 -> 맑은 고딕으로 통일.
# 평문(.Body)으로 만들면 Outlook의 평문 기본 글꼴을 따라가므로 HTML로 만든다.
# (Outlook 일정 항목의 본문은 메일이 아니므로 그대로 둔다)
MAIL_FONT_CSS = "font-family:'맑은 고딕',Malgun Gothic,sans-serif;font-size:10.0pt"


def mail_text_to_html(text: str) -> str:
    """평문 본문을 맑은 고딕 HTML로 감싼다.
    HTML은 연속 공백을 하나로 줄이므로 들여쓰기가 뭉개지지 않도록 2칸 이상
    연속 공백은 &nbsp;로 보존한다."""
    import html as html_module
    import re as re_module
    esc = html_module.escape(str(text or ""))
    esc = esc.replace("\r\n", "\n").replace("\r", "\n")
    esc = re_module.sub(r"  +", lambda mm: "&nbsp;" * len(mm.group()), esc)
    esc = esc.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
    return f'<div style="{MAIL_FONT_CSS}">' + esc.replace("\n", "<br>") + "</div>"


# ───────────────────────── 담당자 메일 ─────────────────────────
def build_mail(month: int, cutoff: dt.date):
    subject = f"{SUBJECT_PREFIX} {month}월 거래명세서 지급일 요청"
    body = (
        f"안녕하세요, {COMPANY} {SENDER_NAME}입니다.\n\n"
        f"{cutoff.month}월 {cutoff.day}일 오전까지 거래명세서 발급 부탁드립니다.\n\n"
        f"감사합니다.\n"
        f"{SENDER_NAME} 드림"
    )
    return subject, body


def send_vendor_mails(month: int, cutoff: dt.date):
    subject, body = build_mail(month, cutoff)
    app = win32com.client.Dispatch("Outlook.Application")
    mode = "발송" if SEND_MODE else "초안저장"
    for v in VENDORS:
        try:
            mail = app.CreateItem(OL_MAIL_ITEM)
            mail.To = v["to"]
            mail.CC = "; ".join(v["cc"])
            mail.Subject = subject
            mail.HTMLBody = mail_text_to_html(body)
            if SEND_MODE:
                mail.Send()
            else:
                mail.Save()   # Drafts 폴더에 저장
            print(f"[메일·{mode}] {v['name']} → {v['to']}")
        except Exception as e:
            print(f"[메일·실패] {v['name']} ({e})")


# ───────────────────────── 메인 ─────────────────────────
def _normalize_cache_entry(v):
    """캐시 항목을 {first, second, ...} 형태로 정규화(구 포맷=문자열은 2차만)."""
    if isinstance(v, str):
        return {"first": None, "second": v, "mail_sent": False}
    if isinstance(v, dict):
        return {"first": v.get("first"), "second": v.get("second"),
                "ym": v.get("ym"), "subject": v.get("subject"),
                "mail_sent": v.get("mail_sent", False)}
    return {"first": None, "second": None, "mail_sent": False}


def resolve_calendar():
    """
    캘린더 날짜 결정 → {'first': iso|None, 'second': iso|None} 반환하며 캐시에 저장.
    second(2차 지급요청 마감)는 이 스크립트의 일정 생성 기준.
    first(1차 vendor 지급)는 dhl_forwarder 가 함께 사용하도록 캐시.
    우선순위: 명령행 인자(2차만) > 캐시 > OCR.
    """
    if len(sys.argv) > 1:
        d = dt.date.fromisoformat(sys.argv[1])
        print(f"[입력] 2차 마감 = {d} ({WD[d.weekday()]})")
        return {"first": None, "second": d.isoformat(), "eid": None}

    msg = find_latest_calendar_mail()
    if msg is None:
        print("Finance Calendar 메일을 찾지 못했습니다.")
        return None

    year, month = parse_subject_ym(msg.Subject)
    eid = msg.EntryID
    cache = load_cache()

    if eid in cache:
        c = _normalize_cache_entry(cache[eid])
        if c.get("second"):
            sd = dt.date.fromisoformat(c["second"])
            fd = dt.date.fromisoformat(c["first"]) if c.get("first") else None
            ftxt = f"1차 {fd} / " if fd else ""
            print(f"[캐시] '{msg.Subject}' → {ftxt}2차 마감 {sd} ({WD[sd.weekday()]})")
            c["eid"] = eid
            return c

    print(f"[OCR] '{msg.Subject}' 이미지 인식 중...")
    images = extract_calendar_images(msg)
    if not images:
        print("  달력 이미지를 찾지 못했습니다.")
        return None

    for path in images:
        first, second, htext = ocr_find_dates(path, year, month)
        first, second = _sanity_check(first, second, year, month, msg.Subject or "")
        if second:
            entry = {
                "first": first.isoformat() if first else None,
                "second": second.isoformat(),
                "ym": f"{year}-{month:02d}",
                "subject": msg.Subject or "",
            }
            cache[eid] = entry
            save_cache(cache)
            ftxt = (f"1차 vendor 지급 {first} ({WD[first.weekday()]}) / "
                    if first else "1차 인식 실패 / ")
            print(f"  인식: {ftxt}2차 마감 헤더 '{htext}' → {second} ({WD[second.weekday()]})")
            entry = dict(entry)
            entry["eid"] = eid
            return entry

    print("  OCR로 2차 마감을 찾지 못했습니다. 날짜를 직접 지정해 주세요:")
    print(f"  python \"{os.path.abspath(__file__)}\" {year}-{month:02d}-DD")
    _log_anomaly(msg.Subject or "", "OCR로 2차 마감을 찾지 못해(이상치 폐기 포함) 캐시 안 함 → 수동 지정 필요")
    return None


def main():
    cal = resolve_calendar()
    if cal is None or not cal.get("second"):
        # 2026-09: 실패를 조용히 종료(exit 0)하면 group_c 러너가 stdout을 버려서
        # run_log에 흔적이 없다(2026-08 사고 원인과 동일 패턴). 실패는 반드시 exit 1로.
        print("일정 미등록: 2차 마감 미확정 (anomalies 로그 확인)")
        sys.exit(1)
    deadline = dt.date.fromisoformat(cal["second"])
    eid = cal.get("eid")
    cal_month = int(cal["ym"].split("-")[1]) if cal.get("ym") else deadline.month

    # 1) 캘린더 일정 (멱등)
    print("-" * 60)
    for offset, subject, hour, reminder, body in EVENTS:
        target = add_business_days(deadline, offset)
        tag = f"D{offset:+d}" if offset else "D-day"
        if calendar_has(subject, target):
            print(f"[건너뜀] {target} ({WD[target.weekday()]}) {tag} | 이미 존재")
            continue
        create_event(subject, target, hour, reminder, body)
        print(f"[등록]   {target} ({WD[target.weekday()]}) {tag} | {subject}")

    # 2) 담당자 cutoff 안내 메일 (EntryID 기준 월 1회)
    print("-" * 60)
    cutoff = add_business_days(deadline, MAIL_OFFSET)
    if not eid:
        print("[메일] 이메일 컨텍스트 없음(수동 단독 실행) → 담당자 메일 생략")
    else:
        cache = load_cache()
        entry = _normalize_cache_entry(cache.get(eid, {}))
        if entry.get("mail_sent"):
            print("[메일] 이미 처리됨 → 건너뜀")
        else:
            send_vendor_mails(cal_month, cutoff)
            # 기존 first/second/ym/subject 보존하며 mail_sent만 추가
            raw = cache.get(eid)
            raw = raw if isinstance(raw, dict) else {"second": deadline.isoformat()}
            raw["mail_sent"] = True
            cache[eid] = raw
            save_cache(cache)

    print("-" * 60)
    print("완료." + ("" if SEND_MODE else "  (메일은 초안 저장됨 — Drafts에서 검토 후 발송)"))


if __name__ == "__main__":
    main()
