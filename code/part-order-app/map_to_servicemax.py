"""parser.py의 파싱 결과를 ServiceMax Case/Parts Order 입력 필드값으로 변환한다.

SOP(05_Customer_Billable_Parts_Order_SOP)에서 확인한 규칙:
- Case Subject/Description: "{내역} - {M}월 {D}일 접수"
- Caller Last Name: 메일의 "주문접수Channel"
- Packing Instructions / Message For Shipper: "{M}월{D}일 접수 {품명} {택배/퀵}"
- Expected Receipt Date: 접수일 + 4일 (MM/DD/YYYY)
- Product Code: 메일에 PN이 있으면 그걸 그대로, 없으면 product_codes.json에서
  품명으로 조회 (예: DCD -> FIN101110). 둘 다 없으면 review로 보냄
- Line Price: 입금액(부가세 포함) / 1.1, 원 단위 반올림
- 고정값: From Location=KRP, Ship Via Master=KRP, Ship Via=Yongma Logis,
  Action Taken="Send billable parts", Why Called="Other",
  Problem Type="consumables", Order Type="Billable Parts Order",
  배송방법은 거의 항상 택배이므로 기본값 "택배" 사용

주의: "접수일자"는 결제일자(payment_date)가 아니라 실제 메일을 처리하는
날짜(Outlook 수신일) 기준이다 - SOP 예시가 그렇게 되어 있음.
"""

import json
import os
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PRODUCT_CODES_PATH = os.path.join(SCRIPT_DIR, "product_codes.json")

VAT_RATE = 1.1
RECEIPT_LEAD_DAYS = 4

FIXED_VALUES = {
    "from_location": "KRP",
    "ship_via_master": "KRP",
    "ship_via": "Yongma Logis",
    "action_taken": "Send billable parts",
    "why_called": "Other",
    "problem_type": "consumables",
    "order_type": "Billable Parts Order",
    "delivery_method": "택배",
    "currency": "Korean Won",
}


def load_product_codes():
    with open(PRODUCT_CODES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_product_code(parsed, product_codes):
    if parsed.get("part_number"):
        return parsed["part_number"], "email_pn"
    item_name = parsed.get("item_name")
    if item_name and item_name in product_codes:
        return product_codes[item_name], "lookup_table"
    return None, None


def to_line_price(amount, qty):
    """ServiceMax의 Line Price는 개당 단가 - 시스템이 Expected Qty를 곱해
    총액을 계산하므로, 부가세 제외한 총액이 아니라 개당 단가를 반환해야 한다."""
    if amount is None or not qty:
        return None
    return round((amount / VAT_RATE) / qty)


def map_record(parsed, received_date):
    """received_date: datetime.date - Outlook에서 메일을 받은 날짜(접수일 기준)."""
    warnings = []

    product_codes = load_product_codes()
    product_code, code_source = resolve_product_code(parsed, product_codes)
    if product_code is None:
        warnings.append(f"품목코드를 찾을 수 없음 (item_name={parsed.get('item_name')!r}) - product_codes.json에 추가 필요")

    m, d = received_date.month, received_date.day
    item_label = parsed.get("item_raw", "")
    receipt_phrase = f"{m}월 {d}일 접수"
    subject = f"{item_label} - {receipt_phrase}"
    packing_instructions = f"{m}월{d}일 접수 {parsed.get('item_name', item_label)} {FIXED_VALUES['delivery_method']}"

    expected_receipt_date = received_date + timedelta(days=RECEIPT_LEAD_DAYS)

    line_price = to_line_price(parsed.get("amount"), parsed.get("item_qty"))
    if line_price is None:
        warnings.append("금액(amount) 또는 수량(item_qty)이 없어 Line Price(개당 단가)를 계산할 수 없음")

    if not parsed.get("order_channel"):
        warnings.append("주문접수Channel이 없어 Caller Last Name을 채울 수 없음")

    result = {
        "hospital_search_keyword": parsed.get("hospital_name"),
        "case": {
            "action_taken": FIXED_VALUES["action_taken"],
            "why_called": FIXED_VALUES["why_called"],
            "problem_type": FIXED_VALUES["problem_type"],
            "subject": subject,
            "description": subject,
            "caller_last_name": parsed.get("order_channel"),
        },
        "parts_order": {
            "from_location": FIXED_VALUES["from_location"],
            "ship_via_master": FIXED_VALUES["ship_via_master"],
            "ship_via": FIXED_VALUES["ship_via"],
            "order_type": FIXED_VALUES["order_type"],
            "currency": FIXED_VALUES["currency"],
            "packing_instructions": packing_instructions,
            "message_for_shipper": packing_instructions,
            "expected_receipt_date": expected_receipt_date.strftime("%m/%d/%Y"),
            "product_code": product_code,
            "product_code_source": code_source,
            "expected_qty": parsed.get("item_qty"),
            "line_price": line_price,
            "use_price_from_pricebook": False,
        },
        "source": {
            "amount_raw": parsed.get("amount_raw"),
            "payment_date": parsed.get("payment_date"),
            "payment_method": parsed.get("payment_method"),
            "depositor_name": parsed.get("depositor_name"),
        },
        "warnings": warnings,
    }

    if not parsed.get("item_qty"):
        warnings.append("수량(item_qty)이 없음 - 확인 필요")

    result["needs_review"] = len(warnings) > 0
    return result


def map_manual_record(hospital_name, item_label, item_qty, unit_price,
                       received_date=None, part_number=None, item_name=None,
                       order_channel=None):
    """메일 파싱을 거치지 않고 구두로 전달받은 파트오더 요청을 map_record와
    동일한 출력 포맷으로 변환한다.

    unit_price는 개당 단가(부가세 별도, 이미 계산된 값)를 그대로 Line Price로
    사용한다 - map_record처럼 입금액을 1.1로 나누는 VAT 역산은 하지 않는다.
    product_code는 part_number가 주어지면 그걸 쓰고, 없으면 item_name으로
    product_codes.json을 조회한다.
    order_channel: 요청에 명시된 "주문접수Channel"/"주문 채널"/"채널" 값(예:
    "이가람과장님", "챗봇 접수", "Service main 전화") - 그대로 Caller Last Name에
    들어간다. 주어지지 않으면 "구두요청"으로 대체하고 warnings에 기록한다.
    """
    warnings = []
    if received_date is None:
        received_date = date.today()

    if order_channel:
        caller_last_name = order_channel
    else:
        caller_last_name = "구두요청"
        warnings.append("주문접수Channel이 없어 Caller Last Name을 기본값('구두요청')으로 채움")

    product_codes = load_product_codes()
    if part_number:
        product_code, code_source = part_number, "manual_pn"
    elif item_name and item_name in product_codes:
        product_code, code_source = product_codes[item_name], "lookup_table"
    else:
        product_code, code_source = None, None
        warnings.append(
            f"품목코드를 찾을 수 없음 (item_name={item_name!r}) - PN을 직접 지정하거나 product_codes.json에 추가 필요"
        )

    m, d = received_date.month, received_date.day
    receipt_phrase = f"{m}월 {d}일 접수"
    subject = f"{item_label} - {receipt_phrase}"
    packing_instructions = f"{m}월{d}일 접수 {item_name or item_label} {FIXED_VALUES['delivery_method']}"
    expected_receipt_date = received_date + timedelta(days=RECEIPT_LEAD_DAYS)

    if not item_qty:
        warnings.append("수량(item_qty)이 없음 - 확인 필요")
    if unit_price is None:
        warnings.append("Line Price(개당 단가)가 없음 - 확인 필요")

    result = {
        "hospital_search_keyword": hospital_name,
        "case": {
            "action_taken": FIXED_VALUES["action_taken"],
            "why_called": FIXED_VALUES["why_called"],
            "problem_type": FIXED_VALUES["problem_type"],
            "subject": subject,
            "description": subject,
            "caller_last_name": caller_last_name,
        },
        "parts_order": {
            "from_location": FIXED_VALUES["from_location"],
            "ship_via_master": FIXED_VALUES["ship_via_master"],
            "ship_via": FIXED_VALUES["ship_via"],
            "order_type": FIXED_VALUES["order_type"],
            "currency": FIXED_VALUES["currency"],
            "packing_instructions": packing_instructions,
            "message_for_shipper": packing_instructions,
            "expected_receipt_date": expected_receipt_date.strftime("%m/%d/%Y"),
            "product_code": product_code,
            "product_code_source": code_source,
            "expected_qty": item_qty,
            "line_price": unit_price,
            "use_price_from_pricebook": False,
        },
        "source": {
            "request_type": "manual_verbal_request",
        },
        "warnings": warnings,
    }

    result["needs_review"] = len(warnings) > 0
    return result


# --- Non-Billable / Exchange Parts Order ---
# 실제 ServiceMax 화면(Case > "Create Non-Billable/Exchange Parts Order")에서
# 라이브로 확인한 값들. Billable과의 핵심 차이:
# - Case의 Action Taken은 "Send non-billable parts\Exchange" (billable은 "Send billable parts")
# - 생성 폼(SVMX_Create_Non_Billable_Exchange_PO_From_Case)에는 Billable의 ExtJS
#   Product 그리드가 없다 - "Part To Be Shipped"라는 단일 lookup 필드 하나뿐이라
#   Line Price/부가세 역산 로직 자체가 필요 없고(Billing Type은 폼이 "Sales Support"로
#   자동 디폴트), 저장하면 Qty=1인 라인이 생성된다. 수량이 1이 아니면 저장 후
#   Parts Order Line을 별도로 수정해야 한다 - 이 부분은 아직 sf_actions.py에
#   미구현이니 실제로 수량>1인 건이 나오면 라이브 화면에서 Edit 흐름을 확인해서
#   추가할 것.
# - Order type은 "Non-Billable Parts Order"(단순 무상 출고) 또는 "Exchange"(불량품
#   회수를 동반하는 교환) 중 하나를 반드시 선택해야 한다(화면상 필수 필드).
#   Exchange인 경우 회수할 기기의 IB Serial To Return을 같이 넣어야 한다.
# - Non Billable Category는 화면상 필수는 아니지만(옵션), 회계/오라클 인터페이스
#   분류를 위한 값이라 어떤 사유인지 모르면 임의로 채우지 않고 needs_review로 넘긴다.
FIXED_VALUES_NON_BILLABLE = {
    "from_location": "KRP",
    "action_taken": "Send non-billable parts\\Exchange",
    "why_called": "Other",
    "problem_type": "consumables",
    "billing_type": "Sales Support",
    "delivery_method": "택배",
}

NON_BILLABLE_ORDER_TYPES = {"Non-Billable Parts Order", "Exchange"}

# 화면 피클리스트에 실제로 있는 값 그대로 - 앞 두 개는 하이픈(-), 뒤 세 개는
# en dash(–)를 쓴다는 점에 주의(오타 아님, ServiceMax 화면 그대로임).
NON_BILLABLE_CATEGORIES = {
    "NB - LAB",
    "NB - FTZ Parts",
    "NB – Concession",
    "NB – T&M Revisit",
    "NB – Unusual",
}


def map_manual_record_non_billable(hospital_name, item_label, item_qty, order_type,
                                    received_date=None, part_number=None, item_name=None,
                                    non_billable_category=None, ib_serial_to_return=None,
                                    fault_on=None, order_channel=None):
    """구두요청/이메일로 전달받은 Non-Billable/Exchange 파트오더 요청을 ServiceMax
    'Create Non-Billable/Exchange Parts Order From Case' 폼 입력값으로 변환한다.

    order_type: "Non-Billable Parts Order" 또는 "Exchange" - 화면의 Order type
    피클리스트 값과 정확히 일치해야 한다.
    ib_serial_to_return: Exchange일 때 회수할 기기의 시리얼(설치제품) - 없으면 경고.
    non_billable_category: NON_BILLABLE_CATEGORIES 중 하나 - 없으면 경고(needs_review).
    order_channel: "주문접수Channel"/"주문 채널"/"채널" 값 - 그대로 Caller Last Name에
    들어간다. 주어지지 않으면 "구두요청"으로 대체하고 warnings에 기록한다.
    """
    warnings = []
    if received_date is None:
        received_date = date.today()

    if order_channel:
        caller_last_name = order_channel
    else:
        caller_last_name = "구두요청"
        warnings.append("주문접수Channel이 없어 Caller Last Name을 기본값('구두요청')으로 채움")

    if order_type not in NON_BILLABLE_ORDER_TYPES:
        warnings.append(
            f"order_type {order_type!r}이 알 수 없는 값 - 'Non-Billable Parts Order' 또는 'Exchange'여야 함"
        )
    if order_type == "Exchange" and not ib_serial_to_return:
        warnings.append("Exchange 오더인데 IB Serial To Return이 지정되지 않음 - 회수할 시리얼 확인 필요")

    if non_billable_category is None:
        warnings.append(
            "Non Billable Category가 지정되지 않음 - "
            + ", ".join(sorted(NON_BILLABLE_CATEGORIES)) + " 중 확인 필요"
        )
    elif non_billable_category not in NON_BILLABLE_CATEGORIES:
        warnings.append(f"Non Billable Category {non_billable_category!r}가 알려진 값이 아님")

    product_codes = load_product_codes()
    if part_number:
        product_code, code_source = part_number, "manual_pn"
    elif item_name and item_name in product_codes:
        product_code, code_source = product_codes[item_name], "lookup_table"
    else:
        product_code, code_source = None, None
        warnings.append(
            f"품목코드를 찾을 수 없음 (item_name={item_name!r}) - PN을 직접 지정하거나 product_codes.json에 추가 필요"
        )

    m, d = received_date.month, received_date.day
    receipt_phrase = f"{m}월 {d}일 접수"
    subject = f"{item_label} - {receipt_phrase}"
    message_for_shipper = f"{m}월{d}일 접수 {item_name or item_label} {FIXED_VALUES_NON_BILLABLE['delivery_method']}"
    expected_receipt_date = received_date + timedelta(days=RECEIPT_LEAD_DAYS)

    if not item_qty:
        item_qty = 1
    if item_qty != 1:
        warnings.append(
            f"수량({item_qty})이 1이 아님 - 이 폼은 생성 시 Qty를 지정할 수 없어(항상 1로 생성) "
            "게다가 저장 후 Parts Order Line 표준 Edit 화면에서도 Expected Qty가 읽기전용(입력창 없음)이라 "
            "수정 자체가 불가능함(2026-08-03 라이브 확인) - 같은 Case에 qty=1 PO를 필요한 개수만큼 "
            "반복 생성해서 처리할 것(batch_promotion_multi.py 참고)"
        )

    result = {
        "hospital_search_keyword": hospital_name,
        "case": {
            "action_taken": FIXED_VALUES_NON_BILLABLE["action_taken"],
            "why_called": FIXED_VALUES_NON_BILLABLE["why_called"],
            "problem_type": FIXED_VALUES_NON_BILLABLE["problem_type"],
            "subject": subject,
            "description": subject,
            "caller_last_name": caller_last_name,
        },
        "parts_order": {
            "order_type": order_type,
            "non_billable_category": non_billable_category,
            "billing_type": FIXED_VALUES_NON_BILLABLE["billing_type"],
            "from_location": FIXED_VALUES_NON_BILLABLE["from_location"],
            "message_for_shipper": message_for_shipper,
            "expected_receipt_date": expected_receipt_date.strftime("%m/%d/%Y"),
            "product_code": product_code,
            "product_code_source": code_source,
            "expected_qty": item_qty,
            "ib_serial_to_return": ib_serial_to_return,
            "fault_on": fault_on,
        },
        "source": {
            "request_type": "manual_verbal_request_non_billable",
        },
        "warnings": warnings,
    }
    result["needs_review"] = len(warnings) > 0
    return result


if __name__ == "__main__":
    sample_parsed = {
        "hospital_name": "셀린의원 분당",
        "item_raw": "DCD 2박스",
        "item_name": "DCD",
        "item_qty": 2,
        "item_unit": "박스",
        "order_channel": "Service main 전화",
        "payment_method": "계좌이체",
        "depositor_name": "분당정자셀린의원",
        "payment_date": "2026-07-07",
        "amount": 3300000,
    }
    mapped = map_record(sample_parsed, date(2026, 7, 7))
    print(json.dumps(mapped, ensure_ascii=False, indent=2))

    manual_mapped = map_manual_record(
        hospital_name="셀린의원 분당",
        item_label="DCD 2박스",
        item_qty=2,
        unit_price=1500000,
        received_date=date(2026, 7, 7),
        item_name="DCD",
        order_channel="Service main 전화",
    )
    print(json.dumps(manual_mapped, ensure_ascii=False, indent=2))

    non_billable_mapped = map_manual_record_non_billable(
        hospital_name="셀린의원 분당",
        item_label="DCD 1박스 (프로모션 증정)",
        item_qty=1,
        order_type="Non-Billable Parts Order",
        received_date=date(2026, 7, 14),
        item_name="DCD",
        non_billable_category="NB – Concession",
    )
    print(json.dumps(non_billable_mapped, ensure_ascii=False, indent=2))
