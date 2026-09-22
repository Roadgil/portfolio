# -*- coding: utf-8 -*-
"""월마감 선출고 요청 메일을 **초안으로만** 저장한다(발송하지 않음).

  제목  : 원본 제목 + " - {택배|퀵} 선출고 {M}월 {D}일"
  받는이: 혜준대리님 + 용마로지스 김기훈/유용호
  본문  : 기훈님 용호님,
          선출고 요청서로 {택배|퀵} 발송 부탁드립니다.
  첨부  : 거래명세서 PDF, 선출고요청서 PDF

본문 문구는 2026-08-27 사용자 지정. 보현과장님 원본에 있던 "오더 미승인으로
{병원} {품목}은 첨부의 거래명세서 및 ~"는 쓰지 않고 위 한 줄로만 간다.

발송은 사용자가 초안을 눈으로 확인한 뒤 직접 누른다(사용자 지시, 2026-08-27).
"""
import argparse
import json
import os
import re

import win32com.client

YONGMA_TO = ("김기훈 <y7221063@yongmalogis.co.kr>; "
             "용호 유 <y7225055@yongmalogis.co.kr>")
HAEJOON = "haejoonk@candelamedical.com"

MAIL_FONT_CSS = "font-family:'맑은 고딕',Malgun Gothic,sans-serif;font-size:10pt;"


def _prepend_html_text(reply, text):
    """원본 인용부 서식을 보존하려면 Body에 대입하면 안 되고 HTMLBody의 <body>
    바로 뒤에 끼워 넣어야 한다(pick_release_watcher와 같은 방식)."""
    import html as html_module
    html_body = reply.HTMLBody or ""
    content = html_module.escape(text).replace("\n", "<br>")
    wrapped = f'<div style="{MAIL_FONT_CSS}">{content}</div>'
    m = re.search(r"(<body[^>]*>)", html_body, re.IGNORECASE)
    if m:
        at = m.end()
        reply.HTMLBody = html_body[:at] + wrapped + html_body[at:]
    else:
        reply.HTMLBody = wrapped + html_body


def build_draft(entry_id, ship, month, day, attachments,
                signature_name="채윤길"):
    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    mail = ns.GetItemFromID(entry_id)

    original_subject = str(mail.Subject or "")
    print("원본 제목:", original_subject)

    reply = mail.Reply()
    reply.To = f"{HAEJOON}; {YONGMA_TO}"
    reply.CC = ""
    reply.BCC = ""

    base = re.sub(r"^(RE|FW|Re|Fw):\s*", "", original_subject).strip()
    reply.Subject = f"Re: {base} - {ship} 선출고 {month}월 {day}일"

    body = (
        f"기훈님 용호님,\n\n"
        f"선출고 요청서로 {ship} 발송 부탁드립니다.\n\n"
        f"감사합니다.\n{signature_name} 드림\n"
    )
    _prepend_html_text(reply, body)

    # 원본에 딸려온 서명 이미지 등은 떼고, 우리 문서 2종만 붙인다.
    for idx in range(reply.Attachments.Count, 0, -1):
        try:
            reply.Attachments.Item(idx).Delete()
        except Exception:
            pass
    for path in attachments:
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        reply.Attachments.Add(path)

    reply.Save()   # ★ 발송하지 않고 초안으로만 저장
    return {
        "subject": reply.Subject,
        "to": reply.To,
        "attachments": [os.path.basename(a) for a in attachments],
        "body_preview": body,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True,
                    help="make_preship_docs와 같은 spec + entry_id 포함")
    args = ap.parse_args()

    spec = json.load(open(args.spec, encoding="utf-8"))
    date = spec["date"]                      # YYYY-MM-DD
    y, m, d = (int(x) for x in date.split("-"))

    out = build_draft(
        entry_id=spec["entry_id"],
        ship=spec.get("ship", "택배"),
        month=m, day=d,
        attachments=[spec["transaction_pdf"], spec["preship_pdf"]],
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print("\n초안으로 저장했습니다. Outlook 초안함에서 확인 후 직접 발송해주세요.")


if __name__ == "__main__":
    main()
