# -*- coding: utf-8 -*-
"""
rebalance_watcher.py

KRP(한국 창고)에서 다른 나라 법인으로 재고를 재분배하는 "Rebalance TO"
(Transfer Order) 처리를 자동화한다. 2026-08-04~05 TO 7866440 실제 케이스로
14단계 전체(트리거 감지부터 CI 저장까지)를 사용자와 함께 실측 검증한 뒤
코드로 옮겼다(자세한 배경/실측 기록은 memory의 rebalance-to-automation-sop
참고). 2026-08-05: run_yongma_scan()이 용마 회신을 TO#로 확실히 매칭하면
사람 명령 없이 바로 process_rebalance_to()(5~14단계, Create Pick Wave부터
수출신고실적까지)를 이어서 실행하도록 변경 - 물리적 재고 이동(Release Now/
Confirm Pick Slips)이 걸려있는 단계이므로 초기 실행 몇 건은 로그/알림 메일을
챙겨 볼 것. TO#를 확실히 못 찾은 애매한 회신은 여전히 자동 실행하지 않고
사람 확인 알림만 보낸다.

전체 흐름(사용자 실측 확인, 2026-08-04):
1. 트리거: Outlook 받은편지함 > Operation > Rebalance 폴더에 SharePoint Online이
   보내는 APAC Stock Movements 변경 알림 메일. 실제 본문 예시(실측 확인):
     "Chandranna Galleli changed TO# to 7868330 for KRP - AUP 1301-00-9395"
     "Chandranna Galleli changed TO# to 7857134 for KRP-ILH-SBA100128"
   "...was added to..." 메일은 TO#가 아직 없어 트리거 대상이 아니고, 본문에
   "changed TO# to"가 있는 메일만 트리거. 한 TO에 파트가 여러 개면 파트별로
   메일이 각각 오므로(같은 TO#가 여러 메일에 등장) TO# 단위로 묶어서 처리한다.
2. SharePoint APAC Stock Movements 리스트에서 그 TO#로 조회해 파트넘버/qty
   확인. 인천관세법인 C.I 확인\\icbl_ci_watcher.py에 이미 이 리스트를 Selenium
   으로 읽는 검증된 함수(lookup_receive_delivery_via_sharepoint, Delivery#
   기준 조회)가 있어 그 파싱 방식(검색 쿼리 URL + innerText 줄 단위 파싱)만
   재사용하고 TO# 기준으로 바꿨다. 단, TO# 기준 조회의 정확한 컬럼 오프셋은
   실제 화면으로 확인된 적이 없어 best-effort로 구현했다(lookup_to_lines_via_sharepoint
   참고, 실패 시 사람 확인 알림).
3. 용마로지스 앞으로 파트넘버/qty를 알려주며 제원정보(박스 크기/locator) 요청
   메일 발송. 수신자는 pick_release_watcher.py의 PICK_RELEASE_REPLY_CC와 동일
   (김기훈/유용호, 사용자가 2026-08-04 재확인).
4. 용마 회신은 받은편지함 > Operation > Yongma 폴더에 제목 "Rebalance"가
   포함된 메일로 옴(원본 스레드 매칭이 아니라 제목 키워드 기준, 사용자 확인).
   자유서식 본문이라 파싱 규칙은 실제 케이스를 몇 건 겪으며 다듬을 필요가 큼.
5. Oracle Create Pick Wave에서 Order Type을 Sales Order -> Transfer Order로
   바꾸고 TO#(7로 시작)만 넣으면 끝(사용자 확인, 2026-08-04 - 그 외 다른 점
   없음). pick_release_watcher.py의 navigate_to_create_pick_wave()/
   _field_by_label() 패턴을 그대로 재사용하되 Order Type 토글 셀렉터만 새로
   추가했다 - 이 토글은 기존 자동화가 한 번도 다뤄본 적 없어 실측 필요.
6~9. Shipments > Confirm Pick Slips에서 로케이터/수량 입력 -> Confirm and go
   to ShipConfirm -> ShipConfirm 번호(9로 시작) 확인 -> Ship Confirm 클릭.
   **주의**: 이 화면은 ship_confirm_watcher.py가 자동화한 "Manage Shipment
   Lines"(Ship Confirm Rule 드롭다운만 바꾸는 화면)와 다르다 - 완전히 새로운
   화면이라 스텁으로 남겨두고 사람에게 알림 메일만 보낸다(confirm_pick_slips
   참고). 실제 재고 이동을 일으키는 단계라 첫 실제 케이스는 사람이 확인하며
   진행하는 게 안전하다는 게 이 프로젝트의 기존 관례(다른 스크립트들도 전부
   실측 검증 후에야 무인 실행으로 전환함).
10. SharePoint APAC Stock Movements의 Delivery# 컬럼에 기입 - 기존 함수는
   읽기 전용이라 쓰기는 스텁(write_delivery_to_sharepoint).
11~12. 인천관세법인 Print Commercial Invoice(Ship From=KRP, Both, Delivery
   Number들)를 실행 - 기존 자동화가 다뤄본 적 없는 조합이라 스텁
   (run_icbl_invoice_krp_both). 성공하면 로컬 템플릿
   "Rebalance Invoice form_Ship from Korea_excel.xlsx"의 목적지 국가 시트에
   옮겨 적는다(populate_rebalance_invoice_template, 완전 구현) - 그 시트에는
   BILL TO/SHIP TO 주소가 이미 국가별로 채워져 있어(2026-08-04 사용자 확인,
   실측: AUP 시트 A9="BILL TO:"~A15, M9="SHIP TO:"~M15) 시트만 맞게 고르면
   Bill To/Ship To 둘 다 자동으로 해당 국가 주소가 된다.
13. 수출신고실적20260126~.xlsx Sheet1에 인보이스 정보 추가(append_export_declaration,
   완전 구현) - 컬럼: Destination/Purpose(="Rebalance")/선적일자/B_L번호/
   HS_code/관리코드(P_N)/품명/수량/단가/금액/SO(=TO#)/Delivery_Number/국가(2자).
   과거 이력 있음(예: 2025-12-03 JPP/AUP 건, 같은 포맷으로 이어 쓰면 됨).
14. Ship To/Bill To가 수정된 최종 인보이스를 12. 수출\\CI 폴더에 저장
   (save_final_invoice_to_ci_folder, 완전 구현) - 파일명 규칙은 그 폴더의
   기존 파일 실측으로 확인: "KRP-{국가코드} {Delivery Number}.xlsx"
   (예: "KRP-AUP 9969738.xlsx").

스케줄(사용자 확인, 2026-08-04):
- 트리거 메일(Rebalance 폴더) 탐색: 원래 하루 1회(아침 10시) 의도였으나, 실제
  등록은 Yongma와 동일하게 매시 정각 반복 -> `python rebalance_watcher.py trigger`
- 용마 회신(Yongma 폴더) 탐색: 1시간에 1회 -> `python rebalance_watcher.py yongma`
작업 스케줄러에 두 트리거를 따로 등록해서 같은 스크립트를 다른 인자로 실행한다.
용마 회신이 오면 위치정보가 pending_cases에 저장되고 알림 메일이 오는데, 그
알림을 보고 사람이 직접 `python rebalance_watcher.py process <TO번호>`를
실행해서 5~14단계(Create Pick Wave ~ CI 저장)를 진행한다(아직 자동 트리거 안 함
- 물리적 재고 이동이 걸려있어 사람 확인 후 실행하는 게 안전).

**2026-08-06 버그 수정**: 두 작업 스케줄러 모두 반복 구간이 09:00~18:00(9시간)
로 등록돼 있어 밤 18시~다음날 9시 사이엔 아예 안 돔 - 그 시간대에 도착한 트리거
메일(KRP발 TO 3건, 7870379/7866552/7870361)이 다음날 09:00 스캔에서도 안 잡혀
누락됨(윈도우 밖에서 온 메일이라 09:00 시점엔 Outlook 폴더 동기화가 아직 안
끝나 있었을 가능성). 두 작업 모두 반복 구간을 09:00~10년(사실상 24시간 무한
반복)으로 재등록해서 야간 공백을 없앰. `run_yongma_scan()`에도 `pending_cases`가
비어 있으면(=보낸 제원요청 메일 자체가 없으면) 바로 리턴하는 가드를 추가해서
불필요한 Outlook 스캔을 생략하게 함(사용자 요청).
"""

from __future__ import annotations

import os
import re
import sys
import shutil
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# icbl_ci_watcher.py의 검증된 오라클 세션 관리 로직 재사용(같은 Edge 인스턴스 공유,
# pick_release_watcher.py/ship_confirm_watcher.py와 동일한 재사용 패턴)
ICBL_DIR = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\10. 수입\인천관세법인 C.I 확인"
)
sys.path.insert(0, ICBL_DIR)
from icbl_ci_watcher import (  # noqa: E402
    ensure_edge_running,
    get_oracle_driver_isolated,
    close_driver,
    is_session_dead_error,
    atomic_write_json,
    read_json_state,
    exc_detail,
    recover_oracle_login,
    oracle_is_logged_in,
    OracleLoginRequired,
    ORACLE_HOME_URL,
    _click_text,
    tasks_panel_open,
    wait_or_sleep,
    text_visible,
    element_present,
    _wait_find,
    _force_restart_edge,
    _debug_port_open,
    _ensure_my_tab,
    _try_sso_relogin,
    acquire_oracle_lock,
    release_oracle_lock,
    set_edge_owner,
)

# pick_release_watcher.py의 Create Pick Wave 화면 조작 패턴 재사용
PICK_RELEASE_DIR = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\10. 수입\DCD 소모품 Pick Release 자동화"
)
sys.path.insert(0, PICK_RELEASE_DIR)
from pick_release_watcher import (  # noqa: E402
    _field_by_label,
    navigate_to_create_pick_wave,
)

# 2026-09-18: 이 프로세스는 자기 전용 Edge(포트/프로필)를 쓴다. **반드시 위
# pick_release_watcher import 뒤에 와야 함** - 그 모듈이 import되는 순간 자기
# 자신을 owner로 세팅해버리므로(pick_release_watcher.py 상단의 동일 패턴),
# 이 줄이 마지막에 다시 덮어써야 이 프로세스가 진짜 rebalance_watcher owner로
# 남는다.
set_edge_owner("rebalance_watcher")

# ==============================================================
# 경로/설정
# ==============================================================
ROOT = os.path.dirname(__file__)
LOG_PATH = os.path.join(ROOT, "rebalance_watcher.log")
STATE_PATH = os.path.join(ROOT, "_rebalance_watcher_state.json")

OUTLOOK_PARENT_SUBFOLDER = "Operation"
TRIGGER_SUBFOLDER = "Rebalance"   # 실측 확인(2026-08-04): Operation 바로 밑이 아니라 그 안의 서브폴더
REPLY_SUBFOLDER = "Yongma"

ALERT_MAIL_TO = "yoongil.chae@candelamedical.com"

# 2026-08-06 사용자 요청: 용마 회신 스캔에서 잡힌 TO를 하나씩 순차로 끝까지
# 처리하던 것을 "회신 전부를 먼저 스캔/매칭한 뒤 2건씩 동시 처리"로 바꾼다.
# 배경(실측): 10:30 회차에서 회신 3건(JPP 1 + ILH 2)이 한 번에 잡혔는데, 목록
# 맨 앞이던 JPP 건의 14단계 파이프라인(ICBL CI 완료 대기가 최대 17분)이 끝날
# 때까지 뒤의 홍콩 2건이 시작도 못 하고 대기했음.
# 동시 2건은 [[pick-release-watcher]]의 MAX_PARALLEL_ORDERS와 같은 값 - 그쪽에서
# 3개로 올렸을 때 stale element reference가 나서 2로 낮춘 실측 이력이 있어
# 같은 보수적 값을 따른다(같은 오라클 로그인 세션을 공유하므로 부하 특성도 동일).
MAX_PARALLEL_TO = 2

# 병렬 처리에서 공유 자원 보호용 락.
# - _STATE_LOCK: state json의 read-modify-write(pending_cases pop 등). 락 없이
#   두 워커가 load_state -> 수정 -> save_state 하면 나중에 저장한 쪽이 앞선
#   쪽의 pop을 되살려버린다(lost update).
# - _EXCEL_LOCK: 수출신고실적 엑셀 append. openpyxl은 파일 전체를 읽어 다시
#   저장하므로 동시에 두 번 저장하면 한쪽 행이 사라진다.
# - _LOG_LOCK: 로그 한 줄이 다른 스레드 줄과 섞여 쓰이는 것 방지.
_STATE_LOCK = threading.Lock()
_EXCEL_LOCK = threading.Lock()
_LOG_LOCK = threading.Lock()

# 2026-08-06: 위 threading.Lock은 "한 프로세스 안의 스레드끼리"만 막아준다 -
# 프로세스가 두 개 뜨면 무용지물이다. 그런데 이 automation은 한 회차가 길어질 수
# 있어(TO 하나의 ICBL CI 완료 대기가 최대 17분 x 재시도 3회) 30분 주기 스케줄러가
# 앞 회차가 끝나기 전에 다음 회차를 띄우는 상황이 실제로 생긴다(실측: 10:30 회차가
# 11:00 트리거 시점에도 JPP 건 CI를 기다리는 중이었음). 그 상태로 두 인스턴스가
# 겹치면 같은 TO를 동시에 처리하려 하고, state json/수출신고실적 엑셀을 프로세스
# 경계를 넘어 동시에 쓰게 된다(위 락으로는 못 막음).
# [[pick-release-watcher]]가 같은 이유로 쓰는 파일 락 패턴을 그대로 가져온다.
LOCK_FILE_PATH = os.path.join(ROOT, "_rebalance_watcher.lock")


def _acquire_singleton_lock():
    """이미 다른 인스턴스(겹치는 스케줄 트리거 포함)가 돌고 있으면 None 반환."""
    import msvcrt
    f = open(LOCK_FILE_PATH, "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f

YONGMA_REQUEST_TO = "김기훈 <y7221063@yongmalogis.co.kr>; 용호 유 <y7225055@yongmalogis.co.kr>"

# ==============================================================
# RMA(본사 반송) 목적지 - 2026-08-18 사용자 요청으로 추가
# ==============================================================
# 같은 Rebalance 폴더로 들어오지만 목적지가 나라(AUP/ILH/...)가 아니라
# "KRP-FA LAB" / "KRP-Refurb Center" / "KRP-PURCHASING"인 메일은 국가간
# 재배치가 아니라 **본사(미국 Marlborough)로 돌아가는 RMA**다(사용자 확인,
# 2026-08-18). 실측 메일 제목/본문(2026-04-14, TO 7672306 - 세 종류가 한 TO에
# 섞여 있었음):
#   "Chandranna Galleli changed TO# to 7672306 for KRP-FA LAB SBA100775"
#   "... for KRP-FA Lab 7122-00-0110"        (대소문자 흔들림)
#   "... for KRP-Refurb Center 7122-00-9572"
#   "... for KRP-PURCHASING 4001-01-0091"
# 셋 다 최종 목적지가 같아서(본사) 인보이스의 Bill To/Ship To는 **FA LAB 시트
# 하나로 통일**한다(사용자 지시). 한 TO에 세 종류가 섞여 오는 게 실제 사례라
# 목적지를 하나로 모으는 이 방식이 데이터상으로도 맞다.
# 2026-09-15: SharePoint 'To' 선택지의 실제 표기는 "FA-LAB"(하이픈)인데 기존
# 패턴은 공백(\s*)만 허용해서 매칭 실패 -> country="FA-LAB", is_rma=False로
# 잘못 떨어졌다(TO 7881992 실측: Purchasing/Refurb Centre는 정상 인식, FA-LAB만
# 실패해서 목적지 불일치 오탐까지 발생). 이미 이 코드베이스에서 같은 이유로
# 쓰던 [\s-]+ 패턴(2026-08-26, Description 레코드 인식)을 그대로 적용한다.
RMA_DEST_PATTERN = r"FA[\s-]*LAB|Refurb\s*Cent(?:er|re)|Purchasing"
RMA_DEST_CODE = "FA LAB"          # 파이프라인 내부에서 쓰는 목적지 코드(=템플릿 시트명)
# RMA(반송품) 고정 HTS code / 단가 비율 - 기존 수출 CI 생성기(12. 수출\ci_invoice_html.py)의
# RMA 모드와 같은 값을 쓴다(RMA_HTS_CODE / RMA_PRICE_RATIO = 0.10). 그 도구는
# 수입신고실적의 금액을 기준으로 10%를 계산하는데, 이 자동화는 같은 금액이
# 이미 찍혀 나온 오라클 CI를 원본으로 삼으므로 인보이스에 인쇄된 금액에
# 그대로 10%를 적용한다(단가/품목별 금액/합계 전부 - 사용자 확인 2026-08-18).
RMA_HTS_CODE = "9801.00.1090"
RMA_PRICE_RATIO = 0.10
# 2026-08-18 사용자 요청: 4월 수기 인보이스(KRP - FA LAB - 9887298 (RMA).pdf)에
# 들어있던 통관 문구를 자동 생성분에도 그대로 넣는다. 금액을 10%로 신고하는
# 근거를 서류에 남기는 문장이라 RMA 건에는 항상 붙는다.
RMA_CUSTOMS_NOTE = (
    "EXPORT DECLARATION: Damaged parts of medical device, return to manufacturer "
    "(RMA). No commercial value. Value for customs purposes only."
)


def normalize_destination(raw: str) -> tuple[str, bool]:
    """트리거 메일/SharePoint에서 읽은 목적지 표기를 (코드, RMA여부)로 정규화한다.
    RMA 3종(FA LAB/Refurb Center/PURCHASING)은 전부 RMA_DEST_CODE로 모으고,
    그 외는 기존과 똑같이 대문자 국가코드를 그대로 쓴다(Rebalance 경로 동작
    변화 없음)."""
    s = re.sub(r"\s+", " ", str(raw or "").strip())
    if re.fullmatch(RMA_DEST_PATTERN, s, re.IGNORECASE):
        return RMA_DEST_CODE, True
    return s.upper(), False


# 트리거 메일 본문 실측 예시:
#   "Chandranna Galleli changed TO# to 7868330 for KRP - AUP 1301-00-9395"
#   "Chandranna Galleli changed TO# to 7857134 for KRP-ILH-SBA100128"
#   "Chandranna Galleli changed TO# to 7672306 for KRP-FA LAB SBA100775"  (RMA)
# 국가/파트 사이 구분자가 " - "일 때도 "-"일 때도 있어 유연하게 매칭한다.
# 2026-08-18: RMA 목적지는 3글자 국가코드가 아니라 공백이 들어간 이름(FA LAB 등)
# 이라 기존 `[A-Za-z]{3}`로는 아예 매칭이 안 됐다(=지금까지 조용히 무시돼 왔음).
# 국가코드 앞에 RMA 이름들을 먼저 시도하도록 alternation만 덧붙인다 - 기존
# 국가코드 매칭 동작은 그대로다.
TRIGGER_BODY_PATTERN = re.compile(
    r"changed TO#\s*to\s*(?P<to_no>\d+)\s*for\s*KRP\s*-?\s*"
    r"(?P<country>" + RMA_DEST_PATTERN + r"|[A-Za-z]{3})[\s-]+(?P<part_no>\S+)",
    re.IGNORECASE,
)

# 국가코드 -> 한글명(사용자 확인, 2026-08-04)
COUNTRY_NAME_MAP = {
    "AUP": "호주",
    "ILH": "홍콩",
    "CHP": "중국",
    "JPP": "일본",
    "WAY": "미국",
    "FBS": "스페인",
    "FBC": "스페인",
    # 2026-08-18: RMA는 나라가 아니라 본사(미국 Marlborough) 반송이다.
    "FA LAB": "본사(RMA)",
}

# FedEx로 발송하지 않는 국가 - 파이프라인은 CI/용마 답장까지 다 하고 **FedEx
# 어레인지만 건너뛴다**(2026-08-27 사용자 지시: "일본은 FedEx로 arrange 안하지?
# 일본은 arrange 전까지만 해주면 돼").
FEDEX_SKIP_COUNTRIES = {"JPP"}

# 국가코드 -> Rebalance Invoice 템플릿 시트명(FBS는 전용 시트가 없어 FBC로 통일,
# 사용자 확인 2026-08-04). WAY(미국)는 시트명이 "US".
COUNTRY_SHEET_MAP = {
    "AUP": "AUP",
    "ILH": "ILH",
    "CHP": "CHP",
    "JPP": "JPP",
    "WAY": "US",
    "FBS": "FBC",
    "FBC": "FBC",
    # 2026-08-18: RMA(FA LAB/Refurb Center/PURCHASING)는 목적지가 전부 본사라
    # Bill To/Ship To를 FA LAB 시트 하나로 통일한다(사용자 지시). 템플릿에
    # Refurb 시트도 따로 있지만(주소는 같고 담당자만 다름) 한 TO에 세 종류가
    # 섞여 오는 게 실제 사례여서 FA LAB로 모으는 쪽이 맞다.
    RMA_DEST_CODE: "FA LAB",
}

REBALANCE_INVOICE_TEMPLATE_PATH = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\12. 수출\Rebalance Invoice form_Ship from Korea_excel.xlsx"
)
EXPORT_DECLARATION_PATH = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\12. 수출\수출신고실적20260126~.xlsx"
)
CI_FOLDER_PATH = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\12. 수출\CI"
)
# 수출신고실적의 S/N 열(N). 기존 컬럼은 M(13, 원산지)까지라 그 다음 칸이다.
# 2026-08-27 사용자 지시로 신설 - 예전엔 시리얼을 자재명 뒤에 붙여 적었는데,
# 한 파트에 시리얼이 여러 개면(시리얼별로 CI가 여러 줄) 하나만 남아 버렸다.
EXPORT_SN_COLUMN = 14

# 2026-09-04 사용자 지시: "HTS/HS code 없으면 901890/9018909000으로 해줘".
# 수입 이력에 없는 파트의 기본 HS code. FedEx는 앞 6자리(901890)만 쓴다
# (HTS_DIGITS_FOR_FEDEX). 2026-08-05에는 이 값이 특정 건 한정이라 범용
# 기본값으로 쓰지 말라고 정리했었는데, 이번에 범용 기본값으로 확정됐다.
HTS_CODE_FALLBACK = "9018909000"

IMPORT_DECLARATION_PATH = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\10. 수입\수입신고실적(20260211)자동화.xlsx"
)

# RMA(본사 반송) 전용 - Foreign Shipper Declaration 양식(2026-08-18 사용자 지시)
# 미국 반송품이 "미국에서 수출된 물품이 가공/가치상승 없이 되돌아가는 것"임을
# 선언하는 서류. 실제 발송 이력(2025-12-09, Delivery 9834927/9834928)은 이 양식을
# **xlsx 그대로** Robert Lazaros(본사) 앞으로 첨부해 보냈다.
# 양식 구조(실측): 로고 이미지 + 선언문/제목 텍스트박스 + 표(6행 헤더, 7~22행 데이터:
# Marks/Shipment/Invoice Date/Part Number/Description/QTY/Value) + B24 Date /
# B25 Address / B26 Title / B29 Signature(서명 이미지는 27행에 앵커).
# **openpyxl로 저장하면 텍스트박스(선언문 본문)가 사라지므로 반드시 Excel COM으로
# 채운다** - 서식/이미지/텍스트박스를 원본 그대로 두고 셀 값만 넣는다.
FSD_TEMPLATE_PATH = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\12. 수출\RMA\202512.12\Foreign Shipper Declaration - Template 2025.12.08.xlsx"
)
FSD_TEMPLATE_DIR = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\12. 수출\RMA"
)
FSD_ROW_START = 7          # 표 첫 데이터 행
FSD_ROW_END = 22           # 양식에 미리 그려져 있는 표 마지막 행
FSD_DATE_CELL = "B24"

# Ship Confirm이 Shipment Exception(CANDELA REGULATORY HOLD 등)으로 막혔을 때
# 해제를 요청하는 담당자(2026-09-16 사용자 지시, TO 7881992/Shipment 9982077
# 실측 - 파트 7122-00-9912가 Regulatory Hold로 막혀 실제로 이 수신자에게
# 메일을 보내 해결한 사례).
REGULATORY_HOLD_MAIL_TO = "Steven Kim <skim@candelamedical.com>"
REGULATORY_HOLD_MAIL_CC = "Miae Jang <miaej@candelamedical.com>"

# RMA 서류(CI + Foreign Shipper Declaration)를 받는 본사 담당자.
# 최초 실측(2025-12-08 발송분 "Delivery 9834927,9834928"): To=Robert Lazaros,
# CC=Miae Jang. 이후 John Ross의 "Global RMA Process" 공식 안내메일
# (2026-06-16, RMA 승인권자가 John Ross->Dale Carr로 이관되고 최종 서류는
# "Dale과 Robert Lazaros"에게 보내라고 명시)에 맞춰 2026-09-08 사용자 확인 후
# To에 Dale Carr 추가, CC는 Miae Jang 그대로 유지. 첨부는 FSD와 인보이스
# **둘 다**, 본문은 아래 RMA_HQ_MAIL_BODY 그대로.
RMA_HQ_MAIL_TO = ("Dale Carr <dalec@candelamedical.com>; "
                   "Robert Lazaros <robertl@candelamedical.com>")
RMA_HQ_MAIL_CC = "Miae Jang <miaej@candelamedical.com>"
RMA_HQ_MAIL_BODY = (
    "Dear Robert.\n\n"
    "Sending out the RMA related documents.\n\n"
    "Please confirm the contents are correctly typed in.\n\n"
    "Thank you.\n"
)

# ==============================================================
# 미국(WAY) Rebalance - 본사 Bob 앞 선적서류 메일 (2026-08-20 추가)
# ==============================================================
# 사용자 지적(2026-08-20): "미국으로 rebalance건은 bob한테 메일 써달라고 한거 기억해
# 이거 왜 안써줘 선적서류 나오면 바로 써서 보내줘". 확인해보니 Bob 앞 메일은
# RMA(본사 반송) 경로에만 구현돼 있었고 WAY Rebalance에는 없었다.
#
# 문구/수신자/첨부는 추측하지 않고 **사용자가 실제로 보낸 메일**을 그대로 따른다
# (보낸편지함 실측):
#   - 2026-08-19 15:06, 15:48 "Rebalance to US" (KRP-WAY 9973476.pdf + FedEx 라벨)
#   - 2026-07-10 12:54 "Rebalance to US 7122-00-9435" (CI + FedEx 라벨)
#   - 2026-08-07 13:23 "AWB 875342190657" (CI + FedEx 라벨)
#   To=Robert Lazaros / CC=Miae Jang, 본문은 아래 US_HQ_MAIL_BODY 그대로.
#
# 실측 발송분에는 FedEx 발송 라벨도 같이 첨부돼 있었다. 2026-08-20에는 라벨
# 발급이 수작업이라 파일이 언제 나올지 몰라 CI만 첨부하기로 했었는데,
# **2026-08-27에 FedEx 발송이 자동화되면서 이 제약이 없어졌다**(사용자 지시:
# "bob도 FedEx가 잡히면 라벨 포함해서 보내는걸로 하자"). 이제 라벨이 나올 때까지
# 기다렸다가 CI + 라벨을 한 통에 담아 보낸다 - FEDEX_LABEL_FOLDER /
# find_fedex_labels() / process_hq_docs_pending() 참고.
# 2026-09-09 사용자 지적("미국 rebalance 건 왜 Dale 넣었어? RMA는 넣는거 맞는데
# 그냥 은 넣지마"): 예전엔 이 두 상수가 RMA_HQ_MAIL_* 를 그대로 가리키고 있어서,
# 2026-09-08에 RMA 수신자에 Dale Carr를 추가한 것이 **재배치 메일까지 따라
# 들어갔다**. Dale은 RMA 승인권자라 본사 반송 서류에만 필요하고, 미국 재배치는
# 예전처럼 Robert Lazaros 앞이다. 두 흐름은 목적지부터 다르다 - RMA의 Ship To는
# FA LAB / Refurb Center / PURCHASING이고 재배치는 WAY(미국 법인)다.
# 다시 묶지 말 것(한쪽만 바꿔도 다른 쪽이 조용히 따라간다).
US_HQ_MAIL_TO = "Robert Lazaros <robertl@candelamedical.com>"
US_HQ_MAIL_CC = "Miae Jang <miaej@candelamedical.com>"
US_HQ_MAIL_SUBJECT = "Rebalance to US"  # 실측 발송분 제목 그대로
US_HQ_MAIL_BODY = (
    "Hi Bob\n\n"
    "Attaching the documents which we will rebalance to US\n"
)
# 미국 목적지 국가코드(이 코드에서 WAY = 미국). 이 건에만 Bob 앞 메일을 만든다.
US_COUNTRY_CODE = "WAY"

# 2026-08-27 사용자 지적("왜 2장 첨부 안 하고 한장만 한거야 보낼거 다 첨부해야해"):
# **한 TO가 배송(Delivery) 여러 건으로 쪼개지면 CI도 여러 장**인데, 예전 코드는
# CI가 확정될 때마다 그 한 장만 붙여 즉시 발송해서 나머지가 빠졌다.
# 실측 사례 TO 7876545(WAY): 배송 9976051 / 9976055 두 건 -> 용마 답장 초안엔
# CI 2장이 들어갔는데 Bob 앞 메일엔 9976051 한 장만 붙었다.
#
# 그래서 흐름을 "즉시 발송" -> **"초안에 모으고, 조용해지면 한 통으로 발송"**
# 으로 바꿨다(hq_docs_pending 큐 / queue_hq_docs / process_hq_docs_pending 참고):
#   1) CI가 확정될 때마다 그 TO의 Bob 앞 초안을 만들거나 기존 초안에 CI를 덧붙인다
#   2) 마지막 CI가 붙고 HQ_QUIET_MINUTES 동안 새 CI가 없고, 그 TO의 CI 완료
#      대기(ci_pending)도 비어 있으면 그때 초안을 발송한다
# 발송이 조금 늦어지는 대신 **보낼 서류가 전부 들어간 메일 한 통**이 나간다.
# 중간에 발송이 실패해도 초안과 큐가 남아 다음 회차가 다시 발송을 시도한다
# (2026-08-26 15:15:53 실측 실패: COM 'The parameter is incorrect.' -> 그때는
# 초안만 남고 아무도 이어받지 않아 Bob 앞으로 결국 아무것도 안 나갔다).
#
# 2026-09-22 사용자 지적(TO 7886291 실측: CI+라벨 다 준비됐는데 20분을 그냥
# 흘려보냄 - "TO 하나당 한 개씩, 기훈님/용호님한테 보내는 것과 같은 타이밍으로
# 보내야지"): 진짜 안전장치는 "waiting"(그 TO의 ci_pending이 비었는지) 체크다 -
# 배송이 여러 건인 TO(실측: TO 7876545, 배송 9976051/9976055 두 건)는 각 배송이
# ci_pending에 등록돼 있어야 여기서 걸린다. 게다가 FedEx 라벨은 애초에 "TO당
# 한 번"이라 **첫 배송의 CI가 끝나는 시점**에 이미 나온다(_start_fedex_arrangement
# 참고) - 즉 "라벨이 있다"는 게 "이 TO의 배송이 다 끝났다"는 뜻이었던 적이 없다.
# 그 보장은 원래부터 ci_pending 체크가 전부 해주고 있었으므로, 그 위에 얹은
# 대기시간은 안전에 기여한 적이 없다 - 0으로 없앤다(사용자 확인 2026-09-22).
HQ_QUIET_MINUTES = 0

# 2026-08-27 사용자 지시: "bob도 FedEx가 잡히면 라벨 포함해서 보내는걸로 하자".
# 위 TODO(2026-08-20)가 해소된 것 - FedEx 발송이 자동화돼(fedex_ship_watcher)
# 라벨 PDF 경로를 알 수 있게 됐다. 실측 발송분(2026-08-19/07-10/08-07)도 원래
# CI + FedEx 라벨을 같이 보냈다. 그래서 이제 **라벨이 나올 때까지 기다렸다가**
# CI + 라벨을 한 통에 담아 보낸다.
# 라벨은 fedex_ship_watcher가 이 폴더에 "FedEx Label KRP-{국가} {TO#} {AWB}.pdf"로
# 보관한다(파일명에 TO#가 들어가므로 TO#로 찾는다).
FEDEX_LABEL_FOLDER = os.path.join(os.path.dirname(ROOT), "FedEx 라벨")
# 라벨이 이 시간을 넘겨도 안 나오면(FedEx가 실패했거나 수작업으로 빠진 경우)
# 조용히 큐에서 썩지 않도록 한 번만 알린다. 그래도 발송은 하지 않는다 -
# 라벨 없이 보내는 건 사용자 지시에 어긋나므로 사람이 판단할 일이다.
HQ_LABEL_WAIT_HOURS = 6


# ==============================================================
# 스페인(FBC/FBS) Rebalance - Tamara 앞 선적서류 메일 (2026-09-18 추가)
# ==============================================================
# 사용자 지시(2026-09-18): "fedex로 FBS나 FBC로 수출할때(rebalance) Tamara
# Coello한테 Tracking number랑 라벨 CI 첨부해서 보내줘 용마한테 보내면서".
# 미국(WAY)에서 Bob 앞으로 보내는 것과 같은 성격이라 **같은 대기 큐를 그대로
# 쓴다**(HQ_DOC_MAIL_PROFILES) - 목적지별로 수신자/제목/본문만 다르다.
#
# 문구/수신자/첨부는 추측하지 않고 **사용자가 실제로 보낸 메일**을 그대로 따른다
# (보낸편지함 실측 2026-09-18 17:50 "RE: Rebalance to Europe from Korea",
#  TO 7882258 / AWB 877393505997):
#   To = Tamara Coello; Simao Pedro Loureiro de Almeida; Miae Jang
#   CC = Alicia Tran
#   첨부 = "FedEx Label KRP-FBC 7882258 877393505997.pdf" + "KRP-FBC 9982474.pdf"(CI)
#   본문 = "Hi Tamara / Attaching the documents you requested. / Tracking number : ..."
# 같은 스레드에서 Tamara가 밝힌 이유: "Please provide paperwork + tracking number
# ... I need to receive everything in advance to work on the customs clearance."
# 그래서 물건이 도착하기 전에, 라벨(=AWB)이 나오는 대로 보내는 게 핵심이다.
# 2026-09-21 사용자 지시("FBC 앞으로 tamara한테만 보내면 돼 메일"):
# 실측 발송분은 스레드 전체 답장이라 Simao/Miae/Alicia가 같이 있었지만, 자동화가
# 새로 쓰는 메일은 **Tamara 한 명 앞**으로만 보낸다. 참조도 없다.
EU_HQ_MAIL_TO = "Tamara Coello <tamarac@candelamedical.com>"
EU_HQ_MAIL_CC = ""
EU_HQ_MAIL_SUBJECT = "Rebalance to Europe from Korea"  # 실측 스레드 제목 그대로
EU_HQ_MAIL_BODY = (
    "Hi Tamara\n\n"
    "Attaching the documents you requested.\n\n"
    "Tracking number : {tracking}\n"
)

# 2026-09-18: 스페인 건은 **초안까지만** 만들고 사람이 보낸다(사용자 지시:
# "그전에 초안 만들어봐 검토하고 자동화 등록하자"). 실제 발송분으로 문구를
# 확인한 뒤 이 값을 True로 바꾸면 미국 건과 똑같이 자동 발송된다.
EU_HQ_AUTO_SEND = False

# 목적지 국가코드 -> 선적서류 메일 프로필.
#   name       : 로그/알림에 쓰는 이름
#   body       : 본문. "{tracking}"이 있으면 라벨에서 뽑은 AWB로 채운다
#   draft_early: CI가 확정될 때마다 초안을 만들어 첨부를 모을지
#                (미국은 예전부터 그렇게 해왔다. 스페인은 본문에 Tracking이
#                 들어가야 해서 라벨이 나온 뒤 한 번에 만든다)
#   auto_send  : False면 발송하지 않고 초안만 남기고 알린다
HQ_DOC_MAIL_PROFILES = {
    "WAY": {
        "name": "본사(Bob)",
        "to": US_HQ_MAIL_TO,
        "cc": US_HQ_MAIL_CC,
        "subject": US_HQ_MAIL_SUBJECT,
        "body": US_HQ_MAIL_BODY,
        "draft_early": True,
        "auto_send": True,
    },
    "FBC": {
        "name": "스페인(Tamara)",
        "to": EU_HQ_MAIL_TO,
        "cc": EU_HQ_MAIL_CC,
        "subject": EU_HQ_MAIL_SUBJECT,
        "body": EU_HQ_MAIL_BODY,
        "draft_early": False,
        "auto_send": EU_HQ_AUTO_SEND,
    },
}
# FBS는 FBC와 같은 스페인 법인이라 프로필을 공유한다(COUNTRY_NAME_MAP/
# COUNTRY_SHEET_MAP도 둘을 같이 묶어 놓았다).
HQ_DOC_MAIL_PROFILES["FBS"] = HQ_DOC_MAIL_PROFILES["FBC"]

# 라벨 파일명 "FedEx Label KRP-FBC 7882258 877393505997.pdf"의 끝 숫자가 AWB다.
_LABEL_AWB_PATTERN = re.compile(r"(\d{10,})\s*\.pdf$", re.IGNORECASE)

SHAREPOINT_STOCK_MOVEMENTS_URL = (
    "https://syneron.sharepoint.com/sites/APACOperation/Lists/"
    "APAC%20Stock%20Movements/AllItems.aspx"
)


# ==============================================================
# 공통 유틸 (기존 스크립트들과 동일한 패턴)
# ==============================================================
def log(msg: str):
    """2026-08-27: 순서를 뒤집고 print를 감쌌다.

    기존엔 print()가 먼저였는데, 콘솔 인코딩이 cp949라 메시지에 ASCII 밖 기호가
    하나라도 있으면(실측: '✗' U+2717) print에서 UnicodeEncodeError가 나면서
    **로그 파일 기록까지 통째로 건너뛰고 실행이 죽었다**. 실측(TO 7876705,
    2026-08-27 10:28~10:30): 시리얼 재기입 경로에서 3번 다 같은 자리에서 죽었고,
    main()의 최상위 예외 처리마저 같은 log() 호출이라 함께 터져 에러 한 줄도
    안 남았다(로그가 그냥 끊긴 것처럼 보임 - 원인 추적이 거의 불가능했다).
    파일 기록이 먼저이고, 콘솔 출력은 실패해도 무시한다."""
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with _LOG_LOCK:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        try:
            print(line)
        except UnicodeEncodeError:
            # 콘솔이 못 찍는 문자만 대체해서라도 화면에는 남긴다
            enc = (getattr(sys.stdout, "encoding", None) or "utf-8")
            try:
                print(line.encode(enc, errors="replace").decode(enc, errors="replace"))
            except Exception:
                pass


def load_state() -> dict:
    """2026-08-06: 예전에는 파일이 깨져 있으면 빈 상태({})를 돌려줬는데, 그건
    "아직 아무 TO도 처리 안 했다"는 뜻이라 이미 끝낸 TO를 처음부터 다시 돌리게
    된다 - 파일이 있는데 깨졌으면 회차를 중단시킨다(파일 자체가 없는 첫 실행은
    예전처럼 {}로 정상 진행)."""
    return read_json_state(STATE_PATH, "Rebalance TO 처리 이력", strict=True)


def save_state(state: dict):
    # 2026-08-06: open("w")는 파일을 먼저 비우므로 쓰는 도중 죽으면 이력이
    # 깨진다 - 임시 파일에 쓰고 바꿔치기하는 원자적 저장으로 변경.
    atomic_write_json(STATE_PATH, state)


# 2026-08-10 사용자 요청: 자동 발송/초안 메일 글꼴을 굴림 -> 맑은 고딕으로 통일.
# 평문(.Body)으로 만들던 메일은 Outlook의 평문 기본 글꼴을 따라가므로,
# HTML 본문으로 만들어 글꼴을 명시한다(용마 CI 답장은 이미 맑은 고딕 적용됨).
MAIL_FONT_CSS = "font-family:'맑은 고딕',Malgun Gothic,sans-serif;font-size:10.0pt"


def mail_text_to_html(text: str) -> str:
    """평문 본문을 맑은 고딕 HTML로 감싼다.
    HTML은 연속 공백을 하나로 줄이므로 들여쓰기가 뭉개지지 않도록 2칸 이상
    연속 공백은 &nbsp;로 보존한다."""
    import html as html_module
    esc = html_module.escape(str(text or ""))
    esc = esc.replace("\r\n", "\n").replace("\r", "\n")
    esc = re.sub(r"  +", lambda mm: "&nbsp;" * len(mm.group()), esc)
    esc = esc.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
    return f'<div style="{MAIL_FONT_CSS}">' + esc.replace("\n", "<br>") + "</div>"


def send_alert(subject: str, body: str):
    """사람이 봐야 하는 알림은 icbl_ci_watcher.py/pick_release_watcher.py와 동일하게
    자동발송하지 않고 초안만 저장한다."""
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = ALERT_MAIL_TO
    mail.Subject = subject
    mail.HTMLBody = mail_text_to_html(body)
    mail.Save()
    log(f"알림 메일 초안 저장: {subject}")


BACKUP_KEEP = 3


def _backup_before_write(path: str) -> str:
    """CLAUDE.md 규칙: 파일 수정 전 반드시 백업 사본을 만든다.

    2026-08-06: TO를 처리할 때마다 수출신고실적(4.4MB)을 통째로 복사하다 보니
    하루에 6개(26MB)가 쌓였다("백업 파일 왤캐 많아" - 사용자 지적) -> 같은 파일의
    `.bak_<타임스탬프>` 사본은 최신 BACKUP_KEEP개만 남기고 오래된 건 지운다.
    지우는 대상은 **이 함수가 직접 만든 이름 형식**(`<원본경로>.bak_YYYYmmdd_HHMMSS`)
    으로만 한정한다 - 업무 데이터/state json은 이 형식과 겹치지 않는다."""
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
        for name in olds[:-BACKUP_KEEP]:
            os.remove(os.path.join(folder, name))
            log(f"오래된 백업 정리: {name}")
    except Exception as e:
        log(f"[정보] 백업 정리 생략({e})")

    return backup_path


# ==============================================================
# 1) 트리거 메일 탐색 (하루 1회, 아침 10시)
# ==============================================================
def find_new_trigger_mails(processed_to_numbers: set) -> dict:
    """받은편지함 > Operation > Rebalance 폴더에서 "changed TO# to ..." 메일을
    찾아 TO#별로 (국가코드, [파트넘버, ...]) 를 묶어서 반환한다. 이미 처리된
    TO#는 건너뛴다. "...was added..." 류(아직 TO# 없음)는 대상 아님."""
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    inbox = outlook.GetDefaultFolder(6)

    op = None
    for f in inbox.Folders:
        if str(f.Name).strip() == OUTLOOK_PARENT_SUBFOLDER:
            op = f
            break
    if op is None:
        raise RuntimeError(f"Outlook 폴더를 못 찾음: 받은편지함 > {OUTLOOK_PARENT_SUBFOLDER}")

    target = None
    for f in op.Folders:
        if str(f.Name).strip() == TRIGGER_SUBFOLDER:
            target = f
            break
    if target is None:
        raise RuntimeError(
            f"Outlook 폴더를 못 찾음: 받은편지함 > {OUTLOOK_PARENT_SUBFOLDER} > {TRIGGER_SUBFOLDER}"
        )

    items = target.Items
    items.Sort("[ReceivedTime]", True)

    cases: dict[str, dict] = {}
    # 2026-08-06: 예전엔 조용히 건너뛰어서 제원요청 메일 한 통이 통째로 빠져도
    # 흔적이 없었다. 동작은 그대로 두고 흔적만 남긴다(로그 폭주 방지로 앞의 3건만).
    _item_errors = 0
    for i in range(1, min(items.Count, 300) + 1):
        try:
            mail = items.Item(i)
        except Exception as e:
            _item_errors += 1
            if _item_errors <= 3:
                log(f"[경고] Outlook 메일 항목 {i}번을 읽지 못해 건너뜀"
                    f"({type(e).__name__}: {e})")
            elif _item_errors == 4:
                log("[경고] Outlook 항목 읽기 실패가 계속됨 - 이후 같은 로그는 생략합니다")
            continue
        if getattr(mail, "Class", None) != 43:
            continue

        body = str(mail.Body or "")
        m = TRIGGER_BODY_PATTERN.search(body)
        if not m:
            continue  # "was added" 등 TO# 없는 알림은 스킵

        to_no = m.group("to_no")
        # 2026-08-18: RMA 목적지(FA LAB/Refurb Center/PURCHASING)는 전부 본사행
        # 이라 RMA_DEST_CODE 하나로 모은다. 나라 케이스는 예전과 동일하게 대문자
        # 국가코드 그대로.
        country, is_rma = normalize_destination(m.group("country"))
        part_no = m.group("part_no").strip()

        if to_no in processed_to_numbers:
            continue

        case = cases.setdefault(
            to_no, {"country": country, "is_rma": is_rma, "parts": set(), "entry_ids": []})
        # 한 TO 안에서 목적지가 엇갈리면(예: 일부는 ILH, 일부는 FA LAB) 어느 쪽
        # 인보이스를 만들어야 할지 알 수 없다 - 예전엔 첫 메일의 값을 조용히 썼다.
        # RMA 3종끼리 섞인 건 정상이라(실측: TO 7672306) 정규화 후에 비교한다.
        if case["country"] != country:
            case["conflict"] = sorted({case["country"], country})
        case["parts"].add(part_no)
        case["entry_ids"].append(mail.EntryID)

    for to_no, case in cases.items():
        case["parts"] = sorted(case["parts"])
    return cases


# ==============================================================
# 2) SharePoint APAC Stock Movements 조회 (icbl_ci_watcher.py 패턴 재사용)
# ==============================================================
# 2026-08-04 실측(TO 7866440 라이브 조회): 이 리스트의 컬럼 순서는
# ID/Description/Status/Part Number/QTY/From/To/TO#/Delivery#/Receive TO#/
# Receive Delivery#/Oracle Receipt#/Tracking Number/Freight Forwarder/
# Comments/Created/Action/Reason for Shipment/Relevant contacts/Currency/
# Freight Cost/Created By/Modified By/Modified/Attachments/Sign-off status.
# TO# 뒤쪽 필드(Delivery#, Receive TO# 등)는 값이 없으면 그냥 그 줄 자체가
# 통째로 비어서 안 나오지만(rebalance 되기 전에는 대부분 비어있음), TO# 앞의
# ID/Description/Status/Part Number/QTY/From/To는 항상 채워져 있어 오프셋이
# 안정적이다. Description은 "KRP - AUP 1301-00-9395"/"KRP-ILH-SBA100128"처럼
# "국가 - 국가 파트넘버" 형태라 이걸 앵커로 각 행(레코드)의 시작을 찾는다.
# 2026-08-18: RMA 행은 Description이 "KRP-FA LAB SBA100775"처럼 목적지 이름에
# 공백이 들어가서 기존 `\S{2,5}`로는 레코드로 인식되지 않았다 - RMA 목적지
# 이름만 예외로 먼저 허용한다(나라 케이스 매칭은 그대로).
# 2026-08-26: 구분자 \s+ -> [\s-]+ (실측 TO 7877405: Description이
# "KRP-ILH-FIN101958"처럼 대시만 있으면 레코드 인식 실패 -> TO 못 찾음).
# 트리거 메일 패턴(TRIGGER_BODY_PATTERN)과 같은 규칙으로 맞췄다.
_SP_DESCRIPTION_PATTERN = re.compile(
    r"^\S{2,5}\s*-\s*(?:" + RMA_DEST_PATTERN + r"|\S{2,5})[\s-]+\S+$", re.IGNORECASE)


def _parse_sp_records(body_text: str) -> list[dict]:
    """APAC Stock Movements 화면 텍스트를 레코드 목록으로 파싱한다.
    (lookup_to_lines_via_sharepoint에 있던 파싱을 재사용하려고 분리, 2026-09-04)"""
    lines = [ln.strip() for ln in body_text.split("\n") if ln.strip()]
    records = []
    for idx, ln in enumerate(lines):
        if not _SP_DESCRIPTION_PATTERN.match(ln):
            continue
        if idx < 1 or idx + 6 >= len(lines):
            continue
        records.append({
            "id": lines[idx - 1],
            "description": ln,
            "status": lines[idx + 1],
            "part_no": lines[idx + 2],
            "qty": lines[idx + 3],
            "from": lines[idx + 4],
            "to": lines[idx + 5],
            "to_no": lines[idx + 6],
        })
    return records


# SharePoint에서 트리거를 만들 때 "아직 안 나간 건"으로 보는 상태값.
# 실측 확인(2026-09-04)된 Status 값: New / @Warehouse / Shipped.
# 2026-09-15 추가: "RMA Approved"(본사(미국) 반송 승인 건, Purchasing/Refurb
# Centre/FA-LAB행)가 빠져있어서 RMA 건이 이 경로로는 절대 안 잡히고 있었다.
# 원래는 SharePoint 알림 메일(find_new_trigger_mails)이 먼저 걸러줘서 문제가
# 안 드러났는데, 그 메일 자체가 2026-08-31 14:36 이후로 끊긴 상태(Outlook
# Operation>Rebalance 폴더 확인, 실측)라 지금은 이 SharePoint 직접조회가
# 사실상 유일한 트리거 경로다 - RMA 건(TO 7881992, KRP->Purchasing/Refurb
# Centre/FA-LAB, Status='RMA Approved')이 안 잡히는 것으로 실측 확인 후 추가.
SP_OPEN_STATUSES = {"New", "@Warehouse", "RMA Approved"}

# SharePoint 목록이 실제로 그려질 때까지 기다리는 한도(2026-09-14)
SP_TRIGGER_LOAD_TIMEOUT_SEC = 60


def find_new_trigger_cases_from_sharepoint_legacy(driver, processed_to_numbers: set) -> dict:
    """(2026-09-15: REST API 버전으로 대체돼 더 이상 호출되지 않음 - 화면
    스크래핑 방식이 문제 생겼을 때 참고/롤백용으로만 보존. 새 구현은 아래
    find_new_trigger_cases_from_sharepoint() 참고 - Modified 날짜 필터가 반드시
    같이 있어야 하는 이유가 그 함수 docstring에 있음.)
    APAC Stock Movements에서 **From=KRP + TO# 배정 + 미출고**인 건을 직접 읽어
    트리거 메일과 같은 모양의 cases를 만든다.

    2026-09-04 배경: SharePoint 알림 메일이 오류로 끊겼다(실측 - 받은편지함 >
    Operation > Rebalance 폴더가 2026-08-31 14:36 이후 새 메일 0건이고, 메일함
    전체 1,759건을 뒤져도 TO 7878369/7878539를 언급한 메일이 없다. 같은 기간
    다른 폴더는 정상 수신). 메일이 유일한 트리거라 그 동안 재배치 건이 통째로
    멈춘다 - 원천을 직접 보는 경로를 둔다.

    메일 트리거와 같은 조건을 본다: TO#가 배정됐고(=7자리), 출발지가 KRP이고,
    아직 처리 안 한 TO. 상태가 Shipped면 이미 끝난 건이라 제외한다."""
    driver.get(f"{SHAREPOINT_STOCK_MOVEMENTS_URL}?q=KRP")
    # 2026-09-14: 예전 대기 조건은 `"KRP" in body_text`였는데, 조회 URL이 ?q=KRP라
    # **검색창에 그 글자가 먼저 찍혀서** 목록이 그려지기도 전에 통과했다. 그러면
    # 레코드 0건으로 읽고 "신규 없음"으로 조용히 끝난다(실측: 2026-09-14 하루 종일
    # KRP-CHP TO 7881974를 못 잡았고, 같은 코드를 수동으로 부르면 바로 잡혔다).
    # 화면 글자가 아니라 **실제로 레코드가 파싱되는지**를 기다린다.
    records = []
    body_text = ""
    deadline = time.time() + SP_TRIGGER_LOAD_TIMEOUT_SEC
    while time.time() < deadline:
        try:
            body_text = driver.execute_script("return document.body.innerText;") or ""
        except Exception:
            body_text = ""
        records = _parse_sp_records(body_text)
        if records:
            break
        time.sleep(2)

    if not records:
        # 진짜로 한 건도 없을 수도, 화면이 안 그려진 것일 수도 있다 - 구분이
        # 안 되므로 "없음"으로 단정하지 않고 흔적을 남긴다.
        log(f"[SharePoint트리거] 레코드를 하나도 파싱하지 못함 "
            f"({SP_TRIGGER_LOAD_TIMEOUT_SEC}초 대기, 화면 글자 {len(body_text)}자) "
            f"- 이번 회차 생략")
        return {}
    log(f"[SharePoint트리거] 재고이동 레코드 {len(records)}건 조회됨")

    cases: dict[str, dict] = {}
    for r in records:
        to_no = str(r.get("to_no") or "").strip()
        if not re.fullmatch(r"\d{7}", to_no):
            continue                       # TO# 미배정이거나 파싱이 어긋난 줄
        if str(r.get("from") or "").strip().upper() != "KRP":
            continue                       # KRP발만(들어오는 건은 대상 아님)
        if to_no in processed_to_numbers:
            continue
        if str(r.get("status") or "").strip() not in SP_OPEN_STATUSES:
            continue                       # Shipped 등 이미 끝난 건
        country, is_rma = normalize_destination(r.get("to"))
        part_no = str(r.get("part_no") or "").strip()
        case = cases.setdefault(
            to_no, {"country": country, "is_rma": is_rma, "parts": set(), "entry_ids": []})
        if case["country"] != country:
            case["conflict"] = sorted({case["country"], country})
        if part_no:
            case["parts"].add(part_no)

    if cases:
        log(f"[SharePoint트리거] 메일 없이 SharePoint에서 신규 TO {sorted(cases)} 감지 "
            f"(From=KRP, 미출고)")
    return cases


_SP_TRIGGER_SCAN_JS = """
var cb = arguments[arguments.length-1];
var url = arguments[0];
fetch(url, {headers: {Accept: 'application/json;odata=nometadata'}})
  .then(function(r){ return r.text().then(function(t){ cb(JSON.stringify({status: r.status, body: t})); }); })
  .catch(function(e){ cb(JSON.stringify({error: String(e)})); });
"""


# 2026-09-15 실측: 오래된 완료 건이 Status를 Shipped로 안 바꾼 채 방치되는
# 데이터 정합성 문제가 실제로 있다(2022~2024년 Modified인 "New" 상태 건 다수
# 발견). Status만으로는 옛날 죽은 건과 진짜 신규 건을 못 가른다 - Modified가
# 최근 SP_TRIGGER_MAX_AGE_DAYS 이내인 것만 후보로 본다. 메일 알림이 끊긴 게
# 2026-08-31이고 이 폴백 자체가 그 이후 상황을 감당하려고 만든 것이므로,
# 30일이면 "메일 끊긴 뒤로 새로 생긴 진짜 열린 건"을 놓칠 걱정 없이 옛날
# 데이터 쓰레기는 확실히 차단한다.
SP_TRIGGER_MAX_AGE_DAYS = 30


def find_new_trigger_cases_from_sharepoint(driver, processed_to_numbers: set) -> dict:
    """APAC Stock Movements를 REST API로 조회해 **From=KRP + TO# 배정 + 미출고 +
    최근 SP_TRIGGER_MAX_AGE_DAYS일 이내 수정**인 건을 찾아 트리거 메일과 같은
    모양의 cases를 만든다(2026-09-15: 화면 스크래핑 대신 REST -
    lookup_to_lines_via_sharepoint()와 같은 패턴).

    2026-09-15 실측 경고: Status(New/@Warehouse/RMA Approved)만으로 필터링하면
    2022~2024년 Modified인 옛날 완료 건(Status가 Shipped로 안 바뀐 채 방치됨)
    까지 "신규 트리거"로 잡혀서(약 70건 오탐 확인) 이미 끝난 건에 용마 메일이
    무더기로 나갈 뻔했다. 그래서 Modified 날짜 필터를 반드시 같이 건다 - 이
    필터 없이 쓰면 안 된다(아래 SP_TRIGGER_MAX_AGE_DAYS 참고).

    화면 렌더링을 기다릴 필요가 없어 legacy에 있던 폴링(SP_TRIGGER_LOAD_TIMEOUT_SEC
    60초)과 "0건 = 아직 안 그려짐일 수도 있다"는 불확실성이 통째로 없어진다 -
    쿼리 결과가 0건이면 그 자체로 확정된 "지금은 대상 없음"이다."""
    import json as _json
    from datetime import datetime, timedelta, timezone
    from urllib.parse import quote

    if SHAREPOINT_SITE_PATH not in (driver.current_url or ""):
        driver.get(SHAREPOINT_STOCK_MOVEMENTS_URL)
        time.sleep(6)

    status_filter = " or ".join(f"Status eq '{s}'" for s in SP_OPEN_STATUSES)
    since = (datetime.now(timezone.utc) - timedelta(days=SP_TRIGGER_MAX_AGE_DAYS))
    since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    filter_expr = (f"From eq 'KRP' and TO_x0023_ ne null and ({status_filter}) "
                   f"and Modified ge datetime'{since_str}'")
    url = (f"{SHAREPOINT_SITE_PATH}/_api/web/lists/getbytitle('{SHAREPOINT_LIST_TITLE}')/items"
           f"?$select=TO_x0023_,PartNumber,Status,To,Modified&$top=5000&$filter={quote(filter_expr)}")

    try:
        raw = driver.execute_async_script(_SP_TRIGGER_SCAN_JS, url)
        outer = _json.loads(raw)
    except Exception as e:
        log(f"[경고] SharePoint 트리거 API 호출 실패: {e} - 이번 회차 생략")
        return {}

    if "error" in outer:
        log(f"[경고] SharePoint 트리거 API 네트워크 에러: {outer['error']} - 이번 회차 생략")
        return {}
    if outer.get("status") != 200:
        log(f"[경고] SharePoint 트리거 API가 {outer.get('status')} 응답: "
            f"{outer.get('body', '')[:300]} - 이번 회차 생략")
        return {}

    try:
        items = _json.loads(outer["body"]).get("value", [])
    except Exception as e:
        log(f"[경고] SharePoint 트리거 API 응답 형식 이상: {e} - 이번 회차 생략")
        return {}

    log(f"[SharePoint트리거] 재고이동 레코드 {len(items)}건 조회됨(From=KRP, 미출고 필터 적용)")

    cases: dict[str, dict] = {}
    for it in items:
        to_raw = it.get("TO_x0023_")
        try:
            to_no = str(int(to_raw))
        except (TypeError, ValueError):
            continue
        if not re.fullmatch(r"\d{7}", to_no):
            continue                       # TO# 형식이 이상한 항목
        if to_no in processed_to_numbers:
            continue
        country, is_rma = normalize_destination(it.get("To"))
        part_no = str(it.get("PartNumber") or "").strip()
        case = cases.setdefault(
            to_no, {"country": country, "is_rma": is_rma, "parts": set(), "entry_ids": []})
        if case["country"] != country:
            case["conflict"] = sorted({case["country"], country})
        if part_no:
            case["parts"].add(part_no)

    for case in cases.values():
        case["parts"] = sorted(case["parts"])

    if cases:
        log(f"[SharePoint트리거] 메일 없이 SharePoint에서 신규 TO {sorted(cases)} 감지 "
            f"(From=KRP, 미출고)")
    return cases


def lookup_to_lines_via_sharepoint_legacy(driver, to_number: str) -> list[dict] | None:
    """(2026-09-15: REST API 버전으로 대체돼 더 이상 호출되지 않음 - 화면
    스크래핑 방식이 문제 생겼을 때 참고/롤백용으로만 보존. 새 구현은 바로 아래
    lookup_to_lines_via_sharepoint() 참고.)
    icbl_ci_watcher.py의 lookup_receive_delivery_via_sharepoint()와 같은 방식
    (검색 쿼리 URL + document.body.innerText 줄 단위 파싱)으로 TO#를 조회해
    파트넘버/Qty 목록을 읽는다. 한 TO#에 파트가 여러 개면 여러 레코드(행)로
    나오므로 전부 모아서 반환한다."""
    driver.get(f"{SHAREPOINT_STOCK_MOVEMENTS_URL}?q={to_number}")
    time.sleep(6)

    body_text = driver.execute_script("return document.body.innerText;")
    if to_number not in body_text:
        log(f"[정보] SharePoint에서 TO {to_number}를 못 찾음(아직 미등록일 수 있음)")
        return None

    lines = [ln.strip() for ln in body_text.split("\n") if ln.strip()]
    records = []
    for idx, ln in enumerate(lines):
        if not _SP_DESCRIPTION_PATTERN.match(ln):
            continue
        if idx < 1 or idx + 6 >= len(lines):
            continue
        records.append({
            "id": lines[idx - 1],
            "description": ln,
            "status": lines[idx + 1],
            "part_no": lines[idx + 2],
            "qty": lines[idx + 3],
            "from": lines[idx + 4],
            "to": lines[idx + 5],
            "to_no": lines[idx + 6],
        })

    matched = [r for r in records if r["to_no"] == to_number]
    if not matched:
        log(f"[경고] SharePoint에서 TO {to_number} 텍스트는 찾았지만 레코드 매칭 실패 "
            f"(파싱된 레코드 {len(records)}개, 화면 구조가 바뀌었을 수 있음)")
        return None

    result = [
        {"part_no": r["part_no"], "qty": int(r["qty"]) if r["qty"].isdigit() else r["qty"]}
        for r in matched
    ]
    log(f"[SharePoint] TO {to_number} -> {result}")
    return result


_SP_LOOKUP_TO_JS = """
var cb = arguments[arguments.length-1];
var TO = arguments[0], site = arguments[1], listTitle = arguments[2];
var q = site + "/_api/web/lists/getbytitle('" + listTitle + "')/items"
        + "?$select=PartNumber,QTY&$filter=TO_x0023_%20eq%20" + TO;
fetch(q, {headers: {Accept: 'application/json;odata=nometadata'}})
  .then(function(r){ return r.text().then(function(t){ cb(JSON.stringify({status: r.status, body: t})); }); })
  .catch(function(e){ cb(JSON.stringify({error: String(e)})); });
"""


def lookup_to_lines_via_sharepoint(driver, to_number: str) -> list[dict] | None:
    """SharePoint 'APAC Stock Movements'를 REST API로 조회해 TO#의 파트넘버/Qty
    목록을 읽는다(2026-09-15: 화면 스크래핑 대신 write_delivery_to_sharepoint()가
    이미 쓰던 것과 같은 REST 패턴 재사용 - 내부 필드명 TO_x0023_/PartNumber/QTY도
    그 함수에서 확인된 값 그대로).

    반환 계약은 legacy와 동일하게 유지한다(호출부 lookup_to_lines_confirmed는
    무수정): TO#가 아직 리스트에 없거나 조회가 실패하면 None, 있으면
    [{"part_no": str, "qty": int}, ...] (한 TO#에 파트가 여러 개면 여러 레코드).
    legacy도 실패 종류를 구분하지 않고 전부 None으로 반환해 호출부의 재시도
    로직(lookup_to_lines_confirmed)에 맡기던 방식이라, 여기서도 그대로 따른다."""
    import json as _json

    if SHAREPOINT_SITE_PATH not in (driver.current_url or ""):
        driver.get(SHAREPOINT_STOCK_MOVEMENTS_URL)
        time.sleep(6)

    try:
        raw = driver.execute_async_script(
            _SP_LOOKUP_TO_JS, str(to_number), SHAREPOINT_SITE_PATH, SHAREPOINT_LIST_TITLE)
        outer = _json.loads(raw)
    except Exception as e:
        log(f"[경고] SharePoint API 호출 실패(TO {to_number}): {e}")
        return None

    if "error" in outer:
        log(f"[경고] SharePoint API 네트워크 에러(TO {to_number}): {outer['error']}")
        return None
    if outer.get("status") != 200:
        log(f"[경고] SharePoint API가 {outer.get('status')} 응답(TO {to_number}): "
            f"{outer.get('body', '')[:200]}")
        return None

    try:
        items = _json.loads(outer["body"]).get("value", [])
    except Exception as e:
        log(f"[경고] SharePoint API 응답 형식 이상(TO {to_number}): {e}")
        return None

    if not items:
        log(f"[정보] SharePoint에서 TO {to_number}를 못 찾음(아직 미등록일 수 있음)")
        return None

    result = [
        {"part_no": it.get("PartNumber"),
         "qty": int(it["QTY"]) if it.get("QTY") is not None else it.get("QTY")}
        for it in items
    ]
    log(f"[SharePoint] TO {to_number} -> {result}")
    return result


def lookup_to_lines_confirmed(
    driver, to_number: str, expected_parts: set[str],
    attempts: int = 3, wait_sec: int = 30,
) -> list[dict] | None:
    """lookup_to_lines_via_sharepoint()를 그대로 신뢰하지 않고 여러 번 확인한다.

    **2026-08-06 실측으로 발견한 문제 2가지**를 막기 위한 함수:
    1. TO 7870379가 처음 트리거 스캔 때 SharePoint 미등록으로 못 잡혔다가
       7분 뒤 재조회하니 정상 등록돼 있었음(qty 없이 "?"로 용마에 잘못 발송된
       사고로 이어짐, 사용자 지적으로 정정 메일 발송).
    2. 같은 TO 7870379를 5분 뒤 다시 조회하니 이번엔 **이미 한 번 찾았던
       레코드가 다시 "못 찾음"으로 나옴** - SharePoint `?q=` 검색이 인덱스
       갱신 주기 때문에 찾았다/못 찾았다를 오갈 수 있는 것으로 추정(플레이키).
    이 두 문제 다 "한 번 조회 성공 = 확정"으로 보면 안 된다는 뜻이라, 여기서는
    (a) 기대하는 파트(트리거 메일에서 나온 case["parts"]) 전부가 잡혀야 확정으로
    보고, 일부만 잡히면(미등록 파트가 섞여있으면) 아직 미완성으로 취급하며,
    (b) 짧게 재시도해서 검색 플레이키니스를 흡수한다. 그래도 실패하면 호출부가
    메일을 보내지 않고 다음 스캔으로 넘긴다(2026-08-06 사용자 지시: 확인 안 된
    Item/국가/TO/qty로는 절대 용마 메일을 보내지 않는다)."""
    for attempt in range(attempts):
        lines = lookup_to_lines_via_sharepoint(driver, to_number)
        if lines:
            found_parts = {l["part_no"] for l in lines}
            missing = expected_parts - found_parts
            if not missing:
                return lines
            log(f"[정보] TO {to_number} 확인 {attempt + 1}/{attempts}: 일부 파트만 "
                f"등록됨(누락={sorted(missing)}) - 재확인")
        else:
            log(f"[정보] TO {to_number} 확인 {attempt + 1}/{attempts}: 아직 못 찾음")
        if attempt < attempts - 1:
            time.sleep(wait_sec)
    return None


# ==============================================================
# 3) 용마로지스 앞 제원 요청 메일
# ==============================================================
# 제원정보 표에 붙일 빈 여유 행 수 / 파트 하나가 차지할 수 있는 최대 행 수
TABLE_SPARE_ROWS = 2
TABLE_MAX_ROWS_PER_PART = 30


def yongma_spec_table_html(
    to_numbers: list[str], parts_qty_by_to: dict[str, list[dict]],
) -> str:
    """용마가 채워 넣을 제원정보 표(Item / Qty / Locator / Serial number)를 만든다.

    2026-08-27 사용자 요청(스크린샷으로 형식 지정): 그동안은 본문에 파트/수량만
    평문으로 나열하고 용마가 자유서식으로 회신해서, 로케이터/시리얼이 줄바꿈
    형식마다 다르게 와서 파싱 조건을 계속 늘려왔다([[rebalance-to-automation-sop]]
    4번, YONGMA_LOCATION_PATTERN 주변 주석 참고). 요청 메일에 아예 표를 넣어
    Item만 우리가 채워 보내고 **Qty/Locator/Serial number는 용마가 채우게** 하면
    회신 형식이 고정돼 파싱이 안정된다.

    **Qty를 미리 채우지 않는 이유(2026-08-27 사용자 지시)**: 시리얼 번호가 있는
    제품은 개체마다 행을 쪼개야 해서(qty 2면 2행) 우리가 박아둔 Qty가 오히려
    방해가 된다. 어떤 파트에 시리얼이 있는지는 우리 쪽에서 알 수 없으므로
    행 분할과 수량 기입은 전부 용마에게 맡긴다 - 총수량은 표 위 평문 줄
    ("7123-00-0593 2개")로 이미 전달되니 정보가 빠지지도 않는다.

    **행 수(2026-08-27 사용자 추가 지시)**: 시리얼이 있으면 개체마다 한 줄이
    필요하므로 파트당 qty 개수만큼 행을 미리 뽑아둔다(qty 2면 Item이 적힌 행이
    2줄). 용마가 표를 직접 늘리지 않아도 되게 하려는 것이고, 시리얼이 없는
    파트면 남는 줄은 그냥 비워두면 된다. 여기에 더해 빈 여유 행
    (TABLE_SPARE_ROWS)을 표 끝에 붙여 예상 못 한 분할(로케이터가 여러 개로
    쪼개지는 경우 등)에도 칸이 모자라지 않게 한다.

    TO가 여러 건 합쳐진 경우엔 어느 TO 것인지 알 수 있도록 Item 칸에 TO#를
    같이 적는다(별도 컬럼을 추가하면 스크린샷 형식에서 벗어남)."""
    import html as html_module

    multi = len(to_numbers) > 1
    th = ("border:1px solid #000;padding:2px 6px;text-align:left;"
          "font-weight:normal")
    td = "border:1px solid #000;padding:2px 6px;height:18px"
    rows = []
    for to_no in to_numbers:
        for p in parts_qty_by_to.get(to_no) or []:
            item = str(p.get("part_no", ""))
            if multi:
                item = f"{item} (TO {to_no})"
            # qty만큼 행을 뽑는다. qty가 숫자가 아니거나(SharePoint 조회 실패 등)
            # 비어있으면 1행, 비정상적으로 크면 표가 감당 못 하니 상한을 둔다.
            try:
                n_rows = int(str(p.get("qty", "")).strip())
            except (TypeError, ValueError):
                n_rows = 1
            n_rows = max(1, min(n_rows, TABLE_MAX_ROWS_PER_PART))
            for _ in range(n_rows):
                rows.append(
                    f'<tr><td style="{td}">{html_module.escape(item)}</td>'
                    f'<td style="{td}"></td>'
                    f'<td style="{td}"></td><td style="{td}"></td></tr>'
                )
    for _ in range(TABLE_SPARE_ROWS):  # 여유 행(파트 정보가 비어도 최소 이만큼은 남는다)
        rows.append(f'<tr><td style="{td}"></td><td style="{td}"></td>'
                    f'<td style="{td}"></td><td style="{td}"></td></tr>')
    return (
        f'<table style="{MAIL_FONT_CSS};border-collapse:collapse">'
        f'<tr><th style="{th}">Item</th><th style="{th}">Qty</th>'
        f'<th style="{th}">Locator</th><th style="{th}">Serial number</th></tr>'
        + "".join(rows) + "</table>"
    )


def create_yongma_request_mail(
    to_numbers: list[str], country_code: str, parts_qty_by_to: dict[str, list[dict]],
    is_rma: bool = False, draft_only: bool = False,
):
    """제목 "KRP-(국가) Rebalance (TO#[+TO#...])" 형식, 본문에 파트넘버/qty
    나열 + 제원정보 요청.

    **2026-08-04 실측 정정**: 처음엔 제목을 "KRP-(국가)TO"로 잘못 짰었는데,
    실제 Sent Items의 오늘 발송 메일("kRP-AUP Rebalance 7868330", 10:06 발송)을
    보니 TO#는 본문이 아니라 **제목**에 들어간다 - "KRP-{국가} Rebalance
    {TO#}" 형식. 본문에는 TO#가 안 들어가고 파트/수량만 나열됨. 이 TO#가
    제목에 있어서 find_yongma_replies()가 회신 제목에서 TO#를 뽑아 정확한
    pending 케이스에 매칭할 수 있음(예전엔 pending이 1건일 때만 추측 매칭).

    **2026-08-04 사용자 지시로 자동발송 전환**: TO 7866440 케이스에서 초안을
    사용자가 직접 보낸 뒤 "자동화에선 너가 직접 보내버려"라고 명시적으로
    요청 - 다른 자동화들(pick_release_watcher 등)이 실측 검증 후 draft->send로
    전환한 것과 달리, 이건 처음부터 바로 자동발송으로 시작한다(사용자가 이미
    한 번 직접 검증한 셈 치는 것으로 판단).

    **2026-08-06 사용자 요청으로 다중 TO 지원 추가**: 같은 나라로 나가는 TO가
    원래 하나로 묶여야 할 물량이 쪼개져서 같은 스캔에서 여러 건 잡히면, 회신을
    나중에 짜맞춰 매칭하기보다 **보낼 때부터 한 통으로 합쳐서 발송**한다(용마도
    실제로 회신을 한 통으로 묶어 보내는 경우가 있어, 아예 보내는 쪽에서 합치는
    게 회신 매칭 부담을 없애는 더 근본적인 해법 - 사용자 제안). `to_numbers`가
    1개면 기존과 동일하게 동작, 여러 개면 제목에 "+"로 이어붙이고 본문을
    TO#별 블록으로 나눠 표시한다 - 제목의 TO#는 find_yongma_replies()가
    findall로 전부 뽑아 pending_cases와 정확히 매칭한다."""
    import win32com.client

    country_name = COUNTRY_NAME_MAP.get(country_code, country_code)
    # 2026-08-18: RMA는 국가간 재배치가 아니라 본사 반송이라 제목의 구분 단어를
    # "Rebalance" 대신 "RMA"로 쓴다(회신 제목에도 그대로 남아 find_yongma_replies가
    # TO#로 매칭한다 - 그래서 그쪽 필터에도 RMA를 같이 넣어뒀다).
    kind = "RMA" if is_rma else "Rebalance"
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = YONGMA_REQUEST_TO
    mail.Subject = f"KRP-{country_code} {kind} {'+'.join(to_numbers)}"

    multi = len(to_numbers) > 1
    blocks = []
    for to_no in to_numbers:
        parts_qty = parts_qty_by_to.get(to_no) or []
        part_lines = "\n".join(f"{p['part_no']} {p.get('qty', '?')}개" for p in parts_qty)
        blocks.append(f"[TO {to_no}]\n{part_lines}" if multi else part_lines)
    body_parts = "\n\n".join(blocks)

    intro = "본사 반송(RMA) 건입니다" if is_rma else f"{country_name} Rebalance 건입니다"
    body = (
        "안녕하세요 기훈님 용호님\n\n"
        f"{body_parts}\n\n"
        f"{intro}" + (f"(TO {len(to_numbers)}건 합침)" if multi else "") + "\n"
        "제원정보 부탁드립니다.\n"
    )
    # 2026-08-27: 평문 본문 아래에 제원정보 표를 붙인다(위 함수 주석 참고).
    mail.HTMLBody = (
        mail_text_to_html(body)
        + yongma_spec_table_html(to_numbers, parts_qty_by_to)
        + f'<div style="{MAIL_FONT_CSS}"><br>감사합니다.<br></div>'
    )
    if draft_only:
        mail.Save()
        log(f"용마 제원요청 메일 초안 저장: KRP-{country_code} {kind} "
            f"{'+'.join(to_numbers)}")
    else:
        mail.Send()
        log(f"용마 제원요청 메일 자동발송: KRP-{country_code} {kind} "
            f"{'+'.join(to_numbers)}")


# ==============================================================
# 4) 용마 회신 탐색 (1시간에 1회)
# ==============================================================
# 2026-08-04 실측(용마 회신 16건 대조): 가장 흔한 형식은 한 줄에
# "파트넘버 로케이터 수량EA"(예: "7123-00-0477 B3-2-51 1EA")가 붙어 있는 것.
# 로케이터는 예외 없이 "글자+숫자-숫자-숫자" 패턴(예: B3-2-51)이라 이걸 앵커로
# 삼아 그 앞 토큰을 파트넘버로, 뒤 숫자를 수량으로 읽는다.
# 단, 실측 중 최소 1건(2026-04-07, 청국 Rebalance 9883480)은 "파트넘버 수량EA"
# 줄과 "로케이터 수량EA" 줄이 따로 떨어져 나오는 완전히 다른 형식이었다(한
# 파트가 로케이터 여러 개로 나뉜 경우로 추정) - 이 형식은 아직 지원 안 함,
# 그런 메일은 로케이터가 비어있거나 이상한 값으로 나오니 아래
# _looks_like_part_no()로 걸러서 사람 확인으로 넘긴다.
YONGMA_LOCATION_PATTERN = re.compile(
    r"(?P<part_no>\S+)\s+(?P<locator>[A-Za-z]\d+-\d+-\d+)\s+(?P<qty>\d+)\s*EA",
    re.IGNORECASE,
)

# 2026-08-26 실측(7876545 미국 건): 줄바꿈 형식 - 파트/로케이터가 각 줄에 따로
# 오고 수량 표기가 없다:
#   50 X 35 X 16    3.3kg
#   7123-00-0593
#   A2-7-1
#   S/N : D12314K-0823100
# 기존 한 줄 패턴("파트 로케이터 수량EA")과 병합해 사용한다.
YONGMA_LOCATION_PATTERN_MULTILINE = re.compile(
    r"(?P<part_no>\S+)\s+(?P<locator>[A-Za-z]\d+-\d+-\d+)\b",
    re.IGNORECASE,
)


def parse_yongma_table_html(html: str) -> list[dict]:
    """용마 회신의 **Item / Qty / Locator / Serial number 표**를 HTML에서 읽는다.

    2026-09-04 배경: 요청 서식을 4컬럼 표로 고정한 뒤(SOP RULE 01) 회신도 표로
    온다. 그런데 평문 파싱은 로케이터를 앵커로 삼아 **바로 앞 토큰**을 파트넘버로
    읽는 방식이라, 표에서는 그 자리가 Qty다 - 실측(2026-09-04 TO 7878369/7878539)
    에서 part_no가 '1','2','1'로, 즉 수량이 품번 자리에 들어갔다. 열이 몇 개든
    위치를 추측하지 않도록 헤더 이름으로 컬럼을 찾는다([[mail-table-parse-html-not-plaintext]]).

    - 회신에는 인용된 원본 요청표(Locator가 빈 표)도 같이 들어있다 - 로케이터가
      채워진 행만 쓴다.
    - Serial number가 'N/A'/'-'/빈칸이면 그 품목은 시리얼이 없는 것이다
      (2026-09-04 사용자 확인: "스페인건 N/A는 없는거야 serial number").
    파싱할 표가 없으면 빈 리스트를 돌려주고 호출부가 기존 평문 파싱으로 넘어간다."""
    if not html:
        return []
    try:
        import lxml.html as LH
    except Exception as e:
        log(f"[정보] lxml 없음({e}) - 평문 파싱으로 진행")
        return []

    def _norm(s):
        return re.sub(r"\s+", " ", str(s or "")).strip()

    NONE_TOKENS = {"", "-", "n/a", "na", "없음", "x"}
    out: list[dict] = []
    try:
        doc = LH.fromstring(html)
    except Exception as e:
        log(f"[정보] 용마 회신 HTML 파싱 실패({e}) - 평문 파싱으로 진행")
        return []

    for tb in doc.xpath("//table"):
        rows = []
        for tr in tb.xpath(".//tr"):
            cells = [_norm(c.text_content()) for c in tr.xpath("./td|./th")]
            if any(cells):
                rows.append(cells)
        if len(rows) < 2:
            continue
        head = [c.lower() for c in rows[0]]
        try:
            i_item = next(i for i, c in enumerate(head) if c.startswith("item"))
            i_loc = next(i for i, c in enumerate(head) if "locator" in c)
        except StopIteration:
            continue                     # 이 표는 우리 서식이 아니다
        i_qty = next((i for i, c in enumerate(head) if c.startswith("qty")), None)
        i_sn = next((i for i, c in enumerate(head) if "serial" in c), None)

        for cells in rows[1:]:
            def _get(idx):
                return cells[idx] if idx is not None and idx < len(cells) else ""
            part_no, locator = _get(i_item), _get(i_loc)
            if not part_no or not locator:
                continue                 # 인용된 빈 요청표 행
            rec = {"part_no": part_no, "locator": locator, "qty": _get(i_qty)}
            sn_raw = _get(i_sn)
            if sn_raw.lower() not in NONE_TOKENS:
                sns = [s.strip() for s in re.split(r"[,\s/]+", sn_raw) if s.strip()]
                sns = [s for s in sns if s.lower() not in NONE_TOKENS]
                if sns:
                    rec["sn"] = sns
            # 2026-09-18 버그 수정(사용자 지적, TO 7882258 FIN101959 실사례):
            # 시리얼 있는 품목은 시리얼 하나당 한 행(같은 part_no+locator,
            # qty="1"씩 5행)으로 온다 - (part_no, locator)만으로 중복 판정하면
            # 진짜로 다른 행(시리얼만 다름)을 전부 "중복"으로 보고 1행만 남기고
            # 4행을 버렸다(오라클 Requested Quantity 5 vs 이 함수가 돌려준
            # 수량 1 불일치의 진짜 원인). 시리얼까지 키에 넣어야 서로 다른
            # 시리얼 행이 안 버려진다.
            key = (part_no, locator, tuple(rec.get("sn", [])))
            if not any((r["part_no"], r["locator"], tuple(r.get("sn", []))) == key
                       for r in out):
                out.append(rec)
    return out


def _looks_like_part_no(token: str) -> bool:
    """"2ea"/"1ea"처럼 수량이 파트넘버 자리에 잘못 매칭된 경우를 걸러낸다
    (2026-08-04 실측: 파트+로케이터가 다른 줄에 나뉜 메일에서 발생 확인)."""
    return not re.fullmatch(r"\d+\s*ea", token, re.IGNORECASE)


def find_yongma_replies(processed_entry_ids: set) -> list[dict]:
    """받은편지함 > Operation > Yongma 폴더에서 제목에 "Rebalance"가 포함된
    메일을 찾아 박스 정보/Location(locator)/qty를 best-effort로 파싱한다.
    자유서식 본문이라 실제 케이스를 몇 건 겪으며 파싱 규칙을 다듬어야 한다."""
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    inbox = outlook.GetDefaultFolder(6)

    op = None
    for f in inbox.Folders:
        if str(f.Name).strip() == OUTLOOK_PARENT_SUBFOLDER:
            op = f
            break
    if op is None:
        raise RuntimeError(f"Outlook 폴더를 못 찾음: 받은편지함 > {OUTLOOK_PARENT_SUBFOLDER}")

    target = None
    for f in op.Folders:
        if str(f.Name).strip() == REPLY_SUBFOLDER:
            target = f
            break
    if target is None:
        raise RuntimeError(
            f"Outlook 폴더를 못 찾음: 받은편지함 > {OUTLOOK_PARENT_SUBFOLDER} > {REPLY_SUBFOLDER}"
        )

    items = target.Items
    items.Sort("[ReceivedTime]", True)

    results = []
    # 2026-08-06: 예전엔 조용히 건너뛰어서 용마 회신 메일 한 통이 통째로 빠져도
    # 흔적이 없었다. 동작은 그대로 두고 흔적만 남긴다(로그 폭주 방지로 앞의 3건만).
    _item_errors = 0
    for i in range(1, min(items.Count, 100) + 1):
        try:
            mail = items.Item(i)
        except Exception as e:
            _item_errors += 1
            if _item_errors <= 3:
                log(f"[경고] Outlook 메일 항목 {i}번을 읽지 못해 건너뜀"
                    f"({type(e).__name__}: {e})")
            elif _item_errors == 4:
                log("[경고] Outlook 항목 읽기 실패가 계속됨 - 이후 같은 로그는 생략합니다")
            continue
        if getattr(mail, "Class", None) != 43:
            continue
        if mail.EntryID in processed_entry_ids:
            continue
        subject = str(mail.Subject or "")
        # 2026-08-18: RMA 건은 요청 메일 제목이 "KRP-FA LAB RMA {TO#}"라
        # "Rebalance"가 없다 - RMA도 회신 대상으로 받되, 이 폴더에 들어오는
        # 무관한 RMA 메일까지 끌려오지 않게 "KRP"가 같이 있는 것만 인정한다.
        subject_upper = subject.upper()
        is_rebalance_reply = "Rebalance" in subject          # 기존 조건 그대로 유지
        is_rma_reply = "RMA" in subject_upper and "KRP" in subject_upper
        if not (is_rebalance_reply or is_rma_reply):
            continue

        # 2026-08-04 실측 정정: 요청 메일 제목이 "KRP-{국가} Rebalance {TO#}"라
        # 회신 제목("Re: kRP-AUP Rebalance 7868330")에도 TO#가 그대로 남아있음
        # -> pending_cases와 확실하게 매칭할 수 있음(예전엔 pending 1건일 때만
        # 추측 매칭했음). TO#가 아예 없는 회신(제목이 변형된 경우)도 있을 수
        # 있어 못 찾으면 None으로 둔다.
        # 2026-08-06: 같은 나라 TO를 합쳐 보낼 때는 제목이 "KRP-{국가} Rebalance
        # {TO1}+{TO2}" 형식이라 TO#가 여러 개 남을 수 있음 - findall로 전부
        # 뽑아 to_numbers 리스트로 둔다(순서 유지, 첫 번째를 to_number로 하위
        # 호환 유지).
        to_numbers = re.findall(r"\b(\d{7,8})\b", subject)
        to_number = to_numbers[0] if to_numbers else None

        body = str(mail.Body or "")

        # 2026-09-04: 4컬럼 표로 온 회신은 HTML에서 헤더 이름으로 읽는다
        # (parse_yongma_table_html 주석 참고). 표가 있으면 그게 정답이므로
        # 평문 추측 파싱을 아예 태우지 않는다 - 평문은 표에서 Qty를 품번으로
        # 잘못 읽는다. 표가 없는 자유서식 회신만 기존 경로로 간다.
        table_locs = parse_yongma_table_html(str(mail.HTMLBody or ""))
        if table_locs:
            log(f"[용마] 표 형식 회신 파싱: {len(table_locs)}행 "
                f"({', '.join(l['part_no'] for l in table_locs)})")
            results.append({
                "entry_id": mail.EntryID,
                "subject": subject,
                "body": body,
                "to_number": to_number,
                "to_numbers": to_numbers,
                "locations": table_locs,
            })
            continue

        locations = [
            m.groupdict() for m in YONGMA_LOCATION_PATTERN.finditer(body)
            if _looks_like_part_no(m.group("part_no"))
        ]
        # 2026-08-26: 줄바꿈 형식(미국 건 실측) 추가 - 파트 줄 다음에 로케이터
        # 줄이 오는 형태. 무게 줄("0.9kg")이 파트로 오판되는 걸 막고, 기존 패턴
        # 결과와 중복 제거 후 병합한다. 수량 표기가 없어 qty는 빈 값 - Oracle
        # Requested Quantity 교차검증은 자동으로 건너뛴다(기존 로직).
        for m in YONGMA_LOCATION_PATTERN_MULTILINE.finditer(body):
            part_no = m.group("part_no")
            if not _looks_like_part_no(part_no):
                continue
            if part_no.lower().endswith("kg") or part_no.lower().startswith("s/n"):
                continue
            if any(l["part_no"] == part_no and l["locator"] == m.group("locator")
                   for l in locations):
                continue
            locations.append({"part_no": part_no, "locator": m.group("locator"),
                              "qty": ""})
        # 2026-08-26: S/N 추출(Oracle 시리얼 기입용) - "S/N : 0726-1279, 0726-1282"
        # 형식(콤마/공백 구분, 수량만큼 나열). 각 S/N 그룹은 본문 위치 기준 가장
        # 가까운 앞쪽 파트에 배정한다. 주의: 캡처에서 \s를 빼면 줄바꿈을 넘어
        # 다음 박스의 치수/무게까지 삼키는 사고이므로(7876545 실측) 한 줄 안에서만
        # 캡처하고, 토큰은 5자 이상+숫자 포함으로 걸러낸다.
        part_positions = sorted(
            [(m.start(), m.group("part_no")) for m in
             YONGMA_LOCATION_PATTERN.finditer(body)] +
            [(m.start(), m.group("part_no")) for m in
             YONGMA_LOCATION_PATTERN_MULTILINE.finditer(body)])
        for sm in re.finditer(r"S/?N\s*:?\s*([0-9A-Za-z][0-9A-Za-z\-, ]+)", body):
            sns = [s.strip() for s in re.split(r"[,\s]+", sm.group(1)) if s.strip()]
            sns = [s for s in sns
                   if len(s) >= 5 and any(c.isdigit() for c in s)
                   and re.match(r"^[0-9A-Za-z\-]+$", s)]
            if not sns:
                continue
            prev = None
            for pos, pn in part_positions:
                if pos < sm.start():
                    prev = pn
            targets = [l for l in locations if l["part_no"] == prev] \
                if prev else (locations if len(locations) == 1 else [])
            for l in targets:
                l.setdefault("sn", [])
                for s in sns:
                    if s not in l["sn"]:
                        l["sn"].append(s)
        results.append({
            "entry_id": mail.EntryID,
            "subject": subject,
            "body": body,
            "to_number": to_number,
            "to_numbers": to_numbers,
            "locations": locations,
        })
    return results


# ==============================================================
# 5) Oracle Create Pick Wave - Transfer Order 전환 (미검증 토글)
# ==============================================================
TRANSFER_ORDER_RELEASE_RULE = "KRP_Pick_Release_SP"

# 2026-08-27: 1차 룰(SP)에서 backordered가 나오면 남은 라인의 재고는 다른
# 서브인벤토리(FG)에 있는 것이므로 FG 룰로 한 번 더 릴리즈한다. 소모품 쪽
# pick_release_watcher.PRIMARY_SECONDARY_RULES("소모품": SP -> FG)에서 이미
# 쓰던 방식과 같다. 이 폴백이 없어서 TO 7876705(2026-08-27 10:15)는
# released=0/backordered=1로 Pick Slip 자체가 안 생겼는데도 그대로 Confirm
# 단계로 넘어가 "그 TO의 행 자체가 없음"이라는 엉뚱한 에러로 3번 재시도하고
# 실패했다(로그에는 백오더가 원인이라는 단서가 없어 오진하기 쉬웠음).
TRANSFER_ORDER_BACKORDER_RULE = "KRP_Pick_Release_FG"

# 2026-09-16 사용자 확인(TO 7881992 실측 중 발견): RMA(본사 반송)는 Rebalance와
# 다른 전용 Release Rule을 쓴다 - **"KRP_Non_Value_Sub_Pick_Release"**. 실제로
# 이 TO를 KRP_Pick_Release_SP로 릴리즈했다가(잘못된 값) 백오더가 나서
# TRANSFER_ORDER_BACKORDER_RULE(FG)로 넘어가려는 순간 사용자가 "FG로 하면 진짜
# 큰일난다"며 Edge 창을 직접 닫아 막았다 - RMA는 FG 백오더 폴백도 적용 대상이
# 아니다(아래 _run_rebalance_pipeline에서 is_rma면 release_backorder_with_fg를
# 아예 호출하지 않고 사람 확인 알림만 보낸다). 화면 스크린샷(2026-09-16 14:47)
# 실측: 이 룰을 고르면 Options 탭이 Pick-from Subinventory=RMA_NV, Staging
# Subinventory=STG_NV, Release Sequence Rule=Default: Scheduled Ship Date,
# Pick Slip Grouping Rule=Order Number, Create shipments=체크,
# Shipment Creation Criteria=Across orders로 자동 채워진다(Release Rule 자체가
# 이 옵션 세트를 담고 있음 - Rebalance의 SP/FG 룰도 마찬가지로 옵션 탭을 코드가
# 건드리지 않고도 지금까지 정상 동작해왔다는 사실과 일치) - 그래서 Options 탭을
# 코드가 별도로 채우지는 않되, RMA 케이스는 이 옵션이 실제로 그대로 채워졌는지
# 최초 라이브 건에서 사람이 한 번 더 확인할 것.
RMA_TRANSFER_ORDER_RELEASE_RULE = "KRP_Non_Value_Sub_Pick_Release"

# 2026-08-14: Create Pick Wave 폼(Release Rule/Order Type/Order)을 채워보는 총 횟수.
# pick_release_watcher.py의 FORM_FILL_ATTEMPTS와 같은 목적 - Release Now 직전
# 검증에서 값이 어긋났을 때 화면을 새로 열지(40~60초) 않고 같은 화면에서 순서대로
# 한 번 더 채워 복구한다. 그래도 어긋나면 예외를 올려 호출부가 화면 재오픈으로
# 재시도하게 한다.
PICK_WAVE_FORM_FILL_ATTEMPTS = 2

# Order를 채우고 Customer가 뜰 때까지 기다리는 한도(초).
# 사용자 확인(2026-08-14): Transfer order 플로우도 Sales order와 동일하게
# Release Rule -> Order Type -> Order 셋이 다 들어가야 Customer가 뜬다.
# 즉 Customer가 비어 있다 = 셋 중 뭔가 안 먹었다는 신호다.
PICK_WAVE_CUSTOMER_TIMEOUT_SEC = 10

# Record Serial Numbers: From Serial Number에 값을 넣고 탭아웃한 뒤 옆 칸
# (To Serial Number)에 값이 뜰 때까지 기다리는 한도(2026-08-27). 이 확정을
# 안 기다리고 다음 행을 추가하면 방금 넣은 행이 초기화된다 - _enter_one_row 주석 참고.
SERIAL_COMMIT_TIMEOUT_SEC = 15
PICK_WAVE_CUSTOMER_POLL_SEC = 0.5

# Ship Confirm 클릭 후 확정 팝업("Shipment {번호} was confirmed")을 찾는 상한
# (2026-09-22 추가, TO 7886291 실측): 클릭 직후 고정 4초만 기다리고 한 번만
# 확인했더니 팝업이 그보다 늦게 떠서 "확정 안 됨"으로 오판(자동화는 정상적으로
# 중단했지만, 5분 뒤 재확인하니 이미 Closed로 실제론 확정돼 있었음). 상한을 두고
# 그 안에서만 짧은 간격으로 다시 찾아본다 - 9/16에 지적받은 "안 뜰 때까지 무한정
# 방황"과는 다르게 상한이 있고, 못 찾으면 기존 폴백(Shipment Status 확인 ->
# Exceptions 재확인 -> 사람에게 넘김) 그대로 탄다.
SHIP_CONFIRM_POPUP_WAIT_SEC = 20


# ==============================================================
# 오라클 화면 조작 공통 재시도 (2026-08-05 추가)
# ==============================================================
# 2026-08-05 사용자 요청으로 오라클을 쓰는 자동화 5종에 동일하게 넣은 헬퍼.
# 배경: pick_release_watcher 실측(2026-08-05 18:00 회차)에서 SSO 재로그인 직후
# "no such element: //img[@title='Tasks']"(화면 진입 실패)가 연달아 났는데,
# 자체 재시도 레이어가 있던 경로는 살아남고 없던 경로는 그대로 실패했다 -
# 같은 실행 안에서 짧게 쉬었다 다시 시도하게 한다.
# 2026-08-05 사용자 확인: Release Now / Confirm Pick Slips / Ship Confirm은
# 오라클에서 한 번밖에 안 된다(이미 처리된 건은 검색 자체가 안 됨) - 재시도가
# 중복 처리를 만들 수 없어서 이 단계들에도 재시도를 붙였다. 대신 "이미 눌렀는데
# 그 뒤에서 터진" 경우엔 재시도가 무의미하므로 progress dict로 그 지점을 기억해
# should_retry로 즉시 중단하고, Shipment 번호를 알림에 실어 사람이 이어받게 한다.
ORACLE_RETRY_ATTEMPTS = 3        # 최초 1회 + 재시도 2회
ORACLE_RETRY_WAIT_SEC = (5, 15)  # 재시도 전 대기(점증)


def run_with_oracle_retry(label: str, fn, *, attempts: int = ORACLE_RETRY_ATTEMPTS,
                          no_retry_exceptions: tuple = (), before_retry=None,
                          should_retry=None):
    """fn()이 일시적 오류로 실패하면 잠깐 쉬었다 다시 시도한다.
    no_retry_exceptions: 재시도해도 결론이 같은 '확정' 예외(그대로 올려보냄).
    before_retry: 재시도 직전 화면을 원위치시키는 콜백(실패해도 무시하고 진행).
    should_retry: 예외를 받아 "지금 재시도해도 되는가"를 판단하는 콜백(False면
    즉시 중단). 이미 커밋된 트랜잭션 뒤라 재시도가 의미 없을 때 쓴다.
    모든 시도가 실패하면 마지막 예외를 그대로 올려 호출부의 기존 처리를 탄다."""
    last_exc = None
    for attempt in range(attempts):
        try:
            return fn()
        except no_retry_exceptions:
            raise
        except Exception as e:
            last_exc = e
            # 2026-08-06: 브라우저 세션 자체가 끊긴 경우엔 같은 driver로 다시
            # 해봐야 결과가 100% 같다(is_session_dead_error 설명 참고).
            if is_session_dead_error(e):
                log(f"  [재시도] {label}: 브라우저 세션이 끊김({type(e).__name__}) "
                    f"- 같은 세션으로는 재시도해도 결과가 같아 여기서 중단")
                raise
            if should_retry is not None and not should_retry(e):
                log(f"  [재시도] {label}: 재시도 조건이 아니라 여기서 중단")
                raise
            if attempt == attempts - 1:
                break
            wait = ORACLE_RETRY_WAIT_SEC[min(attempt, len(ORACLE_RETRY_WAIT_SEC) - 1)]
            # 2026-08-06: 예외 타입만 찍으면(예: "NoSuchElementException") 어느
            # 요소가 없어서 실패했는지 로그만 봐선 알 수 없다 - 메시지 첫 줄까지
            # 남긴다(Selenium 예외는 스택트레이스가 수십 줄이라 첫 줄만).
            # 주의: 이 헬퍼는 오라클을 쓰는 자동화 파일마다 복붙되어 있어
            # (icbl/pick_release/ship_confirm/sco_cancel/rebalance) 한 곳만 고치면
            # 나머지는 그대로다 - 이번엔 icbl과 여기 두 곳에 적용함.
            detail = str(e).strip().splitlines()[0] if str(e).strip() else "(메시지 없음)"
            log(f"  [재시도] {label}: 오라클 처리 실패({type(e).__name__}: {detail}) - "
                f"{wait}초 후 {attempt + 2}/{attempts}번째 시도")
            time.sleep(wait)
            if before_retry is not None:
                try:
                    before_retry()
                except Exception as e2:
                    log(f"  [재시도] {label}: 재시도 전 화면 복구 실패(무시하고 진행): {e2}")
    raise last_exc


def _click_pickwave_blank_area(driver) -> bool:
    """Create Pick Wave 폼의 빈 화면을 실제 마우스로 한 번 클릭한다.

    Order(TO) 번호를 넣고 Tab만 치면 오라클이 조회를 늦게 거는 일이 잦은데, 빈 곳을
    한 번 누르면 Customer가 더 빨리 뜬다(2026-09-02 사용자 관찰). 이 화면 아래쪽
    시리얼 입력 단계에서 쓰는 _click_blank_area와 같은 방식이고, 대상 화면만 다르다.

    누르면 동작하는 자리(버튼/입력칸)면 클릭하지 않는다 - 폼이 틀어지면 안 된다.
    """
    from selenium.webdriver.common.action_chains import ActionChains
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        point = driver.execute_script(r"""
            const els = document.querySelectorAll("input, select");
            let bottom = 0;
            for (const e of els) {
              const r = e.getBoundingClientRect();
              if (r.width && r.height && r.bottom > bottom) bottom = r.bottom;
            }
            const y = Math.min(bottom + 80, window.innerHeight - 20);
            const x = Math.round(window.innerWidth * 0.5);
            const hit = document.elementFromPoint(x, y);
            return {x: x, y: Math.round(y),
                    tag: hit ? hit.tagName.toLowerCase() : null};
        """)
        if not point or not point.get("tag"):
            return False
        if point["tag"] in ("a", "button", "input", "select", "option",
                            "textarea", "label"):
            return False
        rect = body.rect
        dx = int(point["x"] - (rect["x"] + rect["width"] / 2))
        dy = int(point["y"] - (rect["y"] + rect["height"] / 2))
        ActionChains(driver).move_to_element_with_offset(body, dx, dy).click().perform()
        return True
    except Exception:
        return False


# 2026-09-16 사용자 지시("RMA는 내가 방금 참조한 스샷을 무조건 참조해서 해야해"):
# RMA의 Create Pick Wave Options 탭은 이 스크린샷(2026-09-16 14:47, TO 7881992,
# Release Rule=KRP_Non_Value_Sub_Pick_Release 선택 직후 화면) 값과 항상 대조
# 확인한다 - Release Rule 선택만으로 자동 채워지는 것으로 보이지만(Rebalance의
# SP/FG 룰도 옵션 탭을 코드가 건드리지 않고 지금까지 정상 동작해왔다는 사실과
# 일치), 어긋나면 엉뚱한 서브인벤토리/기준으로 릴리즈될 수 있어 매번 읽어서
# 확인하고 다르면 그 자리에서 고친다. 드롭다운/체크박스 종류는 아직 라이브로
# 실측하지 않았다 - 첫 실행에서 셀렉터가 안 맞으면 예외를 올려 사람이 보게
# 한다(값이 틀린 채로 조용히 Release Now를 누르는 것보다 안전).
RMA_PICKWAVE_OPTIONS_EXPECTED = {
    "Pick-from Subinventory": "RMA_NV",
    "Staging Subinventory": "STG_NV",
    "Release Sequence Rule": "Default: Scheduled Ship Date",
    "Pick Slip Grouping Rule": "Order Number",
    "Shipment Creation Criteria": "Across orders",
}
RMA_PICKWAVE_CHECKBOXES_EXPECTED = {
    "Autoconfirm picks": False,
    "Create shipments": True,
    "Append shipments": False,
}


def _open_pickwave_options_tab(driver) -> None:
    """Selection Criteria가 접혀 있으면(기본 'Show More' 상태) Options 탭
    자체가 화면에 없다 - 먼저 'Show More'를 눌러 펼쳐야 'Demand Selection'/
    'Options' 탭이 나타난다(2026-09-16 사용자 지적, 실측)."""
    from selenium.webdriver.common.by import By

    more_links = [el for el in driver.find_elements(
                      By.XPATH, "//*[normalize-space(text())='Show More']")
                  if el.is_displayed()]
    if more_links:
        more_links[0].click()
        time.sleep(1.5)

    tabs = [el for el in driver.find_elements(
                By.XPATH, "//*[normalize-space(text())='Options']")
            if el.is_displayed()]
    if not tabs:
        raise RuntimeError("Create Pick Wave 화면에서 'Options' 탭을 못 찾음"
                           "('Show More' 클릭 후에도 안 보임)")
    tabs[0].click()
    time.sleep(1.5)


def _set_choice_field(driver, label_text: str, expected: str) -> str | None:
    """select 또는 Oracle choice-list(텍스트+드롭다운 화살표) 필드를 읽어서
    기대값과 다르면 고친다. 다르면 (기존값, ) 형태가 아니라 그냥 기존값을
    돌려주고(불일치 로그용), 일치하면 None을 돌려준다."""
    from selenium.webdriver.support.ui import Select

    el = _field_by_label(driver, label_text)
    try:
        sel = Select(el)
        current = (sel.first_selected_option.text or "").strip()
        if current == expected:
            return None
        sel.select_by_visible_text(expected)
        return current
    except Exception:
        pass
    # select가 아니면 Release Rule 필드와 같은 choice-list(클릭 -> 지우기 -> 입력)
    current = (el.get_attribute("value") or "").strip()
    if current == expected:
        return None
    el.click()
    el.clear()
    el.send_keys(expected)
    time.sleep(1)
    driver.switch_to.active_element.send_keys("\t")
    time.sleep(1)
    return current


def verify_and_fix_rma_pickwave_options(driver, to_number: str) -> None:
    """RMA 전용: Create Pick Wave의 Options 탭을 2026-09-16 스크린샷과 대조하고
    다르면 고친다(RMA_PICKWAVE_OPTIONS_EXPECTED 주석 참고). RMA에서만 호출한다.

    2026-09-16 사용자 확인: "option에서 들어가있는 값들이 스샷이랑 같으면 바로
    릴리즈 하면 돼" - 이 확인은 참고용 안전장치일 뿐, 셀렉터를 못 찾는 필드가
    있어도(예: 체크박스 요소를 못 찾음) Release Now를 막으면 안 된다. 그래서
    필드 하나하나를 개별 try/except로 감싸 실패해도 나머지는 계속 확인하고,
    전체를 raise로 막지 않는다 - 못 읽은 필드는 경고만 남기고 사람이 스크린샷
    으로 눈으로 확인한 것을 신뢰한다."""
    _open_pickwave_options_tab(driver)
    time.sleep(1.5)  # Options 패널 자체가 렌더링될 시간(탭 클릭 직후는 아직 비어있을 수 있음)

    mismatches = []
    unverifiable = []

    for label, expected in RMA_PICKWAVE_OPTIONS_EXPECTED.items():
        try:
            prev = _set_choice_field(driver, label, expected)
            if prev is not None:
                mismatches.append((label, prev, expected))
        except Exception as e:
            unverifiable.append((label, exc_detail(e)))

    for label, expected in RMA_PICKWAVE_CHECKBOXES_EXPECTED.items():
        try:
            el = _field_by_label(driver, label)
            current = el.is_selected()
            if current != expected:
                mismatches.append((label, current, expected))
                driver.execute_script("arguments[0].click();", el)
        except Exception as e:
            unverifiable.append((label, exc_detail(e)))

    if unverifiable:
        try:
            diag = os.path.join(
                os.path.dirname(__file__),
                f"_diag_rma_options_{to_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            driver.save_screenshot(diag)
            log(f"  [진단] RMA Options 탭 일부 필드 확인 실패 스크린샷: {os.path.basename(diag)}")
        except Exception:
            pass
        log(f"[Pipeline] TO {to_number} RMA Options 탭 {len(unverifiable)}개 필드는 "
            f"자동으로 못 읽음(사람이 스크린샷으로 확인한 값을 신뢰하고 계속 진행): "
            f"{unverifiable}")

    if mismatches:
        log(f"[Pipeline] TO {to_number} RMA Options 탭 스크린샷과 불일치 "
            f"{len(mismatches)}건 보정함: {mismatches}")
    elif not unverifiable:
        log(f"[Pipeline] TO {to_number} RMA Options 탭이 스크린샷과 전부 일치 확인됨")


def create_pick_wave_transfer_order(driver, to_number: str,
                                    release_rule: str = TRANSFER_ORDER_RELEASE_RULE,
                                    is_rma: bool = False) -> dict:
    """pick_release_watcher.py의 navigate_to_create_pick_wave()/_field_by_label()
    패턴을 재사용. 평소(Sales Order) 화면과 동일하되 Order Type을 Transfer
    Order로 바꾸는 부분만 추가.

    **2026-08-05 실측 검증(TO 7866440, 실제 라이브 케이스)**:
    - "Order Type" select 필드의 실제 옵션 목록: `['', 'Return to customer',
      'Return to supplier', 'Unreferenced supplier return', 'Return transfer
      order', 'Sales order', 'Transfer order']` - 처음엔 "Transfer Order"
      (대문자 O)로 잘못 짜서 실패했음, 실제 값은 소문자 "Transfer order".
    - Release Rule은 사용자 확인: **"KRP_Pick_Release_SP"**(소모품 Sales
      Order 때 쓰는 것과 같은 이름) - Order Type=Transfer order로도 그대로 씀.
    - **순서 중요**: Release Rule을 먼저 채우면(기존 Sales Order 플로우처럼)
      탭아웃 시 Order Type이 도로 빈 값/기본값으로 리셋되는 게 실측 확인됨
      (Order 필드가 Release Rule 확정 후 리셋되는 기존 동작과 유사). 그래서
      **Order Type을 Release Rule보다 나중에, Order 채우기 바로 직전에** 설정
      해야 안 풀린다.
    """
    from selenium.webdriver.support.ui import Select

    navigate_to_create_pick_wave(driver)

    def _fill_form():
        rule_el = _field_by_label(driver, "Release Rule")
        rule_el.click()
        rule_el.clear()
        rule_el.send_keys(release_rule)
        time.sleep(1)
        driver.switch_to.active_element.send_keys("\t")
        time.sleep(2.5)

        order_type_el = _field_by_label(driver, "Order Type")
        Select(order_type_el).select_by_visible_text("Transfer order")
        time.sleep(2)

        order_el = _field_by_label(driver, "Order")
        order_el.click()
        order_el.clear()
        order_el.send_keys(to_number)
        time.sleep(1)
        driver.switch_to.active_element.send_keys("\t")
        # 탭아웃만으로는 조회가 늦게 걸릴 때가 있어 빈 화면을 한 번 눌러준다
        _click_pickwave_blank_area(driver)
        time.sleep(3)

    def _read_form():
        return (
            (_field_by_label(driver, "Release Rule").get_attribute("value") or "").strip(),
            (Select(_field_by_label(driver, "Order Type"))
             .first_selected_option.text or "").strip(),
            (_field_by_label(driver, "Order").get_attribute("value") or "").strip(),
        )

    def _wait_customer():
        """Customer 칸에 값이 들어올 때까지 폴링한다.
        반환: (값, 판정가능여부). **"값이 비었다"와 "칸 자체를 못 찾았다"를 반드시
        구분한다** - Transfer order 화면의 라벨이 Sales order와 다를 가능성이 아직
        실측되지 않았는데, 못 찾은 걸 "비었다"로 처리하면 이 가드가 매번 실패해서
        멀쩡한 자동화를 통째로 막아버린다(그건 막으려던 사고보다 더 나쁘다).
        못 찾으면 판정가능=False로 돌려주고 호출부가 경고만 남기고 진행한다."""
        deadline = time.time() + PICK_WAVE_CUSTOMER_TIMEOUT_SEC
        readable = False
        while True:
            try:
                val = (_field_by_label(driver, "Customer").get_attribute("value") or "")
                readable = True
            except Exception:
                # PPR 도중 stale이거나, 라벨이 아예 다른 경우. 한 번도 못 읽은 채
                # 시간이 다 가면 readable=False로 남아 "판정불가"가 된다.
                val = ""
            if val.strip() or time.time() >= deadline:
                return val.strip(), readable
            time.sleep(PICK_WAVE_CUSTOMER_POLL_SEC)

    # 2026-08-14: 채우고 나서 **Release Now를 누르기 전에** 세 칸을 다시 읽어 확인한다.
    # 이 가드가 없으면 오라클이 화면을 다시 그리며(PPR) Release Rule을 날려버린
    # 경우에도 그대로 Release Now가 눌려 released_lines=0으로 조용히 끝난다
    # (= 출고가 안 됐는데 로그상 실패 흔적이 없음).
    #
    # 이건 추측이 아니라 pick_release_watcher.py에서 실측된 현상이다. 특히
    # 00597607(2026-08-11 14:02)은 **재입력이 한 번도 없이** 세 칸을 순서대로 한
    # 번에 채웠는데도 Order 탭아웃 뒤 Release Rule이 ''로 비어 있었다 - 즉 여기처럼
    # 단일 패스로 곱게 채우는 것만으로는 막을 수 없다. 같은 파일 00597837도
    # 빈 Release Rule 때문에 두 회차를 통째로 날렸다.
    #
    # 어긋나면 화면을 새로 열 것 없이 같은 화면에서 한 번 더 채워보고(순서를 지켜
    # 통째로 다시 채우므로 "룰만 다시 넣어 Order가 리셋되는" 위험이 없다), 그래도
    # 안 되면 예외를 올린다 - 호출부(run_with_oracle_retry)가 화면을 새로 열어
    # 재시도한다. Release Now 이전이라 되돌릴 수 없는 지점이 아니다.
    # 2026-08-19 실측(TO 7872959, 홍콩/ILH): Order를 채우고 탭아웃한 뒤 Order Type이
    # 기본값 **'Sales order'로 되돌아가는** 케이스가 확인됐다
    # (실제 ('KRP_Pick_Release_SP', 'Sales order', '7872959')).
    # 코드가 Sales order를 고른 적은 없다 - 위 _fill_form()은 언제나 'Transfer order'를
    # 선택하며, Rebalance/RMA는 Order Type이 **항상** Transfer order다(아래 expected).
    # 오라클이 Order 확정 PPR에서 이 칸을 기본값으로 되돌리는 것이다.
    #
    # 문제는 기존 대응이 "폼 전체 재입력"뿐이었다는 점이다. 전체 재입력은 Release
    # Rule/Order를 도로 비워버려서(같은 회차 1~2차 시도: 실제 ('', 'Transfer order', ''))
    # 오히려 상태가 더 나빠졌고 3번 다 실패했다. 그래서 **나머지 두 칸이 맞는 상태에서
    # Order Type만 어긋난 경우**엔 그 칸만 다시 골라 고친다(Order를 다시 안 건드리므로
    # 리셋 연쇄가 생기지 않는다). 세 칸이 다 어긋났으면 기존대로 전체를 다시 채운다.
    ORDER_TYPE_REPAIR_ATTEMPTS = 2

    def _repair_order_type_only() -> bool:
        try:
            Select(_field_by_label(driver, "Order Type")).select_by_visible_text(
                "Transfer order")
        except Exception as e:
            log(f"  TO {to_number}: Order Type 재선택 실패: {exc_detail(e)}")
            return False
        time.sleep(2)
        return True

    expected = (release_rule, "Transfer order", to_number)
    customer_v = ""
    for attempt in range(1, PICK_WAVE_FORM_FILL_ATTEMPTS + 1):
        _fill_form()
        actual = _read_form()

        # Order Type만 되돌아간 경우의 국소 교정(위 설명 참고).
        for _ in range(ORDER_TYPE_REPAIR_ATTEMPTS):
            if actual == expected:
                break
            if (actual[0], actual[2]) != (expected[0], expected[2]):
                break   # 다른 칸도 어긋났다면 전체 재입력이 맞다
            log(f"  TO {to_number}: Order Type이 '{actual[1]}'로 되돌아감 "
                f"- Order Type만 다시 선택해 교정 시도")
            if not _repair_order_type_only():
                break
            actual = _read_form()

        # Customer는 세 칸이 다 들어가야 뜨므로 교정을 끝낸 뒤에 확인한다.
        customer_v, customer_readable = _wait_customer()

        # 사용자 확인(2026-08-14): Transfer order도 Sales order와 판정이 똑같다 -
        # 3칸이 정확히 들어가면 Customer가 뜬다. 그래서 "3칸 일치 + Customer 있음"을
        # 통과 조건으로 본다. Customer가 비어 있으면 3칸 중 뭔가 안 먹은 것이므로
        # 그대로 Release Now를 누르면 0건으로 조용히 끝난다.
        # 단, Customer 칸을 아예 못 읽은 경우(판정불가)는 통과로 본다 - _wait_customer
        # 주석 참고. 이때는 3칸 검증만으로 판정하며, 경고를 남겨 라벨을 확인할 수 있게 한다.
        if not customer_readable:
            log(f"  [주의] TO {to_number}: Customer 칸을 못 읽음(라벨이 다를 수 있음) - "
                f"Customer 확인은 건너뛰고 3칸 검증으로만 판정함")
        if actual == expected and (customer_v or not customer_readable):
            break

        reason = []
        if actual != expected:
            reason.append(f"입력값 어긋남(실제 {actual}, 기대 {expected})")
        if customer_readable and not customer_v:
            reason.append("Customer 미표시")
        detail = " / ".join(reason)

        if attempt < PICK_WAVE_FORM_FILL_ATTEMPTS:
            log(f"  TO {to_number}: Release Now 직전 {detail} "
                f"(폼 입력 {attempt}/{PICK_WAVE_FORM_FILL_ATTEMPTS}회차) - "
                f"화면은 그대로 두고 폼 전체를 다시 채워 재시도")
            continue
        raise RuntimeError(
            f"TO {to_number}: Release Now 직전 {detail} "
            f"(폼을 {PICK_WAVE_FORM_FILL_ATTEMPTS}회 채웠는데도 안 됨 - "
            f"빈 칸인 채로 Release Now를 눌러 0건으로 끝나는 걸 막기 위해 중단)"
        )

    # 2026-08-27: 여기서 상수(SP)를 찍고 있어서 FG 폴백으로 호출해도 로그엔 SP로
    # 남았다 - 실제로 채운 값(release_rule 파라미터)을 찍는다.
    log(f"[Oracle] Create Pick Wave - Transfer order {to_number}, "
        f"Release Rule={release_rule} 입력 완료"
        f"(3칸 검증 통과, customer={customer_v})")

    if is_rma:
        verify_and_fix_rma_pickwave_options(driver, to_number)

    return {"to_number": to_number, "release_rule": release_rule}


def release_pick_wave_now(driver, progress: dict | None = None,
                          rule: str = "") -> dict:
    """progress: 넘기면 "Release Now를 실제로 눌렀는지"를 기록한다(재시도 판단용,
    2026-08-05 추가). 눌렀는데 그 뒤 결과 다이얼로그 읽기에서 터진 경우, 재시도가
    같은 TO를 다시 릴리즈하는 게 아니라(오라클이 한 번만 허용) 뽑을 라인이 없어
    실패하므로 호출부가 이 값을 보고 사람 확인으로 넘길 수 있다.

    Create Pick Wave 화면에서 "Release Now" 클릭 -> 확인 다이얼로그에서
    released/backordered 라인 수를 읽는다. pick_release_watcher.py의
    _create_and_release_pick_wave_once()와 동일한 패턴(문구/폴링 방식) 재사용.
    2026-08-05 TO 7866440에서 사용자가 직접 클릭해 결과만 확인함(released=1,
    backordered=0) - 이 함수 자체(자동 클릭)는 아직 실측 검증 전."""
    from selenium.webdriver.common.by import By

    release_btns = [
        el for el in driver.find_elements(By.XPATH, "//*[normalize-space(text())='Release Now']")
        if el.is_displayed()
    ]
    if not release_btns:
        raise RuntimeError("Release Now 버튼을 못 찾음")
    release_btns[0].click()
    if progress is not None:
        progress["released_clicked"] = True  # 여기부터는 되돌릴 수 없는 지점
    time.sleep(4)

    for _ in range(15):
        if "released to warehouse" in driver.page_source:
            break
        time.sleep(1)
    m = re.search(r"Number of shipment lines released to warehouse:\s*(\d+)", driver.page_source)
    if not m:
        raise RuntimeError("Release 결과 확인 실패(확인 다이얼로그를 못 찾음)")
    released = int(m.group(1))
    m_bo = re.search(r"Number of shipment lines backordered:\s*(\d+)", driver.page_source)
    backordered = int(m_bo.group(1)) if m_bo else None

    ok_btns = [el for el in driver.find_elements(By.TAG_NAME, "button")
               if el.is_displayed() and el.text.strip() == "OK"]
    if ok_btns:
        ok_btns[-1].click()
    time.sleep(1)

    log(f"[Oracle] Release Now 완료{f'({rule})' if rule else ''}: "
        f"released={released}, backordered={backordered}")
    return {"released_lines": released, "backordered_lines": backordered}


def release_backorder_with_fg(driver, to_number: str) -> dict:
    """1차 룰(SP) Release Now에서 backordered가 나왔을 때 FG 룰로 Create Pick
    Wave + Release Now를 한 번 더 돌린다(2026-08-27 추가).

    판단 규칙은 소모품 쪽 pick_release_watcher._run_backorder_secondary와 동일:
    - Create Pick Wave 3칸 검증이 "Customer 미표시"로 막히면 = FG 쪽에도 뽑을
      라인이 없다는 뜻이므로 released=0으로 **정상 종료**한다(예외로 올리지 않음).
      Customer는 3칸이 정확히 들어가야 뜨는데, 뽑을 라인이 없으면 안 뜬다.
    - 그 밖의 기술적 오류(네비게이션 실패/세션 끊김 등)는 1회 재시도하고, 그래도
      안 되면 error 메시지를 담아 돌려준다 - 1차 릴리즈 결과는 이미 확정된
      상태이므로 예외로 통째로 날리지 않고 호출부가 판단하게 한다.

    반환: {"released_lines": int, "backordered_lines": int|None, "error": str|None}
    """
    for attempt in range(2):
        try:
            create_pick_wave_transfer_order(
                driver, to_number, release_rule=TRANSFER_ORDER_BACKORDER_RULE)
            r = release_pick_wave_now(driver, rule=TRANSFER_ORDER_BACKORDER_RULE)
            return {"released_lines": r.get("released_lines") or 0,
                    "backordered_lines": r.get("backordered_lines"),
                    "error": None}
        except Exception as e:
            msg = exc_detail(e)
            if "Customer 미표시" in msg:
                log(f"  TO {to_number} {TRANSFER_ORDER_BACKORDER_RULE}(백오더 대응): "
                    f"Customer 미표시 -> FG로도 뽑을 라인 없음(정상 확정)")
                return {"released_lines": 0, "backordered_lines": None, "error": None}
            if attempt == 0:
                log(f"  TO {to_number} {TRANSFER_ORDER_BACKORDER_RULE}(백오더 대응) "
                    f"기술적 오류: {msg} - 1회 재시도")
                time.sleep(5)
                continue
            log(f"  TO {to_number} {TRANSFER_ORDER_BACKORDER_RULE}(백오더 대응) "
                f"재시도도 실패: {msg}")
            return {"released_lines": 0, "backordered_lines": None, "error": msg}


# ==============================================================
# 6~9) Confirm Pick Slips ~ Ship Confirm
# ==============================================================
def _record_serial_numbers(driver, to_number: str, tasks: list[dict]) -> None:
    """Confirm Pick Slip 화면에서 시리얼 번호를 기입한다(2026-08-26 추가).

    흐름(사용자 실측 스크린샷): 라인 선택 -> Actions -> Record Serial Numbers ->
    'Enter Single Serial Number'로 시리얼 기입.

    **2026-08-26 실측(7877405)**: 시리얼 1개 기입 후 OK를 누르면 Record Serial
    Numbers 화면이 **닫히고** Pick Slip 화면으로 돌아온다(저장됨). 그래서 남은
    시리얼은 **화면을 다시 열어서** 이어서 기입한다. 부족분만 기입(재실행
    멱등), 전부 비어 있으면 신규 기입, 용마에 없는 시리얼이 기록돼 있으면 전체
    삭제(✗) 후 재기입한다.

    **로케이터-시리얼 세트(사용자 확인)**: 로케이터마다 담긴 제품이 다르므로
    Source Locator는 라인 루프에서 용마 값으로 무조건 덮어써진다. 화면의
    locator가 용마 값과 다르면(수동 픽) 그 로케이터의 시리얼은 알 수 없으므로
    기입하지 않고 검토 대기로 넘긴다."""
    from selenium.webdriver.common.by import By

    def _diag(tag):
        try:
            p = os.path.join(os.path.dirname(__file__),
                             f"_diag_serial_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            driver.save_screenshot(p)
            log(f"  [진단] {tag}: {os.path.basename(p)}")
        except Exception:
            pass

    def _body_text() -> str:
        try:
            return driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            return driver.page_source or ""

    def _on_serial_screen() -> bool:
        return "Record Serial Numbers" in _body_text()

    def _serial_screen_matches(line: int, part_no: str) -> tuple:
        """지금 열려 있는 Record Serial Numbers 화면이 이 라인/품목의 것인지.

        화면 상단 Transaction Details에 Pick Slip / Line / Item이 찍혀 있다
        (실측 스크린샷: Line 1, Item 7123-00-0593). 품목이 여러 개인 Pick Slip에서
        앞 라인 화면이 안 닫힌 채 남아 있으면 엉뚱한 품목에 시리얼이 들어가므로
        기입 전에 반드시 확인한다(2026-08-27 사용자 지적).
        반환: (일치여부, 사유)"""
        body = _body_text()
        if "Record Serial Numbers" not in body:
            return False, "시리얼 화면이 아님"
        if part_no not in body:
            return False, f"화면에 품번 {part_no}가 없음"
        m = re.search(r"\bLine\s+(\d+)", body)
        if m and m.group(1) != str(line):
            return False, f"화면 Line={m.group(1)}, 기대 Line={line}"
        return True, ""

    def _serial_value_inputs() -> list:
        """Serial Numbers 표의 'From Serial Number' 칸 **전부**(빈 행 포함).

        2026-08-27 실측으로 확인한 id 패턴: ...:table3:2:seFmSNVal::content.
        값 패턴(정규식)으로 찾던 예전 방식은 빈 행을 못 세서 "행이 추가됐는지"를
        판정할 수 없었다 - 그래서 같은 행에 두 번 덮어쓰는 걸 못 잡았다."""
        out = []
        for e in driver.find_elements(By.CSS_SELECTOR, "input[id*='seFmSNVal']"):
            try:
                if e.is_displayed():
                    out.append(e)
            except Exception:
                continue
        return out

    def _serial_row_inputs() -> list:
        """값이 들어있는 'From Serial Number' 칸들."""
        out = []
        for e in _serial_value_inputs():
            try:
                if (e.get_attribute("value") or "").strip():
                    out.append(e)
            except Exception:
                continue
        return out

    def _recorded_serials() -> list:
        out = []
        for e in _serial_row_inputs():
            try:
                out.append((e.get_attribute("value") or "").strip())
            except Exception:
                continue
        return out

    def _numbers_entered():
        """화면의 'Numbers Entered' 값 - 행이 실제로 몇 개 남았는지의 정답지.
        입력칸 스캔만으로는 화면이 잠깐 다시 그려지는 순간 0으로 잘못 읽힌다
        (2026-08-27 실측: 그 오독 때문에 안 지워진 걸 '삭제 완료'로 단정했다)."""
        m = re.search(r"Numbers Entered\s*[\r\n\s]*(\d+)", _body_text())
        return int(m.group(1)) if m else None

    def _dismiss_error_dialog():
        txt = _body_text()
        if "The entire quantity" in txt:
            for t in ("OK", "확인"):
                obs = [e for e in driver.find_elements(
                    By.XPATH, f"//button[normalize-space(.)='{t}']") if e.is_displayed()]
                if obs:
                    driver.execute_script("arguments[0].click();", obs[-1])
                    time.sleep(1.5)
                    return

    def _open_serial_screen(line: int) -> None:
        qty_inputs = [e for e in driver.find_elements(
            By.CSS_SELECTOR, "input[id*='pickedqtyid']") if e.is_displayed()]
        if len(qty_inputs) >= line:
            try:
                qty_inputs[line - 1].click()
                time.sleep(0.5)
            except Exception:
                pass
        act = None
        for e in driver.find_elements(
                By.XPATH, "//*[contains(normalize-space(.),'Actions')]"):
            try:
                if e.is_displayed() and len((e.text or "").strip()) <= 10:
                    act = e
                    break
            except Exception:
                continue
        if act is None:
            _diag("actions_btn")
            raise RuntimeError(f"라인 {line}: Actions 버튼을 못 찾음")
        try:
            act.click()
        except Exception:
            driver.execute_script("arguments[0].click();", act)
        time.sleep(1.5)
        menu = [e for e in driver.find_elements(
            By.XPATH, "//*[normalize-space(.)='Record Serial Numbers']")
            if e.is_displayed()]
        if not menu:
            _diag("serial_menu")
            raise RuntimeError(f"라인 {line}: 'Record Serial Numbers' 메뉴를 못 찾음")
        driver.execute_script("arguments[0].click();", menu[-1])
        deadline = time.time() + 20
        while time.time() < deadline:
            if _on_serial_screen():
                break
            time.sleep(1)
        time.sleep(2)

    def _click_enter_single() -> bool:
        """'Enter Single Serial Number'를 눌러 **행을 하나 더** 추가한다.

        2026-08-27 실측(TO 7876705 Pick Slip 9119299): JS 클릭
        (execute_script)으로 누르면 두 번째부터 **행이 안 늘고** 기존 행
        (id가 계속 table3:2:...)에 그대로 덮어써졌다 - 시리얼 2개를 넣었는데
        화면엔 마지막 것 한 줄만 남았다. 이 파일의 Confirm 드롭다운에도 같은
        기록이 있다("JS 클릭은 이 메뉴를 안 엶 - 실측 확인"). 그래서 실제 마우스
        클릭(ActionChains)으로 누르고, **행 수가 실제로 늘었는지** 확인한다.
        사용자 지시(2026-08-27): "하나 입력하면 enter single serial number를
        하나 더 누르고 해야지", "qty만큼 나와야해".
        """
        from selenium.webdriver.common.action_chains import ActionChains

        before = len(_serial_value_inputs())
        for attempt in range(3):
            btn = [e for e in driver.find_elements(
                By.XPATH, "//button[normalize-space(.)='Enter Single Serial Number']")
                if e.is_displayed()]
            if not btn:
                _diag("single_serial_btn")
                raise RuntimeError("'Enter Single Serial Number' 버튼을 못 찾음")
            try:
                ActionChains(driver).move_to_element(btn[0]).click().perform()
            except Exception:
                driver.execute_script("arguments[0].click();", btn[0])
            time.sleep(2)
            # 기존 행이 안 지워진 채 누르면 오라클이 이 오류로 막는다.
            # 예전엔 그냥 "입력칸을 못 찾음"으로 떠서 원인이 안 보였다.
            if "The entire quantity is already entered" in _body_text():
                _dismiss_error_dialog()
                _diag("serial_qty_full")
                raise RuntimeError(
                    f"'The entire quantity is already entered'(INV-2416271) - 기존 "
                    f"시리얼 {_recorded_serials()}이 남아 있어 행을 더 못 만듦")
            deadline = time.time() + 6
            while time.time() < deadline:
                if len(_serial_value_inputs()) > before:
                    return True
                time.sleep(0.5)
            log(f"    [주의] 'Enter Single Serial Number' 클릭 후에도 행이 "
                f"{before}개 그대로 - 재시도 {attempt + 1}/3")
        return False

    def _click_blank_area() -> None:
        """입력칸 밖의 **빈 화면**을 실제 마우스로 한 번 클릭해 포커스를 뺀다.

        2026-08-27 사용자 실측: Tab은 값을 지우고, 가만히 기다려도 확정이 안 된다.
        빈 곳을 한 번 클릭해야 값이 확정되면서 To Serial Number에 같은 값이 뜬다.
        표 아래 여백을 노린다 - 행이나 버튼 위를 누르면 선택이 바뀌거나 엉뚱한
        동작이 실행되므로, 표의 아래쪽 바깥 좌표를 계산해서 그 지점을 클릭한다."""
        from selenium.webdriver.common.action_chains import ActionChains

        body = driver.find_element(By.TAG_NAME, "body")
        # 시리얼 표의 맨 아래보다 더 아래(=아무것도 없는 흰 여백) 지점
        point = driver.execute_script(r"""
            const rows = document.querySelectorAll("input[id*='seFmSNVal']");
            let bottom = 0;
            for (const e of rows) {
              const r = e.getBoundingClientRect();
              if (r.bottom > bottom) bottom = r.bottom;
            }
            const y = Math.min(bottom + 120, window.innerHeight - 20);
            const x = Math.round(window.innerWidth * 0.5);
            const hit = document.elementFromPoint(x, y);
            return {x: x, y: Math.round(y),
                    tag: hit ? hit.tagName : null,
                    id: hit ? (hit.id || '') : ''};
        """)
        if not point:
            log("    [주의] 빈 화면 좌표 계산 실패 - 클릭 생략")
            return
        # body 중심 기준 오프셋으로 환산(Selenium 4의 move_to_element_with_offset은
        # 요소 중심 기준이다)
        rect = body.rect
        dx = int(point["x"] - (rect["x"] + rect["width"] / 2))
        dy = int(point["y"] - (rect["y"] + rect["height"] / 2))
        try:
            ActionChains(driver).move_to_element_with_offset(body, dx, dy).click().perform()
            log(f"    빈 화면 클릭: ({point['x']},{point['y']}) "
                f"hit={point['tag']}#{point['id'][-25:]}")
        except Exception as e:
            log(f"    [주의] 빈 화면 클릭 실패: {exc_detail(e)}")
        time.sleep(1)

    def _enter_one_row(sn: str) -> None:
        """행을 하나 추가하고 그 새 행에 시리얼을 넣은 뒤, **옆 칸(To Serial
        Number)에 값이 뜨는 것까지 확인**하고 돌아온다. OK는 모든 행을 넣은 뒤
        한 번만 누른다(2026-08-26 사용자 지시: "한번에 그냥 2개 하고 ok").

        To Serial Number 확인이 왜 필수인가(2026-08-27 사용자 지시 + 실측):
        값이 확정되기 전에 'Enter Single Serial Number'를 누르면 그 행이 **통째로
        초기화된다** - 실측 스크린샷에서 From Serial Number가 빈 칸 + 빨간 테두리
        + "Error: A value is required"였고 Numbers Entered=1/Remaining=1이었다.
        그래서 시리얼 2개를 넣어도 행이 하나만 남고 앞의 값이 사라졌다.
        확정 신호는 옆 칸(To Serial Number)에 같은 값이 텍스트로 뜨는 것이다
        (입력칸 value는 텍스트가 아니라 화면 텍스트에 안 잡히므로, 화면 텍스트에
        시리얼이 보이면 = To 칸이 채워졌다는 뜻)."""
        if not _click_enter_single():
            _diag("serial_row_not_added")
            raise RuntimeError(
                f"'Enter Single Serial Number'를 눌러도 행이 안 늘어남({sn}) - "
                f"현재 행={_recorded_serials()}, Numbers Entered={_numbers_entered()}")
        # 행이 추가되는 PPR이 끝나기를 기다린 뒤에 요소를 새로 잡는다. 바로 잡아
        # 타이핑하면 다시 그려지면서 **교체된 옛 요소에 입력이 들어가** 값이
        # 사라진다(2026-08-27 실측: From Serial Number가 빈 칸, To도 빈 칸,
        # Numbers Entered=1/Remaining=1). 그래서 매번 새로 잡고, 넣은 값이 실제로
        # 칸에 남았는지 확인한 뒤에만 탭아웃한다.
        box = None
        for attempt in range(3):
            time.sleep(1.5)
            empties = [e for e in _serial_value_inputs()
                       if not (e.get_attribute("value") or "").strip()]
            if not empties:
                _diag("serial_input")
                raise RuntimeError(f"시리얼 입력칸을 못 찾음({sn})")
            box = empties[-1]
            try:
                box.click()
                # 이미 빈 칸만 고르므로 clear()는 필요 없다. ADF LOV에서 clear()는
                # 빈 값 change 이벤트를 발생시켜 뒤늦은 PPR이 칸을 되돌릴 수 있어
                # 오히려 위험하다(2026-08-27 제거).
                box.send_keys(sn)
            except Exception as e:
                log(f"    [주의] 시리얼 입력 중 오류: {exc_detail(e)} - 재입력 "
                    f"{attempt + 1}/3")
                continue
            time.sleep(0.7)
            try:
                typed = (box.get_attribute("value") or "").strip()
            except Exception:
                typed = "(읽기 실패)"
            if typed == sn:
                log(f"    행 입력: {sn} (input id={box.get_attribute('id')!r})")
                break
            log(f"    [주의] 입력이 칸에 안 남음(현재={typed!r}) - 재입력 "
                f"{attempt + 1}/3")
        else:
            _diag("serial_value_lost")
            raise RuntimeError(
                f"시리얼 {sn}을 칸에 넣어도 값이 안 남음(화면이 계속 다시 그려지는 중) - "
                f"Numbers Entered={_numbers_entered()}")

        # 값 확정(2026-08-27 사용자 실측 관찰):
        #  - Tab을 보내면 From/To가 둘 다 비워진다(스크린샷 3회 재현) - **금지**
        #  - 가만히 기다리기만 해서도 확정되지 않는다
        #  - "기입하고 대기보다 그냥 흰 화면 한번 클릭해야하네" -> 빈 곳을 한 번
        #    클릭해서 포커스를 빼면 확정되고 옆 칸(To Serial Number)에 값이 뜬다
        _click_blank_area()

        deadline = time.time() + SERIAL_COMMIT_TIMEOUT_SEC
        while time.time() < deadline:
            if sn in _body_text():
                log(f"    To Serial Number 확인됨: {sn}")
                return
            time.sleep(0.5)
        _diag("to_serial_missing")
        raise RuntimeError(
            f"To Serial Number가 {SERIAL_COMMIT_TIMEOUT_SEC}초 안에 안 뜸({sn}) - "
            f"값이 확정되지 않아 중단(이 상태로 다음 행을 추가하면 이 행이 초기화됨). "
            f"화면 행={_recorded_serials()}, Numbers Entered={_numbers_entered()}")

    # ✗(Delete) 아이콘을 **화면 좌표**로 찾는다(2026-08-27 재작성).
    # 기존엔 document의 <button> 목록에서 'Enter Single Serial Number' 앞 3개를
    # 집었는데, 실측(TO 7876705 Pick Slip 9119299)에서 ✗가 <button>이 아니라
    # 후보에 아예 안 잡혔다(그래서 한 행도 못 지웠다). 그 전 회차엔 엉뚱한 전역
    # 툴바 버튼을 눌러 화면이 통째로 바뀌었고, 입력칸이 사라진 걸 '삭제됨'으로
    # 오독했다. 화면상 ✗는 'Enter Single Serial Number' **바로 왼쪽, 같은 줄**의
    # 텍스트 없는 아이콘이다(스크린샷: View ▼ | ✗ | Enter Single Serial Number).
    # 태그를 가리지 않고 그 위치 조건으로만 고른다.
    _TOOLBAR_JS = r"""
    const anchorText = 'Enter Single Serial Number';
    let anchor = null;
    for (const e of document.querySelectorAll('button, a, div, span')) {
      if (!e.offsetParent) continue;
      if ((e.textContent || '').trim() === anchorText) { anchor = e; break; }
    }
    if (!anchor) return null;
    const ar = anchor.getBoundingClientRect();
    const mid = (ar.top + ar.bottom) / 2;
    const out = [];
    for (const e of document.querySelectorAll(
            'a, button, img, div[role="button"], span[role="button"]')) {
      if (!e.offsetParent) continue;
      const r = e.getBoundingClientRect();
      if (!r.width || !r.height) continue;
      if (r.right > ar.left) continue;                            // 앵커 왼쪽만
      if (Math.abs((r.top + r.bottom) / 2 - mid) > 20) continue;   // 같은 줄만
      if ((e.textContent || '').trim()) continue;                  // 'View ▼' 제외
      out.push([e, ar.left - r.right]);
    }
    out.sort((a, b) => a[1] - b[1]);                               // 앵커에 가까운 순
    return out.map(x => x[0]);
    """

    def _delete_icon_buttons() -> list:
        try:
            return driver.execute_script(_TOOLBAR_JS) or []
        except Exception as e:
            log(f"    [주의] X 후보 탐색 실패: {exc_detail(e)}")
            return []

    def _dump_serial_toolbar() -> str:
        """실패했을 때 '무엇을 후보로 봤는지'를 로그에 남긴다 - 재실행 없이
        셀렉터 원인을 확정하기 위함."""
        js = _TOOLBAR_JS.replace(
            "return out.map(x => x[0]);",
            "return out.map(x => x[0].tagName + '#' + (x[0].id || '') + '[title=' + "
            "(x[0].getAttribute('title') || '') + ',cls=' + "
            "((x[0].className || '').toString().slice(0, 30)) + ']');")
        try:
            return str(driver.execute_script(js))
        except Exception:
            return "(덤프 실패)"

    def _clear_all_serial_rows(qty: int) -> bool:
        """기록된 시리얼 행을 **전부** 지운다(2026-08-27).

        ✗는 '선택된 행 하나'를 지운다 - 수량이 2면 두 번 눌러야 한다는 사용자
        지적대로 행이 없어질 때까지 반복한다. 기존 코드는 한 번 누르고
        _recorded_serials()가 비어 보이면 '전체 삭제 완료'로 단정했는데, 실측
        (TO 7876705 Pick Slip 9119299, 2026-08-27 10:33~10:35)에서는 두 행이
        그대로 남은 채(Numbers Entered=2, Remaining=0) 통과해버렸고, 그 상태로
        'Enter Single Serial Number'를 누르니 오라클이 "The entire quantity is
        already entered. (INV-2416271)"로 막았다.

        그래서 (1) 지울 때마다 행 수가 실제로 줄었는지 확인하고, (2) 화면을
        벗어나면(=엉뚱한 버튼을 눌렀다는 뜻) 즉시 실패로 본다. 삭제는 OK를
        누르기 전까지 확정되지 않으므로 이 함수가 도는 동안 화면을 떠나면 안 된다.
        """
        # 행 수 + 여유 3회. 무한루프 방지.
        for _ in range(max(qty, 1) + 3):
            rows = _serial_row_inputs()
            entered = _numbers_entered()
            if not rows and entered in (0, None):
                return True
            if not rows:
                # 칸은 안 보이는데 Numbers Entered가 남아있으면 판정 불가 -
                # 잘못 지웠다고 단정하지 말고 실패로 올려 사람이 보게 한다.
                log(f"    [주의] 시리얼 입력칸은 안 보이는데 Numbers Entered={entered}")
                return False
            before = len(rows)
            try:
                rows[0].click()   # ✗는 선택된 행을 지우므로 먼저 행을 고른다
                time.sleep(0.5)
            except Exception:
                pass
            progressed = False
            cands = _delete_icon_buttons()
            for b in cands:
                try:
                    driver.execute_script("arguments[0].click();", b)
                except Exception:
                    continue
                time.sleep(1.5)
                _dismiss_error_dialog()
                if not _on_serial_screen():
                    log("    [주의] 삭제 클릭 후 Record Serial Numbers 화면을 벗어남 "
                        "- 잘못된 버튼으로 판단")
                    return False
                if len(_serial_row_inputs()) < before:
                    progressed = True
                    break
            if not progressed:
                # 어떤 요소를 X로 봤는지 남긴다 - 이게 없으면 "안 지워진다"만 알고
                # 원인(후보 0개인지, 눌렀는데 안 먹는지)을 모른 채 재실행하게 된다.
                log(f"    [진단] X 후보 {len(cands)}개로 삭제 실패 - "
                    f"후보={_dump_serial_toolbar()}")
                return False
            log(f"    시리얼 행 삭제: {before}개 -> {len(_serial_row_inputs())}개 "
                f"(Numbers Entered={_numbers_entered()})")
        return not _serial_row_inputs()

    for task in tasks:
        line, part_no = task["line"], task["part_no"]
        sns = [str(s) for s in task["sns"]]
        qty = task["qty"]
        field_locator = task.get("locator") or ""
        expected_locator = task.get("expected_locator") or ""
        log(f"  시리얼 기입: 라인 {line} ({part_no}) - 화면 locator={field_locator!r}, "
            f"용마 locator={expected_locator!r}, {sns} (수량 {qty})")

        # 로케이터-시리얼 세트(사용자 확인): 화면의 locator가 용마 값과 다르면
        # 그 로케이터의 시리얼을 알 수 없으므로 기입하지 않고 검토 대기로 넘긴다.
        if field_locator and expected_locator and field_locator != expected_locator:
            log(f"  [검토] 라인 {line}: 화면 locator('{field_locator}')가 용마 값("
                f"'{expected_locator}')과 다름 - 시리얼 기입 생략, 검토 대기로 넘김")
            continue

        # 첫 화면 진입
        if not _on_serial_screen():
            _open_serial_screen(line)

        # 2026-08-27 사용자 지적("품목 종류가 여러개가 생기는 경우엔 주의해야해"):
        # 라인이 여러 개면 **남의 라인 화면에 시리얼을 쓸 위험**이 있다. 특히 위
        # `if not _on_serial_screen()`은 앞 라인의 화면이 안 닫힌 채 남아 있으면
        # 그대로 통과해버린다. 그래서 화면의 Line/Item이 이 작업과 같은지 확인하고,
        # 아니면 다시 연다. (시리얼이 없는 품목은 용마 회신에 S/N이 없어 애초에
        # tasks에 안 들어오므로 여기까지 오지 않는다 - confirm_pick_slips 참고.)
        ok, why = _serial_screen_matches(line, part_no)
        if not ok:
            log(f"  [주의] 시리얼 화면이 라인 {line}({part_no})이 아님({why}) - 다시 진입")
            _open_serial_screen(line)
            ok, why = _serial_screen_matches(line, part_no)
        if not ok:
            _diag("serial_wrong_line")
            raise RuntimeError(
                f"Record Serial Numbers 화면이 라인 {line}({part_no})의 것이 아님"
                f"({why}) - 다른 품목에 시리얼을 쓰지 않도록 중단")

        recorded = _recorded_serials()
        log(f"  Record Serial Numbers 화면: 기록된 시리얼={recorded}")

        # 용마에 없는 시리얼이 기록돼 있으면 ✗로 **전부** 지운 뒤 재기입
        # (2026-08-27 사용자 지시: "x로 다 지우고 enter single serial number로 해야해",
        #  "수량이 2개니까 2개를 다 삭제해야지"). _clear_all_serial_rows 주석 참고.
        if set(recorded) - set(sns):
            log(f"  기록된 시리얼 {recorded} 중 용마 값이 아닌 것 발견 - "
                f"{len(recorded)}행 전부 삭제 후 재기입")
            if not _clear_all_serial_rows(qty):
                _diag("serial_clear")
                raise RuntimeError(
                    f"기존 시리얼 삭제(X) 실패 - 남은 값={_recorded_serials()}, "
                    f"Numbers Entered={_numbers_entered()}. 화면에서 직접 삭제해주세요")
            log(f"  시리얼 전체 삭제 완료 (Numbers Entered={_numbers_entered()})")
            recorded = []
            cleared_here = True
        else:
            cleared_here = False

        # 2026-08-26 사용자 지시: 시리얼은 **전부 입력한 뒤 OK를 한 번만** 누른다
        # (하나마다 OK를 누르면 화면이 닫혀 나머지를 못 넣는다 - 7877405 실측).
        missing = [sn for sn in sns if sn not in recorded]
        if missing:
            log(f"  기입 필요 시리얼: {missing}")
            for sn in missing:
                if not _on_serial_screen():
                    # 방금 ✗로 지운 상태라면 화면을 다시 여는 순간 **지운 게 되살아난다**
                    # (삭제는 OK를 눌러야 확정된다). 되살아난 행 위에 기입하면 다시
                    # "The entire quantity is already entered"로 막히므로 여기서 멈춘다.
                    if cleared_here:
                        _diag("serial_lost_after_clear")
                        raise RuntimeError(
                            f"시리얼 삭제 직후 Record Serial Numbers 화면을 벗어남 "
                            f"- 재진입하면 지운 값이 되살아나므로 중단(라인 {line})")
                    log("  Record Serial Numbers 화면 재진입")
                    _open_serial_screen(line)
                _enter_one_row(sn)
                time.sleep(1)
            # 모든 행이 채워졌는지 확인
            recorded = _recorded_serials()
            if set(recorded) != set(sns):
                _diag("serial_rows")
                raise RuntimeError(f"시리얼 행 입력 확인 실패: 화면={recorded}, 용마={sns}")
            # OK 한 번 -> 저장
            ok_clicked = False
            for t in ("OK", "확인"):
                ob = [e for e in driver.find_elements(
                    By.XPATH, f"//button[normalize-space(.)='{t}']") if e.is_displayed()]
                if ob:
                    driver.execute_script("arguments[0].click();", ob[-1])
                    ok_clicked = True
                    time.sleep(2.5)
                    break
            _dismiss_error_dialog()
            log(f"  OK 클릭(ok_clicked={ok_clicked})")

        # 최종 확인: 화면이 닫혔으면 Pick Slip 라인으로 복귀된 상태
        if _on_serial_screen():
            recorded = _recorded_serials()
            if set(recorded) != set(sns):
                _diag("serial_final")
                raise RuntimeError(f"시리얼 최종 불일치: {recorded} vs {sns}")
            for t in ("확인", "Done", "완료", "Back", "뒤로"):
                ob = [e for e in driver.find_elements(
                    By.XPATH, f"//button[normalize-space(.)='{t}']") if e.is_displayed()]
                if ob:
                    driver.execute_script("arguments[0].click();", ob[-1])
                    time.sleep(2.5)
                    break
        log(f"  시리얼 기입 완료: {sns}")




def _send_regulatory_hold_request(to_number: str, shipment_no: str, part_no: str,
                                  is_rma: bool) -> None:
    """Ship Confirm이 CANDELA REGULATORY HOLD로 막혔을 때 담당자에게 해제
    요청 메일을 **바로 발송**한다(2026-09-16 사용자 지시 + 실제 TO 7881992
    /Shipment 9982077/Part 7122-00-9912 건으로 검증된 수신자·문구).

    사람이 조치해야 풀리는 외부(오라클 Regulatory 관리) 이슈를 담당자에게
    즉시 알린다는 점에서 rma_auto_reply.py의 "Interface To Oracle=Error ->
    담당 FSE에게 재생성 요청 자동발송"과 같은 성격이라 초안이 아니라 발송한다."""
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = REGULATORY_HOLD_MAIL_TO
    mail.CC = REGULATORY_HOLD_MAIL_CC
    mail.Subject = f"TO {to_number} - Regulatory Hold Release Request (Part {part_no})"

    context = "RMA(본사 반송) 건" if is_rma else "Rebalance 건"
    body_text = (
        f"스티븐님 안녕하세요,\n\n"
        f"TO {to_number} ({context})이 {part_no} 품목에 Regulatory Hold가 걸려 있어서 "
        f"Ship Confirm이 안 되고 있습니다(Shipment {shipment_no}).\n\n"
        f"확인하시고 Regulatory Hold 해제 부탁드려도 될까요?\n\n"
        f"해제되면 알려주시면 감사하겠습니다.\n"
    )
    mail.HTMLBody = mail_text_to_html(body_text)
    mail.Send()
    log(f"[Pipeline] TO {to_number}: Regulatory Hold 해제 요청 메일 발송 완료 "
        f"(Part {part_no}, Shipment {shipment_no}, To={REGULATORY_HOLD_MAIL_TO})")


def check_and_handle_shipment_exceptions(driver, to_number: str, shipment_no: str,
                                         is_rma: bool) -> bool:
    """Edit Shipment 화면(Ship Confirm 버튼이 있는 화면)에 막 도달했을 때 호출한다.
    'Exceptions in Shipment' 표시가 있으면 그 예외들을 읽어 Regulatory Hold면
    담당자에게 해제 요청 메일을 보내고, 아니면 사람 확인 알림만 보낸다.

    2026-09-16 실측(TO 7881992, Shipment 9982077, Part 7122-00-9912) 기준으로
    처음 짠 코드라 셀렉터가 다른 케이스에서 안 맞을 수 있다 - 그런 경우에도
    조용히 넘어가지 않도록, 예외 표시 자체는 있는데 내용을 못 읽으면 안전하게
    '막혔음(True)'으로 보고 사람 확인 알림을 보낸다(놓치는 것보다 과잉 알림이
    낫다).

    반환: True면 이 Shipment은 막혀 있어 Ship Confirm을 시도하면 안 됨.
    False면 예외가 없어 그대로 Ship Confirm 진행 가능."""
    from selenium.webdriver.common.by import By

    exc_labels = [el for el in driver.find_elements(
                      By.XPATH, "//*[contains(normalize-space(text()),'Exceptions in Shipment')]")
                  if el.is_displayed()]
    if not exc_labels:
        return False  # 라벨 자체가 없으면 예외 없음(기존 정상 케이스와 동일 화면)

    # 2026-09-16 실측 버그 수정(TO 7881076/Shipment 9982824): "Exceptions in
    # Shipment" 라벨은 예외가 0건이어도 **항상** 떠 있고 옆에 그냥 "0"이라고만
    # 써 있다 - 라벨 존재 여부만 보고 막힌 것으로 오판해서, 실제로는 아무 문제
    # 없는 정상 TO의 Ship Confirm을 잘못 막았다(사람 알림만 가고 자동 진행은
    # 안 됐으니 다행히 잘못된 트랜잭션은 없었음). 라벨 자체가 아니라 **같은 행에
    # title='Error'인 아이콘 링크가 실제로 있는지**로만 판단한다 - 없으면(값이
    # "0"이든 뭐든) 예외 없음으로 보고 그대로 진행시킨다.
    exc_icon_row = driver.find_elements(
        By.XPATH,
        "//label[normalize-space(text())='Exceptions in Shipment']/ancestor::tr[1]")
    if exc_icon_row and not exc_icon_row[0].find_elements(By.XPATH, ".//a[@title='Error']"):
        return False  # 값이 0(또는 에러 아이콘 없음) - 정상, 막지 않음

    # 2026-09-16 실측(TO 7881992/Shipment 9982077, DOM 덤프로 확인)으로 확정한
    # 구조: "Exceptions in Shipment" 라벨과 같은 <tr> 안에 title="Error"인 <a>
    # (안에 alt="Error" <img>)가 실제 클릭 대상이고, 그 뒤에 개수 링크
    # "(<a>1</a>)"가 따로 있다. 이전엔 "라벨 뒤 첫 a/button"으로 추측해서
    # 짰는데(우연히 이번엔 같은 요소를 골랐지만) 문서 전체에서 "다음" 것을
    # 찾는 방식이라 다른 레이아웃에서 엉뚱한 링크를 집을 위험이 있었다 -
    # 같은 행(tr)으로 범위를 좁혀 title='Error'인 링크를 직접 지정한다.
    icon_candidates = driver.find_elements(
        By.XPATH,
        "//label[normalize-space(text())='Exceptions in Shipment']"
        "/ancestor::tr[1]//a[@title='Error']")
    clicked = False
    for el in icon_candidates:
        if el.is_displayed():
            try:
                el.click()
                clicked = True
                break
            except Exception:
                continue
    if not clicked:
        log(f"[Pipeline] TO {to_number}: 'Exceptions in Shipment' 표시는 있는데 "
            f"title='Error' 아이콘을 못 찾음 - 안전하게 막힘으로 처리")
        try:
            diag = os.path.join(
                os.path.dirname(__file__),
                f"_diag_shipment_exc_noicon_{to_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            driver.save_screenshot(diag)
        except Exception:
            pass
        send_alert(
            f"[Rebalance TO {to_number}] Ship Confirm 예외 확인 실패",
            f"Shipment {shipment_no}에 'Exceptions in Shipment' 표시가 있는데 "
            f"자동으로 상세 화면을 열지 못했습니다. 오라클에서 직접 확인해주세요.",
        )
        return True

    # 2026-09-16: 고정 sleep(2) 한 번으로 판정하던 걸 폴링으로 바꿨다 - ADF
    # 부분화면갱신(PPR)이 2초보다 오래 걸리는 경우를 놓쳐서 "화면 전환 실패"로
    # 오판할 수 있었다(실측: 첫 시도에서 이 오판이 실제로 발생함).
    # 2026-09-21: 8초도 부족한 경우 실측(SSO 재로그인 직후 첫 조회 - Edge/오라클
    # 콜드스타트라 평소보다 느림). 스크린샷으로는 실제 화면 전환이 이미 끝나
    # 있었는데 폴링이 먼저 포기해서 "확인 실패" 알림이 잘못 나갔다 - 15초로 늘림.
    body_text_all = ""
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            body_text_all = driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            body_text_all = ""
        if "Review Shipping Exceptions" in body_text_all:
            break
        time.sleep(1)
    if "Review Shipping Exceptions" not in body_text_all:
        log(f"[Pipeline] TO {to_number}: Exceptions 아이콘을 눌렀는데 "
            f"Review Shipping Exceptions 화면으로 안 감 - 안전하게 막힘으로 처리")
        try:
            diag = os.path.join(
                os.path.dirname(__file__),
                f"_diag_shipment_exc_click_{to_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            driver.save_screenshot(diag)
            log(f"  [진단] Exceptions 아이콘 클릭 후 화면: {os.path.basename(diag)}")
        except Exception:
            pass
        send_alert(
            f"[Rebalance TO {to_number}] Ship Confirm 예외 확인 실패",
            f"Shipment {shipment_no}의 예외 상세 화면 이동에 실패했습니다. "
            f"오라클에서 직접 확인해주세요.",
        )
        return True

    # Exception Details 패널 제목이 "{Exception Name}: Exception Details"라
    # (실측: "CANDELA REGULATORY HOLD: Exception Details") 여기서 사유를 읽는다.
    detail_titles = [t.text for t in driver.find_elements(
        By.XPATH, "//*[contains(text(),'Exception Details')]") if t.text]
    reason_text = " / ".join(detail_titles)
    is_regulatory = "REGULATORY" in reason_text.upper()

    # 예외 표(Entity 컬럼에 품번)에서 품번을 최대한 뽑는다 - 이 코드베이스
    # 전체가 쓰는 품번 형식(예: 7122-00-9912, 1301-00-7763)을 그대로 앵커로 쓴다.
    part_nos = sorted(set(re.findall(r"\b\d{4}-\d{2}-\d{4}\b", body_text_all)))
    if not part_nos:
        part_nos = ["(품번 확인 필요)"]

    with _STATE_LOCK:
        state = load_state()
        notified = state.setdefault("shipment_exception_notified", {})
        to_list = notified.setdefault(to_number, [])
        new_keys = []
        for part_no in part_nos:
            key = f"{shipment_no}:{part_no}"
            if key not in to_list:
                to_list.append(key)
                new_keys.append((key, part_no))
        if new_keys:
            save_state(state)

    if not new_keys:
        log(f"[Pipeline] TO {to_number} Shipment {shipment_no}: 이미 알림 보낸 "
            f"예외들이라 재발송 없이 막힘 상태만 보고함")
        return True

    for _, part_no in new_keys:
        if is_regulatory:
            try:
                _send_regulatory_hold_request(to_number, shipment_no, part_no, is_rma)
            except Exception as e:
                log(f"[경고] TO {to_number} Regulatory Hold 메일 발송 실패: {exc_detail(e)}")
                send_alert(
                    f"[Rebalance TO {to_number}] Regulatory Hold 메일 발송 실패",
                    f"Shipment {shipment_no}, Part {part_no}: {exc_detail(e)}\n"
                    f"수동으로 {REGULATORY_HOLD_MAIL_TO}에게 해제 요청해주세요.",
                )
        else:
            send_alert(
                f"[Rebalance TO {to_number}] Ship Confirm 예외 발생 - 확인 필요",
                f"Shipment {shipment_no}, Part {part_no}에서 Regulatory Hold가 아닌 "
                f"다른 예외가 발견됐습니다(사유: {reason_text or '확인 불가'}).\n"
                f"오라클에서 직접 확인해주세요.",
            )

    log(f"[Pipeline] TO {to_number} Shipment {shipment_no}: 예외 {len(part_nos)}건으로 "
        f"Ship Confirm 진행 불가(Regulatory={is_regulatory})")
    return True


def confirm_pick_slips(driver, to_number: str, locations: list[dict],
                       progress: dict | None = None,
                       stop_before_confirm: bool = False,
                       skip_slips: set | None = None,
                       stop_before_ship_confirm: bool = False,
                       is_rma: bool = False) -> str:
    """progress: 넘기면 진행 지점을 기록한다(2026-08-05 추가). "Confirm and Go to
    Ship Confirm"이 먹히는 순간 Shipment 번호가 생기는데, 그 뒤 단계에서 터지면
    재시도해도 Pick Slip은 이미 사라져 재검색이 안 된다(오라클이 한 번만 허용).
    그때 Shipment 번호를 잃지 않으려고 읽자마자 progress["shipment_no"]에 남기고,
    Ship Confirm까지 끝나면 progress["ship_confirmed"]=True로 표시한다.

    Shipments > Confirm Pick Slips에서 로케이터/수량을 확인하고 Confirm and
    Go to Ship Confirm -> Ship Confirm까지 실행해서 Shipment 번호(9로 시작)를
    반환한다.

    **2026-08-05 TO 7866440으로 전체 흐름 실측 검증 완료**(사용자와 함께
    스크린샷 보며 진행, 이 함수는 그 실측을 그대로 코드화한 것 - 자동 실행
    자체는 아직 재검증 전이니 처음 돌릴 땐 결과를 확인할 것):
    1. Tasks > Shipments > Confirm Pick Slips 진입.
    2. Order에 TO#, **Due Date 필드를 완전히 비우고**(기본값 오늘 날짜가 들어
       있어 지우지 않으면 검색이 안 됨) Search.
    3. 검색 결과의 Pick Slip 번호 링크 클릭(품목이 여러 개여도 Pick Slip은
       보통 1개 - TO 안의 라인들이 그 안에 다 들어있음).
    4. **각 라인마다**(품목이 여러 개면 전부) Picked Quantity=Requested
       Quantity로 채우고, Source Locator가 비어있으면 locations에서 매칭해
       채운 뒤, Ready to confirm 체크박스를 클릭 - 2026-08-05 사용자 피드백:
       "오늘은 품목이 하나라 하나만 했는데 여러 개면 다 해야 해".
    5. 우측 상단 "Confirm" **옆의 작은 드롭다운 화살표**(`<a title="Confirm">`,
       텍스트 버튼과 별개 요소)를 **ActionChains로 실제 마우스 클릭**(JS 클릭은
       이 메뉴를 안 엶 - 실측 확인) -> "Confirm and Go to Ship Confirm" 클릭.
    6. "Edit Shipment: {Shipment#}" 화면 이동 - 이 Shipment#가 SOP의
       "ShipConfirm/Delivery 번호"(9로 시작, 나중에 SharePoint Delivery#/ICBL
       인보이스 Delivery Number로 그대로 사용).
    7. "Ship Confirm" 버튼 클릭 -> "The shipment {번호} was confirmed." 확인."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
    from selenium.webdriver.common.action_chains import ActionChains

    # 2026-08-06: 같은 Edge를 공유하는 다른 자동화의 탭을 보고 있으면 아래
    # driver.get()이 남의 탭을 덮어쓰고 이후 클릭이 엉뚱한 화면에서 실패한다
    # ([[icbl-ci-watcher-automation]]의 _ensure_my_tab 참고).
    _ensure_my_tab(driver)
    driver.get(ORACLE_HOME_URL)
    # 2026-08-06(2차) 고정대기 -> 조건대기. wait_or_sleep은 조건이 충족되면 즉시
    # 진행하고, 끝까지 안 되면 **원래 sleep과 정확히 같은 시간**을 기다린다
    # (최악의 경우가 기존과 동일 = 더 나빠질 수 없음). 아래는 '조건이 미리 참일
    # 수 없는' 자리만 골랐다. ship_confirm_watcher의 같은 구간에서 실측 A/B로
    # 검증함(고정 24.9초 -> 조건 11.1초, 성공률 3/3 동일, -55%).
    # 여기: driver.get()으로 페이지를 새로 받았으므로 미리 참일 수 없다.
    wait_or_sleep(driver, text_visible("Supply Chain Execution"), 5)
    _click_text(driver, "Supply Chain Execution")
    # 여기만 고정 대기 유지: 스프링보드에서 'Inventory Management' 아이콘이 이
    # 클릭 **전에도 이미 보이는** 경우가 있어(icbl _goto_scheduled_processes에
    # 실측 기록) 조건이 미리 참이 되면 재배치 중에 눌러버릴 수 있다.
    time.sleep(3)
    _click_text(driver, "Inventory Management")
    # Tasks 아이콘은 Inventory Management 화면에만 있다 - 미리 참일 수 없어 안전.
    # 5초 안에 안 뜨면 기존처럼 진행하고 아래 _wait_find(40초)가 이어받는다.
    wait_or_sleep(driver, element_present(By.XPATH, "//img[@title='Tasks']"), 5)
    # 2026-08-06 실측: 여기서 NoSuchElementException(//img[@title='Tasks'])으로
    # 반복 실패함(TO 7866552, 3번 다). 실패까지 걸린 시간이 위 고정 sleep 13초 +
    # _wait_find 기본 8초와 정확히 맞아떨어져서, 화면이 안 뜨는 게 아니라 Inventory
    # Management 렌더가 8초보다 오래 걸리는 것으로 판단(같은 Edge를 여러 자동화가
    # 공유하니 내 탭이 백그라운드일 때 렌더가 더 느려질 수 있다). 타임아웃을
    # 넉넉하게 준다 - 먼저 뜨면 바로 넘어가므로 정상 케이스는 느려지지 않는다.
    try:
        tasks_icon = _wait_find(driver, By.XPATH, "//img[@title='Tasks']", timeout=40)
    except Exception:
        # 40초를 줘도 못 찾으면 "느린 렌더"가 아니라 애초에 다른 화면에 있는
        # 것이므로, 추측하지 말고 그 순간 화면을 남긴다(_diag_ 접두사 = 진단용).
        try:
            diag = os.path.join(
                ROOT, f"_diag_tasksicon_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            driver.save_screenshot(diag)
            log(f"  [진단] Tasks 아이콘 못 찾음 - 화면 캡처: {os.path.basename(diag)} "
                f"(현재 URL: {driver.current_url})")
        except Exception:
            pass
        raise
    # 2026-08-06(2차) 공유 브라우저 상태 간섭 대응: Tasks 아이콘은 **토글**이라
    # 이미 열려 있는데 또 누르면 패널이 닫힌다. 이 열림 상태는 driver.get()으로
    # 페이지를 다시 열어도 유지되고, 같은 Edge를 공유하는 자동화 중 아무도
    # 패널을 닫지 않는다 - 앞선 자동화가 열어둔 채 끝내면 여기서 스스로 닫아버려
    # 바로 아래 Shipments select를 못 찾는다. 네이티브 클릭도 백그라운드 창에서
    # 씹히는 게 실측돼 JS 클릭으로 함께 바꾼다.
    if not tasks_panel_open(driver):
        driver.execute_script("arguments[0].click();", tasks_icon)
    # Shipments 옵션을 가진 select는 Tasks 패널이 열려야 생긴다(패널이 이미
    # 열려 있어 위 클릭을 건너뛴 경우엔 이미 있으므로 즉시 통과가 맞다).
    wait_or_sleep(driver, element_present(
        By.XPATH, "//select[option[normalize-space(text())='Shipments']]"), 2)
    sel_el = _wait_find(driver, By.XPATH, "//select[option[normalize-space(text())='Shipments']]",
                        timeout=20)
    Select(sel_el).select_by_visible_text("Shipments")
    # 'Confirm Pick Slips'는 Shipments 카테고리 작업이라 다른 카테고리에서는
    # 안 보인다 - 카테고리를 실제로 바꿔야 하는 경우엔 미리 참일 수 없다.
    wait_or_sleep(driver, text_visible("Confirm Pick Slips"), 2)
    _click_text(driver, "Confirm Pick Slips")
    # 이 화면의 Order 검색 입력칸이 나타나야 다음 줄에서 쓸 수 있다.
    wait_or_sleep(driver, element_present(
        By.XPATH, "//label[normalize-space(text())='Order']/following::input[1]"), 3)

    order_el = driver.find_element(By.XPATH, "//label[normalize-space(text())='Order']/following::input[1]")
    order_el.click()
    order_el.clear()
    order_el.send_keys(to_number)
    time.sleep(1)
    due_date_el = driver.find_element(By.XPATH, "//label[normalize-space(text())='Due Date']/following::input[1]")
    due_date_el.click()
    due_date_el.clear()
    time.sleep(1)

    # 2026-08-06 실측(TO 7870361, 7866552 둘 다 이 지점에서 StaleElementReference/
    # NoSuchElement로 3번 다 실패): 이 화면에도 'Search'라는 텍스트가 두 곳에 있다 -
    # 검색 패널 제목과 실제 Search 버튼. 위 코드처럼 텍스트만 보고 첫 번째를 누르면
    # DOM 순서상 앞에 있는 제목(<h1>/<span>)을 눌러서 검색이 아예 실행되지 않고,
    # 예외도 안 난다. 그 상태로 아래에서 결과 테이블 링크를 찾으니 검색 전 테이블의
    # 낡은 요소를 잡아 stale이 되거나 아무것도 못 찾는다
    # ([[icbl-ci-watcher-automation]]의 Process ID 검색과 완전히 같은 원인).
    # -> 클릭 가능한 컨트롤(button/a)만 대상으로 한다(제목은 heading이라 제외됨).
    # 2026-08-26: Search 버튼 탐색/클릭에 stale 재시도 추가(7877405 검증 중
    # 실측: ADF 재렌더로 scrollIntoView 시점에 stale이 나서 실패).
    for _search_attempt in range(3):
        try:
            search_btn = None
            for el in driver.find_elements(
                    By.XPATH, "//*[self::button or self::a][normalize-space(.)='Search']"):
                try:
                    if el.is_displayed() and el.is_enabled():
                        search_btn = el
                        break
                except Exception:
                    continue
            if search_btn is None:
                raise RuntimeError("Confirm Pick Slips 화면에서 Search 버튼(button/a)을 못 찾음")
            driver.execute_script("arguments[0].scrollIntoView(true);", search_btn)
            try:
                search_btn.click()
            except Exception:
                driver.execute_script("arguments[0].click();", search_btn)
            break
        except Exception as e:
            if _search_attempt == 2 or "stale" not in str(e).lower():
                raise
            log(f"  [재시도] Search 버튼 stale({type(e).__name__}) - 재탐색")
            time.sleep(1.5)
    time.sleep(4)

    # 검색 결과 테이블의 Pick Slip 번호(숫자만 있는 링크) 클릭.
    # 2026-08-06: 검색 결과가 렌더링될 때까지 기다린 뒤 찾는다(위에서 검색이 실제로
    # 실행되게 고쳤으므로, 이제 결과가 늦게 오는 경우만 남는다). 요소는 클릭 직전에
    # 다시 찾아서 stale을 피한다.
    from selenium.webdriver.support.ui import WebDriverWait

    # 2026-08-06 실측 사고(사용자가 스크린샷으로 발견): 예전 코드는 화면의 숫자
    # 링크 중 **첫 번째를 무조건** 클릭했다 - 그 결과 TO 7866552를 처리하는 중에
    # 다른 TO(7870361)의 Pick Slip 9111328을 열었다. 그대로 진행하면 남의 TO를
    # 잘못된 수량으로 Ship Confirm하는 사고가 난다. 반드시 "그 TO가 들어있는 행"
    # 안에서 Pick Slip 링크를 찾고, 화면에 들어간 뒤 한 번 더 검증한다.
    # 2026-08-06 진단으로 확인한 DOM 구조(_diag_slip_link_*.png):
    # 이 결과 테이블은 ADF 중첩 테이블이라 **Pick Slip 번호 링크는 바깥쪽 <tr>**에
    # 있고, 데이터 셀(Organization/Order/...)은 그 안의 중첩 <tr>에 있다. 그래서
    # "TO가 있는 안쪽 행" 안에서 링크를 찾으면 절대 못 찾는다(실측: 7866552).
    # -> 숫자로만 된 링크를 훑되, 그 링크의 조상 <tr> 텍스트에 이 TO 번호가
    # 있는지로 짝을 맞춘다. 이러면 필터가 덜 걸려 다른 TO의 Pick Slip이 같이
    # 나와도 내 것만 정확히 고른다(실측: 7866552 -> 9111329, 7870361 -> 9111328).
    def _slip_link_for_to(d):
        for a in d.find_elements(By.TAG_NAME, "a"):
            try:
                text = a.text.strip()
                if not text.isdigit() or text == to_number or not a.is_displayed():
                    continue
                # 2026-08-26: 이미 기입을 마친 슬립은 건너뛴다(FG 추가 릴리즈로
                # 한 주문에 슬립이 여러 개가 되는 케이스 대응).
                if skip_slips and text in skip_slips:
                    continue
                tr = a.find_element(By.XPATH, "./ancestor::tr[1]")
                if to_number in tr.text:
                    return a
            except Exception:
                continue
        return None

    try:
        WebDriverWait(driver, 20, poll_frequency=0.5).until(
            _slip_link_for_to,
            message=f"TO {to_number} 행의 Pick Slip 링크가 20초 안에 안 나타남",
        )
    except Exception:
        # 2026-08-06: 여기서 반복 실패 중 - 검색이 실제로 걸리는지, 결과 테이블이
        # 어떤 모양인지 추측하지 말고 그 순간 화면과 Order 입력값을 남긴다.
        try:
            typed = order_el.get_attribute("value")
        except Exception:
            typed = "(읽기 실패)"
        try:
            diag = os.path.join(
                ROOT, f"_diag_pickslip_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            driver.save_screenshot(diag)
            log(f"  [진단] Pick Slip 행 못 찾음 - 캡처: {os.path.basename(diag)}, "
                f"Order 칸에 실제 입력된 값={typed!r}, URL={driver.current_url}")
        except Exception:
            pass
        raise RuntimeError(
            f"TO {to_number}에 대한 Pick Slip을 검색 결과에서 못 찾음(그 TO의 행 자체가 없음)")
    slip_link = _slip_link_for_to(driver)
    slip_no = slip_link.text.strip()
    if progress is not None:
        # 2026-08-27: 슬립이 2장일 때 두 번째 호출에서 첫 슬립을 건너뛰려면
        # 번호를 알아야 한다(skip_slips) - 읽자마자 남긴다.
        progress["slip_no"] = slip_no
    driver.execute_script("arguments[0].click();", slip_link)
    time.sleep(4)

    # 진입 검증: 상세 화면에 이 TO 번호(Order 칸)가 실제로 있어야 한다.
    # 없으면 남의 Pick Slip이므로 아무것도 건드리지 않고 즉시 중단한다.
    try:
        WebDriverWait(driver, 20, poll_frequency=0.5).until(
            lambda d: d.find_elements(By.XPATH, "//*[contains(text(),'Confirm Pick Slip')]"),
            message="Confirm Pick Slip 상세 화면으로 이동 확인 실패",
        )
    except Exception as e:
        raise RuntimeError(f"TO {to_number} Pick Slip {slip_no} 상세 화면 진입 실패: {e}")
    page_text = driver.find_element(By.TAG_NAME, "body").text
    if to_number not in page_text:
        raise RuntimeError(
            f"Pick Slip {slip_no}을 열었는데 화면에 TO {to_number}가 없음 - 다른 TO의 "
            f"Pick Slip으로 판단해 아무것도 입력하지 않고 중단함(수량 오확정 방지)")
    log(f"[Oracle] TO {to_number} Pick Slip {slip_no} 진입 확인")

    # 파트넘버별 locator/qty 매핑(용마 회신 파싱 결과).
    # 2026-09-18 버그 수정(사용자 지적, TO 7882258 실사례): 시리얼 번호가 있는
    # 품목은 용마 회신이 시리얼 하나당 한 행(같은 part_no, qty="1")으로 온다
    # (예: 5개면 5행). 예전엔 딕셔너리 컴프리헨션이 같은 part_no를 그냥
    # 덮어써서 마지막 1행(qty=1, 시리얼 1개)만 남았고, 오라클 Requested
    # Quantity(5)와 비교해 "다르다"며 멈췄다(실제로는 5행 x qty1 = 5로
    # 정확히 일치하는 정상 케이스였음). 이제 같은 part_no의 행들을 qty는
    # 합산, sn은 전부 모아서 하나로 합친다 - 시리얼 기입(serial_tasks)도
    # 같은 loc_by_part를 쓰므로 이걸 고치면 둘 다 같이 고쳐진다.
    loc_by_part: dict[str, dict] = {}
    for loc in locations:
        part_no = loc.get("part_no")
        if not part_no:
            continue
        merged = loc_by_part.setdefault(
            part_no, {"part_no": part_no, "locator": "", "qty": "", "sn": []})
        if not merged["locator"] and loc.get("locator"):
            merged["locator"] = loc["locator"]
        row_qty = str(loc.get("qty") or "").strip()
        if row_qty.isdigit():
            merged["qty"] = str(int(merged["qty"] or 0) + int(row_qty))
        for s in loc.get("sn") or []:
            if s not in merged["sn"]:
                merged["sn"].append(s)
    # 2026-08-26: 시리얼 기입 대상 라인 수집(라인 루프에서 채움)
    serial_tasks = []

    # 각 라인 행: [checkbox(Ready to confirm), Line, Pick Status, Item, Description,
    # UOM, Requested Qty, Picked Qty(입력), Source Subinventory(입력), Source Locator(입력), ...]
    # 2026-08-05 실측: 품목 하나일 땐 이 XPath가 중복으로 여러 번 잡히는 게
    # 확인됨(Oracle ADF 접근성용 그림자 구조로 추정) - rows[0]만 써도 실제
    # 조작에는 문제없었음(같은 DOM 요소를 가리킴).
    # **2026-08-06 중대 수정(사용자가 스크린샷으로 발견)**: 이 XPath는 데이터 행뿐
    # 아니라 그 행들을 감싸는 **바깥쪽 <tr>까지** 매칭한다(ADF 중첩 테이블).
    # 품목이 1개일 때는 안팎이 사실상 같아서 문제가 안 드러났지만(2026-08-05
    # 단일품목 실측이 통과한 이유), 품목이 2개 이상이면 바깥 <tr> 하나를 "한 행"으로
    # 처리하면서 texts[0]=1번 라인의 수량칸, checkboxes[-1]=2번 라인의 체크박스를
    # 잡는다 - 실제로 TO 7870361에서 1번 라인(Requested 2)에 2번 라인 수량인 1이
    # 들어가고, 2번 라인은 빈 채로, 체크는 2번 라인에만 걸렸다.
    # -> not(.//tr)로 **중첩 <tr>이 없는 진짜 데이터 행만** 고른다
    # ([[icbl-ci-watcher-automation]]의 _my_row() 바깥쪽 tr 문제와 같은 계열).
    # 2026-08-06 진단으로 확정한 구조(_diag_pickslip_rows_*.png):
    # 이 화면도 ADF 중첩 테이블이라 "라인 행"을 tr 조건으로 잡으려던 시도는 전부
    # 빗나갔다 - not(.//tr)를 붙이면 0개(모든 후보 행이 중첩 tr을 3개씩 가짐),
    # 떼면 페이지 전체를 감싸는 tr까지 3개가 잡혀서 라인 경계가 무너진다
    # (그래서 예전 코드가 1번 라인 수량칸 + 2번 라인 체크박스를 섞어 잡았다).
    # 대신 **수량 입력칸의 id 패턴이 고정적**이라는 걸 찾았다:
    #   pt1:...:AT1:_ATp:table1:{행번호}:pickedqtyid::content
    # 그래서 이 입력칸들을 기준점으로 삼고, 각 입력칸에서 "체크박스를 가진 가장
    # 가까운 조상 tr"로 올라가 그 라인의 범위를 정한다. 라인 수 = 입력칸 수라
    # 라인이 몇 개든 정확히 1:1로 처리된다.
    qty_inputs = [e for e in driver.find_elements(
        By.CSS_SELECTOR, "input[id*='pickedqtyid']") if e.is_displayed()]
    if not qty_inputs:
        raise RuntimeError(
            "Pick Slip 상세 화면에서 Picked Quantity 입력칸(id에 'pickedqtyid')을 못 찾음")
    log(f"[Oracle] TO {to_number} Pick Slip 라인 {len(qty_inputs)}개 발견 - 라인별로 기입")

    for idx, picked_qty_el in enumerate(qty_inputs, start=1):
        row = picked_qty_el.find_element(
            By.XPATH, "./ancestor::tr[.//input[@type='checkbox']][1]")
        inputs = row.find_elements(By.TAG_NAME, "input")
        checkboxes = [i for i in inputs if i.get_attribute("type") == "checkbox"]
        texts = [i for i in inputs if i.get_attribute("type") == "text"]
        if not checkboxes:
            raise RuntimeError(f"TO {to_number} 라인 {idx}: 그 라인의 체크박스를 못 찾음")

        row_text = row.text
        matched_loc = None
        for part_no, loc in loc_by_part.items():
            if part_no in row_text:
                matched_loc = loc
                break

        # picked_qty_el은 루프 변수(id로 직접 찾은 그 라인의 수량칸)를 그대로 쓴다 -
        # texts[0]으로 다시 잡으면 행 안의 입력칸 순서에 의존하게 되므로 쓰지 않는다.
        # 2026-08-06: 수량은 용마 회신값이 아니라 **화면의 Requested Quantity**를
        # 그대로 쓴다(SOP: "Picked Quantity에 Requested Quantity와 동일한 값 입력").
        # Requested Quantity 셀은 Picked Quantity 입력칸이 든 td의 바로 앞 td다.
        requested = ""
        try:
            requested = picked_qty_el.find_element(
                By.XPATH, "./ancestor::td[1]/preceding-sibling::td[1]").text.strip()
        except Exception:
            pass
        if not requested.isdigit():
            raise RuntimeError(
                f"TO {to_number} 라인 {idx}: 화면에서 Requested Quantity를 읽지 못함"
                f"(읽은 값={requested!r}) - 수량을 추측해서 넣지 않고 중단함")
        # 2026-09-18 사용자 지시: "Picked Quantity는 항상 Requested Quantity와
        # 같으면 된다" - 용마 회신 수량과 다르다고 자동화를 중단하지 않는다
        # (SOP 자체가 "Picked Quantity=Requested Quantity"이지 용마 수량과의
        # 교차검증이 아니다 - 시리얼 분할 파싱 버그로 여기서 반복 오탐이 났던
        # TO 7882258이 계기). 참고용으로 다르면 로그만 남기고 그대로 진행한다.
        yongma_qty = str((matched_loc or {}).get("qty") or "").strip()
        if yongma_qty and yongma_qty != requested:
            log(f"  [정보] 라인 {idx}: 오라클 Requested Quantity({requested})와 "
                f"용마 회신 수량({yongma_qty})이 다름 - Requested Quantity 그대로 진행")
        picked_qty_el.click()
        picked_qty_el.clear()
        picked_qty_el.send_keys(requested)
        log(f"  라인 {idx}: Picked Quantity={requested}"
            + (f", 파트={matched_loc['part_no']}" if matched_loc else " (파트 매칭 실패)"))
        time.sleep(0.5)

        locator_value = ""
        if len(texts) >= 3:
            locator_el = texts[2]
            # 2026-08-26 사용자 지시: 용마 받은 locator로 **무조건** 기입한다 -
            # 로케이터마다 담긴 제품(시리얼)이 다르므로 기존 값(수동 입력분 포함)
            # 이 있어도 덮어쓴다. 시리얼 번호가 없어도 마찬가지.
            if matched_loc and matched_loc.get("locator"):
                if (locator_el.get_attribute("value") or "").strip() != matched_loc["locator"]:
                    locator_el.click()
                    locator_el.clear()
                    locator_el.send_keys(matched_loc["locator"])
                    time.sleep(0.5)
            locator_value = (locator_el.get_attribute("value") or "").strip()

        ready_checkbox = checkboxes[-1]
        if not ready_checkbox.is_selected():
            driver.execute_script("arguments[0].click();", ready_checkbox)
        time.sleep(0.5)

        # 2026-08-26: 용마 회신에 S/N이 있는 라인은 시리얼 기입 대상으로 수집
        sns = (matched_loc or {}).get("sn") or []
        if sns:
            serial_tasks.append({"line": idx, "part_no": matched_loc["part_no"],
                                 "sns": [str(s) for s in sns],
                                 "qty": int(requested),
                                 "locator": locator_value,
                                 "expected_locator": matched_loc.get("locator") or ""})

    driver.switch_to.active_element.send_keys("\t")
    time.sleep(1)

    # 2026-08-26: 시리얼 번호 기입(Actions -> Record Serial Numbers ->
    # Enter Single Serial Number, 사용자 실측 스크린샷 흐름)
    if serial_tasks:
        _record_serial_numbers(driver, to_number, serial_tasks)

    # 2026-08-26 사용자 지시(중요): "Confirm and Go to Ship Confirm은 누르지 말고
    # 대기" - 시리얼/수량/로케이터를 사람이 검토한 뒤 직접 클릭한다. 이 함수는
    # 여기서 정상 종료되고 화면은 그대로 둔다(호출부가 탭을 닫지 않도록 주의).
    if stop_before_confirm:
        log(f"[Oracle] TO {to_number}: 검토 대기 - Confirm and Go to Ship Confirm "
            f"직전 중단(사용자 검토 후 직접 클릭)")
        return slip_no

    confirm_arrows = [el for el in driver.find_elements(By.XPATH, "//a[@title='Confirm']") if el.is_displayed()]
    if not confirm_arrows:
        raise RuntimeError("Confirm 드롭다운 화살표를 못 찾음")
    ActionChains(driver).move_to_element(confirm_arrows[0]).click().perform()
    time.sleep(1.5)

    confirm_ship_items = [
        el for el in driver.find_elements(By.XPATH, "//*[contains(text(),'Confirm and Go to Ship Confirm')]")
        if el.is_displayed()
    ]
    if not confirm_ship_items:
        raise RuntimeError("'Confirm and Go to Ship Confirm' 메뉴 항목을 못 찾음")
    ActionChains(driver).move_to_element(confirm_ship_items[0]).click().perform()
    time.sleep(4)

    title_els = driver.find_elements(By.XPATH, "//*[contains(text(),'Edit Shipment:')]")
    if not title_els:
        raise RuntimeError("Ship Confirm 화면(Edit Shipment)으로 이동 실패")
    m = re.search(r"Edit Shipment:\s*(\d+)", title_els[0].text)
    if not m:
        raise RuntimeError("Edit Shipment 화면에서 Shipment 번호를 못 읽음")
    shipment_no = m.group(1)
    if progress is not None:
        # Confirm이 이미 먹혀 Shipment이 생긴 시점 - 여기부터는 Pick Slip 재검색이
        # 안 되므로 번호를 즉시 남겨 재시도 실패 시에도 잃지 않게 한다.
        progress["shipment_no"] = shipment_no

    # 2026-08-26: 열려있는 배송에 다른 슬립을 추가로 Confirm해야 하는 경우
    # (FG 백오더로 슬립 2개) Ship Confirm 클릭 전에 정지해 검증한다.
    if stop_before_ship_confirm:
        log(f"[Oracle] TO {to_number}: Edit Shipment {shipment_no} 도달 - "
            f"Ship Confirm 클릭 전 정지")
        return shipment_no

    return _run_ship_confirm(driver, to_number, shipment_no, is_rma, progress)


def _run_ship_confirm(driver, to_number: str, shipment_no: str, is_rma: bool,
                      progress: dict | None = None) -> str:
    """Edit Shipment 화면(이미 그 화면에 있어야 함)에서 Exceptions 확인 ->
    Ship Confirm 클릭 -> 확정 검증까지. confirm_pick_slips()가 Confirm 직후
    호출하는 것과, "Confirm Pick Slips는 끝났고 Ship Confirm만 남은" 케이스를
    Manage Shipments로 재개할 때(start_at='ship_confirm') 둘 다 이 함수를
    쓴다(2026-09-16 분리 - TO 7881076: 예외 오탐으로 멀쩡한 Shipment의 Ship
    Confirm이 막혔던 걸 재개할 방법이 없어서 만듦)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains

    # 2026-09-16 추가(TO 7881992/Shipment 9982077 실측): Ship Confirm 버튼을
    # 누르기 전에 Exceptions in Shipment(예: CANDELA REGULATORY HOLD)부터
    # 확인한다 - 막혀 있으면 담당자에게 알리고(Regulatory면 자동발송, 그 외는
    # 사람 알림) ShipmentOnHold를 올려 여기서 조용히 멈춘다.
    if check_and_handle_shipment_exceptions(driver, to_number, shipment_no, is_rma):
        raise ShipmentOnHold(
            f"TO {to_number} Shipment {shipment_no}: Exception으로 Ship Confirm 보류 "
            f"(담당자 알림 발송됨)")

    def _fallback_to_exception_recheck(context: str):
        """버튼이 비활성화거나 확정 신호를 못 읽었을 때 쓴다. **기다리거나
        재시도하지 않고 딱 한 번만** Exceptions를 다시 확인한다(2026-09-16
        사용자 지적: "안 뜰 때까지 계속 방황하는 거 아니냐" - 그래서 폴링/대기
        없이 즉시 판단하고 끝낸다). Regulatory Hold를 지금 찾으면
        ShipmentOnHold로 넘어가 정상적인 담당자 알림 경로를 그대로 타고,
        못 찾으면 원인 불명 에러로 사람에게 넘긴다."""
        if check_and_handle_shipment_exceptions(driver, to_number, shipment_no, is_rma):
            raise ShipmentOnHold(
                f"TO {to_number} Shipment {shipment_no}: {context} - Exceptions 재확인에서 "
                f"발견돼 Ship Confirm 보류(담당자 알림 발송됨)")
        raise RuntimeError(
            f"TO {to_number} Shipment {shipment_no}: {context}"
            f"(Exceptions 재확인에도 원인을 못 찾음) - 오라클에서 직접 확인해주세요")

    ship_confirm_btns = [el for el in driver.find_elements(By.XPATH, "//*[normalize-space(text())='Ship Confirm']")
                         if el.is_displayed()]
    if not ship_confirm_btns:
        raise RuntimeError("Ship Confirm 버튼을 못 찾음")
    # 2026-09-16 추가: 버튼이 비활성화 상태(예: Exceptions in Shipment로 막힘)면
    # 클릭이 조용히 씹힐 수 있다 - check_and_handle_shipment_exceptions()가 이미
    # 앞에서 대부분 걸러내지만, 다른 사유로 막혔을 수도 있으니 한 번 더 확인한다.
    if not ship_confirm_btns[0].is_enabled():
        _fallback_to_exception_recheck("Ship Confirm 버튼이 비활성화 상태")
    ActionChains(driver).move_to_element(ship_confirm_btns[0]).click().perform()

    # 2026-09-16 추가(사용자 지적): 이 "OK" 팝업이 뜬다는 사실 자체가 "확정
    # 다이얼로그가 실제로 떴다"는 증거다 - 팝업이 안 뜨면 버튼이 비활성화라
    # 클릭이 씹혔거나 다른 에러가 났을 가능성이 높다는 뜻. 팝업 문구는 **닫기
    # 전에** 읽어야 한다(OK를 누르면 다이얼로그가 닫혀 DOM에서 사라진다).
    # 2026-09-22 변경(TO 7886291 실측): 고정 4초 후 한 번만 보면 팝업이 늦게 뜬
    # 경우를 놓친다 - SHIP_CONFIRM_POPUP_WAIT_SEC 안에서 1초 간격으로 다시 찾아,
    # 실제 확정 신호("was confirmed")를 최대한 붙잡는다(찾으면 즉시 빠져나감).
    ok_btns = []
    _popup_deadline = time.time() + SHIP_CONFIRM_POPUP_WAIT_SEC
    while time.time() < _popup_deadline:
        ok_btns = [el for el in driver.find_elements(By.XPATH, "//*[normalize-space(text())='OK']") if el.is_displayed()]
        if ok_btns:
            break
        time.sleep(1)
    popup_text = ""
    if ok_btns:
        try:
            dialog = ok_btns[0].find_element(
                By.XPATH, "./ancestor::*[contains(@role,'dialog') or contains(@class,'dialog')][1]")
            popup_text = dialog.text
        except Exception:
            popup_text = ""
        driver.execute_script("arguments[0].click();", ok_btns[-1])
    time.sleep(1)

    # 지금까지는 "클릭하고 예외가 안 났으면 성공"으로 무조건 넘어갔다 - 실제
    # 확정 여부를 확인하지 않았다(사용자 지적). 확인 순서: (1) 방금 읽은 팝업
    # 문구에 확정 메시지(2026-08-05 실측: "The shipment {번호} was confirmed.")가
    # 있는지, (2) 팝업이 아예 안 떴거나 문구를 못 읽었으면 Edit Shipment 화면의
    # 'Shipment Status'가 더 이상 'Open'이 아닌지로 폴백 확인, (3) 둘 다 실패하면
    # 성공으로 단정하지 않고 예외를 올린다.
    confirmed_msg_found = "was confirmed" in popup_text.lower()
    if not confirmed_msg_found:
        status_els = driver.find_elements(
            By.XPATH, "//*[contains(normalize-space(text()),'Shipment Status')]"
                     "/following::*[1]")
        status_text = (status_els[0].text or "").strip() if status_els else ""
        if not status_text or status_text.lower() == "open":
            _fallback_to_exception_recheck(
                f"Ship Confirm 확정 팝업이 "
                f"{'안 떴고' if not ok_btns else '떴지만 문구를 못 읽었고'} Shipment "
                f"Status도 '{status_text or '확인불가'}'(Open이면 아직 미확정)")
        log(f"[Oracle] TO {to_number} Shipment {shipment_no}: 팝업 문구는 못 읽었지만 "
            f"Shipment Status='{status_text}'(Open 아님)로 확정된 것으로 판단")

    if progress is not None:
        progress["ship_confirmed"] = True
    _mark_stage_done(to_number, shipment_no=shipment_no, ship_confirmed=True)

    log(f"[Oracle] Confirm Pick Slips ~ Ship Confirm 완료: TO {to_number} -> Shipment {shipment_no}")
    return shipment_no


# ==============================================================
# 10) SharePoint Delivery# 기입 (쓰기)
# ==============================================================
def _sharepoint_row_counts(driver, to_number: str):
    """지금 렌더된 데이터 행 중 (이 TO인 행 수, 이 TO가 아닌 행 수)."""
    from selenium.webdriver.common.by import By
    mine = other = 0
    for row in driver.find_elements(By.XPATH, "//div[@role='row']"):
        try:
            txt = (row.text or "").strip()
            if not txt or row.find_elements(By.XPATH, ".//div[@role='columnheader']"):
                continue
            if to_number in txt:
                mine += 1
            else:
                other += 1
        except Exception:
            continue
    return mine, other


def _wait_sharepoint_filtered(driver, to_number: str, timeout: int = 40):
    """리스트가 이 TO로 실제 필터된 상태가 될 때까지 기다린다.
    2026-08-06: `?q=`만으로는 검색창에 값이 들어가고도 목록이 그대로인 경우가
    실측됨 - 검색창에 직접 넣고 Enter까지 눌러 재시도한다. 판정 기준은
    "렌더된 행 중 이 TO가 아닌 행이 하나도 없다"(가상 스크롤이라 전체 목록이면
    남의 행이 반드시 섞여 있다)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    deadline = time.time() + timeout
    typed = False
    while time.time() < deadline:
        mine, other = _sharepoint_row_counts(driver, to_number)
        if mine > 0 and other == 0:
            log(f"[SharePoint] 목록이 TO {to_number}로 필터됨(행 {mine}개)")
            return
        if not typed:
            log(f"[SharePoint] 목록이 아직 필터 안 됨(내 행 {mine}개 / 남의 행 {other}개) "
                f"- 검색창에 직접 입력해 재시도")
            boxes = [e for e in driver.find_elements(
                By.CSS_SELECTOR, "input[type='search'], input[role='searchbox'], input[placeholder]")
                if e.is_displayed() and e.is_enabled()]
            for box in boxes:
                try:
                    box.click()
                    box.send_keys(Keys.CONTROL, "a")
                    box.send_keys(to_number)
                    box.send_keys(Keys.ENTER)
                    typed = True
                    break
                except Exception:
                    continue
            if not typed:
                raise RuntimeError("SharePoint 검색 입력창을 못 찾음(필터 적용 불가)")
        time.sleep(3)
    mine, other = _sharepoint_row_counts(driver, to_number)
    raise RuntimeError(
        f"SharePoint 목록이 TO {to_number}로 필터되지 않음(내 행 {mine}개 / 남의 행 "
        f"{other}개) - 필터 없이 가상 스크롤 그리드를 편집하면 엉뚱한 행을 건드릴 "
        f"수 있어 중단함")


SHAREPOINT_SITE_PATH = "/sites/APACOperation"
SHAREPOINT_LIST_TITLE = "APAC Stock Movements"

# 2026-08-06: 그리드 뷰 편집(클릭+타이핑)은 결국 신뢰할 수 없다고 결론냈다.
# 실측: 편집 모드는 정상 ON인데도 Delivery# 셀을 네이티브 클릭/더블클릭해도
# 셀이 편집 상태가 되지 않고(activeElement가 계속 body, 셀 안 input 0개) 키 입력이
# 아무 데도 안 들어갔다. TO 7870379는 12번 시도해도 저장 0건. 반면 같은 코드가
# 7870361/7866552에서는 저장돼서 원인 특정이 오래 걸렸다.
# -> 브라우저 세션(같은 오리진, 로그인 쿠키 그대로)에서 **SharePoint REST API**로
# 직접 쓰면 그리드를 거치지 않고 확실하다. 실측: 2879/2881 둘 다 204 + 재조회로
# 9969124 확인. 내부 필드명은 그리드 셀 class(field-DeliveryNumber)에서 확인.
_SP_WRITE_JS = r"""
var cb = arguments[arguments.length-1];
var TO = arguments[0], VAL = arguments[1];
var site = arguments[2], listTitle = arguments[3];
var L = "getbytitle('" + listTitle + "')";
var H = {'Accept': 'application/json;odata=nometadata'};
(async function(){
  try{
    var q = site + '/_api/web/lists/' + L +
            "/items?$select=Id,TO_x0023_,DeliveryNumber&$filter=TO_x0023_%20eq%20" + TO;
    var rj = await (await fetch(q, {headers: H})).json();
    var items = rj.value || [];
    var before = items.map(function(x){ return {Id: x.Id, D: x.DeliveryNumber}; });
    var writes = [];
    if (items.length) {
      var ctx = await (await fetch(site + '/_api/contextinfo', {method:'POST', headers:H})).json();
      var digest = ctx.FormDigestValue;
      for (var i = 0; i < items.length; i++) {
        if (String(items[i].DeliveryNumber || '') === String(VAL)) {
          writes.push({Id: items[i].Id, status: 'skip'});
          continue;
        }
        var res = await fetch(site + '/_api/web/lists/' + L + '/items(' + items[i].Id + ')', {
          method: 'POST',
          headers: {'Accept':'application/json;odata=nometadata',
                    'Content-Type':'application/json;odata=nometadata',
                    'X-RequestDigest': digest, 'X-HTTP-Method':'MERGE', 'IF-MATCH':'*'},
          body: JSON.stringify({DeliveryNumber: Number(VAL)})
        });
        writes.push({Id: items[i].Id, status: res.status});
      }
    }
    var after = ((await (await fetch(q, {headers: H})).json()).value || [])
                .map(function(x){ return {Id: x.Id, D: x.DeliveryNumber}; });
    cb(JSON.stringify({before: before, writes: writes, after: after}));
  } catch(e) { cb('ERR: ' + (e && e.message ? e.message : e)); }
})();
"""


def write_delivery_to_sharepoint(driver, to_number: str, delivery_no: str,
                                 expected_rows: int | None = None):
    """APAC Stock Movements의 Delivery# 컬럼을 REST API로 기입한다(2026-08-06 전환).
    한 TO에 파트가 여러 개면 그 TO의 **모든 항목**에 기입하고, 응답으로 실제 값을
    재조회해 확인한다. expected_rows(=파트 수)보다 항목이 적게 잡히면 일부만
    기입하지 않고 중단한다."""
    import json as _json

    # fetch를 상대경로로 쓰려면 같은 오리진에 있어야 한다.
    if SHAREPOINT_SITE_PATH not in (driver.current_url or ""):
        driver.get(SHAREPOINT_STOCK_MOVEMENTS_URL)
        time.sleep(6)
    driver.set_script_timeout(120)
    raw = driver.execute_async_script(
        _SP_WRITE_JS, str(to_number), str(delivery_no),
        SHAREPOINT_SITE_PATH, SHAREPOINT_LIST_TITLE)
    if isinstance(raw, str) and raw.startswith("ERR: "):
        raise RuntimeError(f"SharePoint REST 호출 실패: {raw[5:]}")
    data = _json.loads(raw)
    found = len(data.get("after", []))
    log(f"[SharePoint] TO {to_number} 항목 {found}개"
        + (f" (기대 파트 수 {expected_rows})" if expected_rows else "")
        + f" - 기입 결과: {data.get('writes')}")
    if not found:
        raise RuntimeError(f"SharePoint에서 TO {to_number} 항목을 못 찾음")
    if expected_rows and found < expected_rows:
        raise RuntimeError(
            f"SharePoint에서 TO {to_number} 항목이 {found}개만 잡힘"
            f"(기대 {expected_rows}개) - 일부만 기입하지 않고 중단함")
    ok = [x for x in data["after"] if str(x.get("D") or "") == str(delivery_no)]
    if len(ok) < found:
        raise RuntimeError(
            f"SharePoint TO {to_number}: {found}개 중 {len(ok)}개만 Delivery#="
            f"{delivery_no}로 확인됨 (재조회 결과: {data['after']})")
    log(f"[SharePoint] TO {to_number} 항목 {len(ok)}/{found}개에 "
        f"Delivery#={delivery_no} 기입 확인")


def _write_delivery_to_sharepoint_grid(driver, to_number: str, delivery_no: str,
                                       expected_rows: int | None = None):
    """(구) 그리드 뷰 편집 방식 - 2026-08-06 REST 방식으로 대체됨. 참고용으로만 남김.
    expected_rows: 이 TO가 가져야 할 행 수(=파트 수). 주면 그보다 적게 잡혔을 때
    일부만 기입하지 않고 중단한다(2026-08-06 추가).
    2026-08-05 TO 7866440으로 실측 검증 완료: "그리드 뷰에서 편집" 모드 진입 ->
    TO# 값과 일치하는 gridcell 찾기 -> 바로 오른쪽(다음 형제 div)이 Delivery#
    셀 -> 클릭 -> 값 입력 -> Enter -> "그리드 뷰 종료"로 커밋."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.keys import Keys

    # 2026-08-06 실측(_diag_sp_cells_7870361.png): `?q=`로 들어가면 검색창에 값은
    # 들어가지만 **목록이 필터되지 않는 경우가 있다**(캡처: 검색창엔 7870361인데
    # 화면 행들은 7866566/7870383/7870377…). 이 그리드는 가상 스크롤이라 필터가
    # 안 걸린 전체 목록에서는 화면에 렌더된 행만 DOM에 있고, 편집 후 다시 조회하면
    # 렌더된 행 집합이 바뀌어 "2행 중 1행만 확인"처럼 검증이 어긋난다.
    # -> 필터가 실제로 걸린 것을 확인한 뒤에 그리드를 만진다.
    # 2026-08-06 실측: `?q=`(검색)는 검색창에 값만 넣고 목록을 안 거르는 경우가 있어
    # (내 행 2 / 남의 행 28로 확인) 대신 **리스트 뷰 URL 필터**를 쓴다. TO# 컬럼의
    # 내부 이름이 `TO_x0023_`("#"이 _x0023_로 인코딩)인 것을 실측으로 확정했고,
    # 이 URL로 들어가면 내 행만 남는다(내 행 2 / 남의 행 0).
    driver.get(f"{SHAREPOINT_STOCK_MOVEMENTS_URL}"
               f"?FilterField1=TO_x0023_&FilterValue1={to_number}&FilterType1=Number")
    time.sleep(7)
    _wait_sharepoint_filtered(driver, to_number)

    edit_btns = [el for el in driver.find_elements(By.XPATH, "//*[contains(text(),'그리드 뷰에서 편집')]")
                 if el.is_displayed()]
    if not edit_btns:
        raise RuntimeError("SharePoint '그리드 뷰에서 편집' 버튼을 못 찾음")
    driver.execute_script("arguments[0].click();", edit_btns[0])
    time.sleep(3)

    # **2026-08-06 중대 수정(사용자 지적)**: 한 TO에 파트가 여러 개면 APAC Stock
    # Movements에도 그 TO 행이 **여러 개** 생긴다(파트별 1행). 예전 코드는
    # to_cells[0]만 골라 첫 행에만 쓰고도 "기입 완료"를 찍어서, 나머지 행은 조용히
    # 빈 채로 남았다(오늘 처리한 3건 전부 파트 2개짜리). 전부 순회해서 쓴다.
    cell_xpath = f"//div[@role='gridcell'][normalize-space(text())='{to_number}']"
    to_cells = driver.find_elements(By.XPATH, cell_xpath)
    if not to_cells:
        raise RuntimeError(f"SharePoint 그리드에서 TO# {to_number} 셀을 못 찾음")
    found = len(to_cells)
    log(f"[SharePoint] TO {to_number} 행 {found}개 발견"
        + (f" (기대 파트 수 {expected_rows})" if expected_rows else ""))
    # 검색 인덱스 지연으로 행이 덜 잡히는 경우가 실측된 리스트라
    # ([[rebalance-to-automation-sop]]), 기대 개수보다 적으면 반쯤 채우지 않고 멈춘다.
    if expected_rows and found < expected_rows:
        raise RuntimeError(
            f"SharePoint에서 TO {to_number} 행이 {found}개만 잡힘(기대 {expected_rows}개) - "
            f"일부만 기입하지 않고 중단함")

    for i in range(found):
        # 한 셀을 편집하면 그리드가 다시 렌더링돼 앞서 찾아둔 요소가 stale이 되므로
        # 매 회차마다 셀을 처음부터 다시 찾는다.
        cells = driver.find_elements(By.XPATH, cell_xpath)
        if i >= len(cells):
            raise RuntimeError(
                f"SharePoint TO {to_number}: {i}번째 행 편집 중 행 목록이 줄어듦"
                f"({len(cells)}개) - 중단")
        def _row_has_value(idx: int) -> bool:
            """idx번째 TO 행의 텍스트에 이 Delivery#가 들어갔는지.
            2026-08-06: 셀을 following-sibling으로 집어 읽는 방식은 편집모드/읽기모드
            에서 구조가 달라 오판이 있었다(같은 값을 두고 2/2와 0/2가 갈렸음) -
            행 전체 텍스트로 판정하는 게 실측상 가장 안정적이었다."""
            try:
                cs = driver.find_elements(By.XPATH, cell_xpath)
                if idx >= len(cs):
                    return False
                row_el = cs[idx].find_element(By.XPATH, "./ancestor::div[@role='row'][1]")
                return str(delivery_no) in (row_el.text or "")
            except Exception:
                return False

        if _row_has_value(i):
            log(f"  행 {i + 1}/{found}: 이미 Delivery#={delivery_no} - 건너뜀")
            continue

        # 2026-08-06 실측: 클릭+타이핑이 셀 편집으로 안 들어가는 경우가 있어
        # ENTER까지 눌러도 값이 저장되지 않는다(7870379는 두 행 모두 저장 안 됨,
        # 7866552는 2행째만 실패). 로그만 남기고 넘어가면 조용한 미기입이 되므로,
        # 셀 단위로 즉시 확인하고 안 들어갔으면 그 자리에서 다시 시도한다.
        written = False
        for attempt in range(3):
            cells = driver.find_elements(By.XPATH, cell_xpath)
            if i >= len(cells):
                break
            # 2026-08-06 실측: Delivery# 셀은 class에 'field-DeliveryNumber'가 붙어
            # 있다(위치 기반 following-sibling보다 확실). 같은 행 안에서 그 셀을 찾는다.
            row_el = cells[i].find_element(By.XPATH, "./ancestor::div[@role='row'][1]")
            dcs = row_el.find_elements(
                By.CSS_SELECTOR, "div[role='gridcell'][class*='field-DeliveryNumber']")
            if not dcs:
                raise RuntimeError(
                    f"SharePoint TO {to_number} 행 {i + 1}: Delivery# 셀"
                    f"(class에 field-DeliveryNumber)을 못 찾음")
            delivery_cell = dcs[0]
            ActionChains(driver).move_to_element(delivery_cell).click().perform()
            time.sleep(0.6)
            ActionChains(driver).send_keys(Keys.CONTROL, "a").perform()
            ActionChains(driver).send_keys(str(delivery_no)).perform()
            time.sleep(0.6)
            ActionChains(driver).send_keys(Keys.ENTER).perform()
            time.sleep(3)
            if _row_has_value(i):
                written = True
                log(f"  행 {i + 1}/{found}: Delivery#={delivery_no} 기입 확인"
                    + (f" ({attempt + 1}번째 시도)" if attempt else ""))
                break
            log(f"  행 {i + 1}/{found}: 입력했는데 값이 안 남음 - 재시도 "
                f"({attempt + 2}/3)")
        if not written:
            raise RuntimeError(
                f"SharePoint TO {to_number} 행 {i + 1}/{found}: Delivery#={delivery_no}가 "
                f"3번 시도해도 저장되지 않음 - 그리드 편집이 안 먹는 상태로 판단해 중단")

    exit_btns = [el for el in driver.find_elements(By.XPATH, "//*[contains(text(),'그리드 뷰 종료')]")
                 if el.is_displayed()]
    if exit_btns:
        driver.execute_script("arguments[0].click();", exit_btns[0])
    # 그리드 뷰를 나간 뒤 SharePoint가 저장을 반영하는 데 시간이 걸린다(3초로는
    # 부족해 오판한 사례 있음).
    time.sleep(8)

    # 기입 후 실제로 값이 들어갔는지 최종 확인 - 로그만 믿지 않는다(2026-08-06 교훈).
    verified = 0
    for row in driver.find_elements(By.XPATH, "//div[@role='row']"):
        try:
            txt = (row.text or "").strip()
            if not txt or row.find_elements(By.XPATH, ".//div[@role='columnheader']"):
                continue
            if to_number in txt and str(delivery_no) in txt:
                verified += 1
        except Exception:
            continue
    if verified < found:
        raise RuntimeError(
            f"SharePoint TO {to_number}: {found}행 중 {verified}행만 Delivery#="
            f"{delivery_no}로 확인됨 - 나머지 행을 직접 확인해주세요")
    log(f"[SharePoint] TO {to_number} 행 {verified}/{found}개에 Delivery#={delivery_no} 기입 확인")


# ==============================================================
# 11~12) 인천관세법인 Print Commercial Invoice (Ship From=KRP) + PDF 보정
# ==============================================================
# ==============================================================
# CI 완료 대기 큐 (2026-08-19 추가)
# ==============================================================
# 배경(사용자 지적): 오라클 Print Commercial Invoice는 Blocked로 오래 걸리는 게
# 보통이다 - icbl_ci_watcher 주석에 **2시간~8시간** 걸린 사례가 실측으로 남아 있다.
# 그런데 이 파일은 한 회차 안에서 17분을 붙잡고 기다리는 방식(_wait_for_oracle_report,
# max_seconds=17*60)이라 애초에 이길 수 없는 싸움이었다. 실측(2026-08-19): TO
# 7874424/7874410 둘 다 17분을 다 태우고 OracleStillProcessing으로 실패했고,
# run_with_oracle_retry가 이를 3회 반복해 회차가 통째로 묶였다.
#
# icbl_ci_watcher는 이미 이 문제를 풀어놨다(main()의 A~D 단계): 제출과 완료확인을
# 분리하고(submit_oracle_ci_report / poll_oracle_ci_report), 시간 예산을 넘기면
# Process ID를 저장해둔 채 끝내고 **다음 스케줄 실행이 이어받는다**. 이 파일의
# run_icbl_invoice_krp_both docstring에도 "submit/poll을 재사용한다"고 적혀 있는데
# 실제로는 블로킹 함수를 쓰고 있었다 - 옮기다 만 상태였다. 그 구조를 마저 옮긴다.
#
# 동작:
#   1) CI 단계에 처음 오면 리포트를 **제출만** 하고 ci_pending에 Process ID를 저장,
#      CIStillWaiting을 올려 그 회차는 거기서 정상 종료한다(에러 아님, 알림 없음).
#   2) 이후 용마 회차마다 process_ci_pending()이 큐를 훑어 완료 여부를 한 번씩 확인.
#      Succeeded면 그 자리에서 나머지(HTS/주소 보정 -> CI 저장 -> 수출신고실적)를
#      마저 돌리고 큐에서 뺀다.
# pending_cases는 파이프라인이 끝까지 성공해야 지워지므로(아래 pop 지점), CI를
# 기다리는 동안 TO 정보(country/parts_qty/is_rma)는 그대로 살아있다.
CI_PENDING_BUDGET_SEC = 12 * 60   # 한 회차에서 CI 확인에 쓸 시간 상한
# 오라클 Scheduled Processes 조회 필터가 최대 24시간이라, 그보다 오래되면 저장해둔
# Process ID로도 화면에서 못 찾는다 - 그 전에 사람에게 알린다.
CI_PENDING_STALE_HOURS = 20


class CIStillWaiting(Exception):
    """CI 리포트가 아직 Succeeded가 아니라는 신호.

    **에러가 아니라 '정상 보류'다** - 알림을 보내지 않고 다음 회차가 이어받는다.
    run_with_oracle_retry의 no_retry_exceptions로 넘겨 재시도도 하지 않는다
    (몇 초 뒤에 다시 봐야 결과가 같다)."""


class ShipmentOnHold(Exception):
    """Ship Confirm 화면에 도달했는데 Shipment에 Exception(예: CANDELA
    REGULATORY HOLD)이 걸려 있어 Ship Confirm을 시도할 수 없다는 신호
    (2026-09-16 추가, TO 7881992/Shipment 9982077 실측).

    **에러가 아니라 '외부(담당자) 조치 대기'다** - 알림/메일은 이 예외를 올리기
    **전에** check_and_handle_shipment_exceptions()가 이미 보냈으므로, 이
    예외를 받은 쪽은 로그만 남기고 조용히 종료한다(중복 알림 방지). Confirm
    Pick Slips는 이미 끝나 Shipment 번호가 생긴 뒤라 오라클에서 그 Pick Slip을
    다시 Confirm할 수 없다 - 홀드 해제 회신이 오면 Edit Shipment 화면에서 Ship
    Confirm만 이어서 실행하는 재개 경로가 아직 없으므로(2026-09-16 시점), 그
    때까지는 사람이 직접 확인하거나 이 재개 경로부터 만들어야 한다."""


def _ci_pending_put(to_number: str, shipment_no: str, process_id: str) -> None:
    # 2026-08-26: 키를 TO# -> "TO#:배송" 복합 키로 변경(한 TO에 배송 2건 케이스
    # 대응 - 7876545 실측 버그: 두 번째 배송 CI 제출이 첫 번째 Process를 재사용).
    key = f"{to_number}:{shipment_no}"
    with _STATE_LOCK:
        st = load_state()
        st.setdefault("ci_pending", {})[key] = {
            "shipment_no": str(shipment_no),
            "process_id": str(process_id),
            "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_state(st)


def _ci_pending_remove(to_number: str, shipment_no: str | None = None) -> None:
    with _STATE_LOCK:
        st = load_state()
        key = f"{to_number}:{shipment_no}" if shipment_no else to_number
        if (st.get("ci_pending") or {}).pop(key, None) is not None:
            save_state(st)


# CI 리포트 제출 이력(대기 큐와 별도). 큐는 "지금 기다리는 중"을 뜻하고 처리가
# 끝나면 지워지지만, 이 이력은 "이 배송으로 이미 리포트를 냈다"를 남긴다.
# 2026-09-04 추가 - 큐가 비었다는 이유만으로 재제출하다가 같은 리포트를 9번
# 제출한 사고 뒤에 넣었다. 오래된 항목은 자동으로 정리한다.
CI_SUBMISSION_TTL_MIN = 60


def _ci_submission_record(delivery_no: str, process_id: str) -> None:
    with _STATE_LOCK:
        st = load_state()
        subs = st.setdefault("ci_submissions", {})
        subs[str(delivery_no)] = {
            "process_id": str(process_id),
            "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        _ci_submissions_prune(subs)
        save_state(st)


def _ci_submissions_prune(subs: dict) -> None:
    for k in list(subs):
        try:
            age = (datetime.now() - datetime.strptime(
                subs[k]["submitted_at"], "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
        except Exception:
            age = CI_SUBMISSION_TTL_MIN + 1
        if age > CI_SUBMISSION_TTL_MIN:
            subs.pop(k, None)


def _ci_submission_lookup(delivery_no: str) -> str | None:
    """이 배송으로 최근(CI_SUBMISSION_TTL_MIN 이내) 제출한 Process ID."""
    with _STATE_LOCK:
        st = load_state()
        subs = st.get("ci_submissions") or {}
        _ci_submissions_prune(subs)
        st["ci_submissions"] = subs
        save_state(st)
        entry = subs.get(str(delivery_no)) or {}
    return entry.get("process_id") or None


def run_icbl_invoice_krp_both(driver, delivery_no: str, to_number: str) -> str:
    """Ship From=KRP로 Print Commercial Invoice Report를 제출하고 완료까지
    대기해서 PDF 경로를 반환한다. icbl_ci_watcher.py의 submit_oracle_ci_report/
    poll_oracle_ci_report를 org_code='KRP'로 그대로 재사용(사용자 확인: "인천
    관세법인 CI 확인하는 법이랑 똑같아, Ship From만 KRP로 고정"). "Both"는
    이 함수들 내부에서 이미 Item Display 파라미터로 고정 선택되어 있음(별도
    처리 불필요).

    2026-08-05 TO 7866440(Shipment 9968842)으로 end-to-end 실측 검증 완료
    (icbl_ci_watcher.py의 _republish_and_export_pdf에 잔여 팝업 정리 방어
    코드를 추가한 뒤 정상 동작, total=116564.0 확인).

    2026-08-19: **완료까지 기다리지 않는다**(위 'CI 완료 대기 큐' 설명 참고).
    처음이면 제출만 하고 CIStillWaiting을 올리고, 이미 제출해둔 건이면 상태를 한 번만
    확인해서 Succeeded일 때만 PDF 경로를 돌려준다."""
    import icbl_ci_watcher as icbl

    with _STATE_LOCK:
        entry = (load_state().get("ci_pending") or {}).get(
            f"{to_number}:{delivery_no}") or {}
    # 배송 번호가 다른 기존 항목(단일 키 시절 유물)은 재사용하지 않는다 -
    # 7876545 실측: 다른 배송의 Process를 재사용해 같은 CI를 다른 이름으로
    # 저장하는 사고 발생.
    if entry and str(entry.get("shipment_no") or "") != str(delivery_no):
        entry = {}
    process_id = entry.get("process_id")

    # 2026-09-04: 대기 큐가 비면 무조건 새로 제출하는 구조라, 큐가 어떤 이유로든
    # 지워지면 같은 리포트를 계속 다시 제출하게 된다(실측: 큐를 지우며 폴링하는
    # 코드를 돌렸다가 45초 간격으로 9번 중복 제출). 제출 이력을 큐와 **별도로**
    # 남겨서, 최근에 낸 게 있으면 다시 내지 않고 그것을 확인만 한다.
    if not process_id:
        prior = _ci_submission_lookup(delivery_no)
        if prior:
            process_id = prior
            log(f"[ICBL] TO {to_number}: 대기 큐엔 없지만 최근 제출 이력이 있어 "
                f"재제출 없이 Process {process_id} 확인만 합니다")
            _ci_pending_put(to_number, delivery_no, process_id)

    if not process_id:
        process_id = icbl.submit_oracle_ci_report(driver, "KRP", delivery_no)
        log(f"[ICBL] Print Commercial Invoice 제출: KRP/{delivery_no} -> Process {process_id}")
        _ci_pending_put(to_number, delivery_no, process_id)
        _ci_submission_record(delivery_no, process_id)
    else:
        log(f"[ICBL] TO {to_number}: 제출해둔 Process {process_id} 완료 여부 확인"
            f"(제출 {entry.get('submitted_at')})")

    # 대기 루프 없이 "한 번만" 확인한다 - 아직이면 None. Succeeded면 이 안에서
    # Republish -> Export까지 끝내고 총액/PDF를 돌려준다.
    result = icbl.poll_oracle_ci_report(driver, "KRP", delivery_no, process_id)
    if result is None:
        raise CIStillWaiting(
            f"TO {to_number}: CI 리포트(Process {process_id}, delivery {delivery_no})가 "
            f"아직 완료 전 - 다음 용마 회차에서 이어서 확인함")
    log(f"[ICBL] 완료: total={result['total']}, pdf={result['pdf_path']}")
    return result["pdf_path"]


# 2026-08-05 실측(TO 7866440 PDF): BILL TO/SHIP FROM/SHIP TO 3단 레이아웃에서
# 각 라벨의 x좌표(대략 37/221/384.5)는 리포트마다 안정적이었지만, **주소
# 블록 아래쪽 빈 공간의 y좌표(예: Tax Id 줄, item 테이블 행 위치)는 같은
# 리포트를 다시 제출해도 달라질 수 있음이 실측으로 확인됨**(추정 원인: 상단
# 주소 블록의 줄바꿈 개수 차이가 뒤 섹션을 밀어냄) - 그래서 이 함수는 고정
# 좌표를 쓰지 않고, 호출 시점에 그 PDF 안에서 직접 search_for()로 좌표를
# 다시 잰다.
def _cell_bounds_from_rules(page, label_rect):
    """라벨이 들어있는 표 칸의 좌우 경계(세로 괘선 x좌표)를 찾아 돌려준다.
    실측(2026-08-06): 주소 3단의 세로 괘선은 x=31.8/215.4/378.8/553.3에 있고
    BILL TO 칸은 31.8~215.4, SHIP TO 칸은 379.3~553.3이다. 좌표를 하드코딩하지
    않고 매번 재는 이유는 리포트 제출마다 좌표가 흔들릴 수 있기 때문
    (memory rebalance-to-automation-sop의 실측 기록)."""
    xs = []
    for d in page.get_drawings():
        r = d["rect"]
        # 세로 얇은 선(폭 2pt 미만, 높이 30pt 이상)만 괘선으로 인정
        if r.width < 2 and r.height > 30 and r.y0 < label_rect.y0 and r.y1 > label_rect.y1:
            xs.append((r.x0 + r.x1) / 2)
    left = max([x for x in xs if x < label_rect.x0], default=label_rect.x0 - 5)
    right = min([x for x in xs if x > label_rect.x0 + 20], default=label_rect.x0 + 180)
    return left, right


_BASE14_FONT_MAP = {
    "helvetica": "helv",
    "helvetica-bold": "hebo",
    "helvetica-oblique": "heit",
    "helvetica-boldoblique": "hebi",
    "arial": "helv",
    "arial,bold": "hebo",
}


def _get_ship_from_style(page):
    """SHIP FROM 칸에 실제로 찍혀 있는 폰트명/크기/줄간격을 그대로 읽어온다.
    2026-09-15 사용자 지시("폰트를 Ship From에 사용하는 폰트로 모두 통일"):
    예전엔 Bill To/Ship To를 다시 그릴 때 "Helvetica 9pt, 줄간격 10.4pt"를
    2026-08-06 실측값으로 하드코딩해뒀는데, 오라클 리포트 템플릿이 바뀌면
    이 값도 같이 바뀔 수 있다. 매번 그 PDF 안의 SHIP FROM에서 직접 재서 쓰면
    항상 Ship From과 정확히 같은 모양이 보장된다. 못 찾으면 예전 실측값으로
    폴백한다."""
    fallback = ("helv", 9.0, 10.4)
    found = page.search_for("SHIP FROM")
    if not found:
        return fallback
    label = found[0]
    # +200pt 고정폭을 쓰면 오른쪽 SHIP TO 칸(BILL TO/SHIP TO는 3단 레이아웃이라
    # 붙어 있음)까지 걸려서 그 칸의 굵은 라벨/글자를 잘못 주워온다(실측 확인:
    # 2026-09-15) - 세로 괘선으로 잰 실제 칸 경계를 쓴다.
    _, cell_right = _cell_bounds_from_rules(page, label)
    spans = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk["lines"]:
            for sp in ln["spans"]:
                x0, y0, x1, y1 = sp["bbox"]
                txt = sp["text"].strip()
                if (txt and txt.upper() != "SHIP FROM"
                        and label.x0 - 2 <= x0 < cell_right
                        and label.y0 <= y0 <= label.y0 + 150):
                    spans.append(sp)
    if not spans:
        return fallback
    spans.sort(key=lambda s: s["bbox"][1])
    fontsize = spans[0]["size"]
    fontname = _BASE14_FONT_MAP.get(spans[0]["font"].lower().replace(" ", ""), "helv")
    step = fallback[2]
    if len(spans) >= 2:
        diff = round(spans[1]["bbox"][1] - spans[0]["bbox"][1], 2)
        if diff > 0:
            step = diff
    return fontname, fontsize, step


def _split_address_runs(text, base_fontname="helv"):
    """줄 안의 ASCII 구간과 비ASCII(CJK) 구간을 분리해 (조각, 폰트명) 리스트로
    반환한다. 2026-09-15 수정: 예전에는 줄 안에 중국어 글자가 하나라도 섞여
    있으면(예: 전각 콤마 "，" 하나 때문에) 그 줄 전체를 china-s로 그렸다.
    china-s는 라틴 문자를 전각 폭으로 찍어서 "S y n e r o n" 처럼 글자 사이가
    벌어지고, 폭 계산도 어긋나 SHIP TO 칸 밖(CUSTOMER NUMBER 칸)까지 튀어나갔다
    (KRP-CHP 9980515.pdf 실측). 이제 런 단위로 쪼개서 영문/숫자/기호는
    base_fontname(=Ship From 실측 폰트)으로 Bill To/Ship From과 같은 글꼴·
    간격을 유지하고, 실제 한자만 china-s로 찍는다."""
    import re

    runs = []
    for m in re.finditer(r'[\x00-\x7f]+|[^\x00-\x7f]+', text):
        chunk = m.group(0)
        fontname = base_fontname if ord(chunk[0]) <= 0x7F else "china-s"
        runs.append((chunk, fontname))
    return runs or [("", base_fontname)]


def _address_run_width(fitz, runs, fontsize):
    total = 0.0
    for chunk, fontname in runs:
        try:
            total += fitz.get_text_length(chunk, fontname=fontname, fontsize=fontsize)
        except Exception:
            total += len(chunk) * fontsize * 0.6  # 내장 CJK 폰트 폭 계산 실패 시 근사치
    return total


def _wrap_address_line(fitz, text, base_fontname, fontsize, max_w):
    """줄이 max_w보다 길면 폰트를 줄이지 않고 단어 단위로 줄바꿈해서 여러 줄로
    나눈다. 2026-09-15 사용자 지적: CHP 정식 회사명("Syneron/Candela (Bejing)
    Medical Technologies Co., Ltd.")처럼 유독 긴 한 줄이 있으면, 그 줄 하나
    때문에 (같은 fontsize를 쓰는) 블록 전체가 Ship From(9pt)보다 훨씬 작게
    찍혔다(실측 6.5~6.75pt) - "글씨가 더 작고 칸에도 안 맞는다"는 지적대로,
    줄여도 어차피 칸에 꽉 차서 시각적으로 이상했다. 폭 축소 대신 줄바꿈으로
    맞추면 Ship From과 같은 크기를 유지할 수 있다. 단어 하나 자체가 max_w보다
    넓으면(줄바꿈으로 해결 불가) 그 단어만 있는 줄로 남겨 호출부의 폭 축소
    단계(안전장치)가 처리하게 둔다."""
    if _address_run_width(fitz, _split_address_runs(text, base_fontname), fontsize) <= max_w:
        return [text]
    words = text.split(" ")
    out = []
    cur = ""
    for w in words:
        candidate = f"{cur} {w}".strip() if cur else w
        if cur and _address_run_width(
                fitz, _split_address_runs(candidate, base_fontname), fontsize) > max_w:
            out.append(cur)
            cur = w
        else:
            cur = candidate
    if cur:
        out.append(cur)
    return out


def _insert_address_blocks(page, blocks, y_bottom, style=None):
    """blocks=[(label_rect, lines, x_right), ...] (보통 BILL TO/SHIP TO 두 칸)를
    **같은 글꼴 크기로 통일해서** SHIP FROM과 같은 모양으로 써 넣는다.

    2026-09-15 사용자 지적("글씨도 더 작고 박스 안에 들어오지도 않는데"):
    예전엔 칸마다 따로 _insert_address_block()을 불러서 칸별 내용 길이에 맞춰
    독립적으로 폰트를 줄였다 - CHP처럼 정식 회사명이 유독 길면(Bill To 9줄
    Ship To 7줄, 같은 긴 회사명 줄 포함) Bill To는 6.75pt, Ship To는 6.5pt로
    서로 다르게, 게다가 Ship From(9pt)보다 훨씬 작게 찍혔다. 이제는:
    1) 칸 폭을 넘는 줄은 폰트를 줄이기 전에 먼저 단어 단위로 줄바꿈하고
       (_wrap_address_line) - Ship From과 같은 9pt를 최대한 유지한다.
    2) 그래도 다 줄바꿈한 뒤 줄 수가 제일 많은 칸 기준으로, 모든 칸에 같은
       줄간격/폰트를 적용한다 - 칸끼리 크기가 달라지는 일이 없다.
    style=(fontname, fontsize, step)을 안 주면 2026-08-06 실측값(Helvetica
    9pt, 줄간격 10.4pt)으로 폴백한다 - 보통은 _get_ship_from_style(page)로
    실측한 값을 넘긴다. 한 줄 안에 영문과 한자가 섞여 있으면 런 단위로 폰트를
    나눠 찍는다(_split_address_runs)."""
    import fitz

    blocks = [b for b in blocks if b[1]]
    if not blocks:
        return
    base_fontname, base_fontsize, base_step = style or ("helv", 9.0, 10.4)

    prepared = []  # (label_rect, line_runs, max_w)
    max_lines = 1
    for label_rect, lines, x_right in blocks:
        max_w = max(x_right - label_rect.x0 - 2, 40)
        wrapped = []
        for l in lines:
            wrapped.extend(_wrap_address_line(fitz, l, base_fontname, base_fontsize, max_w))
        line_runs = [_split_address_runs(l, base_fontname) for l in wrapped]
        prepared.append((label_rect, line_runs, max_w))
        max_lines = max(max_lines, len(line_runs))

    # 모든 칸이 같은 라벨 행(BILL TO:/SHIP TO:는 같은 y0)에서 시작해 같은
    # y_bottom까지 쓰므로 세로 여유는 공통이다 - 줄 수가 제일 많은 칸 기준으로
    # 줄간격을 정하면 모든 칸에 그대로 적용해도 넘치지 않는다.
    first_baseline = blocks[0][0].y1 + 7.6
    avail_h = y_bottom - first_baseline
    step = base_step
    if avail_h / max_lines < step:
        step = max(6.0, avail_h / max_lines)
    fontsize = min(base_fontsize, step * 0.87)

    while fontsize > 5.0 and any(
        line_runs and max(_address_run_width(fitz, runs, fontsize) for runs in line_runs) > max_w
        for _, line_runs, max_w in prepared
    ):
        fontsize -= 0.25

    for label_rect, line_runs, _ in prepared:
        for i, runs in enumerate(line_runs):
            x = label_rect.x0
            y = first_baseline + i * step
            for chunk, fontname in runs:
                if not chunk:
                    continue
                page.insert_text((x, y), chunk, fontsize=fontsize, fontname=fontname,
                                 color=(0, 0, 0))
                try:
                    x += fitz.get_text_length(chunk, fontname=fontname, fontsize=fontsize)
                except Exception:
                    x += len(chunk) * fontsize * 0.6


def patch_bill_ship_to_and_hts_in_pdf(
    pdf_path: str, country_code: str, hts_by_part: dict | None = None
) -> str:
    """오라클이 생성한 Commercial Invoice PDF에서:
    1. BILL TO / SHIP TO 칸의 주소를 **목적지 국가 주소로 통째 교체**.
    2. 각 품목 행의 HTS Code 칸(원래 비어 있음)에 파트별 값을 채움.
    3. footer의 오라클 Process ID(3pt 숫자) 제거.
    주소는 `Rebalance Invoice form_Ship from Korea_excel.xlsx`의 국가 시트에서
    뽑는다(get_country_address_lines 참고).

    **2026-08-06 전면 수정(사용자 지적: "왜 나라별로 반영 안한거야")**: 예전
    구현은 미국 주소를 그대로 두고 그 아래에 담당자 이름/전화만 덧붙였다.
    ICBL Print Commercial Invoice는 목적지와 무관하게 Bill To/Ship To를 항상
    미국(CANDELA CORPORATION, Marlborough MA)으로 출력하므로, 홍콩(ILH)/일본
    (JPP)행 인보이스가 미국 주소를 그대로 달고 나가 버렸다(8/6 3건 실측 확인).
    게다가 덧붙인 담당자 줄도 insert_textbox 높이가 부족해 조용히 잘려서
    JPP는 이름("Remi")만 찍혀 있었다. 이제는 표 괘선 안쪽을 지우고(redaction)
    국가 시트의 주소 블록 전체를 원본과 같은 서체로 다시 쓴다.

    **2026-08-05 TO 7866440(US 시트)으로 검증한 원칙은 유지** - Excel을 다시
    출력하지 않고 오라클 원본 PDF에 직접 손대는 방식(Excel 재출력 경로는
    인쇄영역/컬럼폭이 달라져 Part Number/REMIT TO가 잘림)."""
    import fitz

    bill_lines = get_country_address_lines(country_code, "bill_to") or []
    ship_lines = get_country_address_lines(country_code, "ship_to") or []

    doc = fitz.open(pdf_path)
    page = doc[0]

    def _label_rect(label):
        found = page.search_for(label)
        return found[0] if found else None

    bill_label = _label_rect("BILL TO:")
    ship_label = _label_rect("SHIP TO:")
    payment_label = _label_rect("PAYMENT TERMS")
    if not (bill_label and ship_label and payment_label):
        raise RuntimeError(
            f"CI PDF에서 BILL TO/SHIP TO/PAYMENT TERMS 라벨을 못 찾음 - 레이아웃이 "
            f"바뀐 것으로 보임(수동 확인 필요): {pdf_path}"
        )

    # 표 칸 아래쪽 경계: PAYMENT TERMS 섹션 시작선 위까지가 주소 칸이다. 주소
    # 칸의 아래 괘선이 y=287.8 부근(PAYMENT TERMS y0 - 10.5)에 있어서, 지우는
    # 영역이 그 선을 덮지 않도록 13pt 위에서 끊는다(선까지 하얗게 덮으면 표가
    # 깨진다 - 괘선 자체는 graphics 옵션으로 보존하지만 흰색 fill이 가릴 수 있음).
    y_bottom = payment_label.y0 - 13
    targets = []
    if bill_lines:
        targets.append((bill_label, bill_lines))
    if ship_lines:
        targets.append((ship_label, ship_lines))

    _redact_options = dict(
        images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
        graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
    )

    # 0) 오라클이 TOTAL 아래 우측에 3pt로 박아넣는 Process ID(리포트 실행번호,
    #    예 48953708) 제거 - 2026-08-06 사용자 지시("숫자 지우는 게 나아").
    #    거래처엔 의미 없는 내부 실행번호이고, 서류 추적은 인보이스에 크게 찍히는
    #    Delivery Number + rebalance_watcher.log의 Process 기록으로 충분하다.
    #    모든 페이지 footer에 반복해서 들어가므로 페이지마다 훑는다.
    removed = 0
    for pg in doc:
        hits = []
        for blk in pg.get_text("dict")["blocks"]:
            if blk.get("type") != 0:
                continue
            for ln in blk["lines"]:
                for sp in ln["spans"]:
                    text = sp["text"].strip()
                    # 3pt 크기의 순수 숫자 6자리 이상만 - '( KRW )' 같은 작은
                    # 라벨이나 금액(₩/쉼표 포함)은 대상에서 빠진다.
                    if sp["size"] < 5.0 and text.isdigit() and len(text) >= 6:
                        hits.append(fitz.Rect(sp["bbox"]))
        for r in hits:
            pg.add_redact_annot(fitz.Rect(r.x0 - 1, r.y0 - 1, r.x1 + 1, r.y1 + 1), fill=(1, 1, 1))
        if hits:
            pg.apply_redactions(**_redact_options)
            removed += len(hits)
    if removed:
        log(f"[CI] 오라클 Process ID 표기 {removed}개 제거")

    # 1) 기존 주소(+예전 버전이 덧붙여 놓은 담당자 줄)를 지운다. 괘선/로고까지
    #    지워지면 레이아웃이 깨지므로 텍스트만 제거하도록 옵션을 명시한다.
    for label, _lines in targets:
        left, right = _cell_bounds_from_rules(page, label)
        rect = fitz.Rect(left + 1.5, label.y1 + 0.5, right - 1.5, y_bottom)
        page.add_redact_annot(rect, fill=(1, 1, 1))
    if targets:
        page.apply_redactions(**_redact_options)

    # 2) 국가별 주소 블록을 SHIP FROM과 같은 위치/서체로, 두 칸이 서로 다른
    #    크기가 되지 않게 함께 계산해서 다시 쓴다(2026-09-15 사용자 지시:
    #    "폰트를 Ship From에 사용하는 폰트로 모두 통일" + "글씨가 더 작고
    #    박스 안에 들어오지도 않는다" 지적).
    ship_from_style = _get_ship_from_style(page)
    blocks = [(label, lines, _cell_bounds_from_rules(page, label)[1]) for label, lines in targets]
    _insert_address_blocks(page, blocks, y_bottom, style=ship_from_style)

    # 3) HTS Code - 파트가 여러 개인 TO도 모든 행을 채운다(예전엔 첫 파트만).
    hts_header = _label_rect("HTS")
    for part_no, hts_code in (hts_by_part or {}).items():
        if not (part_no and hts_code and hts_header):
            continue
        part_rects = page.search_for(str(part_no))
        if not part_rects:
            log(f"[경고] CI PDF에서 파트 {part_no} 행을 못 찾아 HTS Code 미기입")
            continue
        y = part_rects[0].y1 - 2
        # 같은 자리에 이미 값이 있으면(재패치) 겹쳐 쓰지 않는다.
        cell = fitz.Rect(hts_header.x0 - 2, y - 9, hts_header.x0 + 40, y + 2)
        if page.get_textbox(cell).strip():
            continue
        # 2026-08-18: RMA 고정 코드는 "9801.00.1090"처럼 점이 들어가 기존 10자리
        # 숫자보다 길다 - 칸(HTS ~ QUANTITY 사이 약 44pt)을 넘칠 때만 폰트를
        # 줄인다(기존 10자리 코드는 36pt라 6.5pt 그대로 유지된다).
        hts_size = 6.5
        try:
            while hts_size > 5.0 and fitz.get_text_length(
                    str(hts_code), fontname="helv", fontsize=hts_size) > 44:
                hts_size -= 0.25
        except Exception:
            pass
        page.insert_text((hts_header.x0, y), str(hts_code), fontsize=hts_size,
                         fontname="helv", color=(0, 0, 0))

    patched_path = pdf_path[:-4] + "_patched.pdf"
    doc.save(patched_path)
    doc.close()
    return patched_path


# ==============================================================
# 12-2) RMA 전용 - 인보이스 금액 10% 적용 (2026-08-18 추가)
# ==============================================================
# 오라클 CI는 정가로 나온다. RMA(반송품)는 기존 수출 CI 생성기
# (12. 수출\ci_invoice_html.py, RMA_PRICE_RATIO=0.10)와 같은 규칙으로
# **단가 / 품목별 금액(EXTENSION) / SUBTOTAL / TOTAL 전부**에 10%를 적용한다
# (사용자 확인 2026-08-18: "물품별 가격 물품 총 가격 모든 물품 총 가격이
# 원래 CI에 10%").
#
# 실측한 금액 표기 2종(2026-08-18 - 오라클 리포트가 같은 화면에서 뽑아도
# 표기가 다를 수 있으니 둘 다 다뤄야 한다):
#   (a) KRP-ILH 9971969 / KRP-JPP 9969124: 통화기호 span('₩', Go Noto)과
#       숫자 span('1,019,904', Helvetica)이 **따로** 그려진다.
#   (b) TO 7672306 재출력분(2026-08-18, 라벨이 한국어로 나온 인쇄분 -
#       "송금 :"/"본선 인도"): '₩ 7,197,315'처럼 **한 span에 통화기호와 숫자가
#       같이** 들어간다.
# 그래서 span 텍스트만 보고 자르지 않고 **문자 단위 bbox(rawdict)**로 숫자
# 부분만 골라 지운다 - ₩ 글리프는 건드리지 않으니 통화기호 폰트 문제도 없다.
# 숫자는 오른쪽 정렬이라 새 값도 같은 오른쪽 끝(x1)에 맞춰 다시 쓴다.
# 품목 행은 8pt, SUBTOTAL/TOTAL은 9pt이고, 품목이 많으면 페이지가 넘어가
# 총계만 마지막 장에 오기도 한다(그래서 전 페이지를 훑는다).
_MONEY_SPAN_PATTERN = re.compile(
    r"^(?P<won>₩\s*)?(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?)$")


def _span_text(sp: dict) -> str:
    """rawdict/dict 어느 쪽 span이 와도 텍스트를 돌려준다."""
    if sp.get("chars"):
        return "".join(c["c"] for c in sp["chars"])
    return sp.get("text", "")


def _collect_money_spans(page, ratio: float) -> list[dict]:
    """이 페이지의 금액을 찾아 (지울 영역/새 값/기준선/왼쪽 한계)로 돌려준다.
    통화기호 바로 뒤에 붙은 숫자만 금액으로 인정하므로 Tracking#/우편번호/
    수량 같은 다른 숫자는 걸리지 않는다."""
    import fitz

    found = []
    for blk in page.get_text("rawdict")["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk["lines"]:
            spans = [s for s in ln["spans"] if _span_text(s).strip()]
            for i, sp in enumerate(spans):
                txt = _span_text(sp).strip()
                m = _MONEY_SPAN_PATTERN.match(txt)
                if not m:
                    continue
                chars = sp.get("chars") or []
                won_chars = [c for c in chars if c["c"] == "₩"]
                if m.group("won"):
                    left_limit = max(c["bbox"][2] for c in won_chars) if won_chars else sp["bbox"][0]
                else:
                    # (a) 형태 - 바로 앞 span이 통화기호일 때만 금액으로 본다.
                    prev = spans[i - 1] if i else None
                    if not (prev and "₩" in _span_text(prev)
                            and -0.5 <= sp["bbox"][0] - prev["bbox"][2] <= 3.0):
                        continue
                    left_limit = prev["bbox"][2]
                digits = [c for c in chars if c["c"].isdigit() or c["c"] in ",."]
                if not digits:
                    continue
                x0 = min(c["bbox"][0] for c in digits)
                x1 = max(c["bbox"][2] for c in digits)
                found.append({
                    "rect": fitz.Rect(x0, sp["bbox"][1], x1, sp["bbox"][3]),
                    "origin_y": sp["origin"][1],
                    "size": sp["size"],
                    "left_limit": left_limit,
                    "old": txt,
                    "new": _format_money_number(
                        float(m.group("num").replace(",", "")) * ratio),
                })
    return found


def _format_money_number(value: float) -> str:
    """원본 표기(1,019,904)와 같은 천단위 구분 형식으로 되돌린다.
    0.1배는 소수점 한 자리면 항상 정확히 표현되므로(원본이 정수인 경우),
    불필요한 0은 떼고 필요한 만큼만 소수를 남긴다 - 이렇게 해야 단가/금액/
    합계가 서로 정확히 맞아떨어진다(반올림하면 합계가 1원씩 어긋난다)."""
    s = f"{value:,.4f}".rstrip("0").rstrip(".")
    return s or "0"


def _insert_rma_customs_note(doc, note: str = RMA_CUSTOMS_NOTE) -> bool:
    """품목 표 아래 안내문 다음의 빈 칸에 통관 문구를 써 넣는다(4월 수기
    인보이스와 같은 위치/문장).

    좌표를 고정하지 않는 이유(2026-08-18 실측): 품목이 몇 줄이냐에 따라 이
    영역이 통째로 내려가고, 품목이 많으면 **안내문과 총계가 서로 다른 페이지로
    갈라진다**(TO 7672306 재출력분은 4페이지 - 안내문은 3페이지, SUBTOTAL은
    4페이지 맨 위). 그래서 안내문("All items shipped...")이 있는 페이지를
    우선 대상으로 잡고, 없으면 SUBTOTAL이 있는 페이지에 넣는다. 아래 경계는
    같은 페이지의 SUBTOTAL / 오라클이 3pt로 박는 footer / 페이지 하단 중
    가장 위를 쓴다."""
    import fitz

    page = None
    for p in doc:
        if p.search_for("All items shipped"):
            page = p
            break
    if page is None:
        for p in doc:
            if p.search_for("SUBTOTAL"):
                page = p
                break
    if page is None:
        return False

    limits = [page.rect.height - 30]
    subtotal = page.search_for("SUBTOTAL")
    if subtotal:
        limits.append(subtotal[0].y0 - 4)

    # 본문 글자(6pt 이상)만 기준선 후보로 쓰고, 페이지 맨 아래 여백에 3pt로
    # 박힌 오라클 Process ID는 "그 위까지"라는 아래 경계로만 쓴다.
    # **주의(2026-08-18 실측 함정)**: "작은 글자 = footer"로 잡으면 이 함수가
    # 돌기 전에 우리가 HTS 칸에 써넣은 작은 글자(칸 폭에 맞춰 5.75pt까지 줄어듦)
    # 까지 footer로 오인해서 아래 경계가 표 중간으로 올라가고 문구가 아예 안
    # 들어간다. 그래서 footer는 예전부터 쓰던 신호(숫자만 6자리 이상 + 페이지
    # 하단 여백)로만 인정한다.
    body_spans = []
    for blk in page.get_text("dict")["blocks"]:
        if blk.get("type") != 0:
            continue
        for ln in blk["lines"]:
            for sp in ln["spans"]:
                text = sp["text"].strip()
                if not text:
                    continue
                if sp["size"] >= 6:
                    body_spans.append(sp)
                elif (text.isdigit() and len(text) >= 6
                      and sp["bbox"][1] > page.rect.height * 0.85):
                    limits.append(sp["bbox"][1] - 4)
    bottom_limit = min(limits)

    # 왼쪽 칼럼(x<380)의 본문 중 아래 경계 위에 있는 가장 마지막 줄.
    tops = [sp["bbox"][3] for sp in body_spans
            if sp["bbox"][0] < 380 and sp["bbox"][3] < bottom_limit]
    if not tops:
        return False
    top = max(tops)

    fontsize, step = 8.0, 9.2
    max_w = 520.0
    words, lines, cur = note.split(), [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        try:
            too_wide = fitz.get_text_length(cand, fontname="helv", fontsize=fontsize) > max_w
        except Exception:
            too_wide = len(cand) > 100
        if too_wide and cur:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)

    # 위 안내문과 한 줄 띄워 별개 문단으로 보이게 한다(붙여 쓰면 안내문의
    # 이어지는 줄처럼 읽힌다 - 2026-08-18 렌더 확인 후 조정).
    gap = 11.0
    available = bottom_limit - top - gap
    if available < (len(lines) - 1) * step + 4:
        gap = 8.0
        available = bottom_limit - top - gap
        if available < (len(lines) - 1) * step + 4:
            return False
    if len(lines) > 1 and available < (len(lines) - 1) * step + 4:
        step = max(6.0, available / len(lines))
        fontsize = min(fontsize, step * 0.87)

    # 안내문 블록의 x0(=36.0 실측)에 맞춰 왼쪽 정렬.
    anchor = page.search_for("All items shipped")
    x = anchor[0].x0 if anchor else 36.0
    for i, line in enumerate(lines):
        page.insert_text((x, top + gap + i * step), line, fontsize=fontsize,
                         fontname="helv", color=(0, 0, 0))
    return True


def apply_rma_invoice_rules_in_pdf(pdf_path: str, ratio: float = RMA_PRICE_RATIO,
                                   hts_code: str | None = RMA_HTS_CODE) -> str:
    """CI PDF에 RMA 전용 규칙 3가지를 적용한다.
    1. 인쇄된 모든 금액(단가/품목별 금액/SUBTOTAL/TOTAL)에 ratio를 곱해 다시 쓴다.
    2. **모든 품목 행**의 HTS Code 칸을 hts_code로 덮어쓴다.
    3. 품목 표 아래 빈 칸에 통관 문구(RMA_CUSTOMS_NOTE)를 넣는다.

    **HTS를 여기서 처리하는 이유(2026-08-18)**: 주소 패치 함수
    (patch_bill_ship_to_and_hts_in_pdf)의 HTS 기입은 파트넘버를 찾아 그 **첫
    행 하나만**, 그것도 **1페이지에서만** 채운다. Rebalance는 품목이 1~2줄이라
    문제가 없었지만, RMA는 같은 파트가 S/N별로 여러 줄로 나오고 4페이지까지
    이어지며(TO 7672306: 28줄/4페이지) 오라클이 이미 자기 코드(9018.90.8000)를
    찍어둔 행도 섞여 있다. 그래서 RMA는 그 함수에 HTS를 넘기지 않고, 여기서
    "금액이 있는 줄 = 품목 행"을 기준으로 전 페이지·전 행을 덮어쓴다.

    금액을 하나도 못 찾으면 예외를 낸다 - 정가 그대로인 RMA 인보이스가
    조용히 나가는 것이 이 함수가 막아야 할 가장 큰 사고다. 반면 문구 삽입은
    실패해도(빈 칸이 부족한 등) 경고만 남기고 진행한다 - 금액/주소/HTS가 맞는
    서류를 문구 하나 때문에 통째로 막지는 않는다(사람이 알림을 보고 채울 수 있다)."""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        # HTS 칸의 x좌표는 헤더가 있는 첫 페이지에서만 얻을 수 있다(이어지는
        # 페이지에는 표 헤더가 다시 그려지지 않는다 - 컬럼 위치는 동일하다).
        # 칸 좌우 경계(세로 괘선)까지 재둔다 - 실측(2026-08-18) HTS 칸은
        # x=422.4~460.6(폭 38pt)인데 6.5pt로 "9801.00.1090"을 쓰면 39.8pt라
        # 옆 칸(ORDERED)을 넘어간다. 칸 안에 들어오도록 폭에 맞춰 줄인다.
        hts_x = hts_left = hts_right = None
        for page in doc:
            hdr = page.search_for("HTS")
            if hdr:
                hts_x = hdr[0].x0
                try:
                    left, right = _cell_bounds_from_rules(page, hdr[0])
                    # 괘선을 못 찾으면 이 함수가 넓은 기본값을 돌려주므로,
                    # 칸 하나로 볼 수 있는 폭일 때만 채택한다(안 그러면 지우는
                    # 영역이 수량/금액 칸까지 덮는다).
                    if 12 < right - left < 60:
                        hts_left, hts_right = left, right
                except Exception:
                    pass
                break
        if hts_left is None and hts_x is not None:
            hts_left, hts_right = hts_x - 6, hts_x + 42

        money_by_page: dict[int, list[dict]] = {}
        rows_by_page: dict[int, list[float]] = {}
        for pno, page in enumerate(doc):
            money = _collect_money_spans(page, ratio)
            if not money:
                continue
            money_by_page[pno] = money
            subtotal = page.search_for("SUBTOTAL")
            totals_y = subtotal[0].y0 if subtotal else None
            # 품목 행 = 금액이 찍힌 줄 중 **같은 줄 왼쪽(SO NO. 칸)에 글자가 있는**
            # 줄. SUBTOTAL 라벨 위인지로만 걸렀더니, 품목이 많아 **총계 라벨과 금액이
            # 다른 페이지로 갈라진 케이스**(KRP-JPP 9969124: 라벨은 1페이지,
            # 금액은 2페이지)에서 총계 줄을 품목으로 오인해 그 옆에 HTS를 찍었다
            # (2026-08-18 실측으로 발견). 총계 줄은 왼쪽 칸이 비어 있어 확실히 걸러진다.
            left_baselines = []
            for blk in page.get_text("dict")["blocks"]:
                if blk.get("type") != 0:
                    continue
                for ln in blk["lines"]:
                    for sp in ln["spans"]:
                        if sp["text"].strip() and sp["bbox"][0] < 120 and sp["size"] >= 6:
                            left_baselines.append(sp["origin"][1])
            rows = {round(m["origin_y"], 1) for m in money
                    if (totals_y is None or m["origin_y"] < totals_y)
                    and any(abs(m["origin_y"] - b) <= 3 for b in left_baselines)}
            if rows:
                rows_by_page[pno] = sorted(rows)

        if not money_by_page:
            raise RuntimeError(
                f"CI PDF에서 금액(₩) 항목을 하나도 못 찾아 RMA {ratio:.0%} 적용에 실패함 - "
                f"정가 그대로 나가지 않도록 중단함: {pdf_path}")

        _redact_options = dict(
            images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
            graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
        )
        changed = hts_filled = 0
        for pno, money in money_by_page.items():
            page = doc[pno]
            for m in money:
                r = m["rect"]
                page.add_redact_annot(
                    fitz.Rect(r.x0 - 0.3, r.y0 - 0.6, r.x1 + 0.6, r.y1 + 0.6), fill=(1, 1, 1))
            if hts_code and hts_left is not None:
                for y in rows_by_page.get(pno, []):
                    # 오라클이 이미 찍어둔 코드(칸이 좁아 두 줄로 접힌 경우 포함)까지
                    # 칸 안에서만 지운다(괘선은 graphics 옵션으로 보존).
                    page.add_redact_annot(
                        fitz.Rect(hts_left + 0.8, y - 9.5, hts_right - 0.8, y + 13),
                        fill=(1, 1, 1))
            page.apply_redactions(**_redact_options)

            for m in money:
                size = m["size"]
                avail = m["rect"].x1 - m["left_limit"] - 0.6
                try:
                    while size > 5.5 and fitz.get_text_length(
                            m["new"], fontname="helv", fontsize=size) > avail:
                        size -= 0.25
                    width = fitz.get_text_length(m["new"], fontname="helv", fontsize=size)
                except Exception:
                    width = len(m["new"]) * size * 0.5
                # 원본과 같은 오른쪽 정렬을 유지한다.
                page.insert_text((m["rect"].x1 - width, m["origin_y"]), m["new"],
                                 fontsize=size, fontname="helv", color=(0, 0, 0))
                changed += 1

            if hts_code and hts_left is not None:
                max_w = hts_right - hts_left - 3
                size = 6.5
                try:
                    while size > 4.5 and fitz.get_text_length(
                            str(hts_code), fontname="helv", fontsize=size) > max_w:
                        size -= 0.25
                except Exception:
                    pass
                for y in rows_by_page.get(pno, []):
                    page.insert_text((hts_left + 1.5, y), str(hts_code), fontsize=size,
                                     fontname="helv", color=(0, 0, 0))
                    hts_filled += 1

        note_done = _insert_rma_customs_note(doc)

        out_path = pdf_path[:-4] + "_rma.pdf"
        doc.save(out_path)
    finally:
        doc.close()
    log(f"[CI] RMA 규칙 적용: 금액 {ratio:.0%}로 {changed}개 수정, "
        f"HTS {hts_code} {hts_filled}행 기입, 통관 문구 "
        f"{'삽입' if note_done else '미삽입'} -> {os.path.basename(out_path)}")
    if not note_done:
        log("[경고] CI PDF에 통관 문구를 넣을 빈 칸을 못 찾음 - 최종 PDF에 직접 "
            "추가해주세요(금액/주소/HTS는 정상 적용됨)")
    return out_path


def _read_country_block_rows(country_code: str, block: str) -> list[str] | None:
    """국가 시트의 BILL TO(A열)/SHIP TO(M열) 블록 줄들을 위에서 아래로 읽는다.
    라벨("BILL TO:")은 9행이고 실제 주소/담당자는 10행부터인데, **시트마다
    길이가 달라 ILH/CHP는 17행, JPP/CHP는 18행까지 내려간다** - 예전 코드가
    range(9, 17)로 잘라 읽어서 ILH는 이메일이, JPP는 전화/이메일이 통째로
    빠졌다(2026-08-06 실측 확인). 다음 섹션(20행 PAYMENT TERMS/SALESPERSON)을
    만나면 멈춘다. 중간에 빈 줄이 있는 시트(JPP A13)가 있어 "첫 빈 줄에서 중단"
    방식은 쓸 수 없다."""
    import openpyxl

    sheet_name = COUNTRY_SHEET_MAP.get(country_code)
    if sheet_name is None:
        return None
    try:
        wb = openpyxl.load_workbook(REBALANCE_INVOICE_TEMPLATE_PATH, data_only=True, read_only=True)
    except Exception as e:
        log(f"[경고] Rebalance Invoice 템플릿 조회 실패: {e}")
        return None
    if sheet_name not in wb.sheetnames:
        log(f"[경고] Rebalance Invoice 템플릿에 '{sheet_name}' 시트가 없음")
        return None
    ws = wb[sheet_name]
    col = 1 if block == "bill_to" else 13  # A열=1, M열=13

    stop_words = ("PAYMENT TERMS", "SALESPERSON", "SO NO.")
    lines = []
    for row in range(10, 20):
        v = ws.cell(row=row, column=col).value
        if v is None or str(v).strip() == "":
            continue
        s = str(v).strip()
        if s.upper() in ("BILL TO:", "SHIP TO:"):
            continue
        if s.upper() in stop_words:
            break
        lines.append(s)
    return lines or None


def get_country_address_lines(country_code: str, block: str) -> list[str] | None:
    """국가 시트의 BILL TO/SHIP TO 블록 **전체**(회사명/주소/국가/담당자까지)를
    반환한다. patch_bill_ship_to_and_hts_in_pdf()가 ICBL 출력의 미국 주소를
    이 값으로 통째 교체한다(2026-08-06 추가).

    실측 예: ILH -> ['Syneron Medical (HK) limited _ Office',
    'Room 3711 Hopewell centre 183', 'Queens Road East Wah Chai', '40',
    'Hong Kong', 'Nick', '(852) 61082366', 'nick.li@candelamedical.com']

    2026-09-15 수정(사용자 지적): CHP 시트 SHIP TO 끝의 한자 회사명/주소 두 줄
    (영문 줄과 중복 내용)은 CI에 필요 없고, 있으면 그 줄 때문에 폰트가
    Ship From/Bill To와 달라져 보인다("86으로 시작하는 전화번호까지만 있으면
    됨"). 한자(CJK 통합 한자, U+4E00-9FFF)가 포함된 줄만 걸러낸다 - Address
    줄의 전각 콤마(，, U+FF0C)는 한자가 아니라 문장부호라 안 걸린다.

    **같은 날 추가 수정(용마에 보낸 뒤 실측 확인)**: 한자 줄을 걸러내도 Address
    줄에 전각 콤마 하나가 남아 있으면, 그 글자 하나 때문에 PDF에 china-s(Heiti,
    UniGB-UTF16-H) 폰트가 여전히 참조로 남는다. 이 폰트는 실제 글리프가
    임베딩되지 않은 채 뷰어의 시스템 CJK 폰트에 기대는 방식이라, Acrobat
    Reader가 "이 페이지를 올바르게 표시하려면 글꼴 패키지가 필요합니다" 팝업을
    띄우고 Bill To/Ship To 내용이 아예 안 보이며 인쇄까지 막혔다(실측:
    KRP-CHP 9980515.pdf, Acrobat). 한자 줄을 이미 제거한 이상 전각 문장부호도
    ASCII로 정규화해서 china-s 참조 자체를 없앤다."""
    lines = _read_country_block_rows(country_code, block)
    if not lines:
        return lines
    lines = [l for l in lines if not any('一' <= ch <= '鿿' for ch in l)]
    punct_map = str.maketrans({
        "，": ",", "。": ".", "！": "!", "？": "?", "：": ":", "；": ";",
        "（": "(", "）": ")", "　": " ",
    })
    return [l.translate(punct_map) for l in lines]


def get_country_contact_lines(country_code: str, block: str) -> list[str] | None:
    """Rebalance Invoice 템플릿의 국가 시트에서 BILL TO(A열)/SHIP TO(M열) 블록의
    마지막 담당자 정보 줄(이름/이메일/전화)만 뽑는다. icbl_ci_watcher.py의
    get_ship_from_address_lines()와 반대 방향(그쪽은 연락처를 "잘라내고" 주소만
    남기고, 이건 연락처만 남기고 주소는 버림) - 끝에서부터 이메일(@ 포함) ->
    전화번호(숫자/공백/괄호/+/- 만) -> 이름(숫자 없는 1~2단어) 순서로 만나는
    만큼만 채택한다.

    block: 'bill_to'(A열, BILL TO 아래) 또는 'ship_to'(M열, SHIP TO 아래).
    2026-08-05 US 시트로 검증: bill_to -> ['Robert Lazaros',
    'robertl@candelamedical.com', '(1)508-3580483'], ship_to ->
    ['Attn: Bob Lazaros', 'robertl@candelamedical.com ', '(1)508-3580483'].

    2026-08-06: 주소 블록 전체 교체 방식으로 바뀌면서 파이프라인에서는 더 쓰지
    않지만(patch_bill_ship_to_and_hts_in_pdf가 get_country_address_lines를 씀)
    다른 용도로 남겨둔다. 시트 읽기는 _read_country_block_rows로 통일했다 -
    예전에 직접 range(9, 17)로 읽던 부분이 ILH/JPP의 마지막 줄을 빠뜨리던
    버그의 원인이었다."""
    lines = _read_country_block_rows(country_code, block)
    if not lines or len(lines) < 2:
        return None

    # 2026-08-05 실측 정정: icbl_ci_watcher.py의 get_ship_from_address_lines()는
    # "이름/전화/이메일"(이메일이 마지막) 순서를 가정하는데, 이 Bill To/Ship To
    # 템플릿은 실제로 "이름/이메일/전화"(전화가 마지막) 순서였음(US 시트로 직접
    # 검증) - 그래서 여기는 전화 -> 이메일 -> 이름 순으로 뒤에서부터 뗀다.
    contact = []
    rest = list(lines)
    if rest and any(c.isdigit() for c in rest[-1]) and re.sub(r"[\d\s()+\-]", "", rest[-1]) == "":
        contact.insert(0, rest.pop())
    if rest and "@" in rest[-1]:
        contact.insert(0, rest.pop())
    if rest and len(rest[-1].split()) <= 3 and not any(c.isdigit() for c in rest[-1]) and rest[-1] not in ("BILL TO:", "SHIP TO:"):
        contact.insert(0, rest.pop())
    return contact or None


def lookup_hts_code(part_no: str) -> str | None:
    """수입신고실적(20260211)자동화.xlsx에서 이 파트의 HS code를 찾는다(과거
    수입 때 이미 분류된 코드를 재사용). 못 찾으면 None(호출부가 사람에게 물어야
    함 - 파트마다 다른 값이라 하나의 기본값으로 대체할 수 없음, 2026-08-05
    사용자 확인: "이 파일에 없으면 9018.90.9000이야"는 5108-06-0403 이 건에
    한정된 값이었지 범용 기본값이 아니었음)."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(IMPORT_DECLARATION_PATH, data_only=True, read_only=True)
    except Exception as e:
        log(f"[경고] 수입신고실적 파일 조회 실패: {e}")
        return None
    # **2026-08-06 버그 수정(사용자가 발견)**: 예전 코드는 파트가 들어있는 행에서
    # "8자리 이상 숫자 셀 중 첫 번째"를 HS code로 반환했다. 그런데 이 파일의 컬럼
    # 순서가 [4]B/L번호 -> [5]신고번호 -> [6]Hs code 라서, 실제로는 **B/L(AWB)
    # 번호가 먼저 걸린다**(실측: 7123-00-0039 -> 887140998335, 12자리 AWB).
    # 수출 서류의 HS code 칸에 엉뚱한 번호가 들어갈 수 있었던 위험한 버그다.
    # -> 헤더 이름으로 'Hs code' 컬럼을 찾고, 파트 매칭도 아무 셀이 아니라
    # '자재코드' 컬럼에서만 한다.
    ws = wb.active
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

    hs_idx = _col("Hs code", "HS code", "HScode")
    part_idx = _col("자재코드")
    if hs_idx is None or part_idx is None:
        log(f"[경고] 수입신고실적에서 컬럼을 못 찾음(Hs code={hs_idx}, 자재코드={part_idx}) "
            f"- HS code 조회 생략")
        return None

    for row in ws.iter_rows(min_row=2, values_only=True):
        if part_idx >= len(row) or hs_idx >= len(row):
            continue
        cell_part = row[part_idx]
        if cell_part is None or str(cell_part).strip() != str(part_no).strip():
            continue
        hs = row[hs_idx]
        if hs is None or not str(hs).strip():
            continue
        hs = str(int(hs)) if isinstance(hs, (int, float)) else str(hs).strip()
        digits = "".join(ch for ch in hs if ch.isdigit())
        # 한국 HS code는 10자리다. 자리수가 다르면 잘못 읽은 것으로 보고 쓰지 않는다.
        if len(digits) != 10:
            log(f"[경고] 파트 {part_no}의 Hs code 값이 10자리가 아님({hs!r}) - 사용하지 않음")
            continue
        return digits
    return None


# ==============================================================
# 13) 수출신고실적 append (완전 구현)
# ==============================================================
def parse_invoice_items_from_pdf(pdf_path: str, part_numbers: list[str]) -> dict:
    """CI PDF의 품목 행에서 자재명/원산지/수량/단가/금액을 읽어온다.

    **2026-08-06 추가(사용자 지적: 수출신고실적의 자재명/단가/금액 칸이 비어
    있음)**: SharePoint 조회 결과(lookup_to_lines_via_sharepoint)는 파트넘버와
    수량만 주므로 parts_qty에 description/unit_price/amount 키가 아예 없었고,
    append_export_declaration의 `p.get("description")`이 전부 None으로 들어갔다.
    이 값들은 인보이스에 이미 다 찍혀 있으니 오라클 PDF에서 그대로 읽어 쓴다
    (다른 곳에서 다시 조회하면 인보이스와 어긋날 수 있어 인보이스를 단일
    출처로 삼는다).

    실측 블록 형식(2026-08-06, TO 7870361):
      '7870361\\n1\\n7123-00-0058     ASSY, HANDPIECE, RESOLVE, 532   \\nMX\\n1\\n0
       \\n1\\n₩4,060,696\\n₩4,060,696'
      = [SO NO, SO LINE, '파트넘버  자재명', 원산지, ORDERED, BACK ORD, SHIPPED,
         단가, 금액] (자재명이 길면 다음 줄로 접힘)

    반환: {part_no: {"description", "origin", "qty", "unit_price", "amount"}}"""
    import fitz

    def _num(tok: str):
        t = str(tok).replace("₩", "").replace(",", "").replace("KRW", "").strip()
        try:
            return float(t)
        except ValueError:
            return None

    def _segs(block):
        return [s.strip() for s in str(block[4] or "").split("\n") if s.strip()]

    pages_blocks = []
    doc = fitz.open(pdf_path)
    try:
        for page in doc:
            pages_blocks.append(page.get_text("blocks"))
    finally:
        doc.close()

    result = {}
    for part_no in part_numbers:
        if not part_no:
            continue
        hit = None
        for blocks in pages_blocks:
            for b in blocks:
                segs = _segs(b)
                idx = next((i for i, s in enumerate(segs) if s.startswith(str(part_no))), None)
                if idx is not None:
                    hit = (blocks, b, segs, idx)
                    break
            if hit:
                break
        if not hit:
            log(f"[경고] CI PDF에서 파트 {part_no} 행을 못 찾음 - 자재명/단가/금액 미기입")
            continue

        blocks, b, segs, idx = hit
        desc = segs[idx][len(str(part_no)):].strip()
        tail = segs[idx + 1:]
        # 자재명이 길면 그 행 전체가 한 블록으로 안 잡히고 "SO/파트/자재명" 블록과
        # "원산지/수량/단가/금액" 블록으로 쪼개진다(실측: TO 7866552의 Ophir 품목).
        # 그 경우 같은 y에 있는 오른쪽 블록을 찾아 붙인다.
        if not any(_num(t) is not None for t in tail):
            for other in blocks:
                if other is b or other[0] < 380:
                    continue
                if abs(other[1] - b[1]) < 6:
                    tail = tail + _segs(other)
                    break

        # 원산지 코드(2~3자 알파벳)나 숫자가 나오기 전까지는 접힌 자재명이다.
        while tail and _num(tail[0]) is None and not (len(tail[0]) <= 3 and tail[0].isalpha()):
            desc = f"{desc} {tail.pop(0)}".strip()
        origin = tail.pop(0) if tail and len(tail[0]) <= 3 and tail[0].isalpha() else None
        nums = [n for n in (_num(t) for t in tail) if n is not None]
        qty = unit_price = amount = None
        if len(nums) >= 5:
            # [ORDERED, BACK ORD, SHIPPED, 단가, 금액]
            qty, unit_price, amount = nums[2], nums[-2], nums[-1]
        elif len(nums) >= 2:
            unit_price, amount = nums[-2], nums[-1]
        result[str(part_no)] = {
            "description": desc or None,
            "origin": origin,
            "qty": int(qty) if qty is not None and float(qty).is_integer() else qty,
            "unit_price": unit_price,
            "amount": amount,
        }
    return result


def parse_all_invoice_rows_from_pdf(pdf_path: str) -> list[dict]:
    """CI PDF의 **모든 품목 행**을 위에서 아래로 읽는다.

    parse_invoice_items_from_pdf()는 파트넘버 하나당 첫 행만 찾는데(Rebalance는
    품목이 1~2줄이라 충분했다), RMA는 같은 파트가 S/N별로 여러 줄로 나오고
    페이지도 넘어간다(실측 TO 7672306: 15개 파트 / 28줄 / 4페이지). 그래서
    행 단위로 전부 읽어서 파트별로 합산할 수 있게 한다.

    실측 블록 형태(2026-08-18, TO 7672306 재출력분):
      한 줄이 한 블록: ['7672306','13','7122-57-9578  FSE, GMAX DHP YAG HEAD',
                        'MX','1','0','1','₩ 5,424,969','₩ 5,424,969']
      자재명이 길면 좌/우 블록으로 쪼개짐:
        좌: ['7672306','10','9APP7748-CNDL  Applicator ...','Legal Mfg: Candela',
             'S/N: 22020258']
        우: ['MX','1','0','1','₩ 3,335,110','₩ 3,335,110']
      오라클이 HTS를 이미 찍어둔 행은 우측 블록에 코드가 끼어든다:
        ['MX','9018.9','0.8000','1','0','1','₩ 12,932,178','₩ 12,932,178']
      -> 그래서 숫자는 앞에서 세지 않고 **뒤에서 5개**
         [ORDERED, BACK ORD, SHIPPED, 단가, 금액]만 쓴다."""
    import fitz

    def _num(tok: str):
        t = str(tok).replace("₩", "").replace(",", "").replace("KRW", "").strip()
        try:
            return float(t)
        except ValueError:
            return None

    def _segs(block):
        return [s.strip() for s in str(block[4] or "").split("\n") if s.strip()]

    rows: list[dict] = []
    doc = fitz.open(pdf_path)
    try:
        for page in doc:
            blocks = page.get_text("blocks")
            for b in blocks:
                segs = _segs(b)
                # 품목 행은 'SO NO.'(7자리) + 'SO LINE NO.'(숫자)로 시작한다.
                if len(segs) < 3 or not re.fullmatch(r"\d{7}", segs[0]) or not segs[1].isdigit():
                    continue
                part_desc = segs[2]
                m = re.match(r"(\S+)\s{2,}(.*)$", part_desc) or re.match(r"(\S+)\s+(.*)$", part_desc)
                if not m:
                    continue
                part_no, desc = m.group(1).strip(), m.group(2).strip()
                tail = segs[3:]
                # 오른쪽(원산지/수량/금액) 블록이 따로 떨어져 있으면 같은 y에서 찾아 붙인다.
                if not any(_num(t) is not None for t in tail):
                    for other in blocks:
                        if other is b or other[0] < 380:
                            continue
                        if abs(other[1] - b[1]) < 6:
                            tail = tail + _segs(other)
                            break
                # 숫자/원산지가 나오기 전까지는 접힌 자재명이다. S/N 줄은 자재명이
                # 아니라 개별 시리얼이라 자재명에서는 빼고 따로 모은다
                # (2026-08-27 사용자 지시: 수출신고실적에 S/N 열을 따로 둔다).
                serials: list[str] = []
                while tail and _num(tail[0]) is None and not (
                        len(tail[0]) <= 3 and tail[0].isalpha()):
                    piece = tail.pop(0)
                    if piece.upper().startswith("S/N"):
                        # "S/N: D12318K-0823100" 또는 "S/N: a, b" 형태
                        for sn in re.split(r"[,/]", piece.split(":", 1)[-1]):
                            sn = sn.strip()
                            if sn and sn not in serials:
                                serials.append(sn)
                    else:
                        desc = f"{desc} {piece}".strip()
                origin = tail.pop(0) if tail and len(tail[0]) <= 3 and tail[0].isalpha() else None
                nums = [n for n in (_num(t) for t in tail) if n is not None]
                if len(nums) < 5:
                    continue
                ordered, _back, shipped, unit_price, amount = nums[-5:]
                rows.append({
                    "part_no": part_no,
                    "description": desc or None,
                    "origin": origin,
                    "qty": int(shipped) if float(shipped).is_integer() else shipped,
                    "unit_price": unit_price,
                    "amount": amount,
                    "serials": serials,
                })
    finally:
        doc.close()
    return rows


def find_fsd_template() -> str | None:
    """Foreign Shipper Declaration 양식 파일을 찾는다. 기본 경로가 없으면
    12. 수출\\RMA 아래에서 같은 이름 패턴을 가진 가장 최근 파일을 쓴다(양식이
    다음 케이스 폴더로 옮겨지거나 날짜가 붙어 이름이 바뀌어도 따라가도록)."""
    if os.path.exists(FSD_TEMPLATE_PATH):
        return FSD_TEMPLATE_PATH
    import glob
    hits = glob.glob(os.path.join(FSD_TEMPLATE_DIR, "**", "Foreign Shipper Declaration*.xls*"),
                     recursive=True)
    hits = [h for h in hits if not os.path.basename(h).startswith("~$")]
    if not hits:
        log(f"[경고] Foreign Shipper Declaration 양식을 못 찾음(기본 경로: {FSD_TEMPLATE_PATH})")
        return None
    newest = max(hits, key=os.path.getmtime)
    log(f"[정보] FSD 양식 기본 경로가 없어 최근 파일을 사용: {newest}")
    return newest


def parse_invoice_date_from_pdf(pdf_path: str) -> datetime | None:
    """CI 헤더의 DATE(예 '20-APR-2026')를 읽는다. 표 안의 SHIP DATE와 구분하려고
    헤더 영역(y<200)에 있는 값만 본다."""
    import fitz

    doc = fitz.open(pdf_path)
    try:
        for blk in doc[0].get_text("blocks"):
            if blk[1] > 200:
                continue
            m = re.search(r"(\d{1,2})-([A-Z]{3})-(\d{4})", str(blk[4] or "").upper())
            if not m:
                continue
            months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                      "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
            if m.group(2) not in months:
                continue
            return datetime(int(m.group(3)), months.index(m.group(2)) + 1, int(m.group(1)))
    except Exception as e:
        log(f"[정보] CI에서 인보이스 날짜를 못 읽음({e})")
    finally:
        doc.close()
    return None


def build_foreign_shipper_declaration(
    out_path: str, delivery_no: str, invoice_date: datetime, items: list[dict],
) -> str | None:
    """양식을 복사해 표(Marks/Shipment/Invoice Date/Part Number/Description/QTY/
    Value)와 작성일을 채운 Foreign Shipper Declaration을 만든다.

    Value는 **CI에 인쇄된 금액과 같은 값**(RMA는 10% 적용분)을 쓴다 - 서류끼리
    금액이 어긋나면 안 된다. 품목은 파트당 한 줄로 합산해서 넣는다(과거 수기
    이력과 같은 형식).

    실패하면 예외를 올리지 않고 None을 반환한다 - 이 서류는 CI에 곁들이는
    부속 문서라, 만들지 못했다고 파이프라인 본체(실적 기입 등)를 막지 않는다.
    대신 호출부가 알림에 그 사실을 남긴다."""
    template = find_fsd_template()
    if not template:
        return None
    if not items:
        log("[경고] FSD를 만들 품목이 없어 생성 생략")
        return None

    import win32com.client

    shutil.copy2(template, out_path)
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(out_path)
        ws = wb.Worksheets(1)

        rows_available = FSD_ROW_END - FSD_ROW_START + 1
        extra = len(items) - rows_available
        if extra > 0:
            # 품목이 양식의 표보다 많으면 표 아래에 행을 넣어 서명 블록을 밀어낸다.
            ws.Rows(f"{FSD_ROW_END + 1}:{FSD_ROW_END + extra}").Insert()
            ws.Rows(FSD_ROW_END).Copy(ws.Rows(f"{FSD_ROW_END + 1}:{FSD_ROW_END + extra}"))
            ws.Range(f"A{FSD_ROW_END + 1}:G{FSD_ROW_END + extra}").ClearContents()
            log(f"[FSD] 품목이 {len(items)}건이라 표에 {extra}행 추가")

        # COM으로 naive datetime을 넣으면 pywin32가 로컬->UTC로 바꿔 9시간 밀린다
        # (memory rebalance-to-automation-sop 참고) - 엑셀 일련번호로 넣는다.
        serial = (invoice_date.date() - datetime(1899, 12, 30).date()).days
        for i, it in enumerate(items):
            r = FSD_ROW_START + i
            ws.Cells(r, 1).Value = i + 1                      # Marks
            ws.Cells(r, 2).Value = str(delivery_no)           # Shipment
            ws.Cells(r, 3).Value2 = serial                    # Invoice Date
            ws.Cells(r, 4).Value = str(it.get("part_no") or "")
            ws.Cells(r, 5).Value = str(it.get("description") or "")
            ws.Cells(r, 6).Value = it.get("qty")
            ws.Cells(r, 7).Value = it.get("value")
        # 양식에 남아있는 예시 행(이전 건 데이터)을 지운다.
        last_filled = FSD_ROW_START + len(items) - 1
        if last_filled < FSD_ROW_END + max(0, extra):
            ws.Range(f"A{last_filled + 1}:G{FSD_ROW_END + max(0, extra)}").ClearContents()

        ws.Range(FSD_DATE_CELL).Value = f"Date: {datetime.now():%Y.%m.%d}"
        wb.Save()
        wb.Close(False)
    finally:
        try:
            excel.Quit()
        except Exception as e:
            log(f"[정보] FSD 생성 후 Excel 종료 실패({e})")
    log(f"[FSD] Foreign Shipper Declaration 생성: {os.path.basename(out_path)} "
        f"({len(items)}품목, Shipment {delivery_no})")
    return out_path


def create_hq_rma_docs_draft(delivery_no: str, attachments: list[str]) -> str | None:
    """RMA 서류(CI + Foreign Shipper Declaration)를 본사 앞으로 보내는 초안을
    만든다(2026-08-18 사용자 요청).

    제목은 실제 이력(2025-12-08, Delivery 9834927/9834928)을 그대로 따른다 -
    "Delivery {번호}". 수신자는 John Ross의 Global RMA Process 공식메일
    (2026-06-16)에 맞춰 To=Dale Carr+Robert Lazaros / CC=Miae Jang
    (RMA_HQ_MAIL_TO/CC 참고), FSD와 인보이스 둘 다 첨부.
    **초안만 저장한다**(용마 CI 답장과 같은 원칙 - 외부로 서류를 실제로 넘기는
    메일은 사람이 한 번 보고 보낸다).

    실패해도 예외를 올리지 않는다 - 부가 커뮤니케이션 단계라 파이프라인 본체를
    막지 않는다(호출부가 로그/알림에 남긴다)."""
    import win32com.client

    files = [a for a in (attachments or []) if a and os.path.exists(a)]
    if not files:
        log("[경고] 본사 앞 RMA 서류 초안: 첨부할 파일이 없어 생성 생략")
        return None

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = RMA_HQ_MAIL_TO
    mail.CC = RMA_HQ_MAIL_CC
    mail.Subject = f"Delivery {delivery_no}"

    # Outlook의 기본 서명은 Inspector를 한 번 열어야 HTMLBody에 채워진다.
    # 그 서명 위에 본문만 끼워 넣는다(create_yongma_ci_reply_draft에서 원본 서식을
    # 지키려고 쓴 것과 같은 방식 - HTMLBody를 통째로 대입하면 서명이 날아간다).
    signature_html = ""
    try:
        _ = mail.GetInspector
        signature_html = str(getattr(mail, "HTMLBody", "") or "")
    except Exception as e:
        log(f"[정보] 본사 앞 초안: 기본 서명을 못 붙였습니다({e}) - 본문만 작성")

    greeting_html = mail_text_to_html(RMA_HQ_MAIL_BODY)
    m = re.search(r"<body[^>]*>", signature_html, re.IGNORECASE)
    if m:
        mail.HTMLBody = (signature_html[:m.end()] + greeting_html
                         + signature_html[m.end():])
    else:
        mail.HTMLBody = greeting_html + signature_html

    for path in files:
        mail.Attachments.Add(path)
    mail.Save()
    log(f"[HQ] 본사 앞 RMA 서류 초안 저장: 'Delivery {delivery_no}' "
        f"(첨부: {', '.join(os.path.basename(f) for f in files)})")
    return mail.EntryID


def hq_profile(country_code: str) -> dict:
    """목적지 국가코드의 선적서류 메일 프로필(없으면 KeyError)."""
    return HQ_DOC_MAIL_PROFILES[str(country_code).strip().upper()]


def hq_mail_body(profile: dict, trackings: list[str] | None = None) -> str:
    """프로필 본문에 Tracking 번호를 채운다(자리표시자가 없으면 그대로)."""
    body = profile["body"]
    if "{tracking}" not in body:
        return body
    return body.format(tracking=", ".join(trackings) if trackings else "(to be advised)")


def create_hq_docs_draft(country_code: str, delivery_nos: list[str],
                         attachments: list[str],
                         trackings: list[str] | None = None) -> str | None:
    """Rebalance 선적서류를 목적지 담당자 앞으로 보내는 **초안**을 만든다
    (미국=Bob 2026-08-20, 스페인=Tamara 2026-09-18 - US_HQ_MAIL_*/EU_HQ_MAIL_*
    상수 설명 참고).

    제목/수신자/본문은 사용자가 실제로 보낸 메일을 그대로 따른다(추측 아님).
    create_hq_rma_docs_draft와 같은 방식으로 Outlook 기본 서명을 살린다.

    2026-08-27: 예전엔 이 함수가 CI 한 장을 붙여 **바로 발송**했는데, 배송이
    2건인 TO에서 두 번째 CI가 통째로 빠졌다(HQ_QUIET_MINUTES 설명 참고).
    지금은 초안까지만 만들고, 그 TO의 CI가 다 모인 뒤 process_hq_docs_pending()이
    발송한다 - "자동 발송"이라는 결론은 그대로고 타이밍만 뒤로 밀렸다.

    실패해도 예외를 올리지 않는다 - 부가 커뮤니케이션 단계라 파이프라인 본체를
    막지 않는다(RMA 쪽과 같은 원칙)."""
    import win32com.client

    profile = hq_profile(country_code)
    files = [a for a in (attachments or []) if a and os.path.exists(a)]
    if not files:
        log(f"[경고] {profile['name']} 앞 Rebalance 서류 메일: 첨부할 파일이 없어 초안 생략")
        return None

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = profile["to"]
    mail.CC = profile["cc"]
    mail.Subject = profile["subject"]

    # HTMLBody를 통째로 대입하면 기본 서명이 날아가므로 <body> 바로 뒤에 끼워 넣는다
    # (create_hq_rma_docs_draft / create_yongma_ci_reply_draft와 같은 방식).
    signature_html = ""
    try:
        _ = mail.GetInspector
        signature_html = str(getattr(mail, "HTMLBody", "") or "")
    except Exception as e:
        log(f"[정보] {profile['name']} 앞 초안: 기본 서명을 못 붙였습니다({e}) - 본문만 작성")

    greeting_html = mail_text_to_html(hq_mail_body(profile, trackings))
    m = re.search(r"<body[^>]*>", signature_html, re.IGNORECASE)
    if m:
        mail.HTMLBody = (signature_html[:m.end()] + greeting_html
                         + signature_html[m.end():])
    else:
        mail.HTMLBody = greeting_html + signature_html

    for path in files:
        mail.Attachments.Add(path)
    mail.Save()
    log(f"[HQ] {profile['name']} 앞 Rebalance 서류 초안 저장: '{profile['subject']}' "
        f"(Delivery {', '.join(str(d) for d in delivery_nos)}, To {profile['to']}, "
        + (f"Tracking {', '.join(trackings)}, " if trackings else "")
        + f"첨부: {', '.join(os.path.basename(f) for f in files)})")
    return mail.EntryID


# --------------------------------------------------------------
# 목적지 담당자 앞 서류 메일 대기 큐 (2026-08-27 미국 / 2026-09-18 스페인)
# --------------------------------------------------------------
# "한 TO = 메일 한 통"이 되도록, CI가 확정될 때마다 모아두고 그 TO가
# 조용해지면(=새 CI가 HQ_QUIET_MINUTES 동안 없고 ci_pending도 비었으면)
# 발송한다. 자세한 배경은 HQ_QUIET_MINUTES 상수 설명 참고.
def _open_mail_by_entry_id(entry_id: str):
    import win32com.client
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    return ns.GetItemFromID(entry_id)


def _hq_queue(st: dict) -> dict:
    """대기 큐를 돌려준다(구 키 us_hq_pending -> hq_docs_pending 자동 이전).

    큐가 미국 전용이던 시절의 키를 그대로 쓰면 목적지를 구분할 수 없어서
    2026-09-18에 이름을 바꿨다. 남아 있던 항목은 전부 미국 건이므로 country를
    WAY로 채워 옮긴다(이전 시점에 큐는 비어 있었지만, 실행 중 갱신된 state가
    조용히 유실되지 않도록 남겨둔다)."""
    if "us_hq_pending" in st:
        legacy = st.pop("us_hq_pending") or {}
        for v in legacy.values():
            if isinstance(v, dict):
                v.setdefault("country", US_COUNTRY_CODE)
        if legacy:
            log(f"[정보] 구 대기 큐(us_hq_pending) {len(legacy)}건을 "
                f"hq_docs_pending으로 이전합니다")
        st.setdefault("hq_docs_pending", {}).update(legacy)
    return st.setdefault("hq_docs_pending", {})


def _upsert_hq_draft(country_code: str, draft_entry_id: str | None,
                     delivery_nos: list[str], files: list[str],
                     trackings: list[str] | None = None) -> str | None:
    """담당자 앞 초안이 있으면 **아직 안 붙은 첨부만** 더하고, 없으면 새로 만든다.

    첨부 비교는 파일명으로 한다 - 서명 이미지(image001.png 등)도 첨부로 잡히지만
    CI 파일명과 겹치지 않아 문제되지 않는다. 사용자가 초안을 지웠거나 이미 보낸
    경우엔 EntryID 조회가 실패하므로 새 초안을 만든다."""
    profile = hq_profile(country_code)
    mail = None
    if draft_entry_id:
        try:
            mail = _open_mail_by_entry_id(draft_entry_id)
        except Exception as e:
            log(f"[정보] {profile['name']} 앞 초안을 못 찾음(지웠거나 이미 보냄: {e}) "
                f"- 새로 만듭니다")
            mail = None
    if mail is None:
        return create_hq_docs_draft(country_code, delivery_nos, files, trackings)

    have = set()
    for i in range(mail.Attachments.Count):
        try:
            have.add(str(mail.Attachments.Item(i + 1).FileName))
        except Exception:
            continue
    added = []
    for path in files:
        if os.path.basename(path) in have:
            continue
        mail.Attachments.Add(path)
        added.append(os.path.basename(path))
    if added:
        mail.Save()
        log(f"[HQ] {profile['name']} 앞 초안에 서류 추가: {', '.join(added)} "
            f"(Delivery {', '.join(str(d) for d in delivery_nos)})")
    return mail.EntryID


def queue_hq_docs(country_code: str, to_number: str, delivery_no: str,
                  ci_path: str) -> None:
    """확정된 CI 한 장을 그 TO의 담당자 앞 대기 큐에 올린다.

    미국(WAY)은 예전처럼 이 시점에 초안을 만들어 CI를 모아 두고(draft_early),
    스페인(FBC/FBS)은 본문에 Tracking 번호가 들어가야 해서 라벨이 나온 뒤
    _send_hq_draft에서 한 번에 만든다."""
    profile = hq_profile(country_code)
    to_key = str(to_number)
    with _STATE_LOCK:
        st = load_state()
        entry = _hq_queue(st).setdefault(
            to_key, {"docs": {}, "draft_entry_id": None})
        entry["country"] = str(country_code).strip().upper()
        entry.setdefault("docs", {})[str(delivery_no)] = ci_path
        entry["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry["fail_count"] = 0
        save_state(st)
        docs = dict(entry["docs"])
        draft_id = entry.get("draft_entry_id")

    if profile.get("draft_early"):
        files = [docs[d] for d in sorted(docs) if docs[d] and os.path.exists(docs[d])]
        new_id = _upsert_hq_draft(country_code, draft_id, sorted(docs), files)
        if new_id and new_id != draft_id:
            with _STATE_LOCK:
                st = load_state()
                e = _hq_queue(st).get(to_key)
                if e is not None:
                    e["draft_entry_id"] = new_id
                    save_state(st)
    log(f"[HQ대기] TO {to_key}: {profile['name']} 앞 서류 {len(docs)}장 대기 "
        f"(Delivery {', '.join(sorted(docs))}) - 새 CI가 "
        f"{HQ_QUIET_MINUTES}분간 없고 FedEx 라벨이 나오면 발송")


def _hq_pending_remove(to_key: str) -> None:
    with _STATE_LOCK:
        st = load_state()
        if _hq_queue(st).pop(str(to_key), None) is not None:
            save_state(st)


def find_fedex_labels(to_number: str) -> list[str]:
    """그 TO의 FedEx 라벨 PDF들(FEDEX_LABEL_FOLDER 주석 참고).

    fedex_ship_watcher가 "FedEx Label KRP-{국가} {TO#} {AWB}.pdf"로 보관하므로
    파일명에 TO#가 들어간 PDF를 찾는다. 배송이 쪼개져 라벨이 여러 장일 수 있어
    전부 돌려준다."""
    try:
        return sorted(
            os.path.join(FEDEX_LABEL_FOLDER, f)
            for f in os.listdir(FEDEX_LABEL_FOLDER)
            if str(to_number) in f and f.lower().endswith(".pdf")
        )
    except Exception as e:
        log(f"[경고] FedEx 라벨 폴더를 못 읽음({FEDEX_LABEL_FOLDER}): {exc_detail(e)}")
        return []


def tracking_numbers_from_labels(labels: list[str]) -> list[str]:
    """라벨 파일명에서 AWB(Tracking 번호)를 뽑는다.

    번호는 FedEx 화면에서 읽어 파일명에 박아둔 것이라(fedex_ship_watcher의
    confirm_shipment_and_capture_label) 여기서 다시 PDF를 열 필요가 없다.
    배송이 쪼개져 라벨이 여러 장이면 번호도 여러 개 - 순서를 유지해 전부 돌려준다."""
    out = []
    for path in labels or []:
        m = _LABEL_AWB_PATTERN.search(os.path.basename(path))
        if m and m.group(1) not in out:
            out.append(m.group(1))
    return out


def _send_hq_as_new_mail(country_code: str, draft, to_number: str, docs: dict,
                         trackings: list[str] | None = None) -> None:
    """보내지지 않는 초안을 대신해 같은 내용으로 **새 메일**을 만들어 보낸다.

    초안의 첨부를 임시 폴더로 꺼내 다시 붙인다(서명 이미지는 새 메일에도 서명으로
    다시 들어가므로 제외). 본문/제목/수신자는 상수에서 새로 만든다 - 초안에서
    HTMLBody를 가져오면 그 초안이 가진 문제(원인 미상)를 같이 옮길 수 있다."""
    import tempfile
    import win32com.client

    profile = hq_profile(country_code)
    tmp = os.path.join(tempfile.gettempdir(), f"_hq_{to_number}")
    os.makedirs(tmp, exist_ok=True)
    files = []
    for k in range(draft.Attachments.Count):
        try:
            att = draft.Attachments.Item(k + 1)
            name = str(att.FileName)
            if name.lower().startswith("image"):
                continue
            path = os.path.join(tmp, name)
            att.SaveAsFile(path)
            files.append(path)
        except Exception as e:
            log(f"  [경고] 첨부 '{name}' 복사 실패: {e}")
    if not files:
        raise RuntimeError("새 메일로 옮길 첨부가 없음 - 초안을 직접 보내주세요")

    new = win32com.client.Dispatch("Outlook.Application").CreateItem(0)
    new.To = profile["to"]
    new.CC = profile["cc"]
    new.Subject = profile["subject"]
    new.Body = hq_mail_body(profile, trackings)
    for path in files:
        new.Attachments.Add(path)
    new.Send()
    log(f"[HQ] {profile['name']} 앞 Rebalance 서류 발송(새 메일): '{profile['subject']}' "
        f"(TO {to_number}, Delivery {', '.join(sorted(docs))}, To {profile['to']}, "
        + (f"Tracking {', '.join(trackings)}, " if trackings else "")
        + f"첨부: {', '.join(os.path.basename(f) for f in files)})")

    # 2026-09-10 사용자 승인: 새 메일이 나간 뒤 **원본 초안을 지운다**.
    # 남겨뒀더니 사용자가 그 초안을 직접 보내 Robert에게 같은 메일이 2통 갔다
    # (14:27:24 자동 발송 / 14:28:06 수동 발송). 자동화가 만든 초안이고 같은
    # 내용이 이미 나간 뒤라 남겨둘 이유가 없다. **발송 성공 후에만** 지운다.
    try:
        draft.Delete()
        log("  원본 초안 삭제(같은 내용이 이미 발송됨 - 중복 발송 방지)")
    except Exception as e:
        log(f"  [경고] 원본 초안을 지우지 못했습니다({e}) - 임시보관함에서 직접 "
            f"지워주세요. 그대로 두면 중복 발송될 수 있습니다")


def _send_hq_draft(country_code: str, to_number: str, entry: dict) -> None:
    """대기 큐의 초안을 그 TO의 CI 전부 + FedEx 라벨을 붙인 상태로 발송한다.

    프로필의 auto_send가 False면(스페인 건 초기 운용) 초안만 남기고 알린다."""
    profile = hq_profile(country_code)
    docs = entry.get("docs") or {}
    files = [docs[d] for d in sorted(docs) if docs[d] and os.path.exists(docs[d])]
    missing = [d for d in sorted(docs) if not (docs[d] and os.path.exists(docs[d]))]
    if missing:
        log(f"[경고] TO {to_number} {profile['name']} 앞 서류: 파일을 못 찾은 배송 "
            f"{', '.join(missing)} - 나머지만 보냅니다")
    if not files:
        raise RuntimeError("첨부할 CI 파일이 하나도 없음")

    # 2026-08-27 사용자 지시: FedEx 라벨도 같이 보낸다(process_hq_docs_pending이
    # 라벨이 나온 뒤에만 여기까지 오게 막아준다).
    labels = find_fedex_labels(to_number)
    if not labels:
        raise RuntimeError("FedEx 라벨을 못 찾음 - 라벨 없이 보내지 않음")
    files = files + labels
    trackings = tracking_numbers_from_labels(labels)
    if "{tracking}" in profile["body"] and not trackings:
        # 본문에 Tracking을 반드시 써야 하는 목적지(스페인)인데 라벨 파일명에서
        # 번호를 못 뽑았다면 "(to be advised)"로 나가버린다 - 그건 이 메일의
        # 존재 이유(사전 통관 준비)를 깨뜨리므로 보내지 않고 사람에게 넘긴다.
        raise RuntimeError(
            f"라벨 파일명에서 Tracking 번호를 못 뽑음({', '.join(os.path.basename(p) for p in labels)})")

    draft_id = _upsert_hq_draft(country_code, entry.get("draft_entry_id"),
                                sorted(docs), files, trackings)
    if not draft_id:
        raise RuntimeError(f"{profile['name']} 앞 초안을 만들지 못함")
    mail = _open_mail_by_entry_id(draft_id)
    names = []
    for i in range(mail.Attachments.Count):
        try:
            names.append(str(mail.Attachments.Item(i + 1).FileName))
        except Exception:
            continue

    if not profile.get("auto_send", True):
        # 초안까지만. 사람이 보고 보낸다(사용자 지시로 켜기 전 단계).
        log(f"[HQ] {profile['name']} 앞 서류 **초안 저장**(자동 발송 꺼짐): "
            f"'{profile['subject']}' (TO {to_number}, Tracking {', '.join(trackings)}, "
            f"첨부: {', '.join(n for n in names if not n.lower().startswith('image'))})")
        send_alert(
            f"[Rebalance TO {to_number}] {profile['name']} 앞 선적서류 초안이 준비됐습니다",
            f"임시보관함의 '{profile['subject']}' 초안을 확인하고 보내주세요.\n\n"
            f"TO: {to_number}\n목적지: {country_code}\n"
            f"Tracking: {', '.join(trackings)}\n"
            f"수신: {profile['to']}\nCC: {profile['cc']}\n"
            f"첨부: {', '.join(n for n in names if not n.lower().startswith('image'))}\n\n"
            f"문구가 이대로 괜찮으면 rebalance_watcher.py의 EU_HQ_AUTO_SEND를 True로 "
            f"바꾸면 다음 건부터 자동 발송됩니다.",
        )
        return

    # 이 초안의 Send()가 "The parameter is incorrect."로 반복 실패한다
    # (2026-08-26 / 09-09 / 09-10 세 번). 원인은 아직 못 밝혔다 - 수신자는
    # resolved 상태였고, 0바이트 서명 이미지를 떼봐도 그대로 실패했다(둘 다
    # 실측으로 배제). 다만 **같은 내용으로 새 메일을 만들어 보내면 항상 된다**
    # (2026-09-09 실측). 그래서 원인 규명과 별개로, 실패하면 새 메일로 보낸다.
    try:
        mail.Send()
    except Exception as e:
        log(f"[HQ] 초안 Send 실패({e}) - 같은 내용으로 새 메일을 만들어 보냅니다")
        _send_hq_as_new_mail(country_code, mail, to_number, docs, trackings)
        log("  [확인 필요] 보내지 못한 원본 초안이 임시보관함에 남아 있습니다")
        return
    log(f"[HQ] {profile['name']} 앞 Rebalance 서류 발송: '{profile['subject']}' "
        f"(TO {to_number}, Delivery {', '.join(sorted(docs))}, To {profile['to']}, "
        + (f"Tracking {', '.join(trackings)}, " if trackings else "")
        + f"첨부: {', '.join(n for n in names if not n.lower().startswith('image'))})")


def process_hq_docs_pending() -> None:
    """조용해진 TO의 담당자 앞 선적서류 메일을 발송한다(매 회차 앞단에서 호출).

    보류 조건 두 가지:
      - 그 TO의 ci_pending이 아직 남아 있다(=다른 배송의 CI가 곧 더 나온다)
      - 마지막 CI가 붙은 지 HQ_QUIET_MINUTES가 안 지났다
    발송에 실패하면 큐에 그대로 두고 다음 회차가 다시 시도한다(초안도 남아 있어
    사람이 직접 보낼 수도 있다). 3회 연속 실패하면 한 번만 알린다."""
    with _STATE_LOCK:
        st = load_state()
        migrated = "us_hq_pending" in st
        queue = {k: dict(v) for k, v in _hq_queue(st).items()}
        ci_pending = dict(st.get("ci_pending") or {})
        if migrated:
            save_state(st)      # 구 키를 옮겼으면 그 결과를 남긴다
    if not queue:
        return

    for to_key, entry in sorted(queue.items()):
        docs = entry.get("docs") or {}
        if not docs:
            _hq_pending_remove(to_key)
            continue
        country_code = str(entry.get("country") or US_COUNTRY_CODE).upper()
        try:
            profile = hq_profile(country_code)
        except KeyError:
            log(f"[경고] TO {to_key}: 선적서류 메일 프로필이 없는 목적지"
                f"({country_code}) - 큐에서 내립니다")
            _hq_pending_remove(to_key)
            continue

        waiting = [k for k in ci_pending if k.split(":")[0] == to_key]
        if waiting:
            log(f"[HQ대기] TO {to_key}: 같은 TO의 CI가 아직 대기 중({', '.join(waiting)}) "
                f"- 서류가 다 모일 때까지 발송 보류")
            continue

        try:
            elapsed_min = (datetime.now() - datetime.strptime(
                str(entry.get("updated_at")), "%Y-%m-%d %H:%M:%S")).total_seconds() / 60
        except Exception:
            # 시각을 못 읽으면 미루지 않는다(무한 보류 방지).
            elapsed_min = HQ_QUIET_MINUTES
        if elapsed_min < HQ_QUIET_MINUTES:
            log(f"[HQ대기] TO {to_key}: 마지막 CI 이후 {elapsed_min:.0f}분 - "
                f"{HQ_QUIET_MINUTES}분 지나면 발송")
            continue

        # 2026-08-27 사용자 지시("bob도 FedEx가 잡히면 라벨 포함해서 보내는걸로"):
        # 라벨이 나올 때까지 기다린다. CI만 먼저 보내고 라벨을 따로 보내지 않는다.
        # 스페인(Tamara) 건은 본문의 Tracking 번호도 이 라벨에서 나온다.
        labels = find_fedex_labels(to_key)
        if not labels:
            if elapsed_min >= HQ_LABEL_WAIT_HOURS * 60 and not entry.get("label_alerted"):
                log(f"[경고] TO {to_key}: FedEx 라벨을 {HQ_LABEL_WAIT_HOURS}시간째 "
                    f"못 찾아 {profile['name']} 앞 메일이 계속 대기 중")
                send_alert(
                    f"[Rebalance TO {to_key}] {profile['name']} 앞 메일 대기 - FedEx 라벨 없음",
                    f"CI는 준비됐는데 FedEx 라벨이 {HQ_LABEL_WAIT_HOURS}시간째 "
                    f"안 나와 {profile['name']} 앞 메일을 보내지 못하고 있습니다.\n"
                    f"라벨 폴더: {FEDEX_LABEL_FOLDER}\n\n"
                    f"FedEx 발송이 끝났는지 확인해주세요. 라벨이 폴더에 들어오면 "
                    f"다음 회차에 자동으로 발송됩니다.\n"
                    f"(라벨 없이 보내려면 초안이 그대로 남아 있으니 직접 보내시면 됩니다.)",
                )
                with _STATE_LOCK:
                    st2 = load_state()
                    e2 = _hq_queue(st2).get(to_key)
                    if e2 is not None:
                        e2["label_alerted"] = True
                        save_state(st2)
            else:
                log(f"[HQ대기] TO {to_key}: FedEx 라벨이 아직 없음 - 라벨이 나오면 "
                    f"CI와 함께 발송")
            continue

        try:
            _send_hq_draft(country_code, to_key, entry)
            _hq_pending_remove(to_key)
        except Exception as e:
            fails = int(entry.get("fail_count") or 0) + 1
            log(f"[경고] TO {to_key} {profile['name']} 앞 서류 발송 실패({fails}회, "
                f"다음 회차에 재시도): {e}")
            with _STATE_LOCK:
                st = load_state()
                e2 = _hq_queue(st).get(to_key)
                if e2 is not None:
                    e2["fail_count"] = fails
                    save_state(st)
            if fails == 3:
                send_alert(
                    f"[Rebalance TO {to_key}] {profile['name']} 앞 선적서류 발송이 계속 실패합니다",
                    f"임시보관함의 '{profile['subject']}' 초안에 CI "
                    f"{len(docs)}장(Delivery {', '.join(sorted(docs))})이 들어 있습니다.\n"
                    f"자동 발송이 3회 실패했으니 초안을 직접 확인하고 보내주세요.\n\n{e}",
                )


def aggregate_invoice_rows_by_part(rows: list[dict]) -> list[dict]:
    """행 단위 결과를 파트넘버별로 합산한다(수량/금액은 합, 단가·자재명·원산지는
    첫 행 값). 같은 파트가 S/N별로 여러 줄인 RMA 인보이스를 수출신고실적/
    Foreign Shipper Declaration의 "파트당 한 줄" 형식으로 맞추기 위한 것 -
    과거 수기 이력도 파트당 한 줄에 수량을 합쳐 적었다(2025-12-05 RMA 16줄,
    2026-04-14 RMA 15줄)."""
    merged: dict[str, dict] = {}
    for r in rows:
        key = str(r["part_no"]).strip()
        cur = merged.get(key)
        if cur is None:
            merged[key] = dict(r, part_no=key, serials=list(r.get("serials") or []))
            continue
        for field in ("qty", "amount"):
            if r.get(field) is not None:
                cur[field] = (cur.get(field) or 0) + r[field]
        for field in ("description", "origin", "unit_price"):
            if cur.get(field) is None:
                cur[field] = r.get(field)
        # 2026-08-27 사용자 지시("두개 다 적어줘"): S/N별로 쪼개진 행을 합칠 때
        # 시리얼을 버리지 않고 전부 모은다(수출신고실적 S/N 열에 다 적는다).
        for sn in (r.get("serials") or []):
            if sn not in cur.setdefault("serials", []):
                cur["serials"].append(sn)
    return list(merged.values())


def append_export_declaration(
    country_code: str, ship_date: datetime, bl_no: str, hs_code: str,
    parts_qty: list[dict], to_number: str, delivery_no: str,
    purpose: str = "Rebalance",
):
    """수출신고실적20260126~.xlsx Sheet1에 Rebalance 건을 append.
    컬럼(실측 확인, 2025-12-03 JPP/AUP 이력 기준): Destination/Purpose/
    선적일자/B_L번호/HS_code/관리코드/품명/수량/단가/금액/SO/Delivery_Number/국가

    2026-08-18: RMA 건은 Purpose를 "RMA"로 남긴다 - 과거 수기 이력(2026-04-14
    TO 7672306, 2025-12-05 TO 7619973)이 Destination="FA LAB", Purpose="RMA"로
    적혀 있어 같은 형식을 이어쓴다."""
    import openpyxl
    from copy import copy

    _backup_before_write(EXPORT_DECLARATION_PATH)
    wb = openpyxl.load_workbook(EXPORT_DECLARATION_PATH)
    ws = wb["Sheet1"]

    # 기존 이력은 수출일자가 시각 없는 날짜(예: 2026-08-04)라 datetime.now()를
    # 그대로 넣으면 "13:41:10"까지 찍힌다(2026-08-06 실측) - 날짜만 쓴다.
    ship_day = ship_date.date() if isinstance(ship_date, datetime) else ship_date

    # 2026-08-27 사용자 지시("이제 S/N 열을 추가로 만들어서 기입해줘"): 시리얼은
    # 자재명에 섞어 적지 않고 N열(14)에 따로 적는다. 한 파트에 시리얼이 여러 개면
    # 전부 적는다("두개 다 적어줘"). 헤더가 없으면 이때 만든다.
    if not str(ws.cell(row=1, column=EXPORT_SN_COLUMN).value or "").strip():
        ws.cell(row=1, column=EXPORT_SN_COLUMN, value="S/N")
        # 옆 칸(자재명 등)과 같은 서식으로 보이도록 헤더 스타일을 복사한다
        try:
            src, dst = ws.cell(row=1, column=7), ws.cell(row=1, column=EXPORT_SN_COLUMN)
            dst.font = copy(src.font)
            dst.fill = copy(src.fill)
            dst.border = copy(src.border)
            dst.alignment = copy(src.alignment)
        except Exception as e:
            log(f"[정보] S/N 헤더 서식 복사 생략: {e}")
        log("수출신고실적: 'S/N' 열(N) 신규 생성")

    row = ws.max_row + 1
    for p in parts_qty:
        ws.cell(row=row, column=1, value=country_code)          # Destination
        ws.cell(row=row, column=2, value=purpose)                # Purpose(Rebalance/RMA)
        ws.cell(row=row, column=3, value=ship_day)               # 수출일자
        ws.cell(row=row, column=4, value=bl_no)                  # B/L번호
        ws.cell(row=row, column=5, value=p.get("hs_code") or hs_code)  # HS code
        ws.cell(row=row, column=6, value=p.get("part_no"))       # 자재코드(P/N)
        ws.cell(row=row, column=7, value=p.get("description"))   # 자재명
        ws.cell(row=row, column=8, value=p.get("qty"))           # 수량
        ws.cell(row=row, column=9, value=p.get("unit_price"))    # 단가
        ws.cell(row=row, column=10, value=p.get("amount"))       # 금액
        ws.cell(row=row, column=11, value=to_number)             # SO(=TO#)
        ws.cell(row=row, column=12, value=delivery_no)           # Delivery Number
        # 원산지(2자 코드) - 인보이스의 Country of Origin 값. 예전 코드는
        # 'country_2letter' 키를 봤는데 그 키를 채우는 곳이 없어 항상 비었다.
        ws.cell(row=row, column=13, value=p.get("origin") or p.get("country_2letter"))
        sns = p.get("serials") or []
        ws.cell(row=row, column=EXPORT_SN_COLUMN,
                value=", ".join(str(s) for s in sns) if sns else None)  # S/N
        row += 1

    wb.save(EXPORT_DECLARATION_PATH)
    log(f"수출신고실적 append 완료: TO#{to_number}, Delivery {delivery_no}, {len(parts_qty)}건")


# ==============================================================
# 14) 최종 인보이스 CI 폴더 저장 (완전 구현)
# ==============================================================
def save_final_invoice_to_ci_folder(country_code: str, delivery_no: str, source_path: str,
                                    suffix: str = "") -> str:
    """CI 폴더 기존 파일 실측 확인(2026-08-04): "KRP-{국가코드} {Delivery Number}.xlsx"
    형식(예: KRP-AUP 9969738.xlsx).

    2026-08-18: RMA 건은 예전 수기 처리분이 "KRP - FA LAB - 9887298 (RMA).pdf"
    처럼 (RMA) 표시를 달고 있어 나중에 폴더에서 바로 구분된다 - 최신 파일명
    규칙에 이 표시만 붙여 "KRP-FA LAB 9887298 (RMA).pdf"로 저장한다."""
    ext = os.path.splitext(source_path)[1]
    dest_name = f"KRP-{country_code} {delivery_no}{suffix}{ext}"
    dest_path = os.path.join(CI_FOLDER_PATH, dest_name)
    shutil.copy2(source_path, dest_path)
    log(f"최종 인보이스 CI 폴더 저장: {dest_path}")
    return dest_path


def create_yongma_ci_reply_draft(reply_entry_id: str, pdf_path: str,
                                 extra_attachments: list[str] | None = None) -> str | None:
    """Ship To/Bill To 보정까지 끝난 최종 CI를 용마에게 넘겨주는 초안을 만든다
    (2026-08-06 사용자 요청). 새 메일이 아니라 위치정보를 알려준 **원래 그
    용마 회신에 "전체 답장"**으로 만들어서 같은 스레드에 남게 한다.

    자동발송이 아니라 초안(.Save())만 남긴다 - 이 automation의 다른 완료
    알림(send_alert)은 전부 내 앞으로 오는 draft라 사람이 봐야만 아는데,
    이건 외부 벤더(용마)에게 실제로 나가는 메일이라 이 automation에서 지금까지
    외부로 자동발송하는 건 create_yongma_request_mail() 하나뿐이었던 것과
    결이 다르다고 판단 - 보내기 전에 한 번 검토할 수 있게 초안으로 남긴다.

    reply_entry_id로 못 찾으면(예: 메일이 이동/삭제됨) 예외를 올리지 않고
    None을 반환한다 - 이 단계는 부가 기능이라 실패해도 파이프라인 본체
    (수출신고실적 append 등)를 막으면 안 된다(호출부에서 try/except로 감쌈)."""
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    try:
        original = ns.GetItemFromID(reply_entry_id)
    except Exception as e:
        log(f"[경고] 용마 CI 답장 초안 실패 - 원본 메일을 못 찾음(entry_id={reply_entry_id}): {e}")
        return None

    reply = original.ReplyAll()

    # **2026-08-06 서식 깨짐 수정(사용자 지적)**: 예전엔 `reply.Body`(평문)에
    # 인사말+기존 본문을 다시 대입했는데, 용마 회신은 HTML 메일이라 .Body에 값을
    # 넣는 순간 Outlook이 메일 전체를 평문/RTF로 강등시킨다 - 그러면 Exchange가
    # 인용된 원본을 "Converted from text/rtf format" 굴림체 마크업으로 변환해서
    # 표/외부메일 배너/서명 이미지가 전부 깨진 초안이 만들어졌다(실측: 8/6에
    # 만들어진 초안 3건 전부 이 상태). 원본 서식을 건드리지 않으려면 HTML 쪽에
    # 인사말 문단만 끼워 넣어야 한다.
    greeting_lines = ["안녕하세요 기훈님 용호님", "해당선적 서류 전달드립니다"]
    html = str(getattr(reply, "HTMLBody", "") or "")
    if html:
        greeting_html = (
            "<div style=\"font-family:'맑은 고딕',Malgun Gothic,sans-serif;font-size:10.0pt\">"
            + "<br>".join(greeting_lines)
            + "<br><br></div>"
        )
        # <body ...> 바로 뒤(=본문 맨 위, 서명/인용 원본보다 앞)에 삽입한다.
        m = re.search(r"<body[^>]*>", html, re.IGNORECASE)
        insert_at = m.end() if m else 0
        reply.HTMLBody = html[:insert_at] + greeting_html + html[insert_at:]
    else:
        # 원본이 평문 메일인 경우에만 예전 방식(여태 용마 회신은 전부 HTML이었음)
        reply.Body = "\n".join(greeting_lines) + "\n\n" + str(reply.Body or "")

    attached = [pdf_path]
    reply.Attachments.Add(pdf_path)
    # 2026-08-18: RMA는 Foreign Shipper Declaration을 같이 첨부한다.
    for extra in extra_attachments or []:
        if extra and os.path.exists(extra):
            reply.Attachments.Add(extra)
            attached.append(extra)
        elif extra:
            log(f"[경고] 첨부할 파일이 없어 건너뜀: {extra}")
    reply.Save()
    log(f"[Yongma] CI 답장 초안 저장(전체 답장, 첨부: "
        f"{', '.join(os.path.basename(a) for a in attached)})")
    return reply.EntryID


# ==============================================================
# 5~14) 전체 파이프라인 (Create Pick Wave부터 CI 저장까지)
# ==============================================================
def process_rebalance_to(to_number: str, start_at: str = "pickwave",
                         shipment_no: str | None = None):
    """용마 회신까지 다 받은 TO#에 대해 5~14단계(Create Pick Wave -> Release
    Now -> Confirm Pick Slips -> Ship Confirm -> SharePoint Delivery# 기입 ->
    ICBL 인보이스 -> Bill To/Ship To/HTS 보정 -> CI 폴더 저장 -> 수출신고실적
    기입)를 순서대로 실행한다.

    2026-08-05 TO 7866440으로 이 순서 전체를 사용자와 함께 실측 검증했고,
    같은 날 run_yongma_scan()에서 사람 명령 없이 바로 호출하도록 연결했다
    (TO#가 확실히 매칭된 케이스에 한해서만). 물리적 재고 이동을 일으키는
    단계(Release Now, Confirm Pick Slips)가 포함돼 있으니 초기 자동 실행
    몇 건은 완료 알림 메일과 CI 폴더 결과물을 챙겨 확인할 것.

    2026-08-06: 여러 TO를 동시에(MAX_PARALLEL_TO건) 돌리게 되면서, 이 함수는
    [[pick-release-watcher]]의 `_process_single_order`처럼 **자기 전용 탭을 직접
    열고 끝나면 반드시 닫는다** - 예전엔 열기만 하고 안 닫아서 실행마다 탭이
    남았는데, 병렬로 돌리면 그 누수가 배로 쌓이고 잔여 팝업/탭이 오라클 화면
    조작을 방해한 전례가 있다([[icbl-ci-watcher-automation]] 2026-08-05)."""
    global _ACTIVE_WORKERS
    with _ACTIVE_LOCK:
        _ACTIVE_WORKERS += 1
    try:
        progress: dict = {}
        try:
            _run_once(to_number, start_at, shipment_no, progress)
            return
        except Exception as e:
            if not _should_restart_browser(e):
                raise
            if progress:
                log(f"[에스컬레이션] TO {to_number}: 화면 문제로 보이지만 이번 시도에서 "
                    f"이미 되돌릴 수 없는 단계를 지나서({sorted(progress)}) 브라우저 "
                    f"재시작 재시도를 하지 않음 - 중복 처리 위험")
                raise
            with _ACTIVE_LOCK:
                alone = _ACTIVE_WORKERS == 1
            if not alone:
                log(f"[에스컬레이션] TO {to_number}: 다른 워커가 동시에 실행 중이라 "
                    f"Edge 재시작을 생략함(남의 탭을 죽이게 됨)")
                raise
            log(f"[에스컬레이션] TO {to_number}: 오라클 화면 진입이 반복 실패 "
                f"({type(e).__name__}) - 자동화 전용 Edge를 껐다 켜고 한 번 더 시도")
            _restart_browser_and_login()
            _run_once(to_number, start_at, shipment_no, {})
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_WORKERS -= 1


# 2026-08-06 실측으로 확인한 패턴: 같은 코드가 Edge 재시작 직후에는 정상 동작하는데
# (11:54 재시작 -> 12:49/13:00 CI 성공) 같은 브라우저를 오래 쓰며 탭을 많이 열고
# 닫으면 Tools > Scheduled Processes 클릭이 조용히 먹지 않게 된다(13:30~ 반복 실패,
# 딥링크 URL 3종도 전부 실패). 코드가 아니라 브라우저/ADF 세션 수명 문제로 판단해,
# 화면 진입류 실패가 재시도까지 소진했을 때 마지막으로 Edge를 껐다 켜고 한 번 더
# 시도한다. 저수준 이동 함수가 아니라 TO 처리 단위에 두는 이유는, 병렬 워커가 도는
# 중에 Edge를 죽이면 남의 탭까지 날아가기 때문이다(위 alone 검사 참고).
_ACTIVE_WORKERS = 0
_ACTIVE_LOCK = threading.Lock()

# 화면 진입/요소 탐색류 증상 - 브라우저를 새로 띄우면 대개 해소된다.
# 2026-08-14 추가: "Tools 탭을 못 찾음".
# icbl_ci_watcher._goto_scheduled_processes가 오라클 홈이 안 그려질 때 내는 메시지로
# ("오라클 홈이 20초 안에 렌더되지 않음(Tools 탭을 못 찾음)"), 세션이 죽어 로그인
# 화면이 떠 있을 때의 대표 증상이다 - 즉 Edge 재시작으로 풀리는 바로 그 부류다.
# 그런데 목록에 있던 건 "Tasks"(Inventory Management 화면의 Tasks 아이콘)라서
# **Tools/Tasks 한 단어 차이로 매칭에서 새어나갔다**. 실측 TO 7872710
# (2026-08-14 17:26~17:29): 9번 전부 이 메시지로 실패했는데 에스컬레이션이 발동조차
# 하지 않고 바로 위로 올라갔다(아침 17:01 회차에서는 "클릭할 요소를 못 찾음"이라
# 걸려서 Edge 재시작 -> 로그인 복구 -> 정상 진행됐던 것과 같은 원인, 다른 문구).
_RESTART_HINTS = (
    "Scheduled Processes", "Tasks", "클릭할 요소를 못 찾음",
    "no such element", "stale element", "Inventory Management",
    "Tools 탭을 못 찾음",
)


def _should_restart_browser(exc: Exception) -> bool:
    msg = str(exc)
    # 우리가 의도적으로 멈춘 안전장치(수량 불일치, 검증 실패 등)는 재시도 대상이 아니다.
    if "중단함" in msg or "확인 필요해서" in msg:
        return False
    return any(h in msg for h in _RESTART_HINTS)


# Edge를 껐다 켠 뒤 디버그 포트가 열리기를 기다리는 한도(초).
# 폴링이라 열리는 즉시 진행하므로 넉넉히 잡아도 정상 회차엔 영향이 없다.
EDGE_RECONNECT_TIMEOUT_SEC = 60
EDGE_RECONNECT_POLL_SEC = 3


def _connect_after_restart():
    """Edge 재시작 직후, 디버그 포트가 실제로 열린 걸 확인하고 드라이버를 만든다.

    2026-08-19 실측(TO 7872959): 고정 8초만 쉬고 바로 드라이버를 만들다가
    "session not created: cannot connect to microsoft edge at 127.0.0.1:9333"으로
    실패했다. 죽인 프로세스가 많을수록(그날 11개) 재기동이 늦어지므로 고정 대기
    대신 포트를 폴링한다."""
    deadline = time.time() + EDGE_RECONNECT_TIMEOUT_SEC
    while True:
        if _debug_port_open():
            try:
                return get_oracle_driver_isolated()
            except Exception as e:
                log(f"  [에스컬레이션] 포트는 열렸으나 드라이버 생성 실패"
                    f"({exc_detail(e)}) - 재시도")
        else:
            log("  [에스컬레이션] Edge 디버그 포트가 아직 안 열림 - 대기")
        if time.time() >= deadline:
            break
        time.sleep(EDGE_RECONNECT_POLL_SEC)
    # 한도를 넘겼으면 Edge가 아예 안 뜬 것으로 보고 한 번 더 띄운 뒤 마지막 시도.
    # (여기서도 실패하면 예외가 그대로 올라가 호출부의 기존 처리를 탄다)
    log(f"  [에스컬레이션] {EDGE_RECONNECT_TIMEOUT_SEC}초 안에 연결 못함 "
        f"- Edge를 한 번 더 띄우고 마지막으로 연결 시도")
    ensure_edge_running()
    return get_oracle_driver_isolated()


def _restart_browser_and_login():
    """자동화 전용 Edge를 껐다 켜고 오라클 로그인까지 복구한다.

    2026-08-06(2차): 재시작 뒤의 로그인 복구를 공용 사다리
    (icbl_ci_watcher.recover_oracle_login)로 통일했다. 예전에는 SSO를 딱 한 번만
    시도하고 실패하면 바로 포기했는데, 사다리는 그 사이에 '오라클 URL 재진입 후
    재시도'를 한 단계 더 넣어준다(실측상 가장 값싸고 효과적인 복구). 이 함수는
    바로 위에서 이미 Edge를 재시작했으므로 사다리의 3단계(또 재시작)는
    allow_restart=False로 건너뛴다.

    2026-08-19: 재시작 직후 연결을 **고정 8초 대기 -> 바로 드라이버 생성**으로
    하던 것을 포트가 열릴 때까지 폴링하도록 바꿨다(_connect_after_restart 참고).
    실측(TO 7872959, 11:47:34 재시작): Edge 프로세스 11개를 죽인 직후라 재기동이
    고정 대기보다 오래 걸렸고, "session not created: cannot connect to microsoft
    edge at 127.0.0.1:9333"으로 **에스컬레이션 자체가 실패**했다."""
    _force_restart_edge()
    driver = _connect_after_restart()
    try:
        if _wait_oracle_logged_in(driver):
            log("[에스컬레이션] Edge 재시작 후 오라클 로그인 확인됨")
            return
        ok, driver = recover_oracle_login(driver, log, allow_restart=False)
        if ok:
            log("[에스컬레이션] Edge 재시작 후 자동 복구로 로그인 확인됨")
            return
        raise OracleLoginRequired("Edge 재시작 후에도 오라클 로그인 복구 실패")
    finally:
        # close()만 하면 msedgedriver.exe가 남는다(close_driver 설명 참고, 2026-08-06)
        close_driver(driver)


# ==============================================================
# 오라클 로그인 사전 점검 (2026-08-19 추가)
# ==============================================================
# 2026-08-19 실측(TO 7874424/7874410/7872959 3건이 한 회차에 전부 실패):
# 자동화 전용 Edge가 안 떠 있어서 ensure_edge_running()이 새로 띄운 직후
# (11:45:05 "디버그 포트로 떠 있는 Edge가 없음 -> 새로 실행 시도") 곧바로
# 파이프라인에 들어갔는데, 25초 뒤부터 3건 모두 "클릭할 요소를 못 찾음:
# Supply Chain Execution"으로 죽었다.
#
# 원인은 **파이프라인 진입 전에 로그인을 확인/복구하는 단계가 아예 없었던 것**이다:
#   - _run_once()는 ensure_edge_running() -> get_oracle_driver_isolated() 다음에
#     바로 _run_rebalance_pipeline()을 불렀다. 로그인 여부를 아무도 안 봤다.
#   - 파이프라인의 첫 화면 전환(pick_release_watcher.navigate_to_create_pick_wave)은
#     홈을 연 뒤 "Supply Chain Execution" 텍스트를 **5초만** 기다린다. 콜드 스타트는
#     SSO 리다이렉트만으로도 5초를 훌쩍 넘기므로 그 자리에서 바로 실패한다.
#   - 게다가 그 시각엔 워커가 2개 떠 있어서, 마지막 수단인 Edge 재시작 에스컬레이션도
#     "다른 워커가 동시에 실행 중"이라 건너뛰었다 - 스스로 복구할 길이 없었다.
#   - 실제로 그날 SSO 재로그인 사다리는 세 번째 TO가 에스컬레이션을 탄 11:47:34에야
#     처음 돌았다(그마저도 Edge 재시작 직후 9333 포트가 안 올라와 실패).
#
# 그래서 로그인 확인/복구를 **파이프라인보다 앞에** 둔다. 이미 로그인돼 있으면
# oracle_is_logged_in() 한 번(내부 2초 대기)으로 끝나므로 정상 회차의 비용은 거의 없다.
ORACLE_READY_TIMEOUT_SEC = 90   # 콜드 스타트 후 홈이 '로그인된 상태'로 그려질 때까지의 한도
ORACLE_READY_POLL_SEC = 3
# 로그인 페이지에 앉아 있는 게 확실해도 리다이렉트 체인이 아직 끝나는 중일 수 있어
# 이 시간만큼은 판정을 미룬다(그 뒤엔 더 기다려도 저절로 로그인되지 않는다).
SIGNIN_PAGE_GRACE_SEC = 12


def _on_signin_page(driver) -> bool:
    """지금 화면이 '로그인 페이지'인 게 명확한가.

    oracle_is_logged_in()과 같은 URL 단서를 쓴다. 이 판정이 True여도 실제로는
    로그인돼 있을 가능성이 남지만, 그 경우 복구 사다리 0단계가 '이미 로그인됨'으로
    즉시 통과시켜 주므로 손해가 없다 - 반대로 로그인 페이지에서 90초를 다 기다리는
    건 순수한 낭비다(2026-08-19 실측: 콜드 스타트 검증에서 131초 중 90초가 이 대기)."""
    try:
        url = (driver.current_url or "").lower()
    except Exception:
        return False
    return ("signin" in url or "login" in url or "microsoftonline" in url)


def _wait_oracle_logged_in(driver, timeout: float = ORACLE_READY_TIMEOUT_SEC) -> bool:
    """오라클 홈을 열고 '로그인된 상태'가 될 때까지 기다린다(되면 즉시 True).

    간격 폴링이라 준비되는 즉시 반환하므로 timeout을 넉넉히 잡아도 정상 회차의
    속도에는 영향이 없다(느릴 때만 더 기다려줄 뿐) - pick_release_watcher의
    INV_PAGE_READY_TIMEOUT_SEC와 같은 사고방식이다."""
    try:
        _ensure_my_tab(driver)
        driver.get(ORACLE_HOME_URL)
    except Exception as e:
        # 여기서 실패해도 아래 판정/복구 사다리가 다시 시도하므로 치명적이지 않다.
        log(f"[사전점검] 오라클 홈 이동 중 오류(복구 사다리로 넘김): {exc_detail(e)}")
        return False
    started = time.time()
    deadline = started + timeout
    while True:
        try:
            if oracle_is_logged_in(driver):   # 이 함수 안에 2초 대기가 들어있다
                return True
            if (time.time() - started >= SIGNIN_PAGE_GRACE_SEC
                    and _on_signin_page(driver)):
                log("[사전점검] SSO 로그인 페이지에 머물러 있음 "
                    "- 남은 대기를 건너뛰고 복구 사다리로 즉시 전환")
                return False
        except Exception as e:
            if is_session_dead_error(e):
                # 세션이 죽었으면 같은 driver로 더 기다려봐야 결과가 같다.
                log(f"[사전점검] 로그인 판정 중 브라우저 세션이 끊김: {exc_detail(e)}")
                return False
            log(f"[사전점검] 로그인 판정 중 오류(계속 폴링): {exc_detail(e)}")
        if time.time() >= deadline:
            return False
        time.sleep(ORACLE_READY_POLL_SEC)


def ensure_oracle_logged_in(driver, *, where: str, allow_restart: bool):
    """파이프라인에 들어가기 전에 로그인을 보장한다. 반환: 앞으로 쓸 driver.

    복구 사다리(recover_oracle_login)는 3단계에서 Edge를 재시작하며 **드라이버를
    새로 만들어 반환**하므로, 호출부는 반드시 반환값을 다시 받아 써야 한다.
    allow_restart는 병렬 워커가 도는 중에 남의 탭을 죽이지 않기 위한 것으로,
    기존 에스컬레이션의 alone 검사와 같은 기준을 쓴다."""
    if _wait_oracle_logged_in(driver):
        log(f"[사전점검] {where}: 오라클 로그인 확인됨")
        return driver
    # 문구 주의: 로그인 페이지가 확실하면 한도를 다 안 쓰고 일찍 빠져나온다
    # (위 _on_signin_page) - "90초를 다 기다렸다"고 읽히지 않게 적는다.
    log(f"[사전점검] {where}: 로그인 상태 확인 실패(대기 한도 {ORACLE_READY_TIMEOUT_SEC}초) "
        f"-> 자동 복구 사다리 시작(Edge 재시작 허용={allow_restart})")
    ok, driver = recover_oracle_login(driver, log, allow_restart=allow_restart)
    if not ok:
        raise OracleLoginRequired(f"{where}: 파이프라인 진입 전 오라클 로그인 복구 실패")
    log(f"[사전점검] {where}: 자동 복구로 오라클 로그인 확인됨")
    return driver


def ensure_oracle_ready_before_fanout() -> None:
    """워커를 띄우기 **전에 단독으로** 오라클 로그인을 확정한다.

    단독 시점이라 복구 사다리의 3단계(Edge 재시작)까지 안전하게 쓸 수 있다는 게
    핵심이다 - 워커가 뜬 뒤엔 남의 탭을 죽이게 돼서 그 수단을 못 쓴다.
    여기서 로그인이 확정되면 이후 워커들은 이미 로그인된 세션을 물려받는다."""
    ensure_edge_running()
    driver = get_oracle_driver_isolated()
    try:
        driver = ensure_oracle_logged_in(
            driver, where="파이프라인 시작 전", allow_restart=True)
    finally:
        # 복구 3단계를 타면 위 driver는 이미 닫힌 것일 수 있다(그 경우 close_driver가
        # 조용히 무시한다). 여기서 드라이버를 닫아도 디버그 포트로 붙은 Edge 자체는
        # 살아있으므로, 로그인된 세션은 워커들이 그대로 물려받는다.
        try:
            close_driver(driver)
        except Exception:
            pass


def _run_once(to_number: str, start_at: str, shipment_no: str | None, progress: dict):
    ensure_edge_running()
    driver = get_oracle_driver_isolated()
    try:
        # 2026-08-19: 파이프라인 첫 화면 전환이 홈 텍스트를 5초만 기다리므로,
        # 로그인이 안 된 채로 들어가면 곧바로 "클릭할 요소를 못 찾음"이 된다.
        # 위 fanout 사전점검이 있어도 이 자리를 한 번 더 지키는 이유:
        #   - 수동 'process <TO#>' 실행은 fanout 경로를 안 타고 여기로 바로 들어온다
        #   - 앞선 TO를 처리하는 동안 세션이 끊길 수 있다(회차가 길다)
        # 이미 로그인돼 있으면 판정 한 번으로 끝나 비용이 거의 없다.
        with _ACTIVE_LOCK:
            alone = _ACTIVE_WORKERS <= 1
        driver = ensure_oracle_logged_in(
            driver, where=f"TO {to_number}", allow_restart=alone)
        _run_rebalance_pipeline(to_number, driver, start_at=start_at,
                                shipment_no=shipment_no, progress=progress)
    finally:
        # TO 1건마다 드라이버를 새로 만들고(동시 2건) 이 함수가 회차마다 반복
        # 호출되므로, 프로세스까지 정리하지 않으면 msedgedriver.exe가 쌓인다
        # (close()는 탭만 닫는다 - close_driver 설명 참고, 2026-08-06).
        close_driver(driver)


def _start_fedex_arrangement(to_number: str, country_code: str, is_rma: bool,
                             reply_entry_id: str | None, ci_pdf_path: str) -> None:
    """CI/용마 답장 초안 생성까지 끝난 TO를 fedex_ship_watcher의 픽업 어레인지로
    바로 넘긴다(2026-08-25 사용자 지시: "CI 초안이 작성되면서 바로 실행되게").

    - 박스 제원(무게/가로x세로x높이)은 용마 회신 **원본**(reply_entry_id) 본문에서
      파싱한다 - pending_cases에는 위치정보(part/locator/qty)만 저장되고 박스
      물리 정보는 저장되지 않기 때문.
    - arrange는 FedEx 요약 보기 **직전까지** 자동이다. 완료(라벨 발행)는 사람이
      확인하고 누르고, 그 뒤 label/track 모드로 용마 답장 첨부 + SharePoint/
      수출신고실적 Tracking 기입을 이어간다(fedex_ship_watcher 참고).
    - RMA는 발송 용도(수리 및 반환 등) 규칙이 미확정이라 자동 진행하지 않고
      알림만 남긴다.
    - 여기서 raise하면 호출부가 알림으로 처리한다. 파이프라인 본체는 이미 전부
      완료된 뒤라 rebalance 결과에는 영향이 없다.
    - RMA는 2026-09-15부터 Rebalance와 동일하게 자동 진행한다(사용자 확정:
      발송 용도는 '수리 및 반환'). arrange_fedex_pickup(is_rma=...)로 넘긴다."""
    # 2026-08-27 사용자 확인("한 TO에 shipment가 2개여도 무조건 TO 기준으로 하면 돼
    # FedEx도 그렇게 잡으니까"): **FedEx는 TO당 한 번**이다. 배송이 2건이면 이
    # 함수가 배송마다 한 번씩(=두 번) 불리는데, 그대로 두면 같은 TO로 발송물이
    # 두 개 생긴다. 이미 그 TO의 라벨이 있으면 어레인지가 끝난 것이므로 건너뛴다.
    already = find_fedex_labels(to_number)
    if already:
        log(f"[Pipeline] TO {to_number}: 이미 FedEx 라벨이 있어 어레인지 생략 "
            f"(TO 기준 1회, {', '.join(os.path.basename(p) for p in already)})")
        return

    # 2026-08-27 사용자 지시: 일본(JPP)은 FedEx로 보내지 않는다 - arrange 전까지만.
    # 2026-09-15 사용자 지시("일본건은 DHL 나머지는 Fedex로"): FedEx 대신 DHL
    # Express로 자동 어레인지한다(dhl_export_arrange 재사용).
    if str(country_code).upper() in FEDEX_SKIP_COUNTRIES:
        log(f"[Pipeline] TO {to_number}({country_code}"
            f"{'/' + COUNTRY_NAME_MAP[country_code.upper()] if country_code.upper() in COUNTRY_NAME_MAP else ''})"
            f"는 FedEx 발송 대상이 아님 - DHL로 어레인지")
        _start_dhl_arrangement(to_number, country_code, reply_entry_id, ci_pdf_path)
        return

    import fedex_ship_watcher as fedex

    body = None
    if reply_entry_id:
        try:
            import win32com.client
            ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
            body = str(ns.GetItemFromID(reply_entry_id).Body or "")
        except Exception as e:
            log(f"[정보] TO {to_number} 용마 회신 원본 열람 실패({e})")
    if not body:
        # 2026-08-26: reply_entry_id가 없는 케이스(7877405처럼 사용자가 수동으로
        # 진행한 뒤 resume하는 경우) 폴백 - Yongma 폴더에서 TO#로 회신을 찾는다.
        body = fedex._find_yongma_reply_body(to_number)
        if body:
            log(f"[정보] TO {to_number} 용마 회신을 폴더에서 직접 찾았습니다")
    packages = fedex.parse_yongma_dims(body) if body else None
    if not packages:
        send_alert(
            f"[Rebalance TO {to_number}] 용마 제원 파싱 실패 - FedEx 자동 진행 생략",
            "용마 회신에서 박스 무게/크기를 못 찾았습니다(회신 형식 확인 필요).\n"
            f"수동 실행: python fedex_ship_watcher.py ship {country_code} "
            f"--to {to_number} --boxes \"[...]\"",
        )
        return

    lock = fedex._acquire_singleton_lock()
    if lock is None:
        send_alert(
            f"[Rebalance TO {to_number}] FedEx 다른 실행 중 - 자동 진행 생략",
            f"수동 실행: python fedex_ship_watcher.py ship {country_code} "
            f"--to {to_number} --boxes {packages}",
        )
        return
    try:
        log(f"[Pipeline] TO {to_number} FedEx 픽업 어레인지 자동 시작 "
            f"(최종 생성까지, 제원={packages})")
        # 2026-09-09 사용자 지시("fedex 최종 라벨 생성까지는 왜안해?"): 최종
        # 생성까지 자동으로 간다. 2026-08-25에는 되돌릴 수 없는 단계라 요약
        # 화면에서 멈추고 사람이 확정하기로 했었는데, 그 뒤 매 건마다 수동으로
        # --confirm을 돌리고 있어서 체크포인트가 실질적인 역할을 못 했다.
        # 생성 후처리(라벨을 용마 답장에 붙여 발송 + SharePoint Tracking/Status
        # + 수출신고실적 B/L)까지 이어서 실행한다 - 이걸 빼면 발송물만 만들어지고
        # 기록이 전부 누락된다.
        # 2026-09-16 임시 안전장치: RMA는 오늘 처음 실제로 자동 트리거를 타는
        # 케이스라(TO 7881992), 검증 전까지는 confirm=False로 요약 화면에서
        # 멈추게 한다 - 확인 끝나면 이 if는 지운다.
        _rma_first_run_confirm = not is_rma
        result = fedex.arrange_fedex_pickup(
            country_code, packages, to_number=to_number,
            ci_pdf_path=ci_pdf_path, stop_at=None, confirm=_rma_first_run_confirm,
            is_rma=is_rma) or {}
        if _rma_first_run_confirm:
            fedex._post_confirm_followups(to_number, country_code, result,
                                          send_mail=True)
    finally:
        try:
            lock.close()
        except Exception:
            pass


def _start_dhl_arrangement(to_number: str, country_code: str,
                           reply_entry_id: str | None, ci_pdf_path: str) -> None:
    """일본(JPP)은 FedEx 대신 DHL Express로 보낸다(2026-09-15 사용자 지시:
    "일본건은 DHL 나머지는 Fedex로"). CI/용마 답장 초안 생성까지 끝난 TO를
    dhl_export_arrange의 픽업 어레인지로 바로 넘긴다 - _start_fedex_arrangement
    와 같은 구조(제원 파싱/락/실패 시 알림)를 그대로 따른다.

    - confirm=True로 넘겨서 '완료'(실제 운송장 생성)까지 자동 진행한다
      (2026-09-15 사용자 확인: "완료까지 전부 자동(FedEx와 동일)"). DHL은
      finalize_after_creation이 라벨 다운로드+용마 발송+SharePoint 기입까지
      한 번에 처리하므로, FedEx처럼 별도 _post_confirm_followups 호출이
      필요 없다.
    - 라벨 파일명에 TO#가 아니라 Delivery Number가 들어가므로(CI 파일명 규칙,
      [[ci-filename-is-delivery-number-not-to]]), 중복 어레인지 방지 체크는
      Delivery Number 기준으로 한다."""
    import glob
    import dhl_export_arrange as dhl

    m = re.search(r"(\d{5,8})", os.path.basename(ci_pdf_path))
    delivery_number = m.group(1) if m else None
    if delivery_number:
        already = glob.glob(os.path.join(dhl.DHL_LABEL_FOLDER, f"*{delivery_number}*"))
        if already:
            log(f"[Pipeline] TO {to_number}: 이미 DHL 라벨이 있어 어레인지 생략 "
                f"({', '.join(os.path.basename(p) for p in already)})")
            return

    body = None
    if reply_entry_id:
        try:
            import win32com.client
            ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
            body = str(ns.GetItemFromID(reply_entry_id).Body or "")
        except Exception as e:
            log(f"[정보] TO {to_number} 용마 회신 원본 열람 실패({e})")
    if not body:
        body = dhl._find_yongma_reply_body(to_number)
        if body:
            log(f"[정보] TO {to_number} 용마 회신을 폴더에서 직접 찾았습니다")
    packages = dhl.parse_yongma_dims(body) if body else None
    if not packages:
        send_alert(
            f"[Rebalance TO {to_number}] 용마 제원 파싱 실패 - DHL 자동 진행 생략",
            "용마 회신에서 박스 무게/크기를 못 찾았습니다(회신 형식 확인 필요).\n"
            f"수동 실행: python dhl_export_arrange.py ship --to {to_number} "
            f"--ci \"{ci_pdf_path}\" --boxes \"[...]\" --confirm",
        )
        return

    lock = dhl._acquire_singleton_lock()
    if lock is None:
        send_alert(
            f"[Rebalance TO {to_number}] DHL 다른 실행 중 - 자동 진행 생략",
            f"수동 실행: python dhl_export_arrange.py ship --to {to_number} "
            f"--ci \"{ci_pdf_path}\" --boxes {packages} --confirm",
        )
        return
    try:
        log(f"[Pipeline] TO {to_number} DHL 픽업 어레인지 자동 시작 "
            f"(최종 생성까지, 제원={packages})")
        dhl.arrange_dhl_shipment(
            to_number=to_number, ci_pdf_path=ci_pdf_path, packages=packages,
            stop_at=None, confirm=True)
    finally:
        try:
            lock.close()
        except Exception:
            pass


def _mark_stage_done(to_number: str, **fields) -> None:
    """pending_cases[to_number]에 되돌릴 수 없는 단계 완료 표시를 남긴다
    (2026-09-16 사용자 요청). 이미 이 TO가 pending_cases에서 지워졌으면
    (드물게 다른 스레드가 먼저 끝낸 경우) 조용히 무시한다 - 기록 실패가
    파이프라인 본체를 막으면 안 된다."""
    try:
        with _STATE_LOCK:
            state = load_state()
            case = state.get("pending_cases", {}).get(to_number)
            if case is None:
                return
            case.update(fields)
            save_state(state)
    except Exception as e:
        log(f"[경고] TO {to_number} 단계 기록 실패({exc_detail(e)}) - "
            f"다음 재개 시 자동 건너뛰기가 안 될 수 있음")


def _run_rebalance_pipeline(to_number: str, driver, start_at: str = "pickwave",
                            shipment_no: str | None = None,
                            progress: dict | None = None):
    """process_rebalance_to()의 본체. 탭 생성/정리는 호출부가 책임진다
    (2026-08-06 병렬화 때 분리).

    start_at: 어느 단계부터 시작할지(2026-08-06 추가).
      - "pickwave"(기본): 5단계부터 전부
      - "confirm": Create Pick Wave/Release Now는 이미 끝난 것으로 보고
        Confirm Pick Slips부터
      - "ci": Ship Confirm까지 끝난 것으로 보고 SharePoint 기입/ICBL 인보이스부터
        (이 경우 shipment_no 필수)

    **왜 필요한가(2026-08-06 실측)**: Release Now / Confirm Pick Slips / Ship
    Confirm은 오라클에서 한 번밖에 안 된다 - 이미 Release된 TO는 Create Pick Wave
    화면에서 검색조차 안 된다. 그런데 이 함수는 늘 5단계부터 시작하도록만 되어
    있어서, 중간에 깨진 TO는 재실행하면 첫 단계에서 또 실패했다(TO 7870379는 CI
    단계에서, 7870361/7866552는 Confirm Pick Slips에서 깨졌는데 셋 다 자동 복구가
    불가능했음). 그래서 "어디부터 이어갈지"를 받도록 했다."""
    if start_at not in ("pickwave", "confirm", "ship_confirm", "ci"):
        raise ValueError(f"start_at 값이 잘못됨: {start_at} (pickwave|confirm|ship_confirm|ci)")
    if start_at in ("ship_confirm", "ci") and not shipment_no:
        raise ValueError(f"start_at='{start_at}'로 재개할 때는 shipment_no(Delivery 번호)가 필요함")
    with _STATE_LOCK:
        state = load_state()
    pending = state.get("pending_cases", {})
    case = pending.get(to_number)
    if not case:
        raise RuntimeError(f"TO {to_number}가 pending_cases에 없음 - 트리거/용마 회신 단계부터 확인 필요")

    # 2026-09-16 사용자 요청: 되돌릴 수 없는 단계(Release Now/Ship Confirm)가
    # 끝나면 case에 기록해두고(_mark_stage_done 참고), start_at 기본값
    # (pickwave)으로 다시 불러도 자동으로 맞는 단계부터 이어간다 - 이미
    # Release된 TO를 또 Create Pick Wave로 열려다 모달에 막힌 사고(TO 7881076,
    # 2026-09-16) 재발 방지. 사용자가 start_at을 명시하면 그 값을 그대로 쓴다.
    if start_at == "pickwave":
        if case.get("ship_confirmed") and case.get("shipment_no"):
            log(f"[Pipeline] TO {to_number}: state 기록상 이미 Ship Confirm까지 "
                f"완료(Shipment {case['shipment_no']}) - CI 단계부터 자동으로 이어감")
            start_at = "ci"
            shipment_no = case["shipment_no"]
        elif case.get("released") and case.get("shipment_no"):
            log(f"[Pipeline] TO {to_number}: state 기록상 이미 Release Now+Confirm "
                f"Pick Slips 완료(Shipment {case['shipment_no']}) - Ship Confirm부터 "
                f"자동으로 이어감")
            start_at = "ship_confirm"
            shipment_no = case["shipment_no"]
        elif case.get("released"):
            log(f"[Pipeline] TO {to_number}: state 기록상 이미 Release Now 완료 - "
                f"Confirm Pick Slips부터 자동으로 이어감")
            start_at = "confirm"

    # 2026-08-18: RMA(본사 반송)는 Confirm Pick Slips에서 Source Locator를 넣는
    # 절차 자체가 없다(사용자 확인) - 그래서 용마 회신에 위치정보가 없어도 진행
    # 한다. confirm_pick_slips()는 locations가 비어 있으면 로케이터 기입/수량
    # 교차검증을 자동으로 건너뛰고 화면의 Requested Quantity만 쓰므로 그대로
    # 재사용할 수 있다(Rebalance 경로 동작은 그대로 - 여전히 위치정보 필수).
    is_rma = bool(case.get("is_rma"))
    locations = case.get("locations") or []
    # 2026-08-26: 위치정보 필수 체크는 실제로 locations를 쓰는 단계(pickwave/
    # confirm)에서만 한다. 7877405처럼 사용자가 Confirm Pick Slips를 수동으로
    # 마친 뒤 resume(ci)으로 이어가는 경우엔 용마 회신 파싱 결과가 없어도
    # Oracle 작업은 더 이상 필요 없으므로 막지 않는다.
    if not locations and not is_rma and start_at in ("pickwave", "confirm"):
        raise RuntimeError(f"TO {to_number}에 대한 용마 위치정보가 아직 없음 - 회신 대기 필요")

    country_code = case["country"]
    parts_qty = case["parts_qty"]
    if is_rma:
        log(f"[Pipeline] TO {to_number}는 RMA(본사 반송) 건 - 목적지 시트={country_code}, "
            f"HTS 고정={RMA_HTS_CODE}, 금액 {RMA_PRICE_RATIO:.0%} 적용, 로케이터 기입 생략")

    if start_at == "pickwave":
        # 2026-09-16 사용자 확인: RMA는 Rebalance와 다른 전용 Release Rule을
        # 쓴다(RMA_TRANSFER_ORDER_RELEASE_RULE 주석 참고) - Rebalance 경로
        # 동작은 그대로 둔다.
        pickwave_rule = RMA_TRANSFER_ORDER_RELEASE_RULE if is_rma else TRANSFER_ORDER_RELEASE_RULE

        # 화면 진입 + 폼 입력까지만 하는 단계(아직 실제 출고 아님)라 일시적 오라클
        # 오류면 같은 실행 안에서 재시도한다(2026-08-05).
        run_with_oracle_retry(
            f"TO {to_number} Create Pick Wave 입력",
            lambda: create_pick_wave_transfer_order(
                driver, to_number, release_rule=pickwave_rule, is_rma=is_rma),
        )

        # 2026-08-05 사용자 확인: Release Now / Confirm Pick Slips / Ship Confirm은
        # 오라클에서 한 번밖에 안 된다(이미 처리된 건은 검색 자체가 안 됨). 즉 재시도
        # 가 중복 처리를 만들 수 없으므로 이 단계들도 재시도 대상에 넣는다.
        # 다만 "이미 눌렀는데 그 다음 화면 읽기에서 터진" 경우엔 재시도해도 대상이
        # 안 잡혀 헛돌기만 하므로, progress로 그 지점을 기억해 바로 사람 확인으로
        # 넘긴다(특히 Shipment 번호는 잃어버리면 안 되는 값).
        release_progress = {}
        release_result = run_with_oracle_retry(
            f"TO {to_number} Release Now",
            lambda: release_pick_wave_now(driver, progress=release_progress,
                                          rule=pickwave_rule),
            should_retry=lambda e: not release_progress.get("released_clicked"),
            before_retry=lambda: create_pick_wave_transfer_order(
                driver, to_number, release_rule=pickwave_rule, is_rma=is_rma),
        )
        log(f"[Pipeline] TO {to_number} Release Now: {release_result}")
        # 되돌릴 수 없는 단계 통과 표시(에스컬레이션 재시도 판단용, 2026-08-06)
        if progress is not None:
            progress["released"] = True
        _mark_stage_done(to_number, released=True)

        # ---- 2026-08-27: 백오더 -> FG 룰로 한 번 더 (TRANSFER_ORDER_BACKORDER_RULE 주석 참고)
        # 2026-09-16 사용자 확인: RMA는 FG 룰 대상이 아니다("FG로 하면 진짜
        # 큰일난다") - 백오더가 나오면 자동 재릴리즈 없이 사람 확인 알림만 보낸다.
        sp_released = release_result.get("released_lines") or 0
        fg_released = 0
        fg_error = None
        if is_rma and (release_result.get("backordered_lines") or 0) > 0:
            log(f"[Pipeline] TO {to_number}(RMA) 백오더 "
                f"{release_result['backordered_lines']}건 감지 - FG 룰 자동 재릴리즈는 "
                f"RMA에 적용하지 않음, 사람 확인 필요")
            send_alert(
                f"[Rebalance TO {to_number}] RMA 백오더 - 자동 재릴리즈 보류",
                f"{RMA_TRANSFER_ORDER_RELEASE_RULE} 릴리즈에서 "
                f"{release_result['backordered_lines']}라인이 백오더로 남았습니다. "
                f"RMA는 KRP_Pick_Release_FG 자동 재릴리즈 대상이 아니므로(사용자 확인) "
                f"자동으로 진행하지 않았습니다 - 오라클에서 직접 확인해주세요.",
            )
        elif (release_result.get("backordered_lines") or 0) > 0:
            log(f"[Pipeline] TO {to_number} 백오더 "
                f"{release_result['backordered_lines']}건 감지 -> "
                f"{TRANSFER_ORDER_BACKORDER_RULE}로 추가 릴리즈")
            fg = release_backorder_with_fg(driver, to_number)
            fg_released = fg["released_lines"]
            fg_error = fg["error"]
            log(f"[Pipeline] TO {to_number} {TRANSFER_ORDER_BACKORDER_RULE} 추가 릴리즈: "
                f"released={fg_released}, backordered={fg['backordered_lines']}, "
                f"error={fg_error}")

        total_released = sp_released + fg_released

        # 한 라인도 안 뽑혔으면 Pick Slip 자체가 없다. 그대로 Confirm 단계로 가면
        # "그 TO의 행 자체가 없음"이라는 원인을 알 수 없는 에러로 3번 헛돌고 끝난다
        # (실측: TO 7876705, 2026-08-27 10:15~10:18). 여기서 원인을 그대로 적어 멈춘다.
        if total_released == 0:
            raise RuntimeError(
                f"TO {to_number}: Release Now에서 한 라인도 릴리즈되지 않음"
                f"(SP={sp_released}, FG={fg_released}, "
                f"백오더={release_result.get('backordered_lines')}"
                f"{f', FG 오류={fg_error}' if fg_error else ''}) - "
                f"두 서브인벤토리 모두에서 뽑을 수 있는 재고가 없다는 뜻이므로 "
                f"Pick Slip이 생기지 않았다. 오라클에서 재고/예약 상태를 확인해주세요."
            )

        # 2026-08-27 사용자 확인: "슬립 2장이 나올 경우는 없을텐데 TO 하나당 하나니까".
        # SP와 FG 양쪽에서 라인이 나와도 Pick Slip은 그 TO에 **한 장**이다. 그래서
        # 아래 Confirm은 언제나 단일 슬립 경로로 간다(2장을 가정하고 두 번째 슬립을
        # 찾으러 가면, 실제로 한 장일 때 못 찾아서 Ship Confirm을 못 하고 끝난다).
        if sp_released > 0 and fg_released > 0:
            log(f"[Pipeline] TO {to_number}: SP {sp_released}라인 + FG "
                f"{fg_released}라인이 한 Pick Slip에 들어감")

        if fg_error:
            send_alert(
                f"[Rebalance TO {to_number}] FG 추가 릴리즈 확인 필요",
                f"SP 룰 릴리즈는 {sp_released}라인으로 끝났고, 백오더분을 "
                f"{TRANSFER_ORDER_BACKORDER_RULE}로 한 번 더 돌리다 오류가 났습니다:\n"
                f"{fg_error}\n\n"
                f"백오더 라인이 실제로 릴리즈됐는지 오라클에서 확인해주세요. "
                f"이번 회차는 SP 릴리즈분으로 계속 진행합니다.",
            )
    else:
        log(f"[Pipeline] TO {to_number} 재개(start_at={start_at}) - Create Pick Wave/"
            f"Release Now는 이미 끝난 것으로 보고 건너뜀")

    if start_at in ("pickwave", "confirm"):
        confirm_progress = {}
        try:
            shipment_no = run_with_oracle_retry(
                f"TO {to_number} Confirm Pick Slips~Ship Confirm",
                lambda: confirm_pick_slips(driver, to_number, locations,
                                           progress=confirm_progress, is_rma=is_rma),
                should_retry=lambda e: not confirm_progress.get("shipment_no"),
                no_retry_exceptions=(ShipmentOnHold,),
            )
            if progress is not None:
                progress["ship_confirmed"] = True
        except ShipmentOnHold:
            # 담당자 알림/메일은 check_and_handle_shipment_exceptions()가 이미
            # 보냈다 - 여기서 또 send_alert하면 중복 알림이라 그대로 올린다.
            raise
        except Exception as e:
            if confirm_progress.get("shipment_no"):
                # Confirm이 이미 먹혀 Shipment까지 생긴 뒤에 터진 경우 - Pick Slip은
                # 사라져 자동 복구가 안 되므로, 번호를 알려주고 멈춘다(잘못된 값으로
                # 뒤 단계를 이어가지 않도록).
                send_alert(
                    f"[Rebalance TO {to_number}] Ship Confirm 확인 필요",
                    f"Confirm Pick Slips는 통과해 Shipment "
                    f"{confirm_progress['shipment_no']}까지 생성됐는데 그 뒤 단계에서 "
                    f"오류가 났습니다: {e}\n\n"
                    f"Ship Confirm이 실제로 끝났는지 오라클에서 확인해주세요. Pick Slip은 "
                    f"이미 처리된 상태라 자동 재시도로는 복구되지 않습니다.\n"
                    f"(ship_confirmed 기록: {confirm_progress.get('ship_confirmed', False)})\n"
                    f"이어서 진행하려면: python rebalance_watcher.py resume {to_number} ci "
                    f"{confirm_progress['shipment_no']}",
                )
            raise
    elif start_at == "ship_confirm":
        # 2026-09-16 사용자 요청(TO 7881076 실사례): Confirm Pick Slips까지는
        # 끝나 Shipment가 이미 있는데(예: Exceptions 오탐으로 Ship Confirm만
        # 막혔다가 다시 열어야 하는 경우) Manage Shipments에서 그 번호로 바로
        # 검색해 들어가 Ship Confirm만 실행한다.
        log(f"[Pipeline] TO {to_number} 재개(start_at=ship_confirm) - Manage Shipments에서 "
            f"Shipment {shipment_no} 검색 후 Ship Confirm만 실행")
        import oracle_shipment_tracking as ost

        def _goto_and_ship_confirm():
            ost.navigate_to_manage_shipments(driver)
            ost._search_shipment(driver, shipment_no)
            return _run_ship_confirm(driver, to_number, shipment_no, is_rma, progress)

        shipment_no = run_with_oracle_retry(
            f"TO {to_number} Ship Confirm 재개",
            _goto_and_ship_confirm,
            no_retry_exceptions=(ShipmentOnHold,),
        )
    else:
        log(f"[Pipeline] TO {to_number} 재개 - Confirm Pick Slips~Ship Confirm 건너뛰고 "
            f"주어진 Shipment {shipment_no}로 이어서 진행")

    # 아래 두 단계는 같은 값으로 다시 해도 결과가 같아(SharePoint 셀 기입,
    # 인보이스 리포트 재생성) 재시도해도 안전하다.
    run_with_oracle_retry(
        f"TO {to_number} SharePoint Delivery# 기입",
        lambda: write_delivery_to_sharepoint(driver, to_number, shipment_no,
                                             expected_rows=len(parts_qty) or None),
    )

    # CIStillWaiting은 '아직 안 끝났다'는 정상 신호라 재시도 대상이 아니다
    # (몇 초 뒤에 다시 봐도 결과가 같다) - 그대로 올려보내 회차를 끝낸다.
    pdf_path = run_with_oracle_retry(
        f"TO {to_number} ICBL 인보이스 생성(delivery={shipment_no})",
        lambda: run_icbl_invoice_krp_both(driver, shipment_no, to_number),
        no_retry_exceptions=(CIStillWaiting,),
    )

    # 2026-08-18: RMA는 인보이스의 HTS Code가 파트와 무관하게 고정값이고
    # (기존 수출 CI 생성기 ci_invoice_html.py의 RMA 모드와 같은 값),
    # **수출신고실적도 CI에 적힌 대로 기입한다**(사용자 지시: "수출신고실적에는
    # CI에 있는대로 기입해줘야지") - 그래서 CI와 실적표가 같은 값을 쓰고
    # 수입신고실적 조회/알림 자체가 필요 없다.
    if is_rma:
        hts_codes = {p.get("part_no"): RMA_HTS_CODE for p in parts_qty}
        log(f"[Pipeline] TO {to_number} RMA - HTS Code/HS code 전부 {RMA_HTS_CODE} 고정")
    else:
        # HTS Code는 파트마다 다를 수 있어 파트별로 조회한다. 못 찾으면
        # 2026-09-04 사용자 지시대로 기본값을 쓴다("HTS/HS code 없으면
        # 901890/9018909000으로 해줘"). 예전에는 빈 칸으로 두고 알림만 보냈는데,
        # 그러면 CI의 HS 칸이 비고 FedEx 물품 등록이 아예 막힌다(실측: TO 7878369
        # 의 7122-00-9592). 기본값을 썼다는 사실은 로그와 알림에 남긴다.
        hts_codes = {}
        for p in parts_qty:
            part_no = p.get("part_no")
            hts = lookup_hts_code(part_no)
            if hts is None:
                hts = HTS_CODE_FALLBACK
                log(f"[Pipeline] TO {to_number} {part_no}: 수입 이력에 HS code가 없어 "
                    f"기본값 {HTS_CODE_FALLBACK} 적용")
                # 2026-09-09 사용자 요청: 이런 정보성 알림은 메일로 보내지 않는다
                # ("중간중간 오는 알람 중요한 거 아니니 없애줘"). 위 로그로 남는다.
            hts_codes[part_no] = hts

    # 2026-08-06: Bill To/Ship To를 국가 주소로 통째 교체 + 모든 파트 행의 HTS를
    # 채운다(예전엔 첫 파트만 처리했고 주소는 미국 그대로였음).
    first_part = parts_qty[0].get("part_no") if parts_qty else None
    # RMA는 HTS를 여기서 넘기지 않는다 - 이 함수는 파트별 첫 행/1페이지만 채우는데
    # RMA는 같은 파트가 S/N별로 여러 줄, 여러 페이지에 걸쳐 나오므로
    # apply_rma_invoice_rules_in_pdf가 전 행을 덮어쓴다(그쪽 docstring 참고).
    patched_pdf = patch_bill_ship_to_and_hts_in_pdf(
        pdf_path, country_code, None if is_rma else hts_codes)

    # RMA는 단가/품목별 금액/합계 전부 10%로 다시 쓰고 통관 문구를 넣는다
    # (주소/HTS 패치 뒤에 적용).
    # 수출신고실적용 품목 파싱은 **할인 전 PDF**에서 하고 파이썬에서 같은 비율을
    # 곱한다(아래 참고) - 금액 span을 지우고 다시 그리면 PyMuPDF의 블록 묶음이
    # 달라져서 "SO/파트/자재명 + 원산지/수량/단가/금액" 한 행 구조가 깨지고
    # 단가/금액이 엉뚱하게 읽힌다(2026-08-18 실측으로 확인: unit=0.0, qty=None).
    parse_source = patched_pdf
    if is_rma:
        patched_pdf = apply_rma_invoice_rules_in_pdf(patched_pdf)

    final_path = save_final_invoice_to_ci_folder(
        country_code, shipment_no, patched_pdf, suffix=" (RMA)" if is_rma else "")

    # 수출신고실적에 쓸 자재명/원산지/단가/금액을 인보이스에서 읽어 parts_qty에
    # 채운다(2026-08-06 사용자 지적으로 추가 - 예전엔 이 칸들이 전부 비었음).
    # parse_source는 Rebalance면 final_path와 같은 내용(주소/HTS 패치본)이고,
    # RMA면 금액을 다시 쓰기 전의 같은 파일이다(위 설명 참고).
    invoice_items: dict = {}
    try:
        # 같은 파트가 S/N별로 여러 줄로 찍히면(RMA 실측 TO 7672306: 15파트/28줄)
        # 파트별 첫 행만 읽어서는 수량/금액이 실제보다 작게 들어간다 - 행을 전부
        # 읽어 파트별로 합산한다(과거 수기 이력과 같은 "파트당 한 줄" 형식).
        #
        # 2026-08-27: 이 합산을 RMA에만 적용하고 있었는데, **Rebalance도 시리얼
        # 관리 품목이면 똑같이 S/N별로 쪼개진다**. 실측(TO 7876705, Delivery
        # 9977111): 7123-00-0593 수량 2가 CI에 각 1개짜리 2줄(₩5,134,780 x2)로
        # 찍혔는데 첫 행만 읽어 수출신고실적에 1개/₩5,134,780으로 들어갔다
        # (같은 CI를 읽은 fedex_ship_watcher는 2개/₩10,269,560으로 맞게 읽어
        #  "수출신고실적 불일치" 경고를 냈다). 그래서 두 경로 모두 합산으로 통일한다.
        invoice_items = {
            str(a["part_no"]): a for a in aggregate_invoice_rows_by_part(
                parse_all_invoice_rows_from_pdf(parse_source))
        }
    except Exception as e:
        invoice_items = {}
        log(f"[경고] TO {to_number} 인보이스 품목 파싱 실패(자재명/단가/금액 없이 진행): {e}")
    if is_rma:
        # 인보이스에 찍힌 금액과 수출신고실적이 어긋나지 않게, 파싱한 정가에
        # 인보이스와 **똑같은 비율**을 곱한다(둘 다 원본 × 0.10이라 정확히 일치).
        for item in invoice_items.values():
            for key in ("unit_price", "amount"):
                if item.get(key) is not None:
                    item[key] = round(item[key] * RMA_PRICE_RATIO, 4)
    for p in parts_qty:
        item = invoice_items.get(str(p.get("part_no"))) or {}
        # serials: 2026-08-27 추가 - 수출신고실적 S/N 열에 그대로 들어간다
        for key in ("description", "origin", "unit_price", "amount", "serials"):
            if item.get(key) is not None:
                p[key] = item[key]
        p["hs_code"] = hts_codes.get(p.get("part_no"))
        # SharePoint 수량과 인보이스 SHIPPED 수량이 다르면 사람이 봐야 한다.
        if item.get("qty") is not None and p.get("qty") not in (None, item["qty"]):
            log(f"[경고] TO {to_number} 파트 {p.get('part_no')} 수량 불일치 "
                f"(SharePoint={p.get('qty')}, 인보이스={item['qty']}) - 인보이스 값 우선")
            p["qty"] = item["qty"]

    # 2026-08-18 사용자 요청: RMA는 CI와 함께 Foreign Shipper Declaration도
    # 만들어 같이 첨부한다(미국 반송품이 가공/가치상승 없이 되돌아간다는 선언서 -
    # 2025-12-09에 Delivery 9834927/9834928 건으로 실제 보낸 양식과 같은 형식).
    # 금액은 CI와 같은 10% 적용분(위에서 이미 곱해둔 invoice_items 값)을 쓴다.
    fsd_path = None
    if is_rma:
        try:
            fsd_items = [
                {
                    "part_no": part_no,
                    "description": item.get("description"),
                    "qty": item.get("qty"),
                    "value": item.get("amount"),
                }
                for part_no, item in invoice_items.items()
            ]
            fsd_path = build_foreign_shipper_declaration(
                os.path.join(CI_FOLDER_PATH,
                             f"Foreign Shipper Declaration {shipment_no}.xlsx"),
                shipment_no,
                parse_invoice_date_from_pdf(parse_source) or datetime.now(),
                fsd_items,
            )
        except Exception as e:
            log(f"[경고] TO {to_number} Foreign Shipper Declaration 생성 실패"
                f"(CI/실적은 정상 진행): {e}")

        # 2026-08-18 사용자 확인: RMA 서류는 본사(Robert Lazaros)에도 보내야 한다 -
        # 2025-12-08 발송분과 같은 형식으로 초안을 하나 더 만든다(CI+FSD 첨부).
        try:
            create_hq_rma_docs_draft(
                shipment_no, [final_path] + ([fsd_path] if fsd_path else []))
        except Exception as e:
            log(f"[경고] TO {to_number} 본사 앞 RMA 서류 초안 생성 실패"
                f"(파이프라인은 계속 진행): {e}")

    # 2026-08-20 사용자 요청: **미국(WAY)행 Rebalance 건은 본사 Bob 앞으로도**
    # 선적서류 메일을 쓴다(RMA가 아닌 일반 Rebalance 건 - RMA는 위에서 이미 별도
    # 초안을 만든다).
    # 2026-09-18 사용자 요청: **스페인(FBC/FBS)행은 Tamara 앞으로** 같은 방식으로
    # 보낸다(EU_HQ_MAIL_* 상수 설명 참고) - 목적지별 수신자/문구는
    # HQ_DOC_MAIL_PROFILES에 있고, 여기서는 프로필이 있는 목적지면 큐에 올린다.
    #
    # 2026-08-27: 여기서 바로 보내지 않고 **대기 큐에 쌓는다** - 배송이 여러 건인
    # TO는 CI도 여러 장이라 이 자리에서 보내면 먼저 나온 한 장만 나간다
    # (HQ_QUIET_MINUTES 설명의 TO 7876545 사례). 실제 발송은
    # process_hq_docs_pending()이 그 TO의 CI가 다 모이고 FedEx 라벨(=Tracking)이
    # 나온 뒤에 한다.
    # RMA 초안과 같은 원칙으로, 실패해도 파이프라인 본체는 계속 진행한다.
    if not is_rma and country_code in HQ_DOC_MAIL_PROFILES:
        try:
            queue_hq_docs(country_code, to_number, shipment_no, final_path)
        except Exception as e:
            log(f"[경고] TO {to_number} {country_code} 선적서류 메일 대기 등록 실패"
                f"(파이프라인은 계속 진행): {e}")

    # 2026-08-06 사용자 요청: Ship To/Bill To 보정까지 끝난 CI가 나오면, 위치
    # 정보를 받은 그 용마 회신에 전체 답장으로 서류를 첨부해 초안을 만든다.
    # reply_entry_id가 없으면(예: 사람이 'process <TO#>'를 수동 실행한 경우)
    # 그냥 생략하고, 있어도 실패하면 파이프라인 본체(수출신고실적 append 등)는
    # 계속 진행한다 - 이 단계는 부가 커뮤니케이션일 뿐 핵심 트랜잭션이 아니다.
    reply_entry_id = case.get("reply_entry_id")
    if reply_entry_id:
        try:
            create_yongma_ci_reply_draft(
                reply_entry_id, final_path,
                extra_attachments=[fsd_path] if fsd_path else None)
        except Exception as e:
            log(f"[경고] TO {to_number} 용마 CI 답장 초안 생성 실패(파이프라인은 계속 진행): {e}")
    else:
        log(f"[정보] TO {to_number} reply_entry_id 없음 - 용마 CI 답장 초안 생성 생략")

    # 2026-08-27 사용자 지적("수출신고실적 CI 기반으로 작성하는거 아니야?"):
    # **수출신고실적은 이 배송의 CI에 찍힌 것만 적어야 한다.** 예전엔 SharePoint에서
    # 읽은 TO의 파트 전부(parts_qty)를 그대로 append해서, 배송이 쪼개진 TO는
    # 다른 배송 소속 파트까지 같이 들어갔다 - 자재명/단가/금액이 빈 행이 되고
    # Delivery#도 엉뚱하게 붙는다(실측 TO 7876545: CI 9976051에는 7122-00-4050만
    # 있는데 7123-00-0593까지 append됨. 그 파트는 CI 9976055 소속이었다).
    # 그 파트는 해당 배송을 처리할 때 그 CI 값으로 들어간다.
    rows_to_append = parts_qty
    if invoice_items:
        matched = [p for p in parts_qty if str(p.get("part_no")) in invoice_items]
        skipped = [str(p.get("part_no")) for p in parts_qty
                   if str(p.get("part_no")) not in invoice_items]
        if matched:
            rows_to_append = matched
            if skipped:
                log(f"[정보] TO {to_number} Delivery {shipment_no}: 이 CI에 없는 파트 "
                    f"{', '.join(skipped)}는 수출신고실적에 넣지 않음 - 다른 배송의 "
                    f"CI에 있는 것으로 보고 그 배송 처리 때 기입됩니다")
        else:
            # CI는 읽혔는데 파트가 하나도 안 맞는 비정상 - 데이터를 버리지 않고
            # 예전처럼 전부 넣되 사람이 보게 알린다(파싱이 깨졌을 가능성).
            log(f"[경고] TO {to_number} Delivery {shipment_no}: CI에서 읽은 파트"
                f"({', '.join(invoice_items)})가 SharePoint 파트와 하나도 안 맞습니다 "
                f"- 일단 전부 append하고 알림을 보냅니다")
            send_alert(
                f"[Rebalance TO {to_number}] CI 파트와 SharePoint 파트 불일치 - 실적 확인 필요",
                f"Delivery {shipment_no} CI에서 읽은 파트: {', '.join(invoice_items)}\n"
                f"SharePoint 파트: {', '.join(str(p.get('part_no')) for p in parts_qty)}\n\n"
                f"수출신고실적에 SharePoint 파트 기준으로 append했습니다 - 값이 맞는지 "
                f"확인해주세요.",
            )

    # 엑셀은 파일 전체를 읽어 다시 저장하므로 동시 append 금지(2026-08-06 병렬화)
    with _EXCEL_LOCK:
        append_export_declaration(
            country_code=country_code,
            ship_date=datetime.now(),
            bl_no=None,  # 트래킹 번호는 실제 배정 후 별도로 채워야 함(2026-08-05 확인)
            hs_code=hts_codes.get(first_part),
            parts_qty=rows_to_append,
            to_number=to_number,
            delivery_no=shipment_no,
            purpose="RMA" if is_rma else "Rebalance",
        )
    # 엑셀 append는 멱등이 아니다(다시 하면 행이 중복된다) - 이 지점을 지났으면
    # 에스컬레이션 재시도를 하지 않는다.
    if progress is not None:
        progress["excel_appended"] = True

    # 2026-08-06: 다른 워커가 같은 state를 동시에 고칠 수 있으므로, 시작할 때
    # 읽어둔 dict를 그대로 저장하지 말고 락 안에서 파일을 다시 읽어 이 TO만
    # 지운다(안 그러면 상대 워커가 방금 지운 TO가 되살아난다).
    with _STATE_LOCK:
        fresh = load_state()
        fresh.setdefault("pending_cases", {}).pop(to_number, None)
        # 2026-08-19: CI 대기 큐에서도 뺀다. 여기까지 왔다는 건 CI가 나왔고 그 뒤
        # 단계(보정/저장/수출신고실적)까지 다 끝났다는 뜻이다. poll이 성공한 자리가
        # 아니라 **파이프라인 끝**에서 빼는 이유: 중간에서 빼면 그 뒤 단계가 실패했을
        # 때 큐에 아무것도 안 남아 아무도 이어받지 못한다.
        fresh["ci_pending"] = {
            k: v for k, v in (fresh.get("ci_pending") or {}).items()
            if not k.startswith(f"{to_number}:") and k != to_number}
        save_state(fresh)

    # 2026-09-09 사용자 요청: 성공 완료 알림은 메일로 안 보낸다(아래 로그로 충분).
    # FedEx까지 한 번에 가는 지금은 이게 '중간 알림'이 되어버렸다. 다만 RMA
    # 선언서를 못 만든 경우처럼 **사람이 손대야 하는 것**만 메일로 남긴다.
    if is_rma and not fsd_path:
        send_alert(
            f"[RMA TO {to_number}] Foreign Shipper Declaration 생성 실패",
            f"Shipment: {shipment_no}\nCI 파일: {final_path}\n\n"
            f"선언서를 만들지 못했습니다 - 양식으로 직접 작성해주세요.",
        )
    log(f"[Pipeline] TO {to_number} 전체 완료: Shipment={shipment_no}, CI={final_path}")

    # 2026-08-25: FedEx 픽업 어레인지 자동 트리거(fedex_ship_watcher 연동).
    # CI 저장 + 용마 답장 초안 생성이 모두 끝난 이 시점부터 fedex 흐름이 이어진다
    # (2026-09-09부터 최종 생성/라벨 발행까지 자동). 파이프라인 본체는 이미
    # 전부 완료된 뒤라 여기서 실패해도 rebalance 결과에는 영향이 없다.
    try:
        _start_fedex_arrangement(to_number, country_code, is_rma,
                                 case.get("reply_entry_id"), final_path)
    except Exception as e:
        import traceback
        log(f"[경고] TO {to_number} FedEx 픽업 자동 트리거 실패 - 수동 확인 필요: "
            f"{e}\n{traceback.format_exc()}")
        send_alert(
            f"[Rebalance TO {to_number}] FedEx 픽업 자동 트리거 실패",
            f"{e}\n\n수동 실행: python fedex_ship_watcher.py ship {country_code} "
            f"--to {to_number} --boxes \"[...]\"",
        )


# ==============================================================
# 진입점
# ==============================================================
def get_sharepoint_driver():
    """SharePoint만 볼 때 쓰는 드라이버 - **오라클 홈을 거치지 않는다**.

    2026-09-09 사용자 지적("apac movement 페이지 확인하는데 왜 오라클로 먼저
    들어가?"): 공용 헬퍼 get_oracle_driver_isolated()는 탭을 열고 항상
    ORACLE_HOME_URL로 이동한 뒤 2초 쉰다. 오라클을 쓰는 다른 자동화에는 맞지만,
    트리거 스캔은 SharePoint 조회 + Outlook 메일뿐이라 오라클 세션이 아예
    필요 없다 - 무거운 홈 화면 로딩과 SSO 판정을 매 회차 헛돈 셈이다.
    (공용 헬퍼는 4개 스크립트가 같이 쓰므로 건드리지 않고 여기만 따로 둔다.)

    로그인 쿠키는 프로필 전체에 공유되므로 새 탭도 SharePoint에 바로 접근된다.
    쓰고 나면 호출부가 close_driver()로 탭까지 닫는다."""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options
    import icbl_ci_watcher as icbl

    # 2026-09-14: 디버그 포트가 안 열린 상태로 붙으러 가면 selenium 스택트레이스만
    # 길게 남아 원인이 안 보인다("cannot connect to microsoft edge at ..."). 먼저
    # 포트를 확인해 무엇이 문제인지 한 줄로 알린다.
    if not icbl._debug_port_open():
        raise RuntimeError(
            f"Edge 디버그 포트 {icbl.EDGE_DEBUG_PORT}가 닫혀 있습니다 - 자동화용 "
            f"Edge가 떠 있지 않거나, 자동화용이 아닌 Edge가 먼저 실행돼 있어 "
            f"포트가 안 열린 상태입니다. Edge를 모두 닫고 다시 시도해주세요")

    options = Options()
    options.add_experimental_option(
        "debuggerAddress", f"127.0.0.1:{icbl.EDGE_DEBUG_PORT}")

    from selenium.common.exceptions import NoSuchWindowException

    # 2026-09-18: Edge를 방금 새로 띄운 직후(탭이 1개뿐인 불안정한 상태)
    # icbl_ci_watcher.py 등 이 디버그 포트를 같이 쓰는 다른 자동화가 하필 같은
    # 순간에 탭을 열고닫으면, 이 세션이 붙자마자 "현재 창"으로 잡은 탭이 그
    # 사이 닫혀버려 switch_to.new_window()가 NoSuchWindowException("target
    # window already closed")으로 죽는다(실측: 10:00:45 Edge 콜드스타트,
    # 10:01:20 icbl_ci_watcher 시작과 겹쳐서 10:02:19 이 자리에서 크래시).
    # 이 락을 서로 확인하게 만드는 대신(다른 3개 스크립트 건드림), 다시
    # 새로 붙으면 그 시점의 최신 창 목록을 보게 되므로 잠깐 쉬고 재접속만
    # 하면 된다 - 재시도 가능하도록 idempotent해야 한다는 파일 상단 원칙과 동일.
    last_err = None
    for attempt in range(3):
        driver = None
        try:
            driver = icbl._apply_driver_timeouts(webdriver.Edge(options=options))
            driver.switch_to.new_window("tab")
            icbl._remember_my_tab(driver)
            return driver
        except NoSuchWindowException as e:
            last_err = e
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
            time.sleep(3)
    raise last_err


def run_trigger_scan():
    """하루 1회(아침 10시) 실행: 트리거 메일 스캔 -> SharePoint 조회 -> 용마 요청 메일."""
    # 2026-08-27: 본사(Bob) 앞 미국 서류 발송 대기 큐도 여기서 한 번 본다 -
    # 아래 "신규 트리거 없음" 조기 return보다 앞이어야 큐가 계속 돈다
    # (process_ci_pending을 run_yongma_scan 맨 앞에 둔 것과 같은 이유).
    process_hq_docs_pending()

    state = load_state()
    processed = set(state.get("processed_to_numbers", []))
    pending = state.setdefault("pending_cases", {})

    cases = find_new_trigger_mails(processed)

    # 2026-09-04: 알림 메일이 끊겨도 멈추지 않도록, 메일에서 아무것도 못 찾으면
    # SharePoint를 직접 본다(find_new_trigger_cases_from_sharepoint 주석 참고).
    # 메일이 정상일 때는 이 경로가 돌지 않으므로 기존 동작은 그대로다.
    ensure_edge_running()
    # 트리거 스캔은 SharePoint + Outlook만 쓴다 - 오라클 홈을 거치지 않는다
    # (get_sharepoint_driver 주석 참고).
    driver = get_sharepoint_driver()
    try:
        if not cases:
            try:
                cases = find_new_trigger_cases_from_sharepoint(driver, processed)
            except Exception as e:
                log(f"[경고] SharePoint 트리거 조회 실패(메일 경로만 사용): {exc_detail(e)}")
                cases = {}

        if not cases:
            log("신규 Rebalance TO 트리거 없음")
            return

        _run_trigger_cases(driver, cases, state, processed, pending)
    finally:
        # 2026-09-04 사용자 요청: 재고이동 목록을 보고 나면 그 창을 닫는다.
        # 예전엔 스캔이 끝나도 드라이버를 그대로 둬서 APAC Stock Movements 화면이
        # 계속 떠 있었다(msedgedriver.exe도 회차마다 쌓였다).
        close_driver(driver)


def _run_trigger_cases(driver, cases, state, processed, pending):
    """트리거로 잡힌 TO들의 파트/수량을 확정하고 용마 요청 메일까지 보낸다."""

    # 2026-08-06 사용자 제안: 회신을 나중에 짜맞춰 매칭하기보다, 같은 스캔에서
    # 같은 나라로 나가는 TO가 여러 건 잡히면 파트 확인부터 다 끝낸 뒤 나라별로
    # 묶어서 용마 메일을 한 통으로 보낸다 - 그래서 파트 확인 루프와 발송 루프를
    # 분리했다(먼저 전부 확인 -> confirmed_by_country에 모음 -> 나라별로 발송).
    confirmed_by_country: dict[str, list[tuple[str, list[dict]]]] = {}
    for to_no, case in cases.items():
        kind = "RMA(본사반송)" if case.get("is_rma") else "Rebalance"
        log(f"신규 {kind} TO 감지: TO#{to_no}, 목적지={case['country']}, 파트={case['parts']}")
        # 2026-08-18: 한 TO의 트리거 메일들이 서로 다른 목적지를 가리키면 어느
        # 인보이스(나라 시트 vs FA LAB)를 만들어야 할지 알 수 없다 - 추측하지
        # 않고 사람에게 넘긴다. processed에 넣지 않으므로 정리되면 다음 스캔에서
        # 자동으로 다시 잡힌다.
        if case.get("conflict"):
            log(f"[보류] TO {to_no} 트리거 메일의 목적지가 엇갈림({case['conflict']}) - "
                f"용마 메일 보류")
            send_alert(
                f"[Rebalance TO {to_no}] 목적지가 엇갈려 보류 - 확인 필요",
                f"이 TO의 트리거 메일에서 서로 다른 목적지가 읽혔습니다: "
                f"{case['conflict']}\n파트: {sorted(case['parts'])}\n\n"
                f"국가 재배치(Rebalance)인지 본사 반송(RMA)인지에 따라 인보이스 "
                f"주소/HTS/금액 규칙이 달라서 자동 진행하지 않았습니다. APAC Stock "
                f"Movements의 Description을 확인해주세요.",
            )
            continue
        # 조회(읽기 전용)라 일시적 오라클 오류면 재시도해도 안전(2026-08-05).
        # 2026-08-06: 단발 조회 대신 lookup_to_lines_confirmed()로 바꿔 (1) 기대
        # 파트가 전부 잡히는지, (2) SharePoint 검색 자체의 플레이키니스(찾았다/
        # 못 찾았다 오가는 현상, 실측 확인됨)를 짧은 재시도로 흡수한다.
        lines = run_with_oracle_retry(
            f"TO {to_no} 라인 조회(확인 포함)",
            lambda t=to_no, c=case: lookup_to_lines_confirmed(driver, t, set(c["parts"])),
        )
        if not lines:
            # 2026-08-06 사용자 지시: Item/국가/TO/qty가 확인 안 된 채로 용마에
            # 메일을 보내지 않는다(TO 7870379가 SharePoint에 아직 미등록이라
            # qty를 "?"로 보낸 실수 이후 확정). 방금 등록된 TO는 APAC Stock
            # Movements에 반영되기까지 몇 분 걸릴 수 있으므로(실측: 트리거 후
            # 약 7분 뒤 조회하니 정상 등록돼 있었음), 여기서는 processed에 넣지
            # 않고 그냥 넘어가 다음 스캔에서 같은 TO#를 다시 시도하게 둔다.
            log(f"[보류] TO {to_no} SharePoint에서 qty 확인 실패 - 용마 메일 "
                f"보류, 다음 스캔에서 재시도")
            send_alert(
                f"[Rebalance TO {to_no}] SharePoint 미등록 - 용마 메일 보류",
                f"국가={case['country']}, 파트={case['parts']}\n\n"
                f"APAC Stock Movements에서 이 TO#의 파트가 전부 확인되지 않아 "
                f"정확한 qty 없이는 용마 메일을 보내지 않았습니다. 다음 스캔에서 "
                f"자동으로 재시도합니다 - 오래 반복되면 SharePoint 등록 상태를 "
                f"직접 확인해주세요.",
            )
            continue
        confirmed_by_country.setdefault(case["country"], []).append((to_no, lines))

    for country_code, entries in confirmed_by_country.items():
        to_numbers = [e[0] for e in entries]
        parts_qty_by_to = {e[0]: e[1] for e in entries}
        # RMA 3종은 목적지 코드가 이미 하나로 모아져 있어 코드만 봐도 구분된다.
        is_rma = country_code == RMA_DEST_CODE
        if len(to_numbers) > 1:
            log(f"[{'RMA' if is_rma else 'Rebalance'}] 같은 목적지({country_code})로 "
                f"나가는 TO {to_numbers} 동시 감지 - 용마 메일 한 통으로 합쳐서 발송")
        create_yongma_request_mail(to_numbers, country_code, parts_qty_by_to, is_rma=is_rma)
        for to_no in to_numbers:
            pending[to_no] = {
                "country": country_code,
                "is_rma": is_rma,
                "parts_qty": parts_qty_by_to[to_no],
                "requested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            processed.add(to_no)

    state["processed_to_numbers"] = sorted(processed)
    save_state(state)


def process_ci_pending():
    """CI 완료를 기다리는 TO들을 한 번씩 확인하고, 나온 건은 끝까지 마무리한다.

    용마 회차(30분마다)마다 맨 앞에서 불린다. Blocked가 몇 시간 단위라 30분 주기면
    충분하다. 확인 자체는 건당 수십 초라 정상 회차에 부담을 주지 않는다.

    start_at="ci"로 재개하므로 SharePoint 기입부터 다시 타는데, 그 단계는 같은 값을
    다시 써도 결과가 같아 안전하다(호출부 주석에 명시돼 있음). 재고 이동 단계
    (Release Now/Confirm/Ship Confirm)는 건너뛴다.
    """
    with _STATE_LOCK:
        queue = dict(load_state().get("ci_pending") or {})
    if not queue:
        return

    log(f"[CI대기] {len(queue)}건 확인 시작: {sorted(queue)}")
    deadline = time.time() + CI_PENDING_BUDGET_SEC
    # 오래 기다린 건부터 확인한다(제출 시각 순).
    for ci_key, entry in sorted(queue.items(),
                                key=lambda kv: str(kv[1].get("submitted_at") or "")):
        to_number = ci_key.split(":")[0]
        if time.time() >= deadline:
            log(f"[CI대기] 이번 회차 시간 예산({CI_PENDING_BUDGET_SEC // 60}분) 초과 "
                f"- 남은 건은 다음 회차에서 확인")
            break

        shipment_no = entry.get("shipment_no")
        if not shipment_no:
            log(f"[CI대기] TO {to_number}: Shipment 번호가 없어 건너뜀(수동 확인 필요)")
            continue

        try:
            process_rebalance_to(to_number, start_at="ci", shipment_no=shipment_no)
            log(f"[CI대기] TO {to_number} 완료 - 대기 목록에서 제거됨")
        except CIStillWaiting as e:
            log(f"[CI대기] {e}")
            _alert_if_ci_stale(ci_key, entry)
        except Exception as e:
            import traceback
            log(f"[CI대기] TO {to_number} 마무리 중 오류: {e}\n{traceback.format_exc()}")
            send_alert(
                f"[Rebalance TO {to_number}] CI 이후 단계에서 오류 - 확인 필요",
                f"CI는 확인됐는데 그 뒤 단계에서 실패했습니다.\n"
                f"Shipment: {shipment_no}\n\n"
                f"이어서 진행하려면: python rebalance_watcher.py resume {to_number} ci "
                f"{shipment_no}\n\n{e}",
            )


def _alert_if_ci_stale(ci_key: str, entry: dict) -> None:
    """CI가 너무 오래 안 나오면 한 번만 알린다.

    오라클 Scheduled Processes 조회 필터가 최대 24시간이라, 그 시간을 넘기면 저장해둔
    Process ID로도 화면에서 못 찾아 자동 확인이 불가능해진다 - 그 전에 사람이 볼 수
    있게 한다. 알림은 건당 한 번만(state에 표시)."""
    # 2026-08-27: to_number를 안 받아놓고 아래 메시지에서 쓰고 있어, 이 알림이
    # 실제로 뜨는 순간 NameError로 죽던 버그를 고침(키에서 뽑아 쓴다).
    to_number = ci_key.split(":")[0]
    submitted = str(entry.get("submitted_at") or "")
    if entry.get("stale_alerted"):
        return
    try:
        elapsed_h = (datetime.now()
                     - datetime.strptime(submitted, "%Y-%m-%d %H:%M:%S")).total_seconds() / 3600
    except Exception:
        return
    if elapsed_h < CI_PENDING_STALE_HOURS:
        return

    send_alert(
        f"[Rebalance TO {to_number}] CI가 {elapsed_h:.0f}시간째 안 나옴 - 확인 필요",
        f"Shipment {entry.get('shipment_no')} / Process {entry.get('process_id')}를 "
        f"{submitted}에 제출했는데 아직 완료되지 않았습니다.\n"
        f"오라클 Scheduled Processes 조회 필터가 최대 24시간이라, 그 뒤에는 자동 확인이 "
        f"안 됩니다. 오라클에서 프로세스 상태를 직접 확인해주세요.\n"
        f"완료돼 있다면: python rebalance_watcher.py resume {to_number} ci "
        f"{entry.get('shipment_no')}",
    )
    with _STATE_LOCK:
        st = load_state()
        cp = st.get("ci_pending") or {}
        if ci_key in cp:
            cp[ci_key]["stale_alerted"] = True
            save_state(st)


# Ship Confirm이 Exceptions(Regulatory Hold 등)로 막힌 TO를 재확인할 시간대
# (2026-09-21 사용자 요청: 처음엔 "오전 오후에 한번씩"으로 시작했다가 같은 날
# "그냥 시간마다로 하자, 10시부터 18시까지"로 확정). 스캔 자체는 15분마다
# 돌지만, 이 시(hour)에 들어왔을 때만 실제로 재시도해서 결과적으로 업무시간
# 매시간(10~18시, 9회/일)이 된다.
SHIP_CONFIRM_RETRY_HOURS = tuple(range(10, 19))  # 10,11,...,18


def process_ship_confirm_retry_queue() -> None:
    """Exceptions(Regulatory Hold 등)로 Ship Confirm이 막혀 담당자에게 이미
    알림/메일을 보낸 TO들을 업무시간 매시간(10~18시, SHIP_CONFIRM_RETRY_HOURS)
    재확인한다.

    막힌 TO는 shipment_no가 case에 기록되지 않은 채(ShipmentOnHold가
    _mark_stage_done 호출 전에 올라감) pending_cases에 남아있으므로, 대신
    shipment_exception_notified(check_and_handle_shipment_exceptions가 이미
    남긴 "{shipment_no}:{part_no}" 키)에서 shipment_no를 얻는다.

    재시도는 start_at='ship_confirm'으로 Manage Shipments에 바로 들어가
    Exceptions만 다시 확인한다 - 풀렸으면(check_and_handle_shipment_exceptions가
    False를 돌려줌) 그 자리에서 Ship Confirm -> CI -> FedEx까지 원래
    파이프라인이 자동으로 이어진다. 아직 안 풀렸으면 ShipmentOnHold가 다시
    올라오는데, 같은 "{shipment_no}:{part_no}" 키가 이미 notified 목록에 있어
    담당자에게 메일을 또 보내지는 않는다(중복 발송 방지, 기존 로직 그대로 재사용)."""
    now = datetime.now()
    if now.hour not in SHIP_CONFIRM_RETRY_HOURS:
        return

    with _STATE_LOCK:
        state = load_state()
        notified = dict(state.get("shipment_exception_notified") or {})
        pending = state.get("pending_cases") or {}
        retry_log = state.setdefault("ship_confirm_retry_log", {})
        window_key = f"{now.strftime('%Y-%m-%d')}-{now.hour}"

        targets = []  # (to_number, shipment_no)
        for to_number, keys in notified.items():
            if to_number not in pending or not keys:
                continue  # 이미 완전히 끝나 pending에서 빠졌으면 대상 아님
            if window_key in (retry_log.get(to_number) or []):
                continue  # 이 시간대엔 이미 재시도함
            shipment_no = str(keys[-1]).split(":")[0]
            if not shipment_no:
                continue
            targets.append((to_number, shipment_no))
            retry_log.setdefault(to_number, []).append(window_key)
        if targets:
            save_state(state)

    if not targets:
        return

    log(f"[Ship Confirm 재시도] {window_key} 시간대 - {len(targets)}건 확인: "
        f"{[t for t, _ in targets]}")
    for to_number, shipment_no in targets:
        try:
            process_rebalance_to(to_number, start_at="ship_confirm", shipment_no=shipment_no)
            log(f"[Ship Confirm 재시도] TO {to_number}: Exceptions 해제 확인 - "
                f"Ship Confirm부터 이후 단계까지 자동 진행 완료")
        except ShipmentOnHold as e:
            log(f"[Ship Confirm 재시도] TO {to_number}: 아직 보류 중 - {e}")
        except Exception as e:
            import traceback
            log(f"[Ship Confirm 재시도] TO {to_number} 재시도 중 오류: {e}\n{traceback.format_exc()}")
            send_alert(
                f"[Rebalance TO {to_number}] Ship Confirm 재시도 중 오류 - 확인 필요",
                f"Shipment {shipment_no}의 Exceptions 재확인 중 예상치 못한 오류가 "
                f"났습니다(Regulatory Hold 여부와 무관한 기술적 오류로 보임).\n\n{e}",
            )


def run_yongma_scan():
    """1시간에 1회 실행: 용마 회신 스캔 -> (TO#로 확실히 매칭되면) Create Pick
    Wave부터 수출신고실적까지 바로 이어서 자동 실행.

    2026-08-05: 기존엔 위치정보만 저장해두고 사람이 'process <TO#>'를 직접
    쳐야 다음 단계가 진행됐으나(1건 실측 검증 후 안전 체크포인트로 둔 것),
    사용자가 이 마지막 수동 트리거도 없애기로 확정 - process_rebalance_to()를
    이 자리에서 바로 호출한다. 단, TO#가 명확히 매칭된 케이스에서만 자동
    진행하고, 추측 매칭/매칭 불가 케이스는 여전히 사람 확인 알림만 보낸다
    (애매한 상태에서 실제 재고 이동 트랜잭션을 자동 실행하지 않기 위함).

    2026-08-06: 원래 하나의 TO로 묶여야 할 물량이 같은 나라로 나가는 TO 여러
    건으로 쪼개진 경우(사용자 실측 사례: ILH향 TO가 2개로 나뉨), 용마가 회신
    하나에 두 TO의 위치정보를 다 묶어 보낼 수 있다 - 회신 제목엔 TO# 하나만
    있어도, 파싱된 위치정보가 다른 pending TO의 기대 파트 전부를 덮으면 그
    TO도 같이 매칭해서 처리한다(아래 matched_to_numbers 참고). 이렇게 해야
    이미 답장을 받은 TO를 계속 기다리며 스캔이 헛도는 일이 없다.

    2026-08-19: 맨 앞에서 CI 완료 대기 큐부터 확인한다(process_ci_pending 참고).
    **아래 두 개의 조기 return보다 앞이어야 한다** - 그 뒤에 두면 "새 회신이 없는
    회차"에서 함수가 먼저 끝나버려 CI 확인에 영영 도달하지 못한다."""
    process_ci_pending()
    # 2026-08-27: CI 확인 직후에 본사(Bob) 앞 미국 서류 대기 큐를 본다 - 이 회차에
    # 새로 나온 CI까지 초안에 붙은 뒤에 발송 여부를 판단하게 된다.
    process_hq_docs_pending()
    # 2026-09-21 추가: Regulatory Hold 등으로 Ship Confirm이 막힌 TO를 하루
    # 두 번(오전/오후) 재확인 - 풀렸으면 자동으로 이어서 진행.
    process_ship_confirm_retry_queue()

    state = load_state()
    processed_entry_ids = set(state.get("processed_yongma_entry_ids", []))
    pending = state.get("pending_cases", {})

    if not pending:
        # pending_cases는 트리거로 TO#를 확인하고 create_yongma_request_mail()로
        # 제원요청 메일을 실제로 보낸 건에만 생성된다(run_trigger_scan 참고) -
        # 즉 pending이 비어있으면 "대기 중인 TO도, 보낸 메일도" 없다는 뜻이라
        # Outlook Yongma 폴더를 열어 회신을 찾을 이유가 없다(2026-08-06 사용자
        # 요청: 보낸 메일이 없는데 회신을 기다릴 필요가 없다).
        log("대기 중인 Rebalance TO 없음(보낸 제원요청 메일 없음) - 용마 회신 스캔 생략")
        return

    replies = find_yongma_replies(processed_entry_ids)
    if not replies:
        log("신규 용마 회신 없음")
        return

    # 2026-08-06 사용자 요청: 예전엔 이 루프에서 회신 하나를 매칭하면 그 자리에서
    # process_rebalance_to()를 끝까지 돌리고 다음 회신으로 넘어갔다 - 그래서 앞선
    # TO의 14단계(ICBL CI 완료 대기가 최대 17분)가 끝날 때까지 뒤의 회신은 매칭도
    # 안 된 채 대기했다(실측: 10:30 회차에서 홍콩 2건이 일본 건 뒤에 막힘).
    # 이제 (1) 회신 전부를 먼저 매칭해서 위치정보를 state에 다 채워두고,
    # (2) 실행할 TO 목록을 모아 MAX_PARALLEL_TO건씩 동시에 돌린다.
    to_run: list[str] = []
    for reply in replies:
        log(f"용마 회신 감지: {reply['subject']}, TO#={reply['to_number']}, "
            f"위치정보 {len(reply['locations'])}건 파싱됨")
        # 2026-08-04 실측 정정: 요청 메일 제목에 TO#를 넣게 바꿔서(create_yongma_request_mail
        # 참고) 회신 제목에도 TO#가 그대로 남아있다 - 이제 pending 건수와 무관하게
        # TO#로 확실하게 매칭한다. 제목이 변형돼 TO#를 못 찾은 경우에만 예전
        # 방식(1건이면 추측)으로 폴백.
        to_no = reply["to_number"]
        loc_parts = {loc["part_no"] for loc in reply["locations"] if loc.get("part_no")}

        # 2026-08-06 추가: 원래 하나의 TO로 묶여야 할 물량이 같은 나라(예: ILH)로
        # 나가는 TO 여러 건으로 쪼개진 경우, 용마가 회신 하나에 전부 위치정보를
        # 묶어서 보낼 수 있다(사용자 실측 사례) - 제목엔 TO# 하나만 있어도, 이
        # 회신의 위치정보가 "그 TO가 기대하는 파트 전부"를 덮는 pending TO는 전부
        # 매칭 대상으로 본다. 그래야 나머지 TO가 별도 회신을 영원히 기다리며
        # 스캔만 계속 도는 일이 없다.
        # 2026-08-06 사용자 확인: 나라가 같으면 회신이 합쳐져 올 수 있지만, 나라가
        # 다르면 항상 각자 메일로 온다 - 그래서 제목의 TO#로 나라를 알 수 있을
        # 때는(subject_country) 같은 나라의 pending TO만 묶어서 매칭하도록 한 번
        # 더 제한한다(파트 커버리지만으로는 못 거를 우연한 겹침까지 막는 안전판).
        subject_country = pending.get(to_no, {}).get("country") if to_no else None
        matched_to_numbers = [
            t for t, c in pending.items()
            if c.get("parts_qty")
            and {p["part_no"] for p in c["parts_qty"]} <= loc_parts
            and (subject_country is None or c.get("country") == subject_country)
        ]
        # 2026-08-06: 보낼 때 나라별로 합쳐서 보낸 메일(제목이 "...{TO1}+{TO2}")
        # 이면 회신 제목에도 TO#가 전부 남아있으므로, 파트 커버리지 없이도(예:
        # 파싱 실패로 일부만 뽑힘) 제목에 있는 TO#는 전부 신뢰해서 매칭한다
        # (find_yongma_replies()의 to_numbers 리스트, 2026-08-04 이전 동작의
        # 자연스러운 확장).
        for t in reply.get("to_numbers", []):
            if t in pending and t not in matched_to_numbers:
                matched_to_numbers.append(t)

        if matched_to_numbers:
            if len(matched_to_numbers) > 1:
                log(f"[Pipeline] 회신 1건이 TO {matched_to_numbers} 여러 건을 동시에 "
                    f"덮음(같은 나라로 나가는 TO가 쪼개진 케이스로 추정) - 전부 처리")
            for t in matched_to_numbers:
                pending[t]["locations"] = reply["locations"]
                # 2026-08-06 사용자 요청: CI 보정 완료 후 이 원본 회신에 "전체
                # 답장"으로 서류를 첨부해 초안을 만들어야 해서, 그 회신의
                # entry_id를 이 TO의 케이스에 같이 저장해둔다(create_yongma_ci_reply_draft
                # 참고). 회신 한 건이 여러 TO를 덮으면 그 TO들 전부 같은
                # entry_id를 공유한다.
                pending[t]["reply_entry_id"] = reply["entry_id"]
                if t not in to_run:
                    to_run.append(t)
        elif not to_no and len(pending) == 1:
            to_no = next(iter(pending))
            send_alert(
                f"[Rebalance TO {to_no}] 용마 제원 회신 도착(제목에서 TO# 못 찾아 "
                "대기 중인 TO가 1건뿐이라 추측 매칭) - 자동 실행 대신 확인 요청",
                f"용마 회신 제목: {reply['subject']}\n\n{reply['body']}\n\n"
                f"확인 후 'python rebalance_watcher.py process {to_no}'로 진행하세요.",
            )
        else:
            send_alert(
                "[Rebalance] 용마 회신 도착했으나 대기 중인 TO와 매칭 불가"
                f"(회신 제목에서 읽은 TO#={to_no})",
                f"용마 회신 제목: {reply['subject']}\n\n{reply['body']}\n\n"
                f"현재 대기 중인 TO: {list(pending.keys())}",
            )
        processed_entry_ids.add(reply["entry_id"])

    if not to_run:
        with _STATE_LOCK:
            state = load_state()
            state["processed_yongma_entry_ids"] = sorted(processed_entry_ids)
            save_state(state)
        return

    # process_rebalance_to()가 자기 state를 디스크에서 새로 읽으므로, 워커를
    # 띄우기 전에 방금 채운 위치정보를 전부 저장해둬야 한다.
    # pending_cases 전체를 통째로 덮어쓰면 그 사이 trigger 스캔이 추가한 TO가
    # 사라질 수 있으니, 이번에 매칭된 TO의 locations만 골라서 넣는다.
    with _STATE_LOCK:
        saved = load_state()
        saved_pending = saved.setdefault("pending_cases", {})
        for t in to_run:
            if t in saved_pending:
                saved_pending[t]["locations"] = pending[t]["locations"]
                saved_pending[t]["reply_entry_id"] = pending[t].get("reply_entry_id")
        save_state(saved)

    n_workers = min(MAX_PARALLEL_TO, len(to_run))
    log(f"[Pipeline] 위치정보 확보된 TO {to_run} - 동시 {n_workers}건씩 처리 시작")

    # 2026-08-19: 워커를 띄우기 전에 단독으로 로그인을 확정한다
    # (ensure_oracle_ready_before_fanout 설명 참고 - 워커가 뜬 뒤엔 Edge 재시작
    # 수단을 못 쓰기 때문에, 콜드 스타트 회차가 통째로 날아가는 것을 여기서 막는다).
    # 실패하면 이번 회차는 아무것도 시작하지 않고 보류한다. 아래 processed_yongma_
    # entry_ids 저장까지 가지 않고 return하므로, 같은 회신이 다음 yongma 스캔에서
    # 다시 스캔돼 그대로 이어서 처리된다(위치정보는 이미 state에 저장돼 있다).
    try:
        ensure_oracle_ready_before_fanout()
    except Exception as e:
        log(f"[사전점검] 오라클 로그인 확보 실패 - 이번 회차 파이프라인 전체 보류: "
            f"{exc_detail(e)}")
        send_alert(
            "[Rebalance] 오라클 로그인 필요 - 이번 회차 처리 보류",
            f"대상 TO: {', '.join(to_run)}\n\n"
            f"용마 위치정보는 저장돼 있어, 오라클 로그인만 정상화되면 다음 yongma "
            f"스캔에서 자동으로 이어서 처리됩니다.\n\n{e}",
        )
        return

    def _run_one(t: str):
        # 2026-08-14: 이 함수는 ThreadPoolExecutor 워커 스레드에서 돌고, 아래
        # except 절에서 send_alert()(win32com으로 Outlook COM 호출)를 부른다.
        # 메인 스레드는 COM이 암묵적으로 초기화돼 있지만 새로 만든 스레드는 아니라서
        # CoInitialize() 없이 부르면 "CoInitialize has not been called"로 터진다.
        # 그러면 **실패 알림 메일이 안 만들어지고** 예외가 밖으로 퍼져 워커가 죽는다
        # (= 사람이 로그를 직접 안 보면 실패 자체를 모른다. 물건은 이미 나간
        # 상태일 수 있어 특히 위험하다).
        # 실측 TO 7872710(2026-08-14 17:09:12): ICBL 인보이스 생성 실패 -> 알림을
        # 보내려다 이 오류로 워커 종료 -> 알림 메일 0통. pick_release_watcher.py는
        # 같은 버그를 2026-07-23에 이미 고쳤는데(_process_single_order 주석 참고)
        # 이 파일에는 그 수정이 안 옮겨져 있었다.
        import pythoncom
        pythoncom.CoInitialize()
        log(f"[Pipeline] TO {t} 위치정보 확보 - 자동으로 이후 단계 시작")
        try:
            process_rebalance_to(t)
        except CIStillWaiting as e:
            # 실패가 아니라 정상 보류다 - 알림 없이 다음 용마 회차가 이어받는다.
            log(f"[Pipeline] {e}")
        except ShipmentOnHold as e:
            # 담당자 알림/메일은 check_and_handle_shipment_exceptions()가 이미
            # 보냈다 - 추가 알림 없이 로그만 남긴다(중복 알림 방지).
            log(f"[Pipeline] {e}")
        except OracleLoginRequired:
            send_alert(
                f"[Rebalance TO {t}] 오라클 재로그인 필요 - 다음 실행에서 자동 재시도",
                f"용마 위치정보는 저장돼 있어 다음 yongma 스캔에서 이어서 처리됩니다.",
            )
        except Exception as e:
            import traceback
            log(f"[에러] TO {t} 자동 처리 실패: {e}\n{traceback.format_exc()}")
            send_alert(
                f"[Rebalance TO {t}] 자동 처리 중 에러 - 확인 필요",
                f"용마 위치정보는 저장돼 있습니다. 원인 확인 후 "
                f"'python rebalance_watcher.py process {t}'로 수동 재시도하세요.\n\n"
                f"{e}\n\n{traceback.format_exc()}",
            )

    # 한 건이 실패해도 나머지는 계속 돌아야 하므로 예외는 _run_one 안에서 다 먹는다.
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        futures = {ex.submit(_run_one, t): t for t in to_run}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                fut.result()
            except Exception as e:
                log(f"[에러] TO {t} 워커가 예상 못한 예외로 종료: {exc_detail(e)}")

    # 회신 처리 기록은 파이프라인이 다 끝난 뒤에 저장한다 - 중간에 프로세스가
    # 죽으면 그 회신을 다음 실행에서 다시 스캔해 이어갈 수 있게(기존 동작 유지).
    with _STATE_LOCK:
        state = load_state()
        state["processed_yongma_entry_ids"] = sorted(processed_entry_ids)
        save_state(state)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "trigger"
    # 2026-08-06: 앞 회차가 아직 도는 중에 다음 스케줄이 겹쳐 뜨는 것을 막는다
    # (같은 TO 동시 처리 / state·엑셀 프로세스 간 동시 쓰기 방지). 수동
    # 'process' 실행도 같은 락을 타므로, 스캔이 도는 중엔 수동 실행이 거절된다
    # (의도된 동작 - 겹쳐 돌리는 게 더 위험하다).
    lock = _acquire_singleton_lock()
    if lock is None:
        log(f"이미 다른 인스턴스가 실행 중 - 종료 (mode={mode}, 겹치는 스케줄 트리거로 추정)")
        return
    # 2026-09-18: 공유 Edge 락을 걸었다가(TO 7882258 FedEx 어레인지 실사고로
    # 도입) 같은 날 stale 판정 구멍으로 이 스크립트가 pick_release_watcher의
    # 살아있는 Edge를 "죽은 락"으로 오판해 가져가는 사고를 냈다(00603889 건).
    # 대신 이 스크립트를 전용 Edge(포트/프로필)로 완전히 분리해 겹칠 일 자체를
    # 없앴다(set_edge_owner("rebalance_watcher") 참고). 락 제거.
    log(f"===== rebalance_watcher 시작 (mode={mode}) =====")
    try:
        if mode == "trigger":
            run_trigger_scan()
        elif mode == "yongma":
            run_yongma_scan()
        elif mode == "process":
            if len(sys.argv) < 3:
                log("사용법: python rebalance_watcher.py process <TO번호>")
            else:
                process_rebalance_to(sys.argv[2])
        elif mode == "resume":
            # 2026-08-06 추가: 중간에 깨진 TO를 그 다음 단계부터 이어서 처리.
            # 오라클에서 Release/Confirm/Ship Confirm은 한 번만 되므로, 이미
            # 지나간 단계를 다시 시도하지 않고 건너뛰어야 복구가 된다.
            if len(sys.argv) < 4:
                log("사용법: python rebalance_watcher.py resume <TO번호> <confirm|ship_confirm|ci> "
                    "[Shipment번호(ship_confirm/ci일 때 필수)]")
            else:
                resume_to, resume_at = sys.argv[2], sys.argv[3]
                resume_shipment = sys.argv[4] if len(sys.argv) > 4 else None
                log(f"[재개] TO {resume_to}를 '{resume_at}' 단계부터 처리"
                    + (f" (Shipment={resume_shipment})" if resume_shipment else ""))
                process_rebalance_to(resume_to, start_at=resume_at,
                                     shipment_no=resume_shipment)
        else:
            log(f"알 수 없는 mode: {mode} (trigger|yongma|process 중 하나)")
    except ShipmentOnHold as e:
        # 담당자 알림/메일은 check_and_handle_shipment_exceptions()가 이미
        # 보냈다 - 추가 알림 없이 로그만 남긴다(중복 알림 방지).
        log(f"[Pipeline] {e}")
    except CIStillWaiting as e:
        # 2026-09-16 추가: run_yongma_scan()의 _run_one()에는 이미 이 처리가
        # 있었는데, process/resume 모드로 직접 돌릴 때는 빠져 있어서 "정상
        # 보류"가 "실행 중 에러" 알림으로 잘못 나갔다(TO 7881076 실사례) -
        # 에러가 아니라 다음 yongma 스캔이 이어받는 정상 상태이므로 로그만 남긴다.
        log(f"[Pipeline] {e}")
    except OracleLoginRequired:
        send_alert("[Rebalance] 오라클 재로그인 필요", "다음 실행에서 자동 재시도합니다.")
    except Exception as e:
        import traceback
        log(f"[에러] {e}\n{traceback.format_exc()}")
        send_alert(f"[Rebalance] 실행 중 에러", f"{e}\n\n{traceback.format_exc()}")
    finally:
        try:
            lock.close()
        except Exception as e:
            # 2026-08-06: 락이 안 풀리면 다음 회차부터 계속 "이미 실행 중"으로
            # 스킵돼 자동화가 멈추는데 원인이 로그에 안 남았다(다른 4개 자동화의
            # _release_singleton_lock과 동일한 취지). 동작은 그대로 두고 흔적만 남긴다.
            log(f"[경고] 실행 락 해제 실패({type(e).__name__}: {e}) - 다음 회차가 "
                f"'이미 실행 중'으로 스킵되면 락 파일을 확인하세요")
    log("===== rebalance_watcher 종료 =====")


if __name__ == "__main__":
    main()
