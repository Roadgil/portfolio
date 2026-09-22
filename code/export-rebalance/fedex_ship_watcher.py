# -*- coding: utf-8 -*-
"""
fedex_ship_watcher.py - FedEx 픽업 어레인지 자동화

Rebalance TO/RMA 파이프라인(rebalance_watcher.py)의 마지막 퍼즐. CI 저장까지
자동으로 되는 것에 이어, FedEx 발송 예약(픽업 어레인지)을 자동으로 넣고
**요약 보기 화면까지** 간 뒤 사람이 최종 확정만 누르는 구조다(2026-08-25
사용자 지시: "요약보기까지 눌러준 상태까지만"). 최종 생성/발송은 되돌릴 수
없는 지점이라 절대 자동으로 누르지 않는다.

전체 흐름(2026-08-24~25 사용자 지시 + 실측 검증):
  1. https://www.fedex.com/ko-kr/tracking.html 접속(공유 Edge의 새 탭, 오라클
     탭을 열지 않는다 - get_fedex_driver)
  2. 상단 "등록/로그인" -> 드롭다운 "로그인" (쿠키 배너=Usercentrics 섀도우
     DOM이라 JS로 직접 닫는다 - 안 닫으면 모든 클릭이 가로채진다)
  3. ID/PW 기입 후 로그인(성공 판정: 헤더 #fxg-dropdown-signIn이 계정명으로
     바뀜. 이미 로그인돼 있으면 건너뜀)
  4. 발송 - 지금 발송 -> Ship Manager(shippingplus) 발송물 생성 화면
  5. 수취인: `Rebalance Invoice form_Ship from Korea.xlsx` 국가 시트의 SHIP TO
     담당자를 주소록에서 검색(돋보기 옆 '저장된 연락처' 버튼 -> 다이얼로그
     검색 -> '추가'). 홍콩은 Nick이 두 개라 'New' 행 우선.
  6. 자체 포장재 + 용마 회신 제원(박스별 무게/61*47*8 같은 크기) 기입
  7. 발송날짜/서비스: 실행이 컷오프(SERVICE_CUTOFF_HOUR, 현재 13시) 이전이면
     당일, 이후면 다음 영업일(토일/
     공휴일 제외 - FEDEX_HOLIDAYS는 매년 갱신). 도착일 최단, 같으면 최저가.
  8. 패키지 내용물: 발송 용도 '상업용'(RMA는 '수리 및 반환'), 물품 등록(설명/HS 코드 **앞 6자리** -
     자동완성 옵션 "9018.90" 점 표기를 점 빼고 매칭/순중량/수량/세관 신고
     금액/제조 국가 - **가격·원산지·HS는 수출신고실적에서 TO#로 조회**,
     사용자 지시), 상업송장은 '직접 생성한 송장을 업로드'로 rebalance가 만든
     최종 CI PDF를 전자통관문서로 첨부.
  9. 픽업/방문 접수: '픽업 예약 진행' 선택(폼 세부는 실제 케이스에서 확정).
 10. 알림 건너뜀 -> 청구서 세부정보: 운송비 청구 대상='수취인', FEDEX
     고객번호=Address 시트 H열(EMEA는 FBC/FBS 접두어로 구분, RMA는 WAY 번호).
 11. **요약 보기 클릭까지** 하고 멈춘다 - 알림 초안을 남기고 사람이 요약을
     확인한 뒤 최종 생성을 누른다.

라벨이 나오면(사람이 확정한 뒤):
  python fedex_ship_watcher.py label <TO#> --label <라벨PDF> [--send]
  -> 임시보관함의 기존 용마 답장 초안(CI 첨부돼 있는 것)에 라벨을 붙여 넣는다.
     --send를 붙이면 바로 발송, 없으면 초안 갱신만(외부 발송이라 기본 보수적).

라벨의 Tracking 번호가 배정되면(최종 생성 직후):
  python fedex_ship_watcher.py track <TO#> <Tracking번호>
  -> 1) 수출신고실적의 B/L번호 칸 기입(백업 후)
     2) SharePoint APAC Stock Movements의 해당 TO 행들에 Tracking Number 기입
        (내부 필드명은 리스트에서 자동 조회, 기입 후 재조회 검증)
     3) (2026-09-11 추가) WAY(미국)향이면 오라클 Manage Shipments의 해당
        Shipment(수출신고실적 Delivery Number)에서 Tracking # 필드도 같은
        번호로 기입(oracle_shipment_tracking.py). RMA 포함, Purpose는 안 가림 -
        수출신고실적 Destination=WAY로만 판단. 오라클 기입 실패는 SharePoint/
        엑셀을 막지 않고 알림 메일만 남긴다. 백필(8/15 이후 7건: 9973476/
        9974788/9976051/9976055/9977111/9978326/9981240)로 실측 검증 완료 -
        Additional Information 섹션은 기본 접힘 상태라 왼쪽 삼각형(disclosure)
        좌표를 클릭해 펼쳐야 Tracking # 필드가 보인다(텍스트 자체를 눌러도 안
        열림 - oracle_shipment_tracking._fill_tracking_number 참고).
  2026-08-25 사용자 지시. 7873245/876034602894로 실데이터 검증 완료.

**자동 트리거(2026-08-25 사용자 지시: "CI 초안이 작성되면서 바로 실행")**:
  rebalance_watcher의 파이프라인 맨 끝(_run_rebalance_pipeline 완료 직후)에서
  _start_fedex_arrangement()가 이 파일의 arrange_fedex_pickup()을 직접 호출한다
  - 상주 감시자/폴링 없음. 용마 회신 원본(reply_entry_id)에서 제원을 파싱하고,
  CI PDF 경로도 그대로 넘겨준다. 요약 보기 직전까지 자동이며 알림 초안이 온다.
  RMA 건도 2026-09-15부터 동일하게 자동 진행한다(발송 용도만 '수리 및 반환'로
  다르게 선택) - 그 전까지는 이 값이 미확정이라 알림만 남기고 멈췄었다.

실행 방법(수동 실행이 필요할 때):
  python fedex_ship_watcher.py contact ILH          # 엑셀 담당자 조회(브라우저 없음)
  python fedex_ship_watcher.py dims "<용마 회신>"    # 제원 파서 테스트
  python fedex_ship_watcher.py login                # 1~3단계만
  python fedex_ship_watcher.py ship ILH --to 7873245 --boxes "[{'weight':0.81,'L':61,'W':47,'H':8}]"
      [--stop login|shipnow|address|package|service|contents|pickup|billing]
  # --boxes를 빼면 --to의 용마 회신을 찾아 제원을 자동 추출한다(자동 트리거와 동일).
  # 제원을 못 구하면 목업으로 진행하지 않고 **중단**한다(2026-08-27).

2026-08-27 라이브 2건으로 **최종 생성까지** 검증 완료:
  - KRP-ILH 7877405: 2박스 5.56kg, IE ₩180,200, AWB 876344011940, 픽업 JSPA2113
  - KRP-WAY 7876545: 2박스 4.2kg, IP ₩286,150, AWB 876344516235(픽업 별도 안 잡음)
  두 건 다 라벨 다운로드 -> 용마 답장(CI 첨부분)에 라벨 붙여 발송 -> 수출신고실적
  B/L번호 + SharePoint TrackingNumber 기입까지 끝냈다.

같은 날 확정된 규칙(사용자 지시):
  - 품목 설명에는 항상 "Medical Device Part"를 붙인다(ITEM_DESC_SUFFIX)
  - 이미 그날 픽업이 잡혀 있으면 픽업을 또 잡지 않는다(--no-pickup =
    '운송장만 생성 하고 픽업 예약은 별도로 진행')
  - CI가 여러 장인 배송은 한 PDF로 합쳐 올린다(상업송장 슬롯이 1개)
  - 가격/원산지/HS/수량은 **CI PDF가 정답**이다(수출신고실적은 대조·경고만)

아직 남은 일:
  - 2026-09-09부터 rebalance_watcher 자동 트리거도 최종 생성까지 간다
    (confirm=True + _post_confirm_followups). 그전에는 요약 보기까지만 했다.
    무인 실행으로 실제 발송물을 만들지는 사용자 판단이 필요한 영역이라 그대로 뒀다.
  - (해결됨, 2026-09-15) RMA 건의 '발송 용도' 규칙 - '수리 및 반환'으로 확정,
    자동 트리거 대상에 포함됨

2026-08-25 재검증 완료(7873245 예시, 실제 생성은 안 함):
  - 7단계 서비스 자동 선택: 당일 발송(11:43 < 12시 컷오프) -> 최단 도착
    8/26 중 최저가 IP ₩187,790 자동 선택 확인
  - 8단계 물품 등록: HS 9018.90(6자리 자동완성 선택), 순중량 0.81, 금액
    ₩1,404,759, 원산지 Mexico, CI PDF 업로드까지 확인. 주의: 순중량에 0을
    넣으면 검증에 걸려 다이얼로그가 안 닫힌다(처음부터 실제값 필수).
  - 9단계 픽업 폼: '픽업 예약 진행' 선택 시 픽업 날짜(=발송날짜)/가장 이른
    시간(12:00)/가장 늦은 시간(18:00) select가 기본값으로 채워짐 - 그대로 사용.
  - 10단계 청구서: 운송비 청구 대상 '수취인' 변경 + FEDEX 고객번호 **2칸**
    (운송비/관세)에 Address 시트 번호 기입 확인. 주의: 라벨 텍스트에
    non-breaking space가 섞여 'FEDEX 고객번호' 완전 매칭은 안 된다 -
    '고객번호'로 검색하고 FEDEX 여부는 파이썬에서 확인한다.
  - 요약 보기 클릭 -> "발송물을 검토합니다" 화면(완료 버튼 존재) 확인 후 정지.
"""

from __future__ import annotations

import os
import tempfile
import re
import sys
import glob
import json
import time
import shutil
import argparse
from datetime import datetime

# 같은 Edge 인스턴스(디버그 포트 공유)를 쓰는 기존 자동화들의 공통 인프라 재사용 -
# FedEx 페이지도 오라클/SharePoint와 같은 브라우저 안의 다른 탭/사이트일 뿐이라
# ensure_edge_running/get_oracle_driver_isolated 조합을 그대로 쓴다.
ICBL_DIR = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\10. 수입\인천관세법인 C.I 확인"
)
sys.path.insert(0, ICBL_DIR)
from icbl_ci_watcher import (  # noqa: E402
    ensure_edge_running,
    close_driver,
    is_session_dead_error,
    exc_detail,
    wait_or_sleep,
    element_present,
    _wait_find,
    _resolve_edge_target,
    acquire_oracle_lock,
    release_oracle_lock,
    set_edge_owner,
)

# 2026-09-18: 이 프로세스는 자기 전용 Edge(포트/프로필)를 쓴다.
set_edge_owner("fedex_ship_watcher")

ROOT = os.path.dirname(__file__)
LOG_PATH = os.path.join(ROOT, "fedex_ship_watcher.log")
LOCK_FILE_PATH = os.path.join(ROOT, "_fedex_ship.lock")

FEDEX_TRACKING_URL = "https://www.fedex.com/ko-kr/tracking.html"

# 2026-08-24 사용자 제공 계정. 비밀번호는 코드에 하드코딩하지 않고 환경변수로 받는다
# (2026-09-22, 포트폴리오 공개 저장소에 평문 노출됐던 사고 이후 수정).
# setx FEDEX_PASSWORD "실제비밀번호" 로 1회 등록해두면 작업 스케줄러 실행 시에도 읽힌다.
FEDEX_USER_ID = "sckorea1234"
FEDEX_PASSWORD = os.environ["FEDEX_PASSWORD"]

# 국가별 담당자가 적힌 엑셀(2026-08-24 사용자 지정 경로).
CONTACT_TEMPLATE_PATH = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\12. 수출\Rebalance Invoice form_Ship from Korea.xlsx"
)

# CI 실제값(단가/금액/원산지/HS) 조회용 수출신고실적 - rebalance_watcher.py가
# append하는 그 파일. 2026-08-25 사용자 지시: FedEx 물품 등록의 가격/원산지는
# CI(=수출신고실적에 기입된 값)를 참조한다.
EXPORT_DECLARATION_PATH = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\12. 수출\수출신고실적20260126~.xlsx"
)

# 최종 CI가 저장되는 폴더(rebalance_watcher.save_final_invoice_to_ci_folder).
# FedEx 상업송장 업로드(전자통관문서)에 이 PDF를 쓴다.
CI_FOLDER_PATH = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\12. 수출\CI"
)

# 서비스 선택 규칙(2026-08-25 사용자 지시):
# - 코드 실행 시각이 오후 1시 이전이면 발송날짜=당일, 이후면 다음 영업일.
# - 도착일은 최대한 빠른 날, 같은 도착일이면 최저가.
# - 도착일을 아예 계산 안 해주는 목적지가 있음(2026-08-25 ILH/홍콩 실측:
#   FedEx가 "--"/undefined 표시) - 그 경우 **전체 후보 중 최저가**를 선택한다
#   (사용자 확인: "도착일을 계산 안해주는 경우는 제일 싼걸로").
# - 토/일 제외(영업일 기준). FedEx 날짜 옵션 자체가 영업일만 나오므로 주말은
#   자동 제외된다. 휴일은 아래 목록을 매년 업데이트한다(공휴일에 픽업/발송 불가).
FEDEX_HOLIDAYS = {
    # ---- 2026년 대한민국 공휴일(매년 사용자가 확인/갱신할 것) ----
    "2026-01-01",   # 신정
    "2026-02-16", "2026-02-17", "2026-02-18",   # 설날(전날/당일/다음날)
    "2026-03-01",   # 삼일절
    "2026-05-05",   # 어린이날
    "2026-06-06",   # 현충일
    "2026-08-15",   # 광복절
    "2026-09-24", "2026-09-25", "2026-09-26",   # 추석(전날/당일/다음날)
    "2026-10-03",   # 개천절
    "2026-10-09",   # 한글날
    "2026-12-25",   # 성탄절
}
SERVICE_CUTOFF_HOUR = 13   # 이 시각 이전이면 당일 발송, 이후면 다음 영업일(2026-08-25 사용자 지시: 12시->13시)

# ---- 픽업 시간대 (2026-09-04 사용자 지시) ----
# "용마 픽업 마감은 17시야 그래서 1시 이후면 페덱스에서 예약할때 13시부터
#  16시30분 사이에 잡도록해야해"
#
# 지금까지 이 값들을 **읽어서 로그만 찍고 설정하지 않았다** - FedEx 기본값이
# 그대로 들어갔고, 실측(2026-08-27 TO 7876705)에서 픽업 창이 11:30~18:00으로
# 잡혔다. 18시는 용마 마감을 한 시간 넘긴 시각이라 그 창으로는 트럭이 이미 떠난
# 뒤다. 그래서 이제 실제로 선택한다.
YONGMA_PICKUP_DEADLINE_HOUR = 17      # 용마 픽업 마감
PICKUP_LATEST_MIN = 16 * 60 + 30      # 가장 늦은 시간 = 16:30 (마감 30분 전)
PICKUP_AFTERNOON_EARLIEST_MIN = 13 * 60   # 13시 이후 실행이면 가장 이른 시간 = 13:00
PICKUP_NEXTDAY_EARLIEST_MIN = 8 * 60      # 픽업이 다음날이면 08:00부터

# 수출신고실적의 원산지 2자 코드 -> FedEx 제조국 select의 영문 옵션명.
# (실측: 옵션은 "South Korea"/"Mexico"처럼 영문 국가명이다)
ORIGIN_CODE_TO_FEDEX = {
    "MX": "Mexico", "KR": "South Korea", "CN": "China", "US": "United States",
    "JP": "Japan", "HK": "Hong Kong SAR, China", "TW": "Taiwan",
    "SG": "Singapore", "MY": "Malaysia", "TH": "Thailand", "VN": "Vietnam",
    "PH": "Philippines", "ID": "Indonesia", "IN": "India",
    "DE": "Germany", "DK": "Denmark", "CH": "Switzerland", "GB": "United Kingdom",
    "FR": "France", "IT": "Italy", "NL": "Netherlands", "BE": "Belgium",
    "AT": "Austria", "SE": "Sweden", "FI": "Finland", "NO": "Norway",
    "PT": "Portugal", "PL": "Poland", "CZ": "Czech Republic", "HU": "Hungary",
    "GR": "Greece", "IE": "Ireland", "ES": "Spain", "TR": "Turkey",
    "RU": "Russia", "CA": "Canada", "BR": "Brazil", "AU": "Australia",
    "NZ": "New Zealand", "ZA": "South Africa", "AE": "United Arab Emirates",
    "SA": "Saudi Arabia", "IL": "Israel", "AR": "Argentina", "CL": "Chile",
}

# FedEx 물품 HS 코드는 앞 6자리만 쓴다(2026-08-25 사용자 지시: "9000은 없을거야
# 뒤에 4자리는 빼면 될듯" - 실측: 자동완성 옵션도 "9018.90" 6자리 점 표기).
HTS_DIGITS_FOR_FEDEX = 6

# 주소록에서 연락처를 고른 뒤 수취인 상세 정보가 채워질 때까지 기다리는 한도.
# 2026-09-04 추가 - 단발 확인이라 화면이 느린 회차에 그대로 실패했다.
RECIPIENT_FILL_TIMEOUT_SEC = 45


# 2026-09-04 사용자 지시: "HTS/HS code 없으면 901890/9018909000으로 해줘".
# 수입 이력에 없는 파트의 기본 HS code. FedEx는 앞 6자리(901890)만 쓴다
# (HTS_DIGITS_FOR_FEDEX). 2026-08-05에는 이 값이 특정 건 한정이라 범용
# 기본값으로 쓰지 말라고 정리했었는데, 이번에 범용 기본값으로 확정됐다.
HTS_CODE_FALLBACK = "9018909000"


# rebalance_watcher.py와 같은 매핑(RBS/FBS는 FBC로 통일, WAY는 US 시트, RMA 3종은
# FA LAB 하나로 모은다 - 이 자동화도 RMA 건 발송을 같이 맡게 될 것을 대비).
COUNTRY_SHEET_MAP = {
    "AUP": "AUP",
    "ILH": "ILH",
    "CHP": "CHP",
    "JPP": "JPP",
    "WAY": "US",
    "FBS": "FBC",
    "FBC": "FBC",
    "FA LAB": "FA LAB",
}

ALERT_MAIL_TO = "yoongil.chae@candelamedical.com"

# 홍콩(ILH) 주소록에는 "Nick"이 두 개다 - 결과가 여러 개일 때 이 키워드가 들어간
# 행을 우선 고른다(2026-08-24 사용자 지시: "홍콩은 Nick이 두개 New로 진행").
PREFER_RESULT_KEYWORD = "New"

# ==============================================================
# 국가코드 정규화 (rebalance_watcher.normalize_destination와 같은 규칙)
# ==============================================================
# 사람이 부르는 이름/트리거 메일 표기를 시트 매핑 키로 맞춘다.
# - "US"/"USA"는 내부 코드 WAY(미국)로 통일한다(COUNTRY_SHEET_MAP이 WAY를 쓴다).
# - RMA 3종(FA LAB/Refurb Center/PURCHASING)은 전부 본사 행이라 FA LAB 하나로
#   모은다 - 인보이스 쪽(rebalance_watcher.py)과 같은 방식이다.
_RMA_DEST_PATTERN = r"FA\s*LAB|Refurb\s*Cent(?:er|re)|Purchasing"


def normalize_country_code(raw: str) -> str:
    # 트리거 메일은 "KRP - AUP"/"KRP-FA LAB"처럼 KRP 접두어를 붙여 온다.
    s = re.sub(r"^KRP\s*-?\s*", "", re.sub(r"\s+", " ", str(raw or "").strip()),
               flags=re.IGNORECASE)
    if re.fullmatch(_RMA_DEST_PATTERN, s, re.IGNORECASE):
        return "FA LAB"
    u = s.upper()
    return {"US": "WAY", "USA": "WAY", "UNITED STATES": "WAY"}.get(u, u)

LOGIN_SETTLE_TIMEOUT_SEC = 20   # 로그인 후 내비게이션이 바뀔 때까지의 한도


def log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        # 작업 스케줄러/cp949 콘솔에서는 '₩' 같은 문자를 못 찍는다. 로그 파일은
        # utf-8이라 멀쩡하므로, 화면 출력 때문에 자동화가 죽지 않게 대체 출력한다
        # (2026-08-27: 서비스 요금 로그에서 UnicodeEncodeError로 중단됐다).
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"))
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def send_alert(subject: str, body: str):
    """기존 자동화들과 동일 - 알림은 초안만 저장한다."""
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = ALERT_MAIL_TO
    mail.Subject = subject
    mail.Body = body
    mail.Save()
    log(f"알림 메일 초안 저장: {subject}")


def _save_diag(driver, tag: str) -> str:
    """추측하지 말고 그 순간 화면을 남긴다(rebalance_watcher의 _diag_ 패턴)."""
    path = os.path.join(ROOT, f"_diag_fedex_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    try:
        driver.save_screenshot(path)
        log(f"  [진단] 화면 캡처: {os.path.basename(path)} (URL: {driver.current_url})")
    except Exception as e:
        log(f"  [진단] 스크린샷 실패: {e}")
    return path


def _acquire_singleton_lock():
    """rebalance_watcher/pick_release_watcher와 같은 파일 락. 겹치는 실행 방지."""
    return _acquire_lock_file(LOCK_FILE_PATH)


def _acquire_lock_file(path: str):
    """지정 경로의 파일 락 획득(실패 시 None). watch 감시자 전용 락 등 공용."""
    import msvcrt
    f = open(path, "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


# ==============================================================
# 5단계 준비) 엑셀에서 국가별 담당자 읽기 (완전 구현 - 바로 테스트 가능)
# ==============================================================
def lookup_ship_to_contact(country_code: str) -> dict:
    """`Rebalance Invoice form_Ship from Korea.xlsx`의 국가 시트 SHIP TO 블록(M열,
    10~19행)에서 담당자 정보를 뽑는다.

    시트마다 줄 구성이 조금씩 다르지만 공통 구조는
      [회사명, 주소..., 국가, **담당자 이름**, 전화, 이메일]
    이다. 그래서 뒤에서부터 이메일(@) -> 전화(숫자/+/-/( ) -> 이름 순으로 뗀다.
    이 판독 방식은 rebalance_watcher.get_country_contact_lines()에서 실측으로
    검증된 것("이름/이메일/전화" 순서, US 시트로 검증)과 같다.

    주소록 검색창에 넣을 검색어는 '이름' 하나이므로:
    - US 시트처럼 "Attn: Bob Lazaros"면 접두어를 뗀다.
    - FA LAB 시트처럼 "Zachery Lee, Debra Gilbert"로 두 명이 한 줄에 있으면
      **첫 사람만** 검색어로 쓴다(주소록은 사람 단위라고 가정 - 두 명을 한 번에
      검색하면 못 찾는다. 실측에서 어긋나면 여기를 고친다).

    반환: {"name", "search_name", "email", "phone", "sheet", "all_lines"}"""
    import openpyxl

    country_code = normalize_country_code(country_code)
    sheet_name = COUNTRY_SHEET_MAP.get(country_code)
    if sheet_name is None:
        raise ValueError(f"국가 코드 {country_code}에 해당하는 시트 매핑이 없음")

    wb = openpyxl.load_workbook(CONTACT_TEMPLATE_PATH, data_only=True, read_only=True)
    if sheet_name not in wb.sheetnames:
        raise ValueError(f"'{os.path.basename(CONTACT_TEMPLATE_PATH)}'에 '{sheet_name}' 시트가 없음")
    ws = wb[sheet_name]

    lines = []
    for row in range(10, 20):          # SHIP TO 라벨이 M9, 내용은 10행부터
        v = ws.cell(row=row, column=13).value   # M열=13
        if v is None or str(v).strip() == "":
            continue
        s = str(v).strip()
        if s.upper().startswith("PAYMENT TERMS"):
            break
        lines.append(s)
    wb.close()
    if not lines:
        raise ValueError(f"{sheet_name} 시트 SHIP TO 블록을 못 읽음")

    # 뒤에서부터 이메일/전화 줄이 몇 개든(FA LAB 시트는 이메일 두 줄) 계속 떼고,
    # 더 이상 아니면 그 자리의 줄이 담당자 이름이다.
    def _is_phone(s: str) -> bool:
        return bool(re.fullmatch(r"[\d\s()+\-/#.]+", s)) and any(c.isdigit() for c in s)

    def _is_email(s: str) -> bool:
        return "@" in s and " " not in s

    email = phone = None
    rest = list(lines)
    while rest:
        last = rest[-1].strip()
        if _is_email(last):
            email = rest.pop().strip()
        elif _is_phone(last):
            phone = last
            rest.pop()
        else:
            break

    name = rest[-1].strip() if rest else ""
    if not name or "@" in name:
        raise ValueError(f"{sheet_name} 시트에서 담당자 이름을 못 찾음(줄들: {lines})")
    search_name = re.sub(r"^Attn\s*:\s*", "", name, flags=re.IGNORECASE)
    # 여러 명이 한 줄에 있으면 첫 사람만(위 docstring 참고).
    multi = None
    if "," in search_name:
        multi = [p.strip() for p in search_name.split(",") if p.strip()]
        search_name = multi[0]

    result = {
        "name": name,
        "search_name": search_name.strip(),
        "email": email,
        "phone": phone,
        "sheet": sheet_name,
        "all_lines": lines,
    }
    log(f"[엑셀] {country_code}(시트 {sheet_name}) 담당자: "
        f"name={result['name']!r}, search={result['search_name']!r}, "
        f"email={email!r}, phone={phone!r}"
        + (f", 추가 인원={multi[1:]}" if multi else ""))
    return result


# ==============================================================
# 6단계 준비) 용마 회신에서 제원(박스 무게/크기) 파싱 (골격 - 실제 회신으로 다듬기)
# ==============================================================
# 용마 회신은 자유서식이다(rebalance_watcher YONGMA_LOCATION_PATTERN 주석 참고).
# 위치정보("파트넘버 로케이터 수량EA")는 이미 거기서 파싱하니, 여기는 그 밖의
# **박스 물리 정보**만 뽑는다. 아래 정규식은 흔한 표기 3종에 대한 최소 커버리지며,
# 실제 회신을 몇 건 모아 보고 반드시 확장할 것:
#   크기: "50x40x30cm" / "500 X 400 X 300 mm" / "50*40*30"
#   무게: "12kg" / "12.5 KG" / "12 키로"
#   박스 수: "박스 2개" / "BOX 2" / "2 boxes"
_BOX_SIZE_PATTERN = re.compile(
    r"(?P<l>\d{1,4})\s*[xX×*]\s*(?P<w>\d{1,4})\s*[xX×*]\s*(?P<h>\d{1,4})\s*(?P<unit>cm|mm|CM|MM)?")
_WEIGHT_PATTERN = re.compile(r"(?P<w>\d+(?:\.\d+)?)\s*(?:kg|KG|Kg|키로)")
# 박스 수는 어느 쪽 순서든 온다: "2 boxes" / "박스 2개" / "BOX 2" - 둘 다 본다.
# 2026-09-16 실측 버그 수정: \s*는 개행도 건너뛰어서 "FA LAB : 2box\n\n58 X 55
# X 51..."처럼 목적지별로 구간을 나눠 보낸 RMA 회신(TO 7881992)에서 "box" 뒤
# 개행 두 줄 너머의 치수 첫 숫자("58")까지 "박스 58개"로 잘못 붙어 읽혔다
# (n_boxes가 4가 아니라 60으로 계산됨 - 마지막 박스 값이 60개 가까이 복제될
# 뻔했다). 같은 줄 안의 공백/탭만 허용하도록 [ \t]*로 좁혀서 줄 경계를 넘지
# 않게 한다.
_BOX_COUNT_PATTERNS = (
    re.compile(r"(?P<n>\d+)[ \t]*(?:박스|box)", re.IGNORECASE),
    re.compile(r"(?:박스|box)[ \t]*(?P<n>\d+)[ \t]*개?", re.IGNORECASE),
)


def _find_yongma_reply_mail(to_number: str):
    """용마 폴더에서 이 TO#의 회신 **메일 아이템**을 돌려준다(없으면 None).

    주의(2026-09-04 실측): Outlook COM은 .Items를 접근할 때마다 새 컬렉션을
    주기 때문에 `folder.Items.Sort(...)` 뒤 `folder.Items.Item(i)`로 쓰면
    정렬이 풀린다 - 한 번만 바인딩해서 쓴다."""
    import win32com.client

    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    inbox = ns.GetDefaultFolder(6)
    op = next((f for f in inbox.Folders if str(f.Name).strip() == "Operation"), None)
    if op is None:
        return None
    yongma = next((f for f in op.Folders if str(f.Name).strip() == "Yongma"), None)
    if yongma is None:
        return None
    items = yongma.Items
    items.Sort("[ReceivedTime]", True)
    for i in range(1, min(items.Count, 100) + 1):
        try:
            mail = items.Item(i)
            if getattr(mail, "Class", None) != 43:
                continue
            if str(to_number) in str(mail.Subject or ""):
                return mail
        except Exception:
            continue
    return None


def _send_as_fresh_reply(to_number, draft, subject: str, label_name: str) -> None:
    """인라인 답장이라 못 보낸 초안을, 원본에서 만든 새 답장으로 대신 보낸다."""
    original = _find_yongma_reply_mail(to_number)
    if original is None:
        raise RuntimeError(
            f"인라인 초안을 대신할 원본 용마 회신을 못 찾음(TO {to_number}) - "
            f"임시보관함의 '{subject}' 초안을 직접 보내주세요")

    tmp = os.path.join(tempfile.gettempdir(), f"_yongma_reply_{to_number}")
    os.makedirs(tmp, exist_ok=True)
    saved = []
    for k in range(draft.Attachments.Count):
        a = draft.Attachments.Item(k + 1)
        name = str(a.FileName)
        # 서명 이미지는 새 답장에도 서명으로 다시 들어가므로 옮기지 않는다
        if name.lower().startswith("image") and name.lower().endswith(
                (".png", ".jpg", ".jpeg", ".gif")):
            continue
        path = os.path.join(tmp, name)
        a.SaveAsFile(path)
        saved.append(path)

    html = str(getattr(draft, "HTMLBody", "") or "")
    reply = original.ReplyAll()
    if html:
        reply.HTMLBody = html
    for path in saved:
        reply.Attachments.Add(path)
    reply.Send()
    log(f"[용마] 답장 발송(원본에서 새로 작성): '{subject}' + 라벨 {label_name}")

    # 2026-09-10 사용자 승인: 새 답장이 나간 뒤 **원본 초안을 지운다**.
    # 본사 앞 메일 쪽에서 초안을 남겨뒀다가 사용자가 그걸 또 보내 같은 메일이
    # 2통 나간 사고가 있었다(같은 구조라 여기도 함께 적용). 발송 성공 후에만 지운다.
    try:
        draft.Delete()
        log("  원본 인라인 초안 삭제(같은 내용이 이미 발송됨 - 중복 발송 방지)")
    except Exception as e:
        log(f"  [경고] 원본 초안을 지우지 못했습니다({e}) - 임시보관함에서 직접 "
            f"지워주세요. 그대로 두면 중복 발송될 수 있습니다")


def _find_yongma_reply_body(to_number: str) -> str | None:
    """용마 폴더(받은편지함 > Operation > Yongma)에서 이 TO#의 회신 본문을
    찾는다(rebalance_watcher와 같은 폴더/조건). 없으면 None."""
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    inbox = outlook.GetDefaultFolder(6)
    op = next((f for f in inbox.Folders if str(f.Name).strip() == "Operation"), None)
    if op is None:
        return None
    yongma = next((f for f in op.Folders if str(f.Name).strip() == "Yongma"), None)
    if yongma is None:
        return None
    items = yongma.Items
    items.Sort("[ReceivedTime]", True)
    for i in range(1, min(items.Count, 100) + 1):
        try:
            mail = items.Item(i)
        except Exception:
            continue
        if getattr(mail, "Class", None) != 43:
            continue
        subj = str(mail.Subject or "")
        if str(to_number) in subj and ("Rebalance" in subj or "RMA" in subj.upper()):
            return str(mail.Body or "")
    return None


def parse_yongma_dims(body: str) -> list[dict] | None:
    """용마 회신 본문에서 박스별 [무게kg, 가로, 세로, 높이(cm)]를 best-effort로 뽑는다.

    반환: [{"weight": float, "L": float, "W": float, "H": float}, ...] 또는 None.
    - mm로 쓰인 경우 cm로 환산한다(FedEx 입력 단위가 cm/kg라고 가정 - 실측에서
      화면 단위 확인 필요).
    - 박스가 여러 개인데 크기/무게가 한 세트만 있는 경우(전 박스 동일하다는 뜻으로
      해석) 박스 수만큼 값을 복제한다 - **추측이 들어간 부분**이므로, 파싱 결과는
      항상 로그로 남기고 나중에 사람 알림에 같이 보여준다."""
    text = str(body or "")
    sizes = []
    for m in _BOX_SIZE_PATTERN.finditer(text):
        l, w, h = (float(m.group(k)) for k in ("l", "w", "h"))
        unit = (m.group("unit") or "cm").lower()
        if unit == "mm":
            l, w, h = l / 10.0, w / 10.0, h / 10.0
        sizes.append({"L": l, "W": w, "H": h})
    weights = [float(m.group("w")) for m in _WEIGHT_PATTERN.finditer(text)]
    n_boxes = 0
    for pat in _BOX_COUNT_PATTERNS:
        for m in pat.finditer(text):
            n_boxes = max(n_boxes, int(m.group("n")))
    n_boxes = n_boxes or max(len(sizes), len(weights))

    if not sizes and not weights:
        return None

    packages = []
    for i in range(max(n_boxes, 1)):
        size = sizes[min(i, len(sizes) - 1)] if sizes else {"L": None, "W": None, "H": None}
        weight = weights[min(i, len(weights) - 1)] if weights else None
        packages.append({"weight": weight, "L": size["L"], "W": size["W"], "H": size["H"]})

    log(f"[용마파싱] 박스 {len(packages)}개 추정: {packages}")
    return packages


# ==============================================================
# FedEx 화면 조작 (1~6단계) - 셀렉터는 전부 실측 전 추정
# ==============================================================
def get_fedex_driver():
    """공유 Edge(디버그 포트)에 붙어 **새 탭을 열어 바로 FedEx로** 보내는 전용
    드라이버 생성 함수.

    2026-08-25 사용자 요청("오라클 홈페이지로 들어가지말고 바로 fedex로"):
    icbl의 get_oracle_driver_isolated()는 새 탭을 열고 무조건 오라클 홈으로
    이동시키기 때문에, FedEx 실행 때마다 오라클 로그인 탭이 하나씩 생겼다.
    같은 공유 Edge에 붙는 부분(로그인 세션=쿠키는 프로필 전체 공유)은 그대로
    쓰고, 초기 이동만 FedEx로 바꿨다."""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options

    port, _ = _resolve_edge_target()
    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    driver = webdriver.Edge(options=options)
    try:
        driver.set_page_load_timeout(60)
        driver.set_script_timeout(30)
    except Exception:
        pass
    driver.switch_to.new_window("tab")   # about:blank 새 탭 - 여기서 바로 FedEx로 감
    return driver



def _click_first_visible(driver, texts, timeout: float = 8.0):
    """보이는 요소 중 텍스트가 texts와 일치하는 것을 찾아 클릭한다.

    2026-08-24 실측 수정: 예전엔 contains 매칭의 첫 후보를 클릭했는데, FedEx는
    내비게이션 전체를 감싼 컨테이너 div의 텍스트에도 "등록/로그인"이 들어 있어
    **바깥쪽 컨테이너를 클릭**해버렸다(로그인 창이 안 열림). 그래서
    1) 텍스트가 정확히 같은 요소를 먼저 찾고(exact),
    2) 없으면 contains 후보 중 **텍스트가 가장 짧은 것**(=가장 안쪽 잎 요소)을
    고른다. FedEx는 React SPA라 일반 클릭이 씹힐 수 있어 JS 클릭 폴백도 둔다."""
    from selenium.webdriver.common.by import By

    deadline = time.time() + timeout
    tags = ("self::a or self::button or self::span or self::div or "
            "self::*[@role='button' or @role='link' or @role='menuitem']")
    exact_xpath = "//*[" + tags + "][" + " or ".join(
        f"normalize-space(.)='{t}'" for t in texts) + "]"
    contains_xpath = "//*[" + tags + "][" + " or ".join(
        f"contains(normalize-space(.),'{t}')" for t in texts) + "]"

    while time.time() < deadline:
        for xpath in (exact_xpath, contains_xpath):
            best = best_len = None
            for el in driver.find_elements(By.XPATH, xpath):
                try:
                    if not (el.is_displayed() and el.is_enabled()):
                        continue
                    txt = (el.text or "").strip()
                except Exception as e:
                    if is_session_dead_error(e):
                        raise
                    continue
                if not txt:
                    continue
                if best is None or len(txt) < best_len:
                    best, best_len = el, len(txt)
            if best is not None:
                txt = (best.text or "").strip()
                try:
                    best.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", best)
                log(f"[FedEx] 클릭: '{txt[:40]}' (후보 텍스트={texts})")
                time.sleep(2)
                return best
        time.sleep(0.5)
    _save_diag(driver, "click_" + re.sub(r"\W+", "_", texts[0])[:20])
    raise RuntimeError(f"FedEx 화면에서 클릭 대상을 못 찾음: {texts}")


# 2026-08-24 3차 실측 확정: FedEx 쿠키 배너는 Usercentrics CMP로, 본문이
# <aside id="usercentrics-cmp-ui">의 **섀도우 DOM** 안에 있다(일반 XPath로는
# 안 잡힘). 게다가 이 aside가 페이지 전체 클릭을 가로채서(ElementClickInterceptedException,
# 실측: "Other element would receive the click: <aside id=usercentrics-cmp-ui>")
# 배너를 안 닫으면 이후 모든 클릭이 먹지 않는다. 섀도우 루트 안의 버튼을
# 직접 찾아 누른다 - '수락'이 없으면 '거부'로라도 닫는다(목적은 오버레이 제거).
_JS_DISMISS_COOKIE_BANNER = r"""
var host = document.querySelector('#usercentrics-cmp-ui');
if (!host) return 'no-banner';
if (host.shadowRoot) {
  var btns = host.shadowRoot.querySelectorAll('button');
  var accept = null, deny = null;
  for (var i = 0; i < btns.length; i++) {
    var sig = ((btns[i].textContent || '') + ' ' + (btns[i].id || '') + ' '
               + (btns[i].className || ''));
    if (/수락|accept/i.test(sig)) accept = accept || btns[i];
    if (/거부|deny/i.test(sig)) deny = deny || btns[i];
  }
  var b = accept || deny;
  if (b) { b.click(); return 'clicked:' + (b.id || (b.textContent || '').trim()); }
  return 'no-button-in-shadow';
}
return 'no-shadow';
"""


def _dismiss_cookie_banner(driver) -> None:
    """하단 쿠키 동의 배너(Usercentrics)를 닫는다.
    2026-08-24 3차 실측: 배너 본문이 섀도우 DOM 안에 있어 위 JS로 직접 닫는다.
    배너가 안 떠 있어도 무해하다 - 실패를 내지 않고 조용히 넘어간다."""
    try:
        result = str(driver.execute_script(_JS_DISMISS_COOKIE_BANNER) or "")
    except Exception as e:
        log(f"  [정보] 쿠키 배너 처리 중 오류({exc_detail(e)}) - 계속 진행")
        return
    if result.startswith("clicked"):
        log(f"[FedEx] 쿠키 배너 닫음({result})")
        time.sleep(1.5)
    elif result == "no-banner":
        log("  [정보] 쿠키 배너가 없음 - 건너뜀")
    else:
        # 닫지 못했으면 오버레이가 클릭을 계속 가로챈다 - 화면을 남겨 판단한다.
        log(f"  [경고] 쿠키 배너 닫기 결과: {result} - 이후 클릭이 가로채질 수 있음")
        _save_diag(driver, "cookie_banner")


def _click_dropdown_login(driver) -> None:
    """등록/로그인 드롭다운의 '로그인' 항목 클릭.
    2026-08-24 2차 실측: 항목은 <a> 안의 span일 수 있어, 텍스트가 정확히 '로그인'인
    보이는 요소를 찾아 가능하면 그 앵커/버튼 조상을 대신 클릭한다."""
    from selenium.webdriver.common.by import By

    cands = []
    for el in driver.find_elements(By.XPATH, "//*[normalize-space(.)='로그인']"):
        try:
            if el.is_displayed():
                cands.append(el)
        except Exception:
            continue
    if not cands:
        _save_diag(driver, "dropdown_login")
        raise RuntimeError("드롭다운에서 '로그인' 항목을 못 찾음")
    for el in cands:
        target = el
        try:
            anc = el.find_element(By.XPATH, "./ancestor::a[1] | ./ancestor::button[1]")
            if anc.is_displayed():
                target = anc
        except Exception:
            pass
        try:
            target.click()
        except Exception:
            driver.execute_script("arguments[0].click();", target)
        log("[FedEx] 드롭다운 '로그인' 클릭")
        return


def _switch_to_login_page(driver, timeout: float = 15.0) -> bool:
    """로그인 화면이 열릴 때까지 모든 탭을 훑어 이동한다.
    2026-08-24 2차 실측: 드롭다운 '로그인'이 같은 탭에서 안 열릴 수 있다(새 탭
    가능성). 판정: URL에 login이 있거나, 그 탭에 비밀번호 입력칸이 보이면 성공."""
    from selenium.webdriver.common.by import By

    def _looks_like_login() -> bool:
        try:
            url = (driver.current_url or "").lower()
            # 2026-08-25 실측: 공유 Edge에 남은 **오라클** 로그인 탭
            # (idcs-*.oraclecloud.com/ui/v1/signin)이 이 판정에 걸려
            # FedEx 계정을 오라클 화면에 입력하려는 사고가 났다 - fedex.com
            # 탭만 대상으로 한다.
            if "fedex.com" not in url:
                return False
            if "login" in url:
                return True
            for el in driver.find_elements(By.CSS_SELECTOR, "input[type='password']"):
                if el.is_displayed():
                    return True
        except Exception as e:
            if is_session_dead_error(e):
                raise
        return False

    deadline = time.time() + timeout
    while time.time() < deadline:
        for handle in driver.window_handles:
            try:
                driver.switch_to.window(handle)
                if _looks_like_login():
                    log(f"[FedEx] 로그인 화면 진입 확인: {driver.current_url[:80]}")
                    return True
            except Exception as e:
                if is_session_dead_error(e):
                    raise
                continue
        time.sleep(1)
    return False


def open_and_login(driver) -> None:
    """1~3단계: tracking.html 접속 -> 등록/로그인 -> 로그인 -> ID/PW -> 로그인.

    _TODO_실측: 상단 버튼의 정확한 문구/구조, 로그인 위젯이 모달인지 새 페이지인지,
    ID/PW 입력칸 셀렉터는 아직 실측 전이다. 아래 구현은 '텍스트로 찾되 안 되면
    속성으로 찾는' 2중 안전망 구조로만 잡아두었다."""
    from selenium.webdriver.common.by import By

    log("[FedEx] tracking.html 접속")
    driver.get(FEDEX_TRACKING_URL)
    wait_or_sleep(driver, element_present(By.TAG_NAME, "body"), 10)
    time.sleep(3)   # SPA 초기 렌더 여유
    _dismiss_cookie_banner(driver)

    # 2026-08-24 실측: 공유 Edge에 세션이 남아 있으면 헤더 계정명이 이미 떠 있다 -
    # 그 경우 등록/로그인 드롭다운의 항목 구성이 달라져(로그아웃 메뉴) 아래
    # 로그인 플로우가 오히려 실패하므로 통째로 건너뛴다.
    try:
        header = driver.find_element(By.ID, "fxg-dropdown-signIn")
        txt = (header.text or "").strip()
        if txt and "등록/로그인" not in txt:
            log(f"[FedEx] 이미 로그인된 세션(계정명: {txt!r}) - 로그인 단계 건너뜀")
            return
    except Exception:
        pass

    # 2단계 - 상단 등록/로그인. 문구 변형 후보들을 함께 넣는다.
    # _TODO_실측: 실제 버튼 aria-label/텍스트 확인 필요.
    _click_first_visible(driver, ["등록/로그인", "로그인/등록", "Sign In or Register",
                                  "Register or Log In"])
    # 드롭다운/메뉴에 나타나는 "로그인" - 2026-08-24 실측: 드롭다운이 열리고
    # 그 안의 '로그인' 항목을 눌러야 한다. 눌러도 같은 탭이 안 바뀔 수 있어
    # 모든 탭을 훑어 로그인 화면을 찾고, 그래도 안 되면 한 번 더 클릭한다.
    time.sleep(1.5)
    _click_dropdown_login(driver)
    if not _switch_to_login_page(driver, timeout=15):
        log("  [정보] 로그인 화면이 아직 안 열림 - '로그인'을 한 번 더 클릭해 재시도")
        _click_first_visible(driver, ["로그인", "Log In", "Login"])
        if not _switch_to_login_page(driver, timeout=10):
            _save_diag(driver, "no_login_page")
            raise RuntimeError("로그인 화면(페이지/위젯)이 열리지 않음")

    # 3단계 - ID/PW. placeholder/name/id로 먼저 찾고, 실패하면 라벨 기준.
    # _TODO_실측: 실제 input 셀렉터 확정 필요.
    def _fill(selector_variants, label_texts, value, kind):
        last_err = None
        for sel in selector_variants:
            try:
                el = _wait_find(driver, By.CSS_SELECTOR, sel, timeout=4)
                el.click()
                el.clear()
                el.send_keys(value)
                log(f"[FedEx] {kind} 입력 완료 (셀렉터: {sel}, 길이 {len(value)})")
                return
            except Exception as e:
                last_err = e
                continue
        # 폴백: 라벨 텍스트 근처의 input
        for lt in label_texts:
            try:
                el = _wait_find(
                    driver, By.XPATH,
                    f"//label[contains(normalize-space(.),'{lt}')]/following::input[1]",
                    timeout=3)
                el.click(); el.clear(); el.send_keys(value)
                log(f"[FedEx] {kind} 입력 완료 (라벨: {lt}, 길이 {len(value)})")
                return
            except Exception as e:
                last_err = e
        _save_diag(driver, f"input_{kind}")
        raise RuntimeError(f"FedEx 로그인 {kind} 입력칸을 못 찾음: {last_err}")

    _fill(
        ["input[name*='user' i]", "input[id*='userId' i]", "input[placeholder*='ID']"],
        ["사용자 ID", "User ID", "이메일"],
        FEDEX_USER_ID, "ID")
    _fill(
        ["input[type='password']"],
        ["비밀번호", "Password"],
        FEDEX_PASSWORD, "PW")

    _click_first_visible(driver, ["로그인", "Log In", "Login"])

    # 로그인 성공 판정 - 2026-08-24 실측 2건으로 확정:
    #  (a) tracking 쪽이면 헤더 #fxg-dropdown-signIn 텍스트가 "등록/로그인"에서
    #      계정 소유자 이름(예: Miae)으로 바뀐다.
    #  (b) 로그인 전에 발송 화면(shippingplus)을 열어뒀으면 로그인 뒤 그 페이지로
    #      **리다이렉트**된다 - 이 화면은 헤더 구조가 달라 (a) 요소가 없다.
    #  공통 규칙: secure-login에서 벗어나는 것이 1차 신호다.
    deadline = time.time() + LOGIN_SETTLE_TIMEOUT_SEC
    while time.time() < deadline:
        try:
            url = (driver.current_url or "").lower()
            if url and "secure-login" not in url:
                try:
                    header = driver.find_element(By.ID, "fxg-dropdown-signIn")
                    txt = (header.text or "").strip()
                    if txt and "등록/로그인" not in txt:
                        log(f"[FedEx] 로그인 완료 확인(헤더 계정명: {txt!r})")
                        return
                except Exception:
                    pass
                if "shippingplus" in url:
                    log("[FedEx] 로그인 완료 확인(발송 화면으로 리다이렉트)")
                    return
        except Exception as e:
            if is_session_dead_error(e):
                raise
        page = driver.page_source or ""
        if any(sig in page for sig in ("로그아웃", "Log Out", "Sign Out")):
            log("[FedEx] 로그인 완료로 판단(로그아웃 신호 확인 - 폴백 판정)")
            return
        time.sleep(1)
    _save_diag(driver, "after_login")
    raise RuntimeError("FedEx 로그인 후 상태를 확인 못 함(로그인 실패 또는 신호 미발견)")


def goto_ship_now(driver) -> None:
    """4단계: 발송 메뉴 -> 지금 발송.

    _TODO_실측: 상단 메뉴가 hover 메뉴인지 클릭 메뉴인지, "지금 발송"이 서브메뉴
    항목인지 버튼인지 미확인. hover가 필요하면 ActionChains로 바꿀 것."""
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By

    ship_menu = None
    for t in ("발송", "Ship"):
        els = [e for e in driver.find_elements(By.XPATH, f"//*[normalize-space(text())='{t}']")
               if e.is_displayed()]
        if els:
            ship_menu = els[0]
            break
    if ship_menu is None:
        _save_diag(driver, "ship_menu")
        raise RuntimeError("FedEx 상단에서 '발송' 메뉴를 못 찾음")
    try:
        ship_menu.click()
    except Exception:
        driver.execute_script("arguments[0].click();", ship_menu)
    time.sleep(1.5)
    # hover 방식도 시도해본다(메뉴가 hover형일 경우 대비) - 클릭이 이미 먹혔으면 해롭지 않다.
    try:
        ActionChains(driver).move_to_element(ship_menu).perform()
    except Exception:
        pass

    _click_first_visible(driver, ["지금 발송", "Ship Now"])
    # 2026-08-25 실측: 발송 화면(shippingplus) 전환은 수십 초 걸릴 수 있다.
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if "shippingplus" in (driver.current_url or "").lower():
                break
        except Exception as e:
            if is_session_dead_error(e):
                raise
        time.sleep(2)
    else:
        _save_diag(driver, "ship_page_timeout")
        raise RuntimeError("지금 발송 후 발송 화면(shippingplus)으로 이동하지 않음")
    log(f"[FedEx] 발송 화면 진입: {driver.current_url[:80]}")
    time.sleep(3)   # 수취인 섹션 렌더 여유


def _close_cookie_notice(driver) -> None:
    """화면 하단의 "This FedEx website uses cookies..." 공지를 닫는다.
    2026-08-25 실측: 이 배너가 다음 버튼 클릭을 가로챈다
    (ElementClickInterceptedException, intercepting element=<p>). 닫기 버튼은
    텍스트 없는 X 아이콘 button이라 하단(y>900) 무텍스트 버튼을 닫는다.
    못 찾아도 무해하다 - JS 클릭 폴백이 있다."""
    from selenium.webdriver.common.by import By
    for b in driver.find_elements(By.XPATH, "//button[not(normalize-space(.))]"):
        try:
            if not b.is_displayed():
                continue
            if b.rect.get("y", 0) > 900:
                driver.execute_script("arguments[0].click();", b)
                log("[FedEx] 하단 쿠키 공지 닫기 시도")
                time.sleep(1)
                return
        except Exception:
            continue


def _close_info_modal(driver) -> None:
    """\"주소 확인이란?\" 같은 정보 모달(닫기 버튼)을 닫는다. 없으면 조용히 넘어간다."""
    from selenium.webdriver.common.by import By
    for b in driver.find_elements(By.XPATH, "//button[normalize-space(.)='닫기' or normalize-space(.)='Close']"):
        try:
            if b.is_displayed():
                d = driver.execute_script(
                    "var r=arguments[0].getBoundingClientRect();"
                    "return (r.width>300 && r.height>200) || arguments[0].closest('dialog')!=null;",
                    b)
                if d:
                    driver.execute_script("arguments[0].click();", b)
                    log("[FedEx] 정보 모달 닫기")
                    time.sleep(2)
                    return
        except Exception:
            continue


def _click_next(driver) -> None:
    """다음 버튼 클릭(가로챔 대비 JS 폴백) + 뒤에 뜰 수 있는 안내 모달 정리."""
    from selenium.webdriver.common.by import By
    _close_cookie_notice(driver)
    btns = [b for b in driver.find_elements(
        By.XPATH, "//button[normalize-space(.)='다음' or normalize-space(.)='Next']")
        if b.is_displayed()]
    if not btns:
        _save_diag(driver, "next_button")
        raise RuntimeError("다음 버튼을 못 찾음")
    try:
        btns[0].click()
    except Exception:
        driver.execute_script("arguments[0].click();", btns[0])
    log("[FedEx] 다음 클릭")
    time.sleep(6)
    _close_info_modal(driver)


def select_recipient_from_address_book(driver, country_code: str) -> dict:
    """5단계: 주소록 검색으로 받는 사람 선택 -> 다음.

    2026-08-25 실측으로 셀렉터 전부 확정(KRP-WAY/Bob Lazaros 케이스):
    - 수취인 검색창: [data-test-id='receiver-address-search-input'] 안의 input
      (placeholder 속성은 빈 값이고 "주소록에서 검색"은 float label이다)
    - 돋보기 옆 버튼: button[aria-label='저장된 연락처'] -> 우측 슬라이드
      다이얼로그(dialog[data-test-id='dialog-slide'])가 열린다
    - 다이얼로그 안 검색창에 이름을 넣으면 목록이 좁혀지고 행마다 '추가' 버튼이
      있다 - 추가를 누르면 다이얼로그가 닫히며 수취인 폼이 자동 채워진다
      (실측: 이름/회사/전화/주소1 확인).
    - 홍콩(ILH)처럼 동명이인이 여러 개면 PREFER_RESULT_KEYWORD('New')가 들어간
      행을 우선한다(사용자 지시)."""
    from selenium.webdriver.common.by import By

    contact = lookup_ship_to_contact(country_code)
    search_name = contact["search_name"]

    # 수취인 검색창이 뜰 때까지 대기(발송 화면 로딩이 수십 초 걸릴 수 있다).
    box = None
    deadline = time.time() + 60
    while time.time() < deadline and box is None:
        for el in driver.find_elements(
                By.CSS_SELECTOR, "[data-test-id='receiver-address-search-input'] input"):
            try:
                if el.is_displayed():
                    box = el
                    break
            except Exception:
                continue
        if box is None:
            time.sleep(2)
    if box is None:
        _save_diag(driver, "addr_searchbox")
        raise RuntimeError("수취인 주소록 검색창을 못 찾음")

    box.click()
    box.clear()
    box.send_keys(search_name)
    log(f"[FedEx] 주소록 검색어 입력: {search_name!r}")
    time.sleep(1.5)

    # 돋보기 옆 '저장된 연락처' 버튼으로 다이얼로그를 연다. 2026-08-25 실측:
    # 가끔 클릭이 씹힌다(하단 쿠키 공지/렌더 타이밍) - 닫기 -> 클릭 -> 최대
    # 15초 폴링 -> 한 번 더 클릭 순으로 재시도한다.
    _close_cookie_notice(driver)
    ab_btn = None
    for b in driver.find_elements(By.XPATH, "//button[@aria-label='저장된 연락처']"):
        if b.is_displayed():
            ab_btn = b
            break
    if ab_btn is None:
        _save_diag(driver, "saved_contacts_btn")
        raise RuntimeError("'저장된 연락처' 버튼(돋보기 옆)을 못 찾음")

    def _dialog_opened() -> bool:
        for e in driver.find_elements(By.CSS_SELECTOR, "dialog[data-test-id='dialog-slide']"):
            try:
                if e.is_displayed():
                    return True
            except Exception:
                continue
        return False

    for attempt in range(2):
        try:
            ab_btn.click()
        except Exception:
            driver.execute_script("arguments[0].click();", ab_btn)
        deadline = time.time() + 15
        while time.time() < deadline:
            if _dialog_opened():
                break
            time.sleep(1)
        if _dialog_opened():
            break
        log(f"  [정보] 다이얼로그 미개함(시도 {attempt + 1}/2) - 재클릭")
    if not _dialog_opened():
        _save_diag(driver, "contacts_dialog")
        raise RuntimeError("저장된 연락처 다이얼로그가 열리지 않음")
    log("[FedEx] 저장된 연락처 다이얼로그 열기")
    time.sleep(2)

    dlg = None
    for e in driver.find_elements(By.CSS_SELECTOR, "dialog[data-test-id='dialog-slide']"):
        try:
            if e.is_displayed():
                dlg = e
                break
        except Exception:
            continue
    if dlg is None:
        # _dialog_opened()가 참이었는데 재탐색에서 놓치는 건 재렌더 타이밍 문제다 -
        # 추측으로 진행하면 엉뚱한 요소를 만지므로 화면을 남기고 중단한다.
        _save_diag(driver, "contacts_dialog_lost")
        raise RuntimeError("저장된 연락처 다이얼로그를 다시 못 잡음(재렌더 추정)")

    # 다이얼로그 안 검색창(첫 보이는 텍스트 input)에 이름을 넣어 좁힌다.
    sbox = None
    for inp in dlg.find_elements(By.CSS_SELECTOR, "input[type='text'], input[type='search']"):
        try:
            if inp.is_displayed():
                sbox = inp
                break
        except Exception:
            continue
    if sbox is None:
        _save_diag(driver, "dialog_searchbox")
        raise RuntimeError("다이얼로그 안 검색창을 못 찾음")
    sbox.click()
    sbox.clear()
    sbox.send_keys(search_name)
    time.sleep(3)

    # 결과 행: '추가' 버튼에서 조상으로 올라가며 검색어(첫 단어)가 들어간 행을
    # 찾는다. 2026-08-25 실측: ancestor::div[1]은 버튼의 좁은 래퍼라 이름 텍스트가
    # 없다 - 몇 단계든 올라가 토큰이 포함된 첫 조상을 행으로 삼는다.
    token = (search_name.split() or [""])[0]
    rows = []
    for b in dlg.find_elements(By.XPATH, ".//button[normalize-space(.)='추가']"):
        try:
            if not b.is_displayed():
                continue
            node = b
            for _ in range(6):
                node = node.find_element(By.XPATH, "..")
                txt = (node.text or "").strip()
                if token.lower() in txt.lower():
                    if txt not in [r[0] for r in rows]:
                        rows.append((txt, node, b))
                    break
        except Exception:
            continue
    if not rows:
        _save_diag(driver, "dialog_results")
        raise RuntimeError(f"주소록에서 '{search_name}' 결과를 못 찾음")
    chosen_txt, chosen_row, chosen_btn = rows[0]
    if len(rows) > 1:
        preferred = [r for r in rows if PREFER_RESULT_KEYWORD in r[0]]
        if preferred:
            chosen_txt, chosen_row, chosen_btn = preferred[0]
        log(f"[FedEx] 검색 결과 {len(rows)}개 - 선택: {chosen_txt[:50]!r} "
            f"({'New' in chosen_txt} New 우선 적용)")
    else:
        log(f"[FedEx] 검색 결과 1개: {chosen_txt[:50]!r}")

    driver.execute_script("arguments[0].click();", chosen_btn)
    log("[FedEx] 연락처 '추가' 클릭")
    time.sleep(4)

    # 수취인 폼이 실제로 채워졌는지 확인. 주의: 폼에는 주소록의 **실명**(예:
    # "Robert Lazaros")이 들어가지 검색어("Bob Lazaros")와 다를 수 있다(2026-08-25
    # 실측) - 그래서 토큰 매칭이 아니라 "텍스트 필드에 값이 들어왔는지"로 본다.
    #
    # 2026-09-04: 예전엔 sleep 4 뒤 **한 번만** 확인해서, 상세 정보가 늦게 차는
    # 회차는 그대로 실패했다(실측 2회 연속 - 진단 캡처에 검색창엔 'Robert
    # Lazaros'가 들어갔는데 연락처 이름/회사명/전화가 전부 빈 칸이고 로딩
    # 스피너가 돌고 있었다). 같은 계정이 30분 전에는 성공했으니 화면이 느린
    # 것뿐이다 - 채워질 때까지 폴링한다.
    filled = False
    deadline = time.time() + RECIPIENT_FILL_TIMEOUT_SEC
    while time.time() < deadline:
        for inp in driver.find_elements(By.CSS_SELECTOR, "input[id^='fedex-input-text-field']"):
            try:
                v = (inp.get_attribute("value") or "").strip()
                if v:
                    log(f"[FedEx] 수취인 폼 채워짐 확인: {v[:40]!r}")
                    filled = True
                    break
            except Exception:
                continue
        if filled:
            break
        time.sleep(2)
    if not filled:
        _save_diag(driver, "recipient_not_filled")
        raise RuntimeError(
            f"연락처 추가 후 수취인 폼이 {RECIPIENT_FILL_TIMEOUT_SEC}초 안에 "
            f"채워지지 않음({search_name!r})")
    log(f"[FedEx] 수취인 폼 채워짐 확인: {search_name!r}")

    _click_next(driver)
    return contact


def choose_own_packaging_and_fill_packages(driver, packages: list[dict]) -> None:
    """6단계: 포장 유형 '자체포장재' 선택 + 용마 제원(무게/크기) 기입.

    packages: [{"weight": kg, "L","W","H": cm}, ...] (parse_yongma_dims 결과)

    2026-08-25/27 실측으로 확정(KRP-WAY 케이스):
    - 포장 유형은 <select>다 - '자체 포장재' 옵션을 골라 선택(내부값 7:
      YOUR_PACKAGING 확인).
    - 행 구조(2026-08-27 DOM 실측): 한 행이
      [패키지 수량][무게][치수 길이][폭][높이] 순서이고, 치수만
      `package-details__dimensions-{i}-length|width|height`로 id가 있다.
      수량/무게 칸은 id가 `fedex-input-field-NNNNNN`로 매번 바뀌므로 **그 행
      길이칸 바로 앞 input**으로 찾는다.
    - 행 추가: button[data-test-id='package-details.add-package'],
      행 삭제: button[data-test-id='package-details.remove-package-{i}'].
    - **값 검증 필수**: 이전 미완성 발송물이 복원되면 칸에 옛 값이 남고 clear()가
      안 먹어 덧입력된다(2026-08-26 사고: 50 -> 500). 아래 _set_verified 참고."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    # 포장 유형 select(옵션에 '자체 포장재'가 있는 select)가 뜰 때까지 대기.
    pkg_select = None
    deadline = time.time() + 60
    while time.time() < deadline and pkg_select is None:
        for s in driver.find_elements(By.TAG_NAME, "select"):
            try:
                if not s.is_displayed():
                    continue
                opts = [o.text.strip() for o in s.find_elements(By.XPATH, "./option")]
                if "자체 포장재" in opts:
                    pkg_select = s
                    break
            except Exception:
                continue
        if pkg_select is None:
            time.sleep(2)
    if pkg_select is None:
        _save_diag(driver, "packaging_select")
        raise RuntimeError("포장 유형 select('자체 포장재' 옵션 포함)을 못 찾음")
    Select(pkg_select).select_by_visible_text("자체 포장재")
    log("[FedEx] 포장 유형: 자체 포장재 선택")
    time.sleep(2)

    n = len(packages)

    def _rows() -> list:
        """현재 화면의 패키지 행 개수 = 보이는 치수 '길이' 입력칸 개수."""
        return [e for e in driver.find_elements(
            By.CSS_SELECTOR, "input[id*='dimensions-'][id*='-length']")
            if e.is_displayed()]

    def _dim_input(i: int, key: str):
        els = [e for e in driver.find_elements(
            By.CSS_SELECTOR, f"input[id*='dimensions-{i}-{key}']") if e.is_displayed()]
        if not els:
            _save_diag(driver, f"dim_{i}_{key}")
            raise RuntimeError(f"패키지 {i + 1}행 치수 {key} 입력칸을 못 찾음")
        return els[0]

    def _weight_input(i: int):
        """행의 무게 칸. 2026-08-27 실측: 무게/패키지수 칸은 aria-label도 for-라벨도
        없는 `fedex-input-field-NNNNNN`이고, DOM 순서가
        [패키지 수량][무게][치수 길이][폭][높이] 라서 **그 행 길이칸 바로 앞의
        텍스트 input**이 무게다(예전엔 'kg select가 뒤따르는 input'으로 찾았는데
        테이블 뷰에서는 select가 행 밖에 있어 못 찾았다)."""
        el = _dim_input(i, "length").find_element(
            By.XPATH, "./preceding::input[@type='text'][1]")
        if (el.get_attribute("aria-label") or "").startswith("치수"):
            _save_diag(driver, f"weight_{i}")
            raise RuntimeError(f"패키지 {i + 1}행 무게 칸 위치 판정 실패"
                               f"(치수칸이 잡힘: {el.get_attribute('id')})")
        return el

    def _fmt(v) -> str:
        """50.0 -> '50' (FedEx 치수칸은 정수 표기를 쓴다). 3.3은 그대로."""
        f = float(v)
        return str(int(f)) if f == int(f) else str(f)

    def _set_verified(el, value, what: str) -> None:
        """입력 후 **값이 실제로 그 값인지 확인**한다.

        2026-08-26 사고(7876545): FedEx가 이전 미완성 발송물을 복원해 칸에 '0'이
        남아 있었는데 clear()가 React 입력칸에 안 먹어 '50'을 치면 '500'이 됐다
        (치수 500cm -> "최대 302cm" 검증 오류 -> 행 추가까지 거부). 값 확인 없이
        진행하면 **엉뚱한 치수로 실제 발송물이 나간다** - 그래서 Ctrl+A/Delete로
        지우고, 기대값과 다르면 한 번 더 시도한 뒤 그래도 다르면 중단한다."""
        from selenium.webdriver.common.keys import Keys
        want = _fmt(value)
        for attempt in (1, 2):
            try:
                el.click()
            except Exception:
                driver.execute_script("arguments[0].focus();", el)
            el.send_keys(Keys.CONTROL, "a")
            el.send_keys(Keys.DELETE)
            time.sleep(0.3)
            el.send_keys(want)
            time.sleep(0.6)
            got = (el.get_attribute("value") or "").strip()
            if got == want:
                return
            log(f"  [경고] {what} 기입값 불일치(시도 {attempt}/2): 기대 {want!r} / 실제 {got!r}")
        tag = re.sub(r"\W+", "_", what)[:20]
        _save_diag(driver, "value_mismatch_" + tag)
        raise RuntimeError(f"{what} 값이 {want!r}로 안 들어감(실제 {got!r}) - "
                           f"이전 발송물 값이 남아 있을 수 있습니다")

    def _add_row(expect: int) -> None:
        """'새 패키지 추가'로 행을 하나 늘린다(expect = 늘어난 뒤 총 행 수)."""
        target = None
        for e in driver.find_elements(
                By.CSS_SELECTOR, "button[data-test-id='package-details.add-package']"):
            try:
                if e.is_displayed():
                    target = e
                    break
            except Exception:
                continue
        if target is None:
            _save_diag(driver, "add_package_link")
            raise RuntimeError("'새 패키지 추가' 버튼을 못 찾음(다중 박스)")
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", target)
            time.sleep(0.5)
        except Exception:
            pass
        try:
            target.click()
        except Exception:
            driver.execute_script("arguments[0].click();", target)
        deadline = time.time() + 20
        while time.time() < deadline:
            if len(_rows()) >= expect:
                log(f"[FedEx] 패키지 행 {expect}개로 확장")
                time.sleep(1)
                return
            time.sleep(1)
        _save_diag(driver, "package_row_not_added")
        raise RuntimeError(f"패키지 {expect}행 추가가 확인되지 않음 - 앞 행의 값이 "
                           f"검증에 걸리면 FedEx가 행 추가를 막습니다")

    # 복원된 발송물에 필요 이상으로 행이 남아 있으면 지운다(남은 빈 행이 있으면
    # 다음 단계 검증에 걸린다). 삭제 버튼은 remove-package-{i}(2026-08-27 실측).
    while len(_rows()) > n:
        idx = len(_rows()) - 1
        btns = [b for b in driver.find_elements(
            By.CSS_SELECTOR, f"button[data-test-id='package-details.remove-package-{idx}']")
            if b.is_displayed()]
        if not btns:
            _save_diag(driver, "remove_package_btn")
            raise RuntimeError(f"남은 패키지 {idx + 1}행을 지울 버튼을 못 찾음")
        driver.execute_script("arguments[0].click();", btns[0])
        log(f"[FedEx] 이전 발송물에서 남은 패키지 {idx + 1}행 삭제")
        time.sleep(2)

    for i, pkg in enumerate(packages):
        if len(_rows()) < i + 1:
            _add_row(i + 1)
        for key, val in (("length", pkg.get("L")), ("width", pkg.get("W")),
                         ("height", pkg.get("H"))):
            if val is None:
                raise RuntimeError(f"패키지 {i + 1}행 치수({key})가 비었습니다 - "
                                   f"용마 회신 제원을 확인하세요")
            _set_verified(_dim_input(i, key), val, f"{i + 1}행 치수 {key}")
        if pkg.get("weight") is None:
            raise RuntimeError(f"패키지 {i + 1}행 무게가 비었습니다")
        _set_verified(_weight_input(i), pkg["weight"], f"{i + 1}행 무게")
        log(f"[FedEx] 패키지 {i + 1}행 기입 확인: 무게={pkg.get('weight')}kg, "
            f"L={pkg.get('L')} W={pkg.get('W')} H={pkg.get('H')}")

    # 마지막 칸에 포커스가 남아 있으면 그 값이 FedEx 내부 상태(총 중량 합계)에
    # 반영되지 않는다(2026-08-27 실측: 2행 0.9kg 기입 직후 화면 "총 중량 3.3kg").
    # 요금이 무게로 계산되므로 반드시 blur 시키고 합계까지 확인한다.
    try:
        from selenium.webdriver.common.keys import Keys
        _weight_input(n - 1).send_keys(Keys.TAB)
        time.sleep(1.5)
    except Exception as e:
        log(f"  [정보] 마지막 칸 blur 생략({exc_detail(e)})")

    # 기입이 끝난 뒤 전 행을 다시 읽어 최종 확인(중간에 리렌더로 되돌아가는 경우 대비).
    for i, pkg in enumerate(packages):
        got = {k: (_dim_input(i, k).get_attribute("value") or "").strip()
               for k in ("length", "width", "height")}
        want = {"length": _fmt(pkg["L"]), "width": _fmt(pkg["W"]), "height": _fmt(pkg["H"])}
        gw = (_weight_input(i).get_attribute("value") or "").strip()
        if got != want or gw != _fmt(pkg["weight"]):
            _save_diag(driver, f"row_recheck_{i}")
            raise RuntimeError(f"패키지 {i + 1}행 최종 확인 실패: 치수 {got} (기대 {want}), "
                               f"무게 {gw!r} (기대 {_fmt(pkg['weight'])!r})")

    # 화면 하단 "총 패키지 수: N  총 중량: X kg"로 FedEx가 실제로 인식한 합계를 본다.
    want_total = round(sum(float(p["weight"]) for p in packages), 3)
    total_txt = ""
    for attempt in (1, 2):
        try:
            total_txt = driver.find_element(
                By.XPATH, "//*[contains(text(),'총 패키지 수')]/..").text
        except Exception:
            total_txt = ""
        m_cnt = re.search(r"총 패키지 수\s*:?\s*(\d+)", total_txt)
        m_wt = re.search(r"총 중량\s*:?\s*([\d.]+)", total_txt)
        if m_cnt and m_wt:
            got_cnt, got_wt = int(m_cnt.group(1)), float(m_wt.group(1))
            if got_cnt == n and abs(got_wt - want_total) < 0.005:
                log(f"[FedEx] 합계 확인: 총 패키지 {got_cnt}개 / 총 중량 {got_wt}kg")
                break
            log(f"  [경고] 합계 불일치(시도 {attempt}/2): 화면 {got_cnt}개/{got_wt}kg, "
                f"기대 {n}개/{want_total}kg")
        else:
            log(f"  [경고] 합계 표시를 못 읽음(시도 {attempt}/2): {total_txt!r}")
        time.sleep(3)
    else:
        _save_diag(driver, "package_total_mismatch")
        raise RuntimeError(f"FedEx가 인식한 패키지 합계가 기대와 다릅니다"
                           f"(화면: {total_txt!r}, 기대 {n}개 / {want_total}kg) - "
                           f"요금이 무게로 계산되므로 중단합니다")
    log(f"[FedEx] 자체포장재 + 제원 기입 완료(박스 {n}개, 값 검증까지 통과)")


# ==============================================================
# CI 실제값 조회 (수출신고실적에서 TO#로)
# ==============================================================
# CI PDF 품목 줄(2026-08-27 실측, KRP-WAY 9976055 / KRP-ILH 9976957):
#   7876545 1 7123-00-0593 Kit, Pico 532 HE Resolve HP MX 9018909000 1 0 1 ₩5,134,780 ₩5,134,780
#   7877405 1 FIN101958 GMPP Modified LSDS Options Kit for DCD US 1 0 1 ₩8,222,028 ₩8,222,028
# 열 순서: SO / SO라인 / 파트넘버 / 품명 / 원산지(2자) / HTS(10자리, **없는 줄도 있다**)
#          / ORDERED / BACK ORD / SHIPPED / 단가 / 금액.
# 품명 안에도 대문자 2글자 토큰이 있지만(HE, HP) 그 뒤가 숫자열+₩ 형태가 아니라
# 원산지로 오인되지 않는다(비탐욕 매칭 + 뒤쪽 형태 제약).
_CI_ITEM_LINE = re.compile(
    r"^(?P<so>\d{6,8})\s+(?P<line>\d+)\s+(?P<part>[A-Z0-9][A-Z0-9\-]+)\s+"
    r"(?P<desc>.*?)\s+(?P<origin>[A-Z]{2})\s+(?:(?P<hts>\d{8,10})\s+)?"
    r"(?P<ordered>\d+)\s+(?P<back>\d+)\s+(?P<shipped>\d+)\s+"
    r"₩(?P<unit>[\d,]+)\s+₩(?P<ext>[\d,]+)\s*$")


def parse_ci_pdf_items(ci_paths: list[str]) -> list[dict]:
    """CI PDF(들)에서 FedEx 물품 등록에 쓸 품목을 뽑는다.

    2026-08-27에 소스를 수출신고실적 -> **CI PDF**로 바꿨다. 사용자 지시가
    "가격 및 원산지는 CI에 있으니 참조해서 해줘"인데, 실제로 실적 파일이 CI와
    어긋나는 사례를 확인했기 때문이다:
      - TO 7877405: CI는 FIN101958 2대(₩16,444,056)인데 실적은 1대만
      - TO 7876545: 실적의 7123-00-0593 행에 금액/원산지가 비어 있음(CI엔 MX/₩5,134,780)
    잘못된 금액으로 세관 신고가 나가는 걸 막으려면 CI가 정답이어야 한다.

    같은 파트가 여러 줄이면(S/N만 다른 경우) 수량/금액을 합쳐 한 물품으로 만든다.
    반환: [{"part_no","description","qty","amount","hs_code","origin"}, ...]"""
    import pdfplumber

    merged: dict = {}
    for path in ci_paths:
        if not os.path.exists(path):
            raise FileNotFoundError(f"CI PDF가 없음: {path}")
        found = 0
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for raw in (page.extract_text() or "").splitlines():
                    m = _CI_ITEM_LINE.match(raw.strip())
                    if not m:
                        continue
                    found += 1
                    hts = "".join(ch for ch in (m.group("hts") or "") if ch.isdigit())
                    key = (m.group("part"), m.group("origin"))
                    item = merged.setdefault(key, {
                        "part_no": m.group("part"),
                        "description": m.group("desc").strip(),
                        "qty": 0,
                        "amount": 0,
                        "hs_code": None,
                        "origin": m.group("origin"),
                    })
                    item["qty"] += int(m.group("shipped"))
                    item["amount"] += int(m.group("ext").replace(",", ""))
                    if hts and not item["hs_code"]:
                        item["hs_code"] = hts[:HTS_DIGITS_FOR_FEDEX]
        if not found:
            raise ValueError(f"CI PDF에서 품목 줄을 못 읽음: {os.path.basename(path)} - "
                             f"양식이 바뀌었는지 확인 필요(추측 기입 금지)")
        log(f"[CI] {os.path.basename(path)}: 품목 줄 {found}건 파싱")

    rows = list(merged.values())
    for r in rows:
        if not r["hs_code"]:
            # 2026-09-04 사용자 지시: 없으면 기본값. 예전엔 여기서 중단해
            # 어레인지 전체가 멈췄다(실측: TO 7878369의 7122-00-9592 - 그 파트가
            # 수입 이력이 없어 CI의 HS 칸도 비어 있었다).
            r["hs_code"] = HTS_CODE_FALLBACK[:HTS_DIGITS_FOR_FEDEX]
            log(f"  [정보] CI에 {r['part_no']}의 HS 코드가 없어 기본값 "
                f"{r['hs_code']} 적용")
    log("[CI] FedEx 물품 등록 대상 " + str(len(rows)) + "건: "
        + "; ".join(f"{r['part_no']} x{r['qty']} {r['origin']} ₩{r['amount']:,} HS{r['hs_code']}"
                    for r in rows))
    return rows


def crosscheck_export_declaration(to_number: str, ci_rows: list[dict]) -> list[str]:
    """CI에서 뽑은 값과 수출신고실적을 비교해 **차이만 알려준다**(진행은 막지 않음).

    실적은 사후 정정이 가능한 기록이고 FedEx에 들어가는 값은 CI가 정답이므로,
    여기서 멈추지 않고 경고만 남겨 알림 메일에 함께 보낸다."""
    warnings = []
    try:
        decl = lookup_ci_data_for_to(to_number)
    except Exception as e:
        return [f"수출신고실적 대조 실패: {e}"]
    by_part: dict = {}
    for d in decl:
        cur = by_part.setdefault(d["part_no"], {"qty": 0, "amount": 0})
        cur["qty"] += int(d["qty"] or 0)
        cur["amount"] += int(d["amount"] or 0)
    for r in ci_rows:
        d = by_part.get(r["part_no"])
        if d is None:
            warnings.append(f"{r['part_no']}: CI에는 있는데 수출신고실적에 없음")
            continue
        if d["amount"] != r["amount"] or d["qty"] != r["qty"]:
            warnings.append(
                f"{r['part_no']}: CI {r['qty']}개/₩{r['amount']:,} vs "
                f"실적 {d['qty']}개/₩{d['amount']:,}")
    for w in warnings:
        log(f"  [경고] 수출신고실적 불일치 - {w}")
    return warnings


def lookup_ci_data_for_to(to_number: str) -> list[dict]:
    """수출신고실적에서 이 TO의 행을 찾아 FedEx 물품 등록에 쓸 값을 돌려준다.

    2026-08-25 사용자 지시: "가격 및 원산지는 CI에 있으니 참조해서 해줘" -
    CI에 찍히는 단가/금액/원산지/HS는 수출신고실적에 같은 값으로 기입돼 있으므로
    여기서 읽는다(rebalance_watcher.append_export_declaration이 쓰는 그 파일).

    반환: [{"part_no", "description", "qty", "amount", "hs_code", "origin"}, ...]
    - hs_code는 FedEx용으로 앞 6자리만 둔다(HTS_DIGITS_FOR_FEDEX)."""
    import openpyxl

    wb = openpyxl.load_workbook(EXPORT_DECLARATION_PATH, data_only=True, read_only=True)
    ws = wb["Sheet1"]
    header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())

    def _col(*names):
        for idx, h in enumerate(header):
            if h is None:
                continue
            norm = str(h).strip().lower().replace(" ", "")
            for n in names:
                if norm == n.lower().replace(" ", ""):
                    return idx
        return None

    part_i = _col("자재코드")
    desc_i = _col("자재명")
    qty_i = _col("수량")
    amount_i = _col("금액")
    hs_i = _col("HS code")
    origin_i = _col("원산지")
    so_i = _col("SO")
    wb.close()
    if so_i is None:
        raise ValueError("수출신고실적에서 SO 컬럼을 못 찾음")

    rows = []
    wb = openpyxl.load_workbook(EXPORT_DECLARATION_PATH, data_only=True, read_only=True)
    ws = wb["Sheet1"]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if so_i >= len(row) or row[so_i] is None:
            continue
        if str(row[so_i]).strip() != str(to_number).strip():
            continue

        def _get(i):
            return row[i] if i is not None and i < len(row) else None

        hs = _get(hs_i)
        hs_digits = "".join(ch for ch in str(hs or "") if ch.isdigit())
        origin = _get(origin_i)
        rows.append({
            "part_no": str(_get(part_i) or "").strip(),
            "description": str(_get(desc_i) or "").strip(),
            "qty": _get(qty_i),
            "amount": _get(amount_i),
            "hs_code": hs_digits[:HTS_DIGITS_FOR_FEDEX] or None,
            "origin": str(origin or "").strip().upper() or None,
        })
    wb.close()
    if not rows:
        raise ValueError(f"수출신고실적에서 TO {to_number} 행을 못 찾음 - CI 기입이 먼저 필요")
    log(f"[엑셀] TO {to_number} CI 데이터 {len(rows)}건: "
        + "; ".join(f"{r['part_no']}/{r['hs_code']}/{r['origin']}/{r['amount']}" for r in rows))
    return rows


# ==============================================================
# 7단계) 발송날짜 + 서비스 선택 (컷오프 13시/최고빠른 도착/최저가)
# ==============================================================
def _next_business_day(dt):
    """토/일/휴일(FEDEX_HOLIDAYS)을 건너뛴 다음 영업일."""
    from datetime import timedelta
    cur = dt
    while True:
        cur += timedelta(days=1)
        if cur.weekday() >= 5:
            continue
        if cur.strftime("%Y-%m-%d") in FEDEX_HOLIDAYS:
            continue
        return cur


def _kr_date_option(dt):
    """FedEx 발송날짜 select 옵션 형식('2026년 8월 25일 화요일')으로 바꾼다."""
    wd = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"][dt.weekday()]
    return f"{dt.year}년 {dt.month}월 {dt.day}일 {wd}"


def select_ship_date_and_service(driver) -> dict:
    """서비스 섹션에서 발송날짜/서비스를 고른다.

    규칙(2026-08-25 사용자 지시):
    - 실행 시각 < SERVICE_CUTOFF_HOUR(13시): 발송날짜 = 당일.
      이후: 다음 영업일(토/일/공휴일 제외).
    - 도착일은 최대한 빠른 날, 그 안에서 최저가 카드를 고른다.
    실측(2026-08-25): 발송날짜는 <select>, 서비스는 라디오 카드(그룹 헤더가
    도착일)다. 라디오의 value에 "FEDEX_INTERNATIONAL_PRIORITY 2026-08-26 오후
    5:00"처럼 서비스+도착시각이 들어 있고 카드 텍스트에 ₩요금이 있다."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
    from datetime import datetime

    # 1) 발송날짜 select
    now = datetime.now()
    want = now if now.hour < SERVICE_CUTOFF_HOUR else _next_business_day(now)
    want_txt = _kr_date_option(want)
    date_sel = None
    deadline = time.time() + 60
    while time.time() < deadline and date_sel is None:
        for s in driver.find_elements(By.TAG_NAME, "select"):
            try:
                if not s.is_displayed():
                    continue
                opts = [o.text.strip() for o in s.find_elements(By.XPATH, "./option")]
                if any("발송" in o or want_txt in o for o in opts) and any(
                        "년" in o and "일" in o for o in opts):
                    date_sel = s
                    break
            except Exception:
                continue
        if date_sel is None:
            time.sleep(2)
    if date_sel is None:
        _save_diag(driver, "shipdate_select")
        raise RuntimeError("발송날짜 select를 못 찾음")
    Select(date_sel).select_by_visible_text(want_txt)
    log(f"[FedEx] 발송날짜 선택: {want_txt} (실행 {now:%H:%M}, 컷오프 {SERVICE_CUTOFF_HOUR}시)")
    time.sleep(4)   # 카드 재로딩

    # 2) 서비스 카드 수집. 실측(2026-08-25): 라디오의 value는 "on"이고
    # **id**에 "FEDEX_INTERNATIONAL_PRIORITY 2026-08-26 오후 5:00"처럼
    # 서비스+도착시각이 들어 있다. 카드 텍스트에 ₩요금이 있다.
    cards = []
    deadline = time.time() + 60
    while time.time() < deadline and not cards:
        for r in driver.find_elements(By.CSS_SELECTOR, "input[type='radio']"):
            try:
                sig = f"{r.get_attribute('value') or ''} {r.get_attribute('id') or ''}"
                # 주의1: 라디오 input 자체는 Material 스타일 때문에 숨겨져 있고
                # 보이는 원은 장식 요소다 - input의 is_displayed()로 거르면 전부
                # 탈락한다. **카드(조상) 표시 여부**로 판정한다.
                # 주의2: id에 FEDEX가 없는 서비스 카드도 있다(2026-08-25 ILH
                # 실측: Economy 카드 누락) - id 필터 대신 카드 텍스트에
                # 'FedEx'+₩가 함께 있는지로 판정한다.
                node = r
                card_txt = ""
                card_el = None
                for _ in range(6):
                    node = node.find_element(By.XPATH, "..")
                    t = (node.text or "")
                    if "₩" in t and "FedEx" in t:
                        card_txt = t
                        card_el = node
                        break
                if card_el is None or not card_el.is_displayed():
                    continue
                m = re.search(r"₩\s*([\d,]+)", card_txt)
                price = int(m.group(1).replace(",", "")) if m else None
                cards.append({"value": sig, "price": price, "radio": r,
                              "text": card_txt, "el": card_el})
            except Exception:
                continue
        if not cards:
            time.sleep(2)
        else:
            # 같은 카드를 여러 조상 깊이로 중복 잡았으면 가장 안쪽(짧은 텍스트)만
            by_sig = {}
            for c in cards:
                key = c["value"]
                if key not in by_sig or len(c["text"]) < len(by_sig[key]["text"]):
                    by_sig[key] = c
            cards = list(by_sig.values())
    if not cards:
        _save_diag(driver, "service_cards")
        raise RuntimeError("서비스 카드를 못 찾음")

    # 3) 도착일 추출: value/id의 "2026-08-26" 또는 카드 텍스트의 도착일.
    # 2026-08-25 ILH(홍콩) 실측: 카드에 따라 value가 "undefined"로 나와 도착일을
    # 못 읽는 케이스가 있다 - 그런 카드는 도착일 미상으로 **선택 후보에서 빼고**,
    # 전부 미상이면 최저가로 선택한다(미상을 최단으로 오판해 요금이 다른 카드를
    # 고르는 사고를 막는다).
    def _arrival(card):
        for sig in (card["value"], card["text"]):
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", sig or "")
            if m:
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", sig or "")
            if m:
                return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        return None

    # 그룹 헤더("2026년 8월 27일 수요일까지 배송")를 문서 순서로 훑어 각 라디오에
    # 최근접 선행 헤더의 도착일을 배정한다(ILH처럼 value가 "undefined"인 카드 대응,
    # 2026-08-25 실측).
    header_dates = {}
    current = None
    for el in driver.find_elements(
            By.XPATH,
            "//*[contains(normalize-space(.),'배송') and string-length(normalize-space(.)) < 45]"
            " | //input[@type='radio']"):
        try:
            if el.tag_name.lower() == "input":
                sig = f"{el.get_attribute('value') or ''} {el.get_attribute('id') or ''}"
                if "FEDEX" in sig.upper():
                    header_dates[sig] = current
            else:
                t = (el.text or "").strip()
                m = re.search(r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일", t)
                if m:
                    current = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        except Exception:
            continue

    for c in cards:
        c["arrival"] = _arrival(c) or header_dates.get(c["value"])
    dated = [c for c in cards if c["arrival"]]
    undated = [c for c in cards if not c["arrival"]]
    if undated:
        log(f"  [경고] 도착일 미상 카드 {len(undated)}개 제외: "
            f"{[c['value'][:40] for c in undated]}")
    if dated:
        fastest = min(c["arrival"] for c in dated)
        pool = [c for c in dated if c["arrival"] == fastest]
    else:
        fastest = "미상"
        pool = cards
    best = min(pool, key=lambda c: (c["price"] if c["price"] is not None else float("inf")))
    log(f"[FedEx] 서비스 후보 {len(cards)}개 - 최단 도착 {fastest}, 선택: "
        f"{best['value'][:50]!r} ₩{best['price']:,}" if best['price'] else
        f"[FedEx] 서비스 후보 {len(cards)}개 - 최단 도착 {fastest}, 선택: {best['value'][:50]!r}")
    driver.execute_script("arguments[0].click();", best["radio"])
    time.sleep(3)
    return {"ship_date": want_txt, "service": best["value"], "price": best["price"],
            "arrival": fastest}


# ==============================================================
# 8단계) 패키지 내용물 (물품 등록 + 상업송장 업로드)
# ==============================================================
# 2026-08-27 사용자 지시: "품목설명란에 Medical Device Part도 항상 추가해줘
# 모든 항목에". 통관에서 품목 성격이 드러나야 하기 때문이라, CI의 품명 뒤에
# 항상 이 문구를 붙인다(이미 들어 있으면 중복해서 붙이지 않는다).
ITEM_DESC_SUFFIX = "Medical Device Part"


MERGED_CI_DIR = os.path.join(ROOT, "병합CI")


def _merge_pdfs(paths: list[str]) -> str:
    """여러 CI PDF를 한 파일로 합친다(FedEx 상업송장 슬롯이 1개라서).
    원본은 건드리지 않고 `병합CI` 폴더에 새 파일을 만든다."""
    from pypdf import PdfWriter

    os.makedirs(MERGED_CI_DIR, exist_ok=True)
    stems = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    out = os.path.join(MERGED_CI_DIR, f"{stems[0]}+{'+'.join(s.split()[-1] for s in stems[1:])}.pdf")
    writer = PdfWriter()
    for p in paths:
        writer.append(p)
    with open(out, "wb") as fh:
        writer.write(fh)
    writer.close()
    log(f"[CI] {len(paths)}장을 한 파일로 합침: {os.path.basename(out)}")
    return out


def _item_description(row: dict) -> str:
    base = (row.get("description") or "").strip()
    if not base:
        return ITEM_DESC_SUFFIX
    if ITEM_DESC_SUFFIX.lower() in base.lower():
        return base
    return f"{base}, {ITEM_DESC_SUFFIX}"



def fill_package_contents(driver, ci_rows: list[dict], ci_pdf_path,
                          packages: list[dict] | None = None,
                          is_rma: bool = False) -> None:
    """패키지 내용물 섹션: 발송 용도/물품 등록(CI 값)/상업송장 업로드.

    2026-08-25 실측 확정:
    - 발송 용도 select(상업용/선물/샘플/수리 및 반환/...) - Rebalance는 '상업용',
      RMA(본사 반송)는 '수리 및 반환'(2026-09-15 사용자 확정 - CI 통관문구
      "return to manufacturer (RMA), No commercial value"와 성격이 맞는 옵션).
    - '새 물품 추가' 버튼 -> 인라인 폼: 품목 설명(textarea)/HS 코드(자동완성 -
      **옵션은 "9018.90"처럼 점 찍힌 6자리**, 점 빼고 비교해 클릭)/순중량/수량
      (단위 PCS 기본)/세관 신고 금액(통화 KRW 기본)/제조 국가(영문 국가명 select).
    - 상업송장 방식 select에서 '직접 생성한 송장을 업로드하겠습니다'를 고르면
      file input(type=file)이 생긴다 - rebalance 파이프라인이 만든 최종 CI PDF를
      넣는다(전자상거래 문서로 첨부됨, 실측 확인).
    물품은 CI 행마다 하나씩 등록한다(파트가 여러 개인 TO 대비)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
    from selenium.webdriver.common.keys import Keys

    # 발송 용도 - RMA는 '수리 및 반환', 그 외(Rebalance)는 '상업용'
    purpose_text = "수리 및 반환" if is_rma else "상업용"
    lbl = driver.find_element(By.XPATH, "(//label[contains(normalize-space(.),'발송 용도')])[last()]")
    Select(driver.find_element(By.ID, lbl.get_attribute("for"))).select_by_visible_text(purpose_text)
    log(f"[FedEx] 발송 용도: {purpose_text}")
    time.sleep(1)

    def _js_fill(el, value):
        driver.execute_script("""
            var el = arguments[0], v = arguments[1];
            el.focus(); el.value = v;
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            el.blur();
        """, el, str(value))
        time.sleep(0.6)

    def _fill_by_label(label_text, value, occurrence="last"):
        pos = "last()" if occurrence == "last" else "1"
        lbl = driver.find_element(
            By.XPATH, f"(//label[contains(normalize-space(.),'{label_text}')])[{pos}]")
        el = driver.find_element(By.ID, lbl.get_attribute("for"))
        try:
            el.click(); el.clear()
        except Exception:
            pass
        el.send_keys(str(value))
        time.sleep(0.6)
        return el

    def _pick_hs_code(code6: str):
        """HS 자동완성에서 점 표기 옵션('9018.90')을 골라 선택한다."""
        hs_lbl = driver.find_element(
            By.XPATH, "(//label[contains(normalize-space(.),'HS 코드')])[last()]")
        hs = driver.find_element(By.ID, hs_lbl.get_attribute("for"))
        hs.click()
        hs.send_keys(Keys.CONTROL, "a")
        hs.send_keys(Keys.DELETE)
        time.sleep(0.4)
        hs.send_keys(code6)
        time.sleep(3)
        for p in driver.find_elements(By.CSS_SELECTOR, "[role='listbox']"):
            try:
                if not p.is_displayed():
                    continue
                for o in p.find_elements(By.CSS_SELECTOR, "[role='option']"):
                    t = (o.text or "").strip()
                    first = t.split()[0] if t else ""
                    if first.replace(".", "") == code6:
                        driver.execute_script("arguments[0].click();", o)
                        time.sleep(1.5)
                        return (hs.get_attribute("value") or "")
            except Exception:
                continue
        hs.send_keys(Keys.ESCAPE)
        return hs.get_attribute("value")

    # 순중량: 박스 **총**무게를 물품 수로 나눠 넣는다. 2026-08-25 실측 사고:
    # 0을 넣고 나중에 덮어쓰려다 검증("0kg 이상이어야 합니다"는 통과하지만
    # 실제로는 0kg 불가)에 걸려 다이얼로그가 안 닫혔다 - **처음부터 실제 값을
    # 넣는다**. 2박스 1품목이면 두 박스 무게의 합이 그 품목의 순중량이다
    # (예전엔 packages[0]만 봐서 2박스째 무게가 통째로 빠졌다).
    # 2026-09-15 실측 버그 수정: net_w는 물품 1개 단위 순중량이고 FedEx는
    # 저장 시 (순중량 x 수량)의 합으로 총중량 초과를 검증한다(사이드바 "총
    # 순중량"엔 줄별 무게를 그냥 더한 값만 보여서 안 드러남). 예전처럼 물품
    # "줄 수"로 나누면 수량>1인 줄에서 실제 배분 총합이 박스 총무게를 넘겨
    # "물품의 중량 합계는 총 발송물 중량을 초과할 수 없습니다"로 저장이 막힌다
    # (TO 7881974, 품목 3줄 중 1줄 수량=2에서 재현). 총 개수(수량 합)로 나눠야
    # (순중량 x 수량)의 합이 박스 총무게와 정확히 같아진다.
    packages = packages or []
    total_w = sum((p.get("weight") or 0) for p in packages)
    total_qty = sum((row.get("qty") or 1) for row in ci_rows)
    net_w = round(total_w / total_qty, 3) if (total_w and total_qty) else None
    if not net_w:
        _save_diag(driver, "net_weight")
        raise RuntimeError("물품 순중량을 못 정함 - packages에 박스 무게가 필요")
    log(f"[FedEx] 순중량 배분: 박스 총 {total_w}kg / 총 수량 {total_qty}개 = 개당 {net_w}kg")

    for idx, row in enumerate(ci_rows):
        # '새 물품 추가' - 첫 행은 빈 폼이 이미 열려 있을 수도 있다. 다만 라벨이
        # DOM에만 있고 숨겨져 있는 경우가 있다(2026-08-25 실측:
        # ElementNotInteractable) - **입력칸이 실제 표시돼 있을 때만** 열려 있다고
        # 본다.
        need_open = True
        try:
            lbl = driver.find_element(
                By.XPATH, "(//label[contains(normalize-space(.),'품목 설명')])[last()]")
            el = driver.find_element(By.ID, lbl.get_attribute("for"))
            need_open = not el.is_displayed()
        except Exception:
            need_open = True
        if need_open:
            # 2026-08-25 실측: 버튼이 렌더되기까지 시간이 걸리고, 텍스트가 자식
            # 요소에 나뉘어 있어 button 한정 검색으로는 못 잡을 수 있다 -
            # _click_first_visible(텍스트 매칭/최단 텍스트 우선/JS 클릭 폴백)으로
            # 넉넉히 기다린다.
            _click_first_visible(driver, ["새 물품 추가", "새물품추가", "Add New Item"], timeout=30)
            time.sleep(3)

        desc = _item_description(row)
        _fill_by_label("품목 설명", desc)
        hs6 = row.get("hs_code")
        hs_val = _pick_hs_code(hs6) if hs6 else ""
        log(f"  물품 {idx + 1}: {desc!r}, HS={hs_val!r}, 순중량={net_w}")
        _fill_by_label("순중량", net_w)
        qty = row.get("qty") or 1
        _fill_by_label("수량", qty)
        amount = row.get("amount")
        if amount is None:
            _save_diag(driver, "item_amount")
            raise RuntimeError("CI 금액이 없어 세관 신고 금액을 못 채움(추측 기입 금지)")
        _js_fill(_fill_by_label("세관 신고 금액", amount), amount)
        origin = row.get("origin")
        country = ORIGIN_CODE_TO_FEDEX.get(origin)
        if not country:
            _save_diag(driver, "origin_map")
            raise RuntimeError(f"원산지 코드 {origin!r}를 FedEx 국가명으로 못 바꿈 - "
                               f"ORIGIN_CODE_TO_FEDEX에 추가하세요")
        lbl = driver.find_element(By.XPATH, "(//label[contains(normalize-space(.),'제조 국가')])[last()]")
        Select(driver.find_element(By.ID, lbl.get_attribute("for"))).select_by_visible_text(country)
        time.sleep(0.6)

        # 저장(물품 폼 하단 primary '추가' - 헤더의 '저장' 아님)
        add_btns = [b for b in driver.find_elements(
            By.XPATH, "//button[normalize-space(.)='추가' and contains(@class,'primary')]")
            if b.is_displayed()]
        if not add_btns:
            _save_diag(driver, "item_add_btn")
            raise RuntimeError("물품 폼 '추가' 버튼을 못 찾음")
        driver.execute_script("arguments[0].click();", add_btns[-1])
        time.sleep(3)
        log(f"  물품 {idx + 1} 저장 완료")

    # 상업송장: 직접 생성한 송장 업로드 + CI PDF 첨부
    lbl = driver.find_element(By.XPATH, "(//label[contains(normalize-space(.),'상업송장을 어떻게')])[last()]")
    Select(driver.find_element(By.ID, lbl.get_attribute("for"))).select_by_visible_text(
        "직접 생성한 송장을 업로드하겠습니다.")
    time.sleep(2)
    paths = [ci_pdf_path] if isinstance(ci_pdf_path, str) else list(ci_pdf_path or [])
    if not paths:
        _save_diag(driver, "ci_pdf_missing")
        raise RuntimeError("업로드할 CI PDF가 지정되지 않음")
    for p in paths:
        if not os.path.exists(p):
            _save_diag(driver, "ci_pdf_missing")
            raise RuntimeError(f"업로드할 CI PDF가 없음: {p}")

    # 2026-08-27 실측: 상업송장 업로드 슬롯은 **1개**다(한 장 올리면 file input이
    # 사라지고 '파일 삭제'만 남는다). CI가 여러 장인 건(미국 7876545: Delivery
    # 2건 -> 9976051/9976055)은 한 PDF로 합쳐서 올린다.
    if len(paths) > 1:
        paths = [_merge_pdfs(paths)]

    # 업로드 후 화면 재렌더로 input이 stale이 될 수 있어 매번 다시 찾는다.
    for p in paths:
        finput = None
        deadline = time.time() + 20
        while time.time() < deadline and finput is None:
            els = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
            if els:
                finput = els[0]
            else:
                time.sleep(1)
        if finput is None:
            _save_diag(driver, "file_input")
            raise RuntimeError("송장 업로드 file input을 못 찾음")
        finput.send_keys(p)
        time.sleep(6)
        log(f"[FedEx] 상업송장 업로드(전자통관문서): {os.path.basename(p)}")

    # 올라간 파일명이 화면에 보이는지 확인한다(조용한 업로드 실패 방지).
    page = driver.page_source or ""
    missing = [os.path.basename(p) for p in paths
               if os.path.splitext(os.path.basename(p))[0] not in page]
    if missing:
        _save_diag(driver, "ci_upload_verify")
        raise RuntimeError(f"업로드한 CI가 화면에서 확인되지 않음: {missing}")
    log(f"[FedEx] 상업송장 {len(paths)}장 업로드 확인")


# ==============================================================
# 9단계) 픽업 예약
# ==============================================================
def _parse_kr_time(text: str):
    """'오후 4:30' / '오전 11:30' -> 분(0~1439). 못 읽으면 None."""
    m = re.search(r"(오전|오후)\s*(\d{1,2}):(\d{2})", str(text or ""))
    if not m:
        return None
    ampm, h, mi = m.group(1), int(m.group(2)), int(m.group(3))
    if ampm == "오전":
        h = 0 if h == 12 else h
    else:
        h = 12 if h == 12 else h + 12
    return h * 60 + mi


def _set_pickup_window(driver) -> None:
    """픽업 '가장 이른/늦은 시간'을 용마 마감에 맞춰 고른다(2026-09-04).

    - 가장 늦은 시간: PICKUP_LATEST_MIN(16:30) **이하 중 가장 늦은** 옵션.
      용마가 17시에 마감하므로 그 뒤 시각으로 잡으면 트럭이 이미 떠난 뒤다.
    - 가장 이른 시간: **픽업이 오늘일 때만** 13:00(또는 지금 시각) 이후로 민다.
      13시 이후 회차는 발송날짜가 다음 영업일이므로(SERVICE_CUTOFF_HOUR) 픽업도
      그날이고, 그때는 오늘 시각이 창을 좁힐 이유가 없어 FedEx 기본값을 둔다
      (2026-09-04 사용자 확인: 13시 이후 다음 영업일 규칙은 그대로 유지).
    - 두 값이 뒤집히지 않는지(이른 < 늦은) 마지막에 확인한다."""
    from datetime import datetime
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    def _sel(label_text):
        lbl = driver.find_element(
            By.XPATH, f"//label[contains(normalize-space(.),'{label_text}')]")
        return Select(driver.find_element(By.ID, lbl.get_attribute("for")))

    late = _sel("가장 늦은 시간")
    opts = [(o.text.strip(), _parse_kr_time(o.text)) for o in late.options]
    ok = [(t, v) for t, v in opts if v is not None and v <= PICKUP_LATEST_MIN]
    if not ok:
        raise RuntimeError(f"16:30 이하 '가장 늦은 시간' 옵션이 없음(옵션={[t for t,_ in opts]})")
    late_txt, late_min = max(ok, key=lambda x: x[1])
    if _parse_kr_time(late.first_selected_option.text) != late_min:
        late.select_by_visible_text(late_txt)
        time.sleep(1.5)
    log(f"[FedEx] 픽업 가장 늦은 시간: {late_txt!r} (용마 마감 "
        f"{YONGMA_PICKUP_DEADLINE_HOUR}시)")

    # 픽업이 오늘인지 확인 - 오늘이 아니면 지금 시각으로 창을 좁히지 않는다.
    pickup_is_today = False
    try:
        d_txt = _sel("픽업 날짜").first_selected_option.text
        pickup_is_today = _kr_date_option(datetime.now()) in d_txt
    except Exception as e:
        log(f"  [정보] 픽업 날짜 판독 실패({e}) - 오늘이 아닌 것으로 보고 진행")

    early = _sel("가장 이른 시간")
    now = datetime.now()
    now_min = now.hour * 60 + now.minute
    early_txt = early.first_selected_option.text.strip()
    early_min = _parse_kr_time(early_txt)
    # 픽업이 오늘이면 지금 시각 이후로, 다음날이면 아침 8시부터
    # (2026-09-09 사용자 지시: "다음날로 잡으면 오전 8시부터 오후 4시 30분으로").
    # 예전엔 다음날일 때 FedEx 기본값을 그대로 뒀는데 12:00으로 잡혀서 오전
    # 픽업 기회를 놓쳤다(실측: 2026-09-09 TO 7881469, 9/10 12:00~16:30).
    target = None
    if pickup_is_today:
        if now_min >= PICKUP_AFTERNOON_EARLIEST_MIN:
            target = max(PICKUP_AFTERNOON_EARLIEST_MIN, now_min)
    else:
        target = PICKUP_NEXTDAY_EARLIEST_MIN
    if target is not None:
        cands = [(o.text.strip(), _parse_kr_time(o.text)) for o in early.options]
        cands = [(t, v) for t, v in cands if v is not None and target <= v < late_min]
        if not cands:
            raise RuntimeError(
                f"{target // 60}:{target % 60:02d} 이후 ~ {late_txt} 사이의 "
                f"'가장 이른 시간' 옵션이 없음")
        early_txt, early_min = min(cands, key=lambda x: x[1])
        if _parse_kr_time(early.first_selected_option.text) != early_min:
            early.select_by_visible_text(early_txt)
            time.sleep(1.5)
    log(f"[FedEx] 픽업 가장 이른 시간: {early_txt!r} "
        f"(실행 {now:%H:%M}, 픽업일={'당일' if pickup_is_today else '익일'})")

    if early_min is None or early_min >= late_min:
        raise RuntimeError(f"픽업 시간대가 뒤집힘: {early_txt} ~ {late_txt}")


def select_pickup_reservation(driver, mode: str = "reserve") -> None:
    """픽업/방문 접수 섹션에서 선택지를 고른다.

    mode="reserve"     : '픽업 예약 진행'(기본) - 픽업을 새로 잡는다
    mode="label_only"  : '운송장만 생성' - 픽업을 따로 잡지 않는다
      2026-08-27 사용자 지시: "이렇게 픽업예약 그날에 진행한 경우엔 픽업 예약
      따로 안해도 돼" - 같은 날 이미 픽업이 잡혀 있으면 기사님이 어차피 오므로
      두 번 잡지 않는다.

    실측(2026-08-25): 3개 선택지 - FedEx 접수처 방문 / 운송장만 생성 / 픽업 예약
    진행. 라디오 id가 한글('픽업 예약 진행')이고, 클릭 직후 화면이 다시 그려져
    stale이 나므로 재탐색한다. **픽업 폼(날짜/시간대) 세부 기입은 아직 실측 전** -
    선택까지만 하고 폼은 실제 케이스에서 확정한다."""
    from selenium.webdriver.common.by import By

    # 라디오 id가 화면 문구 전체다. 2026-08-27 실측한 실제 id 3종:
    #   'FedEx 접수처를 방문해 발송물을 접수하겠습니다'
    #   '운송장만 생성 하고 픽업 예약은 별도로 진행'
    #   '픽업 예약 진행'
    # 문구가 길고 바뀌기 쉬워 **부분 일치**로 찾는다(가장 짧은 id 우선).
    want = "픽업 예약 진행" if mode == "reserve" else "운송장만 생성"

    def _click_radio():
        # 섹션 렌더에 시간이 걸린다(실측) - 최대 30초 폴링.
        deadline = time.time() + 30
        while True:
            els = driver.find_elements(By.XPATH, f"//input[@id='{want}']")
            if not els:
                cands = []
                for e in driver.find_elements(By.CSS_SELECTOR, "input[type='radio']"):
                    try:
                        eid = e.get_attribute("id") or ""
                    except Exception:
                        continue
                    if want in eid:
                        cands.append((len(eid), eid, e))
                if cands:
                    cands.sort(key=lambda x: x[0])
                    log(f"[FedEx] 픽업 선택지 부분일치: {cands[0][1]!r}")
                    els = [cands[0][2]]
            if els:
                r = els[0]
                driver.execute_script("""
                    var r = arguments[0];
                    r.click();
                    r.dispatchEvent(new Event('change', {bubbles: true}));
                    r.dispatchEvent(new Event('input', {bubbles: true}));
                """, r)
                return r
            if time.time() >= deadline:
                # 문구가 바뀌었을 수 있으니 실제 선택지를 로그에 남겨 판단하게 한다.
                ids = []
                for e in driver.find_elements(By.CSS_SELECTOR, "input[type='radio']"):
                    try:
                        ids.append(e.get_attribute("id"))
                    except Exception:
                        continue
                _save_diag(driver, "pickup_radio")
                raise RuntimeError(f"'{want}' 라디오가 30초 안에 안 뜸 "
                                   f"(화면의 라디오 id들: {ids})")
            time.sleep(2)

    _click_radio()
    time.sleep(5)
    # 클릭 후 화면 재렌더로 stale이 나는 건 정상(실측) - 선택 여부는 다시 읽어 확인.
    try:
        r = next(e for e in driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                 if want in (e.get_attribute("id") or ""))
        log(f"[FedEx] '{want}' 선택: checked={r.is_selected()}")
    except Exception:
        log(f"[FedEx] '{want}' 선택(재확인 실패 - 화면 재렌더로 추정, 진행)")

    if mode != "reserve":
        log("[FedEx] 픽업은 따로 잡지 않습니다(같은 날 픽업이 이미 예약된 경우)")
        return

    # 픽업 폼(2026-08-25 실측 확정): 픽업 날짜/가장 이른 시간/가장 늦은 시간
    # select가 기본값으로 채워진다(발송날짜 당일, 12:00~18:00). 픽업 날짜는
    # 발송날짜와 같으므로 그대로 두고, **시간대만 용마 마감에 맞춰 다시 고른다**
    # (PICKUP_LATEST_MIN 주석 참고). 주소는 발송인 주소가 기본.
    from selenium.webdriver.support.ui import Select
    try:
        lbl = driver.find_element(
            By.XPATH, "//label[contains(normalize-space(.),'픽업 날짜')]")
        el = driver.find_element(By.ID, lbl.get_attribute("for"))
        log(f"[FedEx] 픽업 픽업 날짜: {Select(el).first_selected_option.text!r}")
    except Exception as e:
        log(f"  [정보] 픽업 날짜 읽기 생략({exc_detail(e)})")

    try:
        _set_pickup_window(driver)
    except Exception as e:
        # 시간대를 못 고르면 기본값(18시까지)이 남는데, 그건 용마가 못 받는
        # 창이라 조용히 넘어가면 안 된다.
        _save_diag(driver, "pickup_window")
        raise RuntimeError(
            f"픽업 시간대를 용마 마감에 맞춰 설정하지 못함: {exc_detail(e)}")


# ==============================================================
# 9-2단계) 청구서 세부정보 (운송비 청구 대상=수취인 + FedEx 고객번호)
# ==============================================================
def lookup_fedex_account(country_code: str) -> str:
    """Address 시트에서 이 목적지의 FedEx 고객번호(H열)를 읽는다.

    2026-08-25 사용자 지시: 청구서 세부정보의 운송비 청구 대상을 수취인으로
    하고, 여기서 번호를 가져와 FEDEX 고객번호 칸에 기입한다.
    시트 실측(2026-08-25): A열=국가코드, H열=FedEx, I열=DHL.
    - EMEA 행은 "FBC: 626499830 / FBS: 680928975"처럼 한 칸에 둘이 있어
      국가코드(FBC/FBS)로 골라낸다.
    - RMA(FA LAB/Refurb)는 목적지가 본사(미국)라 WAY 번호를 쓴다."""
    import openpyxl

    cc = normalize_country_code(country_code)
    if cc == "FA LAB":          # 본사 반송 = 미국 수취인
        cc = "WAY"
    # Address 시트에는 FBC/FBS 행이 없고 EMEA 한 행에 "FBC: .../FBS: ..."로
    # 들어 있다(2026-08-25 실측) - 행 키를 EMEA로 바꾸고 아래에서 접두어로 고른다.
    row_key = "EMEA" if cc in ("FBC", "FBS") else cc

    wb = openpyxl.load_workbook(CONTACT_TEMPLATE_PATH, data_only=True, read_only=True)
    if "Address" not in wb.sheetnames:
        raise ValueError("Address 시트가 없음")
    ws = wb["Address"]
    result = None
    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row or row[0] is None:
            continue
        if str(row[0]).strip().upper() != row_key:
            continue
        raw = row[7]   # H열 = FedEx
        if raw is None or not str(raw).strip():
            continue
        raw = str(raw).strip()
        if ":" in raw:
            # "FBC: 626499830\nFBS: 680928975" 형태 - 국가코드로 고른다
            for part in raw.split("\n"):
                if ":" not in part:
                    continue
                key, _, num = part.partition(":")
                if key.strip().upper() == cc:
                    result = num.strip()
                    break
        else:
            result = raw
        if result:
            break
    wb.close()
    if not result:
        raise ValueError(f"Address 시트에서 {cc}의 FedEx 고객번호를 못 찾음")
    log(f"[엑셀] {cc} FedEx 고객번호: {result}")
    return result


def fill_billing_details(driver, country_code: str) -> None:
    """청구서 세부정보 섹션: 운송비 청구 대상=수취인, FEDEX 고객번호 기입.

    사용자 실측 스크린샷(2026-08-25): 운송비 청구 대상(기본 '내 고객번호')을
    '수취인'으로 바꾸면 FEDEX 고객번호 입력칸이 생긴다 - Address 시트의 번호를
    넣는다. 알림 섹션은 건너뛴다(사용자 확인)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    account = lookup_fedex_account(country_code)

    # 운송비 청구 대상 -> 수취인
    lbl = driver.find_element(By.XPATH, "//label[contains(normalize-space(.),'운송비 청구 대상')]")
    sel = Select(driver.find_element(By.ID, lbl.get_attribute("for")))
    sel.select_by_visible_text("수취인")
    log("[FedEx] 운송비 청구 대상: 수취인")
    time.sleep(2)

    # FEDEX 고객번호 입력칸은 운송비/관세 두 곳에 있다(2026-08-25 실측) - 선택
    # 직후 렌더되므로 최대 15초 폴링하고, 보이는 빈 칸을 전부 같은 번호로 채운다.
    filled = 0
    deadline = time.time() + 15
    while time.time() < deadline and not filled:
        # 주의: 라벨 텍스트에 non-breaking space가 섞여 있을 수 있어(2026-08-25
        # 실측 추정) 'FEDEX 고객번호' 전체가 아닌 '고객번호'로 검색하고 파이썬에서
        # FEDEX 여부를 확인한다.
        for lbl in driver.find_elements(By.XPATH, "//label[contains(normalize-space(.),'고객번호')]"):
            try:
                if "fedex" not in (lbl.text or "").lower():
                    continue
                fid = lbl.get_attribute("for")
                if not fid:
                    continue
                el = driver.find_element(By.ID, fid)
                if el.is_displayed() and not (el.get_attribute("value") or "").strip():
                    # 네이티브 클릭이 오버레이에 가로채는 경우가 있다(실측) -
                    # JS로 값 세팅 + input/change 이벤트를 발사한다.
                    driver.execute_script("""
                        var el = arguments[0], v = arguments[1];
                        el.focus(); el.value = v;
                        el.dispatchEvent(new Event('input', {bubbles: true}));
                        el.dispatchEvent(new Event('change', {bubbles: true}));
                        el.blur();
                    """, el, account)
                    filled += 1
                    log(f"  FEDEX 고객번호 기입(id={fid}): {account}")
                    time.sleep(0.6)
            except Exception:
                continue
        if not filled:
            time.sleep(1.5)
    if not filled:
        _save_diag(driver, "fedex_account_field")
        raise RuntimeError("FEDEX 고객번호 입력칸을 못 찾음")
    log(f"[FedEx] FEDEX 고객번호 {filled}칸 기입: {account}")


# ==============================================================
# 10-2단계) 최종 생성('완료') + 라벨 PDF 확보 + Tracking 번호
# ==============================================================
# 2026-08-27 사용자 지시("실제로 발송물도 만들어줘 ... 라벨까지 첨부해서 메일
# 보내야지")로 자동화 범위를 요약 보기 -> **최종 생성**까지 넓혔다.
# 그 전까지는 되돌릴 수 없다는 이유로 의도적으로 사람이 눌렀다.
LABEL_FOLDER_PATH = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\12. 수출\FedEx 라벨"
)
DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")
# FedEx 트래킹 번호는 12자리가 기본이다(예: 876034602894).
_TRACKING_RE = re.compile(r"\b(\d{12})\b")


def _pdf_snapshot(folder: str) -> set:
    try:
        return {f for f in os.listdir(folder) if f.lower().endswith(".pdf")}
    except Exception:
        return set()


def confirm_shipment_and_capture_label(driver, to_number: str, country_code: str,
                                       timeout: float = 240.0) -> dict:
    """요약 화면의 '완료'를 눌러 **발송물을 실제로 생성**하고, 나온 라벨 PDF와
    Tracking 번호를 확보한다.

    - 라벨은 브라우저 다운로드로 떨어지므로 Downloads 폴더의 새 PDF를 감시해
      잡고, `FedEx 라벨` 폴더로 옮겨 보관한다(파일명에 TO#/Tracking 포함).
    - Tracking 번호는 생성 직후 화면 텍스트에서 12자리 숫자로 뽑는다.
    - **되돌릴 수 없는 지점이라** 여기서부터는 실패해도 다시 누르지 않는다
      (중복 발송물 생성 방지) - 실패 시 화면을 남기고 사람이 확인한다.
    반환: {"tracking": str|None, "label_path": str|None}"""
    from selenium.webdriver.common.by import By

    os.makedirs(LABEL_FOLDER_PATH, exist_ok=True)

    btns = [b for b in driver.find_elements(By.XPATH, "//button[normalize-space(.)='완료']")
            if b.is_displayed()]
    if not btns:
        _save_diag(driver, "confirm_button")
        raise RuntimeError("요약 화면에서 '완료' 버튼을 못 찾음")
    log("[FedEx] === 최종 '완료' 클릭 - 발송물을 실제로 생성합니다 ===")
    driver.execute_script("arguments[0].click();", btns[0])

    # 1) '발송물 생성 성공' 화면을 **지금 탭에서** 기다린다.
    #    2026-08-27 사고: 예전엔 열린 탭을 전부 훑어 12자리 숫자를 찾았는데,
    #    공유 Edge에 떠 있던 SharePoint 탭의 숫자(876290411899)를 AWB로 잘못
    #    집어 실적/APAC에 틀린 번호를 기입했다. **다른 탭은 절대 보지 않는다.**
    deadline = time.time() + timeout
    body = ""
    while time.time() < deadline:
        try:
            body = driver.find_element(By.TAG_NAME, "body").text or ""
        except Exception as e:
            if is_session_dead_error(e):
                raise
            body = ""
        if "발송물 생성 성공" in body:
            break
        time.sleep(3)
    else:
        _save_diag(driver, "after_confirm_no_success")
        raise RuntimeError("'발송물 생성 성공' 화면을 확인 못 함 - 생성 여부를 "
                           "FedEx 화면에서 직접 확인하세요(중복 생성 방지를 위해 "
                           "자동 재시도하지 않습니다)")
    _save_diag(driver, "after_confirm")

    # 2) 배송 조회 ID(=AWB)와 픽업 ID를 라벨 문구 기준으로 정확히 뽑는다.
    m = re.search(r"배송 조회 ID\s*\n\s*(\d{10,14})", body)
    tracking = m.group(1) if m else None
    m2 = re.search(r"픽업 ID\s*\n\s*(\S+)", body)
    pickup_id = m2.group(1) if m2 else None
    if not tracking:
        _save_diag(driver, "no_tracking_on_success")
        raise RuntimeError("생성은 됐는데 '배송 조회 ID'를 못 읽었습니다 - "
                           "화면에서 확인 후 track 모드로 기입하세요")
    log(f"[FedEx] 발송물 생성 성공: AWB {tracking}"
        + (f", 픽업 ID {pickup_id}" if pickup_id else " (픽업 ID 없음)"))

    # 3) 라벨 다운로드: 화면 하단의 큰 '다운로드' 버튼(button 태그)을 누르면
    #    바로 받아진다(2026-08-27 사용자 안내 + 실측). 같은 문구의 <a>도 있어
    #    **button만** 고른다.
    before_pdfs = _pdf_snapshot(DOWNLOAD_DIR)
    label_src = None
    dl = [b for b in driver.find_elements(By.XPATH, "//button[normalize-space(.)='다운로드']")
          if b.is_displayed()]
    if not dl:
        log("  [경고] 라벨 '다운로드' 버튼을 못 찾음")
        _save_diag(driver, "label_download_btn")
    else:
        driver.execute_script("arguments[0].click();", dl[-1])
        log("[FedEx] 라벨 '다운로드' 클릭")
        wait_until = time.time() + 90
        while time.time() < wait_until:
            time.sleep(2)
            new_pdfs = _pdf_snapshot(DOWNLOAD_DIR) - before_pdfs
            done = [x for x in new_pdfs
                    if not os.path.exists(os.path.join(DOWNLOAD_DIR, x + ".crdownload"))]
            if done:
                label_src = os.path.join(
                    DOWNLOAD_DIR,
                    sorted(done, key=lambda x: os.path.getmtime(
                        os.path.join(DOWNLOAD_DIR, x)))[-1])
                break

    label_path = None
    if label_src:
        label_path = os.path.join(
            LABEL_FOLDER_PATH, f"FedEx Label KRP-{country_code} {to_number} {tracking}.pdf")
        shutil.copy2(label_src, label_path)
        log(f"[FedEx] 라벨 보관: {os.path.basename(label_path)}")
    else:
        log("  [경고] 라벨 PDF를 자동으로 못 받았습니다 - FedEx 화면에서 직접 내려받아야 합니다")
    return {"tracking": tracking, "label_path": label_path, "pickup_id": pickup_id}


# ==============================================================
# 11단계) Tracking 번호 후처리 (SharePoint + 수출신고실적)
# ==============================================================
# FedEx arrange(라벨 생성)가 끝나면:
#   1. SharePoint APAC Stock Movements의 해당 TO 행들에 Tracking Number 기입
#   2. 수출신고실적의 B/L번호 칸에 같은 번호 기입
# 2026-08-25 사용자 지시. 라벨이 나온 뒤 사람이 실행한다:
#   python fedex_ship_watcher.py track <TO#> <FedEx Tracking번호>
# (rebalance_watcher 쪽 코드는 건드리지 않는다 - 이 파일에 독립 구현)

SHAREPOINT_SITE_PATH = "/sites/APACOperation"
SHAREPOINT_LIST_TITLE = "APAC Stock Movements"
SHAREPOINT_STOCK_MOVEMENTS_URL = (
    "https://syneron.sharepoint.com/sites/APACOperation/Lists/"
    "APAC%20Stock%20Movements/AllItems.aspx"
)

# SharePoint REST 기입(브라우저 세션의 fetch 사용 - rebalance_watcher의
# Delivery# 기입과 같은 방식). Tracking 컬럼의 내부 이름은 시트마다 다를 수
# 있어 먼저 리스트 필드에서 Title에 'Tracking'이 들어가는 것을 찾아 쓴다.
# 숫자형 컬럼이면 Number로 변환해 보낸다.
_SP_WRITE_TRACKING_JS = r"""
var cb = arguments[arguments.length-1];
var TO = arguments[0], VAL = arguments[1];
var site = arguments[2], listTitle = arguments[3];
var FIELD = arguments[4];            // 기입할 필드 Title(예: 'Tracking', 'Status')
var L = "getbytitle('" + listTitle + "')";
var H = {'Accept': 'application/json;odata=nometadata'};
(async function(){
  try{
    var flds = await (await fetch(site + '/_api/web/lists/' + L +
        '/fields?$select=Title,InternalName,TypeAsString,ReadOnlyField', {headers:H})).json();
    var tf = null, exact = null;
    (flds.value||[]).forEach(function(f){
      if (f.ReadOnlyField) return;
      if (f.Title === FIELD) { if (!exact) exact = f; }
      else if (!tf && f.Title.indexOf(FIELD) >= 0) tf = f;
    });
    tf = exact || tf;                 // 정확히 같은 이름을 우선한다
    if (!tf) { cb('ERR: ' + FIELD + ' 필드를 못 찾음'); return; }
    var q = site + '/_api/web/lists/' + L + "/items?$select=Id,TO_x0023_," +
            tf.InternalName + "&$filter=TO_x0023_%20eq%20" + TO;
    var rj = await (await fetch(q, {headers:H})).json();
    var items = rj.value || [];
    var before = items.map(function(x){ return {Id: x.Id, V: x[tf.InternalName]}; });
    var ctx = await (await fetch(site + '/_api/contextinfo', {method:'POST', headers:H})).json();
    var digest = ctx.FormDigestValue;
    var writes = [];
    for (var i = 0; i < items.length; i++) {
      if (String(items[i][tf.InternalName] || '') === String(VAL)) {
        writes.push({Id: items[i].Id, status: 'skip'});
        continue;
      }
      var body = {};
      body[tf.InternalName] = (tf.TypeAsString === 'Number') ? Number(VAL) : VAL;
      var res = await fetch(site + '/_api/web/lists/' + L + '/items(' + items[i].Id + ')', {
        method: 'POST',
        headers: {'Accept':'application/json;odata=nometadata',
                  'Content-Type':'application/json;odata=nometadata',
                  'X-RequestDigest': digest, 'X-HTTP-Method':'MERGE', 'IF-MATCH':'*'},
        body: JSON.stringify(body)
      });
      writes.push({Id: items[i].Id, status: res.status});
    }
    var rj2 = await (await fetch(q, {headers:H})).json();
    var after = (rj2.value||[]).map(function(x){ return {Id: x.Id, V: x[tf.InternalName]}; });
    cb(JSON.stringify({field: tf.InternalName, before: before, writes: writes, after: after}));
  } catch(e) { cb('ERR: ' + (e && e.message ? e.message : e)); }
})();
"""


def _write_sp_field(driver, to_number: str, value: str, field_title: str,
                    label: str) -> None:
    """APAC Stock Movements에서 이 TO의 **모든 행**에 한 필드를 기입하고 재조회로
    확인한다. 항목이 하나도 없거나 일부만 기입되면 중단한다.
    (2026-09-04: Tracking 전용이던 것을 필드명 파라미터화 - Status도 같은 방식으로
     기입한다. 사용자 지시: "tracking number 기입하면서 status도 shipped로 바꿔줘")"""
    import json as _json

    if SHAREPOINT_SITE_PATH not in (driver.current_url or ""):
        driver.get(SHAREPOINT_STOCK_MOVEMENTS_URL)
        time.sleep(6)
    driver.set_script_timeout(120)
    raw = driver.execute_async_script(
        _SP_WRITE_TRACKING_JS, str(to_number), str(value),
        SHAREPOINT_SITE_PATH, SHAREPOINT_LIST_TITLE, field_title)
    if isinstance(raw, str) and raw.startswith("ERR: "):
        raise RuntimeError(f"SharePoint {label} 기입 실패: {raw[5:]}")
    data = _json.loads(raw)
    after = data.get("after", [])
    writes = data.get("writes", [])
    bad = [w for w in writes if isinstance(w.get("status"), int) and w["status"] >= 400]
    log(f"[SharePoint] TO {to_number} 항목 {len(after)}개, 필드={data.get('field')}, "
        f"기입 결과: {writes}")
    if not after:
        raise RuntimeError(f"SharePoint에서 TO {to_number} 항목을 못 찾음")
    if bad:
        raise RuntimeError(f"SharePoint {label} 기입 실패한 행 있음: {bad}")
    ok = [x for x in after if str(x.get("V") or "") == str(value)]
    if len(ok) < len(after):
        raise RuntimeError(f"SharePoint TO {to_number}: {len(after)}개 중 {len(ok)}개만 "
                           f"{label}={value} 확인됨 (재조회: {after})")
    log(f"[SharePoint] TO {to_number} {len(ok)}/{len(after)}행 {label}={value} 기입 확인")


def write_tracking_to_sharepoint(driver, to_number: str, tracking_no: str) -> None:
    _write_sp_field(driver, to_number, tracking_no, "Tracking", "Tracking")


# 출고 완료 시 SharePoint Status에 넣는 값(실측 확인된 선택지: New/@Warehouse/Shipped)
SHAREPOINT_SHIPPED_STATUS = "Shipped"


def write_status_to_sharepoint(driver, to_number: str,
                               status: str = SHAREPOINT_SHIPPED_STATUS) -> None:
    _write_sp_field(driver, to_number, status, "Status", "Status")


def _backup_before_write(path: str) -> str:
    """엑셀 수정 전 백업 사본(.bak_타임스탬프)을 만들고 오래된 것은 3개만 남긴다
    (rebalance_watcher의 같은 이름 함수와 같은 규칙 - 이 파일에 독립 구현)."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{path}.bak_{ts}"
    shutil.copy2(path, backup_path)
    log(f"백업 생성: {backup_path}")
    try:
        folder = os.path.dirname(path) or "."
        prefix = os.path.basename(path) + ".bak_"
        olds = sorted(
            f for f in os.listdir(folder)
            if f.startswith(prefix) and re.fullmatch(r"\d{8}_\d{6}", f[len(prefix):])
        )
        for name in olds[:-3]:
            os.remove(os.path.join(folder, name))
            log(f"오래된 백업 정리: {name}")
    except Exception as e:
        log(f"[정보] 백업 정리 생략({e})")
    return backup_path



# 2026-09-11 도입 시 "RMA 포함, Purpose는 안 가림"이라고 문서화됐지만 실제
# 조건은 Destination=="WAY"뿐이었다. RMA(본사 반송)는 수출신고실적에
# Destination="FA LAB"로 기입되므로([[rebalance-rma-branch]]) 그 조건으로는
# 절대 안 걸린다 - 2026-09-16 코드 감사로 발견(실사례 없이 문서만 사실이던
# 경우, ship_confirm 확인 누락 사고와 같은 패턴). RMA도 목적지가 미국
# 본사(Marlborough)라 오라클 Tracking# 기입 대상이 맞으므로 여기에 포함한다.
_ORACLE_TRACKING_DESTINATIONS = {"WAY", "FA LAB"}


def update_export_declaration_bl(to_number: str, tracking_no: str) -> tuple[int, set[str]]:
    """수출신고실적에서 SO=TO# 행 전부의 B/L번호 칸을 tracking_no로 채운다.
    반환: (수정한 행 수(0이면 예외), 이 중 Destination이 WAY/FA LAB(RMA)인
    행들의 Delivery Number 집합 - 오라클 Manage Shipments Tracking # 후속
    기입 대상 판단용, 2026-09-11 사용자 지시)."""
    import openpyxl

    _backup_before_write(EXPORT_DECLARATION_PATH)
    wb = openpyxl.load_workbook(EXPORT_DECLARATION_PATH)
    ws = wb["Sheet1"]
    header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())

    def _col(*names):
        for idx, h in enumerate(header):
            if h is None:
                continue
            norm = str(h).strip().lower().replace(" ", "")
            for n in names:
                if norm == n.lower().replace(" ", ""):
                    return idx
        return None

    so_i = _col("SO")
    bl_i = _col("B/L번호", "BL번호", "B_L번호")
    dest_i = _col("Destination")
    dn_i = _col("Delivery Number", "DeliveryNumber")
    if so_i is None or bl_i is None:
        raise ValueError(f"수출신고실적 컬럼을 못 찾음(SO={so_i}, B/L번호={bl_i})")

    updated = 0
    way_shipment_nos: set[str] = set()
    for row in ws.iter_rows(min_row=2):
        if so_i >= len(row):
            continue
        v = row[so_i].value
        if v is None or str(v).strip() != str(to_number).strip():
            continue
        ws.cell(row=row[0].row, column=bl_i + 1, value=str(tracking_no))
        updated += 1
        if dest_i is not None and dn_i is not None and dest_i < len(row) and dn_i < len(row):
            dest = str(row[dest_i].value or "").strip()
            dn_raw = str(row[dn_i].value or "").strip()
            if dest in _ORACLE_TRACKING_DESTINATIONS and dn_raw:
                for dn in re.split(r"[\/,]", dn_raw):
                    dn = dn.strip()
                    if dn:
                        way_shipment_nos.add(dn)
    if not updated:
        wb.close()
        raise ValueError(f"수출신고실적에서 TO {to_number} 행을 못 찾음 - "
                         f"B/L번호 기입 실패(행이 없음)")
    wb.save(EXPORT_DECLARATION_PATH)
    log(f"[엑셀] 수출신고실적 TO {to_number} {updated}행 B/L번호={tracking_no} 기입")
    return updated, way_shipment_nos


def update_tracking_number(to_number: str, tracking_no: str) -> None:
    """FedEx arrange 완료 후 처리: SharePoint Tracking Number + 수출신고실적
    B/L번호 + (WAY향이면) 오라클 Manage Shipments의 Tracking #까지 같은 번호로
    채운다(순서: 엑셀 먼저 - 브라우저 실패와 무관하게 이력은 남긴다).

    2026-09-11 사용자 지시: "미국(WAY)으로 나가는 FedEx 건은 오라클 Shipment의
    Tracking #에도 같은 AWB를 넣어야 한다" - CI/SharePoint 뒤에 이어지는 마지막
    단계로 추가. 대상은 WAY만(RMA 포함, Purpose 안 가림) - 수출신고실적에서 이
    TO의 행 중 Destination=WAY인 것의 Delivery Number(=오라클 Shipment 번호)로
    판단한다. 오라클 기입이 실패해도 SharePoint/엑셀은 이미 끝났으니 여기서는
    막지 않고 알림만 남긴다(다른 목적지 자동화를 이 신규 기능 하나 때문에
    깨뜨리지 않기 위함)."""
    tracking_no = str(tracking_no).strip()
    if not tracking_no.isdigit():
        raise ValueError(f"Tracking 번호가 숫자가 아님: {tracking_no!r}")
    _, way_shipment_nos = update_export_declaration_bl(to_number, tracking_no)

    ensure_edge_running()
    driver = get_fedex_driver()
    try:
        write_tracking_to_sharepoint(driver, to_number, tracking_no)
        # 2026-09-04 사용자 지시: Tracking을 넣는 시점이 곧 출고 확정이므로
        # Status도 Shipped로 바꾼다. Tracking 기입이 성공한 뒤에만 바꾼다
        # (Tracking 없이 Shipped로만 바뀌면 추적이 안 되는 행이 남는다).
        write_status_to_sharepoint(driver, to_number)
    finally:
        close_driver(driver)
    log(f"[완료] TO {to_number} Tracking {tracking_no} 후처리 끝 "
        f"(SharePoint Tracking+Status=Shipped, 수출신고실적)")

    for shipment_no in sorted(way_shipment_nos):
        try:
            sys.path.insert(0, ROOT)
            from oracle_shipment_tracking import write_tracking_number_to_oracle_shipment
            write_tracking_number_to_oracle_shipment(shipment_no, tracking_no)
            log(f"[완료] Shipment {shipment_no}: 오라클 Manage Shipments Tracking # 기입")
        except Exception as e:
            log(f"[경고] Shipment {shipment_no}: 오라클 Tracking # 기입 실패({exc_detail(e)}) - "
                f"SharePoint/엑셀은 이미 반영됨, 오라클은 수동 확인 필요")
            send_alert(
                f"[확인 필요] TO {to_number} Shipment {shipment_no} - 오라클 Tracking # 기입 실패",
                f"TO: {to_number}\nShipment: {shipment_no}\nAWB: {tracking_no}\n\n{exc_detail(e)}\n\n"
                f"SharePoint/수출신고실적 B/L번호는 이미 기입됐습니다. 오라클 Manage Shipments에서 "
                f"이 Shipment의 Tracking # 필드만 수동으로 확인/기입해주세요.")



# ==============================================================
# 10단계) 라벨 -> 용마 답장 초안에 첨부/발송 (라벨 생성 후 호출)
# ==============================================================
def send_label_to_yongma_draft(to_number: str, label_pdf_path: str, *, send: bool = False):
    """발송 라벨을 **기존 용마 답장 초안**(rebalance_watcher가 CI 첨부까지 해서
    Drafts에 저장해둔 것)에 붙여 넣는다.

    2026-08-25 사용자 지시: "예약 잡는거 다 되면 발송라벨 용마 답장에 넣어서
    답장해주면 돼. 초안으로 저장되어있는거 발송해주면 될듯. 보통은 CI만
    들어가있으니까."

    - 초안 찾기: Outlook 임시보관함에서 제목에 TO#가 있는 메일.
    - 동작: 라벨 PDF 첨부 추가. send=True면 발송, False면 초안 갱신만(기본).
      외부 발송이므로 기본은 초안 갱신만 두고, 실측 후 자동 발송으로 전환한다."""
    import win32com.client

    if not os.path.exists(label_pdf_path):
        raise FileNotFoundError(f"라벨 파일이 없음: {label_pdf_path}")

    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    # 2026-09-09 사고: 매칭 조건이 "제목에 TO#가 있고 Rebalance/RMA가 들어감"
    # 뿐이라, **알림 메일 초안**("[Rebalance TO 7881469] HTS Code 기본값 적용...")
    # 이 먼저 걸려 거기에 라벨이 붙어 발송됐다(수신자가 본인이라 외부 유출은
    # 없었지만 용마는 라벨을 못 받았다). 알림 초안은 제목이 '['로 시작하고
    # 수신자가 내부(ALERT_MAIL_TO)라 그 둘로 걸러낸다. 용마 답장 초안은 회신이라
    # 제목이 RE:로 시작한다.
    drafts = ns.GetDefaultFolder(16)   # 16 = olFolderDrafts
    items = drafts.Items               # .Items를 매번 새로 받으면 정렬/인덱스가 흔들린다
    target = None
    skipped = []
    for i in range(1, min(items.Count, 200) + 1):
        try:
            mail = items.Item(i)
        except Exception:
            continue
        if getattr(mail, "Class", None) != 43:
            continue
        subj = str(mail.Subject or "")
        if str(to_number) not in subj:
            continue
        if not ("Rebalance" in subj or "RMA" in subj.upper()):
            continue
        if subj.lstrip().startswith("["):
            skipped.append(subj[:50])      # 알림/진단 초안
            continue
        to_line = str(getattr(mail, "To", "") or "")
        if "candelamedical.com" in to_line.lower() and "@" not in to_line.replace(
                "candelamedical.com", ""):
            skipped.append(subj[:50])      # 사내 수신자만 있는 초안
            continue
        target = mail
        break
    if target is None:
        raise RuntimeError(
            f"임시보관함에서 TO {to_number}의 용마 답장 초안을 못 찾음 - "
            f"용마 CI 답장 초안이 만들어졌는지 확인 필요"
            + (f" (알림 초안으로 보고 건너뛴 것: {skipped})" if skipped else ""))
    if skipped:
        log(f"  [정보] 알림 초안 {len(skipped)}건은 건너뛰고 용마 답장을 골랐습니다")

    # 이미 붙어 있으면 다시 붙이지 않는다(발송 실패 후 재시도 시 중복 첨부 방지).
    label_name = os.path.basename(label_pdf_path)
    already = False
    try:
        for j in range(1, target.Attachments.Count + 1):
            if str(target.Attachments.Item(j).FileName) == label_name:
                already = True
                break
    except Exception:
        pass
    if already:
        log(f"[용마] 라벨이 이미 첨부돼 있음 - 재첨부 생략({label_name})")
    else:
        target.Attachments.Add(label_pdf_path)
        try:
            target.Save()
        except Exception:
            pass
    if send:
        # Send() 직후에는 아이템이 보낸편지함으로 옮겨져 Subject/EntryID 접근이
        # "The item has been moved or deleted."로 실패한다(2026-08-27 실측) -
        # 보내기 **전에** 로그에 쓸 값을 미리 읽어둔다.
        entry_id = target.EntryID
        subject = str(target.Subject or "")
        try:
            target.Send()
        except Exception as e:
            # 2026-08-27 실측: Outlook 읽기창에서 인라인 답장으로 열려 있는 초안은
            # COM Send가 막힌다("This method can't be used with an inline response
            # mail item."). 복사본은 일반 MailItem이라 발송된다 - 원본 초안은
            # 남으므로(임의 삭제 안 함) 사람이 나중에 지우면 된다.
            if "inline response" not in str(e):
                raise
            # 2026-09-04 실측: Copy()를 떠도 **복사본 역시 인라인 답장**이라
            # 같은 오류로 막힌다(TO 7878369에서 폴백까지 실패). 그래서 원본
            # 회신에서 ReplyAll로 **새 메일을 만들어** 초안의 본문/첨부를 옮겨
            # 담아 보낸다. 인라인 여부는 Outlook 읽기창 상태에 달려 있어서
            # 초안을 만드는 시점에는 막을 수 없다.
            log("  [정보] 인라인 답장이라 직접 발송 불가 - 원본에서 새 답장을 "
                "만들어 보냅니다")
            _send_as_fresh_reply(to_number, target, subject, label_name)
            return entry_id
        log(f"[용마] 답장 초안 발송: '{subject}' + 라벨 {label_name}")
        return entry_id
    target.Save()
    log(f"[용마] 답장 초안에 라벨 첨부(미발송): '{target.Subject}' + "
        f"{os.path.basename(label_pdf_path)}")
    return target.EntryID


# ==============================================================
# 파이프라인 + CLI
# ==============================================================
def arrange_fedex_pickup(country_code: str, packages: list[dict], *,
                         to_number: str | None = None, ci_pdf_path=None,
                         stop_at: str | None = None, confirm: bool = False,
                         pickup_mode: str = "reserve",
                         is_rma: bool = False) -> dict:
    """FedEx 픽업 어레인지 전체를 순서대로 실행한다.

    흐름(2026-08-25 실측 완료분까지 구현):
      1~3 로그인 -> 4 지금 발송 -> 5 주소록 수신인 -> 6 자체포장재/제원
      -> 7 발송날짜+서비스(컷오프 13시/최단 도착/최저가)
      -> 8 패키지 내용물(CI 값 물품 등록 + 상업송장 PDF 업로드)
      -> 9 픽업 예약 진행 선택 -> 10 청구서 세부정보(수취인 청구/고객번호)
      -> 11 **요약 보기 클릭까지 하고 반드시 멈춘다** - 최종 생성(발송물 확정)은
         되돌릴 수 없는 지점이라 사람이 요약 화면을 확인하고 직접 누른다.

    stop_at: 더 일찍 멈출 지점("login"/"shipnow"/"address"/"package"/"service"/
    "contents"/"pickup"/"billing"). 기본값 None = 요약 보기까지 전체 실행.

    to_number/ci_pdf_path: 8단계(CI 값 조회/송장 업로드)에 필요. to_number는
    수출신고실적 조회에, ci_pdf_path는 업로드할 최종 CI PDF 경로에 쓴다
    (None이면 CI 폴더에서 "KRP-{국가} *.pdf" 최근 파일을 쓴다 - 통합 시에는
    rebalance_watcher가 정확한 경로를 넘겨준다)."""
    from selenium.webdriver.common.by import By

    country_code = normalize_country_code(country_code)
    # ci_pdf_path는 문자열 하나(기존 호출부: rebalance_watcher) 또는 여러 장 리스트
    # (미국 7876545처럼 Delivery가 갈려 CI가 2장인 경우)를 다 받는다.
    if ci_pdf_path is None:
        ci_paths = []
    elif isinstance(ci_pdf_path, str):
        ci_paths = [ci_pdf_path]
    else:
        ci_paths = list(ci_pdf_path)
    decl_warnings: list[str] = []
    if not packages and stop_at not in ("login", "shipnow", "address"):
        # 제원 없이 6단계로 들어가면 빈 값/목업이 그대로 FedEx에 올라간다 - 막는다.
        raise ValueError("박스 제원(packages)이 비어 있습니다 - 용마 회신 파싱 결과나 "
                         "--boxes로 실제 무게/치수를 넣어야 합니다")
    contact = None
    ensure_edge_running()
    driver = get_fedex_driver()
    try:
        open_and_login(driver)
        if stop_at == "login":
            _save_diag(driver, "stop_login")
            log("[FedEx] stop_at=login - 여기서 종료")
            return
        goto_ship_now(driver)
        if stop_at == "shipnow":
            _save_diag(driver, "stop_shipnow")
            log("[FedEx] stop_at=shipnow - 여기서 종료")
            return
        contact = select_recipient_from_address_book(driver, country_code)
        if stop_at == "address":
            _save_diag(driver, "stop_address")
            log("[FedEx] stop_at=address - 여기서 종료")
            return
        choose_own_packaging_and_fill_packages(driver, packages)
        if stop_at == "package":
            _save_diag(driver, "stop_package")
            log("[FedEx] stop_at=package - 여기서 종료")
            return
        _click_next(driver)   # 패키지 세부정보 -> 서비스
        select_ship_date_and_service(driver)
        if stop_at == "service":
            _save_diag(driver, "stop_service")
            log("[FedEx] stop_at=service - 여기서 종료")
            return

        if not to_number:
            raise ValueError("8단계(CI 값 조회)에는 to_number가 필요합니다 (--to)")
        if not ci_paths:
            hits = sorted(glob.glob(os.path.join(CI_FOLDER_PATH, f"KRP-{country_code} *.pdf")),
                          key=os.path.getmtime)
            if not hits:
                raise FileNotFoundError(f"CI 폴더에 KRP-{country_code} PDF가 없음 - "
                                        f"--ci로 경로를 지정하세요")
            ci_paths = [hits[-1]]
            log(f"[정보] --ci 미지정 - CI 폴더 최신 파일 사용: {os.path.basename(ci_paths[0])}")
        # 값의 출처는 **CI PDF**다(실적 파일은 어긋나는 사례가 있어 대조/경고만).
        ci_rows = parse_ci_pdf_items(ci_paths)
        decl_warnings = crosscheck_export_declaration(to_number, ci_rows)
        _click_next(driver)   # 패키지 -> 서비스는 이미 지났고, 서비스 -> 서비스 옵션
        _click_next(driver)   # 서비스 옵션(전부 옵션) -> 패키지 내용물
        # packages를 반드시 같이 넘긴다 - 물품 '순중량'을 박스 무게에서 계산하기
        # 때문에 빼먹으면 "순중량을 못 정함"으로 8단계에서 멈춘다.
        fill_package_contents(driver, ci_rows, ci_paths, packages, is_rma=is_rma)
        if stop_at == "contents":
            _save_diag(driver, "stop_contents")
            log("[FedEx] stop_at=contents - 여기서 종료")
            return
        _click_next(driver)   # 패키지 내용물 -> 픽업/방문 접수
        select_pickup_reservation(driver, mode=pickup_mode)
        if stop_at == "pickup":
            _save_diag(driver, "stop_pickup")
            log("[FedEx] stop_at=pickup - 여기서 종료")
            return
        _click_next(driver)   # 픽업 -> 알림(건너뜀, 사용자 확인)
        _click_next(driver)   # 알림 -> 청구서 세부정보
        fill_billing_details(driver, country_code)
        if stop_at == "billing":
            _save_diag(driver, "stop_billing")
            log("[FedEx] stop_at=billing - 여기서 종료")
            return
        # 요약 보기. confirm=False면 여기까지가 끝이고(사람이 확정),
        # confirm=True면 이어서 '완료'를 눌러 실제 발송물을 만든다.
        summary_btns = [b for b in driver.find_elements(
            By.XPATH, "//button[normalize-space(.)='요약 보기' or normalize-space(.)='요약보기']")
            if b.is_displayed()]
        if not summary_btns:
            _save_diag(driver, "summary_btn")
            raise RuntimeError("'요약 보기' 버튼을 못 찾음")
        driver.execute_script("arguments[0].click();", summary_btns[0])
        log("[FedEx] 요약 보기 클릭")
        time.sleep(3)
        _save_diag(driver, "stop_summary")

        if confirm:
            result = confirm_shipment_and_capture_label(driver, to_number, country_code)
            result["decl_warnings"] = decl_warnings
            result["packages"] = packages
            result["contact"] = contact
            # 2026-09-09 사용자 요청: 생성 성공 자체는 메일로 안 알린다
            # (Tracking/라벨은 어차피 용마 답장·SharePoint·수출신고실적에 들어간다).
            # 실적이 CI와 어긋난 경우만 사람이 봐야 하므로 그때만 메일을 보낸다.
            log(f"[FedEx] {country_code} TO {to_number} 발송물 생성 완료 "
                f"(Tracking {result.get('tracking') or '미확인'}, "
                f"라벨 {result.get('label_path')})")
            if decl_warnings:
                send_alert(
                    f"[FedEx] TO {to_number} 수출신고실적이 CI와 다릅니다",
                    f"FedEx에는 CI 값을 넣었습니다. 실적을 확인해주세요:\n  - "
                    + "\n  - ".join(decl_warnings),
                )
            return result
        send_alert(
            f"[FedEx] {country_code} 픽업 예약 사전입력 완료 - 요약 확인 후 확정해주세요",
            f"TO: {to_number}\n국가: {country_code}\n"
            f"받는 사람: {(contact or {}).get('search_name', '(확인 필요)')}\n"
            f"박스: {json.dumps(packages, ensure_ascii=False)}\n"
            + (("\n[확인 필요] 수출신고실적이 CI와 다릅니다(FedEx에는 CI 값을 넣었습니다):\n  - "
                + "\n  - ".join(decl_warnings) + "\n") if decl_warnings else "")
            + "\n"
            f"브라우저의 FedEx 요약 화면에서 내용을 확인하고 최종 생성을 진행해주세요.\n"
            f"라벨이 나오면:\n"
            f"  1) python fedex_ship_watcher.py label {to_number} --label <라벨PDF> [--send]\n"
            f"     -> 용마 답장 초안(CI 첨부분)에 라벨을 붙여 넣습니다\n"
            f"  2) python fedex_ship_watcher.py track {to_number} <Tracking번호>\n"
            f"     -> SharePoint Tracking Number + 수출신고실적 B/L번호 기입",
        )
    except Exception:
        # 2026-08-27: 실패할 때마다 탭을 닫아버려서 5~8분치 입력(수취인/제원/서비스/
        # 물품/송장)이 통째로 날아가고 처음부터 다시 태워야 했다. 실패 시에는
        # **탭을 남겨** 사람이 이어서 하거나 다음 시도에서 상태를 볼 수 있게 한다.
        log("[정보] 실패로 종료 - 확인할 수 있게 FedEx 탭은 닫지 않고 남겨둡니다")
        raise
    else:
        close_driver(driver)


def _post_confirm_followups(to_number: str, country_code: str, result: dict,
                            *, send_mail: bool) -> None:
    """발송물 생성 후 남은 일: 용마 답장 초안에 라벨 첨부(+발송), Tracking 기입.

    각 단계는 앞 단계 실패와 무관하게 최대한 진행한다 - 발송물은 이미 만들어졌고
    되돌릴 수 없으므로, 여기서 멈추면 기록만 누락된다."""
    label = result.get("label_path")
    tracking = result.get("tracking")

    if label:
        try:
            send_label_to_yongma_draft(to_number, label, send=send_mail)
        except Exception as e:
            log(f"[경고] 용마 답장 라벨 첨부 실패(수동 처리 필요): {exc_detail(e)}")
            send_alert(f"[FedEx] TO {to_number} 용마 답장 라벨 첨부 실패",
                       f"라벨: {label}\n{e}")
    else:
        log("[경고] 라벨 파일이 없어 용마 답장 첨부를 건너뜁니다")

    if tracking:
        try:
            update_tracking_number(to_number, tracking)
        except Exception as e:
            log(f"[경고] Tracking 후처리 실패(수동 처리 필요): {exc_detail(e)}")
            send_alert(f"[FedEx] TO {to_number} Tracking 기입 실패",
                       f"Tracking: {tracking}\n{e}\n\n"
                       f"수동: python fedex_ship_watcher.py track {to_number} {tracking}")
    else:
        log("[경고] Tracking 번호가 없어 SharePoint/실적 기입을 건너뜁니다")


def _parse_boxes_arg(raw: str) -> list[dict]:
    """--boxes 값을 파싱한다. JSON이 정석이지만 PowerShell/CMD에서 큰따옴표를
    escape하기 번거로워 사용자가 작은따옴표로 넣는 경우가 잦다
    (예: "[{'weight':0.81,'L':61,'W':47,'H':8}]") - 그 표기도 받아준다."""
    try:
        packages = json.loads(raw)
    except Exception:
        import ast
        packages = ast.literal_eval(raw)
    if isinstance(packages, dict):
        packages = [packages]
    if not isinstance(packages, list) or not packages:
        raise ValueError(f"--boxes 형식이 잘못됨: {raw!r}")
    for p in packages:
        if not isinstance(p, dict) or not p.get("weight"):
            raise ValueError(f"--boxes 각 박스에 weight(kg)가 있어야 함: {p!r}")
    return packages


def _resolve_packages(args) -> list[dict]:
    """ship 모드에서 쓸 박스 제원을 정한다.

    2026-08-27: 예전에는 --boxes가 없으면 목업 제원(12kg/50x40x30)으로 그냥
    진행했는데, 그 값이 그대로 FedEx 발송물에 올라가는 구조라 위험하다
    (요금/서비스 계산도 무게로 달라진다). 이제는
      1) --boxes가 있으면 그 값
      2) 없고 --to가 있으면 용마 회신을 찾아 parse_yongma_dims로 추출
      3) 둘 다 안 되면 **진행하지 않고 중단**
    으로 바꿨다. 자동 트리거 경로(rebalance_watcher._start_fedex_arrangement)와
    같은 데이터를 쓰게 되므로 수동/자동 결과가 어긋나지 않는다."""
    if args.boxes:
        packages = _parse_boxes_arg(args.boxes)
        log(f"[정보] --boxes 제원 사용: {packages}")
        return packages
    if args.stop in ("login", "shipnow", "address"):
        # 6단계 전에 멈추는 실측용 실행은 제원이 필요 없다.
        return []
    if not args.to:
        raise ValueError("박스 제원이 없습니다 - --boxes로 직접 넣거나 "
                         "--to <TO번호>로 용마 회신에서 자동 추출하세요")
    body = _find_yongma_reply_body(args.to)
    if not body:
        raise ValueError(f"용마 폴더에서 TO {args.to} 회신을 못 찾음 - "
                         f"--boxes로 제원을 직접 넣어주세요")
    packages = parse_yongma_dims(body)
    if not packages:
        raise ValueError(f"TO {args.to} 용마 회신에서 박스 무게/크기를 못 뽑음 - "
                         f"--boxes로 제원을 직접 넣어주세요")
    if any(p.get("weight") is None for p in packages):
        raise ValueError(f"용마 회신 파싱 결과에 무게 없는 박스가 있음({packages}) - "
                         f"--boxes로 제원을 직접 넣어주세요")
    log(f"[정보] --boxes 미지정 - 용마 회신에서 추출한 제원 사용: {packages}")
    return packages


def main():
    parser = argparse.ArgumentParser(description="FedEx 픽업 어레인지 자동화")
    parser.add_argument("mode", choices=["contact", "login", "ship", "dims", "label",
                                         "track"])
    parser.add_argument("arg", nargs="?", help="국가코드(contact/login/ship), 본문(dims), TO번호(label/track)")
    parser.add_argument("arg2", nargs="?", help="FedEx Tracking 번호(track 모드)")
    parser.add_argument("--boxes",
                        help="박스 제원 JSON, 예: [{\"weight\":12,\"L\":50,\"W\":40,\"H\":30}]. "
                             "생략하면 --to의 용마 회신에서 자동 추출(못 구하면 중단)")
    parser.add_argument("--to", help="TO번호(수출신고실적 CI 값 조회용)")
    parser.add_argument("--ci", action="append",
                        help="업로드할 CI PDF 경로(미지정 시 CI 폴더 최신 파일). "
                             "CI가 여러 장이면 --ci를 반복해서 넣는다")
    parser.add_argument("--label", dest="label_pdf", help="용마 초안에 첨부할 라벨 PDF 경로(label 모드)")
    # 2026-09-04 사용자 지적("CI 랑 라벨 포함해서 답장해주는거 왜 안해"):
    # 라벨까지 붙은 답장은 **기본 발송**으로 바꿨다. 예전엔 초안만 만들고
    # --send를 줘야 나가서, 매번 사람이 임시보관함을 열어 보내야 했다.
    parser.add_argument("--send", action="store_true",
                        help="(호환용) 예전 플래그 - 지금은 기본이 발송이라 없어도 된다")
    parser.add_argument("--no-send", dest="no_send", action="store_true",
                        help="라벨을 붙이기만 하고 발송하지 않는다(초안으로 남김)")
    parser.add_argument("--no-pickup", dest="no_pickup", action="store_true",
                        help="픽업을 새로 잡지 않고 '운송장만 생성'을 고른다"
                             "(같은 날 이미 픽업이 예약된 경우)")
    parser.add_argument("--confirm", action="store_true",
                        help="ship 모드에서 요약 확인 후 **최종 '완료'까지 눌러 실제 "
                             "발송물을 생성**한다(되돌릴 수 없음). 생성 후 라벨을 "
                             "용마 답장 초안에 붙이고 Tracking을 기입한다")
    parser.add_argument("--stop", choices=["login", "shipnow", "address", "package",
                                           "service", "contents", "pickup", "billing"],
                        help="ship 모드에서 지정 단계까지만 실행(단계별 실측용)")
    args = parser.parse_args()

    if args.mode == "contact":
        print(json.dumps(lookup_ship_to_contact(args.arg), ensure_ascii=False, indent=2))
        return

    if args.mode == "dims":
        result = parse_yongma_dims(args.arg or "")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.mode == "label":
        if not (args.arg and args.label_pdf):
            parser.error("사용법: fedex_ship_watcher.py label <TO번호> --label <라벨PDF> [--send]")
        send_label_to_yongma_draft(args.arg, args.label_pdf, send=not args.no_send)
        return

    if args.mode == "track" and not (args.arg and args.arg2):
        parser.error("사용법: fedex_ship_watcher.py track <TO번호> <FedEx Tracking번호>")

    lock = _acquire_singleton_lock()
    if lock is None:
        log("이미 다른 인스턴스가 실행 중 - 종료")
        return
    # 2026-09-18: 공유 Edge 락을 걸었다가(TO 7882258 실사고로 도입) 같은 날
    # stale 판정 구멍으로 또 실전 충돌이 났다 - 대신 이 스크립트를 전용
    # Edge(포트/프로필)로 완전히 분리해 겹칠 일 자체를 없앴다
    # (set_edge_owner("fedex_ship_watcher") 참고). 락 제거.
    log(f"===== fedex_ship_watcher 시작 (mode={args.mode}) =====")
    try:
        if args.mode == "login":
            arrange_fedex_pickup(args.arg or "ILH", [], stop_at="login")
        elif args.mode == "track":
            update_tracking_number(args.arg, args.arg2)
        else:  # ship
            if not args.arg:
                parser.error("ship 모드에는 국가코드가 필요합니다 (예: ship ILH)")
            packages = _resolve_packages(args)
            result = arrange_fedex_pickup(
                args.arg, packages, to_number=args.to, ci_pdf_path=args.ci,
                stop_at=args.stop, confirm=args.confirm,
                pickup_mode=("label_only" if args.no_pickup else "reserve")) or {}
            if args.confirm:
                _post_confirm_followups(args.to, args.arg, result,
                                        send_mail=not args.no_send)
    except Exception as e:
        import traceback
        log(f"[에러] {e}\n{traceback.format_exc()}")
        send_alert("[FedEx] 픽업 자동화 실행 에러", f"{e}\n\n{traceback.format_exc()}")
    finally:
        try:
            lock.close()
        except Exception:
            pass
    log("===== fedex_ship_watcher 종료 =====")


if __name__ == "__main__":
    main()







