"""오늘자 신규 출고요청을 스캔하고, ready 건에 대해 ServiceMax에 Case+Parts
Order를 자동 생성한다 (Save까지 자동, 사람 확인 단계 없음).

- Location 검색결과가 정확히 1건인 건만 자동 진행, 그 외(0건/2건 이상)는
  건너뛰고 결과 리포트의 "location_review"에 남긴다.
- 한 건 처리 중 오류가 나도 나머지 건 처리는 계속한다 (건별 try/except).
- 결과는 batch_result.json에 저장한다.
"""

import json
import os
from datetime import datetime

from playwright.sync_api import sync_playwright

import scan_new_orders
from map_to_servicemax import map_record
from sf_actions import (
    get_sf_page,
    search_and_open_location,
    create_case_from_location,
    create_parts_order_from_case,
)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_PATH = os.path.join(SCRIPT_DIR, "batch_result.json")
DEBUG_PORT = 9222
HOME_URL = "https://candelamedical.my.salesforce.com/home/home.jsp"


def go_home(page):
    page.goto(HOME_URL)
    page.wait_for_load_state("networkidle", timeout=15000)


# map_record()의 warnings 중 자동 기본값으로 보정해서 진행해도 되는 "경미한" 경우만
# 여기 나열한다 - 그 외 경고(품목코드 못 찾음, 금액/수량 계산 불가 등)가 하나라도 남아있으면
# 무조건 생성하지 않고 needs_review로 넘긴다.
ORDER_CHANNEL_MISSING_WARNING = "주문접수Channel이 없어 Caller Last Name을 채울 수 없음"


def main(rescan=True):
    if rescan:
        print("1) Outlook 스캔 중...")
        scan_new_orders.main(lookback_days=3)
    else:
        print("1) (재스캔 생략, 기존 scan_result.json 사용)")

    with open(os.path.join(SCRIPT_DIR, "scan_result.json"), "r", encoding="utf-8") as f:
        scan_result = json.load(f)

    ready = scan_result.get("ready", [])

    # 이전에 이미 SF에 생성된 건은 건너뛴다 (scan의 dedup과는 별개 - 여기서는
    # "실제로 Case/Parts Order가 생성됐는가"만 기준으로 함)
    already_created_topics = set()
    if os.path.exists(RESULT_PATH):
        with open(RESULT_PATH, "r", encoding="utf-8") as f:
            prev = json.load(f)
        already_created_topics = {c["topic"] for c in prev.get("created", [])}

    ready = [r for r in ready if r["topic"] not in already_created_topics]
    print(f"2) 자동생성 대상 {len(ready)}건 (이미 생성된 건 제외)")

    results = {"created": [], "needs_review": [], "location_review": [], "errors": []}
    if os.path.exists(RESULT_PATH):
        with open(RESULT_PATH, "r", encoding="utf-8") as f:
            results = json.load(f)
            results.setdefault("needs_review", [])

    if not ready:
        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print("처리할 건이 없습니다.")
        return

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
        context = browser.contexts[0]
        page = get_sf_page(context)

        for rec in ready:
            parsed = rec["parsed"]
            hospital = parsed.get("hospital_name")
            print(f"\n[처리중] {hospital} - {parsed.get('item_raw')}")

            try:
                received_date = datetime.fromisoformat(rec["received"]).date()

                # 경미한 예외만 기존 관례값으로 보정: 수량 미기재는 map_record 호출 전에
                # 1개로 간주(그래야 Line Price 계산도 정상적으로 됨).
                qty_note = None
                if not parsed.get("item_qty"):
                    parsed["item_qty"] = 1
                    qty_note = "수량 표기 없어 1개로 간주"

                mapped = map_record(parsed, received_date)

                # 주문접수Channel 미기재도 경미한 예외로 보고 기존 관례값("구두요청")으로 보정.
                if ORDER_CHANNEL_MISSING_WARNING in mapped["warnings"]:
                    mapped["case"]["caller_last_name"] = "구두요청"
                    mapped["warnings"].remove(ORDER_CHANNEL_MISSING_WARNING)

                # 위 두 가지 외의 경고(품목코드 못 찾음, 금액 계산 불가 등)가 남아있으면
                # 애매한 값을 추정하지 않고 사람이 볼 목록으로 넘긴다.
                if mapped["warnings"]:
                    print(f"  -> 확인 필요: {mapped['warnings']}")
                    results["needs_review"].append({
                        "topic": rec["topic"], "hospital": hospital, "reason": mapped["warnings"],
                    })
                    continue

                go_home(page)
                found, reason = search_and_open_location(page, hospital)
                if not found:
                    print(f"  -> Location 매칭 실패: {reason}")
                    results["location_review"].append({
                        "topic": rec["topic"], "hospital": hospital, "reason": reason,
                    })
                    continue

                case_url = create_case_from_location(page, mapped["case"])
                print(f"  -> Case 생성: {case_url}")

                po_url = create_parts_order_from_case(page, mapped["parts_order"])
                print(f"  -> Parts Order 생성: {po_url}")

                created_entry = {
                    "topic": rec["topic"], "hospital": hospital,
                    "case_url": case_url, "parts_order_url": po_url,
                    "line_price": mapped["parts_order"]["line_price"],
                    "expected_qty": mapped["parts_order"]["expected_qty"],
                }
                if qty_note:
                    created_entry["note"] = qty_note
                results["created"].append(created_entry)
            except Exception as e:
                print(f"  -> 오류: {e}")
                results["errors"].append({
                    "topic": rec["topic"], "hospital": hospital, "error": str(e),
                })

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n생성 완료: {len(results['created'])}건")
    print(f"확인 필요(경고): {len(results['needs_review'])}건")
    print(f"Location 확인 필요: {len(results['location_review'])}건")
    print(f"오류: {len(results['errors'])}건")
    print(f"결과 저장: {RESULT_PATH}")


if __name__ == "__main__":
    main()
