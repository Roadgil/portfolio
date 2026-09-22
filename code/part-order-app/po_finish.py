# -*- coding: utf-8 -*-
"""승인 이후 단계: Trigger Interface To Oracle -> Success 확인 -> 오라클 Release
-> 완료 메일.

Send To Approval은 여기서도 절대 누르지 않는다 - 사용자가 직접 누른다.
"""
import json
import os
import re
import sys
import time
from datetime import datetime

import paths                    # 사용자마다 다른 경로를 이 PC 기준으로 풀어준다
from sf_actions import wait_for_frame_with_text

PICK_DIR = paths.PICK_DIR

YONGMA_TO = ("김기훈 <y7221063@yongmalogis.co.kr>; "
             "용호 유 <y7225055@yongmalogis.co.kr>")
MAIL_FONT_CSS = "font-family:'맑은 고딕',Malgun Gothic,sans-serif;font-size:10pt;"


# ---------------------------------------------------------------- Salesforce
def _load(page, url, log):
    # 같은 주소로 다시 goto하면 브라우저가 캐시된 화면을 그대로 보여줘, 남이 방금
    # 바꾼 값을 못 읽는다. 2026-09-03 00601290: 재무가 14:00에 Finance Status를
    # Approved로 바꿨는데도 계속 'Pending Approval'로 읽혀 "승인 대기"로 오판했다.
    # 매번 다른 쿼리스트링을 붙여 새로 받아온다.
    bust = f"{'&' if '?' in url else '?'}_t={int(time.time() * 1000)}"
    try:
        page.goto(url + bust, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        log(f"  goto 경고(무시): {e}")
    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass          # SF Classic은 계속 폴링해 networkidle에 도달하지 않을 수 있음
    page.wait_for_timeout(2000)


def read_fields(page, names):
    got = {}
    labels = page.locator("td.labelCol")
    for i in range(labels.count()):
        try:
            lab = labels.nth(i).inner_text().strip()
            if lab in names:
                got[lab] = labels.nth(i).locator(
                    "xpath=following-sibling::td[1]").first.inner_text().strip()
        except Exception:
            continue
    return got


def approval_status(page):
    """Approval History 관련목록 텍스트에서 승인 여부를 판단한다."""
    lists = page.locator("div.bRelatedList")
    for i in range(lists.count()):
        try:
            t = lists.nth(i).inner_text()
        except Exception:
            continue
        if "Approval History" in t:
            if "Approved" in t:
                return "Approved", t.strip()[:400]
            if "Rejected" in t:
                return "Rejected", t.strip()[:400]
            if "Submitted" in t or "Pending" in t:
                return "Pending", t.strip()[:400]
            return "None", t.strip()[:400]
    return "Unknown", ""


def trigger_interface(page, po_url, log=print, poll_sec=240):
    """승인 확인 -> Trigger Interface To Oracle -> Success/Oracle Order Number 폴링."""
    _load(page, po_url, log)
    f = read_fields(page, {"Order Status", "Interface To Oracle",
                           "Oracle Order Number", "Account",
                           "Pay In Advance?", "Finance Status",
                           "Consumables Approval Status"})
    log(f"  Order Status={f.get('Order Status')!r} "
        f"Interface={f.get('Interface To Oracle')!r} "
        f"OracleNo={f.get('Oracle Order Number')!r}")

    if (f.get("Order Status") or "").lower() == "canceled":
        return {"status": "canceled", **f}

    if (f.get("Interface To Oracle") or "").lower() == "success" and f.get("Oracle Order Number"):
        log("  이미 오라클 전송 완료 - 트리거 생략")
        return {"status": "already_success", **f}

    st, hist = approval_status(page)
    log(f"  승인상태: {st}")
    if st != "Approved":
        return {"status": "not_approved", "approval": st, "history": hist, **f}

    # 선입금(Pay In Advance) 건은 서비스팀 승인 뒤에 **재무 승인이 한 번 더** 필요하다.
    # 그때까지는 트리거 링크가 화면에 보여도 눌리지 않는다 - 예전에는 이 상태를
    # trigger_disabled로 뭉뚱그려 "Location 오라클 연동을 확인하라"는 엉뚱한 안내를
    # 냈다(2026-09-03 00601290 로제피부과의원 범어 실측: Pay In Advance?=True,
    # Finance Status=Pending Approval, 1차 승인은 정상).
    pay_adv = (f.get("Pay In Advance?") or "").strip().lower() in ("true", "yes", "checked")
    fin = (f.get("Finance Status") or "").strip()
    if pay_adv and fin.lower() not in ("approved", ""):
        log(f"  선입금 건 - Finance Status={fin!r}: 재무 승인이 아직 안 났습니다")
        return {"status": "needs_finance_approval",
                "hint": "선입금(Pay In Advance) 건이라 재무 승인이 한 번 더 필요합니다. "
                        "화면에서 Send to Approval을 다시 눌러 재무 승인을 받은 뒤 "
                        "다시 실행하세요.", **f}

    fr = wait_for_frame_with_text(page, "Trigger Interface To Oracle", timeout_ms=20000)
    if fr is None:
        return {"status": "no_trigger_link",
                "hint": "승인 후에도 링크가 없으면 Order가 취소됐거나 "
                        "'Interface user's permission to run' 권한이 없을 수 있음", **f}

    link = fr.get_by_text("Trigger Interface To Oracle", exact=False).first
    # 링크가 보여도 안 눌리는 경우가 있다 - Location의 'Interface To Oracle'이
    # 비어 있으면(오라클 연동 안 된 Location) 비활성이다.
    # is_enabled()로 미리 판단하면 안 된다: 전송이 끝난 정상 건도 False로 나온다
    # (2026-09-01 실측). 짧은 타임아웃으로 실제 클릭을 시도해서 판별한다.
    # (기본 30초를 그대로 두면 예외가 나면서 배치 전체가 죽는다)
    try:
        link.click(timeout=8000)
    except Exception:
        log(f"  트리거 링크가 안 눌림 - 오라클 전송 불가 "
            f"(Finance Status={f.get('Finance Status')!r}, "
            f"Pay In Advance?={f.get('Pay In Advance?')!r})")
        return {"status": "trigger_disabled",
                "hint": "① 선입금 건이면 재무 승인이 한 번 더 필요합니다"
                        "(Send to Approval 재발송). "
                        "② 그게 아니면 Location의 'Interface To Oracle'이 비어 있는지 "
                        "확인하세요(오라클 연동 안 된 Location이면 등록이 먼저 필요).", **f}
    log("  Trigger Interface To Oracle 클릭 - 결과 대기(최대 %d초)" % poll_sec)
    page.wait_for_timeout(5000)

    deadline = time.time() + poll_sec
    while time.time() < deadline:
        _load(page, po_url, log=lambda *_: None)
        f = read_fields(page, {"Interface To Oracle", "Oracle Order Number",
                               "Oracle error message", "Order Status"})
        iface = (f.get("Interface To Oracle") or "").strip()
        ono = (f.get("Oracle Order Number") or "").strip()
        if iface.lower() == "success" and ono:
            log(f"  전송 성공 | Oracle Order Number={ono}")
            return {"status": "success", **f}
        if iface.lower() in ("error", "failed"):
            log(f"  전송 실패: {f.get('Oracle error message')}")
            return {"status": "interface_error", **f}
        log(f"  ... 대기중 (Interface={iface!r})")
        time.sleep(15)

    return {"status": "timeout", **f}


# ------------------------------------------------------------------- Oracle
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PDF_UPDATER_PY = paths.PDF_UPDATER_PY
RELEASE_SCRIPT = os.path.join(BASE_DIR, "release_one.py")


def release_order(order_no, subject, kind="DCD", log=print, timeout=900,
                  busy_retries=6, busy_wait=70):
    """busy(스케줄러 watcher가 락 보유)면 기다렸다 재시도한 뒤 결과를 돌려준다.

    pick_release_watcher가 20분마다 도는데 그때 물리면 singleton lock을 못 잡아
    'busy'로 끝난다(2026-09-01: 6건 중 4건이 이걸로 실패). 릴리즈 자체는 문제없고
    잠깐 기다리면 되므로 여기서 재시도한다."""
    import time as _t
    for i in range(busy_retries + 1):
        res = _release_once(order_no, subject, kind, log, timeout)
        if res.get("status") != "busy":
            return res
        if i < busy_retries:
            log(f"  락 사용 중 - {busy_wait}초 후 재시도 ({i + 1}/{busy_retries})")
            _t.sleep(busy_wait)
    return res


def _release_once(order_no, subject, kind="DCD", log=print, timeout=900):
    """Parts Order 번호(00xxxxxx)로 오라클 Pick Release.

    pick_release_watcher는 pytesseract/selenium이 있는 `pdf_updater` 콘다 환경에서만
    import된다. 앱은 기본 파이썬으로 도니 여기서 직접 import하면
    ModuleNotFoundError가 난다(2026-09-01 실측) - 전용 인터프리터로 subprocess 실행한다.
    """
    import subprocess
    import tempfile

    # exe로 묶여 돌 때는 콘다 환경이 없다. 릴리즈에 필요한 패키지가 exe 안에 같이
    # 들어 있으므로 자기 자신을 --release 모드로 다시 부른다(2026-09-02 단독 실행 지원).
    frozen = getattr(sys, "frozen", False)
    if frozen:
        cmd = [sys.executable, "--release", kind, order_no, subject]
    elif not os.path.exists(PDF_UPDATER_PY):
        return {"status": "no_interpreter",
                "msg": f"릴리즈용 파이썬을 찾을 수 없음: {PDF_UPDATER_PY}"}
    else:
        cmd = [PDF_UPDATER_PY, RELEASE_SCRIPT, kind, order_no, subject]

    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="release_")
    os.close(fd)
    cmd = cmd + [out_path]
    log(f"  release 시작: {kind} {order_no} (별도 프로세스)")

    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    try:
        # encoding을 명시하지 않으면 자식 프로세스의 한글 로그가 깨져 보인다.
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "msg": f"{timeout}초 안에 안 끝남"}

    for line in (p.stdout or "").splitlines():
        if line.strip():
            log("   " + line.rstrip()[:200])

    try:
        with open(out_path, encoding="utf-8") as f:
            res = json.load(f)
    except Exception:
        res = {"status": "no_result",
               "stderr": (p.stderr or "")[-800:]}
    finally:
        try:
            os.remove(out_path)
        except Exception:
            pass

    if res.get("status") == "released":
        log(f"  release 성공: {res.get('released')}건 - 상태파일 기록 완료")
    else:
        log(f"  release 결과: {res.get('status')} {res.get('error') or res.get('msg') or ''}")
    return res


# -------------------------------------------------------------------- Mail
def _prepend_html(reply, text):
    import html as html_module
    body = reply.HTMLBody or ""
    content = html_module.escape(text).replace("\n", "<br>")
    wrapped = f'<div style="{MAIL_FONT_CSS}">{content}</div>'
    m = re.search(r"(<body[^>]*>)", body, re.IGNORECASE)
    if m:
        reply.HTMLBody = body[:m.end()] + wrapped + body[m.end():]
    else:
        reply.HTMLBody = wrapped + body


def send_completion_mail(entry_id, po_numbers, log=print, send=True, preship=False):
    """휴가 중 형식(사용자 지정): To=용마 두 분만, CC 없음, 본문에 parts order 번호.

    발송 후 reply의 속성을 다시 읽으면 'item has been moved or deleted' COM 오류가
    나는데 보낸편지함으로 옮겨간 것뿐이다 - 오류 보고 재발송하지 말 것.
    """
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    mail = ns.GetItemFromID(entry_id)
    subject = str(mail.Subject or "")

    reply = mail.ReplyAll()
    reply.To = YONGMA_TO
    reply.CC = ""
    reply.BCC = ""

    nums = po_numbers if isinstance(po_numbers, (list, tuple)) else [po_numbers]
    lines = "\n".join(f"parts order : {n}" for n in nums)
    # 월마감 선출고 건은 물건이 이미 나갔고 전산만 뒤늦게 맞추는 것이라 문구가 다르다
    # (2026-09-01 사용자 지정).
    head = ("선출고 건 릴리즈됐습니다 전산처리 부탁드립니다" if preship
            else "release 완료됐습니다")
    body = f"기훈님 용호님\n\n{head}\n\n{lines}\n"
    _prepend_html(reply, body)

    for idx in range(reply.Attachments.Count, 0, -1):
        try:
            reply.Attachments.Item(idx).Delete()
        except Exception:
            pass

    if send:
        reply.Send()
        log(f"  완료메일 발송: {subject} | {nums}")
        return {"status": "sent", "subject": subject, "po": nums}
    reply.Save()
    log(f"  완료메일 초안 저장: {subject} | {nums}")
    return {"status": "draft", "subject": subject, "po": nums}


# 승인 알림이 떨어지는 받은편지함 하위 폴더들. 서비스팀 승인은 'CK service team',
# 선입금(Pay In Advance) 건의 재무 승인은 'Finance'로 온다(2026-09-03 사용자 확인
# - 00601290이 재무 승인까지 났는데 CK 폴더만 봐서 '승인 0건'으로 나왔다).
APPROVAL_FOLDERS = ("CK service team", "Finance")
APPROVAL_FOLDER = APPROVAL_FOLDERS[0]      # 예전 이름 유지(다른 코드 참조 대비)
# 실측 제목: "[External] Part Order #:  00600136  has been approved"
APPROVAL_RE = re.compile(r"Part Order #:\s*(\d{6,10})\s*has been approved", re.I)


def scan_approval_mails(days=14, mailbox=None, log=print):
    """CK service team 폴더에서 승인 알림 메일을 읽어 {PO번호: 정보} 로 돌려준다.

    보내는 사람은 차종성 차장님/이광열 이사님이지만, 이름에 의존하지 않고 제목
    패턴으로 잡는다(제목에 PO 번호가 그대로 들어있다).
    """
    import win32com.client
    from datetime import timedelta
    if mailbox is None:
        import local_config
        mailbox = local_config.load()["outlook_mailbox"]

    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    inbox = ns.Folders[mailbox].Folders["받은 편지함"]
    cutoff = datetime.now() - timedelta(days=days)

    found, seen_folders = {}, []
    for name in APPROVAL_FOLDERS:
        folder = next((f for f in inbox.Folders if f.Name == name), None)
        if folder is None:
            log(f"  [경고] '{name}' 폴더를 찾지 못함 - 건너뜀")
            continue
        seen_folders.append(name)
        items = folder.Items
        items.Sort("[ReceivedTime]", True)
        for it in items:
            try:
                if it.Class != 43:
                    continue
                rt = it.ReceivedTime.replace(tzinfo=None)
            except Exception:
                continue
            if rt < cutoff:
                break
            subj = str(getattr(it, "Subject", "") or "")
            m = APPROVAL_RE.search(subj)
            if not m:
                continue
            po = m.group(1)
            info = {"received": str(rt)[:16],
                    "sender": str(getattr(it, "SenderName", "") or ""),
                    "subject": subj, "folder": name}
            cur = found.setdefault(po, {"stages": {}})
            # 승인은 2단계다 - 1차 서비스팀(CK service team), 선입금 건만 2차
            # 재무(Finance). 단계별로 따로 들고 있다가 최신 것을 대표값으로 쓴다
            # (2026-09-03 실측 31건: CK 31건 전부 / Finance 2건 / Finance만 온 건 0).
            cur["stages"].setdefault(name, info)
            if "received" not in cur or info["received"] > cur["received"]:
                cur.update({k: info[k] for k in ("received", "sender", "subject",
                                                 "folder")})
    log(f"  승인 메일 {len(found)}건 감지 (최근 {days}일, 폴더 {'/'.join(seen_folders)})")
    return found


def decide_kind(product_code):
    """릴리즈 룰 카테고리를 정한다.

    사용자 규칙(2026-09-01): DCD는 FG, **소모품이 하나라도 있으면 SP도 돌려야 한다.**
    watcher의 PRIMARY_SECONDARY_RULES가
      DCD    = (FG, 백오더면 SP)
      소모품 = (SP, 백오더면 FG)
    이므로 소모품이 섞이면 kind를 '소모품'으로 줘서 SP가 먼저 돌게 한다.
    DCD 품번은 FIN101110 하나뿐이고 나머지(7122-xx 등)는 소모품이다.
    """
    codes = [c.strip() for c in str(product_code or "").split("+") if c.strip()]
    if not codes:
        return "DCD"
    return "DCD" if all(c.upper() == "FIN101110" for c in codes) else "소모품"


def send_completion_mail_new(hospital, po_numbers, item_label="", log=print,
                             send=True, preship=False):
    """원본 요청 메일이 없는 건(문자 접수)용 완료메일 - 새 메일로 보낸다."""
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = YONGMA_TO
    mail.CC = ""
    nums = po_numbers if isinstance(po_numbers, (list, tuple)) else [po_numbers]
    suffix = f" {item_label}" if item_label else ""
    subj = f"출고 요청의 건 ({hospital}){suffix} - release 완료"
    mail.Subject = subj          # 발송 후에는 이 속성을 다시 읽으면 안 된다(아래 주석)
    lines = "\n".join(f"parts order : {n}" for n in nums)
    head = ("선출고 건 릴리즈됐습니다 전산처리 부탁드립니다" if preship
            else "release 완료됐습니다")
    text = f"기훈님 용호님\n\n{head}\n\n{lines}\n\n감사합니다\n채윤길 드림\n"
    import html as html_module
    mail.HTMLBody = (f'<div style="{MAIL_FONT_CSS}">'
                     + html_module.escape(text).replace("\n", "<br>") + "</div>")
    if send:
        mail.Send()
        # Send() 뒤에 mail.Subject 같은 속성을 읽으면 보낸편지함으로 옮겨가서
        # "The item has been moved or deleted" COM 오류가 난다 - 발송은 정상인데
        # 스크립트가 죽는다(2026-09-01 실측). 제목은 미리 잡아둔 변수를 쓴다.
        log(f"  완료메일 발송(신규): {subj} | {nums}")
        return {"status": "sent_new", "po": nums, "subject": subj}
    mail.Save()
    log(f"  완료메일 초안(신규): {nums}")
    return {"status": "draft_new", "po": nums}


def already_sent_completion(po_no, days=7):
    """이 PO의 완료메일이 이미 나갔는지 본문의 'parts order : <번호>'로 확인한다.

    병원명으로 찾으면 8/31에 보낸 선출고 요청메일이 걸려 완료메일을 건너뛴다
    (제목에 병원명이 들어가므로) - 2026-09-01 수정.
    """
    import win32com.client
    from datetime import timedelta
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    sent = ns.GetDefaultFolder(5)
    items = sent.Items
    items.Sort("[SentOn]", True)
    cutoff = datetime.now() - timedelta(days=days)
    needle = f"parts order : {po_no}"
    hits = []
    for it in items:
        try:
            if it.Class != 43:
                continue
            son = it.SentOn.replace(tzinfo=None)
        except Exception:
            continue
        if son < cutoff:
            break
        try:
            body = str(getattr(it, "Body", "") or "")
        except Exception:
            continue
        if needle in body:
            hits.append((str(son)[:19], str(getattr(it, "Subject", "") or "")))
    return hits


def already_replied(subject_hint, days=3):
    """보낸편지함에 같은 제목 답장이 이미 있는지 확인(중복 발송 방지)."""
    import win32com.client
    from datetime import timedelta
    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    sent = ns.GetDefaultFolder(5)
    items = sent.Items
    items.Sort("[SentOn]", True)
    cutoff = datetime.now() - timedelta(days=days)
    hits = []
    for it in items:
        try:
            if it.Class != 43:
                continue
            son = it.SentOn.replace(tzinfo=None)
        except Exception:
            continue
        if son < cutoff:
            break
        s = str(getattr(it, "Subject", "") or "")
        if subject_hint and subject_hint in s:
            hits.append((str(son)[:19], s))
    return hits


# --------------------------------------------------------------- 진행 상태 분류
# 대기 목록(batch_result.json)의 note는 생성 시점에 "릴리즈 대기"로 고정돼 있어서
# 끝난 건과 안 끝난 건이 섞여 보인다. note를 믿지 말고 실제 흔적 두 가지로 판정한다.
#   - 릴리즈 여부: pick_release_watcher의 _processed_orders.json (키 = PO 번호)
#   - 완료메일 여부: 보낸편지함 본문의 "parts order : <번호>"
PROCESSED_ORDERS = paths.PROCESSED_ORDERS
_SENT_PO_RE = re.compile(r"parts order\s*:\s*(\d{6,10})", re.I)


def released_orders():
    """{PO번호: {처리시각, kind, 릴리즈줄수}} - 오라클 릴리즈가 끝난 건."""
    try:
        with open(PROCESSED_ORDERS, encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        return {}
    out = {}
    for k, v in st.items():
        if not (k.isdigit() and isinstance(v, dict)):
            continue          # FIBER백오더 등 접두어 붙은 키는 대상 아님
        lines = sum((r.get("released_lines") or 0) for r in (v.get("results") or []))
        out[k] = {"at": v.get("processed_at"), "kind": v.get("kind"),
                  "lines": lines, "error": v.get("error")}
    return out


def sent_completion_orders(days=30):
    """보낸편지함을 한 번만 훑어 완료메일이 나간 PO 번호 집합을 돌려준다.

    already_sent_completion()은 PO 1건마다 보낸편지함을 다시 읽어서 목록이
    20건이면 20번 훑는다. 화면 새로고침용으로는 이 한 번짜리를 쓴다.
    """
    import win32com.client
    from datetime import timedelta
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    items = ns.GetDefaultFolder(5).Items
    items.Sort("[SentOn]", True)
    cutoff = datetime.now() - timedelta(days=days)
    found = {}
    for it in items:
        try:
            if it.Class != 43:
                continue
            son = it.SentOn.replace(tzinfo=None)
        except Exception:
            continue
        if son < cutoff:
            break
        try:
            body = str(getattr(it, "Body", "") or "")
        except Exception:
            continue
        for po in _SENT_PO_RE.findall(body):
            found.setdefault(po, str(son)[:16])
    return found


#   done      릴리즈 + 완료메일까지 끝 (더 볼 것 없음)
#   mail_todo 릴리즈는 됐는데 완료메일이 안 나감 -> ③만 돌리면 됨
#   ready     승인 메일은 왔는데 릴리즈 전 -> ①~③ 대상
#   waiting   아직 승인 안 남 (Send to Approval 확인 필요)
#   no_po     PO 번호가 비어 기록됨 -> _diag_backfill_po_number.py
#   cancelled SF에서 취소됨 (취소 알림 메일로 판정)
#   fin_wait  1차(서비스팀) 승인은 났는데 선입금 건이라 재무 승인이 남음
STATUS_LABEL = {"done": "완료", "mail_todo": "메일만 남음", "ready": "승인 - 진행가능",
                "waiting": "승인 대기", "no_po": "PO번호 없음", "cancelled": "취소됨",
                "fin_wait": "재무 승인 대기"}


def classify_pending(pending, appr=None, rel=None, sent=None, canc=None, log=print):
    """대기 목록 각 건에 status/status_label/released/mailed_at 를 채워 돌려준다."""
    if appr is None:
        appr = scan_approval_mails(days=14, log=log)
    if rel is None:
        rel = released_orders()
    if sent is None:
        try:
            sent = sent_completion_orders()
        except Exception as e:
            log(f"  보낸편지함 확인 실패(완료 판정 생략): {e}")
            sent = {}
    if canc is None:
        try:
            canc = scan_cancel_mails(log=log)
        except Exception as e:
            log(f"  취소 메일 확인 실패(무시): {e}")
            canc = {}

    out = []
    for c in pending:
        c = dict(c)
        po = str(c.get("parts_order_number") or "")
        r, s, a = rel.get(po), sent.get(po), appr.get(po)
        c["released"] = r
        c["mailed_at"] = s
        c["approved_at"] = a["received"] if a else None
        c["cancelled_at"] = canc.get(po)
        stages = (a or {}).get("stages") or {}
        c["approved_service_at"] = (stages.get("CK service team") or {}).get("received")
        c["approved_finance_at"] = (stages.get("Finance") or {}).get("received")
        if not po:
            c["status"] = "no_po"
        elif c.get("cancelled") or (c["cancelled_at"] and not r):
            # 취소 알림 메일이 오면 취소된 것. 다만 릴리즈까지 끝난 건은 덮지 않는다.
            c["status"] = "cancelled"
        elif (not r and c.get("needs_finance")
              and not c["approved_finance_at"]):
            # 선입금 건이라 오라클 전송 때 재무 승인 대기로 막힌 적이 있고, 아직
            # Finance 폴더 승인 메일이 안 온 상태. 미리 예측하지 않고 한 번 막혀본
            # 뒤에만 이 상태로 둔다(_finish_one이 needs_finance를 기록한다).
            c["status"] = "fin_wait"
        elif r and s:
            c["status"] = "done"
        elif r:
            c["status"] = "mail_todo"
        elif a:
            c["status"] = "ready"
        else:
            c["status"] = "waiting"
        c["status_label"] = STATUS_LABEL[c["status"]]
        out.append(c)
    return out


# 파트오더를 취소하면 "[External] Part Order# 00601076 Was Canceled" 제목으로
# 알림 메일이 본인 받은편지함에 온다(2026-09-02 사용자 확인). 예전엔 취소해도
# 앱이 몰라서 계속 '승인 대기'로 떠 있었다.
CANCEL_RE = re.compile(r"Parts?\s*Order#?\s*(\d{6,10}).{0,40}?Cancel", re.I)


def scan_cancel_mails(days=30, mailbox=None, log=print):
    """취소 알림 메일을 훑어 {PO번호: 받은시각} 을 돌려준다.

    받은편지함 본문(하위 폴더 포함)에 흩어져 오므로 폴더를 재귀로 본다.
    """
    import win32com.client
    from datetime import timedelta
    if mailbox is None:
        import local_config
        mailbox = local_config.load()["outlook_mailbox"]
    ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    try:
        inbox = ns.Folders[mailbox].Folders["받은 편지함"]
    except Exception as e:
        log(f"  취소 메일 확인 생략({e})")
        return {}

    cutoff = datetime.now() - timedelta(days=days)
    found, stack, seen = {}, [inbox], 0
    while stack and seen < 40:
        f = stack.pop()
        seen += 1
        try:
            for sub in f.Folders:
                stack.append(sub)
        except Exception:
            pass
        try:
            items = f.Items
            items.Sort("[ReceivedTime]", True)
        except Exception:
            continue
        n = 0
        for it in items:
            n += 1
            if n > 400:                 # 폴더마다 최근 것만 본다(속도)
                break
            try:
                if it.Class != 43:
                    continue
                rt = it.ReceivedTime.replace(tzinfo=None)
            except Exception:
                continue
            if rt < cutoff:
                break
            subj = str(getattr(it, "Subject", "") or "")
            if "ancel" not in subj:
                continue
            m = CANCEL_RE.search(subj)
            if m:
                found.setdefault(m.group(1), str(rt)[:16])
    return found
