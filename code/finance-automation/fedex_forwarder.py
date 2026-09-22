#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FedEx Invoice Auto-Forwarder
=============================
'FedEx Billing Online 새 청구서 첨부' 메일에서 FedEx 항공 운송료 인보이스 PDF를
찾아, DHL과 동일하게 재무팀(전은평 주임님) 앞 비용처리 요청 메일 초안을 자동
생성한다. (자동 발송하지 않고 임시보관함(Drafts)에 저장 — 검토 후 직접 발송)

메일 출처: Inbox > FedEx 폴더 — FedEx Billing Online이 noreply@fedex.com 으로
직접 보낸다(제목 '[External] FedEx Billing Online 새 청구서 첨부').
예전엔 Miae Jang(miaej@candelamedical.com)이 사내로 전달(FW:)해줬으나,
2026-09-19부터 FedEx Billing Online이 이 주소로 직접 보내는 방식으로 바뀌었고
2026-09-21 사용자가 "이제 Miae Jang으로는 안 온다"고 확인해줘서 그 경로는 제거함.

2026-09-15 신규 추가 (사용자 요청: "DHL이랑 마찬가지로 처리해줘").
처음엔 DHL SELR과 동일하게 발견 즉시 초안 1통을 만들도록 했으나, 같은 날
사용자가 "SELR/FedEx도 D*.pdf처럼 발송일(D-2) 배치 로직으로 통일해달라"고
요청해 Phase1(발견→pending 적재)/Phase2(발송일 도래분 일괄 초안) 구조로 다시
바꿈. '지급날짜'(1차/2차) 문구와 발송일 계산은 dhl_forwarder.assign_round()를
그대로 재사용한다 — 같은 로직(Finance Calendar 앵커/윈도우/공휴일)을 이 파일에
복붙하면 두 파일이 따로 놀다 드리프트 나는 사고(과거 Oracle SSO 재로그인 로직
4중복 사고 참고)가 재발할 수 있어, dhl_forwarder.py를 수정하지 않고 import만
해서 쓴다.

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
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import pythoncom
import win32com.client

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

# dhl_forwarder.py 를 수정하지 않고 그대로 import 해서 재사용
# (지급 차수 계산 로직/본문 템플릿/공통 유틸 — 두 곳에 복붙하면 드리프트 위험).
from dhl_forwarder import (  # noqa: E402
    assign_round,
    mail_text_to_html,
    sanitize_filename,
    restrict_recent,
    get_sender_smtp,
    format_pay_date,
    _calendar_has_month,
    RECIPIENT_ADDRESS,
    CC_ADDRESS,
    PURPOSE_SELR,
)


# ============================================================
#                          설정
# ============================================================
# 감시 대상 발신자(소문자). FedEx Billing Online 이 직접 보내는 주소(2026-09-19~).
SENDER_ADDRESS        = "noreply@fedex.com"
SUBJECT_MUST_CONTAIN  = "fedex billing online"        # 소문자 비교
ATTACHMENT_EXT        = ".pdf"

# 파일명/제목에 아래 키워드가 있으면 청구서로 보지 않고 무시.
# (DHL 에서 '미수금 납부 촉구서'를 청구서로 오인해 전달한 사고가 있었음 — 같은
#  실수를 FedEx 에서도 미리 방지)
EXCLUDE_SUBJECT_KEYWORDS = ["미수금", "납부촉구", "촉구서", "독촉"]

# 메일 '발견' 검색 기간(일). 1 = 최근 24시간. (발견된 청구서는 pending 에 적재되어
# 발송일까지 보관되므로, 이 값은 '발견 시점' 한정.)
LOOKBACK_DAYS = 3

# True 로 두면 실제 초안 저장 없이 로그만 남깁니다(테스트용). 상태 파일도 갱신 안 함.
DRY_RUN = False

# 초안 저장(False, 기본/권장) vs 자동 발송(True). 금액 오인식 위험이 있으니
# 한동안 초안만 확인한 뒤 전환 권장 (DHL 과 동일 정책).
SEND_MODE = False

# 발송일(D-2) 당일 몇 시 이후부터 배치를 만들지 (DHL SEND_AT_HOUR 와 동일 개념).
# None = 시각 무시, D-2 당일 어느 실행에서든 즉시 생성.
SEND_AT_HOUR = None

# 해당 '월'의 Finance Calendar 가 캐시에 들어오기 전엔 그 달 배치를 보류(DHL 과 동일 정책).
REQUIRE_CALENDAR_MONTH = True

# 캘린더가 끝내 안 와도 발송일을 N일 초과하면 휴리스틱 날짜로 강제 발송. None = 강제 안 함.
FORCE_SEND_IF_OVERDUE_DAYS = None

SCRIPT_DIR = Path(__file__).resolve().parent
STATE_FILE = SCRIPT_DIR / "_fedex_forwarder_state.json"
LOG_FILE   = SCRIPT_DIR / "fedex_forwarder.log"
TEMP_DIR   = SCRIPT_DIR / "_temp_attachments"

SUBJECT_TEMPLATE_SINGLE = "[FedEx 비용청구] 미결제 청구서 전달 ({invoice})"
SUBJECT_TEMPLATE_BATCH  = "[FedEx 비용청구] 미결제 청구서 {count}건 일괄 전달 ({pay_round} 지급)"

# dhl_forwarder.BODY_TEMPLATE 은 "DHL 현재 납부할 내역..."으로 발신사가 하드코딩돼
# 있어 그대로 재사용하면 FedEx 건에도 'DHL'이라고 나가는 사고가 난다(2026-09-15
# 최초 테스트 때 발견). 본문만 자체 템플릿으로 따로 둔다.
BODY_TEMPLATE = """안녕하세요 전은평 주임님.

FedEx 현재 납부할 내역 확인 후 첨부 드리니 비용처리 부탁드립니다.

1. 비용목적 : {purpose}
2. 지급금액 : {amount}
3. 지급날짜 : {pay_date}
4. 지급방법 : 계좌 변동 없음
5. 첨부파일 : 정산서

감사합니다.

채윤길 드림"""


def build_body(invoice_amounts: list, pay_date, pay_round: str, purpose: str = PURPOSE_SELR) -> str:
    """dhl_forwarder.build_body() 와 동일한 금액 포맷 로직, 본문 발신사만 FedEx로 교체."""
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
            st.setdefault("pending", {})   # entry_id -> {"received": iso, "subject": str}
            st.setdefault("last_run", None)
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


# ============================================================
#                      PDF 파싱
# ============================================================
def _read_pdf_text(pdf_path: Path):
    """PDF 텍스트 추출. 실패 시 None. pdfplumber 1순위, 실패 시 pypdf."""
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            return "".join((pg.extract_text() or "") + "\n" for pg in pdf.pages)
    except ImportError:
        logging.info("pdfplumber 미설치 → pypdf 로 대체합니다. (pip install pdfplumber 권장)")
    except Exception as e:
        logging.warning(f"pdfplumber 추출 실패: {e} → pypdf 로 대체 시도")

    try:
        from pypdf import PdfReader
        return "".join((pg.extract_text() or "") + "\n" for pg in PdfReader(str(pdf_path)).pages)
    except Exception as e:
        logging.error(f"PDF 텍스트 추출 실패({pdf_path.name}): {e}")
        return None


def extract_fedex_invoice(pdf_path: Path):
    """
    FedEx 인보이스 PDF에서 (invoice_no, amount) 를 추출한다.
      · 금액   : 'Grand Total 총액 KRW 588,670.00' 앵커 — 요약란/입금확인증
                 두 곳에 같은 값이 반복 표기되므로 최빈값을 취한다(DHL 방식과 동일).
      · 청구서번호 : 'Invoice Number 청구서 번호  9-559-64903' 형식.
                     못 찾으면 파일명을 그대로 사용.
    """
    text = _read_pdf_text(pdf_path)
    if not text:
        return None, None

    amounts = []
    for m in re.finditer(r'Grand\s*Total\D*?KRW\s*([\d][\d,]*(?:\.\d+)?)', text, re.I | re.S):
        try:
            amounts.append(int(float(m.group(1).replace(",", ""))))
        except ValueError:
            pass
    amount = Counter(amounts).most_common(1)[0][0] if amounts else None

    inv_no = None
    m = re.search(r'Invoice\s*Number\D*?(\d[\d\-]{5,}\d)', text, re.I)
    if m:
        inv_no = m.group(1)

    return inv_no, amount


# ============================================================
#                     배치 초안 생성 (D-2 발송일 기준)
# ============================================================
def find_fedex_folder(namespace):
    inbox = namespace.GetDefaultFolder(6)  # 6 = olFolderInbox
    return inbox.Folders["FedEx"]


def build_fedex_batch_draft(outlook, namespace, rnd, entry_ids: list) -> bool:
    """rnd 차수에 배정된 entry_ids 들을 한 통의 초안으로 묶어 생성(DHL D*.pdf 배치와
    동일한 발송일(D-2) 기준). 각 메일을 EntryID 로 다시 열어 첨부 저장 + 금액 추출."""
    TEMP_DIR.mkdir(exist_ok=True)
    saved_paths = []
    invoice_amounts = []  # [(invoice_name, amount|None), ...]
    missing = []

    for eid in entry_ids:
        try:
            mail = namespace.GetItemFromID(eid)
        except Exception as e:
            logging.warning(f"  · 메일 재오픈 실패(EntryID={eid[:12]}…): {e}")
            missing.append(eid)
            continue

        try:
            attachments = list(mail.Attachments)
        except Exception as e:
            logging.warning(f"  · 첨부 확인 실패: {e}")
            attachments = []

        for att in attachments:
            fname = att.FileName or ""
            if not fname.lower().endswith(ATTACHMENT_EXT):
                continue  # image001.emz / image00N.png 등 인라인 이미지 제외
            try:
                safe_name = sanitize_filename(fname)
                pdf_path = TEMP_DIR / safe_name
                if pdf_path.exists():
                    pdf_path = TEMP_DIR / f"{pdf_path.stem}_{int(datetime.now().timestamp())}{pdf_path.suffix}"
                att.SaveAsFile(str(pdf_path))
                saved_paths.append(pdf_path)

                inv_no, amount = extract_fedex_invoice(pdf_path)
                inv_name = inv_no or Path(fname).stem
                invoice_amounts.append((inv_name, amount))
                logging.info(
                    f"  · FedEx 첨부: {pdf_path.name} | 청구서번호: {inv_name} | 금액: "
                    f"{format(amount, ',') + '원' if amount is not None else '추출 실패(확인 필요)'}"
                )
            except Exception as e:
                logging.warning(f"  · FedEx 첨부 저장 실패({fname}): {e}")

    if not invoice_amounts:
        logging.error("  · FedEx PDF 첨부를 하나도 확보하지 못해 초안을 만들지 않습니다.")
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
        build_body(invoice_amounts, rnd.pay_date, rnd.label, purpose=PURPOSE_SELR))
    for p in saved_paths:
        new_mail.Attachments.Add(str(p))

    if DRY_RUN:
        logging.info(f"[DRY_RUN] FedEx {'발송' if SEND_MODE else '초안'} 생략 — Subject={subject}")
        result = False
    elif SEND_MODE:
        new_mail.Send()
        logging.info(f"FedEx 자동 발송 완료 → Subject={subject}")
        result = True
    else:
        new_mail.Save()  # 자동 발송하지 않고 Drafts 에 한 통으로 저장
        logging.info(f"FedEx 초안 저장 완료(검토 후 직접 발송) → Subject={subject}")
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
    """발견 → pending 적재 → 발송일(D-2) 도래분 일괄 초안. 생성한 초안(배치) 수 반환."""
    pythoncom.CoInitialize()
    try:
        outlook   = win32com.client.Dispatch("Outlook.Application")
        namespace = outlook.GetNamespace("MAPI")
        folder    = find_fedex_folder(namespace)

        state = load_state()
        processed = set(state.get("processed_entry_ids", []))
        pending = dict(state.get("pending", {}))  # entry_id -> {"received","subject"}

        # ── Phase 1: 신규 청구서 발견 → pending 적재 (즉시 초안 X) ──
        items = folder.Items
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
            if not entry_id or entry_id in processed or entry_id in pending:
                continue

            if get_sender_smtp(mail) != SENDER_ADDRESS.lower():
                continue

            subject = getattr(mail, "Subject", "") or ""
            if SUBJECT_MUST_CONTAIN not in subject.lower():
                continue

            subject_flat = re.sub(r'\s+', '', subject)
            if any(kw and re.sub(r'\s+', '', kw) in subject_flat
                   for kw in EXCLUDE_SUBJECT_KEYWORDS):
                logging.info(f"제외 키워드 매칭 → 스킵(초안 미생성): {subject!r}")
                processed.add(entry_id)
                continue

            has_pdf = any((getattr(a, "FileName", "") or "").lower().endswith(ATTACHMENT_EXT)
                          for a in mail.Attachments)
            if not has_pdf:
                logging.info(f"조건 일치하나 PDF 첨부 없음 → 스킵: {subject!r}")
                processed.add(entry_id)
                continue

            rt = mail.ReceivedTime
            received_dt = datetime(rt.year, rt.month, rt.day, rt.hour, rt.minute, rt.second)
            rnd = assign_round(received_dt.date())
            pending[entry_id] = {
                "received": received_dt.isoformat(timespec="seconds"),
                "subject": subject,
            }
            logging.info(
                f"발견→대기 등록 [{received_dt:%Y-%m-%d %H:%M}] {subject!r} "
                f"→ {rnd.label} 배치 (발송예정 {rnd.send_date:%Y-%m-%d} / 앵커 {rnd.pay_date:%Y-%m-%d})"
            )

        # ── Phase 2: pending 을 차수별로 묶고, 발송일(D-2) 도래분 일괄 처리 ──
        now = datetime.now()
        today = now.date()
        groups: dict = {}  # key -> {"round": Round, "ids": [...]}
        for eid, meta in pending.items():
            try:
                r_date = datetime.fromisoformat(meta["received"]).date()
            except Exception:
                r_date = today
            rnd = assign_round(r_date)
            key = (rnd.pay_date.isoformat(), rnd.label)
            groups.setdefault(key, {"round": rnd, "ids": []})["ids"].append(eid)

        drafts_created = 0
        for _, g in sorted(groups.items(), key=lambda kv: kv[1]["round"].send_date):
            rnd, ids = g["round"], g["ids"]

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
                        f"대기(시각): {rnd.label} 배치 {len(ids)}건 — 오늘이 발송일(D-2)이나 "
                        f"{SEND_AT_HOUR}시 이전(현재 {now:%H:%M}). 그 이후 실행에서 처리."
                    )
                else:
                    logging.info(
                        f"대기 유지: {rnd.label} 배치 {len(ids)}건 "
                        f"— 발송 예정 {rnd.send_date:%Y-%m-%d}(D-2), 윈도우 끝 {rnd.window_end:%Y-%m-%d}(D-3)"
                    )
                continue

            # 캘린더 게이트: 해당 월 Finance Calendar 가 캐시에 있어야 앵커가 확정됨.
            cal_ok = (not REQUIRE_CALENDAR_MONTH) or _calendar_has_month(rnd.year, rnd.month)
            overdue_force = (
                FORCE_SEND_IF_OVERDUE_DAYS is not None
                and not cal_ok
                and (today - rnd.send_date).days >= FORCE_SEND_IF_OVERDUE_DAYS
            )
            if not cal_ok and not overdue_force:
                logging.info(
                    f"대기(캘린더): {rnd.label} 배치 {len(ids)}건 — "
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
                f"발송일 도래: {rnd.label} 배치 {len(ids)}건 "
                f"(발송일 {rnd.send_date:%Y-%m-%d} ≤ 오늘 {today:%Y-%m-%d}) → 일괄 {action}"
            )
            created = build_fedex_batch_draft(outlook, namespace, rnd, ids)
            if created and not DRY_RUN:
                for eid in ids:
                    pending.pop(eid, None)
                    processed.add(eid)
                drafts_created += 1

        if not DRY_RUN:
            state["processed_entry_ids"] = sorted(processed)
            state["pending"] = pending
            save_state(state)

        return drafts_created

    finally:
        pythoncom.CoUninitialize()


def main() -> int:
    setup_logging()
    logging.info("=" * 60)
    logging.info(f"FedEx Forwarder 시작 (LOOKBACK_DAYS={LOOKBACK_DAYS}, DRY_RUN={DRY_RUN})")
    try:
        n = process_mails()
        logging.info(f"FedEx Forwarder 종료. 생성한 초안 수: {n}")
        return 0
    except Exception:
        logging.error("처리 중 예외 발생:\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
