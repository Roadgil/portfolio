"""파트오더(소모품 출고) 신청 메일 본문을 구조화된 필드로 추출하는 파서.

실제 메일은 인사말 -> "(비고)" -> 라벨/값이 반복되는 표 형태로 구성된다.
라벨 자체가 항상 "다음 줄 = 값" 처럼 깔끔하게 1:1로 대응하지 않고,
- 내역: 품명 줄 다음에 품번(PN) 줄이 더 붙기도 함 ("PN: 값" 또는 라벨 없는 코드)
- 결제수단: 값 다음에 입금자명이 "입금자명: 값" 또는 라벨 없이 한 줄 더 붙기도 함
- 표현이 "계좌이체"/"계좌입금"처럼 라벨마다 다르게 옴
- 마지막 필드(입금액) 뒤에 할인 안내 같은 자유 텍스트가 더 붙기도 함
등의 변형이 있어, 줄 단위 1:1 매칭 대신 "라벨 줄의 위치 = 구간 경계"로 보고
각 라벨과 다음 라벨 사이의 모든 줄을 그 라벨의 값 구간으로 처리한다.

또한 Outlook 답장/전달 메일에는 이전 요청 메일 내용이 인용되어 아래에
그대로 남아있는 경우가 있어 "병원명"이 메일 본문에 두 번 이상 나오면
첫 번째 요청 건만 파싱하고 나머지는 무시 + 경고를 남긴다.
"""

import json
import re

# 라벨 줄 -> 내부 필드 키. 가장 먼저 매치되는 라벨 줄이 다음 라벨 줄 전까지의
# 전체 구간(여러 줄일 수 있음)에 대한 값이 된다.
LINE_LABELS = {
    "병원명": "hospital_name",
    "내역": "item_raw",
    "주문접수Channel": "order_channel",
    "결제수단": "payment_method",
    "결제일자": "payment_date",
}
AMOUNT_LABEL_PREFIX = "입금액"  # "입금액 (원)"처럼 뒤에 괄호가 붙어 정확매치가 안 됨

# 한 줄에 "라벨: 값" 형태로 붙어 나오는 필드 (구간 안에서 위치 무관하게 인식)
INLINE_LABELS = {
    "입금자명": "depositor_name",
    "PN": "part_number",
}

ITEM_PATTERN = re.compile(r"^(?P<name>.+?)\s*\*?\s*(?P<qty>\d+)\s*(?P<unit>박스|개|EA|ea|BOX|box)$")
INLINE_PATTERN = re.compile(r"^([^:：]{1,20})[:：]\s*(.+)$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PART_CODE_PATTERN = re.compile(r"^\d{3,5}-\d{2,3}-\d{3,6}$")


def _clean_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def _match_label(line):
    if line in LINE_LABELS:
        return LINE_LABELS[line]
    if line.startswith(AMOUNT_LABEL_PREFIX):
        return "amount_section"
    return None


def _split_inline_or_bare(lines, result, unparsed, section, bare_fallback_key=None):
    """구간 안의 나머지 줄들에서 인라인 라벨을 뽑고, 남는 줄은 unparsed로."""
    leftover = []
    for line in lines:
        m = INLINE_PATTERN.match(line)
        label = m.group(1).strip() if m else None
        if m and label in INLINE_LABELS:
            result[INLINE_LABELS[label]] = m.group(2).strip()
        elif bare_fallback_key and bare_fallback_key not in result:
            result[bare_fallback_key] = line
        elif PART_CODE_PATTERN.match(line):
            result["part_number"] = line
        else:
            leftover.append(line)
    for line in leftover:
        unparsed.append(f"[{section}] 추가 텍스트(미인식): {line}")


def parse_email_body(text):
    all_lines = _clean_lines(text)
    result = {}
    unparsed = []

    hospital_indices = [i for i, line in enumerate(all_lines) if line == "병원명"]
    if not hospital_indices:
        return {"error": "병원명 라벨을 찾지 못했습니다 - 양식이 다른 메일일 수 있습니다.", "unparsed": all_lines}

    start = hospital_indices[0]
    end = hospital_indices[1] if len(hospital_indices) > 1 else len(all_lines)
    if len(hospital_indices) > 1:
        unparsed.append("메일 본문에 '병원명'이 여러 번 발견됨 - 인용/전달된 이전 메일로 보고 첫 번째 요청 건만 파싱함")

    lines = all_lines[start:end]

    marks = [(i, _match_label(line)) for i, line in enumerate(lines) if _match_label(line)]

    for idx, (pos, key) in enumerate(marks):
        value_start = pos + 1
        value_end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        value_lines = lines[value_start:value_end]

        if not value_lines:
            continue

        if key == "hospital_name":
            result["hospital_name"] = value_lines[0]
            _split_inline_or_bare(value_lines[1:], result, unparsed, "병원명")
        elif key == "item_raw":
            result["item_raw"] = value_lines[0]
            _split_inline_or_bare(value_lines[1:], result, unparsed, "내역")
        elif key == "order_channel":
            result["order_channel"] = value_lines[0]
            _split_inline_or_bare(value_lines[1:], result, unparsed, "주문접수Channel")
        elif key == "payment_method":
            result["payment_method"] = value_lines[0]
            _split_inline_or_bare(value_lines[1:], result, unparsed, "결제수단", bare_fallback_key="depositor_name")
        elif key == "payment_date":
            result["payment_date"] = value_lines[0]
            if not DATE_PATTERN.match(value_lines[0]):
                unparsed.append(f"payment_date 형식 이상: {value_lines[0]}")
            _split_inline_or_bare(value_lines[1:], result, unparsed, "결제일자")
        elif key == "amount_section":
            result["amount_raw"] = value_lines[0]
            _split_inline_or_bare(value_lines[1:], result, unparsed, "입금액")

    if "amount_raw" in result:
        digits = re.sub(r"[^\d]", "", result["amount_raw"])
        result["amount"] = int(digits) if digits else None

    if "item_raw" in result:
        m = ITEM_PATTERN.match(result["item_raw"])
        if m:
            result["item_name"] = m.group("name")
            result["item_qty"] = int(m.group("qty"))
            result["item_unit"] = m.group("unit")
        else:
            result["item_name"] = result["item_raw"]
            unparsed.append(f"내역에서 수량 패턴 인식 실패(품명만 저장): {result['item_raw']}")

    required = ["hospital_name", "item_raw", "payment_method", "payment_date", "amount"]
    missing = [f for f in required if f not in result or result.get(f) in (None, "")]
    if missing:
        unparsed.append(f"필수 필드 누락: {', '.join(missing)}")

    result["unparsed"] = unparsed
    return result


if __name__ == "__main__":
    samples = {
        "sample1_아티움청주_PN코드_비라벨입금자": """안녕하세요 보현 과장님,

서비스팀 정재필입니다.

하기의 건 출고요청 드리고자 합니다.

확인 후 명일 택배 발송 될 수 있도록 도움 부탁 드립니다.



(비고)

병원명

아티움의원 청주



내역

젠틀맥스 시술자용 고글

  8095-00-0476

주문접수Channel

정재필과장



결제수단

계좌입금

안혜림 or 아티움청주
결제일자

2026-07-02

입금액 (원)

330,000원


""",
        "sample2_셀의원대구_톡결제_입금자없음": """안녕하세요 보현 과장님,

서비스팀 김혜준입니다.

하기의 건 출고요청 드리고자 합니다.

확인 후 명일 택배 발송 될 수 있도록 도움 부탁 드립니다.



(비고)

병원명

셀의원 대구



내역

DCD 1박스



주문접수Channel

Service main 전화



결제수단

톡결제

결제일자

2026-07-02

입금액 (원)

1,650,000
""",
        "sample3_샤인빔강서_입금자명라벨": """안녕하세요 보현 과장님,

서비스팀 김혜준입니다.

하기의 건 출고요청 드리고자 합니다.

확인 후 금일 택배 발송 될 수 있도록 도움 부탁 드립니다.



(비고)

병원명

샤인빔의원 강서



내역

DCD 2박스



주문접수Channel

Service main 전화

결제수단

계좌이체

입금자명: 샤인빔의원황규명

결제일자

2026-07-07

입금액 (원)

3,300,000

 """,
        "sample4_모던스탠다드_PN라벨_끝에할인문구": """안녕하세요 보현 과장님,

서비스팀 김혜준입니다.

하기의 건 출고요청 드리고자 합니다.

확인 후 금일 택배 발송 될 수 있도록 도움 부탁 드립니다.



(비고)

병원명

모던스탠다드의원



내역

18mm DG *6EA

PN: 7122-00-9424

주문접수Channel

Service main 전화



결제수단

계좌이체

결제일자

2026-07-06

입금액 (원)

891,000

 프리미엄센터 10%할인
""",
        "sample5_원본_분당셀린": """병원명

셀린의원 분당



내역

DCD 2박스



주문접수Channel

Service main 전화



결제수단

계좌이체

입금자명: 분당정자셀린의원

결제일자

2026-07-07

입금액 (원)

3,300,000




""",
    }

    # 인용/전달 메일 가드 테스트: 두 건이 한 본문에 이어붙은 경우
    samples["sample6_병원명중복_전달메일가드테스트"] = (
        samples["sample1_아티움청주_PN코드_비라벨입금자"]
        + samples["sample2_셀의원대구_톡결제_입금자없음"]
    )

    for name, body in samples.items():
        print(f"=== {name} ===")
        print(json.dumps(parse_email_body(body), ensure_ascii=False, indent=2))
        print()
