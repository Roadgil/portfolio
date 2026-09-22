# -*- coding: utf-8 -*-
"""
rma_auto_reply.py

받은편지함 > "CK service team" 폴더(Inbox 바로 아래 하위 폴더)로 오는
    [External] New RMA#  00000000 Is Returned From The Field
형식의 FSE(현장 서비스 엔지니어) 알림 메일만 감시해서(2026-08-10 범위 축소:
번호만 바뀌는 이 고정 문구 하나만 매칭, RE:/FW: 회신은 제외):
  1) 제목에서 RMA 번호(8자리)를 추출
  2) 본문의 "Link to Parts Order:" 다음 줄에 있는 Salesforce 레코드 링크를 열어
     Order Type / Oracle Order Number / Parts Order Lines(Disposition 등)를 읽고
  3) Disposition 값으로 "Unused RMA" / "Defective RMA"를 판정한 뒤
  4) 발신자(FSE) 이름을 한글 존칭으로 바꿔 한국어 답장을 작성해 바로 발송한다
     (mail.ReplyAll() -> reply.Send()).

2026-07-16 작성. 아래 3개는 이 스크립트를 만들기 직전 단계(Feasibility/기술검증,
100% 읽기전용 진행)에서 이미 실제로 검증된 내용을 그대로 재사용한 것이다:
  - Edge 헬퍼 함수들(ensure_rma_edge_running/get_rma_driver/open_salesforce_tab/
    is_salesforce_login_page) 및 Shadow DOM 텍스트 추출/파싱 로직
    (get_full_shadow_text/extract_rma_fields/classify_rma_type) - RMA 전용
    포트 9334 + 전용 프로필을 쓰며, Oracle 자동화(icbl_ci_watcher.py,
    EDGE_DEBUG_PORT=9333)와는 포트/프로필이 완전히 분리되어 있다. 이 파일에는
    Oracle 관련 코드/URL을 전혀 포함하지 않는다(콜드스타트 시에도 Oracle
    홈페이지가 아니라 처리할 Salesforce 링크로 바로 이동한다).
  - 실측 결과 이 회사 PC 환경에서는 Salesforce 접속 시 로그인 절차 없이
    바로 레코드 화면이 렌더링됐다(Windows 도메인/Azure AD SSO로 추정). 다만
    이건 1회 관측이라 배포 후에도 계속 그런지 계속 확인이 필요하므로, 매 실행
    마다 is_salesforce_login_page()로 방어적으로 체크하고, 로그인 페이지로
    보이면 절대 아이디/비번을 입력하지 않고 사람에게 알림 메일만 보낸다.
  - "Unused RMA는 Disposition=Unused, 나머지는 Defective RMA" 규칙과
    "Unused RMA는 Oracle Order Number가 항상 7로 시작" 규칙 모두 실측 10건
    (직접 확인 6건 + 교차검증 4건) 전수 일치 확인됨 - 그대로 검증 규칙으로
    사용한다(어긋나면 이상 케이스로 사람에게 넘김).

기존 자동화(pick_release_watcher.py)에서 그대로 재사용한 관례:
  - _acquire_singleton_lock()/_release_singleton_lock(f): msvcrt.locking 기반
    파일 락으로 같은 스크립트의 중복 실행 방지.
  - log(msg): print + 로그파일 append.
  - load_state()/save_state(state): 단순 JSON dict 상태파일.
  - send_alert(subject, body): win32com으로 alert 메일을 사람 앞으로 Save()만
    (발송 아님). 로그인 필요/파싱 실패/미매핑 발신자/판정 이상 케이스 등
    애매한 건 전부 자동으로 밀어붙이지 않고 send_alert로 사람에게 넘긴다
    (추측 금지가 최우선 원칙).
  - 완료 답장 CC 고정 상수: pick_release_watcher.py의 PICK_RELEASE_REPLY_CC
    (574~577번째 줄, 실제 파일에서 원문 그대로 확인함)를 이 스크립트에서도
    동일한 문자열 그대로 재사용한다(RMA_REPLY_CC).
  - 답장 생성: mail.ReplyAll() 호출 후 reply.To/reply.CC를 강제로 덮어쓰고
    (원본 스레드의 To/CC를 따르지 않음), reply.BCC = "", reply.Body 앞에
    우리가 만든 본문을 prepend, 마지막은 reply.Send()로 바로 발송한다.

*** AUTO_SEND = True (2026-07-16 사용자 명시적 요청으로 전환) ***
초기에는 안정화 전까지 임시보관함 초안만 만들도록 만들었으나, 실제 초안
2건(RMA#00593366, 00593486)을 사람이 직접 검토해 내용이 정확함을 확인한 뒤
사용자가 "초안 작성 말고 그대로 보내달라"고 명시적으로 요청해 바로 발송으로
전환함. 로그인 필요/파싱 실패/미매핑 발신자/판정 이상/Oracle 처리 중 등 애매한
케이스는 여전히 자동 발송하지 않고 send_alert(초안만 저장)로 사람에게 넘기는
원칙은 그대로 유지한다 - 확실한 정상 케이스만 바로 발송됨.

2026-08-13 추가 - Oracle 연동 결과에 따른 3분기 처리:
Salesforce 레코드가 Oracle 오더를 아직/영영 못 만든 상태를 예전엔 전부 "파싱
실패" 하나로 뭉뚱그려서, 기다리면 풀릴 건에도 알림을 만들고 영영 안 풀릴 건도
매시간 헛돌기만 했다. 사용자 지시로 상태를 구분한다.
  1) "processing in Oracle" 안내 문구 -> 아직 인터페이스 처리 중인 정상 상태.
     알림 없이 조용히 다음 회차 재시도(기존과 동일).
  2) Interface To Oracle = Error -> 연동 자체가 실패해 Oracle Order Number가
     영영 안 채워진다. 담당 FSE에게 화면의 Oracle error message를 그대로 붙여
     "재생성 부탁드립니다" 답장을 바로 발송한다(_build_oracle_error_body).
     실측 근거: RMA#00598005 (2026-08-13, Missing Billing/Shipping Location 등
     Cloud 동기화 누락으로 Error).
  3) 그 외 파싱 실패 -> 대개 화면이 덜 렌더링된 일시적 상태이므로
     PARSE_RETRY_LIMIT회까지 조용히 재시도하고, 그래도 안 되면 사람에게 알림.

2026-08-18 추가 - Defective 계열 답장에 Case 번호(CA...) 포함:
사용자 요청("Defective인 경우엔 Case 옆에 CA로 시작하는 것도 포함해서 보내줘",
스샷 근거: Case=CA1438337 / Order Type=Defective RMA)으로, Defective 계열
(= Unused RMA가 아닌 건) 답장 본문에 Oracle Order Number 아래 "Case: CAxxxxxxx"
한 줄을 추가한다(CASE_NO_RE로 파싱). Unused RMA 본문은 이전과 완전히 동일하다.
Defective인데 Case 번호를 못 읽었으면 불완전한 답장을 보내지 않고 위 3)의 파싱
실패 경로(재시도 -> 한도 초과 시 알림)로 넘긴다.

2026-08-18 추가 - 완료 답장 인사말 형식 통일(사용자 지시):
"안녕하세요" 다음 줄에 "{담당자 존칭}의 {Defective/Unused} RMA입니다."로 쓴다.
예전처럼 인사말 줄에 이름을 붙이고("안녕하세요 정재필 과장님,") 타입을 따로
쓰지 않는다. Unused/Defective 모두 동일한 형식이다.

주의:
- Task Scheduler(schtasks) 등록됨: RMA_Auto_Reply, 매일 08:00~19:00 1시간 간격
  (2026-07-16 등록, 사용자가 "답장을 빨리 할 필요는 없다"고 심플하게 결정).
- LOOKBACK_START_DATE 이전 메일(이 스크립트를 처음 만든 시점 이전의 백로그)은
  절대 건드리지 않는다 - pick_release_watcher.py의 LOOKBACK_START_DATE와
  동일한 취지(과거 수십 건에 답장 초안을 한꺼번에 만들면 안 됨).
"""

from __future__ import annotations

import html
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime

# ==============================================================
# 경로/설정
# ==============================================================
ROOT = os.path.dirname(__file__)
LOG_PATH = os.path.join(ROOT, "rma_auto_reply.log")
STATE_PATH = os.path.join(ROOT, "_processed_rma.json")
LOCK_FILE_PATH = os.path.join(ROOT, "_watcher.lock")

OUTLOOK_SUBFOLDER = "CK service team"  # 받은편지함(Inbox) 바로 아래 하위 폴더

ALERT_MAIL_TO = "yoongil.chae@candelamedical.com"

# 2026-07-16 사용자 지정: RMA#00593366(포함)부터 처리한다 - 그 이전 메일은
# 사용자가 이미 전부 수동으로 처리 완료했다고 확인함. 시각이 아니라 RMA 번호
# 기준 컷오프다(처음엔 "스크립트 생성 시각 이후"로 만들었었는데, 그러면 이미
# 받은편지함에 쌓여있는 실제 백로그를 하나도 처리 못 해서 사용자가 이 번호
# 기준으로 바꿔달라고 요청함). pick_release_watcher.py의 LOOKBACK_START_DATE와
# 취지는 동일 - 과거분(사람이 이미 처리한 것)에 중복으로 답장 초안을 만들면 안 됨.
CUTOFF_RMA_NO = 593366

# 제목에서 RMA 번호 추출(처리 완료 여부 판단 키, 8자리).
# 2026-08-10 사용자 요청으로 범위를 좁힘. 예전엔 제목 아무 데나 "RMA#숫자"가
# 있으면 잡았는데(re.search), 그러면 담당자가 스레드에 답장한 "RE: [External]
# New RMA# ..." 같은 것도 후보로 올라오고, CK service team 폴더로 오는 출고요청/
# 재고문의 메일까지 전부 "RMA 번호 못 찾음" 경고 로그를 뿜어서 로그가 지저분했다.
# 실제 알림 메일 제목은 번호만 바뀌고 나머지는 항상 동일한 고정 문구다:
#   [External] New RMA#  00597245 Is Returned From The Field
# 그래서 앞뒤를 앵커로 고정해 이 형식 하나만 매칭한다(RE:/FW: 회신은 ^ 때문에
# 자동으로 제외). 번호는 8자리(현재는 00으로 시작).
RMA_SUBJECT_RE = re.compile(
    r"^\[External\]\s*New\s+RMA#\s*(\d{8})\s+Is\s+Returned\s+From\s+The\s+Field\s*$",
    re.IGNORECASE,
)

# 위 고정 문구가 언젠가 바뀌면 조용히 한 건도 안 잡히는 상황이 생길 수 있다.
# "New RMA#"는 들어있는데 전체 형식이 안 맞는 제목만 골라 경고 로그를 남기기
# 위한 느슨한 패턴(무관한 메일에는 걸리지 않으므로 로그가 늘지 않는다).
RMA_SUBJECT_LOOSE_RE = re.compile(r"New\s+RMA#", re.IGNORECASE)

# 담당자가 스레드에 답장/전달한 메일은 원본이 아니므로 스킵하는 게 정상 동작이다.
# 위 경고까지 뜨면 다시 로그가 지저분해지므로 이 접두어가 붙은 건 조용히 넘긴다.
RMA_SUBJECT_REPLY_PREFIX_RE = re.compile(r"^\s*(RE|FW|FWD)\s*:", re.IGNORECASE)

# 본문에는 서명/로고 이미지의 salesforce.com/servlet/... 링크도 섞여 있어(Feasibility
# 단계 실측 확인) 아무 salesforce.com 링크나 잡으면 오탐이 난다. "Link to Parts
# Order:" 바로 다음 줄의 레코드 링크만 정확히 잡도록 앵커를 둔다(검증된 정규식
# 그대로 재사용).
SF_LINK_RE = re.compile(
    r"Link to Parts Order:\s*\r?\n\s*(https://[^\s]*salesforce\.com/[^\s]+)"
)


# ==============================================================
# RMA 전용 Edge 설정 (Oracle 자동화와 완전히 분리 - 포트/프로필 모두 별도)
# Feasibility 단계에서 그대로 가져온 것 - EDGE_DEBUG_PORT=9333(Oracle)과
# 겹치지 않는 9334번 포트 + 별도 프로필을 쓴다.
# ==============================================================
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
RMA_EDGE_PROFILE_DIR = r"C:\Users\yoongil.chae\.rma_auto_reply_automation\browser_profile"
RMA_EDGE_DEBUG_PORT = 9334  # 9333(Oracle 자동화 전용)과 절대 겹치지 않는 별도 포트


def ensure_rma_edge_running(initial_url: str = "about:blank"):
    """RMA 자동화 전용 Edge 디버그 인스턴스가 떠 있는지 확인하고, 없으면 새로
    실행한다. icbl_ci_watcher.py의 ensure_edge_running() '구조'(포트 확인 ->
    없으면 subprocess.Popen으로 새로 실행 -> 대기)만 참고했을 뿐, Oracle 관련
    코드/URL은 전혀 포함하지 않는다. 콜드스타트 시 여는 초기 URL은 Oracle
    홈페이지가 아니라 처리할 Salesforce 링크(또는 about:blank)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", RMA_EDGE_DEBUG_PORT))
        s.close()
        return True
    except Exception:
        s.close()

    subprocess.Popen([
        EDGE_PATH,
        f"--remote-debugging-port={RMA_EDGE_DEBUG_PORT}",
        f"--user-data-dir={RMA_EDGE_PROFILE_DIR}",
        "--profile-directory=Default",
        "--start-maximized",
        initial_url,
    ])
    time.sleep(10)
    return True


# 2026-08-06 추가: 지금까지 페이지 로드 타임아웃이 지정돼 있지 않았다. Selenium
# 기본값은 "무한 대기"라서 Salesforce가 응답을 주다 마는 순간 driver.get()이
# 영영 돌아오지 않고, 예외가 안 나므로 아래의 어떤 except도 작동하지 못한다.
# 이 스크립트는 파일 락(_acquire_singleton_lock)을 쓰고 작업 스케줄러 실행
# 제한이 PT72H라, 한 번 멈추면 이후 회차가 전부 "이미 실행 중"으로 스킵되면서
# 사람이 눈치챌 때까지 조용히 멈춘다. 정상 상황에선 절대 안 걸릴 만큼 넉넉히
# 잡되, 걸리면 TimeoutException으로 올라가 기존 except가 받게 한다.
# (icbl_ci_watcher.py의 PAGE_LOAD_TIMEOUT_SEC과 같은 취지 - 이 스크립트는
#  오라클 쪽 모듈을 import하지 않으므로 값을 따로 둔다.)
# 2026-08-10 수정(180/120 -> 90/60): 취지는 맞았지만 값이 잘못돼 있어 이 설정이
# 한 번도 발동할 수 없는 상태였다. Selenium이 msedgedriver와 통신하는 HTTP
# 클라이언트의 기본 read timeout이 120초라, 페이지 로드 타임아웃을 그보다 큰
# 180초로 두면 항상 클라이언트가 먼저 포기한다. 그러면 (1) 올라오는 예외가
# WebDriverException이 아니라 urllib3 raw 에러라서 기존 분류/재시도 로직이
# 판단을 못 하고, (2) 클라이언트만 손을 뗐을 뿐 msedgedriver는 그 명령을 계속
# 붙잡고 있어 다음 명령이 버려진 응답과 엇갈릴 수 있다(세션 desync).
# 실측 사례는 icbl_ci_watcher.py의 같은 상수 주석 참고
# (2026-08-10 SharePoint 조회에서 read timeout=120으로 실패).
# 두 값 모두 120초보다 작게 두어 드라이버가 먼저 스스로 중단하게 만든다.
PAGE_LOAD_TIMEOUT_SEC = 90
SCRIPT_TIMEOUT_SEC = 60


def get_rma_driver():
    """RMA 전용 디버그 포트(9334)에 attach하는 selenium driver를 반환."""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options

    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{RMA_EDGE_DEBUG_PORT}")
    driver = webdriver.Edge(options=options)
    try:
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SEC)
    except Exception as e:
        log(f"[경고] 페이지 로드 타임아웃 설정 실패(무시하고 계속): {e}")
    try:
        driver.set_script_timeout(SCRIPT_TIMEOUT_SEC)
    except Exception as e:
        log(f"[경고] 스크립트 타임아웃 설정 실패(무시하고 계속): {e}")
    return driver


def close_rma_driver(driver) -> None:
    """이 실행이 쓰던 드라이버를 끝낼 때 부른다 - 탭을 닫고(close) 드라이버
    프로세스까지 정리한다(quit).

    2026-08-06 추가. close()는 '탭'만 닫을 뿐 msedgedriver.exe 프로세스는
    그대로 남는다(webdriver.Edge()를 부를 때마다 하나씩 새로 뜬다). 실측:
    부모 파이썬이 끝난 지 3시간 지난 고아 msedgedriver.exe가 살아있었다.

    quit()이 공유 Edge까지 죽이는지 별도 프로필/포트로 실측 검증함(2026-08-06):
    debuggerAddress로 '붙은' 드라이버는 브라우저를 자기가 띄운 게 아니라서
    quit()을 해도 msedgedriver만 정리되고 Edge 프로세스와 디버그 포트는 그대로
    살아있다(검증 후 재접속해 탭 조회까지 정상 확인)."""
    if driver is None:
        return
    try:
        driver.close()
    except Exception:
        pass
    try:
        driver.quit()
    except Exception:
        pass


def open_salesforce_tab(driver, url: str):
    """같은 디버그포트 인스턴스에 새 탭을 열어 url로 이동. 작업이 끝나면
    호출부가 close_rma_driver()로 정리한다.
    2026-08-06 정정: 원래 이 주석에 "driver.quit()은 전체 브라우저를 닫으므로
    쓰지 말 것"이라고 적혀 있었는데, 실측해보니 debuggerAddress로 붙은
    드라이버의 quit()은 브라우저를 닫지 않는다(위 close_rma_driver 설명 참고).
    그 오해 때문에 msedgedriver.exe가 계속 쌓이고 있었다."""
    driver.switch_to.new_window("tab")
    driver.get(url)
    time.sleep(3)
    return driver


def is_salesforce_login_page(driver) -> bool:
    """로그인 페이지로 리다이렉트됐는지 확인. URL에 login.salesforce.com이
    포함되거나, 화면에 로그인 폼(Username/Password input)이 보이면 True.
    True면 절대 아이디/비번을 입력하지 말고 사람에게 알림만 보낼 것."""
    from selenium.webdriver.common.by import By

    url = driver.current_url or ""
    if "login.salesforce.com" in url:
        return True
    try:
        if driver.find_elements(By.ID, "username") and driver.find_elements(By.ID, "password"):
            return True
    except Exception:
        pass
    if "Log In" in (driver.title or "") or "Login" in (driver.title or ""):
        return True
    return False


# ==============================================================
# Shadow DOM 재귀 순회로 화면에 실제 렌더링된 텍스트 전체 추출
# (실측 화면은 Classic이라 Shadow DOM이 없었지만, Lightning으로 바뀌거나
#  다른 레코드가 Lightning 컴포넌트를 쓰는 경우에도 안전하게 동작하도록
#  범용으로 짜둠 - shadowRoot가 없으면 그냥 일반 DOM 텍스트만 모은다.)
# ==============================================================
SHADOW_DOM_TEXT_JS = r"""
function collectVisibleText(root, out) {
    const walker = document.createTreeWalker(
        root,
        NodeFilter.SHOW_TEXT,
        {
            acceptNode: function(node) {
                const parent = node.parentElement;
                if (!parent) return NodeFilter.FILTER_REJECT;
                if (parent.offsetParent === null && parent.tagName !== 'BODY') {
                    return NodeFilter.FILTER_REJECT;
                }
                const style = window.getComputedStyle(parent);
                if (style.display === 'none' || style.visibility === 'hidden') {
                    return NodeFilter.FILTER_REJECT;
                }
                const txt = node.nodeValue.trim();
                if (!txt) return NodeFilter.FILTER_REJECT;
                return NodeFilter.FILTER_ACCEPT;
            }
        }
    );
    let node;
    while (node = walker.nextNode()) {
        out.push(node.nodeValue.trim());
    }

    // 같은 root 안의 모든 element를 훑어서 shadowRoot가 있으면 재귀
    const allElements = root.querySelectorAll('*');
    allElements.forEach(function(el) {
        if (el.shadowRoot) {
            collectVisibleText(el.shadowRoot, out);
        }
    });
}

const result = [];
collectVisibleText(document.body, result);
return result.join('\n');
"""


def get_full_shadow_text(driver) -> str:
    return driver.execute_script(SHADOW_DOM_TEXT_JS)


# 2026-07-16 사용자 확인: RMA 레코드가 생성된 직후 너무 빨리 조회하면 Salesforce가
# Oracle 인터페이스 처리 중이라는 안내만 보여줄 때가 있다("Order is processing in
# Oracle. Please wait for a while and refresh the page to check the status
# message."). 이건 파싱 실패나 이상 케이스가 아니라 그냥 아직 준비가 안 된
# 정상적인 일시 상태이므로, 사람에게 alert를 보내지 않고 조용히 다음 예약 실행으로
# 넘긴다(상태에도 기록하지 않아 다음 실행에서 자동으로 재시도됨).
ORACLE_PROCESSING_RE = re.compile(r"processing in oracle", re.IGNORECASE)


# 2026-08-13 실측 확인(RMA#00598005): 위의 "처리 중"과 전혀 다른, 진짜 실패 상태가
# 따로 있다. 레코드 상세에 "Interface To Oracle" 필드가 있고 값이 Error면 연동이
# 실패한 것이라 Oracle Order Number가 영영 안 채워진다. 실제 화면 발췌:
#     Interface To Oracle
#     Error
#     ...
#     Oracle error message
#     OIC Instance Id (...) - Missing Billing Account details.Please check if
#     account has been synced with Cloud
#     Missing Billing location details. ...
#     Missing Shipping Location details. ...
#     Analysis Required?
#     Oracle Order Number      <- 값 없음
# 이걸 예전엔 "필드 파싱 실패"로만 처리해서 매시간 헛돌기만 했다. 시간이 지나도
# 저절로 풀리지 않는 상태이므로 담당 FSE에게 재생성을 요청해야 한다
# (2026-08-13 사용자 지시: "error라고 뜨면 보낸 담당자에게 오라클 연동이슈로
#  재생성 부탁드립니다 메일 보내줘").
#
# 주의: "Interface To Oracle"은 화면 아래쪽 Parts Order History에도 나온다
# ("Changed Interface To Oracle from Processed to Error."). re.search는 첫 번째
# 매치(=상세 영역)만 잡으므로 문제 없고, 혹시 상세 필드가 비어 있으면 다음 라벨
# 텍스트가 잡히는데 그 값은 "Error"가 아니므로 오탐이 나지 않는다.
INTERFACE_TO_ORACLE_RE = re.compile(r"Interface To Oracle\s*\n\s*([^\n]+)")

# Oracle error message는 여러 줄이다. 다음에 오는 라벨 중 먼저 나오는 것을 끝
# 앵커로 삼아 그 사이를 통째로 가져온다(값이 비어 있으면 곧바로 라벨이 오므로
# 매치되지 않고 빈 문자열이 된다).
ORACLE_ERROR_MSG_RE = re.compile(
    r"Oracle error message\s*\n(.*?)\n(?:Analysis Required\?|Oracle Order Number"
    r"|Retrigger to Oracle Status|Warehouse)",
    re.DOTALL,
)

# 2026-08-18 사용자 요청: Defective 계열 답장에는 Salesforce Parts Order 레코드의
# Case 번호도 같이 넣어야 한다. 실제 화면(사용자 스샷, Case=CA1438337 /
# Order Type=Defective RMA) 발췌:
#     Record Type
#     RMA
#     Case
#     CA1438337
#     Work Order
#     WO-00582199
# 값 자체가 "CA"+숫자 형태라 이걸 앵커로 잡는다. 화면 다른 곳에 Case 관련 라벨이
# 있어도 바로 다음 줄이 CA숫자가 아니면 매치되지 않으므로 오탐 위험이 낮다.
CASE_NO_RE = re.compile(r"Case\s*\n\s*(CA\d+)")


def is_oracle_processing_page(driver) -> bool:
    """Salesforce 레코드가 아직 Oracle 인터페이스 처리 중이라 데이터가 준비되지
    않은 일시적 상태인지 확인한다. True면 파싱을 시도하지 말고 그냥 다음 예약
    실행으로 넘겨야 한다(alert 없이 조용히 skip)."""
    try:
        text = get_full_shadow_text(driver)
    except Exception:
        return False
    return bool(ORACLE_PROCESSING_RE.search(text or ""))


# ==============================================================
# 필드 파싱 (Feasibility 단계 실측 검증된 로직 그대로 재사용)
# ==============================================================
# 2026-07-16 실측 확인 (총 2건의 실제 오정렬 버그를 발견/재현):
# 1) Parts Order Lines 표의 'Work Order' 컬럼이 비어있으면 그 칸의 텍스트 노드
#    자체가 생기지 않아 뒤 컬럼(Disposition/Line Status/Total Line Price)이
#    한 칸씩 당겨져 보인다.
# 2) Fulfillment Qty가 아직 0으로도 안 채워진(주문 Status가 아직 "Open"인) 행은
#    Expected Qty 한 개만 텍스트로 나오고 Fulfillment Qty 칸 자체가 비어서
#    숫자 값이 1개만 나올 수도 있다.
# 즉 Product Code and Serial과 Disposition 리터럴("Unused"/"Defective") 앵커
# 사이에 오는 줄 수가 0~3개로 가변적이다. 그래서 고정 줄 수를 가정하지 않고,
# 그 사이 전체를 통째로 캡처한 뒤 파이썬에서 숫자 형태 줄만 골라 Expected/
# Fulfillment Qty로 배정하고 나머지(있다면)를 Work Order로 취급한다.
# Disposition 리터럴은 "Unused"/"Defective" 외에 "Failed During Testing (DOA)"도
# 관측됨(2026-07-21, 사용자 확인 - Defective의 일종으로 취급). 다른 값이 새로
# 나오면 이 앵커 방식은 그 행을 놓칠 수 있으므로(파싱 실패 -> extract_rma_fields가
# 빈 리스트를 반환 -> 아래 process 단계에서 파싱 실패로 판단해 send_alert) 계속
# 실측 검증 필요 - 새 값이 확인되면 아래 알터네이션에 추가할 것(추측 금지, 실제
# 관측된 값만 추가).
LN_ROW_RE = re.compile(
    r"(LN-\d+)\s*\n"                    # line number
    r"([^\n]+)\s*\n"                    # product name
    r"([^\n]+)\s*\n"                    # product code and serial
    r"((?:[^\n]+\n)*?)"                 # Expected/Fulfillment Qty + (있다면) Work Order - 가변 줄수
    r"(Unused|Defective|Failed During Testing \(DOA\))\s*\n"  # disposition (실측 리터럴 값 앵커)
    r"([^\n]+)"                         # line status
)
_NUMERIC_RE = re.compile(r"^[\d.,]+$")


def extract_rma_fields(driver) -> dict:
    """Salesforce 레코드 화면(Shadow DOM 포함)에서 실제로 렌더링된 텍스트를
    모아 Order Type / Oracle Order Number / Parts Order Lines를 정규식으로
    파싱한다. driver는 이미 해당 레코드 페이지에 있어야 한다."""
    text = get_full_shadow_text(driver)

    result = {
        "order_type": None,
        "oracle_order_number": None,
        "parts_order_lines": [],
        # 2026-08-13 추가: Oracle 연동 실패 판정용(위 INTERFACE_TO_ORACLE_RE 주석 참고)
        "interface_to_oracle": None,
        "oracle_error_message": "",
        # 2026-08-18 추가: Defective 계열 답장 본문에 넣을 Case 번호(CA...)
        "case_number": None,
    }

    m = re.search(r"Order Type\s*\n\s*([^\n]+)", text)
    if m:
        result["order_type"] = m.group(1).strip()

    m = re.search(r"Oracle Order Number\s*\n\s*(\d+)", text)
    if m:
        result["oracle_order_number"] = m.group(1).strip()

    m = INTERFACE_TO_ORACLE_RE.search(text)
    if m:
        result["interface_to_oracle"] = m.group(1).strip()

    m = ORACLE_ERROR_MSG_RE.search(text)
    if m:
        result["oracle_error_message"] = m.group(1).strip()

    m = CASE_NO_RE.search(text)
    if m:
        result["case_number"] = m.group(1).strip()

    lines = []
    for lm in LN_ROW_RE.finditer(text):
        line_number, product, code_serial, middle_block, disposition, line_status = lm.groups()
        middle_lines = [ln.strip() for ln in middle_block.splitlines() if ln.strip()]
        numeric_vals = [ln for ln in middle_lines if _NUMERIC_RE.match(ln)]
        non_numeric_vals = [ln for ln in middle_lines if not _NUMERIC_RE.match(ln)]
        exp_qty = numeric_vals[0] if len(numeric_vals) >= 1 else ""
        ful_qty = numeric_vals[1] if len(numeric_vals) >= 2 else ""
        work_order = non_numeric_vals[0] if non_numeric_vals else ""
        lines.append({
            "line_number": line_number.strip(),
            "product": product.strip(),
            "product_code_serial": code_serial.strip(),
            "expected_qty": exp_qty,
            "fulfillment_qty": ful_qty,
            "work_order": work_order,
            "disposition": disposition.strip(),
            "line_status": line_status.strip(),
        })
    result["parts_order_lines"] = lines
    return result


def classify_rma_type(fields: dict) -> str:
    """사용자 규칙(Feasibility 단계 10건 전수 일치 확인): 라인 전부의
    Disposition이 'Unused'면 Unused RMA. 그 외(Defective, "Failed During Testing
    (DOA)" 등)는 전부 "Defective 계열"로 취급하되(7-prefix 검증 규칙 등에서
    "Unused RMA"가 아니면 전부 이 계열로 처리), 답장 문구는 실제 Disposition
    값을 그대로 살려서 자연스럽게 쓴다(2026-07-21 사용자 확인: "Failed During
    Testing (DOA)"는 Defective의 일종이니 답장엔 "Defective RMA"로 뭉뚱그리지
    말고 그 문구 그대로 써서 보내면 됨). 라인마다 Disposition이 섞여있는 경우는
    process_rma_mails 쪽에서 이 함수를 부르기 전에 먼저 걸러내(사람에게 alert)
    판정하지 않으므로, 여기 도달한 시점엔 전 라인의 Disposition이 동일하다."""
    lines = fields.get("parts_order_lines") or []
    if lines and all(l["disposition"] == "Unused" for l in lines):
        return "Unused RMA"
    if lines:
        return f"{lines[0]['disposition']} RMA"
    return "Defective RMA"


# ==============================================================
# FSE 발신자 -> 한글 존칭 이름 매핑
# 사용자가 명시적으로 확인해준 매핑만 사용한다. 이 표에 없는 발신자는 절대
# 이름을 추측하지 않고 send_alert로 사람에게 넘긴다.
# ==============================================================
FSE_NAME_MAP = {
    "jaepil jeong": "정재필 과장님",
    "dasung jung": "정다성 과장님",
    "jong seong cha": "차종성 차장님",
    "chang sik shin": "신창식 차장님",
    "junyeol yang": "양준열 대리님",
    "ben lee": "이병무 대리님",
    # 2026-07-16 사용자 확인 후 추가(Feasibility 단계에서 영문 표기만 관측됐던
    # 발신자 2명의 한글 존칭 이름을 사용자가 알려줌):
    "joohyung han": "한주형 차장님",
    "kwang yul lee": "이광열 이사님",
}
# 아직 실제 발신 메일로 영문 표기를 관측하지 못한 나머지 FSE(사용자가 알려준
# 전체 10명 명단 중 미관측 2명) - 실제 메일이 오면 표시 이름을 확인해서 추가할 것:
#   - 김혜준 대리님
#   - 박준곤 대리님


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower())


# ==============================================================
# 유틸 (pick_release_watcher.py와 동일한 패턴)
# ==============================================================
def log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


class StateFileCorrupted(Exception):
    """상태 파일이 존재하는데 JSON으로 읽히지 않는 경우. 빈 상태로 진행하면
    이미 답장한 RMA에 또 답장하게 되므로 이 예외로 회차를 중단시킨다.
    (icbl_ci_watcher.py의 같은 이름 예외와 취지 동일 - 이 스크립트는 오라클
    모듈을 import하지 않으므로 따로 둔다.)"""


def _exc_detail(e: BaseException) -> str:
    """로그에 남길 예외 상세 - 예외 타입 + 메시지 + 파이썬 스택.
    2026-08-06 추가. 지금까지 [에러] 로그가 f"{e}"만 남겨서, Selenium 예외의
    경우 메시지에 msedgedriver 내부 스택만 들어있고 우리 코드 어느 줄에서
    터졌는지가 안 보였다.
    (icbl_ci_watcher.py의 exc_detail과 같은 취지 - 이 스크립트는 오라클
    모듈을 import하지 않으므로 따로 둔다.)"""
    import traceback
    return f"{type(e).__name__}: {e}\n{traceback.format_exc()}"


def load_state() -> dict:
    """2026-08-06: 예전에는 파일이 깨져 있으면 빈 상태({})를 돌려줬는데, 그건
    "아직 아무 RMA도 처리 안 했다"는 뜻이라 이미 답장을 보낸 건에 또 답장하게
    된다 - 파일이 있는데 깨졌으면 회차를 중단시킨다(파일 자체가 없는 첫 실행은
    예전처럼 {}로 정상 진행)."""
    if not os.path.exists(STATE_PATH):
        return {}
    import json
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"[치명] RMA 처리 이력({os.path.basename(STATE_PATH)})을 읽을 수 없습니다: {e}\n"
            f"       빈 상태로 진행하면 이미 답장한 건에 다시 답장하게 되므로 "
            f"이번 회차를 중단합니다.")
        raise StateFileCorrupted(f"RMA 처리 이력 손상: {STATE_PATH}") from e


def save_state(state: dict):
    # 2026-08-06: open("w")는 파일을 먼저 비우기 때문에 쓰는 도중 프로세스가
    # 죽으면 이력 파일이 통째로 깨진다 - 임시 파일에 다 쓰고 os.replace로
    # 한 번에 바꿔치기해서(원자적) 기존 파일이 절대 손상되지 않게 한다.
    import json
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_PATH)


# 2026-08-10 사용자 요청: 자동 발송/초안 메일 글꼴을 굴림 -> 맑은 고딕으로 통일.
# 굴림이 나오던 이유: 답장에 끼워 넣던 <div>에 글꼴 지정이 없어 원본 메일의
# 글꼴을 그대로 물려받았고, 평문(.Body)으로 만들던 메일은 Outlook 평문
# 기본 글꼴을 따라갔다.
MAIL_FONT_CSS = "font-family:'맑은 고딕',Malgun Gothic,sans-serif;font-size:10.0pt"


def mail_text_to_html(text: str) -> str:
    """평문 본문을 맑은 고딕 HTML로 감싼다.
    HTML은 연속 공백을 하나로 줄이므로 들여쓰기가 뭉개지지 않도록 2칸 이상
    연속 공백은 &nbsp;로 보존한다."""
    esc = html.escape(str(text or ""))
    esc = esc.replace("\r\n", "\n").replace("\r", "\n")
    esc = re.sub(r"  +", lambda mm: "&nbsp;" * len(mm.group()), esc)
    esc = esc.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
    return f'<div style="{MAIL_FONT_CSS}">' + esc.replace("\n", "<br>") + "</div>"


def send_alert(subject: str, body: str):
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = ALERT_MAIL_TO
    mail.Subject = subject
    mail.HTMLBody = mail_text_to_html(body)
    mail.Save()
    log(f"알림 메일 초안 저장: {subject}")


def _acquire_singleton_lock():
    """이미 다른 인스턴스(다른 스케줄 트리거 포함)가 돌고 있으면 None 반환."""
    import msvcrt
    f = open(LOCK_FILE_PATH, "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


def _release_singleton_lock(f):
    import msvcrt
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()
    except Exception as e:
        # 2026-08-06: 락이 안 풀리면 다음 회차부터 계속 "이미 실행 중"으로
        # 스킵돼 자동화가 멈추는데 원인이 로그에 안 남았다. 동작은 그대로 두고
        # 흔적만 남긴다.
        log(f"[경고] 실행 락 해제 실패({type(e).__name__}: {e}) - 다음 회차가 "
            f"'이미 실행 중'으로 스킵되면 {os.path.basename(LOCK_FILE_PATH)}를 확인하세요")


# ==============================================================
# 1) Outlook에서 신규 RMA 메일 찾기
# ==============================================================
def find_new_rma_mails(processed_rma: set) -> list:
    """받은편지함(Inbox) 바로 아래 'CK service team' 폴더에서 제목에 RMA#이
    있고 아직 처리하지 않은 RMA 번호를 가진 메일을 찾는다. pick_release_watcher
    와 달리 이 폴더는 Inbox 직속 하위 폴더라 부모 폴더를 한 번 더 순회하지
    않는다."""
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    inbox = outlook.GetDefaultFolder(6)

    target = None
    for f in inbox.Folders:
        if str(f.Name).strip() == OUTLOOK_SUBFOLDER:
            target = f
            break
    if target is None:
        raise RuntimeError(f"Outlook 폴더를 못 찾음: 받은편지함 > {OUTLOOK_SUBFOLDER}")

    items = target.Items
    items.Sort("[ReceivedTime]", True)

    results = []
    # 2026-08-06: 예전엔 조용히 건너뛰어서 RMA 메일 한 통이 통째로 빠져도
    # 흔적이 없었다. 동작은 그대로 두고 흔적만 남긴다(로그 폭주 방지로 앞의 3건만).
    _item_errors = 0
    _skipped_not_rma = 0  # RMA 알림 형식이 아닌 일반 메일(조용히 스킵, 건수만 집계)
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

        subject = str(mail.Subject or "")

        m_rma = RMA_SUBJECT_RE.match(subject)
        if not m_rma:
            # 이 폴더에는 출고요청/재고문의 등 RMA와 무관한 메일이 훨씬 많다.
            # 그런 건 조용히 넘기고(예전엔 매 실행마다 경고 20여 줄이 쌓여서
            # 진짜 문제가 묻혔다) 마지막에 건수만 요약한다. 다만 "New RMA#"가
            # 들어있는데 형식이 안 맞는 건 알림 메일 문구가 바뀌었다는 신호일
            # 수 있으므로 개별 경고를 남긴다.
            if (RMA_SUBJECT_LOOSE_RE.search(subject)
                    and not RMA_SUBJECT_REPLY_PREFIX_RE.match(subject)):
                log(f"[경고] New RMA# 메일 같은데 제목 형식이 달라 스킵됨"
                    f"(문구 변경 확인 필요): {subject}")
            else:
                _skipped_not_rma += 1
            continue

        rma_no = m_rma.group(1)

        # 시간 정렬과 RMA 번호 순서가 완벽히 일치한다고 단정할 수 없으므로
        # break가 아니라 continue로 매 건 개별 비교한다(최대 100건 스캔이라
        # 비용도 크지 않음).
        try:
            if int(rma_no) < CUTOFF_RMA_NO:
                continue  # 사용자가 이미 수동 처리한 백로그 - 자동 처리 대상 아님
        except ValueError:
            pass

        if rma_no in processed_rma:
            continue

        results.append({
            "entry_id": mail.EntryID,
            "subject": subject,
            "rma_no": rma_no,
        })

    if _skipped_not_rma:
        log(f"스캔 {min(items.Count, 100)}건 중 RMA 알림 형식이 아닌 메일 "
            f"{_skipped_not_rma}건은 건너뜀(정상)")

    return results


# ==============================================================
# 2) 답장 본문 생성 / 발신자 이메일 확인
# ==============================================================
def _build_reply_body(honorific_name: str, rma_type: str, oracle_order_number: str,
                      lines: list, case_number: str = "") -> str:
    lines_text = "\n".join(
        f"- {l['line_number']} {l['product']} ({l['product_code_serial']}) / "
        f"Expected Qty {l['expected_qty']}"
        for l in lines
    )
    # 2026-08-18 사용자 요청: Defective 계열(= Unused RMA가 아닌 건)은 Oracle Order
    # Number 옆에 Salesforce Case 번호(CA...)도 같이 알려준다. Unused RMA에는 넣지
    # 않는다(요청 범위가 Defective 한정).
    case_text = ""
    if rma_type != "Unused RMA" and case_number:
        case_text = f"Case: {case_number}\n"
    # 2026-08-18 사용자 지시("앞으로 모든 메일 / 안녕하세요 / 누구누구누구의
    # Defective RMA or Unused RMA 입니다 라고 해줘"): 인사말 줄에 이름을 붙이지 않고,
    # 바로 다음 줄에 "{담당자}의 {타입} RMA입니다."로 누구 건인지 밝힌다. 답장은
    # 담당 FSE 앞으로 가면서 용마(창고)가 CC로 같이 받으므로, 창고에서도 누구
    # 건인지 첫 줄에서 바로 알 수 있게 하는 형식이다.
    return (
        f"안녕하세요\n"
        f"{honorific_name}의 {rma_type}입니다.\n\n"
        f"Oracle Order Number: {oracle_order_number}\n"
        f"{case_text}\n"
        f"Parts Order Lines:\n{lines_text}\n\n"
        f"감사합니다."
    )


def _build_oracle_error_body(honorific_name: str, rma_no: str, error_message: str) -> str:
    """Oracle 연동 실패(Interface To Oracle = Error) 건에 대해 담당 FSE에게 보낼
    재생성 요청 본문. 2026-08-13 사용자 지시로 신설 - 이 상태는 기다린다고 풀리는
    게 아니라 레코드를 새로 만들어야 하므로, 사람 손을 기다리지 않고 바로 담당자에게
    되돌려준다. Salesforce가 알려주는 원인 메시지를 그대로 붙여줘서 담당자가 무엇을
    고쳐야 하는지(대개 Account/Location이 Cloud와 동기화 안 된 문제) 바로 알 수 있게
    한다 - 우리가 원인을 해석해서 지시하지는 않는다(추측 금지)."""
    err_block = (error_message or "").strip() or "(화면에 표시된 오류 메시지 없음)"
    return (
        f"안녕하세요 {honorific_name},\n\n"
        f"RMA#{rma_no} 건은 Salesforce에서 Oracle로 넘어가는 과정에 오류가 발생해"
        f" Oracle Order가 생성되지 않았습니다.\n"
        f"(Salesforce 레코드의 Interface To Oracle 값이 Error 상태입니다.)\n\n"
        f"Salesforce에 표시된 오류 내용은 아래와 같습니다.\n"
        f"{err_block}\n\n"
        f"현재 상태로는 입고 처리가 진행되지 않으니, 확인 후 Parts Order를 새로"
        f" 생성해 주시기 바랍니다.\n"
        f"새로 생성해 주시면 그 건으로 다시 안내드리겠습니다.\n\n"
        f"감사합니다."
    )


def _get_sender_email(mail) -> str:
    """원본 발신자의 SMTP 이메일 주소를 최대한 정확히 가져온다. 사내(Exchange)
    계정이면 mail.SenderEmailAddress가 X500 주소일 수 있어 GetExchangeUser()로
    PrimarySmtpAddress를 우선 시도하고, 실패하면 SenderEmailAddress로 fallback."""
    try:
        if getattr(mail, "SenderEmailType", None) == "EX":
            exch_user = mail.Sender.GetExchangeUser()
            if exch_user is not None:
                addr = exch_user.PrimarySmtpAddress
                if addr:
                    return addr
    except Exception as e:
        # 2026-08-06: 여기서 조용히 넘어가면 아래 fallback이 X500 주소
        # ("/o=ExchangeLabs/ou=...") 를 그대로 돌려줄 수 있고, 그 주소로
        # 답장을 만들면 발송이 실패하거나 엉뚱한 곳으로 간다. 동작(fallback)은
        # 그대로 두고 왜 정확한 주소를 못 구했는지 흔적을 남긴다.
        log(f"[경고] Exchange 발신자 주소 조회 실패({type(e).__name__}: {e}) - "
            f"SenderEmailAddress로 대체함")
    return str(getattr(mail, "SenderEmailAddress", "") or "")


# ==============================================================
# 3) 답장 발송 (완료 답장 CC 고정 상수 - pick_release_watcher.py의
#    PICK_RELEASE_REPLY_CC와 정확히 동일한 문자열을 그대로 재사용)
# ==============================================================
RMA_REPLY_CC = (
    "김기훈 <y7221063@yongmalogis.co.kr>; 용호 유 <y7225055@yongmalogis.co.kr>"
)

# *** AUTO_SEND = True (2026-07-16 사용자 요청으로 전환) ***
# 확실한 정상 케이스(로그인 OK, 파싱 성공, 발신자 매핑됨, Disposition/7-prefix
# 규칙 일치)는 reply.Send()로 바로 발송한다. 애매한 케이스(로그인 필요/파싱
# 실패/미매핑 발신자/판정 이상/Oracle 처리 중)는 여전히 send_alert만 보내고
# 자동 발송하지 않는다.
# 2026-08-13 추가: Oracle 연동 실패(Interface To Oracle = Error)도 "확실한 케이스"에
# 해당한다 - 화면이 대놓고 Error라고 알려주므로 추측이 아니다. 이 경우 담당 FSE에게
# 재생성 요청 답장을 같은 AUTO_SEND 규칙으로 보낸다.
AUTO_SEND = True

# 2026-08-13 사용자 지시("interfacing to oracle 처럼 시간이 걸리는 거는 재시도하는
# 게 맞고"): 파싱 실패는 대부분 화면이 아직 덜 채워진 일시적 상태다. 실제로 지금까지
# 있었던 파싱 실패 3건 중 2건(RMA#00593931, 00596241)은 다음 회차 재시도에서 정상
# 처리됐다. 그런데도 예전 코드는 첫 실패에 바로 사람에게 alert 초안을 만들어서,
# 가만 놔둬도 풀릴 건에 대해 불필요한 알림을 만들었다. 이제는 조용히 재시도하다가
# 이 횟수(=시간당 1회이므로 약 5시간)를 넘겨도 계속 실패할 때만 사람에게 알린다.
# 진짜 실패(Interface To Oracle = Error)는 이 재시도 경로를 타지 않고 위에서 먼저
# 걸러져 담당자에게 바로 나가므로, 이 값을 늘려도 실제 오류 대응이 늦어지지 않는다.
PARSE_RETRY_LIMIT = 5


# ==============================================================
# 4) 메일 처리 메인 루프
# ==============================================================
def process_rma_mails(new_mails: list, state: dict) -> None:
    import win32com.client

    # "Salesforce 링크를 못 찾음" 알림은 같은 RMA로 반복 스팸이 안 되도록 한 번만
    # 보낸다(상태파일에 영구 저장 - 다음 실행에서도 유지되어야 하므로 세션이 아닌
    # state에 남긴다). 반면 "로그인 필요" 알림은 실행 도중 세션 상태가 바뀔 리
    # 없으므로(같은 브라우저 세션을 이번 실행 내내 그대로 씀) 이번 실행에서 한
    # 번만 보내고 나머지 메일은 이번 회차 처리를 중단한다(런타임 한정 - 다음
    # 예약 실행에서는 처음부터 다시 시도).
    alerted_rma = set(state.get("_alerted_rma", []))
    login_alert_sent_this_run = False

    # 2026-08-13 추가.
    # _oracle_error_notified: Oracle 연동 실패로 담당자에게 재생성 요청을 이미 보낸
    #   RMA. 처리이력(state 본체)에 넣지 않는 이유는, 담당자가 재생성 대신 Salesforce
    #   에서 Retrigger를 걸어 같은 레코드가 살아나는 경우가 있을 수 있기 때문이다.
    #   여기에만 기록해두면 다음 회차에도 화면을 다시 확인해서, 아직 Error면 조용히
    #   넘기고(재촉 메일 안 보냄) 정상으로 바뀌었으면 평소대로 완료 답장을 보낸다.
    #   무한정 다시 열어보게 되는 것 아니냐 하면, find_new_rma_mails가 최근 메일
    #   100건만 훑기 때문에 오래된 건은 자연히 스캔 범위 밖으로 빠진다.
    # _parse_retry: 파싱 실패 연속 횟수(PARSE_RETRY_LIMIT 주석 참고).
    # _parse_alerted: 재시도 한계를 넘겨 사람에게 알림을 이미 보낸 RMA(중복 방지).
    oracle_error_notified = set(state.get("_oracle_error_notified", []))
    parse_retry = dict(state.get("_parse_retry", {}))
    parse_alerted = set(state.get("_parse_alerted", []))

    for m in new_mails:
        rma_no = m["rma_no"]
        subject = m["subject"]
        entry_id = m["entry_id"]
        log(f"처리 시작: RMA#{rma_no} ({subject})")

        try:
            outlook = win32com.client.Dispatch("Outlook.Application")
            ns = outlook.GetNamespace("MAPI")
            mail = ns.GetItemFromID(entry_id)
            body = str(mail.Body or "")
        except Exception as e:
            log(f"[에러] RMA#{rma_no}: 메일 재조회 실패 - {_exc_detail(e)}")
            continue

        m_link = SF_LINK_RE.search(body)
        if not m_link:
            if rma_no not in alerted_rma:
                send_alert(
                    f"[RMA 확인 필요] Salesforce 링크를 찾지 못함 - RMA#{rma_no}",
                    "본문에서 'Link to Parts Order:' 다음 줄의 Salesforce 링크를 "
                    f"찾지 못했습니다.\n메일 제목: {subject}\n"
                    "메일 형식이 예상과 다르거나 링크가 없는 경우일 수 있습니다. "
                    "수동으로 확인해주세요.\n"
                    "(이 RMA에 대해서는 이 알림을 다시 보내지 않으며, 처리는 계속 "
                    "재시도됩니다.)",
                )
                alerted_rma.add(rma_no)
                state["_alerted_rma"] = sorted(alerted_rma)
                save_state(state)
            else:
                log(f"RMA#{rma_no}: Salesforce 링크 없음(이미 알림 보냄 - 재알림 생략)")
            continue

        sf_link = m_link.group(1).rstrip(".,)>")

        if login_alert_sent_this_run:
            # 이미 이번 실행에서 로그인 필요 알림을 보냈다면, 같은 브라우저 세션을
            # 계속 쓰는 한 나머지 메일도 동일하게 실패할 것이 확실하므로 불필요한
            # 탭을 계속 열지 않고 이번 실행은 여기서 중단한다(상태에 기록하지
            # 않았으니 다음 예약 실행에서 전부 처음부터 재시도됨).
            log(f"RMA#{rma_no}: 이번 실행에서 이미 로그인 필요 알림을 보냈으므로 이후 메일 처리를 중단")
            break

        driver = None
        try:
            ensure_rma_edge_running(sf_link)
            driver = get_rma_driver()
            open_salesforce_tab(driver, sf_link)

            if is_salesforce_login_page(driver):
                log(f"[경고] RMA#{rma_no}: Salesforce 로그인 필요 상태로 판단됨")
                send_alert(
                    "[RMA 확인 필요] Salesforce 로그인 필요",
                    "Salesforce 세션이 로그인되지 않은 것으로 보입니다. 아이디/비번을 "
                    "자동으로 입력하지 않고 알림만 보냅니다.\n"
                    f"RMA#{rma_no} ({subject})\n링크: {sf_link}\n"
                    f"Edge(포트 {RMA_EDGE_DEBUG_PORT}, RMA 전용 프로필)에서 로그인 상태를 "
                    "확인해주세요.\n"
                    "(이번 실행에서는 이 알림을 한 번만 보내며, 이번 실행의 나머지 메일 "
                    "처리는 중단합니다 - 다음 예약 실행에서 다시 시도됩니다.)",
                )
                login_alert_sent_this_run = True
                continue

            if is_oracle_processing_page(driver):
                # 방금 생성된 RMA라 Oracle 인터페이스 처리가 아직 안 끝난 정상적인
                # 일시 상태 - alert 없이 조용히 skip, 상태에도 기록 안 해서 다음
                # 예약 실행(1시간 뒤)에서 자동으로 재시도된다.
                log(f"RMA#{rma_no}: Oracle 처리 중(\"processing in Oracle\") - 다음 실행으로 넘김")
                continue

            fields = extract_rma_fields(driver)
            order_type = fields.get("order_type")
            oracle_order_number = fields.get("oracle_order_number")
            lines = fields.get("parts_order_lines") or []

            # ---- (a) Oracle 연동 실패: 기다려도 안 풀리므로 담당자에게 재생성 요청 ----
            # 파싱 실패 판정보다 반드시 먼저 본다. Interface To Oracle이 Error면
            # Oracle Order Number가 비어 있는 게 당연한 결과이지 우리 파싱이 틀린 게
            # 아니기 때문이다(2026-08-13 RMA#00598005에서 실제로 이 오진이 있었다).
            if (fields.get("interface_to_oracle") or "").strip().lower() == "error":
                err_msg = fields.get("oracle_error_message") or ""
                if rma_no in oracle_error_notified:
                    log(f"RMA#{rma_no}: Oracle 연동 실패(Error) 상태 유지 중 - "
                        f"이미 재생성 요청을 보냈으므로 재발송하지 않음")
                    continue

                log(f"[경고] RMA#{rma_no}: Oracle 연동 실패(Interface To Oracle=Error) - "
                    f"담당자에게 재생성 요청 발송 시도. 오류내용: {err_msg!r}")

                sender_name_raw = str(getattr(mail, "SenderName", "") or "")
                honorific_name = FSE_NAME_MAP.get(_normalize_name(sender_name_raw))
                sender_email = _get_sender_email(mail)
                # 이름을 추측해서 보내지 않는다는 원칙은 여기서도 동일하게 지킨다.
                if not honorific_name or not sender_email:
                    send_alert(
                        f"[RMA 확인 필요] Oracle 연동 실패인데 담당자 확인 불가 - RMA#{rma_no}",
                        "Salesforce에서 Oracle 연동이 실패(Interface To Oracle = Error)했지만, "
                        f"발신자 '{sender_name_raw}'의 한글 존칭 이름 또는 이메일 주소를 확인하지 "
                        "못해 재생성 요청 메일을 자동으로 보내지 않았습니다.\n"
                        f"메일 제목: {subject}\n링크: {sf_link}\n\n"
                        f"Oracle error message:\n{err_msg}",
                    )
                    continue

                body_text = _build_oracle_error_body(honorific_name, rma_no, err_msg)
                reply = mail.ReplyAll()
                reply.To = sender_email
                # 완료 답장과 달리 용마(창고)는 넣지 않는다 - 오라클 오더 자체가
                # 생성되지 않아 창고가 할 일이 없는 단계이기 때문이다.
                reply.CC = ""
                reply.BCC = ""
                _html_body = reply.HTMLBody or ""
                _content_html = html.escape(body_text).replace("\n", "<br>")
                _m = re.search(r"(<body[^>]*>)", _html_body, re.IGNORECASE)
                _wrapped = f'<div style="{MAIL_FONT_CSS}">{_content_html}</div>'
                if _m:
                    _insert_at = _m.end()
                    reply.HTMLBody = _html_body[:_insert_at] + _wrapped + _html_body[_insert_at:]
                else:
                    reply.HTMLBody = _wrapped + _html_body
                for idx in range(reply.Attachments.Count, 0, -1):
                    try:
                        reply.Attachments.Item(idx).Delete()
                    except Exception:
                        pass

                if AUTO_SEND:
                    reply.Send()
                else:
                    reply.Save()

                oracle_error_notified.add(rma_no)
                state["_oracle_error_notified"] = sorted(oracle_error_notified)
                # 이 건으로 쌓여 있던 파싱 실패 카운터는 의미가 없으므로 정리한다.
                parse_retry.pop(rma_no, None)
                state["_parse_retry"] = parse_retry
                save_state(state)
                log(
                    f"Oracle 연동 실패 재생성 요청 {'발송' if AUTO_SEND else '초안 작성'}: "
                    f"RMA#{rma_no} -> {sender_email}"
                )
                continue

            # 2026-08-18 사용자 요청으로 추가: Defective 계열 답장에는 Case 번호가
            # 반드시 들어가야 하므로, Defective인데 Case 번호를 못 읽었으면 본문에
            # 필요한 정보가 빠진 상태다. 화면이 덜 그려진 일시적 문제일 수 있으니
            # 아래 파싱 실패와 똑같이 재시도 -> 한도 초과 시 알림으로 처리한다
            # (불완전한 답장을 자동 발송하지 않는다).
            case_number = fields.get("case_number")
            case_missing = (
                bool(lines)
                and not all(l["disposition"] == "Unused" for l in lines)
                and not case_number
            )

            # ---- (b) 파싱 실패: 대개 화면이 아직 덜 채워진 것이므로 우선 재시도 ----
            if not order_type or not oracle_order_number or not lines or case_missing:
                attempts = int(parse_retry.get(rma_no, 0)) + 1
                parse_retry[rma_no] = attempts
                state["_parse_retry"] = parse_retry
                save_state(state)
                log(
                    f"[경고] RMA#{rma_no}: 필드 파싱 실패(order_type={order_type}, "
                    f"oracle_order_number={oracle_order_number}, lines={len(lines)}건, "
                    f"case_number={case_number}{', Defective인데 Case 번호 없음' if case_missing else ''}) "
                    f"- {attempts}회차, {PARSE_RETRY_LIMIT}회까지는 다음 실행에서 재시도"
                )
                if attempts >= PARSE_RETRY_LIMIT and rma_no not in parse_alerted:
                    send_alert(
                        f"[RMA 확인 필요] 화면 파싱 실패 - RMA#{rma_no}",
                        "Salesforce 레코드 화면에서 Order Type/Oracle Order Number/"
                        "Parts Order Lines/Case 번호 중 일부를 정상적으로 추출하지 "
                        "못했습니다.\n"
                        f"메일 제목: {subject}\n링크: {sf_link}\n"
                        f"order_type={order_type}, oracle_order_number={oracle_order_number}, "
                        f"lines={len(lines)}건, case_number={case_number}\n"
                        + ("Defective 계열인데 Case 번호(CA...)를 못 읽어서 답장을 보류했습니다.\n"
                           if case_missing else "")
                        +
                        f"Interface To Oracle={fields.get('interface_to_oracle')!r} "
                        "(Error가 아니라서 연동 실패로는 분류되지 않았습니다)\n"
                        f"{attempts}회 연속 실패라 일시적인 문제가 아닌 것으로 보입니다. "
                        "화면 구조가 바뀌었거나 다른 레코드 타입일 수 있으니 수동으로 "
                        "확인해주세요.\n"
                        "(이 RMA에 대해서는 이 알림을 다시 보내지 않으며, 처리는 계속 "
                        "재시도됩니다.)",
                    )
                    parse_alerted.add(rma_no)
                    state["_parse_alerted"] = sorted(parse_alerted)
                    save_state(state)
                continue

            # 여기까지 왔으면 정상 파싱된 것이므로 재시도 카운터를 정리한다.
            if rma_no in parse_retry:
                parse_retry.pop(rma_no, None)
                state["_parse_retry"] = parse_retry
                save_state(state)

            dispositions = {l["disposition"] for l in lines}
            if len(dispositions) > 1:
                log(f"[경고] RMA#{rma_no}: 라인별 Disposition이 혼재함({dispositions}) - 자동 판정 보류")
                send_alert(
                    f"[RMA 확인 필요] Disposition 혼재 - RMA#{rma_no}",
                    "한 RMA 안에 서로 다른 Disposition이 섞여 있어 Unused RMA/Defective RMA를 "
                    f"자동 판정할 수 없습니다({dispositions}).\n"
                    f"메일 제목: {subject}\n링크: {sf_link}\n"
                    f"라인: {lines}\n수동으로 확인해주세요.",
                )
                continue

            rma_type = classify_rma_type(fields)

            # 검증 규칙(Feasibility 10건 전수 일치): Unused RMA는 Oracle Order
            # Number가 항상 7로 시작. 어긋나면 이상 케이스이므로 자동 답장을
            # 만들지 않고 사람에게 넘긴다.
            if rma_type == "Unused RMA" and not oracle_order_number.startswith("7"):
                log(
                    f"[경고] RMA#{rma_no}: Unused RMA인데 Oracle Order Number가 "
                    f"7로 시작하지 않음({oracle_order_number})"
                )
                send_alert(
                    f"[RMA 확인 필요] Unused RMA인데 Order Number가 7로 시작하지 않음 - RMA#{rma_no}",
                    f"Oracle Order Number: {oracle_order_number}\n메일 제목: {subject}\n"
                    f"링크: {sf_link}\n"
                    "실측 검증 규칙(Unused RMA는 항상 7로 시작)과 어긋나는 이상 케이스이므로 "
                    "자동 답장을 만들지 않았습니다. 수동으로 확인해주세요.",
                )
                continue

            sender_name_raw = str(getattr(mail, "SenderName", "") or "")
            sender_key = _normalize_name(sender_name_raw)
            honorific_name = FSE_NAME_MAP.get(sender_key)
            if not honorific_name:
                log(f"[경고] RMA#{rma_no}: 미매핑 발신자 - '{sender_name_raw}'")
                send_alert(
                    f"[RMA 확인 필요] 미매핑 발신자 - RMA#{rma_no}",
                    f"발신자 '{sender_name_raw}'가 FSE_NAME_MAP에 없습니다. 실제 한글 존칭 "
                    "이름을 확인한 뒤 코드에 매핑을 추가해주세요(추측 매핑 금지).\n"
                    f"메일 제목: {subject}\n링크: {sf_link}",
                )
                continue

            sender_email = _get_sender_email(mail)
            if not sender_email:
                log(f"[경고] RMA#{rma_no}: 발신자 이메일 주소를 못 가져옴")
                send_alert(
                    f"[RMA 확인 필요] 발신자 이메일 주소 확인 실패 - RMA#{rma_no}",
                    "원본 메일의 발신자 이메일 주소를 가져오지 못해 답장 초안을 만들지 "
                    f"못했습니다.\n메일 제목: {subject}",
                )
                continue

            body_text = _build_reply_body(
                honorific_name, rma_type, oracle_order_number, lines, case_number or ""
            )

            reply = mail.ReplyAll()
            reply.To = sender_email
            reply.CC = RMA_REPLY_CC
            reply.BCC = ""
            # 2026-07-23 사용자 보고로 수정: reply.Body(plain text)에 직접 대입하면
            # Outlook이 답장 전체(원본 인용부 포함)를 서식 없는 텍스트로 재생성해버려
            # 원본 서식이 깨진다. HTMLBody의 <body> 태그 바로 뒤에 우리 본문만
            # 끼워 넣어 원본 서식을 보존한다.
            _html_body = reply.HTMLBody or ""
            _content_html = html.escape(body_text).replace("\n", "<br>")
            _m = re.search(r"(<body[^>]*>)", _html_body, re.IGNORECASE)
            _wrapped = f'<div style="{MAIL_FONT_CSS}">{_content_html}</div>'
            if _m:
                _insert_at = _m.end()
                reply.HTMLBody = _html_body[:_insert_at] + _wrapped + _html_body[_insert_at:]
            else:
                reply.HTMLBody = _wrapped + _html_body

            # 2026-07-21 실측 확인: reply.Body를 재설정하면 Outlook이 원본 인용
            # 내용의 HTML을 재구성하는 과정에서, 원본에 있던 장식용 이미지(스페이서/
            # 불릿 등)가 "~WRD####.jpg" 같은 이름의 실제 첨부파일로 튀어나오는 경우가
            # 있다(RMA#00593931 건에서 4KB짜리 빈 이미지로 실제 확인됨). HTMLBody만
            # 건드리는 지금 방식에서는 재현되지 않을 가능성이 높지만, 이 답장은
            # 어차피 첨부파일이 전혀 필요 없으므로 안전하게 계속 제거한다.
            for idx in range(reply.Attachments.Count, 0, -1):
                try:
                    reply.Attachments.Item(idx).Delete()
                except Exception:
                    pass

            if AUTO_SEND:
                reply.Send()  # 2026-07-16 사용자 요청으로 바로 발송
            else:
                reply.Save()  # 임시보관함 초안만 저장(사람이 검토 후 발송)

            state[rma_no] = {
                "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "subject": subject,
                "order_type": rma_type,
                "oracle_order_number": oracle_order_number,
                "case_number": case_number or "",
                "sender": sender_name_raw,
                "sender_email": sender_email,
            }
            save_state(state)
            log(
                f"완료 및 답장 {'발송' if AUTO_SEND else '초안 작성'}: RMA#{rma_no} ({rma_type}, "
                f"Oracle Order Number={oracle_order_number}"
                f"{f', Case={case_number}' if rma_type != 'Unused RMA' and case_number else ''}) "
                f"-> {sender_email}"
            )

        except Exception as e:
            log(f"[에러] RMA#{rma_no} 처리 중 예외 발생: {_exc_detail(e)}")
            send_alert(
                f"[RMA 확인 필요] 처리 중 예외 발생 - RMA#{rma_no}",
                f"자동 처리 중 예상하지 못한 오류가 발생했습니다: {e}\n메일 제목: {subject}",
            )
        finally:
            # RMA 1건마다 드라이버를 새로 만들므로 프로세스까지 정리한다
            # (close()는 탭만 닫는다 - close_rma_driver 설명 참고, 2026-08-06).
            close_rma_driver(driver)


# ==============================================================
# main
# ==============================================================
def main():
    lock = _acquire_singleton_lock()
    if lock is None:
        log("이미 다른 인스턴스가 실행 중 - 종료 (겹치는 스케줄 트리거로 추정)")
        return
    try:
        log("===== rma_auto_reply 시작 =====")
        state = load_state()
        processed_rma = {k for k in state.keys() if not k.startswith("_")}

        try:
            new_mails = find_new_rma_mails(processed_rma)
        except Exception as e:
            log(f"[에러] 메일 검색 실패: {_exc_detail(e)}")
            return

        if not new_mails:
            log("신규 RMA 메일 없음. 종료.")
            return

        new_mails.reverse()  # 오래된 것부터 순서대로 처리
        process_rma_mails(new_mails, state)

        log("===== rma_auto_reply 종료 =====\n")
    finally:
        _release_singleton_lock(lock)


if __name__ == "__main__":
    main()
