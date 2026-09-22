# -*- coding: utf-8 -*-
"""
ship_confirm_watcher.py

Bohyun Kim(bohyunk@candelamedical.com)이 보내는 "[장비납품이동] ... - 쉽컨펌 및
세금계산서 요청/발행" 계열 메일(받은편지함 > Operation > Bohyun Kim 폴더)을 감시해서
본문의 8자리 주문번호(00으로 시작)를 뽑아, Oracle Fusion Inventory Management의
Manage Shipment Lines에서 해당 주문의 shipment를 모두 찾아 각각
Ship Confirm Rule을 "Candela Ship Rule"로 바꾸고 Ship Confirm을 실행한다.

사용자가 알려준 수동 처리 절차:
1. 메일 본문에서 00으로 시작하는 8자리 번호 확인
2. Oracle Fusion: Supply Chain Execution > Inventory Management > Show Tasks
   (Shipments) > Manage Shipment Lines
3. Order에 그 번호 입력 -> 검색
4. 결과의 Shipment 컬럼에 9로 시작하는 7자리 번호가 나옴(중복 있으면 한 번만)
5. 각 shipment 번호 클릭 -> 상단 Actions -> Change Ship Confirm Options ->
   Ship Confirm Rule을 "Candela Ship Rule"로 변경(기본값은 보통 Try&Buy) ->
   Save and Close
6. 상단 Ship Confirm 클릭
7. 4에서 나온 모든 shipment 번호에 대해 5~6 반복

2026-07-20 전체 흐름 실측 검증 완료(주문 00237693 / shipment 9922008, Shipment
Status Open -> Closed 확인됨, Packing Slip 17825 부여):
- 로그인: icbl_ci_watcher.py의 Edge 세션(SSO 자동 재로그인) 재사용 확인됨. 단,
  Edge를 콜드 스타트(디버그 포트로 떠 있는 인스턴스가 없어 새로 실행)하면 로그인까지
  수 분(실측 6분 이상) 걸릴 수 있음 - 조급하게 실패로 판단하지 말 것.
- 네비게이션: Home -> Supply Chain Execution -> Inventory Management -> Tasks ->
  Shipments -> Manage Shipment Lines 진입 확인됨.
- Order 검색창은 Advanced Search 패널(연산자+값 구조)이라 label의 for가 연산자
  select를 가리킴 - 실제 입력창은 `input[type=text][aria-label='Order']`.
- 검색 결과 렌더링도 콜드 스타트 직후엔 느려서, 고정 sleep(4초)만으로는 실제로
  shipment가 있는데 0건으로 잘못 읽는 경우가 실측됨 -> 폴링 방식으로 변경.
- Change Ship Confirm Options 다이얼로그: 기본 Ship Confirm Rule 값은 보통
  "Candela Try & Buy"이고, "Candela Ship Rule"로 명시적으로 바꿔야 함(_field_by_label
  방식으로 정상 조회됨). "Save and Close" 버튼은 Oracle ADF가 accesskey 밑줄
  표시 때문에 글자를 여러 자식 노드로 쪼개놔서 Selenium의 XPath text()로는 못
  찾음(자손 텍스트를 다 보는 JS textContent 매칭으로 클릭, _click_by_textcontent).
- 상단 "Ship Confirm" 버튼도 같은 accesskey 문제로 동일한 방식으로 클릭.
  클릭 후 "Confirmation: The shipment {번호} was confirmed." 다이얼로그가 뜨고
  OK를 눌러야 닫힘(이것도 _click_by_textcontent로 처리).
아직 실측 못한 것: 한 주문에 shipment가 여러 개인 경우(중복 아닌 서로 다른 번호가
2개 이상) 순차 처리가 문제없이 되는지, Ship Confirm 실패/예외 케이스(예:
Customer 미표시 지연 같은 것)의 처리.
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime

# icbl_ci_watcher.py의 검증된 오라클 세션 관리 로직 재사용(같은 Edge 인스턴스 공유)
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
    sso_relogin,
    recover_oracle_login,
    oracle_is_logged_in,
    OracleLoginRequired,
    ORACLE_HOME_URL,
    _click_text,
    _js_click_text,
    tasks_panel_open,
    wait_or_sleep,
    text_visible,
    element_present,
    _wait_find,
    _force_restart_edge,
    acquire_oracle_lock,
    release_oracle_lock,
    set_edge_owner,
)

# 2026-09-18: 이 프로세스는 자기 전용 Edge(포트/프로필)를 쓴다.
set_edge_owner("ship_confirm_watcher")

# ==============================================================
# 경로/설정
# ==============================================================
ROOT = os.path.dirname(__file__)
LOG_PATH = os.path.join(ROOT, "ship_confirm_watcher.log")
STATE_PATH = os.path.join(ROOT, "_processed_orders.json")
LOCK_FILE_PATH = os.path.join(ROOT, "_watcher.lock")

OUTLOOK_PARENT_SUBFOLDER = "Operation"
OUTLOOK_SUBFOLDER = "Bohyun Kim"
SUBJECT_KEYWORD = "쉽컨펌 및 세금계산서"

SHIP_CONFIRM_RULE = "Candela Ship Rule"

# 2026-08-06(2차) 추가: Inventory Management 화면이 다 그려질 때까지 기다리는 한도.
# pick_release_watcher.py의 같은 이름 상수와 같은 값/같은 이유다(그쪽은 08-06에
# 이미 늘렸는데 이 파일만 옛 값이 남아 실측 0/3 실패했다 - 아래
# navigate_to_manage_shipment_lines 주석 참고).
INV_PAGE_READY_TIMEOUT_SEC = 40

ALERT_MAIL_TO = "yoongil.chae@candelamedical.com"

# 이 시각 이전 메일은 절대 자동 처리하지 않음(과거분은 이미 사람이 수동으로
# 처리했음 - 자동화 도입 시점부터만 처리).
# 2026-07-20 09:40 사용자 확인: 00237693(쁘띠365의원)은 이미 처리 완료 + 답장은
# 사용자가 직접 보냄. "이 이후부터"만 자동 추적하라는 요청으로 컷오프를 이 시각으로
# 올림 - 그 이전 백로그(테스트로 조회만 해본 것들 포함)는 자동으로 건드리지 않음.
# 2026-08-07 11:25 사용자 요청으로 컷오프를 이 시각으로 올림. 이날 오전에 0건
# 오판으로 "완료" 초안만 만들어지고 실제로는 쉽컨펌이 안 된 건들(00211195,
# 00237571, 00238212)을 사용자가 전부 수동 처리했다 - 그 이전 메일은 자동으로
# 다시 건드리지 않고, 이 시각 이후에 받은 메일부터만 처리한다.
LOOKBACK_START_DATE = datetime(2026, 8, 7, 11, 25, 0)


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


def load_state() -> dict:
    """2026-08-06: 예전에는 파일이 깨져 있으면 빈 상태({})를 돌려줬는데, 그건
    "아직 아무 주문도 쉽컨펌 안 했다"는 뜻이라 이미 처리한 주문을 다시 처리하고
    완료 답장을 다시 보내게 된다 - 파일이 있는데 깨졌으면 회차를 중단시킨다
    (첫 실행처럼 파일 자체가 없는 경우는 예전처럼 {}로 정상 진행)."""
    return read_json_state(STATE_PATH, "쉽컨펌 처리 이력", strict=True)


def save_state(state: dict):
    # 2026-08-06: open("w")는 파일을 먼저 비우므로 쓰는 도중 죽으면 이력이
    # 깨진다 - 임시 파일에 쓰고 바꿔치기하는 원자적 저장으로 변경.
    atomic_write_json(STATE_PATH, state)


def _acquire_singleton_lock():
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


# 2026-08-10 사용자 요청: 자동 발송/초안 메일 글꼴을 굴림 -> 맑은 고딕으로 통일.
# 굴림이 나오던 이유: 답장에 끼워 넣던 <div>에 글꼴 지정이 없어 원본 메일의
# 글꼴을 그대로 물려받았고, 평문(.Body)으로 만들던 메일은 Outlook 평문
# 기본 글꼴을 따라갔다.
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
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = ALERT_MAIL_TO
    mail.Subject = subject
    mail.HTMLBody = mail_text_to_html(body)
    mail.Save()
    log(f"알림 메일 초안 저장: {subject}")


def _try_sso_relogin(driver) -> bool:
    """세션이 끊겨 Sign In 페이지에 있으면 SSO 버튼을 눌러 재로그인을 시도한다.

    2026-08-06(2차): 실제 구현을 icbl_ci_watcher.sso_relogin()으로 모았다.
    예전엔 이 로직을 파일마다 복사해 뒀는데, 같은 날 확인해보니 복사본끼리
    대기시간이 24초/48초로 어긋나 있었다(주석은 전부 "24초"라고 적혀 있었음).
    그리고 이번에 발견한 자동 복구 실패 원인 2가지(버튼 렌더 지연을 '버튼 없음'
    으로 오판 / MS 계정 타일이 is_displayed()로는 안 잡힘)도 4곳에 따로 고치면
    또 어긋난다. 구현은 하나만 두고 여기서는 이 파일의 log()만 넘긴다 -
    로그는 그대로 이 파일의 로그에 남는다."""
    return sso_relogin(driver, log)


# 2026-09-11: 본문 전체(인용된 과거 메일 이력 포함)에서 주문번호를 긁으면
# 스레드에 남아있는 옛 주문번호까지 "신규"로 오인한다(00223579 요청 메일의
# 인용문에 있던 00754550/00754552가 실제 사례 - 이미 끝난 옛 건인데 매 회차
# shipment 0건으로 재시도됐다). 인용 구분선/헤더가 나오기 전, 사람이 새로
# 쓴 부분까지만 잘라서 그 안에서만 주문번호를 찾는다.
QUOTE_MARKER_RE = re.compile(
    r"_{10,}|^\s*(보낸\s*사람|From)\s*:|^-{3,}\s*(Original Message|원본 메일)\s*-{3,}",
    re.IGNORECASE | re.MULTILINE,
)


def strip_quoted_history(body: str) -> str:
    m = QUOTE_MARKER_RE.search(body)
    return body[:m.start()] if m else body


def extract_order_nos(body: str) -> list:
    """본문에서 오라클 오더번호(00으로 시작하는 8자리 숫자)를 추출한다.
    SMAX(ServiceMax) PO 번호도 같은 8자리 형식이라 섞여 나올 수 있어서,
    번호 바로 앞에 'SMAX'가 언급된 경우는 오라클 오더번호가 아니므로 제외한다
    (2026-09-22, 00559888 SMAX PO 오탐 발견 후 수정)."""
    order_nos = []
    for m in re.finditer(r"\b(00\d{6})\b", body):
        preceding = body[max(0, m.start() - 20):m.start()]
        if re.search(r"SMAX", preceding, re.IGNORECASE):
            continue
        order_nos.append(m.group(1))
    return list(dict.fromkeys(order_nos))


# ==============================================================
# 1) Outlook에서 신규 쉽컨펌 메일 찾기
# ==============================================================
def find_new_ship_confirm_mails(processed_orders: set) -> list:
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
        if OUTLOOK_SUBFOLDER in str(f.Name):
            target = f
            break
    if target is None:
        raise RuntimeError(
            f"Outlook 폴더를 못 찾음: 받은편지함 > {OUTLOOK_PARENT_SUBFOLDER} > {OUTLOOK_SUBFOLDER}"
        )

    items = target.Items
    items.Sort("[ReceivedTime]", True)

    results = []
    # 2026-08-06: 예전엔 조용히 건너뛰어서 쉽컨펌 요청 메일 한 통이 통째로
    # 빠져도 흔적이 없었다. 동작은 그대로 두고 흔적만 남긴다(로그 폭주 방지로
    # 앞의 3건만).
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

        received_dt = datetime(
            mail.ReceivedTime.year, mail.ReceivedTime.month, mail.ReceivedTime.day,
            mail.ReceivedTime.hour, mail.ReceivedTime.minute, mail.ReceivedTime.second,
        )
        if received_dt < LOOKBACK_START_DATE:
            break  # 최신순 정렬이므로 여기부터는 더 볼 필요 없음(과거 메일)

        subject = str(mail.Subject or "")
        if SUBJECT_KEYWORD not in subject:
            continue

        body = strip_quoted_history(str(mail.Body or ""))
        order_nos = extract_order_nos(body)
        if not order_nos:
            log(f"[경고] 본문(인용 이력 제외)에서 8자리 주문번호를 못 찾음(스킵): {subject}")
            continue

        new_order_nos = [o for o in order_nos if o not in processed_orders]
        if not new_order_nos:
            continue

        results.append({
            "entry_id": mail.EntryID,
            "subject": subject,
            "order_nos": new_order_nos,
        })

    return results


# ==============================================================
# 2) 오라클 Manage Shipment Lines에서 Ship Confirm 실행
# ==============================================================
def _field_by_label(driver, label_text: str):
    """일반 폼(라벨 for가 필드 id를 직접 가리킴)에서 쓰는 표준 방식."""
    from selenium.webdriver.common.by import By
    label = _wait_find(driver, By.XPATH, f"//label[normalize-space(text())='{label_text}']")
    input_id = label.get_attribute("for")
    return _wait_find(driver, By.ID, input_id)


def _advanced_search_field_by_label(driver, label_text: str):
    """Advanced Search 패널(연산자+값 구조) 전용 - 실측 확인된 방식.
    label의 for는 연산자 select를 가리키므로, 실제 값 입력창은
    aria-label이 label_text와 같은 text input을 찾는다."""
    from selenium.webdriver.common.by import By
    return _wait_find(
        driver, By.XPATH,
        f"//input[@type='text' and normalize-space(@aria-label)='{label_text}']"
    )


def navigate_to_manage_shipment_lines(driver):
    """2026-07-23 실측: 한 주문에 shipment가 여러 개일 때, 첫 shipment의 Ship
    Confirm 처리 직후 다음 shipment를 위해 재진입하는 두 번째 호출에서 Fusion이
    아직 배경 정리 중이라 Tasks 아이콘이 기본 타임아웃(8초) 안에 안 뜨는 경우가
    2건 실측됨(주문 00207006). 실패하면 한 번 더 재시도(타임아웃 넉넉히)한다."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    last_err = None
    for attempt in range(2):
        try:
            driver.get(ORACLE_HOME_URL)
            # 2026-08-06(2차) 고정대기 -> 조건대기 전환. wait_or_sleep은 조건이
            # 충족되면 즉시 진행하고, 끝까지 안 되면 **원래 sleep과 정확히 같은
            # 시간**을 기다린 뒤 진행한다(최악의 경우가 기존과 동일 = 더 나빠질
            # 수 없음). 아래는 전부 '조건이 미리 참일 수 없는' 자리만 골랐다.
            # 여기: driver.get()으로 페이지를 새로 받았으므로 이 텍스트는 새 홈이
            # 그려진 뒤에만 존재할 수 있다.
            wait_or_sleep(driver, text_visible("Supply Chain Execution"), 5)

            # 2026-08-06(2차): 네이티브 클릭이 백그라운드 창에서 예외 없이 조용히
            # 씹히는 것이 실측됐다 - 같은 오라클 스프링보드에서 icbl의 이동을
            # A/B로 재본 결과 네이티브 0/3 성공(각 80초 소진), JS 클릭 3/3 성공
            # (6~13초)이었다. 여기도 같은 스프링보드를 쓰므로 동일하게 바꾼다.
            # 클릭 대상/순서/대기시간은 그대로다(_js_click_text 설명 참고).
            _js_click_text(driver, "Supply Chain Execution")
            # 여기는 일부러 고정 대기를 유지한다: 스프링보드에서는 'Inventory
            # Management' 아이콘이 이 클릭 **전에도 이미 보이는** 경우가 있어
            # (icbl _goto_scheduled_processes에 같은 함정이 실측 기록돼 있다)
            # 조건이 미리 참이 되어 아이콘이 재배치되는 중에 눌러버릴 수 있다.
            time.sleep(3)
            _js_click_text(driver, "Inventory Management")
            # Tasks 아이콘은 Inventory Management 화면에만 있고 스프링보드에는
            # 없다 - 미리 참일 수 없어 안전. 5초 안에 안 뜨면 기존처럼 진행하고
            # 바로 아래 _wait_find(최대 40초)가 이어서 기다린다.
            wait_or_sleep(driver, element_present(By.XPATH, "//img[@title='Tasks']"), 5)

            # 2026-08-06(2차) 실측: 이 화면(Inventory Management)이 다 그려지는 데
            # 걸리는 시간이 여기 잡힌 예산(Tasks 15초 / Shipments select 기본 8초)을
            # 넘는다. pick_release_watcher.py는 같은 화면을 쓰면서 08-06에 이미
            # INV_PAGE_READY_TIMEOUT_SEC=40으로 늘렸는데 이 파일만 옛 값이 남아
            # 있었다 - A/B로 재보니 pick_release는 8/8 성공인데 이 함수는 0/3
            # 실패("Tasks 아이콘 못 찾음", "Shipments select 못 찾음")였다.
            # 같은 값으로 맞춘다. _wait_find는 0.3초 간격 폴링이라 준비되는 즉시
            # 반환하므로, 값을 키워도 정상 상황의 속도에는 영향이 없다(느릴 때만
            # 더 기다려줄 뿐 - 더 나빠질 수 없는 변경).
            tasks_icon = _wait_find(driver, By.XPATH, "//img[@title='Tasks']",
                                    timeout=INV_PAGE_READY_TIMEOUT_SEC)
            # 2026-08-06(2차) 공유 브라우저 상태 간섭 대응: Tasks 아이콘은
            # **토글**이라 이미 열려 있는데 또 누르면 패널이 닫힌다. 이 열림
            # 상태는 driver.get()으로 페이지를 다시 열어도 유지되고, 같은 Edge를
            # 공유하는 자동화 중 아무도 패널을 닫지 않는다 - 앞선 자동화가
            # 열어둔 채 끝내면 여기서 스스로 닫아버려 아래 Shipments select를
            # 못 찾는다. 네이티브 클릭도 백그라운드 창에서 씹히는 게 실측돼
            # JS 클릭으로 함께 바꾼다(_js_click_text 설명과 같은 이유).
            if not tasks_panel_open(driver):
                driver.execute_script("arguments[0].click();", tasks_icon)
            # Shipments 옵션을 가진 select는 Tasks 패널이 열려야 생긴다.
            # (패널이 이미 열려 있어 위에서 클릭을 건너뛴 경우엔 이미 존재하므로
            #  즉시 통과하는 게 맞다 - 기다릴 대상이 없는 상황이다.)
            wait_or_sleep(driver, element_present(
                By.XPATH, "//select[option[normalize-space(text())='Shipments']]"), 2)

            sel_el = _wait_find(driver, By.XPATH,
                                "//select[option[normalize-space(text())='Shipments']]",
                                timeout=INV_PAGE_READY_TIMEOUT_SEC)
            Select(sel_el).select_by_visible_text("Shipments")
            # 'Manage Shipment Lines'는 Shipments 카테고리의 작업이라 다른
            # 카테고리(예: sco가 남긴 Inventory)에서는 안 보인다 - 즉 카테고리를
            # 실제로 바꿔야 하는 경우엔 미리 참일 수 없다. 이미 Shipments였다면
            # 보이는 게 정상이고 즉시 진행하는 것이 맞다.
            wait_or_sleep(driver, text_visible("Manage Shipment Lines"), 2)

            _js_click_text(driver, "Manage Shipment Lines")
            # 이 검색 입력칸은 Manage Shipment Lines 화면에만 있다 - 미리 참일 수
            # 없어 안전. 실측: aria-label이 앞에 공백 붙은 " Order"로 내려오므로
            # normalize-space로 비교한다.
            wait_or_sleep(driver, element_present(
                By.XPATH, "//input[normalize-space(@aria-label)='Order']"), 5)
            return
        except Exception as e:
            last_err = e
            log(f"[경고] Manage Shipment Lines 네비게이션 실패(시도 {attempt + 1}/2): {e}")
    raise last_err


def _click_by_textcontent(driver, text: str, tags: str = "button, a", timeout: float = 8.0) -> bool:
    """Oracle ADF 버튼(예: 'Save and Close', 상단 'Ship Confirm')은 accesskey 밑줄
    표시 때문에 실제 글자가 여러 자식 노드로 쪼개져 있어, Selenium의
    XPath text()(직계 텍스트 노드만 봄)로는 못 찾는 경우가 실측 확인됨(2026-07-20,
    주문 00237693/shipment 9922008 실제 처리 중 발견). JS textContent(자손 텍스트
    전부 포함)로 찾아서 클릭한다."""
    deadline = time.time() + timeout
    script = """
        var text = arguments[0];
        var tags = arguments[1].split(',').map(function(s){return s.trim();});
        var els = document.querySelectorAll(tags.join(','));
        for (var i=0;i<els.length;i++){
            var t = (els[i].textContent || '').replace(/\\s+/g, ' ').trim();
            if (t === text) {
                var rect = els[i].getBoundingClientRect();
                if (rect.width>0 && rect.height>0){
                    els[i].scrollIntoView(true);
                    els[i].click();
                    return true;
                }
            }
        }
        return false;
        """
    while time.time() < deadline:
        if driver.execute_script(script, text, tags):
            return True
        time.sleep(0.5)
    return False


def find_shipment_numbers_for_order(driver, order_no: str) -> list:
    """Order 검색 후 결과에 나오는 9로 시작하는 7자리 shipment 번호를 중복 없이 반환.
    2026-07-20 실측: Edge를 콜드 스타트한 직후에는 검색 결과 렌더링이 4초보다
    훨씬 오래 걸려(실측 6분 이상 걸린 사례 있음 - 로그인 자체가 늦어진 경우 포함)
    고정 sleep만으로는 결과를 0건으로 잘못 읽는 경우가 있었다(주문 00237693에서
    실제로는 shipment가 있었는데 0건으로 보고됨). 결과 영역에 변화가 생기거나
    최대 대기시간까지 폴링한다."""
    from selenium.webdriver.common.by import By

    order_el = _advanced_search_field_by_label(driver, "Order")
    order_el.click()
    order_el.clear()
    order_el.send_keys(order_no)
    time.sleep(1)

    search_btns = [el for el in driver.find_elements(By.XPATH, "//*[normalize-space(text())='Search']") if el.is_displayed()]
    if not search_btns:
        raise RuntimeError("Search 버튼을 못 찾음")
    search_btns[0].click()

    # 2026-08-07: 예전에는 번호가 '하나라도' 잡히면 즉시 반환했다. 그런데 결과 표는
    # 행 단위로 순차 렌더되므로, 첫 행이 그려진 순간 반환해버리면 뒤쪽 행이 아직
    # 화면에 없는 상태로 다음 단계(링크 클릭)로 넘어간다. 실측: 주문 00236830에서
    # 3건 중 마지막 9962548의 링크를 못 찾아 3회 재시도가 전부 같은 이유로 실패.
    # -> 같은 결과가 두 번 연속 나올 때까지(=표가 더 안 늘어날 때까지) 기다린다.
    deadline = time.time() + 30
    shipment_nos = []
    prev = None
    while time.time() < deadline:
        time.sleep(2)
        page_text = driver.find_element(By.TAG_NAME, "body").text
        shipment_nos = sorted(set(re.findall(r"\b(9\d{6})\b", page_text)))
        if shipment_nos and shipment_nos == prev:
            break
        if not shipment_nos and "No data to display" in page_text:
            break
        prev = shipment_nos
    return shipment_nos


def change_ship_confirm_rule_and_confirm(driver, shipment_no: str) -> dict:
    """shipment 하나에 대해 Change Ship Confirm Options -> Candela Ship Rule ->
    Save and Close -> Ship Confirm 클릭까지 수행.
    반환: {"already_closed": bool, "ship_confirmed": bool}
    2026-07-20 실측 검증 완료(주문 00237693 / shipment 9922008, Open -> Closed 확인):
    - Change Ship Confirm Options 다이얼로그의 기본 Ship Confirm Rule 값은
      "Candela Try & Buy"였고, "Candela Ship Rule"로 명시적으로 바꿔야 했다.
    - Ship Confirm 클릭 후 "Confirmation: The shipment {번호} was confirmed." 다이얼로그가
      뜨고 OK 버튼을 눌러야 닫힌다."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    # 2026-08-07: 이 파일에서 유일하게 '한 번 보고 없으면 즉시 실패'하던 지점이었다.
    # 다른 요소는 전부 _wait_find/폴링으로 기다리는데 여기만 단발성이라, 검색 결과
    # 표가 아직 다 안 그려진 순간에 걸리면 그대로 RuntimeError로 떨어졌다
    # (주문 00236830 / shipment 9962548 실측, 재시도 3회 전부 같은 이유로 실패).
    # 링크가 뜰 때까지 폴링하고, 그래도 없으면 '그때 화면에 실제로 보이던 번호'를
    # 함께 남겨 다음 진단을 쉽게 한다.
    link_xpath = f"//a[normalize-space(text())='{shipment_no}']"
    deadline = time.time() + 20
    shipment_links = []
    while time.time() < deadline:
        shipment_links = [el for el in driver.find_elements(By.XPATH, link_xpath) if el.is_displayed()]
        if shipment_links:
            break
        time.sleep(0.5)
    if not shipment_links:
        try:
            visible = sorted(set(re.findall(
                r"\b(9\d{6})\b", driver.find_element(By.TAG_NAME, "body").text)))
        except Exception:
            visible = []
        raise RuntimeError(f"Shipment 링크를 못 찾음: {shipment_no} (화면에 보이는 번호: {visible})")
    shipment_links[0].click()
    time.sleep(4)

    status_label = _wait_find(driver, By.XPATH, "//label[normalize-space(text())='Shipment Status']", timeout=8)
    status_val = driver.execute_script(
        "var l = arguments[0]; var td = l.closest('td'); "
        "return td.nextElementSibling ? td.nextElementSibling.textContent.trim() : '';",
        status_label,
    )
    if status_val == "Closed":
        log(f"  shipment {shipment_no}: 이미 Closed 상태 - 건너뜀")
        return {"already_closed": True, "ship_confirmed": False}

    actions_btns = [el for el in driver.find_elements(By.XPATH, "//*[normalize-space(text())='Actions']") if el.is_displayed()]
    if not actions_btns:
        raise RuntimeError("Actions 버튼을 못 찾음")
    actions_btns[0].click()
    time.sleep(2)

    # 2026-08-06(2차): 여기만 네이티브 클릭으로 남아 있었다. 바로 아래의 실제
    # 트랜잭션 버튼들(Save and Close / Ship Confirm / OK)은 이미
    # _click_by_textcontent가 execute_script 안에서 click()을 부르는 **JS 클릭**
    # 이므로, 이 한 줄만 네이티브라 혼자 튀는 상태였다 - 경로를 일관되게 맞춘다.
    # 안전성: 이 클릭은 다이얼로그를 여는 것뿐이라 아직 아무 상태도 바꾸지 않는다.
    # 씹히면 다음 줄의 "Ship Confirm Rule" 라벨을 못 찾아 예외로 안전하게 끝난다
    # (지금과 동일). 성공하면 예전처럼 다이얼로그가 열린다 - 더 나빠질 수 없다.
    _js_click_text(driver, "Change Ship Confirm Options")
    time.sleep(3)

    rule_el = _field_by_label(driver, "Ship Confirm Rule")
    Select(rule_el).select_by_visible_text(SHIP_CONFIRM_RULE)
    time.sleep(1)

    if not _click_by_textcontent(driver, "Save and Close"):
        raise RuntimeError("Save and Close 버튼을 못 찾음")
    time.sleep(3)

    if not _click_by_textcontent(driver, "Ship Confirm"):
        raise RuntimeError("Ship Confirm 버튼을 못 찾음(비활성 상태일 수 있음)")
    time.sleep(4)

    # "Confirmation: The shipment {번호} was confirmed." 다이얼로그의 OK 버튼
    _click_by_textcontent(driver, "OK", tags="button, a", timeout=6)
    time.sleep(2)

    return {"already_closed": False, "ship_confirmed": True}


def _prepend_html_text(reply, text: str):
    """reply.Body(plain text)에 직접 대입하면 Outlook이 답장 전체(원본 인용부 포함)를
    서식 없는 텍스트로 재생성해버려 원본 서식이 깨진다. HTMLBody의 <body> 태그
    바로 뒤에 텍스트만 끼워 넣어 원본 서식을 보존한다. 2026-07-23 사용자 보고로 수정."""
    import html as html_module
    html_body = reply.HTMLBody or ""
    content_html = html_module.escape(text).replace("\n", "<br>")
    m = re.search(r"(<body[^>]*>)", html_body, re.IGNORECASE)
    wrapped = f'<div style="{MAIL_FONT_CSS}">{content_html}</div>'
    if m:
        insert_at = m.end()
        reply.HTMLBody = html_body[:insert_at] + wrapped + html_body[insert_at:]
    else:
        reply.HTMLBody = wrapped + html_body


def create_completion_reply(entry_id: str):
    """원본 메일에 ReplyAll로 완료 답장을 즉시 발송한다.
    2026-07-20 사용자 요청으로 추가(당시엔 초안만 저장).
    2026-09-11 사용자 요청으로 초안 저장 대신 바로 발송으로 변경."""
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    mail = ns.GetItemFromID(entry_id)
    reply = mail.ReplyAll()
    _prepend_html_text(reply, "안녕하세요 보현 과장님,\n\n쉽컨펌 완료됐습니다.\n\n")
    reply.Send()


# ==============================================================
# 오라클 화면 조작 공통 재시도 (2026-08-05 추가)
# ==============================================================
# 2026-08-05 사용자 요청으로 오라클을 쓰는 자동화 5종에 동일하게 넣은 헬퍼.
# 배경: pick_release_watcher 실측(2026-08-05 18:00 회차)에서 SSO 재로그인 직후
# "no such element: //img[@title='Tasks']"(화면 진입 실패)가 연달아 났는데,
# 자체 재시도 레이어가 있던 경로는 살아남고 없던 경로는 그대로 실패해 다음
# 예약 실행까지 밀렸다 - 같은 실행 안에서 짧게 쉬었다 다시 시도하게 한다.
# 2026-08-05 사용자 확인: Ship Confirm 같은 오라클 트랜잭션은 애초에 한 번밖에
# 안 된다(이미 처리된 건은 검색 자체가 안 됨). 즉 재시도가 중복 처리를 만들
# 수 없어서, 화면 진입/검색뿐 아니라 확정 단계에도 재시도를 붙였다.
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
            log(f"  [재시도] {label}: 오라클 처리 실패({type(e).__name__}) - "
                f"{wait}초 후 {attempt + 2}/{attempts}번째 시도")
            time.sleep(wait)
            if before_retry is not None:
                try:
                    before_retry()
                except Exception as e2:
                    log(f"  [재시도] {label}: 재시도 전 화면 복구 실패(무시하고 진행): {e2}")
    raise last_exc


def process_order(driver, order_no: str) -> dict:
    def _nav_and_find():
        navigate_to_manage_shipment_lines(driver)
        return find_shipment_numbers_for_order(driver, order_no)

    # 화면 진입/검색은 다시 해도 부작용이 없으므로 일시적 오류면 재시도한다.
    shipment_nos = run_with_oracle_retry(f"주문 {order_no} 화면 진입/검색", _nav_and_find)

    # 2026-08-07: 0건은 예외가 아니라 '정상 반환'이라 위 재시도가 안 걸렸다. 그런데
    # 실측상 0건의 상당수는 진짜 0건이 아니라 결과 표가 아직 안 그려진 것이다
    # (주문 00236830 수동 재실행: 1차 0건 -> 60초 뒤 재검색 3건 전부).
    # 화면을 새로 진입해 다시 검색해본다 - 검색은 부작용이 없어 반복해도 안전하다.
    for extra in range(2):
        if shipment_nos:
            break
        log(f"  주문 {order_no}: shipment 0건 - 화면을 새로 열어 재검색 "
            f"({extra + 2}/3번째 시도)")
        time.sleep(5)
        try:
            shipment_nos = _nav_and_find()
        except Exception as e:
            log(f"  주문 {order_no}: 재검색 실패(무시하고 진행): {exc_detail(e)}")

    log(f"  주문 {order_no}: shipment {len(shipment_nos)}건 발견 {shipment_nos}")

    results = {}
    for sn in shipment_nos:
        try:
            # 2026-08-05 사용자 확인: Ship Confirm은 오라클에서 한 번밖에 안 된다
            # (이미 확정된 건은 검색/재확정 자체가 안 됨). 게다가 이 함수는
            # 첫머리에서 Shipment Status를 읽어 "Closed"면 그냥 건너뛰므로,
            # 1차 시도가 실제로 확정까지 갔다가 화면 읽기에서 터진 경우에도
            # 재시도는 중복 확정이 아니라 already_closed로 정리된다 - 그래서
            # 여기에도 재시도를 붙였다.
            r = run_with_oracle_retry(
                f"{order_no} / {sn} Ship Confirm",
                lambda s=sn: change_ship_confirm_rule_and_confirm(driver, s),
                before_retry=_nav_and_find,
            )
            results[sn] = r
            log(f"  {order_no} / {sn}: {r}")
        except Exception as e:
            log(f"[에러] {order_no} / {sn} 처리 실패: {exc_detail(e)}")
            results[sn] = {"error": str(e)}
        # 다음 shipment 처리를 위해 검색 화면으로 다시 진입(Cancel로 돌아가면
        # 대시보드로 튈 수 있어 매번 새로 네비게이션 - pick_release_watcher.py와
        # 동일한 방식). 여기서 일시적으로 실패해도 남은 shipment을 포기하지
        # 않도록 재시도한다(2026-08-05).
        run_with_oracle_retry(f"주문 {order_no} 재네비게이션", _nav_and_find)

    return results


# ==============================================================
# main
# ==============================================================
def main():
    lock = _acquire_singleton_lock()
    if lock is None:
        log("이미 다른 인스턴스가 실행 중 - 종료")
        return
    driver = None
    try:
        log("===== ship_confirm_watcher 시작 =====")
        state = load_state()
        processed = set(state.keys())

        try:
            new_mails = find_new_ship_confirm_mails(processed)
        except Exception as e:
            log(f"[에러] 메일 검색 실패: {exc_detail(e)}")
            return

        if not new_mails:
            log("신규 쉽컨펌 메일 없음. 종료.")
            return

        # 2026-09-18: 공유 Edge 락을 걸었다가(TO 7882258 실사고로 도입) 같은 날
        # stale 판정 구멍으로 다른 스크립트에서 실전 충돌이 났다 - 대신 이
        # 스크립트를 전용 Edge(포트/프로필)로 완전히 분리해 겹칠 일 자체를
        # 없앴다(set_edge_owner("ship_confirm_watcher") 참고). 락 제거.

        # 2026-09-18: 이 구간(Edge 실행~로그인 복구)에 try/except가 없어서 여기서
        # 예외가 나면 로그 한 줄도 안 남기고 파이썬이 그대로 죽었다(exit code 1) -
        # 사용자가 "시작만 찍히고 끊겼는데 왜 죽었는지 모르겠다"고 지적해서 발견.
        # 스케줄러의 30분 반복은 각 회차가 독립 실행이라 다음 회차는 정상 도는데,
        # 원인만 알 수 없었다 - 최소한 무엇 때문에 죽었는지는 로그에 남긴다.
        try:
            ensure_edge_running()
            # 2026-08-06: driver를 try 바깥에서 미리 None으로 잡아두고, 아래 처리
            # 도중 어떤 예외가 나도 finally에서 반드시 정리되도록 구조를 바꿨다.
            # (예전에는 정상 종료 경로에서만 driver.close()를 불렀기 때문에, 메일
            # 처리 루프에서 예외가 나면 탭과 msedgedriver.exe가 그대로 남았다.)
            driver = get_oracle_driver_isolated()
            driver.get(ORACLE_HOME_URL)
            time.sleep(4)
            # 2026-08-06(2차): 복구 순서를 recover_oracle_login()의 사다리로 통일
            # (SSO -> URL 재진입 -> Edge 재시작 -> 실패). 예전에는 SSO 실패 시 곧바로
            # Edge를 강제 재시작했는데, 실측 결과 재시작은 콜드 부팅이라 로그인 페이지
            # 렌더를 더 느리게 만들어 오히려 실패 확률을 높였다(원래 실패 원인이
            # "SSO 버튼이 1.0~8.4초 늦게 뜬다"였음). 알림/스킵 처리는 예전과 동일.
            ok, driver = recover_oracle_login(driver, log)
        except Exception as e:
            log(f"[에러] Edge/오라클 시작 실패 -> 이번 회차 스킵: {exc_detail(e)}")
            return
        if not ok:
            log("[경고] 자동 복구 실패 -> 사람이 재로그인 필요, 이번 회차 전체 스킵")
            send_alert(
                "[오라클 재로그인 필요] 쉽컨펌 자동화",
                "오라클 Fusion 세션이 끊겨서 자동 처리를 못했습니다. Edge에서 한 번 로그인해주세요.\n"
                "대상 메일: " + "; ".join(m["subject"] for m in new_mails)
            )
            return  # 드라이버 정리는 아래 finally가 담당(2026-08-06)

        new_mails.reverse()  # 오래된 것부터
        for m in new_mails:
            mail_all_ok = True
            for order_no in m["order_nos"]:
                try:
                    results = process_order(driver, order_no)
                    # 2026-08-07: shipment가 0건이면 예전엔 "할 일이 없다 = 성공"으로
                    # 보고 그대로 완료 답장 초안까지 만들었다. 그런데 0건은 실제로
                    # 없는 경우보다 **검색 결과가 아직 안 그려진 경우**가 많다 -
                    # 같은 날 주문 00236830을 수동 재실행했을 때 1차 검색은 0건,
                    # 60초 뒤 재검색은 3건 전부(9934291/9934292/9962548)가 나왔다.
                    # 실제로 00211195, 00237571이 이 경로로 "0건 -> 완료 답장"까지
                    # 갔고 쉽컨펌은 안 된 상태였다(사용자가 수동 처리).
                    # -> 0건은 성공이 아니라 '확인 필요'로 처리한다. 상태에 기록하지
                    #    않으므로 다음 실행 때 자동으로 다시 시도된다.
                    if not results:
                        mail_all_ok = False
                        log(f"[경고] 주문 {order_no}: shipment 0건 - 완료 처리하지 않고 "
                            "다음 실행 때 재시도합니다")
                        send_alert(
                            f"[쉽컨펌 확인 필요] {order_no} - shipment 0건",
                            f"메일 제목: {m['subject']}\n"
                            "Manage Shipment Lines 검색 결과가 0건으로 읽혔습니다.\n"
                            "실제로 shipment가 없을 수도 있지만, 검색 결과가 늦게 그려져 "
                            "0건으로 잘못 읽히는 경우가 확인됐습니다.\n"
                            "완료 답장은 보내지 않았고, 상태에도 기록하지 않아 "
                            "다음 실행 때 자동으로 다시 시도합니다."
                        )
                        continue
                    state[order_no] = {
                        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "subject": m["subject"],
                        "results": results,
                    }
                    save_state(state)
                    failed = {sn: r["error"] for sn, r in results.items()
                              if isinstance(r, dict) and r.get("error")}
                    if failed:
                        mail_all_ok = False
                        # 2026-08-07: 일부 shipment만 실패하면 여기서 조용히 끝났다.
                        # 주문 자체는 상태에 기록돼 다음 실행 때 재시도되지 않고,
                        # 완료 답장도 안 나가서 로그를 직접 열어보기 전엔 알 수가
                        # 없었다(주문 00236830 / 9962548). 남은 건은 사람이 처리해야
                        # 하므로 알림을 보낸다.
                        send_alert(
                            f"[쉽컨펌 일부 실패] {order_no}",
                            f"메일 제목: {m['subject']}\n"
                            "아래 shipment는 자동 처리되지 않았습니다. 오라클에서 직접 Ship Confirm 해주세요.\n"
                            + "\n".join(f"  - {sn}: {err}" for sn, err in failed.items())
                            + "\n\n(주문은 처리 완료로 기록되어 다음 실행 때 자동 재시도되지 않습니다.)"
                        )
                except Exception as e:
                    mail_all_ok = False
                    log(f"[에러] 주문 {order_no} 처리 실패: {exc_detail(e)}")
                    send_alert(
                        f"[쉽컨펌 확인 필요] {order_no}",
                        f"메일 제목: {m['subject']}\n에러: {e}\n"
                        "상태에 기록하지 않아 다음 실행 때 자동 재시도됩니다."
                    )
            if mail_all_ok:
                try:
                    create_completion_reply(m["entry_id"])
                    log(f"완료 답장 발송: {m['order_nos']} ({m['subject']})")
                except Exception as e:
                    log(f"[경고] 답장 발송 실패 ({m['subject']}): {e}")

        log("===== ship_confirm_watcher 종료 =====\n")
    finally:
        # 2026-08-06: 예전에는 이 close()가 finally 밖(정상 종료 경로)에 있어서,
        # 위 메일 처리 루프에서 예외가 나면 탭과 msedgedriver.exe가 그대로
        # 남았다 - 어떤 경로로 끝나든 반드시 정리되도록 finally로 옮김.
        close_driver(driver)
        _release_singleton_lock(lock)


if __name__ == "__main__":
    main()
