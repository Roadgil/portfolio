#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DHL Invoice Auto-Forwarder  (배치 버전)
======================================
Outlook 받은편지함 > DHL 폴더에서 아래 3가지 조건을 모두 만족하는 메일을 찾아
eunpyeongc@candelamedical.com 으로 보낼 메일 초안을 자동 생성합니다.
(자동 발송하지 않고 임시보관함(Drafts)에 저장 — 검토 후 직접 발송)

  1) 발신자  : kr.fin.noreply@dhl.com
  2) 첨부파일: 확장자가 .pdf
  3) 첨부파일: 파일명이 'D' 로 시작 (인바운드 수수료 청구서 — 아래 배치 로직 적용)

[SELR(아웃바운드 운송료 청구서)]
  파일명이 'SELR' 로 시작하는 첨부. 금액은 인보이스 합계가 아니라 PDF 맨 아래
  PAYMENT INSTRUCTION(지로고지서)의 '금액'을 우선 사용한다(지로는 10원 단위로
  절사되어 합계와 몇 원 차이 날 수 있음 — extract_selr_amount 참고).
  2026-07-14 에는 배치로 모으지 않고 발견 즉시 초안 1통을 만들도록 바꿨었으나,
  2026-09-15 사용자 요청으로 D*.pdf 와 동일한 '건별 → 배치 전환' 방식으로 되돌림
  (아래 항목 참고). 종류(kind)만 D/SELR 로 나눠 별도 배치 초안을 만든다
  (비용목적 문구가 달라서 같은 통에 섞지 않음).

[건별 → 배치 전환] (D*.pdf, SELR*.pdf 공통)
  청구서 1건당 초안 1통을 즉시 생성하지 않고,
  각 달의 Finance Calendar 지급 차수(1차/2차)에 맞춰 '윈도우'로 묶어서 보냅니다.

  · 앵커(기준일)는 Finance Calendar 에서 (finance_calendar_to_outlook.py 가 OCR→캐시):
      - 1차 앵커 = "1차 vendor 지급"        (예: 2026-06 → 06-10)
      - 2차 앵커 = "당월 2차 지급요청 마감"  (예: 2026-06 → 06-24)
    캐시(_fin_cal_cache.json)에 없으면 해당 앵커만 휴리스틱으로 폴백(로그 경고).

  · 윈도우 규칙 (영업일 기준, 한 줄로):
      청구서 수신일 r → "D-3(윈도우 끝) ≥ r 인 가장 이른 차수"에 배정,
      그 차수의 D-2(발송일)에 해당 윈도우의 청구서를 '한 통'으로 일괄 초안 작성.

    이는 다음과 동일합니다 (틈/겹침 없이 한 달을 둘로 분할):
      ┌ [1차 D-2  …  2차 D-3]            → 2차 D-2 에 일괄 발송
      └ [2차 D-2  …  익월 1차 D-3]       → 익월 1차 D-2 에 일괄 발송

  · 발견(Phase 1)과 발송(Phase 2)을 분리합니다.
      Phase 1 : 새 청구서를 찾으면 즉시 초안을 만들지 않고 'pending' 에 적재.
      Phase 2 : 발송일(D-2)이 도래한 차수의 pending 들을 한 통으로 묶어 초안 생성.
    → 매일 실행해도 D-2 이 오기 전까지는 모으기만 하고, D-2(또는 그 이후 첫 실행)에 발송.
       PC 가 꺼져 D-2 을 놓쳐도 다음 실행에서 catch-up.

한 번 초안으로 만든 메일은 _dhl_forwarder_state.json 의 processed 목록에 EntryID 가
기록되어 중복 전송을 방지합니다. 첨부 PDF 에서 부가세 포함 총액(KRW)을 읽어 본문에 반영합니다.

요구사항:
    pip install pywin32 pdfplumber
    (pdfplumber 가 없으면 pypdf 로 자동 대체 — pip install pypdf)

작성: Candela Medical 자동화
"""

from __future__ import annotations

import json
import logging
import re
import sys
import traceback
from collections import namedtuple
from datetime import datetime, timedelta, date
from pathlib import Path

import pythoncom
import win32com.client


# ============================================================
#                          설정
# ============================================================
SENDER_ADDRESS    = "kr.fin.noreply@dhl.com"
RECIPIENT_ADDRESS = "eunpyeongc@candelamedical.com"
CC_ADDRESS        = "younjinl@candelamedical.com; kates@candelamedical.com; miaej@candelamedical.com"
ATTACHMENT_EXT    = ".pdf"     # 첨부파일 확장자

# 첨부파일명 패턴. 2026-08-21 수정: 예전엔 "D 로 시작"만 봐서
# 'DHL 미수금 납부 촉구서 - 1302121524 ....PDF' 같은 파일이 그대로 통과했다.
# 실제 청구서는 항상 D/SELR + 숫자 형식이므로 숫자까지 요구한다.
ATTACHMENT_PATTERN      = re.compile(r'^D\d{5,}', re.I)     # 인바운드 수수료 청구서(배치)
ATTACHMENT_PATTERN_SELR = re.compile(r'^SELR\d{5,}', re.I)  # 아웃바운드 운송료 청구서(즉시 처리)

# 파일명에 아래 문구가 있으면 청구서로 보지 않고 무시(패턴을 통과하더라도).
EXCLUDE_FILENAME_KEYWORDS = ["촉구", "미수금", "독촉"]

# 제목에 아래 문구 중 하나라도 포함되면 전달 대상에서 제외(초안 생성 안 함).
#  · DHL '미수금 내역 안내문' / '미수금 납부 촉구서'는 실제 청구서가 아니므로 제외.
#    (사용자 지시 2026-08-21: 재무팀 DHL 납부 메일에 촉구서는 절대 포함하지 말 것)
#  · 비교는 공백을 모두 제거하고 하므로 '미수금 내역 안내' == '미수금내역안내'.
#  · 특정 건 하나만 제외하려면 그 송장번호(예: "1302121524")를 추가하세요.
EXCLUDE_SUBJECT_KEYWORDS = [
    "미수금",      # 미수금 내역 안내 / 미수금 납부 촉구서 등 전부
    "납부촉구",
    "촉구서",
    "독촉",
]

# 메일 '발견' 검색 기간(일). 1 = 최근 24시간. 작업 누락 방지를 위해 2~3 권장.
# (발견된 청구서는 pending 에 적재되어 발송일까지 보관되므로, 이 값은 '발견 시점' 한정.)
LOOKBACK_DAYS = 3

# True 로 두면 실제 초안 저장/발송 없이 로그만 남깁니다(테스트용).
# 상태 파일도 갱신하지 않으므로 반복 테스트 가능.
DRY_RUN = False

# 배치를 '초안 저장'할지 '자동 발송'할지.
#   False(기본/권장) : 임시보관함(Drafts)에 한 통으로 저장 → 검토 후 직접 발송.
#   True             : D-2 도래 시 자동으로 한 통 '발송'(MailItem.Send).
# ※ 금액 오인식 위험이 있으니, 한동안 False 로 초안만 확인한 뒤 전환을 권장합니다.
SEND_MODE = False

# 발송일(D-2) '당일'에 몇 시 이후부터 배치를 만들지(시각 가드).
#   None : 시각 무시 — D-2 당일 어느 실행에서든 즉시 생성(=스케줄러 트리거 시각에 좌우).
#   10   : D-2 당일에는 10시 이후 실행에서만 생성(오전 10시 정시 발송용).
# ※ D-2 를 이미 지난 경우(catch-up)는 시각과 무관하게 즉시 생성합니다.
# ※ 작업이 하루 1회·정시(예: 10:00)만 돈다면 None 으로 둬도 결과는 같습니다.
SEND_AT_HOUR = None

# [중요] 해당 '월'의 Finance Calendar 가 캐시에 들어오기 전엔 그 달 배치를 보류.
#   Finance Calendar 메일은 월말에 도착하므로, 다음 달 앵커(1차/2차)는 그 메일이
#   와야 확정된다. True 면 그 달 캐시가 생길 때까지 발송하지 않고 계속 모아둔다(hold).
#   → 추정(휴리스틱) 날짜로 잘못 나가는 것을 방지. 캘린더 도착 후 자동으로 발송.
REQUIRE_CALENDAR_MONTH = True

# 안전장치: 캘린더가 끝내 안 와도 발송일을 N일 초과하면 휴리스틱 날짜로 강제 발송.
#   None(기본) : 강제 안 함 — 캘린더 올 때까지 계속 보류(매 실행 경고 로그).
#   예) 7      : (추정)발송일이 7일 지나도 캐시에 그 달이 없으면 경고 후 발송.
FORCE_SEND_IF_OVERDUE_DAYS = None

# 스크립트 폴더 기준 경로
SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "_dhl_forwarder_state.json"
LOG_FILE   = SCRIPT_DIR / "dhl_forwarder.log"
TEMP_DIR   = SCRIPT_DIR / "_temp_attachments"

SUBJECT_TEMPLATE_SINGLE = "[DHL 비용청구] 미결제 청구서 전달 ({invoice})"
SUBJECT_TEMPLATE_BATCH  = "[DHL 비용청구] 미결제 청구서 {count}건 일괄 전달 ({pay_round} 지급)"

PURPOSE_D    = "수수료"   # 인바운드(D*.pdf) 청구서
PURPOSE_SELR = "운송료"   # 아웃바운드(SELR*.pdf) 청구서 (2026-07-14 추가)

# 2026-08-10 사용자 요청: 자동 발송/초안 메일 글꼴을 굴림 -> 맑은 고딕으로 통일.
# 평문(.Body)으로 만들면 Outlook의 평문 기본 글꼴을 따라가므로 HTML로 만든다.
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


BODY_TEMPLATE = """안녕하세요 전은평 주임님.

DHL 현재 납부할 내역 확인 후 첨부 드리니 비용처리 부탁드립니다.

1. 비용목적 : {purpose}
2. 지급금액 : {amount}
3. 지급날짜 : {pay_date}
4. 지급방법 : 계좌 변동 없음
5. 첨부파일 : 정산서

감사합니다.

채윤길 드림"""


# ============================================================
#                    지급일 / 윈도우 설정
# ============================================================
# 앵커(기준일) — 각 달 Finance Calendar 에서 가져온다(없으면 휴리스틱 폴백):
#   · 1차 앵커 : "1차 vendor 지급" 날짜 (예: 2026-06 → 06-10)   ← 폴백: 매월 10일(휴일이면 직전 영업일)
#   · 2차 앵커 : "당월 2차 지급요청 마감" 날짜 (예: 2026-06 → 06-24)  ← 폴백: 월말 3번째 영업일(주의: 의미 다름)
# 발송/윈도우 (영업일 기준)
#   · 발송일(D-2) : 앵커의 2 영업일 전
#   · 윈도우 끝(D-3): 앵커의 3 영업일 전
#   · 윈도우 시작 : 직전 차수의 발송일(D-2)
#   ┌ [1차 D-2 … 2차 D-3]          → 2차 D-2 에 일괄 발송
#   └ [2차 D-2 … 익월 1차 D-3]     → 익월 1차 D-2 에 일괄 발송
FIRST_PAY_DAY          = 10      # (폴백) 1차 앵커: 매월 10일
SECOND_PAY_NTH_LAST_WD = 3       # (폴백) 2차 앵커: 월말 마지막에서 N번째 working day
SEND_OFFSET_WD         = 2       # 발송일 = 앵커 - N working days (D-2)
WINDOW_END_OFFSET_WD   = 3       # 윈도우 끝 = 앵커 - N working days (D-3)

# Finance Calendar(OCR 캐시)를 1차/2차 앵커의 우선 출처로 사용할지 여부.
#   True(권장): _fin_cal_cache.json(= finance_calendar_to_outlook.py 산출)에서
#               해당 월의 1차 vendor 지급 / 2차 지급요청 마감 날짜를 읽음.
#               캐시에 없으면 해당 앵커만 휴리스틱으로 폴백(로그 경고).
#   ※ 2차 휴리스틱(월말 3번째 영업일)은 '지급요청 마감'이 아니라 'vendor 지급일'에
#      가까우므로, 캐시가 비어있을 땐 날짜가 다를 수 있음 — 캘린더 메일 처리 권장.
PREFER_FINANCE_CALENDAR = True
FIN_CAL_CACHE = SCRIPT_DIR / "_fin_cal_cache.json"

# 한국 공휴일 — working day 계산에서 제외됩니다.
# ※ 매년 초에 다음 해 공휴일(대체공휴일 포함)을 추가해 주세요.
#    등록되지 않은 연도는 주말만 제외하고 계산되며 로그에 경고가 남습니다.
KR_HOLIDAYS = {
    # ---- 2026년 ----
    "2026-01-01",                                              # 신정
    "2026-02-16", "2026-02-17", "2026-02-18",                  # 설날 연휴
    "2026-03-01", "2026-03-02",                                # 삼일절(일) + 대체공휴일
    "2026-05-05",                                              # 어린이날
    "2026-05-24", "2026-05-25",                                # 부처님오신날(일) + 대체공휴일
    "2026-06-03",                                              # 전국동시지방선거
    "2026-06-06",                                              # 현충일(토)
    "2026-07-17",                                              # 제헌절(금, 2026년부터 공휴일 재지정)
    "2026-08-15", "2026-08-17",                                # 광복절(토) + 대체공휴일
    "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-28",    # 추석 연휴 + 대체공휴일
    "2026-10-03", "2026-10-05",                                # 개천절(토) + 대체공휴일
    "2026-10-09",                                              # 한글날
    "2026-12-25",                                              # 성탄절
    # ---- 2027년 ----
    "2027-01-01",                                              # 신정
    "2027-02-05", "2027-02-06", "2027-02-07", "2027-02-08",    # 설날 연휴(토~일 포함) + 대체공휴일
    "2027-03-01",                                              # 삼일절(월)
    "2027-05-05",                                              # 어린이날
    "2027-05-13",                                              # 부처님오신날
    "2027-06-06",                                              # 현충일(일)
    "2027-07-17",                                              # 제헌절(토)
    "2027-08-15", "2027-08-16",                                # 광복절(일) + 대체공휴일
    "2027-09-14", "2027-09-15", "2027-09-16",                  # 추석 연휴
    "2027-10-03", "2027-10-04",                                # 개천절(일) + 대체공휴일
    "2027-10-09", "2027-10-11",                                # 한글날(토) + 대체공휴일
    "2027-12-25", "2027-12-27",                                # 성탄절(토) + 대체공휴일
    # ---- 2028년 ----
    "2028-01-01",                                              # 신정(토)
    "2028-01-25", "2028-01-26", "2028-01-27",                  # 설날 연휴
    "2028-03-01",                                              # 삼일절(수)
    "2028-04-12",                                              # 국회의원선거(수)
    "2028-05-02",                                              # 부처님오신날(화)
    "2028-05-05",                                              # 어린이날(금)
    "2028-06-06",                                              # 현충일(화)
    "2028-07-17",                                              # 제헌절(월)
    "2028-08-15",                                              # 광복절(화)
    "2028-10-02", "2028-10-03", "2028-10-04", "2028-10-05",    # 추석 연휴(개천절 겹침) + 대체공휴일
    "2028-10-09",                                              # 한글날(월)
    "2028-12-25",                                              # 성탄절(월)
}
HOLIDAY_YEARS = {int(s[:4]) for s in KR_HOLIDAYS}

# 한 지급 차수를 나타내는 구조체
Round = namedtuple("Round", "pay_date label send_date window_end year month")


# ============================================================
#                          유틸
# ============================================================
def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            st.setdefault("processed_entry_ids", [])
            # pending 키: "{EntryID}::{kind}" (kind: "D"|"SELR"), 값: {"entry_id","kind","received","subject"}
            st.setdefault("pending", {})
            st.setdefault("last_run", None)
            # 2026-09-15 이전 포맷(키=EntryID 그대로, kind 없음 — 전부 D*.pdf)을 이행.
            for key, meta in st["pending"].items():
                meta.setdefault("entry_id", key)
                meta.setdefault("kind", "D")
            return st
        except Exception as e:
            logging.warning(f"상태 파일 파싱 실패: {e} → 새로 시작합니다.")
    return {"processed_entry_ids": [], "pending": {}, "last_run": None}


def save_state(state: dict) -> None:
    state["last_run"] = datetime.now().isoformat(timespec="seconds")
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def sanitize_filename(name: str) -> str:
    """Windows 파일 시스템에서 사용 불가능한 문자를 '_' 로 치환."""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip()


# ============================================================
#                  영업일 / 지급일 계산
# ============================================================
def is_working_day(d: date) -> bool:
    """주말/공휴일이 아닌 영업일 여부."""
    return d.weekday() < 5 and d.strftime("%Y-%m-%d") not in KR_HOLIDAYS


def working_days_before(d: date, n: int) -> date:
    """d 기준 n번째 이전 working day. (n=1, d=2026-06-10 → 2026-06-09)"""
    cur, cnt = d, 0
    while cnt < n:
        cur -= timedelta(days=1)
        if is_working_day(cur):
            cnt += 1
    return cur


def nth_last_working_day_of_month(year: int, month: int, n: int) -> date:
    """해당 월의 마지막에서 n번째 working day. (2026-06, n=3 → 06-26)"""
    if month == 12:
        cur = date(year, 12, 31)
    else:
        cur = date(year, month + 1, 1) - timedelta(days=1)
    cnt = 0
    while True:
        if is_working_day(cur):
            cnt += 1
            if cnt == n:
                return cur
        cur -= timedelta(days=1)


def _load_fin_cal() -> dict:
    try:
        return json.loads(FIN_CAL_CACHE.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _cal_dates_for(year: int, month: int):
    """
    캐시에서 해당 (year, month)의 (first_date, second_date) 반환. 신/구 포맷 모두 지원.
      · 신 포맷: {eid: {"first": iso, "second": iso, ...}}
      · 구 포맷: {eid: "iso"}  → 2차(지급요청 마감)만
    """
    first = second = None
    for v in _load_fin_cal().values():
        if isinstance(v, str):
            try:
                d = date.fromisoformat(v)
                if d.year == year and d.month == month:
                    second = d
            except Exception:
                pass
        elif isinstance(v, dict):
            for key, slot in (("first", "first"), ("second", "second")):
                raw = v.get(key)
                if not raw:
                    continue
                try:
                    d = date.fromisoformat(raw)
                except Exception:
                    continue
                if d.year == year and d.month == month:
                    if slot == "first":
                        first = d
                    else:
                        second = d
    return first, second


def _calendar_has_month(year: int, month: int) -> bool:
    """해당 (year, month)의 Finance Calendar 데이터가 캐시에 존재하는지."""
    target = f"{year}-{month:02d}"
    for v in _load_fin_cal().values():
        if isinstance(v, str):
            try:
                d = date.fromisoformat(v)
                if d.year == year and d.month == month:
                    return True
            except Exception:
                pass
        elif isinstance(v, dict):
            if v.get("ym") == target:
                return True
            for k in ("first", "second"):
                raw = v.get(k)
                if not raw:
                    continue
                try:
                    d = date.fromisoformat(raw)
                    if d.year == year and d.month == month:
                        return True
                except Exception:
                    pass
    return False


_warned_anchor: set = set()


def _warn_once(tag: str, msg: str) -> None:
    if tag not in _warned_anchor:
        _warned_anchor.add(tag)
        logging.warning(msg)


def first_anchor(year: int, month: int) -> date:
    """1차 앵커 = '1차 vendor 지급'. 캘린더 우선, 없으면 10일(휴일이면 직전 영업일)."""
    if PREFER_FINANCE_CALENDAR:
        f, _ = _cal_dates_for(year, month)
        if f:
            return f
        _warn_once(
            f"first-{year}-{month:02d}",
            f"{year}-{month:02d} 1차 vendor 지급일 캐시 미발견 → 휴리스틱(10일) 폴백.",
        )
    d = date(year, month, FIRST_PAY_DAY)
    while not is_working_day(d):
        d -= timedelta(days=1)
    return d


def second_anchor(year: int, month: int) -> date:
    """2차 앵커 = '당월 2차 지급요청 마감'. 캘린더 우선, 없으면 월말 N번째 영업일(주의)."""
    if PREFER_FINANCE_CALENDAR:
        _, s = _cal_dates_for(year, month)
        if s:
            return s
        _warn_once(
            f"second-{year}-{month:02d}",
            f"{year}-{month:02d} 2차 지급요청 마감일 캐시 미발견 → 월말 3번째 영업일로 폴백. "
            "이 값은 '지급요청 마감'이 아닐 수 있으니 Finance Calendar 처리를 확인하세요.",
        )
    return nth_last_working_day_of_month(year, month, SECOND_PAY_NTH_LAST_WD)


def _round_from(anchor: date, label: str) -> Round:
    return Round(
        pay_date=anchor,                                                  # 앵커(1차 vendor 지급 / 2차 지급요청 마감)
        label=label,
        send_date=working_days_before(anchor, SEND_OFFSET_WD),            # D-2
        window_end=working_days_before(anchor, WINDOW_END_OFFSET_WD),     # D-3
        year=anchor.year,
        month=anchor.month,
    )


_warned_years: set = set()


def _warn_missing_holidays(year: int) -> None:
    if year not in HOLIDAY_YEARS and year not in _warned_years:
        _warned_years.add(year)
        logging.warning(
            f"{year}년 공휴일이 KR_HOLIDAYS 에 등록되지 않았습니다. "
            "주말만 제외하고 계산하므로 날짜가 부정확할 수 있습니다."
        )


def iter_rounds(start_year: int, start_month: int, n_months: int) -> list:
    """start_(year,month)부터 n_months 동안의 (1차,2차) 차수를 window_end 순으로 정렬해 반환."""
    y, m = start_year, start_month
    rounds = []
    for _ in range(n_months):
        _warn_missing_holidays(y)
        rounds.append(_round_from(first_anchor(y, m), "1차"))
        rounds.append(_round_from(second_anchor(y, m), "2차"))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    rounds.sort(key=lambda r: r.window_end)
    return rounds


def assign_round(received_date: date) -> Round:
    """
    청구서 수신일 → 배정 지급 차수.
    규칙: window_end(D-3) >= received_date 인 가장 이른 차수.
          (윈도우가 틈/겹침 없이 한 달을 둘로 나누므로 이 한 조건이 곧 윈도우 소속을 뜻함)
    """
    # 수신월부터 앞으로 2개월이면 어떤 경우든 매칭 차수를 포함한다(2026-07-10: 4개월은
    # 과도한 여유라 사용자 요청으로 2개월로 축소).
    rounds = iter_rounds(received_date.year, received_date.month, 2)
    for r in rounds:
        if r.window_end >= received_date:
            return r
    return rounds[-1]  # 방어 코드


def format_pay_date(pay_date: date, pay_round: str) -> str:
    """본문 '지급날짜' 라인 — 차수만 표기(기존 포맷 유지)."""
    return f"{pay_round} 지급"


# ============================================================
#                   Outlook / 첨부 / PDF
# ============================================================
def get_sender_smtp(mail) -> str:
    """Outlook MailItem 에서 SMTP 주소를 안전하게 추출."""
    try:
        addr = (mail.SenderEmailAddress or "").strip()
    except Exception:
        return ""
    if not addr:
        return ""
    if addr.startswith("/"):  # 사내 Exchange 주소(/O=...)면 SMTP 로 변환
        try:
            exch_user = mail.Sender.GetExchangeUser()
            if exch_user is not None:
                return (exch_user.PrimarySmtpAddress or "").lower()
        except Exception:
            return ""
    return addr.lower()


def find_target_attachments(mail, pattern=ATTACHMENT_PATTERN) -> list:
    """파일명이 pattern(D숫자/SELR숫자)으로 시작하고 .pdf 로 끝나는 첨부만 반환.
    촉구서/미수금 안내문은 파일명 키워드로 한 번 더 걸러낸다."""
    matches = []
    try:
        for att in mail.Attachments:
            fname = (att.FileName or "")
            if not fname.lower().endswith(ATTACHMENT_EXT.lower()):
                continue
            if not pattern.match(fname):
                continue
            if any(kw in fname for kw in EXCLUDE_FILENAME_KEYWORDS):
                logging.info(f"제외 파일명 매칭 → 첨부 제외: {fname!r}")
                continue
            matches.append(att)
    except Exception as e:
        logging.warning(f"첨부 확인 실패: {e}")
    return matches


def _amounts_from_text(text: str) -> list:
    """개별 청구서(INBOUND CHARGES INVOICE) 텍스트에서 총액 후보(int) 추출."""
    cands = []
    patterns = [
        r'The\s*Amount\s*:?\s*KRW\s*([\d][\d,]*)',   # 청구내역 총액
        r'Total\s*Amount\s*KRW\s*:?\s*([\d][\d,]*)', # 수금통지서/승인서 총액
    ]
    for pat in patterns:
        for m in re.findall(pat, text, re.I):
            try:
                cands.append(int(m.replace(",", "")))
            except ValueError:
                pass
    return cands


def _dunning_total(text: str):
    """미수금 납부 촉구서에서 '연체 합계(부가세 포함)' 추출."""
    m = re.search(r'경과\s*미수금\s*:?\s*KRW\s*([\d,]+)', text)
    if m:
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    rows = re.findall(
        r'\b\d{9}\s+D0\d{5,}\s+\d{4}/\d{2}/\d{2}\s+\d{4}/\d{2}/\d{2}\s+KRW\s+([\d,]+)',
        text,
    )
    if rows:
        try:
            return sum(int(r.replace(",", "")) for r in rows)
        except ValueError:
            pass
    return None


def _read_pdf_text(pdf_path: Path):
    """PDF 텍스트 추출. (engine, text) 반환. pdfplumber 1순위, 실패 시 pypdf."""
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            text = "".join((pg.extract_text() or "") + "\n" for pg in pdf.pages)
        return "pdfplumber", text
    except ImportError:
        logging.info("pdfplumber 미설치 → pypdf 로 대체합니다. (pip install pdfplumber 권장)")
    except Exception as e:
        logging.warning(f"pdfplumber 추출 실패: {e} → pypdf 로 대체 시도")

    try:
        from pypdf import PdfReader
        text = "".join((pg.extract_text() or "") + "\n" for pg in PdfReader(str(pdf_path)).pages)
        return "pypdf", text
    except Exception as e:
        logging.error(f"PDF 텍스트 추출 실패({pdf_path.name}): {e}")
        return None, None


def extract_invoice_amount(pdf_path: Path):
    """
    DHL PDF에서 '부가세 포함 청구 금액(KRW)'을 추출한다. 성공 시 int, 실패 시 None.
      1) 개별 청구서 → 'The Amount: KRW' / 'Total Amount KRW' 총액
      2) 미수금 납부 촉구서 → '경과 미수금(연체 합계)' 또는 청구서 행 합산
    pypdf 는 개별 청구서 옆 계좌번호 오인식 사례가 있어 'The Amount: KRW' 앵커만 신뢰한다.
    """
    engine, text = _read_pdf_text(pdf_path)
    if not text:
        return None

    if engine == "pypdf":
        m = re.search(r'The\s*Amount\s*:?\s*KRW\s*([\d][\d,]*)', text, re.I)
        invoice_cands = [int(m.group(1).replace(",", ""))] if m else []
    else:
        invoice_cands = _amounts_from_text(text)

    if invoice_cands:
        from collections import Counter
        return Counter(invoice_cands).most_common(1)[0][0]

    return _dunning_total(text)


def extract_selr_giro_amount(text: str):
    """SELR(아웃바운드) 인보이스 하단 PAYMENT INSTRUCTION(지로고지서)의 '금액'을 추출.
    인보이스 자체 합계(Total Amount)와 다를 수 있음 — 지로 결제는 10원 단위로
    절사되기 때문(예: 합계 270,085원 → 지로 금액 270,080원). 항상 지로 금액을
    우선 사용한다.

    이 페이지는 라벨(금액/청구일자/납부기한 등)이 배경 이미지라 pdfplumber
    텍스트 레이어엔 값만 남는다(실측: "270,080\n6005417310\nSYNERON CANDELA
    KOREA\n594884246 2025-11-30\nSELR005417310 2025-12-30"). "인보이스번호 +
    공백 + 납부기한(YYYY-MM-DD)"이 이 페이지에서만 나오는 고유 패턴이라 이를
    앵커로 삼고, 그 앞쪽 몇 줄 중 '숫자,숫자' 형식만 단독으로 있는 줄(=금액)을
    역방향으로 찾는다(인보이스 합계도 자기 페이지에서 단독 줄로 나오므로 앵커
    없이 전체 텍스트에서 찾으면 안 됨)."""
    m = re.search(r'SELR\d+\s+\d{4}-\d{2}-\d{2}', text)
    if not m:
        return None
    lines_before = text[: m.start()].split("\n")
    for line in reversed(lines_before[-10:]):
        line = line.strip()
        if re.fullmatch(r'\d{1,3}(,\d{3})*', line):
            try:
                return int(line.replace(",", ""))
            except ValueError:
                pass
    return None


def extract_selr_amount(pdf_path: Path):
    """SELR PDF에서 지로 금액을 추출. 못 찾으면 인보이스 합계(Total Amount (KRW))로
    폴백(경고 로그, 10원 단위 절사로 실제 청구액과 다를 수 있음)."""
    engine, text = _read_pdf_text(pdf_path)
    if not text:
        return None
    amount = extract_selr_giro_amount(text)
    if amount is not None:
        return amount

    # 폴백: DHL Express INVOICE(SELR) 양식의 합계 표기는 "Total Amount ( KRW ) 270,085"
    # 형태라 D*.pdf 용 _amounts_from_text() 패턴("The Amount: KRW" 등)과 다름.
    m = re.search(r'Total\s*Amount\s*\(\s*KRW\s*\)\s*([\d][\d,]*)', text, re.I)
    if m:
        try:
            logging.warning(
                f"{pdf_path.name}: PAYMENT INSTRUCTION 금액을 못 찾아 인보이스 합계로 대체 "
                "(지로 결제 10원 단위 절사로 실제 청구액과 다를 수 있음 — 확인 필요)"
            )
            return int(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def build_body(invoice_amounts: list, pay_date: date, pay_round: str, purpose: str = PURPOSE_D) -> str:
    """
    invoice_amounts: [(invoice_name, amount|None), ...]
    여러 건이면 총액 + 건별 내역, 못 읽으면 '확인 필요' 표기.
    """
    known = [(n, a) for n, a in invoice_amounts if a is not None]

    if not known:
        amount_line = "(PDF에서 금액을 읽지 못했습니다 — 확인 필요)"
    elif len(invoice_amounts) == 1:
        amount_line = f"{known[0][1]:,}원 (부가세포함)"
    else:
        total = sum(a for _, a in known)
        parts = [
            (f"   - {n} : {a:,}원" if a is not None else f"   - {n} : 금액 확인 필요")
            for n, a in invoice_amounts
        ]
        amount_line = f"{total:,}원 (부가세포함)\n" + "\n".join(parts)

    return BODY_TEMPLATE.format(
        purpose=purpose,
        amount=amount_line,
        pay_date=format_pay_date(pay_date, pay_round),
    )


def restrict_recent(items, since: datetime):
    """Outlook Items.Restrict 로 최근 메일만 필터링. 실패 시 원본 그대로 반환."""
    date_str = since.strftime("%m/%d/%Y %I:%M %p")
    query = f"[ReceivedTime] >= '{date_str}'"
    try:
        return items.Restrict(query)
    except Exception as e:
        logging.warning(f"Restrict 실패({e}) → 전체 순회로 대체합니다.")
        return items


# ============================================================
#                     배치 초안 생성
# ============================================================
def build_batch_draft(outlook, namespace, rnd: Round, entries: list, kind: str = "D") -> bool:
    """
    rnd 차수에 배정된 entries([{"entry_id":...}, ...])를 한 통의 초안으로 묶어 생성.
    kind("D"|"SELR")에 따라 첨부 패턴/금액추출/비용목적이 달라진다 — 두 종류를
    한 통에 섞지 않고 별도 배치로 만든다(2026-09-15: SELR도 D와 동일하게 배치화).
    각 메일을 EntryID 로 다시 열어 첨부 저장 + 금액 추출.
    성공(초안 저장)하면 True, 만들 게 없으면 False.
    """
    pattern    = ATTACHMENT_PATTERN if kind == "D" else ATTACHMENT_PATTERN_SELR
    extract_fn = extract_invoice_amount if kind == "D" else extract_selr_amount
    purpose    = PURPOSE_D if kind == "D" else PURPOSE_SELR

    TEMP_DIR.mkdir(exist_ok=True)
    saved_paths = []
    invoice_amounts = []  # [(invoice_name, amount|None), ...]
    missing = []

    for entry in entries:
        eid = entry["entry_id"]
        try:
            mail = namespace.GetItemFromID(eid)
        except Exception as e:
            logging.warning(f"  · 메일 재오픈 실패(EntryID={eid[:12]}…): {e}")
            missing.append(eid)
            continue

        for att in find_target_attachments(mail, pattern):
            try:
                safe_name = sanitize_filename(att.FileName)
                pdf_path = TEMP_DIR / safe_name
                if pdf_path.exists():
                    pdf_path = TEMP_DIR / f"{pdf_path.stem}_{int(datetime.now().timestamp())}{pdf_path.suffix}"
                att.SaveAsFile(str(pdf_path))
                saved_paths.append(pdf_path)

                inv_name = Path(att.FileName).stem
                amount = extract_fn(pdf_path)
                invoice_amounts.append((inv_name, amount))
                logging.info(
                    f"  · 첨부: {pdf_path.name} | 금액: "
                    f"{format(amount, ',') + '원' if amount is not None else '추출 실패(확인 필요)'}"
                )
            except Exception as e:
                logging.warning(f"  · 첨부 저장 실패({att.FileName}): {e}")

    if not invoice_amounts:
        logging.error("  · 첨부를 하나도 확보하지 못해 초안을 만들지 않습니다.")
        # 임시 파일 정리
        for p in saved_paths:
            try:
                p.unlink()
            except Exception:
                pass
        return False

    invoice_names = [n for n, _ in invoice_amounts]
    if len(invoice_names) == 1:
        subject = SUBJECT_TEMPLATE_SINGLE.format(invoice=invoice_names[0])
    else:
        subject = SUBJECT_TEMPLATE_BATCH.format(count=len(invoice_names), pay_round=rnd.label)

    new_mail = outlook.CreateItem(0)  # 0 = olMailItem
    new_mail.To      = RECIPIENT_ADDRESS
    new_mail.CC      = CC_ADDRESS
    new_mail.Subject = subject
    new_mail.HTMLBody = mail_text_to_html(
        build_body(invoice_amounts, rnd.pay_date, rnd.label, purpose=purpose))
    for p in saved_paths:
        new_mail.Attachments.Add(str(p))

    if DRY_RUN:
        logging.info(
            f"[DRY_RUN] {'발송' if SEND_MODE else '초안'} 생략 — Subject={subject} | 건수={len(invoice_names)}"
        )
        result = False
    elif SEND_MODE:
        new_mail.Send()  # 자동 발송
        logging.info(f"자동 발송 완료 → Subject={subject} | 건수={len(invoice_names)}")
        result = True
    else:
        new_mail.Save()  # 자동 발송하지 않고 Drafts 에 한 통으로 저장
        logging.info(f"초안 저장 완료(검토 후 직접 발송) → Subject={subject}")
        result = True

    if missing:
        logging.warning(f"  · 재오픈 실패 {len(missing)}건은 본 배치에서 누락됨.")

    for p in saved_paths:
        try:
            p.unlink()
        except Exception:
            pass

    return result


# ============================================================
#                        메인 로직
# ============================================================
def process_mails() -> int:
    """발견 → pending 적재 → 발송일 도래분 일괄 초안. 생성한 초안(배치) 수 반환."""
    pythoncom.CoInitialize()
    try:
        outlook   = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        inbox     = namespace.GetDefaultFolder(6)  # 6 = olFolderInbox
        dhl_folder = inbox.Folders["DHL"]

        state = load_state()
        processed = set(state.get("processed_entry_ids", []))
        pending = dict(state.get("pending", {}))  # "{eid}::{kind}" -> {"entry_id","kind","received","subject"}
        pending_entry_ids = {meta["entry_id"] for meta in pending.values()}

        # ── Phase 1: 신규 청구서 발견 → pending 적재 (즉시 초안 X, D/SELR 공통) ──
        items = dhl_folder.Items
        items.Sort("[ReceivedTime]", True)  # 최신순
        since = datetime.now() - timedelta(days=LOOKBACK_DAYS)
        items = restrict_recent(items, since)

        for mail in items:
            try:
                if getattr(mail, "Class", None) != 43:  # 43 = olMail
                    continue
            except Exception:
                continue

            entry_id = getattr(mail, "EntryID", None)
            if not entry_id or entry_id in processed or entry_id in pending_entry_ids:
                continue

            if get_sender_smtp(mail) != SENDER_ADDRESS.lower():
                continue

            subject = getattr(mail, "Subject", "") or ""
            subject_flat = re.sub(r'\s+', '', subject)  # '납부 촉구서' == '납부촉구서'
            if any(kw and re.sub(r'\s+', '', kw) in subject_flat
                   for kw in EXCLUDE_SUBJECT_KEYWORDS):
                logging.info(f"제외 키워드 매칭 → 스킵(초안 미생성): {subject!r}")
                processed.add(entry_id)
                continue

            d_atts = find_target_attachments(mail, ATTACHMENT_PATTERN)
            selr_atts = find_target_attachments(mail, ATTACHMENT_PATTERN_SELR)

            if not d_atts and not selr_atts:
                logging.info(f"발신자 일치, 'D*/SELR*.pdf' 첨부 없음 → 스킵: {subject!r}")
                processed.add(entry_id)
                continue

            rt = mail.ReceivedTime
            received_dt = datetime(rt.year, rt.month, rt.day, rt.hour, rt.minute, rt.second)
            received_iso = received_dt.isoformat(timespec="seconds")
            rnd = assign_round(received_dt.date())

            # D(수수료)/SELR(운송료)는 비용목적이 달라 같은 통에 섞지 않고
            # kind 별로 각각 pending 등록 → 차수 발송일(D-2)에 kind 단위로 배치 처리.
            if d_atts:
                pending[f"{entry_id}::D"] = {
                    "entry_id": entry_id, "kind": "D",
                    "received": received_iso, "subject": subject,
                }
                logging.info(
                    f"발견→대기 등록(수수료) [{received_dt:%Y-%m-%d %H:%M}] {subject!r} "
                    f"→ {rnd.label} 배치 (발송예정 {rnd.send_date:%Y-%m-%d} / 앵커 {rnd.pay_date:%Y-%m-%d})"
                )
            if selr_atts:
                pending[f"{entry_id}::SELR"] = {
                    "entry_id": entry_id, "kind": "SELR",
                    "received": received_iso, "subject": subject,
                }
                logging.info(
                    f"발견→대기 등록(운송료) [{received_dt:%Y-%m-%d %H:%M}] {subject!r} "
                    f"→ {rnd.label} 배치 (발송예정 {rnd.send_date:%Y-%m-%d} / 앵커 {rnd.pay_date:%Y-%m-%d})"
                )

        # ── Phase 2: pending 을 (차수, kind) 별로 묶고, 발송일(D-2) 도래분 일괄 처리 ──
        now = datetime.now()
        today = now.date()
        groups: dict = {}  # key -> {"round": Round, "kind": str, "keys": [...]}
        for key, meta in pending.items():
            try:
                r_date = datetime.fromisoformat(meta["received"]).date()
            except Exception:
                r_date = today
            rnd = assign_round(r_date)
            gkey = (rnd.pay_date.isoformat(), rnd.label, meta["kind"])
            groups.setdefault(gkey, {"round": rnd, "kind": meta["kind"], "keys": []})["keys"].append(key)

        drafts_created = 0
        for _, g in sorted(groups.items(), key=lambda kv: (kv[1]["round"].send_date, kv[1]["kind"])):
            rnd, kind, keys = g["round"], g["kind"], g["keys"]

            # 발송 조건: 발송일(D-2)을 이미 지났으면 즉시(catch-up);
            #           당일이면 SEND_AT_HOUR 가드(미설정 시 즉시).
            due = False
            if rnd.send_date < today:
                due = True
            elif rnd.send_date == today:
                due = (SEND_AT_HOUR is None) or (now.hour >= SEND_AT_HOUR)

            if not due:
                if rnd.send_date == today:
                    logging.info(
                        f"대기(시각): {rnd.label} {kind} 배치 {len(keys)}건 — 오늘이 발송일(D-2)이나 "
                        f"{SEND_AT_HOUR}시 이전(현재 {now:%H:%M}). 그 이후 실행에서 처리."
                    )
                else:
                    logging.info(
                        f"대기 유지: {rnd.label} {kind} 배치 {len(keys)}건 "
                        f"— 발송 예정 {rnd.send_date:%Y-%m-%d}(D-2), 윈도우 끝 {rnd.window_end:%Y-%m-%d}(D-3)"
                    )
                continue

            # 캘린더 게이트: 해당 월 Finance Calendar 가 캐시에 있어야 앵커가 확정됨.
            #   없으면(= 다음 달 메일 미도착) 발송 보류하고 계속 모아둔다.
            cal_ok = (not REQUIRE_CALENDAR_MONTH) or _calendar_has_month(rnd.year, rnd.month)
            overdue_force = (
                FORCE_SEND_IF_OVERDUE_DAYS is not None
                and not cal_ok
                and (today - rnd.send_date).days >= FORCE_SEND_IF_OVERDUE_DAYS
            )
            if not cal_ok and not overdue_force:
                logging.info(
                    f"대기(캘린더): {rnd.label} {kind} 배치 {len(keys)}건 — "
                    f"{rnd.year}-{rnd.month:02d} Finance Calendar 미도착(앵커 미확정). "
                    f"해당 월 데이터가 캐시에 들어오면 자동 발송."
                )
                continue
            if overdue_force:
                logging.warning(
                    f"강제 발송: {rnd.year}-{rnd.month:02d} Finance Calendar 미도착이나 "
                    f"발송일({rnd.send_date:%Y-%m-%d})이 {FORCE_SEND_IF_OVERDUE_DAYS}일 초과 → "
                    "휴리스틱 날짜로 진행(날짜 정확도 확인 필요)."
                )

            action = "발송" if (SEND_MODE and not DRY_RUN) else "초안 생성"
            logging.info(
                f"발송일 도래: {rnd.label} {kind} 배치 {len(keys)}건 "
                f"(발송일 {rnd.send_date:%Y-%m-%d} ≤ 오늘 {today:%Y-%m-%d}) → 일괄 {action}"
            )
            entries = [pending[k] for k in keys]
            created = build_batch_draft(outlook, namespace, rnd, entries, kind)
            if created and not DRY_RUN:
                for k in keys:
                    meta = pending.pop(k, None)
                    if meta:
                        eid = meta["entry_id"]
                        if not any(v["entry_id"] == eid for v in pending.values()):
                            processed.add(eid)
                drafts_created += 1

        if not DRY_RUN:
            state["processed_entry_ids"] = sorted(processed)
            state["pending"] = pending
            save_state(state)

        return drafts_created

    finally:
        pythoncom.CoUninitialize()


def _print_schedule(start_year: int, start_month: int, n_months: int) -> None:
    """차수별 앵커/발송일(D-2)/윈도우([직전 D-2 … 당 D-3]) 출력."""
    rounds = iter_rounds(start_year, start_month, n_months)
    print(f"{'차수':<6}{'앵커(기준일)':<14}{'발송일 D-2':<12}{'윈도우(수신일 범위)':<26}")
    print("-" * 64)
    prev_send = None
    for r in rounds:
        win_start = prev_send if prev_send else "(직전 차수 D-2)"
        ws = win_start if isinstance(win_start, str) else win_start.strftime("%Y-%m-%d")
        print(f"{r.label:<6}{r.pay_date.strftime('%Y-%m-%d'):<14}"
              f"{r.send_date.strftime('%Y-%m-%d'):<12}"
              f"[{ws} … {r.window_end:%Y-%m-%d}]")
        prev_send = r.send_date


def main() -> int:
    setup_logging()

    # 스케줄 확인:  python dhl_forwarder.py --schedule [YYYY-MM] [months]
    if len(sys.argv) >= 2 and sys.argv[1] == "--schedule":
        if len(sys.argv) >= 3:
            y, m = map(int, sys.argv[2].split("-"))
        else:
            t = date.today(); y, m = t.year, t.month
        months = int(sys.argv[3]) if len(sys.argv) >= 4 else 4
        _print_schedule(y, m, months)
        return 0

    # 배정 확인:  python dhl_forwarder.py --assign YYYY-MM-DD
    if len(sys.argv) >= 3 and sys.argv[1] == "--assign":
        d = date.fromisoformat(sys.argv[2])
        r = assign_round(d)
        print(f"수신일 {d} → {r.label} 배치 | 발송일(D-2) {r.send_date} | "
              f"앵커 {r.pay_date} | 윈도우 끝(D-3) {r.window_end}")
        return 0

    logging.info("=" * 60)
    logging.info(f"DHL Forwarder(배치) 시작 (LOOKBACK_DAYS={LOOKBACK_DAYS}, DRY_RUN={DRY_RUN})")
    try:
        n = process_mails()
        logging.info(f"DHL Forwarder 종료. 생성한 배치 초안 수: {n}")
        return 0
    except Exception:
        logging.error("처리 중 예외 발생:\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
