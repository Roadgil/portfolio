# -*- coding: utf-8 -*-
"""
sco_cancel_watcher.py

매달 영업일 말일 오전 10시, Oracle BI Publisher가 매일 아침 자동으로 보내주는
"Candela Open Sales and Transfer Order Report-APAC" 메일(받은편지함 > Operation >
Transfer order report)의 최신 첨부를 읽어, 아래 조건에 맞는 라인을 뽑는다.

  - Ship From Org(U) == "KRP"
  - Line Type(U) == "SCO"
  - 30 <= Days Open <= 90 (2026-08-01 사용자 요청으로 상한 90 추가 - 90일
    초과는 별도 처리가 필요해 이 자동화 대상에서 제외)
  - So Number(U)가 "7"로 시작 (Transfer Order 번호)

각 So Number(U)(=Transfer Order 번호)마다 Oracle Fusion Inventory Management >
Manage Transfer Orders에서 검색해서, 그 TO의 Open 라인들을 아래 두 케이스로
처리한다(2026-08-01 사용자 확인).

  1) Shipped/Received/Delivered가 전부 비어있고 Requested만 있는 라인
     -> 그 라인을 선택 -> "Cancel Line" 클릭
  2) Shipped/Received/Delivered에 이미 (서로 같은) 숫자가 들어있는 라인
     -> Requested 입력칸을 그 숫자로 고침 (Cancel Line은 누르지 않음)

라인별 처리 후 상단 Submit을 눌러 그 TO 전체를 제출한다.

Shipped/Received/Delivered가 서로 다른 값이면(부분 입고 등 애매한 상태) 자동
처리하지 않고 확인 필요 알림만 보낸다.

2026-08-01 실제 오라클 화면 실측 확인:
  - Manage Transfer Orders 검색화면의 "Transfer Order" 입력창은 Advanced Search
    구조라 aria-label이 " Transfer Order"(앞에 공백 포함)로 내려온다 -> strip
    비교 필요.
  - Open 라인만 Requested가 실제 <input>으로 렌더링되고, 그 input의 id에
    'propReqQty'가 포함됨(예:
    ...:AP1:AT2:_ATp:ATt2:0:propReqQty::content) - 이 id 패턴으로 Open 라인의
    Requested 입력칸을 특정한다. Closed 라인은 Requested도 일반 텍스트라 input이
    없음 - 즉 propReqQty input이 없는 라인은 이미 끝난 라인이므로 건드리지 않는다.
  - 그 input의 가장 가까운 조상 <tr>(frozen 컬럼이 아닌 스크롤 영역 tr)의 셀
    순서: [0]Line Status, [1]Fulfillment Status, [2]Source Organization,
    [3]Source Subinventory, [4]Destination Location, [5]Requested Delivery Date,
    [6]UOM Name, [7]Requested(input), [8]Shipped, [9]Received, [10]Delivered,
    [11]Requisition, [12]Comment(input).
  - "Cancel Line"은 라인별 버튼이 아니라 그리드 상단 툴바 버튼 - 반드시 먼저
    그 라인 행을 클릭해서 선택한 다음 눌러야 한다.
  - 오라클 로그인/세션 관리, Edge 디버그 세션은 icbl_ci_watcher.py 것을 그대로
    재사용(다른 자동화들과 동일 패턴).

주의(2026-08-01 빌드 중 실측): get_oracle_driver_isolated()는 호출할 때마다
새 탭을 열고 ORACLE_HOME_URL로 이동한다 - 한 프로세스 실행 안에서 여러 번
부르면 그때마다 처음부터 다시 네비게이션해야 한다. 또한 디버그 Edge에 탭이
너무 많이 쌓이면(수동 테스트 중 지저분하게 열어둔 탭들) 새 webdriver.Edge()
연결 자체가 응답 없이 멈추는 현상이 실측됨 - 이 자동화는 매번 쓰던 탭을
반드시 driver.close()로 정리하고, 절대 다른 자동화가 쓰는 탭까지 통째로
정리하려 하지 않는다(잘못 건드리면 Edge 전체가 닫혀서 공유 디버그 세션
자체가 죽는다 - 실제로 이번 빌드 중 한 번 재현됨, ensure_edge_running()으로
복구).
"""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timedelta

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
    ORACLE_HOME_URL,
    _click_text,
    tasks_panel_open,
    _wait_find,
    _force_restart_edge,
    acquire_oracle_lock,
    release_oracle_lock,
    set_edge_owner,
)

# 2026-09-18: 이 프로세스는 자기 전용 Edge(포트/프로필)를 쓴다.
set_edge_owner("sco_cancel_watcher")

# ==============================================================
# 경로/설정
# ==============================================================
ROOT = os.path.dirname(__file__)
LOG_PATH = os.path.join(ROOT, "sco_cancel_watcher.log")
STATE_PATH = os.path.join(ROOT, "_processed_lines.json")
LOCK_FILE_PATH = os.path.join(ROOT, "_watcher.lock")
REPORT_ARCHIVE_DIR = os.path.join(ROOT, "리포트_보관")

OUTLOOK_PARENT_SUBFOLDER = "Operation"
OUTLOOK_SUBFOLDER = "Transfer order report"

SHIP_FROM_ORG = "KRP"
LINE_TYPE = "SCO"
DAYS_OPEN_MIN = 30
# 2026-08-01 사용자 요청: Days Open이 90일을 넘는 건은 이 자동화 대상에서
# 제외(별도 처리가 필요해서) - 30~90일 구간만 대상으로 좁힘.
DAYS_OPEN_MAX = 90

ALERT_MAIL_TO = "yoongil.chae@candelamedical.com"


# ==============================================================
# 유틸 (다른 watcher들과 동일 패턴)
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
    "아직 아무 TO도 취소 제출 안 했다"는 뜻이라 이미 제출한 건을 다시 제출하게
    된다 - 파일이 있는데 깨졌으면 회차를 중단시킨다(파일 자체가 없는 첫 실행은
    예전처럼 {}로 정상 진행)."""
    return read_json_state(STATE_PATH, "SCO 취소 처리 이력", strict=True)


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
# 평문(.Body)으로 만들던 메일은 Outlook의 평문 기본 글꼴을 따라가므로,
# HTML 본문으로 만들어 글꼴을 명시한다.
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




def _select_task_category(driver, category: str) -> bool:
    """Inventory Management의 Tasks 패널에서 카테고리 드롭다운을 category로 바꾼다.

    2026-08-06(2차) 추가. 이 패널의 작업 목록은 카테고리별로 갈리는데
    (Inventory / Counts / Shipments / Picks / Receipts), 이 자동화가 쓰는
    'Manage Transfer Orders'는 **Inventory** 카테고리에만 있다. 패널은 마지막에
    고른 카테고리를 기억하고, 같은 Edge 프로필을 공유하는 다른 자동화
    (pick_release/ship_confirm)가 매번 'Shipments'를 골라놓기 때문에 이쪽이
    그 상태를 물려받아 링크를 영영 못 찾았다 - 호출부 주석 참고.

    반환값: **실제로 카테고리를 바꿨으면 True**, 이미 그 값이거나 드롭다운이
    아직 없으면 False. 호출부는 True일 때만 다시 그려질 시간을 준다(그래야
    무한히 다시 선택하지 않는다)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select
    try:
        els = [e for e in driver.find_elements(
            By.XPATH, "//select[option[normalize-space(text())='Inventory']]")
            if e.is_displayed()]
        if not els:
            return False  # 패널이 아직 안 열림 - 다음 폴링에서 다시 본다
        sel = Select(els[0])
        current = (sel.first_selected_option.text or "").strip()
        if current == category:
            return False  # 이미 원하는 카테고리
        sel.select_by_visible_text(category)
        log(f"  Tasks 패널 카테고리 변경: {current!r} -> {category!r}")
        return True
    except Exception as e:
        log(f"  [경고] Tasks 패널 카테고리 선택 실패(무시하고 계속): "
            f"{type(e).__name__}: {e}")
        return False


def _click_by_textcontent(driver, text: str, tags: str = "button, a, span", timeout: float = 8.0) -> bool:
    """ship_confirm_watcher.py와 동일 - accesskey 밑줄로 텍스트가 여러 자식
    노드로 쪼개진 Oracle ADF 버튼을 JS textContent 완전일치로 찾아 클릭."""
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


def is_last_business_day_of_month(d: datetime) -> bool:
    """d가 그 달의 마지막 영업일(평일)인지 확인. 한국 공휴일은 고려하지 않음
    (주말만 제외) - 필요하면 나중에 공휴일 리스트를 추가할 것."""
    next_day = d + timedelta(days=1)
    if next_day.month == d.month:
        return False  # 아직 그 달이 안 끝남
    # 이 달의 마지막 날짜부터 거꾸로 평일(월~금)을 찾는다
    last_day = d.replace(day=1) + timedelta(days=32)
    last_day = last_day.replace(day=1) - timedelta(days=1)
    while last_day.weekday() >= 5:  # 5=토, 6=일
        last_day -= timedelta(days=1)
    return d.date() == last_day.date()


# ==============================================================
# 1) Outlook에서 최신 리포트 첨부 가져오기
# ==============================================================
def fetch_latest_report() -> str:
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    root = None
    for acc in outlook.Folders:
        try:
            inbox = acc.Folders["받은 편지함"]
        except Exception:
            continue
        try:
            op = inbox.Folders[OUTLOOK_PARENT_SUBFOLDER]
            target = op.Folders[OUTLOOK_SUBFOLDER]
            root = target
            break
        except Exception:
            continue

    if root is None:
        raise RuntimeError(
            f"Outlook 폴더를 못 찾음: 받은 편지함 > {OUTLOOK_PARENT_SUBFOLDER} > {OUTLOOK_SUBFOLDER}"
        )

    items = root.Items
    items.Sort("[ReceivedTime]", True)
    latest = items[0]

    if latest.Attachments.Count == 0:
        raise RuntimeError(f"최신 리포트 메일에 첨부가 없음: {latest.Subject} ({latest.ReceivedTime})")

    os.makedirs(REPORT_ARCHIVE_DIR, exist_ok=True)
    att = latest.Attachments(1)
    stamp = datetime.now().strftime("%Y%m%d")
    save_path = os.path.join(REPORT_ARCHIVE_DIR, f"TransferOrderReport_{stamp}.xls")
    att.SaveAsFile(save_path)
    log(f"리포트 저장: {save_path} (메일 수신: {latest.ReceivedTime})")
    return save_path


# ==============================================================
# 2) 리포트 파싱 -> 대상 TO별 라인 목록
# ==============================================================
def parse_candidates(xls_path: str) -> dict:
    import pandas as pd

    df = pd.read_excel(xls_path, sheet_name=0, header=13)
    cols = df.columns

    def find_col(name):
        for c in cols:
            if isinstance(c, str) and c.strip() == name:
                return c
        raise RuntimeError(f"리포트에서 컬럼을 못 찾음: {name}")

    c_ship_from = find_col("Ship From Org(U)")
    c_line_type = find_col("Line Type(U)")
    c_so_num = find_col("So Number(U)")
    c_days_open = find_col("Days Open")
    c_item = find_col("Item(U)")

    df[c_so_num] = df[c_so_num].astype(str)
    days_open_num = pd.to_numeric(df[c_days_open], errors="coerce")
    sub = df[
        (df[c_ship_from] == SHIP_FROM_ORG)
        & (df[c_line_type] == LINE_TYPE)
        & (days_open_num >= DAYS_OPEN_MIN)
        & (days_open_num <= DAYS_OPEN_MAX)
        & (df[c_so_num].str.startswith("7"))
    ]

    result = {}
    for _, row in sub.iterrows():
        to_num = row[c_so_num]
        result.setdefault(to_num, []).append({
            "item": row[c_item],
            "days_open": row[c_days_open],
        })
    return result


# ==============================================================
# 3) 오라클 Manage Transfer Orders 자동 처리
# ==============================================================
def _click_containing_text_ancestor_link(driver, text: str) -> bool:
    """텍스트가 라벨(아이콘 아래 두 줄로 쪼개진 경우 포함)로만 들어있는 타일도
    누를 수 있도록, 정확히 일치하는 텍스트 노드를 가진 요소를 찾은 뒤 가장
    가까운 클릭 가능한 조상(a/button/[onclick]/role=button)까지 올라가서
    클릭한다. 못 찾으면 그 요소 자체를 클릭."""
    return driver.execute_script(r"""
        var text = arguments[0];
        var walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        var node;
        while ((node = walker.nextNode())) {
            if (node.nodeValue.trim() === text) {
                var el = node.parentElement;
                var target = el;
                var cur = el;
                for (var i=0; i<6 && cur; i++) {
                    if (cur.tagName === 'A' || cur.tagName === 'BUTTON' ||
                        cur.hasAttribute('onclick') || cur.getAttribute('role') === 'button' ||
                        cur.getAttribute('role') === 'link') {
                        target = cur;
                        break;
                    }
                    cur = cur.parentElement;
                }
                var rect = target.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    target.scrollIntoView(true);
                    target.click();
                    return true;
                }
            }
        }
        return false;
        """, text)


def _click_link_containing(driver, text: str) -> bool:
    """<a> 태그 중 textContent에 text가 포함된 것을 찾아 클릭(부분일치).
    2026-08-01 실측: 홈 화면의 'Inventory Management' 앱 타일은 실제 텍스트가
    'Inventory Management (Classic)' 한 덩어리라 정확일치로는 못 찾음 -
    'Manage Transfer Orders' 링크 클릭과 동일하게 <a> 한정 부분일치로 찾는다."""
    return driver.execute_script(r"""
        var text = arguments[0];
        var links = document.querySelectorAll("a");
        for (var i=0;i<links.length;i++){
            var t = (links[i].textContent || "").replace(/\s+/g, " ").trim();
            if (t.indexOf(text) !== -1) {
                var rect = links[i].getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    links[i].scrollIntoView(true);
                    links[i].click();
                    return true;
                }
            }
        }
        return false;
        """, text)


def navigate_to_manage_transfer_orders(driver):
    """2026-08-01 실측: 홈 화면의 'Inventory Management' 앱 타일 실제 텍스트는
    'Inventory Management (Classic)' 한 덩어리(줄바꿈은 CSS일 뿐 별도 텍스트
    노드가 아님) - 정확일치로 찾으면 못 찾아서 home 화면에 그대로 머물러
    있었음(Tasks 아이콘 못 찾음 오류의 진짜 원인). <a> 한정 부분일치로 수정.
    클릭 후 실제로 화면이 바뀌었는지 확인하고, 안 바뀌면 재시도한다."""
    from selenium.webdriver.common.by import By

    last_err = None
    for attempt in range(5):
        try:
            if attempt > 0:
                # 동시에 다른 자동화(icbl_ci_watcher 등)가 같은 오라클 세션을
                # 붐비게 만들고 있을 수 있어(2026-08-01 실측: 부하가 몰리면
                # Tasks 패널이 계속 안 열림), 바로 재시도하지 않고 부하가
                # 가라앉을 시간을 줌.
                time.sleep(20)
            driver.get(ORACLE_HOME_URL)
            time.sleep(6)

            _click_containing_text_ancestor_link(driver, "Supply Chain Execution")
            time.sleep(3)

            # 2026-08-01 실측: 렌더링 중에 재클릭하면(느리게 뜨는 중인데 또
            # 누르면) 오히려 상태가 꼬여서 다음 단계(Tasks 패널)까지 영향을
            # 주는 것으로 의심됨 - Tasks 패널과 동일하게 재클릭 없이 길게
            # 폴링하고, 정말 안 될 때만 딱 한 번 재클릭.
            im_ok = False
            for _ in range(2):
                _click_link_containing(driver, "Inventory Management (Classic)")
                deadline = time.time() + 20
                while time.time() < deadline:
                    time.sleep(1)
                    if "Inventory Organization" in driver.find_element(By.TAG_NAME, "body").text:
                        im_ok = True
                        break
                if im_ok:
                    break
            if not im_ok:
                raise RuntimeError("Inventory Management 화면으로 못 넘어감")

            # 2026-08-01 실측: "Inventory Organization" 텍스트가 보이는 시점과
            # 화면의 JS 이벤트 핸들러(Tasks 아이콘 클릭 등)가 실제로 연결되는
            # 시점 사이에 지연이 있는 것으로 의심됨 - 텍스트만 보고 바로
            # Tasks 아이콘을 클릭하면 클릭이 씹히는 경우가 반복 확인됨.
            # debug_fresh.py(고정 8초 대기)는 항상 성공했던 것과 대조적 -
            # 같은 여유를 준다.
            time.sleep(8)

            # 2026-08-01 실측 버그: 패널이 렌더링 중일 때 재클릭하면 열리다 만 패널이
            # 다시 닫혀버려(토글) 오히려 실패 확률이 올라감 - 한 번 클릭한 뒤에는
            # 충분히 길게 재클릭 없이 기다린다.
            # 2026-08-01 추가 실측: 1초 간격으로 execute_script를 계속 돌리며
            # 폴링하면(레이아웃을 자주 강제로 다시 계산시켜서) 패널이 열리는
            # CSS 애니메이션/렌더링을 방해해 영원히 안 열리는 것으로 의심됨
            # (반면 debug_fresh.py처럼 sleep만 하고 뜸하게 확인하면 항상 성공함).
            # 그래서 폴링 간격을 넉넉히(4초) 벌린다.
            ok = False
            for tasks_attempt in range(2):
                tasks_icon = _wait_find(driver, By.XPATH, "//img[@title='Tasks']", timeout=25)
                # 2026-08-06(2차) 실측으로 확인한 두 가지를 여기서 고친다.
                #  (1) **이미 열려 있으면 누르지 않는다.** 이 아이콘은 토글이라
                #      열린 패널을 다시 누르면 닫힌다. 오라클은 패널 열림 상태를
                #      페이지를 다시 열어도 기억하고, 같은 Edge를 공유하는 다른
                #      자동화가 열어둔 채로 남길 수 있다 - 그 상태에서 예전 코드는
                #      무조건 눌러서 스스로 닫아버렸다(이 함수 위쪽 2026-08-01
                #      주석의 '토글' 경고와 같은 현상).
                #  (2) **네이티브 클릭 대신 JS 클릭.** 백그라운드 창에서 네이티브
                #      클릭이 예외 없이 조용히 씹히는 것이 실측됨(같은 조건 비교:
                #      네이티브는 패널이 안 열렸고 JS는 열렸다). pick_release_watcher
                #      는 같은 아이콘을 이미 JS 클릭으로 누르고 있다.
                if not tasks_panel_open(driver):
                    driver.execute_script("arguments[0].click();", tasks_icon)

                deadline = time.time() + 28
                while time.time() < deadline:
                    time.sleep(4)
                    # 2026-08-06(2차) 원인 규명: 여기서 'Manage Transfer Orders'를
                    # 못 찾던 진짜 이유는 패널이 안 열려서가 아니라 **카테고리가
                    # 달라서**였다. 실측(패널 내용 덤프):
                    #   - Tasks 패널은 정상적으로 열림(보이는 링크 19개)
                    #   - 그런데 목록이 전부 Shipments 카테고리
                    #     (Manage Shipments / Manage Shipment Lines / Create Pick
                    #      Wave / Confirm Pick Slips ...)
                    #   - 카테고리 드롭다운: Inventory/Counts/Shipments/Picks/Receipts
                    #   - 'Manage Transfer Orders'는 **Inventory** 카테고리에만 있음
                    # 왜 예전엔 됐나: 이 패널은 마지막에 고른 카테고리를 기억하는데,
                    # 같은 Edge 프로필을 공유하는 pick_release_watcher와
                    # ship_confirm_watcher가 매 실행마다 'Shipments'를 선택한다 -
                    # 그 상태가 이 자동화에까지 넘어온 것(자동화 간 상태 간섭).
                    # 남이 뭘 골라놨든 상관없도록 여기서 Inventory를 명시한다.
                    if _select_task_category(driver, "Inventory"):
                        # 방금 카테고리를 바꿨으면 목록이 다시 그려질 시간을 준다
                        # (여기서 바로 찾으면 아직 예전 목록이라 헛탕).
                        #
                        # 2026-08-06(2차) 실측 메모 - 여기서 예산을 늘리지 않는
                        # 이유: 패널을 '방금 연 직후'에 카테고리를 바꾸면 이
                        # 회차에서는 목록이 끝내 갱신되지 않는 경우가 있다(ADF의
                        # 부분 렌더 바인딩이 아직 안 붙은 것으로 추정). 그래서
                        # 대기 예산을 28초 -> 50초로 늘려봤지만 결과는 같았고
                        # (링크는 여전히 안 나타남) 총 소요만 134초 -> 159초로
                        # 늘었다. 타이밍 문제가 아니라는 뜻이라 원복했다.
                        # 바깥 재시도가 페이지를 새로 열면(driver.get) 그 회차에서
                        # 정상적으로 잡힌다 - 실측 3/3 모두 그렇게 해소됐다.
                        continue
                    ok = driver.execute_script("""
                        var links = document.querySelectorAll("a");
                        for (var i=0;i<links.length;i++){
                            var t = (links[i].textContent||"").trim();
                            if (t === "Manage Transfer Orders"){
                                links[i].scrollIntoView(true);
                                links[i].click();
                                return true;
                            }
                        }
                        return false;
                        """)
                    if ok:
                        break
                if ok:
                    break
                log(f"[경고] Tasks 패널이 안 열림(시도 {tasks_attempt + 1}/2) - 재클릭")
            if not ok:
                try:
                    driver.save_screenshot(os.path.join(ROOT, f"_debug_fail_attempt{attempt+1}.png"))
                except Exception:
                    pass
                raise RuntimeError("'Manage Transfer Orders' 링크를 못 찾음")
            time.sleep(6)
            return
        except Exception as e:
            last_err = e
            log(f"[경고] Manage Transfer Orders 네비게이션 실패(시도 {attempt + 1}/5): {e}")
    raise last_err


def search_transfer_order(driver, to_number: str) -> bool:
    """검색 후 라인이 있으면 True, 진짜 "No data to display"(검색은 됐고 결과가
    없음)면 False. 2026-08-01 실측: 화면 전환 직후라 입력이 씹혀서(포커스는
    갔지만 값이 실제로 안 들어간 채 빈 칸으로 남는 경우) Search를 눌러도
    "No search conducted"로 끝나버리는 사례 발견 - 입력 후 실제 값을 읽어
    확인하고, 비어있으면 재시도한다.
    2026-08-31 실측: 3회 재시도 후에도 "No search conducted"에 머물러 있으면
    (검색 버튼 클릭 자체가 끝내 반영 안 된 것) False가 아니라 RuntimeError를
    던진다 - "진짜 없음"과 "판정 불가"를 같은 False로 뭉개면 호출부가 둘 다
    "이미 Closed"로 오판해 실제로 Open 라인이 남은 TO를 조용히 스킵한다
    (그날 오라클 못 찾음 7건 중 6건이 이 케이스로 확인됨). 예외를 던지면
    run_with_oracle_retry의 바깥 재시도(재네비게이션 포함)를 타고, 그래도
    안 풀리면 summary["error"]로 남아 알림 메일에 드러난다."""
    from selenium.webdriver.common.by import By

    def _find_to_input():
        els = driver.find_elements(By.XPATH, "//input[@type='text']")
        matches = [e for e in els if (e.get_attribute("aria-label") or "").strip() == "Transfer Order" and e.is_displayed()]
        return matches[0] if matches else None

    # 화면 전환 직후 그리드/검색폼이 아직 안정화 안 된 상태에서 입력하면 씹히는
    # 경우가 있어(2026-08-01 실측), 검색창이 실제로 나타날 때까지 먼저 대기.
    deadline0 = time.time() + 15
    while time.time() < deadline0 and _find_to_input() is None:
        time.sleep(1)

    typed_ok = False
    for _ in range(6):
        to_input = _find_to_input()
        if to_input is None:
            time.sleep(1)
            continue
        to_input.click()
        to_input.clear()
        to_input.send_keys(to_number)
        time.sleep(0.8)
        to_input2 = _find_to_input()
        if to_input2 is not None and to_input2.get_attribute("value") == to_number:
            typed_ok = True
            break
        # send_keys가 씹혔으면 JS로 값 강제 설정 + input/change 이벤트 발생
        if to_input2 is not None:
            driver.execute_script("""
                var el = arguments[0], val = arguments[1];
                var nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                nativeSetter.call(el, val);
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                """, to_input2, to_number)
            time.sleep(0.8)
            to_input3 = _find_to_input()
            if to_input3 is not None and to_input3.get_attribute("value") == to_number:
                typed_ok = True
                break
        time.sleep(1)
    if not typed_ok:
        raise RuntimeError(f"Transfer Order 검색창에 값 입력 실패: {to_number}")

    def _click_search():
        search_btns = [b for b in driver.find_elements(By.XPATH, "//*[normalize-space(text())='Search']") if b.is_displayed()]
        if not search_btns:
            return False
        search_btns[0].click()
        return True

    def _search_already_resolved():
        body_text = driver.find_element(By.TAG_NAME, "body").text
        return f"Edit Transfer Order: {to_number}" in body_text or "No data to display" in body_text

    # 2026-08-01 실측: Search 버튼 클릭이 먹지 않는("No search conducted" 그대로
    # 남는) 경우가 반복 확인됨 - 입력창에서 Enter를 누르는 방식이 Oracle ADF
    # 검색 폼에서 더 안정적으로 통하는 경우가 많아 우선 시도한다. Enter만으로
    # 이미 결과 화면으로 넘어갔으면(Search 버튼 자체가 없어짐) 그대로 두고,
    # 아직 안 넘어갔을 때만 Search 버튼 클릭으로 보완한다.
    to_input_final = _find_to_input()
    if to_input_final is not None:
        from selenium.webdriver.common.keys import Keys
        to_input_final.send_keys(Keys.ENTER)
        time.sleep(2)
    def _try_open_from_results_list() -> bool:
        """2026-08-01 실측(TO 7643215): 검색 결과가 바로 Edit Transfer Order
        화면으로 안 넘어가고 "Search Results" 목록(같은 TO의 라인이 여러 행)으로
        나오는 경우가 있다 - 이때는 목록의 "Transfer Order" 번호 링크를 클릭해야
        Edit 화면으로 들어간다."""
        clicked = driver.execute_script("""
            var links = document.querySelectorAll("a");
            for (var i=0;i<links.length;i++){
                if ((links[i].textContent||"").trim() === arguments[0]) {
                    var rect = links[i].getBoundingClientRect();
                    if (rect.width > 0 && rect.height > 0) {
                        links[i].scrollIntoView(true);
                        links[i].click();
                        return true;
                    }
                }
            }
            return false;
            """, to_number)
        return bool(clicked)

    if not _search_already_resolved():
        _click_search()
    tried_list_click = False
    for search_attempt in range(3):
        deadline = time.time() + 15
        while time.time() < deadline:
            time.sleep(2)
            body_text = driver.find_element(By.TAG_NAME, "body").text
            if f"Edit Transfer Order: {to_number}" in body_text:
                return True
            if "No data to display" in body_text:
                return False
            if not tried_list_click and "Search Results" in body_text and to_number in body_text:
                tried_list_click = True
                if _try_open_from_results_list():
                    time.sleep(3)
        # 15초 지나도 "No search conducted"에 그대로 머물러 있으면 재클릭
        body_text = driver.find_element(By.TAG_NAME, "body").text
        if "No search conducted" in body_text and search_attempt < 2:
            log(f"[경고] Search 클릭이 안 먹은 것으로 보임(시도 {search_attempt + 1}/3) - 재클릭")
            _click_search()
            continue
        if "No data to display" in body_text:
            return False
        if "No search conducted" in body_text:
            # 2026-08-31 실측: 검색 버튼 클릭 자체가 끝내 반영 안 된 상태
            # ("No search conducted")를 "No data to display"(진짜 결과 없음)와
            # 똑같이 False로 처리하면 "오라클에서 못 찾음"에 진짜 닫힌 건과
            # 판정 불가 건이 뒤섞여, 실제로는 Open 라인이 남아있는 TO가 조용히
            # 스킵된다(그날 7건 중 6건이 이 케이스로 확인됨). 판정 불가는
            # 예외로 올려서 run_with_oracle_retry의 바깥 재시도(재네비게이션
            # 포함)를 타게 하고, 그래도 안 되면 summary["error"]로 남아 알림
            # 메일에 드러나게 한다 - "못 찾음"이라 부르지 않는다.
            raise RuntimeError(
                f"TO {to_number}: Search 클릭이 반영되지 않아 검색 자체가 안 됨"
                f"(3회 재시도 후에도 'No search conducted') - 진짜 없는지 판정 불가"
            )
    raise RuntimeError(f"TO {to_number}: 검색 결과 화면 상태를 판정할 수 없음(예상 밖 상태) - 수동 확인 필요")


def read_open_lines(driver) -> list:
    """propReqQty input이 있는(=Open) 라인들을 읽어온다.
    2026-08-01 실측 버그 수정: Requested Delivery Date가 비어있으면(날짜피커가
    인라인으로 숨은 캘린더 팝업 DOM을 같이 들고 있어) 그 앞쪽에 빈 td가 여러 개
    끼어들어 행마다 전체 셀 개수가 달라진다(고정 인덱스로 읽으면 다른 컬럼을
    잘못 읽음 - 실제로 TO 7700712에서 Received를 읽으려다 날짜피커의
    "Select Date and Time" 문구를 잘못 읽은 사례 있음). 고정 인덱스 대신,
    Requested <input>이 들어있는 td를 찾아 그 바로 다음 3개 td를
    Shipped/Received/Delivered로 읽는 상대 오프셋 방식을 쓴다(TO 7639989와
    7700712 둘 다 실측 검증됨) - Line Status는 항상 그 행의 첫 번째 td.
    반환: [{"requested_input_id":..., "line_status":..., "shipped":..., "received":...,
            "delivered":..., "requested": "3"}, ...]"""
    dump = driver.execute_script(r"""
        var inputs = document.querySelectorAll("input[id*='propReqQty']");
        var out = [];
        for (var i=0;i<inputs.length;i++){
            var inp = inputs[i];
            var tr = inp.closest('tr');
            if (!tr) continue;
            var reqTd = inp.closest('td');
            var tds = Array.prototype.slice.call(tr.children);
            var reqIdx = tds.indexOf(reqTd);
            var lineStatus = tds.length > 0 ? tds[0].innerText.replace(/\n/g,' ').trim() : '';
            var shipped = reqIdx >= 0 && tds[reqIdx+1] ? tds[reqIdx+1].innerText.replace(/\n/g,' ').trim() : null;
            var received = reqIdx >= 0 && tds[reqIdx+2] ? tds[reqIdx+2].innerText.replace(/\n/g,' ').trim() : null;
            var delivered = reqIdx >= 0 && tds[reqIdx+3] ? tds[reqIdx+3].innerText.replace(/\n/g,' ').trim() : null;
            out.push({id: inp.id, value: inp.value, reqIdx: reqIdx, totalTds: tds.length,
                      lineStatus: lineStatus, shipped: shipped, received: received, delivered: delivered});
        }
        return JSON.stringify(out);
        """)
    import json
    raw = json.loads(dump)
    results = []
    for r in raw:
        if r["reqIdx"] < 0 or r["shipped"] is None or r["received"] is None or r["delivered"] is None:
            log(f"[경고] Requested 입력칸 기준 행 구조를 못 읽음 - 건너뜀: {r}")
            continue
        results.append({
            "requested_input_id": r["id"],
            "line_status": r["lineStatus"],
            "requested": r["value"],
            "shipped": r["shipped"],
            "received": r["received"],
            "delivered": r["delivered"],
        })
    return results


def _select_row_by_input_id(driver, input_id: str):
    """Cancel Line 툴바 버튼은 선택된 행에 적용되므로, 해당 input의 tr을 클릭해서
    행을 선택 상태로 만든다."""
    from selenium.webdriver.common.by import By
    inp = driver.find_element(By.ID, input_id)
    driver.execute_script("""
        var inp = arguments[0];
        var tr = inp.closest('tr');
        if (tr) { tr.click(); }
        """, inp)
    time.sleep(1)


def cancel_line(driver, input_id: str) -> bool:
    """2026-08-01 실측: "Cancel Line" 클릭 시 반드시
    'The line is selected for cancellation and a request for cancellation will
    be sent upon submission. Do you want to continue?' 경고 다이얼로그(Yes/No)가
    뜬다 - Yes를 눌러야 실제로 취소 대상으로 표시된다(이후 Submit에서 최종
    반영). 이 처리를 빼먹으면 Cancel Line을 눌러도 화면상 아무 변화 없이
    조용히 무시된 것처럼 보인다(실측 버그: TO 7700712에서 재현/확인)."""
    _select_row_by_input_id(driver, input_id)
    if not _click_by_textcontent(driver, "Cancel Line", timeout=6):
        return False
    time.sleep(1.5)
    if not _click_by_textcontent(driver, "Yes", tags="button, a", timeout=6):
        raise RuntimeError("Cancel Line 확인 다이얼로그의 'Yes' 버튼을 못 찾음")
    time.sleep(1)
    return True


def set_requested_quantity(driver, input_id: str, value: str):
    from selenium.webdriver.common.by import By
    _select_row_by_input_id(driver, input_id)
    inp = driver.find_element(By.ID, input_id)
    inp.click()
    inp.send_keys([])  # focus 유지
    driver.execute_script("arguments[0].select();", inp)
    inp.send_keys(value)
    time.sleep(0.3)
    # 탭아웃해서 값 반영
    from selenium.webdriver.common.keys import Keys
    inp.send_keys(Keys.TAB)
    time.sleep(1)


def submit_transfer_order(driver) -> str:
    """Submit 클릭 후 결과를 읽어 문자열로 반환(성공/오류 판단은 호출부에서)."""
    if not _click_by_textcontent(driver, "Submit", timeout=6):
        raise RuntimeError("Submit 버튼을 못 찾음")
    time.sleep(4)
    from selenium.webdriver.common.by import By
    # 확인/오류 다이얼로그가 있으면 OK로 닫는다(있을 때만).
    _click_by_textcontent(driver, "OK", tags="button, a", timeout=3)
    time.sleep(2)
    return driver.find_element(By.TAG_NAME, "body").text


# ==============================================================
# 오라클 화면 조작 공통 재시도 (2026-08-05 추가)
# ==============================================================
# 2026-08-05 사용자 요청으로 오라클을 쓰는 자동화 5종에 동일하게 넣은 헬퍼.
# 배경: pick_release_watcher 실측(2026-08-05 18:00 회차)에서 SSO 재로그인 직후
# "no such element: //img[@title='Tasks']"(화면 진입 실패)가 연달아 났는데,
# 자체 재시도 레이어가 있던 경로는 살아남고 없던 경로는 그대로 실패했다 -
# 같은 실행 안에서 짧게 쉬었다 다시 시도하게 한다.
# 2026-08-05 사용자 확인: 오라클 트랜잭션은 애초에 한 번밖에 안 먹는다(이미
# 처리된 건은 검색/재처리가 안 됨). Cancel Line/Submit도 재시도가 중복 제출을
# 만들 수 없고, 재시도 시 TO를 다시 검색하면 이미 취소된 라인은 Open이 아니라
# 안 잡히므로 자연스럽게 already_closed로 정리된다 - 그래서 TO 처리 전체에
# 재시도를 붙였다.
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


def process_transfer_order(driver, to_number: str, expected_items: list) -> dict:
    # 검색/라인 읽기 단계의 일시적 오류는 여기서 먼저 흡수한다(목록 화면으로
    # 되돌아가 재검색). 그 뒤 Cancel Line/수량 수정/Submit에서 터지는 경우는
    # 호출부(main)가 TO 처리 전체를 재시도하며, 그때도 TO를 다시 검색하므로
    # 이미 처리된 라인은 Open이 아니라 중복 제출이 되지 않는다(2026-08-05).
    def _search_and_read():
        found = search_transfer_order(driver, to_number)
        if not found:
            return False, []
        return True, read_open_lines(driver)

    ok, lines = run_with_oracle_retry(
        f"TO {to_number} 검색/라인조회",
        _search_and_read,
        before_retry=lambda: navigate_to_manage_transfer_orders(driver),
    )
    if not ok:
        return {"status": "not_found"}

    if not lines:
        log(f"  TO {to_number}: Open 라인 없음(이미 전부 Closed) - 건너뜀")
        return {"status": "already_closed"}

    log(f"  TO {to_number}: Open 라인 {len(lines)}건 발견")
    actions = []
    needs_review = False
    for ln in lines:
        shipped, received, delivered = ln["shipped"], ln["received"], ln["delivered"]
        all_blank = not shipped and not received and not delivered
        all_equal_and_present = (
            shipped and received and delivered and shipped == received == delivered
        )
        if all_blank:
            success = cancel_line(driver, ln["requested_input_id"])
            actions.append({"action": "cancel_line", "requested": ln["requested"], "clicked": success})
            log(f"    Cancel Line 처리 (Requested={ln['requested']}) -> 클릭 성공: {success}")
        elif all_equal_and_present:
            set_requested_quantity(driver, ln["requested_input_id"], shipped)
            actions.append({"action": "set_requested", "from": ln["requested"], "to": shipped})
            log(f"    Requested {ln['requested']} -> {shipped} 로 수정")
        else:
            needs_review = True
            actions.append({"action": "needs_review", "line": ln})
            log(f"[경고] TO {to_number}: Shipped/Received/Delivered가 서로 다르거나 애매함"
                f" (shipped={shipped}, received={received}, delivered={delivered}) - 자동 처리 건너뜀")

    if needs_review:
        return {"status": "needs_review", "actions": actions}

    result_text = submit_transfer_order(driver)
    return {"status": "submitted", "actions": actions, "result_text_snippet": result_text[:500]}


# ==============================================================
# main
# ==============================================================
def main(force: bool = False):
    lock = _acquire_singleton_lock()
    if lock is None:
        log("이미 다른 인스턴스가 실행 중 - 종료")
        return
    # 2026-08-06: 아래 처리 도중 어떤 예외가 나도 finally에서 드라이버가 반드시
    # 정리되도록 미리 None으로 잡아둔다(예전에는 정상 종료 경로에서만 close()를
    # 불러서, TO 처리 루프에서 예외가 나면 탭과 msedgedriver.exe가 남았다).
    driver = None
    try:
        log("===== sco_cancel_watcher 시작 =====")

        if not force and not is_last_business_day_of_month(datetime.now()):
            log("오늘은 이번 달의 마지막 영업일이 아님 - 종료")
            return

        try:
            report_path = fetch_latest_report()
            candidates = parse_candidates(report_path)
        except Exception as e:
            log(f"[에러] 리포트 조회/파싱 실패: {exc_detail(e)}")
            send_alert("[SCO 취소 자동화] 리포트 조회 실패", str(e))
            return

        log(f"대상 Transfer Order {len(candidates)}건 발견")
        if not candidates:
            log("대상 없음 - 종료")
            return

        state = load_state()

        # 2026-09-18: 공유 Edge 락을 걸었다가(TO 7882258 실사고로 도입) 같은 날
        # stale 판정 구멍으로 다른 스크립트에서 실전 충돌이 났다 - 대신 이
        # 스크립트를 전용 Edge(포트/프로필)로 완전히 분리해 겹칠 일 자체를
        # 없앴다(set_edge_owner("sco_cancel_watcher") 참고). 락 제거.
        ensure_edge_running()
        driver = get_oracle_driver_isolated()
        driver.get(ORACLE_HOME_URL)
        time.sleep(4)
        # 2026-08-06(2차): 복구 순서를 recover_oracle_login()의 사다리로 통일
        # (SSO -> URL 재진입 -> Edge 재시작 -> 실패). 예전에는 SSO 실패 시 곧바로
        # Edge를 강제 재시작했는데, 실측 결과 재시작은 콜드 부팅이라 로그인 페이지
        # 렌더를 더 느리게 만들어 오히려 실패 확률을 높였다. 알림/스킵은 예전과 동일.
        ok, driver = recover_oracle_login(driver, log)
        if not ok:
            log("[경고] 자동 복구 실패 -> 사람이 재로그인 필요, 이번 회차 전체 스킵")
            send_alert(
                "[오라클 재로그인 필요] SCO 취소 자동화",
                f"오라클 Fusion 세션이 끊겨서 자동 처리를 못했습니다. Edge에서 한 번 로그인해주세요.\n"
                f"대상 TO {len(candidates)}건: {', '.join(list(candidates.keys())[:20])}"
            )
            return  # 드라이버 정리는 아래 finally가 담당(2026-08-06)

        run_with_oracle_retry(
            "Manage Transfer Orders 최초 진입",
            lambda: navigate_to_manage_transfer_orders(driver),
        )

        summary = {"submitted": [], "already_closed": [], "not_found": [], "needs_review": [], "error": []}
        for to_number, items in candidates.items():
            try:
                # TO 처리 전체를 재시도 대상으로 둔다. 재시도는 항상 TO 재검색
                # 부터 다시 하는데, 이미 취소/제출된 라인은 Open 목록에 안 잡혀서
                # 중복 제출이 되지 않고 already_closed로 정리된다(2026-08-05).
                r = run_with_oracle_retry(
                    f"TO {to_number} 처리",
                    lambda t=to_number, i=items: process_transfer_order(driver, t, i),
                    before_retry=lambda: navigate_to_manage_transfer_orders(driver),
                )
                state[to_number] = {
                    "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "result": r,
                }
                save_state(state)
                summary[r["status"]].append(to_number)
            except Exception as e:
                log(f"[에러] TO {to_number} 처리 실패: {exc_detail(e)}")
                summary["error"].append(to_number)
                state[to_number] = {
                    "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "result": {"status": "error", "error": str(e)},
                }
                save_state(state)
            # 다음 TO 검색을 위해 목록 화면으로 복귀. 여기서 한 번 삐끗했다고
            # 남은 TO를 전부 포기하면 손해가 커서 재시도를 붙였다(2026-08-05).
            try:
                run_with_oracle_retry(
                    "다음 TO 목록 화면 복귀",
                    lambda: navigate_to_manage_transfer_orders(driver),
                )
            except Exception as e:
                log(f"[에러] 다음 TO 처리를 위한 재네비게이션 실패(재시도 포함): {exc_detail(e)}"
                    f" - 남은 TO는 다음 실행으로 넘김")
                break

        # 오라클 작업은 여기서 끝 - 결과 요약/알림은 브라우저가 필요 없으므로
        # 드라이버를 먼저 놓아준다(정리 자체는 아래 finally가 다시 보장, 2026-08-06).
        close_driver(driver)
        driver = None

        body = (
            f"제출 완료: {len(summary['submitted'])}건\n{summary['submitted']}\n\n"
            f"이미 Closed(건드릴 것 없음): {len(summary['already_closed'])}건\n\n"
            f"오라클에서 못 찾음: {len(summary['not_found'])}건\n{summary['not_found']}\n\n"
            f"확인 필요(Shipped/Received/Delivered 불일치 등): {len(summary['needs_review'])}건\n{summary['needs_review']}\n\n"
            f"에러: {len(summary['error'])}건\n{summary['error']}\n"
        )
        log("결과 요약:\n" + body)
        send_alert(f"[SCO 취소 자동화] {datetime.now().strftime('%Y-%m-%d')} 처리 결과", body)

        log("===== sco_cancel_watcher 종료 =====\n")
    finally:
        # 2026-08-06: 예전에는 close()가 finally 밖에 있어서 TO 처리 루프에서
        # 예외가 나면 탭과 msedgedriver.exe가 남았다 - 어떤 경로로 끝나든
        # 반드시 정리되도록 finally로 옮김.
        close_driver(driver)
        _release_singleton_lock(lock)


if __name__ == "__main__":
    force_run = "--force" in sys.argv
    main(force=force_run)
