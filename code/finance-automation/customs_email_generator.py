# -*- coding: utf-8 -*-
"""
인천관세법인 '월별 납부 고지서' 메일 자동 처리 -> 비용처리 요청 메일 초안 생성

전체 흐름 (무인 실행 가능):
  1) Outlook 받은 편지함에서 '월별 납부 고지서' 메일(제목에 키워드 포함 또는 NT 시작)
     중 가장 최근 것을 찾는다.
  2) 그 메일에서 NT 로 시작하는 PDF 첨부만 저장한다. (해당 PDF만 파싱)
  3) PDF에서 관세 / 부가세 / 납부기한을 추출한다.
  4) 정해진 형식의 비용처리 요청 메일을 만들어 Outlook 초안(Drafts)으로 저장한다.
     (검토 후 직접 [보내기] / --display: 작성 창을 띄움)

사용법:
  python customs_email_generator.py            -> Outlook에서 자동 수집 + 초안 저장
  python customs_email_generator.py --display  -> 초안 저장 대신 작성 창을 띄움
  python customs_email_generator.py "어떤.pdf" -> 특정 PDF 직접 지정 (Outlook 수집 생략)

필요 패키지:
  pip install pdfplumber pywin32
"""

import os
import re
import sys
import json
import shutil
import calendar
import argparse
from datetime import date, datetime

import pdfplumber
import openpyxl


# ── 설정 (환경에 맞게 수정) ──────────────────────────────────────
MAILBOX         = "yoongil.chae@candelamedical.com"  # 받은 편지함 계정
SUBJECT_KEYWORD = "월별 납부 고지서"   # 메일 제목 매칭 키워드 (공백 무시 비교)
ATTACH_PREFIX   = "NT"                # 파싱할 PDF 첨부 파일명 접두어
INBOX_NAMES     = ["받은 편지함", "Inbox"]  # 받은편지함 폴더명 후보

# 고지서가 들어오는 폴더 '이름'. 폴더트리 어디에 있든 이 이름으로 찾는다.
# (받은편지함 > 인천관세법인 처럼 하위 폴더여도 자동 탐색)
# 비우면("") 받은편지함 + 아래 INBOX_SUBFOLDER_PATH 방식으로 동작.
TARGET_FOLDER_NAME = "인천관세법인"

# (TARGET_FOLDER_NAME 을 비웠을 때만 사용하는) 받은편지함 하위 경로
INBOX_SUBFOLDER_PATH = []
SCAN_LIMIT      = 500                 # 폴더에서 최신순으로 훑을 최대 메일 수

# ── 오래된 고지서 차단(발행월 기준) ──────────────────────────────
# 고지서는 '발행월' 안에서만 발송한다. 발행월이 지나면(다음 달 이후) 건너뛴다.
#   예) 발행일 4/16 -> 4월에만 발송. 5월 들어 실행되면 건너뜀.
# 발행일은 파일명(NT + YYYYMMDD)에서 우선 추출하고, 실패 시 본문 라벨로 폴백한다.
ISSUE_DATE_LABELS  = [
    "발행일자", "발행일", "발급일자", "발급일",
    "고지일자", "고지일", "작성일자", "작성일",
    "출력일자", "출력일",
]

# 받은 PDF 첨부를 저장할 폴더 (스크립트 위치 기준 하위 폴더)
def _script_dir():
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.getcwd()

SAVE_DIR = os.path.join(_script_dir(), "납부고지서_PDF")

# 이미 처리한 메일을 기록하는 상태 파일 (중복 처리 방지)
STATE_FILE = os.path.join(_script_dir(), "customs_email_state.json")

# ── W&D Cost 자동 반영 (2026-08-31 사용자 요청) ──────────────────
# wd_cost_monthly_updater.py 와 동일한 경로/파일명 규칙을 그대로 재사용한다.
_ROOT_DIR      = os.path.dirname(_script_dir())        # "...\10. 수입"
_OPERATION_DIR = os.path.dirname(_ROOT_DIR)             # "...\Syneron-Candela Korea - Operation"
WD_DIR         = os.path.join(_OPERATION_DIR, "기타")
WD_MONTH_COL   = {m: chr(ord("C") + m - 1) for m in range(1, 13)}  # 1->C ... 12->N
WD_DUTY_ROW    = 2   # Customs Clearance (Duty) = 관세
WD_TAX_ROW     = 3   # Customs Clearance (Tax)  = 부가세

# ── 메일 고정 정보 (금액/기한 외에 바꿀 일 거의 없는 값) ─────────
TO_NAME      = "전은평 주임"
TO_EMAIL     = "eunpyeongc@candelamedical.com"  # 받는사람 주소
CC_EMAIL     = "younjinl@candelamedical.com; kates@candelamedical.com; miaej@candelamedical.com"  # 참조(CC)
SUBJECT      = "인천관세법인 납부할 관세/부가세 비용처리 요청"
COST_PURPOSE = "관세 및 부가세"
PAY_DATE     = "2차 지급"
PAY_METHOD   = "계좌 변동 없음"
ATTACHMENT   = "영수증서"
AGENCY       = "인천관세법인"


# ── 로깅 ─────────────────────────────────────────────────────────
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _subject_matches(subject):
    """공백/대소문자 무시하고 키워드 포함 또는 NT 시작 여부 판단."""
    norm = re.sub(r"\s+", "", (subject or "")).upper()
    kw   = re.sub(r"\s+", "", SUBJECT_KEYWORD).upper()
    return (kw in norm) or norm.startswith("NT")


# ── 처리 기록(중복 방지) ─────────────────────────────────────────
def load_processed():
    """이미 처리한 메일 EntryID 집합을 반환."""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f).get("processed_ids", []))
    except Exception:
        return set()


def mark_processed(entry_id, subject="", received=""):
    """메일 EntryID를 처리 완료로 기록."""
    if not entry_id:
        return
    data = {"processed_ids": [], "log": []}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        pass

    ids = data.get("processed_ids", [])
    if entry_id not in ids:
        ids.append(entry_id)
    data["processed_ids"] = ids[-200:]  # 최근 200건만 유지

    hist = data.get("log", [])
    hist.append({
        "entry_id": entry_id,
        "subject": subject,
        "received": received,
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    data["log"] = hist[-200:]

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"[경고] 상태 파일 저장 실패: {e}")


# ── Outlook: 받은편지함에서 최신 고지서 PDF 수집 ─────────────────
def fetch_latest_notice_pdf(save_dir, processed):
    """
    Outlook 받은 편지함에서 아직 처리하지 않은 '월별 납부 고지서' 메일을 최신순으로
    찾아 NT*.pdf 첨부를 저장. (pdf_path, entry_id, subject, received) 반환.
    신규 메일이 없으면 None.
    """
    import win32com.client  # pywin32

    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")

    inbox = _resolve_inbox(ns, MAILBOX)
    if inbox is None:
        raise RuntimeError(f"받은 편지함을 찾지 못했습니다: {MAILBOX}")

    items = inbox.Items
    try:
        items.Sort("[ReceivedTime]", True)  # 최신순
    except Exception:
        pass

    os.makedirs(save_dir, exist_ok=True)

    scanned = 0
    for item in items:
        scanned += 1
        if scanned > SCAN_LIMIT:
            break
        try:
            if item.Class != 43:  # olMail
                continue
        except Exception:
            continue

        subject = (getattr(item, "Subject", "") or "")
        if not _subject_matches(subject):
            continue

        # 이미 처리한 메일은 건너뜀 (중복 방지)
        try:
            entry_id = item.EntryID
        except Exception:
            entry_id = None
        if entry_id and entry_id in processed:
            continue

        pdf_path = _save_nt_pdf(item, save_dir)
        if pdf_path:
            recv = str(getattr(item, "ReceivedTime", ""))
            log(f"신규 고지서 발견: '{subject}' (수신 {recv}) -> {os.path.basename(pdf_path)}")
            return pdf_path, entry_id, subject, recv

    return None


def _resolve_inbox(ns, mailbox):
    """검색할 폴더를 반환. TARGET_FOLDER_NAME 이 있으면 그 이름의 폴더를 우선 탐색."""
    # 1) 폴더 이름으로 직접 탐색 (가장 우선)
    if TARGET_FOLDER_NAME:
        # 먼저 해당 계정 스토어 안에서, 없으면 전체에서
        store = _find_store_root(ns, mailbox)
        hit = None
        if store is not None:
            hit = _search_subtree(store, TARGET_FOLDER_NAME)
        if hit is None:
            hit = _find_folder_by_name(ns, TARGET_FOLDER_NAME)
        if hit is not None:
            return hit
        log(f"[경고] '{TARGET_FOLDER_NAME}' 폴더를 못 찾아 받은편지함으로 대체합니다.")

    # 2) 받은편지함( + INBOX_SUBFOLDER_PATH ) 방식
    target = (mailbox or "").strip().lower()
    inbox = None
    if target:
        try:
            for f in ns.Folders:
                name = (getattr(f, "Name", "") or "").lower()
                if target in name or name in target:
                    sub = _find_inbox_under(f)
                    if sub is not None:
                        inbox = sub
                        break
        except Exception:
            pass
    if inbox is None:
        try:
            inbox = ns.GetDefaultFolder(6)
        except Exception:
            return None
    return _descend_subfolder(inbox, INBOX_SUBFOLDER_PATH)


def _find_store_root(ns, mailbox):
    """mailbox 계정의 최상위 스토어 폴더를 반환."""
    target = (mailbox or "").strip().lower()
    if not target:
        return None
    try:
        for f in ns.Folders:
            name = (getattr(f, "Name", "") or "").lower()
            if target in name or name in target:
                return f
    except Exception:
        pass
    return None


def _search_subtree(root, folder_name):
    """root 하위 전체에서 이름이 일치하는 폴더를 BFS 로 탐색."""
    want = (folder_name or "").strip().lower()
    stack = [root]
    while stack:
        f = stack.pop()
        try:
            if (getattr(f, "Name", "") or "").strip().lower() == want and f is not root:
                return f
        except Exception:
            pass
        try:
            for sub in f.Folders:
                stack.append(sub)
        except Exception:
            pass
    # root 자신이 그 이름이면 root 반환
    try:
        if (getattr(root, "Name", "") or "").strip().lower() == want:
            return root
    except Exception:
        pass
    return None


def _find_folder_by_name(ns, folder_name):
    """모든 스토어를 통틀어 이름이 일치하는 폴더를 탐색."""
    try:
        for store in ns.Folders:
            hit = _search_subtree(store, folder_name)
            if hit is not None:
                return hit
    except Exception:
        pass
    return None


def _descend_subfolder(folder, path):
    for name in (path or []):
        try:
            folder = folder.Folders[name]
        except Exception:
            log(f"[경고] 하위 폴더 '{name}'를 찾지 못해 상위 폴더에서 검색합니다.")
            break
    return folder


def _find_inbox_under(store_folder):
    for nm in INBOX_NAMES:
        try:
            return store_folder.Folders[nm]
        except Exception:
            continue
    return None


def _save_nt_pdf(mail_item, save_dir):
    """메일 첨부 중 NT 로 시작하는 PDF를 저장하고 경로 반환. (없으면 일반 PDF 폴백)"""
    fallback = None
    try:
        attachments = mail_item.Attachments
    except Exception:
        return None

    for att in attachments:
        fn = os.path.basename(getattr(att, "FileName", "") or "")
        if not fn.lower().endswith(".pdf"):
            continue
        dest = os.path.join(save_dir, fn)
        if fn.upper().startswith(ATTACH_PREFIX.upper()):
            att.SaveAsFile(dest)
            return dest
        if fallback is None:
            fallback = (att, dest)

    if fallback is not None:
        att, dest = fallback
        att.SaveAsFile(dest)
        return dest
    return None


# ── 금액 추출 ────────────────────────────────────────────────────
def _to_int(num_str):
    return int(num_str.replace(",", ""))


def extract_amounts(pdf_path):
    """
    합계 행(모든 토큰이 숫자, 마지막=나머지 합)을 찾아
    관세=첫번째, 부가세=두번째, 계=마지막 으로 추출.
    """
    candidates = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                tokens = line.split()
                if len(tokens) < 3:
                    continue
                if not all(re.fullmatch(r"[\d,]+", t) for t in tokens):
                    continue
                nums = [_to_int(t) for t in tokens]
                if nums[-1] == sum(nums[:-1]) and nums[-1] > 0:
                    candidates.append(nums)

    if not candidates:
        raise ValueError("합계 행을 찾지 못했습니다. PDF 형식이 예상과 다를 수 있어요.")

    nums = max(candidates, key=lambda r: r[-1])
    return {
        "customs": nums[0],
        "vat":     nums[1],
        "total":   nums[-1],
        "others":  nums[2:-1],
    }


def extract_due_date(pdf_path):
    """'납부기한 2026년06월30일' 형태를 찾아 date 반환. 못 찾으면 None."""
    pat = re.compile(r"납부기한\s*(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            m = pat.search(text.replace(" ", "")) or pat.search(text)
            if m:
                try:
                    return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                except ValueError:
                    continue
    return None


def extract_issue_date(pdf_path):
    """발행일 date 반환. 파일명(NT+YYYYMMDD) 우선, 실패 시 PDF 본문 라벨로 폴백. 못 찾으면 None."""
    # 1) 파일명에서 NT + YYYYMMDD (가장 확실)
    base = os.path.basename(pdf_path)
    m = re.search(r"NT\D*(\d{4})(\d{2})(\d{2})", base, re.IGNORECASE)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass

    # 2) 본문 라벨 기반 (폴백) — 라벨이 한글이라 추출이 깨질 수 있어 보조 수단
    labels = "|".join(re.escape(lb) for lb in ISSUE_DATE_LABELS)
    pat_kr  = re.compile(rf"(?:{labels})\D{{0,6}}(\d{{4}})\s*년\s*(\d{{1,2}})\s*월\s*(\d{{1,2}})\s*일")
    pat_sep = re.compile(rf"(?:{labels})\D{{0,6}}(\d{{4}})[.\-/](\d{{1,2}})[.\-/](\d{{1,2}})")
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            raw = page.extract_text() or ""
            for text in (raw, raw.replace(" ", "")):
                for pat in (pat_kr, pat_sep):
                    mm = pat.search(text)
                    if mm:
                        try:
                            return date(int(mm.group(1)), int(mm.group(2)), int(mm.group(3)))
                        except ValueError:
                            continue
    return None


def _parse_recv_date(recv):
    """Outlook ReceivedTime 문자열에서 YYYY-MM-DD 를 뽑아 date 반환. 실패 시 None."""
    if not recv:
        return None
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", str(recv))
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def _effective_due(due_date):
    """납부기한 date 반환. 없으면 이번 달 말일로 폴백."""
    if due_date is None:
        today = date.today()
        last_day = calendar.monthrange(today.year, today.month)[1]
        return date(today.year, today.month, last_day)
    return due_date


def deadline_phrase(due_date):
    """'6월 30일 이전' (로그용)."""
    d = _effective_due(due_date)
    return f"{d.month}월 {d.day}일 이전"


def due_date_str(due_date):
    """'6월 30일' (날짜만)."""
    d = _effective_due(due_date)
    return f"{d.month}월 {d.day}일"


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


# ── W&D Cost 파일 자동 반영 ──────────────────────────────────────
def update_wd_cost_duty_tax(year, month, customs, vat):
    """W&D Cost_Korea_{year}.xlsx Summary 시트의 관세(2행)/부가세(3행) 칸을 채운다.
    wd_cost_monthly_updater.py의 update_workbook()과 동일하게 복사->편집->되돌리기
    방식으로 OneDrive 파일 락을 피하고, 실패해도 예외를 던지지 않고 로그만 남긴다."""
    xlsx_path = os.path.join(WD_DIR, f"W&D Cost_Korea_{year}.xlsx")
    if not os.path.exists(xlsx_path):
        log(f"[W&D] [오류] 파일 없음: {xlsx_path}")
        return False
    if month not in WD_MONTH_COL:
        log(f"[W&D] [오류] 잘못된 월: {month}")
        return False

    tmp_dir = os.path.join(_script_dir(), "_wd_cost_tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    tmp_copy = os.path.join(tmp_dir, f"WD_{year}_dutytax_work.xlsx")
    backup_path = os.path.join(
        WD_DIR, f"W&D Cost_Korea_{year}_backup_{datetime.now().strftime('%Y%m%d')}.xlsx"
    )

    try:
        shutil.copy2(xlsx_path, tmp_copy)
    except PermissionError:
        log("[W&D] [대기] 원본 파일을 읽을 수 없습니다(엑셀에서 열려 있을 수 있음). "
            "관세/부가세 자동 반영을 건너뜁니다 — 수동으로 반영해주세요.")
        return False
    except Exception as e:
        log(f"[W&D] [오류] 원본 복사 실패: {e}")
        return False

    if not os.path.exists(backup_path):
        try:
            shutil.copy2(xlsx_path, backup_path)
            log(f"[W&D] [백업] {os.path.basename(backup_path)} 생성")
        except Exception as e:
            log(f"[W&D] [경고] 백업 생성 실패(계속 진행): {e}")

    col = WD_MONTH_COL[month]
    changed = []
    try:
        wb = openpyxl.load_workbook(tmp_copy)
        ws = wb["Summary"]
        for row, value, label in (
            (WD_DUTY_ROW, customs, "관세"),
            (WD_TAX_ROW, vat, "부가세"),
        ):
            coord = f"{col}{row}"
            before = ws[coord].value
            if before == value:
                continue
            ws[coord] = value
            changed.append((coord, before, value, label))
        wb.save(tmp_copy)
    except Exception as e:
        log(f"[W&D] [오류] 엑셀 편집 실패: {e}")
        return False

    if not changed:
        log(f"[W&D] [확인] {year}-{month:02d}: 관세/부가세 값이 기존 시트와 이미 동일 — 변경 없음.")
        return True

    try:
        shutil.copy2(tmp_copy, xlsx_path)
    except PermissionError:
        log("[W&D] [대기] 원본 파일이 열려 있어 저장하지 못했습니다. 수동으로 반영해주세요.")
        return False
    except Exception as e:
        log(f"[W&D] [오류] 원본 덮어쓰기 실패: {e}")
        return False

    for coord, before, after, label in changed:
        log(f"[W&D] [반영] {coord}: {before!r} -> {after:,} ({label})")
    return True


# ── 메일 본문 생성 ───────────────────────────────────────────────
def build_email_body(amounts, due_date=None):
    customs = amounts["customs"]
    vat     = amounts["vat"]
    due_str = due_date_str(due_date)

    return (
        f"안녕하세요 {TO_NAME}님.\n"
        f"\n"
        f"{AGENCY} 현재 납부할 내역 확인 후 첨부 드리니 비용처리 부탁드립니다.\n"
        f"\n"
        f"1. 비용목적 : {COST_PURPOSE}\n"
        f"2. 지급금액 :\n"
        f"관세 : {customs:,}\n"
        f"부가세 : {vat:,}\n"
        f"3. 지급날짜 : {due_str}\n"
        f"4. 지급방법 : {PAY_METHOD}\n"
        f"5. 첨부파일 : {ATTACHMENT}\n"
        f"\n"
        f"감사합니다."
    )


# ── Outlook 메일 작성 ────────────────────────────────────────────
def create_outlook_mail(subject, body, attachment_path=None, to_email="", cc_email="", action="save"):
    """
    action: 'save'=초안(Drafts) 저장(검토 후 직접 발송) / 'display'=작성 창을 띄움
    ※ 자동 발송은 비활성화됨. 'send'가 들어와도 초안 저장으로 처리한다.
      (메일은 항상 작성까지만 하고, 검토 후 사용자가 직접 발송)
    """
    import win32com.client  # pywin32
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)  # olMailItem
    if to_email:
        mail.To = to_email
    if cc_email:
        mail.CC = cc_email
    mail.Subject = subject
    mail.HTMLBody = mail_text_to_html(body)
    if attachment_path and os.path.exists(attachment_path):
        mail.Attachments.Add(os.path.abspath(attachment_path))

    if action == "send":
        # 자동 발송 차단: 발송 대신 초안으로 저장한다.
        log("[알림] 자동 발송은 비활성화되어 있습니다 → 초안(Drafts)으로 저장합니다.")
        mail.Save()
        return "save"
    elif action == "display":
        mail.Display()  # 작성 창을 띄움
    else:  # save
        mail.Save()  # Drafts 폴더에 저장 (무인 실행에 적합)
    return action


# ── 진단 모드 ────────────────────────────────────────────────────
def diagnose():
    """받은편지함에서 매칭되는 메일을 점검만 한다. (발송/기록 없음)"""
    log(f"pdfplumber 버전: {getattr(pdfplumber, '__version__', '?')}")
    log(f"상태 파일: {STATE_FILE}")
    log(f"저장 폴더: {SAVE_DIR}")
    log(f"키워드: '{SUBJECT_KEYWORD}' / 첨부 접두어: '{ATTACH_PREFIX}'")

    try:
        import win32com.client
    except Exception:
        log("[오류] pywin32 가 필요합니다: pip install pywin32")
        return

    try:
        outlook = win32com.client.Dispatch("Outlook.Application")
        ns = outlook.GetNamespace("MAPI")
    except Exception as e:
        log(f"[오류] Outlook 연결 실패: {e}")
        return

    inbox = _resolve_inbox(ns, MAILBOX)
    if inbox is None:
        log(f"[진단] 받은편지함을 못 찾았습니다: {MAILBOX}")
        return
    try:
        log(f"[진단] 사용 중인 받은편지함: {inbox.FolderPath}")
    except Exception:
        log(f"[진단] 사용 중인 받은편지함: {getattr(inbox, 'Name', '?')}")

    items = inbox.Items
    try:
        items.Sort("[ReceivedTime]", True)
    except Exception:
        pass

    processed = load_processed()
    log(f"[진단] 처리완료로 기록된 메일 수: {len(processed)}")

    scanned, matched = 0, 0
    for item in items:
        scanned += 1
        if scanned > SCAN_LIMIT:
            break
        try:
            if item.Class != 43:
                continue
        except Exception:
            continue

        subject = (getattr(item, "Subject", "") or "")
        if not _subject_matches(subject):
            continue

        matched += 1
        try:
            eid = item.EntryID
        except Exception:
            eid = None
        status = "이미처리(건너뜀)" if (eid and eid in processed) else "신규(처리대상)"

        names, has_nt = [], False
        try:
            for att in item.Attachments:
                fn = getattr(att, "FileName", "") or ""
                names.append(fn)
                if fn.lower().endswith(".pdf") and fn.upper().startswith(ATTACH_PREFIX.upper()):
                    has_nt = True
        except Exception:
            pass

        recv = getattr(item, "ReceivedTime", "")
        log(f"  [{matched}] {status} | 제목='{subject}' | 수신={recv} | "
            f"NT첨부={'있음' if has_nt else '없음'} | 첨부목록={names}")
        if matched >= 10:
            log("  (매칭 메일 10건까지만 표시)")
            break

    if matched == 0:
        log(f"[진단] 스캔 {scanned}건 중 매칭되는 메일 없음. "
            f"제목에 '{SUBJECT_KEYWORD}' 포함 또는 'NT' 시작인 메일이 받은편지함에 있는지 확인하세요.")
    else:
        log(f"[진단] 매칭 {matched}건. '신규(처리대상)'이 하나도 없으면 "
            f"이미 처리되어 발송되지 않습니다. (재발송하려면 상태 파일 삭제)")


# ── 메인 ─────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="월별 납부 고지서 -> 비용처리 메일 생성")
    parser.add_argument("pdf", nargs="?", help="직접 지정할 PDF 경로 (생략 시 Outlook에서 수집)")
    parser.add_argument("--display", action="store_true",
                        help="초안 저장 대신 작성 창을 띄움")
    parser.add_argument("--send", action="store_true",
                        help="(비활성화됨) 자동 발송하지 않고 초안으로 저장")
    parser.add_argument("--dry", action="store_true",
                        help="진단: 받은편지함 매칭 메일만 점검 (발송/기록 안 함)")
    args = parser.parse_args()

    if args.dry:
        diagnose()
        return

    action = "send" if args.send else ("display" if args.display else "save")

    entry_id, subj, recv = None, "", ""

    # 1) PDF 확보: 직접 지정 or Outlook 수집
    if args.pdf:
        pdf_path = args.pdf
        if not os.path.exists(pdf_path):
            log(f"[오류] 파일 없음: {pdf_path}")
            sys.exit(1)
    else:
        processed = load_processed()
        try:
            result = fetch_latest_notice_pdf(SAVE_DIR, processed)
        except ImportError:
            log("[오류] pywin32 가 필요합니다: pip install pywin32")
            sys.exit(1)
        except Exception as e:
            log(f"[오류] Outlook 수집 실패: {e}")
            sys.exit(1)
        if not result:
            log("[알림] 처리할 신규 '월별 납부 고지서' 메일이 없습니다. "
                "(이미 처리했거나 미수신) 종료.")
            sys.exit(0)
        pdf_path, entry_id, subj, recv = result

    # 1.5) 발행월 검사 (Outlook 자동 수집 건만)
    #      발행월이 지났으면(다음 달 이후) 메일을 만들지 않고 건너뛴다. 고지서는 해당 월에만 발송.
    #      발행일을 못 찾으면 메일 수신일로 폴백한다.
    if not args.pdf:
        issue_date = extract_issue_date(pdf_path)
        ref_date   = issue_date or _parse_recv_date(recv)
        ref_kind   = "발행일" if issue_date else ("수신일" if ref_date else None)
        if ref_date is not None:
            today = date.today()
            cur_ym = (today.year, today.month)
            ref_ym = (ref_date.year, ref_date.month)
            if cur_ym > ref_ym:  # 발행월이 이미 지남
                log(f"[건너뜀] {ref_kind} {ref_date} (발행월 {ref_ym[0]}-{ref_ym[1]:02d})이 지났습니다. "
                    f"현재 {cur_ym[0]}-{cur_ym[1]:02d}. 해당 월에만 발송하므로 메일을 만들지 않습니다.")
                # 다음 실행 때 같은 메일이 또 최신으로 잡히지 않도록 처리완료로 기록
                if entry_id:
                    mark_processed(entry_id, subj, recv)
                    log("[기록] 이 메일은 처리완료로 저장했습니다. (다음 실행 시 건너뜀)")
                sys.exit(0)
            else:
                log(f"[확인] {ref_kind} {ref_date} (발행월 {ref_ym[0]}-{ref_ym[1]:02d}). "
                    f"현재 발행월 내 -> 처리 진행.")
        else:
            log("[알림] 발행일·수신일을 모두 확인하지 못해 발행월 검사를 건너뜁니다. (그대로 진행)")

    # 2) 파싱
    try:
        amounts = extract_amounts(pdf_path)
    except Exception as e:
        log(f"[오류] 금액 추출 실패: {e}")
        sys.exit(1)

    due_date = extract_due_date(pdf_path)

    chk = amounts["customs"] + amounts["vat"] + sum(amounts["others"])
    if chk != amounts["total"]:
        log(f"[경고] 합계 검증 불일치: 관세+부가세+기타={chk:,} / 계={amounts['total']:,}")

    # 2.5) W&D Cost 파일에 관세/부가세 자동 반영 (2026-08-31 사용자 요청)
    #      고지서 '발행월' 컬럼에 채운다. 6월/7월 실측 확인: 발행(수신)월 = 그 달 컬럼.
    #      메일 작성이 실패하더라도 이 반영은 별도로 시도한다.
    issue_date_for_wd = extract_issue_date(pdf_path) or _parse_recv_date(recv) or date.today()
    try:
        update_wd_cost_duty_tax(issue_date_for_wd.year, issue_date_for_wd.month,
                                 amounts["customs"], amounts["vat"])
    except Exception as e:
        log(f"[W&D] [오류] 관세/부가세 반영 중 예외: {e}")

    body = build_email_body(amounts, due_date=due_date)

    log(f"관세={amounts['customs']:,} / 부가세={amounts['vat']:,} / 계={amounts['total']:,} "
        f"/ 납부기한={deadline_phrase(due_date)}"
        f"{'' if due_date else ' (PDF 미검출, 이번달 말일 대체)'}")

    # 3) Outlook 메일 작성
    try:
        done = create_outlook_mail(SUBJECT, body, attachment_path=pdf_path,
                                   to_email=TO_EMAIL, cc_email=CC_EMAIL, action=action)
        msg = {"save": "초안(Drafts)으로 저장", "display": "작성 창을 띄움",
               "send": "초안(Drafts)으로 저장"}[done]
        log(f"[완료] {msg} 했습니다.")
        # 처리한 메일 기록 -> 다음 실행부터 중복 처리 안 함
        if entry_id:
            mark_processed(entry_id, subj, recv)
            log("[기록] 이 메일은 처리 완료로 저장했습니다. (다음 실행 시 건너뜀)")
    except ImportError:
        log("[오류] pywin32 가 필요합니다: pip install pywin32")
        print("\n----- 메일 본문 (수동 복사용) -----\n")
        print(body)
        sys.exit(1)
    except Exception as e:
        log(f"[오류] Outlook 메일 작성 실패: {e}")
        print("\n----- 메일 본문 (수동 복사용) -----\n")
        print(body)
        sys.exit(1)


if __name__ == "__main__":
    main()
