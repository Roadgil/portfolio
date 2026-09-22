# -*- coding: utf-8 -*-
"""FSE PO(받은편지함 > FSE PO 폴더) 신규 Parts Order 자동 처리.

Order Type = "Shipping Only" 인 건만 대상으로 한다 - "Billable Parts Order"는
기존 pick_release_watcher(Sales Order 기반)가 별도로 처리하는 영역이라 여기서
건드리지 않는다(2026-09-01 사용자가 실제로 중단시킨 뒤 확정된 규칙).

대상 건에 대해:
  1. SF Parts Order 링크에서 Oracle Order Number / Parts Order Line / Message
     For Shipper 확인
  2. 기훈님/용호님(용마로지스) TO + 원발신자 CC로 출고요청 메일 발송(품목은
     줄바꿈으로, 세미콜론 연결 금지 - 2026-09-01 사용자 지정)
  3. 오라클에서 Transfer order로 SP release(부품은 SP 1회로 충분, backorder
     있으면 FG 1회 추가만, 그 이상 재시도 안 함) - fse_po_oracle_release.py를
     pdf_updater 콘다 환경 subprocess로 호출

state 파일(fse_po_release_state.json)로 중복 처리를 막는다. 삭제·수정은 사용자
명시적 요청 때만.

사용법:
  python fse_po_release.py scan              FSE PO 폴더에서 신규 메일 스캔·처리
  python fse_po_release.py direct <PO_NO>    메일이 아직 안 왔을 때 ServiceMax에서
                                             PO 번호로 직접 검색해 처리(수동 트리거)
  python fse_po_release.py cutoff            지금 이후에 온 메일만 처리하도록 기준시각 설정
  python fse_po_release.py cutoff <YYYY-MM-DD HH:MM:SS>
"""
import json
import os
import re
import sys
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_PATH = os.path.join(SCRIPT_DIR, "fse_po_release_state.json")
ORACLE_RELEASE_SCRIPT = os.path.join(SCRIPT_DIR, "fse_po_oracle_release.py")
PART_ORDER_BACKUP_DIR = next(
    (d for d in (os.environ.get("PART_ORDER_DIR"),
                 os.path.join(os.path.dirname(SCRIPT_DIR), "part_order_backup"),
                 r"C:\mcp\import_mcp\part_order_backup") if d and os.path.isdir(d)),
    r"C:\mcp\import_mcp\part_order_backup")
sys.path.insert(0, PART_ORDER_BACKUP_DIR)
import paths                # 사용자마다 다른 경로를 이 PC 기준으로 풀어준다  # noqa: E402

PDF_UPDATER_PY = paths.PDF_UPDATER_PY

DEBUG_PORT = 9222
SF_BASE = "https://candelamedical.my.salesforce.com"
YONGMA_TO = "김기훈 <y7221063@yongmalogis.co.kr>; 용호 유 <y7225055@yongmalogis.co.kr>"

# 세일즈포스 조회/메일발송은 2건까지 동시에, 오라클 릴리즈는 한 번에 하나씩만
# (릴리즈는 singleton lock 때문에 진짜 동시실행이 안 됨 - part_order_app의
# RELEASE_LOCK과 같은 패턴, po_finish/release_one과 별개 프로세스라 락 객체는
# 공유 못하지만 이 스크립트 안에서 도는 워커끼리만 줄을 세우면 된다).
MAX_PARALLEL_FSE = 2
RELEASE_LOCK = threading.Lock()
STATE_LOCK = threading.Lock()


def _save_state_locked(state):
    with STATE_LOCK:
        save_state(state)

# 메일이 아직 안 온 건(ServiceMax 직접 검색)에서 발신자 이메일을 못 구할 때 쓰는
# 폴백 맵. 이름 토큰을 정렬해 키로 쓰므로 "Chang Sik Shin"/"Sik Shin Chang"처럼
# SF 필드 표기 순서가 달라도 동일하게 매칭된다. 2026-09-01 FSE PO 폴더 발신자
# 전수조사(최근 3000건) 기준.
_SENDER_TABLE = [
    ("Ben Lee", "benl@candelamedical.com"),
    ("Jaepil Jeong", "jaepilj@candelamedical.com"),
    ("Jong Seong Cha", "jongseongc@candelamedical.com"),
    ("Kwang Yul Lee", "kwangl@candelamedical.com"),
    ("Dasung Jung", "dasungj@candelamedical.com"),
    ("Junyeol Yang", "junyeoly@candelamedical.com"),
    ("JooHyung Han", "joohyungh@candelamedical.com"),
    ("Chang Sik Shin", "changsiks@candelamedical.com"),
    ("Jungon Park", "jungonp@candelamedical.com"),
    ("Haejoon Kim", "haejoonk@candelamedical.com"),
    ("Jaehwan han", "jaehwanh@candelamedical.com"),
    ("Chang Gyu Yu", "changgyuy@candelamedical.com"),
    ("Yohan Kim", "yohank@candelamedical.com"),
]


def _norm_name(name: str) -> str:
    return " ".join(sorted(name.lower().split()))


SENDER_MAP = {_norm_name(n): (n, e) for n, e in _SENDER_TABLE}

# 출고요청 메일 첫 줄에 "누구 파트오더인지"를 밝히기 위한 한글 표기.
# GAL에는 영문 이름과 영문 직책(Field Service Engineer 등)만 있어서 한글 직급은
# 자동으로 못 가져온다 - 2026-09-03 사용자 확인분을 그대로 적었다.
# 직급이 빈 사람은 이름 + 님까지만 쓴다(틀린 직급을 붙이는 것보다 낫다).
_SENDER_KO = {
    "Ben Lee":        ("이병무", "대리"),
    "Jaepil Jeong":   ("정재필", "과장"),
    "Jong Seong Cha": ("차종성", "차장"),
    "Kwang Yul Lee":  ("이광열", "이사"),
    "Haejoon Kim":    ("김혜준", "대리"),
    "Dasung Jung":    ("정다성", "과장"),
    "Junyeol Yang":   ("양준열", "대리"),
    "JooHyung Han":   ("한주형", "차장"),
    "Chang Sik Shin": ("신창식", "차장"),
    # 아래 4명은 퇴사(2026-09-03 사용자 확인). 새 파트오더는 안 오지만, 예전
    # 메일을 direct 모드로 다시 돌릴 때를 위해 이름은 남겨둔다.
    "Chang Gyu Yu":   ("유창규", ""),
    "Jungon Park":    ("박정온", ""),
    "Jaehwan han":    ("한재환", ""),
    "Yohan Kim":      ("김요한", ""),
}
_SENDER_KO_NORM = {_norm_name(k): v for k, v in _SENDER_KO.items()}


def sender_honorific(name: str) -> str:
    """'이병무 대리님'처럼 부를 이름을 만든다.

    표에 없으면 받은 이름 그대로 '님'만 붙인다(영문이라 어색할 뿐 틀리지는 않는다).
    직급을 모르면 이름 + 님까지만 쓴다.
    """
    raw = (name or "").strip()
    if not raw:
        return ""
    ko = _SENDER_KO_NORM.get(_norm_name(raw))
    if not ko:
        return raw if raw.endswith("님") else raw + "님"
    ko_name, rank = ko
    return f"{ko_name} {rank}님" if rank else f"{ko_name}님"


def lookup_sender_email(name: str):
    return SENDER_MAP.get(_norm_name(name))


def log(msg: str):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_state() -> dict:
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            log("[경고] state 파일 파싱 실패 - 빈 상태로 시작(파일은 덮어쓰지 않고 다음 저장 때 갱신)")
            return {}
    return {}


def save_state(state: dict):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_PATH)


# ------------------------------------------------------------- Outlook (win32com)
SETTINGS_KEY = "_settings"


def get_fse_po_folder():
    """FSE PO 알림이 쌓이는 폴더.

    2026-09-02부터 본인 받은편지함 아래 'FSE PO' 폴더로 온다. 그 전에는
    보현과장님 공유메일함(Bohyun Kim > FSE PO)이었고, 예전 메일을 봐야 할 때가
    있으니 새 폴더가 없으면 옛 위치로 넘어간다.
    """
    import win32com.client
    import local_config
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")

    try:
        mailbox = local_config.load()["outlook_mailbox"]
        inbox = ns.Folders[mailbox].Folders["받은 편지함"]
        for f in inbox.Folders:
            if f.Name == "FSE PO":
                return f
    except Exception as e:
        log(f"  받은편지함 FSE PO 폴더 확인 실패({e}) - 공유메일함으로 넘어감")

    for f in ns.Folders:                      # 예전 위치(공유메일함)
        if f.Name == "Bohyun Kim":
            return f.Folders["FSE PO"]
    raise RuntimeError(
        "FSE PO 폴더를 찾지 못함 - 받은편지함 아래 'FSE PO' 폴더나 "
        "'Bohyun Kim' 공유메일함이 있어야 합니다")


def get_only_after(state):
    """이 시각 이후에 온 메일만 처리한다(없으면 제한 없음)."""
    v = (state.get(SETTINGS_KEY) or {}).get("only_after")
    if not v:
        return None
    from datetime import datetime as _dt
    try:
        return _dt.strptime(v, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        log(f"  [경고] only_after 형식이 이상합니다: {v!r}")
        return None


def set_only_after(state, when):
    """컷오프 시각을 상태파일에 박아둔다."""
    state.setdefault(SETTINGS_KEY, {})["only_after"] = when.strftime("%Y-%m-%d %H:%M:%S")
    return state


LINK_RE = re.compile(r"Link to Parts Order:\s*\r?\n?\s*(https://\S+)")
PO_NO_RE = re.compile(r"New Parts Order#\s*(\d+)")


def scan_new_mails(max_scan=300, max_age_hours=48, only_after=None):
    """FSE PO 폴더 최신순으로 훑어 아직 처리 안 한 PO만 뽑는다.

    2026-09-01 실측: state 파일에 없는 과거 이력이 훨씬 많아서(2700+건 중
    처리 기록 30여 건뿐) max_scan만 믿으면 매번 수백 건의 옛날 메일까지
    SF에서 다시 조회하려 든다(건당 10초 이상 - 스캔 한 번에 30분+ 걸림).
    폴더가 최신순 정렬이므로, 받은 지 max_age_hours 넘은 메일을 만나는 즉시
    스캔을 끝낸다(그 뒤는 더 오래된 메일뿐이라 볼 필요 없음)."""
    from datetime import datetime, timedelta
    folder = get_fse_po_folder()
    items = folder.Items
    items.Sort("[ReceivedTime]", True)
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    if only_after is not None and only_after > cutoff:
        cutoff = only_after            # 지정 시각 이전 메일은 아예 안 본다
        log(f"  {cutoff:%Y-%m-%d %H:%M} 이후에 온 메일만 처리합니다")

    found = []
    count = 0
    for item in items:
        count += 1
        if count > max_scan:
            break
        try:
            recv = item.ReceivedTime.replace(tzinfo=None)
        except Exception:
            recv = None
        if recv is not None and recv < cutoff:
            break
        subj = str(getattr(item, "Subject", "") or "")
        m = PO_NO_RE.search(subj)
        if not m:
            continue
        po_no = m.group(1)
        body = str(getattr(item, "Body", "") or "")
        link_m = LINK_RE.search(body)
        found.append({
            "po_no": po_no,
            "subject": subj,
            "sender_name": str(getattr(item, "SenderName", "") or ""),
            "sender_email": str(getattr(item, "SenderEmailAddress", "") or ""),
            "po_link": link_m.group(1).strip() if link_m else None,
            "entry_id": item.EntryID,
        })
    return found


def known_billable_po_numbers() -> set:
    """파트오더앱(혜준대리님 건)이 만든 Parts Order 번호 집합.

    그 건들은 전부 Billable Parts Order라 FSE 플로우 대상이 아니다. 파트오더앱
    쪽에서 이미 release/완료메일까지 끝난 것도 있어서, 여기서 또 건드리면
    용마에 중복 출고요청이 나간다.
    """
    path = os.path.join(PART_ORDER_BACKUP_DIR, "batch_result.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as e:
        log(f"  [경고] 파트오더앱 기록을 못 읽음({e}) - 번호 선차단 생략")
        return set()
    return {str(c["parts_order_number"]) for c in data.get("created", [])
            if c.get("parts_order_number")}


def already_sent(po_no: str, days=14) -> bool:
    """state 파일은 이 앱이 직접 처리한 것만 기억한다 - 사용자가 수동으로 보냈거나
    다른 프로세스가 이미 처리한 PO는 state에 없을 수 있다(2026-09-01 실제로 이걸
    놓쳐서 이미 처리된 5건에 중복 메일을 보낸 사고 발생, 사용자가 회수함).
    그래서 state 확인과 별개로 **발송 직전 반드시 보낸편지함에서 같은 PO 번호가
    포함된 제목이 있었는지 확인**한다 - 있으면 절대 보내지 않는다."""
    import win32com.client
    from datetime import timedelta, datetime
    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    sent = ns.GetDefaultFolder(5)
    items = sent.Items
    items.Sort("[SentOn]", True)
    cutoff = datetime.now() - timedelta(days=days)
    for it in items:
        try:
            if it.Class != 43:
                continue
            son = it.SentOn.replace(tzinfo=None)
        except Exception:
            continue
        if son < cutoff:
            break
        subj = str(getattr(it, "Subject", "") or "")
        if po_no in subj:
            return True
    return False


def send_release_mail(subject, oracle_no, lines, msg_shipper, cc_name, cc_email, entry_id=None):
    """용마 앞 출고요청 메일 발송.

    2026-09-03부터 새 메일 대신 원본 알림 메일에 **전체회신**한다(사용자 요청) -
    원본 발신자/수신자가 스레드에 그대로 남고, 기훈님/용호님(YONGMA_TO)을 CC에
    추가한다. entry_id가 없으면(direct 모드처럼 원본 알림 메일이 없는 경우) 예전
    방식대로 새 메일을 만든다."""
    import win32com.client
    lines_block = "\n".join(f"- {p}({c}) x{q}" for p, c, q in lines) or "(품목 정보 없음)"
    greeting = sender_honorific(cc_name)
    body = (
        (f"안녕하세요, {greeting} 파트오더입니다.\n\n" if greeting else "")
        + "기훈님 용호님\n\n"
        "출고 부탁드립니다\n\n"
        f"Oracle Order Number : {oracle_no}\n"
        f"Parts Order Line :\n{lines_block}\n\n"
        f"Message for Shipper : {msg_shipper}\n"
    )
    outlook = win32com.client.Dispatch("Outlook.Application")

    mail = None
    if entry_id:
        try:
            original = outlook.GetNamespace("MAPI").GetItemFromID(entry_id)
            mail = original.ReplyAll()
        except Exception as e:
            log(f"  [경고] 원본 메일 전체회신 준비 실패({e}) - 새 메일로 대체 발송")
            mail = None

    if mail is None:
        mail = outlook.CreateItem(0)
        mail.Subject = subject
        mail.To = YONGMA_TO
        mail.CC = f"{cc_name} <{cc_email}>" if cc_email else ""
        mail.Body = body
        mail.Send()
        log(f"  메일 발송 완료 - 새 메일 (CC={cc_email or '없음'})")
        return

    existing_cc = (mail.CC or "").strip()
    mail.CC = f"{existing_cc}; {YONGMA_TO}" if existing_cc else YONGMA_TO
    # 원본이 HTML 형식(대부분 그렇다 - 서명/링크 포함)이면 .Body(순수 텍스트)에
    # 쓰면 안 된다 - 인용문 서식이 깨지고 줄바꿈도 뭉개진다(2026-09-03 사용자
    # 지적, 실제 발송 메일에서 확인). BodyFormat으로 원본 형식을 보고 HTML이면
    # HTMLBody 위에 붙인다.
    if getattr(mail, "BodyFormat", 1) == 2:   # olFormatHTML
        html_block = body.replace("\n", "<br>\n")
        mail.HTMLBody = (
            "<div style=\"font-family:'맑은 고딕',sans-serif;font-size:10pt;\">"
            + html_block + "</div><br>" + (mail.HTMLBody or "")
        )
    else:
        mail.Body = body + "\n" + (mail.Body or "")
    # Send() 후에 mail 속성을 읽으면 "item has been moved or deleted" COM 오류로
    # 죽는다(2026-09-03 00601295 건 실제 재현 - 발송은 됐는데 이 로그 줄 때문에
    # 뒤의 release 단계가 통째로 못 돎). 반드시 Send() 전에 값을 잡아둘 것.
    to_snapshot, cc_snapshot = mail.To, mail.CC
    mail.Send()
    log(f"  메일 발송 완료 - 전체회신 (To={to_snapshot} / CC={cc_snapshot})")


# ------------------------------------------------------------- Salesforce (Playwright)
def _sf_page(browser):
    """전용 탭을 새로 열어 돌려준다.

    로그인된 Salesforce 탭을 그대로 쓰면, 파트오더앱의 탭1(생성)/탭2(승인 후)가
    같은 탭을 서로 다른 주소로 옮겨다녀 양쪽이 깨진다(2026-09-02 앱 통합).
    세션은 컨텍스트가 공유하므로 새 탭을 열어도 로그인 상태 그대로다.
    """
    sys.path.insert(0, PART_ORDER_BACKUP_DIR)
    from sf_actions import get_sf_page
    ctx = browser.contexts[0]
    get_sf_page(ctx)              # 로그인된 탭이 있는지 확인만 한다
    page = ctx.new_page()
    # 새 탭은 about:blank라 검색창이 없다. search_po_url()이 현재 화면에서
    # 바로 'Search...' 를 찾으므로 반드시 Salesforce 화면을 띄워두고 넘긴다
    # (2026-09-02: 전용 탭으로 바꾸면서 이걸 빠뜨려 direct 모드가 죽었다).
    page.goto(SF_BASE, wait_until="domcontentloaded", timeout=40000)
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1500)
    return page


def _connect_sf():
    from playwright.sync_api import sync_playwright
    p = sync_playwright().start()
    try:
        browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{DEBUG_PORT}")
    except Exception:
        p.stop()
        raise RuntimeError(
            "SF 브라우저(포트 9222)에 연결 못함 - part_order_backup\\open_browser.py를 "
            "먼저 백그라운드로 띄워야 함")
    return p, browser


def search_po_url(page, po_no: str):
    """메일 링크가 없을 때 SF 전역검색으로 Parts Order 레코드 URL을 찾는다."""
    search_box = page.get_by_placeholder("Search...")
    search_box.click()
    search_box.fill(po_no)
    page.get_by_role("button", name="Search", exact=True).click()
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(1200)
    links = page.locator(f"a:has-text('{po_no}')")
    if links.count() == 0:
        return None
    href = links.first.get_attribute("href")
    if href and href.startswith("/"):
        return SF_BASE + href
    return href


LINE_RE = re.compile(r"Edit\t(LN-\S+)\t([^\t]+)\t([^\t]+)\t([\d.]+)")
WANT_LABELS = {"Order Type", "Order Status", "Interface To Oracle", "Oracle Order Number",
               "Message For Shipper", "Account", "Case"}


def fetch_po_details(page, po_url: str, retries=4, wait_sec=3):
    page.goto(po_url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(wait_sec * 1000)

    def _read():
        fields = {}
        labels = page.locator("td.labelCol")
        for i in range(labels.count()):
            try:
                lab = labels.nth(i).inner_text().strip()
                if lab in WANT_LABELS:
                    fields[lab] = labels.nth(i).locator(
                        "xpath=following-sibling::td[1]").first.inner_text().strip()
            except Exception:
                continue
        return fields

    fields = _read()
    for attempt in range(retries):
        order_type = fields.get("Order Type")
        if fields.get("Oracle Order Number"):
            break
        # 페이지 로딩이 덜 끝나 Order Type이 아직 빈 값으로 읽히는 경우가 있다
        # (2026-09-04 00601547 실측 - 실제로는 Shipping Only인데 빈 값으로 읽혀
        # skipped_billable로 영구 확정돼버렸다). 빈 값은 "아직 안 뜬 것"으로 보고
        # 반드시 재시도한다 - Billable 등 확정된 값이 나온 뒤에만 스킵 판단을 내린다.
        if order_type in (None, ""):
            page.wait_for_timeout(wait_sec * 1000)
            fields = _read()
            continue
        # Interface Success인데 Oracle Order Number가 아직 안 읽혔으면 재시도
        if order_type == "Shipping Only":
            page.wait_for_timeout(wait_sec * 1000)
            fields = _read()
        else:
            break

    lines = []
    go_to_list = page.locator("a:has-text('Go to list')")
    if go_to_list.count() > 0:
        href = go_to_list.first.get_attribute("href")
        full = (SF_BASE + href) if href and href.startswith("/") else href
        page.goto(full, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(1500)
        body_text = page.locator("body").inner_text()
    else:
        body = page.locator("div.bRelatedList")
        body_text = ""
        for i in range(body.count()):
            try:
                bt = body.nth(i).inner_text()
            except Exception:
                continue
            if "Parts Order Lines" in bt:
                body_text = bt
                break

    for m in LINE_RE.finditer(body_text):
        lines.append((m.group(2).strip(), m.group(3).strip(), m.group(4).strip()))

    # 2026-09-01 실측: Order Type/Oracle Order Number는 다 읽혔는데 관련목록
    # 렌더링이 아직 안 끝나 lines가 0건으로 잡히는 레이스가 있었다(00600626).
    # 품목 0건인 채로 메일을 보내면 안 되므로 몇 초 더 기다려 재확인한다.
    line_retry = 0
    while not lines and line_retry < retries:
        page.wait_for_timeout(wait_sec * 1000)
        body = page.locator("div.bRelatedList")
        body_text = ""
        for i in range(body.count()):
            try:
                bt = body.nth(i).inner_text()
            except Exception:
                continue
            if "Parts Order Lines" in bt:
                body_text = bt
                break
        for m in LINE_RE.finditer(body_text):
            lines.append((m.group(2).strip(), m.group(3).strip(), m.group(4).strip()))
        line_retry += 1

    return fields, lines


# ------------------------------------------------------------- Oracle release
def run_oracle_release(oracle_no: str) -> dict:
    import tempfile
    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="fse_release_")
    os.close(fd)
    if getattr(sys, "frozen", False):
        # exe로 묶여 돌면 콘다 환경이 없다 - 자기 자신을 릴리즈 모드로 다시 부른다
        cmd = [sys.executable, "--fse-release", oracle_no, out_path]
    else:
        cmd = [PDF_UPDATER_PY, ORACLE_RELEASE_SCRIPT, oracle_no, out_path]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=600, env=env)
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    for line in (p.stdout or "").splitlines():
        if line.strip():
            log("   " + line.rstrip()[:200])
    try:
        with open(out_path, encoding="utf-8") as f:
            res = json.load(f)
    except Exception:
        res = {"status": "no_result", "stderr": (p.stderr or "")[-800:]}
    finally:
        try:
            os.remove(out_path)
        except Exception:
            pass
    return res


# ------------------------------------------------------------- 공통 처리
DONE_STATUSES = ("released", "skipped_billable", "skipped_closed",
                  "skipped_already_sent", "mail_sent_release_pending")

# mail_sent_release_pending은 "메일은 나갔는데 release가 아직 안 됨"을 뜻한다.
# 이 상태를 DONE_STATUSES에 넣어 스캔에서 자동으로 다시 안 건드리게 한 이유는
# 2026-09-01 실제로 이미 처리된 5건에 중복 메일을 보낸 사고가 있었기 때문 -
# 재시도를 자동화하면 already_sent() 판정에만 의존하게 되는데, 그 판정이
# 놓치는 경우(예: 보낸편지함 검색 범위 밖)가 또 사고로 이어질 수 있다.
# release만 남았으면 fse_po_oracle_release.py를 오라클 오더번호로 직접
# 수동 실행할 것(오라클 release 자체는 재실행해도 안전 - 이미 release된 라인은
# 오라클이 다시 뽑지 않고, 안 뽑힌 라인만 released_lines로 잡힘).


def process_one(page, po_no, subject, sender_name, sender_email, po_link, state, entry_id=None):
    if po_no in state and state[po_no].get("status") in DONE_STATUSES:
        log(f"PO {po_no}: 이미 처리됨({state[po_no]['status']}) - 건너뜀")
        return

    if po_link:
        url = po_link
    else:
        url = search_po_url(page, po_no)
        if url is None:
            log(f"PO {po_no}: ServiceMax 검색 결과 없음 - 건너뜀")
            state[po_no] = {"status": "not_found"}
            return

    fields, lines = fetch_po_details(page, url)
    order_type = fields.get("Order Type", "")
    order_status = fields.get("Order Status", "")

    if order_type != "Shipping Only":
        log(f"PO {po_no}: Order Type={order_type!r} - Shipping Only 아님, 건너뜀"
            f"(Billable Parts Order 등은 이 자동화 대상 아님)")
        state[po_no] = {"status": "skipped_billable", "order_type": order_type}
        return

    # 2026-09-01 실측: 알림 메일은 남아있어도 그 사이 이미 다른 경로로
    # 완료(Closed)/취소(Shipment Complete 등)된 건일 수 있다(00600626 사고) -
    # 그런 건 절대 다시 건드리지 않는다. 다만 "Partial"(라인 일부만 backorder로
    # 남은 건)은 예외 - 사용자 확인(2026-09-01, "남은 backorder도 release
    # 시도"): 메일은 이미 나갔을 것이므로 다시 보내지 않되, 오라클 release만
    # 다시 시도해 남은 라인을 마저 뽑아본다.
    if order_status not in ("Open", "Partial"):
        log(f"PO {po_no}: Order Status={order_status!r} - 완료/취소된 건으로 보임, 건너뜀")
        state[po_no] = {"status": "skipped_closed", "order_type": order_type,
                        "order_status": order_status}
        return

    oracle_no = fields.get("Oracle Order Number", "").strip()
    if not oracle_no:
        log(f"PO {po_no}: Oracle Order Number 아직 없음(인터페이스 미완료) - "
            f"다음 스캔에서 재시도")
        state[po_no] = {"status": "pending_interface", "order_type": order_type}
        return

    if order_status == "Partial":
        log(f"PO {po_no}: Order Status=Partial(일부 라인 backorder 남음), "
            f"Oracle#{oracle_no} - 메일 재발송 없이 release만 재시도")
        with RELEASE_LOCK:
            release_result = run_oracle_release(oracle_no)
        release_ok = any(
            (r or {}).get("released_lines")
            for r in (release_result.get("rules") or {}).values()
        )
        state[po_no] = {
            "status": "partial_release_retried",
            "order_type": order_type,
            "order_status": order_status,
            "oracle_no": oracle_no,
            "release": release_result,
            "processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        log(f"PO {po_no}: Partial release 재시도 완료"
            f"({'추가로 뽑힘' if release_ok else '더 안 뽑힘 - 재고부족 지속 추정'})")
        return

    if not lines:
        log(f"PO {po_no}: 품목(Parts Order Line)을 하나도 못 읽음 - 정보 누락 상태로 "
            f"메일 보내면 안 되므로 건너뜀(다음 스캔에서 재시도)")
        state[po_no] = {"status": "pending_lines", "order_type": order_type,
                        "oracle_no": oracle_no}
        return

    if not sender_email:
        hit = lookup_sender_email(sender_name)
        if hit:
            sender_name, sender_email = hit
        else:
            log(f"PO {po_no}: 발신자 이메일을 못 구함({sender_name!r}) - CC 없이 발송")

    if not subject:
        subject = f"[External] New Parts Order#  {po_no}, , Expected Receive Date - (직접조회)"

    # 2026-09-01 사고 재발 방지: state 파일은 이 앱이 직접 처리한 것만 기억하므로,
    # 사용자가 수동으로 보냈거나 다른 프로세스가 이미 보낸 건은 state에 없을 수
    # 있다. 발송 직전 반드시 보낸편지함을 실제로 확인한다.
    if already_sent(po_no):
        log(f"PO {po_no}: 보낸편지함에 이미 같은 PO번호로 발송된 메일이 있음 - "
            f"중복 발송 방지를 위해 건너뜀(오라클 release도 이미 끝났을 가능성이 "
            f"높으니 건드리지 않음)")
        state[po_no] = {"status": "skipped_already_sent", "order_type": order_type,
                        "oracle_no": oracle_no}
        return

    msg_shipper = fields.get("Message For Shipper", "").strip()

    log(f"PO {po_no}: Order Type=Shipping Only, Oracle#{oracle_no}, "
        f"품목 {len(lines)}건 - 메일 발송 진행")
    send_release_mail(subject, oracle_no, lines, msg_shipper, sender_name, sender_email, entry_id)

    # 메일은 나갔으니 이 시점부터는 상태를 반드시 남긴다(release 성공 여부와
    # 무관하게 재발송은 절대 안 되므로).
    state[po_no] = {
        "status": "mail_sent_release_pending",
        "order_type": order_type,
        "oracle_no": oracle_no,
        "subject": subject,
        "cc_email": sender_email,
        "processed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    log(f"PO {po_no}: 오라클 release 진행 (다른 건과 겹치면 대기)")
    with RELEASE_LOCK:
        release_result = run_oracle_release(oracle_no)

    release_ok = any(
        (r or {}).get("released_lines")
        for r in (release_result.get("rules") or {}).values()
    )
    state[po_no]["release"] = release_result
    state[po_no]["status"] = "released" if release_ok else "mail_sent_release_pending"
    # mail_sent_release_pending은 DONE_STATUSES에 있어서 스캔이 다음 실행에서
    # 자동으로 다시 안 건드린다(메일 중복발송 방지가 우선이라 의도된 설계) -
    # 그래서 release 실패는 "다음 실행에서 자동재시도"가 아니라 fse_po_oracle_release.py
    # <오라클오더번호>로 수동 실행해야 마무리된다. 이 로그가 예전엔 반대로
    # 써 있어서 헷갈렸음(2026-09-03 00601331 건에서 발견).
    log(f"PO {po_no}: 처리 완료(release "
        + ("성공" if release_ok
           else "실패 - 자동재시도 안 됨, fse_po_oracle_release.py로 직접 재실행 필요")
        + ")")


def process_candidate(c, state, stop_event):
    """워커 스레드 1건 처리 - 자기 전용 Playwright 연결/탭을 새로 열고 끝나면 정리.

    part_order_app.py의 병렬처리(2026-09-02)와 같은 패턴: 워커마다 sync_playwright()
    인스턴스를 따로 띄운다(연결 객체를 스레드끼리 공유하면 충돌). Outlook COM은
    새 스레드마다 CoInitialize가 필요하다([[selenium-stability-hardening]]과 동일 원인).
    """
    po_no = c["po_no"]
    if stop_event.is_set():
        log(f"PO {po_no}: 브라우저 연결 문제로 이번 회차는 건너뜀 - 다음 스캔에서 재시도")
        return
    import pythoncom
    pythoncom.CoInitialize()
    p = browser = page = None
    try:
        p, browser = _connect_sf()
        page = _sf_page(browser)
        process_one(page, po_no, c["subject"], c["sender_name"],
                    c["sender_email"], c["po_link"], state, c.get("entry_id"))
    except Exception as e:
        import traceback
        traceback.print_exc()
        msg = str(e)
        log(f"PO {po_no}: 처리 중 예외 - {type(e).__name__}: {msg}")
        # 브라우저가 죽은 거면 남은 건을 계속 돌려봐야 전부 실패한다.
        # 그대로 두면 실패 기록만 잔뜩 쌓이므로 나머지 대기 건은 건너뛴다.
        if "has been closed" in msg or "Target page" in msg or "연결 못함" in msg:
            log("  브라우저 연결이 끊겼습니다 - 남은 대기 건은 스킵합니다. "
                "[브라우저 열기] 후 다시 실행하세요.")
            stop_event.set()
        else:
            with STATE_LOCK:
                state[po_no] = {"status": "error", "error": msg}
    finally:
        try:
            if page:
                page.close()
        except Exception:
            pass
        try:
            if p:
                p.stop()
        except Exception:
            pass
        _save_state_locked(state)
        pythoncom.CoUninitialize()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "scan"
    state = load_state()

    if mode == "cutoff":
        # 기준시각 설정은 Salesforce에 붙을 필요가 없다
        from datetime import datetime as _dt
        when = (_dt.strptime(sys.argv[2], "%Y-%m-%d %H:%M:%S")
                if len(sys.argv) > 2 else _dt.now())
        save_state(set_only_after(state, when))
        log(f"이 시각 이후에 온 메일만 처리합니다: {when:%Y-%m-%d %H:%M:%S}")
        return

    if mode == "scan":
        candidates = scan_new_mails(only_after=get_only_after(state))
        # error도 다시 시도한다. 예전엔 한 번 error가 박히면 영영 건너뛰어서
        # 브라우저가 잠깐 닫힌 것만으로 그 주문이 조용히 누락됐다
        # (2026-09-02: 브라우저가 닫히며 5건이 줄줄이 error로 기록됨).
        # 메일 재발송은 already_sent()가 보낸편지함으로 막으므로 안전하다.
        # pending_lines도 여기 없으면 영원히 안 건드려진다(2026-09-03 00601295로
        # 실제 발견 - 스캔 순간 관련목록 렌더링이 안 끝나 lines=0으로 한 번 걸리면
        # DONE_STATUSES에도 없고 RETRY에도 없어서 다음 스캔부터 그냥 통째로 무시됨).
        RETRY = ("pending_interface", "pending_lines", "error")
        pending = [c for c in candidates if c["po_no"] not in state
                   or state[c["po_no"]].get("status") in RETRY]

        # 파트오더앱(혜준대리님 건)이 만든 Billable Parts Order는 FSE 플로우
        # 대상이 아니다. 그 알림 메일도 FSE PO 폴더로 같이 들어오는데, SF를
        # 조회해서 Order Type으로 거르기 전에 번호만으로 먼저 쳐낸다 -
        # 조회 자체를 안 하면 잘못 읽어 용마에 중복 출고요청이 나갈 여지가 없다
        # (2026-09-02 사용자 지시: "billable은 무시해야해").
        own = known_billable_po_numbers()
        skipped_own = [c for c in pending if c["po_no"] in own]
        for c in skipped_own:
            state[c["po_no"]] = {"status": "skipped_billable",
                                 "reason": "파트오더앱이 만든 Billable 건",
                                 "processed_at": time.strftime("%Y-%m-%d %H:%M:%S")}
            log(f"PO {c['po_no']}: 파트오더앱(Billable) 건 - 건너뜀")
        if skipped_own:
            save_state(state)
        pending = [c for c in pending if c["po_no"] not in own]

        log(f"FSE PO 폴더 스캔: 후보 {len(candidates)}건 중 처리 대상 {len(pending)}건 "
            f"(최대 {MAX_PARALLEL_FSE}건 동시 처리, 오라클 릴리즈만 순서대로)")
        if pending:
            stop_event = threading.Event()
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_FSE) as ex:
                list(ex.map(lambda c: process_candidate(c, state, stop_event), pending))
        return

    if mode == "direct":
        if len(sys.argv) < 3:
            print("사용법: python fse_po_release.py direct <PO_NO>")
            sys.exit(1)
        po_no = sys.argv[2]
        p, browser = _connect_sf()
        page = None
        try:
            page = _sf_page(browser)
            process_one(page, po_no, None, "", "", None, state)
            save_state(state)
        finally:
            # 내가 연 탭만 닫고 연결을 끊는다. browser.close()를 하면 붙어 있는
            # Edge 자체를 건드려 다른 탭 작업까지 같이 죽을 수 있다.
            try:
                if page:
                    page.close()
            except Exception:
                pass
            p.stop()
        return

    print(f"알 수 없는 모드: {mode} (scan 또는 direct 사용)")
    sys.exit(1)


if __name__ == "__main__":
    main()
