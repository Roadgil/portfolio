# -*- coding: utf-8 -*-
"""승인 완료된 Parts Order만 골라 오라클 전송 -> 릴리즈 -> 완료메일까지 처리한다.

승인 여부는 CK service team 폴더의 알림 메일(제목에 PO 번호)로 판단한다.
Send To Approval은 절대 누르지 않는다.

  python run_approved.py            -> 대상만 보여주고 끝(미리보기)
  python run_approved.py --go       -> 실제 실행
  python run_approved.py --go 00600290 00600311   -> 지정한 PO만
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

import po_finish
from sf_actions import get_sf_page

BASE = os.path.dirname(os.path.abspath(__file__))
RESULT = os.path.join(BASE, "batch_result.json")
DEBUG_PORT = 9222


def load_pending():
    """앱의 대기 목록과 같은 기준으로 고른다.

    track 플래그가 정식 기준이고, 그 전에 만든 건은 옛 note 문구로 걸러낸다.
    앱(파트오더앱.py)만 고치고 여기를 안 고쳐서, 새로 만든 건이 이 스크립트에선
    통째로 안 보였다(2026-09-03 00601290 - "승인 완료 0건"으로만 나왔다).
    """
    res = json.load(open(RESULT, encoding="utf-8"))
    return [c for c in res.get("created", [])
            if not c.get("cancelled")
            and (c.get("track") == "part_order"
                 or "릴리즈 대기" in (c.get("note") or "")
                 or "Send to Approval 미클릭" in (c.get("note") or ""))]


def main():
    go = "--go" in sys.argv
    only = {a for a in sys.argv[1:] if a.isdigit()}

    pend = load_pending()
    appr = po_finish.scan_approval_mails(days=14, log=print)

    targets = []
    for c in pend:
        po = str(c.get("parts_order_number") or "")
        if only and po not in only:
            continue
        if po in appr:
            targets.append(c)

    print(f"\n대기 {len(pend)}건 / 승인 완료 {len(targets)}건")
    for c in targets:
        preship = "선출고" in (c.get("note") or "")
        print(f"  {c['parts_order_number']}  {c['hospital']:22s} "
              f"{'[선출고]' if preship else '[평상시]'} "
              f"{'메일있음' if c.get('entry_id') else '메일없음(문자접수)'}")

    if not go:
        print("\n(미리보기입니다. 실제 실행은 --go)")
        return

    results = []
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
        ctx = browser.contexts[0]
        get_sf_page(ctx)
        page = ctx.new_page()

        for c in targets:
            po = str(c["parts_order_number"])
            hosp = c.get("hospital")
            preship = "선출고" in (c.get("note") or "")
            out = {"po": po, "hospital": hosp, "preship": preship}
            print("\n" + "=" * 72)
            print(f"[{po}] {hosp} {'(선출고)' if preship else '(평상시)'}")

            # ① 오라클 전송
            out["trigger"] = po_finish.trigger_interface(page, c["parts_order_url"], print)
            if out["trigger"].get("status") not in ("success", "already_success"):
                print(f"  -> 중단: {out['trigger'].get('status')}")
                results.append(out)
                continue

            # ② 릴리즈 - 소모품이 섞이면 SP가 먼저 돌도록 kind를 바꾼다
            kind = po_finish.decide_kind(c.get("product_code"))
            out["kind"] = kind
            print(f"  품번 {c.get('product_code')} -> kind={kind}")
            out["release"] = po_finish.release_order(po, f"{hosp} {po}", kind, print)
            if out["release"].get("status") not in ("released", "already_released"):
                print(f"  -> 중단: {out['release'].get('status')}")
                results.append(out)
                continue

            # ③ 완료메일
            dup = po_finish.already_sent_completion(po)
            if dup:
                out["mail"] = {"status": "skipped_dup", "hits": dup}
                print(f"  -> 완료메일 이미 발송됨: {dup}")
                results.append(out)
                continue
            eid = c.get("entry_id")
            if eid:
                out["mail"] = po_finish.send_completion_mail(
                    eid, po, print, send=True, preship=preship)
            else:
                # 문자로 접수돼 원본 메일이 없는 건도 완료메일은 보내야 한다
                # (2026-09-01 사용자 지시) - 답장 대신 새 메일로 발송한다.
                out["mail"] = po_finish.send_completion_mail_new(
                    hosp, po, item_label="", log=print, send=True, preship=preship)
            results.append(out)

        page.close()

    print("\n" + "=" * 72)
    print("요약")
    for r in results:
        print(f"  {r['po']} {r['hospital'][:18]:20s} "
              f"전송={r.get('trigger', {}).get('status')} "
              f"릴리즈={r.get('release', {}).get('status')} "
              f"메일={r.get('mail', {}).get('status')}")
    json.dump(results, open(os.path.join(BASE, "run_approved_result.json"),
                            "w", encoding="utf-8"), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
