# -*- coding: utf-8 -*-
"""월마감 선출고용 문서 2종을 자동 생성한다.

  1) 거래명세서_{병원명}_{YYYY-MM-DD}.pdf   <- 창작소\거래명세서_생성기.html
  2) 선출고요청서_{병원명}_{YYYY-MM-DD}.pdf <- 창작소\선출고_요청서.html

두 생성기 모두 로컬 HTML이라 Playwright로 열어 값만 채우고 PDF로 뽑는다.
거래명세서는 혜준대리님 메일 본문을 그대로 붙여넣으면 품번/단가가 자동 조회된다.

사용 예:
  python make_preship_docs.py --spec spec.json
spec.json 형식은 build_spec() 주석 참고.
"""
import argparse
import json
import os
import re
from datetime import datetime

from playwright.sync_api import sync_playwright

import paths                    # 사용자마다 다른 경로를 이 PC 기준으로 풀어준다

CHANGJAK = paths.CREATIVE_DIR
TRANS_HTML = os.path.join(CHANGJAK, "거래명세서_생성기.html")
PRESHIP_HTML = os.path.join(CHANGJAK, "선출고_요청서.html")

DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "preship_docs")


def _file_url(path):
    return "file:///" + path.replace("\\", "/")


# 메일 본문에서 "내역" 다음에 오는 라벨들 - 여기서 내역 구간이 끝난다.
_NEXT_LABEL = re.compile(r"^\s*(주문접수|결제수단|결제\s*일자|결제일자|입금액|입금자|병원명|비고)")


def normalize_mail_body(text):
    """거래명세서 생성기에 넣기 전에 '내역' 구간을 한 줄로 합친다.

    생성기의 parseBlock은 내역 값을 **한 줄만** 읽는다(`if (!rest && lines[i+1])
    rest = lines[i+1]` 이후 바로 break). 그래서 혜준대리님 메일처럼

        내역
        18mm DG
        PN: 7122-00-9424

    3줄로 오면 품번 줄을 못 봐서 품번/단가/공급가액이 통째로 비어버린다
    (2026-08-28 밴스의원 삼성 건에서 실제로 발생 - 합계만 맞고 품목 행은 '-'/0).
    품번이 CODE_ALIAS에 있는 품목(DCD)은 우연히 통과하기 때문에 더 늦게 드러난다.

    창작소 원본 HTML은 보현과장님도 쓰시므로 건드리지 않고, 여기서 입력만 고친다.
    """
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        out.append(lines[i])
        if re.match(r"^\s*내역[A-Za-z가-힣]*\s*$", lines[i]):
            # 내역 라벨만 있는 줄 -> 다음 라벨 전까지의 값 줄들을 한 줄로 합친다
            j = i + 1
            parts = []
            while j < len(lines):
                s = lines[j].strip()
                if not s:
                    j += 1
                    continue
                if _NEXT_LABEL.match(s):
                    break
                parts.append(s)
                j += 1
            if parts:
                out.append(" ".join(parts))
            i = j
            continue
        i += 1
    return "\n".join(out)


def make_transaction_statement(page, mail_body, vat_type, out_pdf, price_override=None):
    """거래명세서 생성기: 메일 본문 붙여넣기 -> 생성 -> PDF."""
    page.goto(_file_url(TRANS_HTML), wait_until="domcontentloaded")
    page.wait_for_timeout(800)

    # 대학병원처럼 내장 가격표(PRICE_DB)와 단가가 다른 건은, 로드된 페이지의
    # PRICE_DB 항목만 덮어쓴다. 창작소 원본 HTML은 건드리지 않는다
    # (2026-08-31 순천향 건: DCD가 PRICE_DB상 1,500,000이지만 대학병원가는 3,600,000).
    if price_override:
        page.evaluate(
            """(ov) => { for (const [code, v] of Object.entries(ov)) {
                    PRICE_DB[code] = v;
                } }""",
            price_override,
        )
        print(f"  가격 덮어쓰기: {price_override}")

    page.fill("#emailInput", normalize_mail_body(mail_body))
    if vat_type:
        try:
            page.select_option("#vatType", label=vat_type)
        except Exception:
            try:
                page.select_option("#vatType", value=vat_type)
            except Exception:
                print(f"  [경고] vatType '{vat_type}' 선택 실패 - 기본값 사용")

    page.get_by_role("button", name=re.compile("거래명세서 생성")).click()
    page.wait_for_timeout(1500)

    status = ""
    try:
        status = page.locator("#statusMsg").inner_text().strip()
    except Exception:
        pass
    preview = ""
    try:
        preview = page.locator("#previewPanel").inner_text()
    except Exception:
        pass

    if not preview.strip():
        raise RuntimeError(f"거래명세서 미리보기가 비어 있음 (status={status!r})")

    page.pdf(path=out_pdf, format="A4", print_background=True,
             margin={"top": "10mm", "bottom": "10mm", "left": "10mm", "right": "10mm"})
    return {"status": status, "preview_head": preview.strip()[:400]}


def make_preship_request(page, spec, out_pdf):
    """선출고 요청서: 폼 채우고 PDF."""
    page.goto(_file_url(PRESHIP_HTML), wait_until="domcontentloaded")
    page.wait_for_timeout(1500)  # 내장 품목 마스터 로딩

    page.fill("#reqDate", spec["date"])          # YYYY-MM-DD
    if spec.get("oracle_number"):
        page.fill("#oracle", spec["oracle_number"])   # 보통 공란(월마감 시 번호 없음)

    # 병원명: 입력하면 후보 드롭다운이 뜨고, 고르면 주소가 자동으로 채워진다.
    # 단 드롭다운을 고르면 병원명도 DB의 정식명으로 덮어써진다("아윤의원" ->
    # "아윤의원 강남", 2026-08-28 실측). 그러면 거래명세서(메일의 병원명)와
    # 선출고요청서의 병원명이 어긋나므로, 주소를 이미 알고 있으면(SF Location에서
    # 가져온 경우) 드롭다운을 아예 건드리지 않고 메일의 병원명을 그대로 쓴다.
    page.fill("#hospital", spec["hospital"])
    page.wait_for_timeout(900)
    picked = False
    if not spec.get("address"):
        try:
            dd = page.locator("#hospDD li, #hospDD div").filter(has_text=spec["hospital"])
            if dd.count() > 0 and dd.first.is_visible():
                dd.first.click()
                page.wait_for_timeout(500)
                picked = True
        except Exception:
            pass
    else:
        page.keyboard.press("Escape")
        page.fill("#address", spec["address"])
    if spec.get("address_detail"):
        page.fill("#addressDetail", spec["address_detail"])

    ship = spec.get("ship", "택배")
    page.check("#ship-quick" if ship == "퀵" else "#ship-taekbae")

    if spec.get("contact"):
        page.fill("#contact", spec["contact"])
    if spec.get("delivery_dt"):
        page.fill("#deliveryDt", spec["delivery_dt"])   # YYYY-MM-DDTHH:MM

    _fill_items(page, spec["items"])

    page.wait_for_timeout(500)
    page.pdf(path=out_pdf, format="A4", print_background=True,
             margin={"top": "10mm", "bottom": "10mm", "left": "10mm", "right": "10mm"})
    return {"hospital_picked_from_dropdown": picked}


def _fill_items(page, items):
    """품목 행 채우기.

    행 구조는 addRow()가 만드는 tr: input.code / td.desc / input.ea / input.out /
    input.rmk / button.rm(행 삭제). 폼은 빈 행을 미리 몇 개 깔아두는데, 그대로
    두면 인쇄물에 빈 줄이 같이 찍히므로 마지막에 지운다(보현과장님 원본은
    채워진 행만 나온다)."""
    add_btn = page.get_by_role("button", name=re.compile(r"품목 행 추가"))
    rows = page.locator("tr:has(input.code)")
    while rows.count() < len(items):
        add_btn.click()
        page.wait_for_timeout(300)

    for idx, it in enumerate(items):
        row = rows.nth(idx)
        code_box = row.locator("input.code").first
        code_box.click()
        code_box.fill(it["code"])
        page.wait_for_timeout(700)
        # 코드 자동완성 후보가 뜨면 첫 번째를 고른다(Description 자동 채움).
        # 안 뜨면 blur만 시켜도 fillDesc가 돌아 Description이 채워진다.
        sugg = row.locator(".sugg.show *")
        if sugg.count() > 0 and sugg.first.is_visible():
            sugg.first.click()
        else:
            code_box.press("Tab")
        page.wait_for_timeout(500)

        row.locator("input.ea").first.fill(str(it["qty"]))
        row.locator("input.out").first.fill(str(it.get("out_qty", it["qty"])))
        if it.get("remark"):
            row.locator("input.rmk").first.fill(it["remark"])

    # 코드가 비어 있는 행은 인쇄 전에 제거하고, 남아있는 포커스 테두리도 없앤다.
    page.evaluate("""() => {
        document.querySelectorAll('tr').forEach(tr => {
            const c = tr.querySelector('input.code');
            if (c && !c.value.trim()) tr.remove();
        });
        if (document.activeElement && document.activeElement.blur) {
            document.activeElement.blur();
        }
    }""")
    page.wait_for_timeout(300)


def build_spec():
    """spec.json 예시:
    {
      "date": "2026-08-28",
      "hospital": "리버스의원 강남",
      "address": "서울시 서초구 ...",          # 생략하면 병원 드롭다운 자동입력에 맡김
      "ship": "택배",                          # 또는 "퀵"
      "contact": "",
      "delivery_dt": "2026-08-28T14:00",
      "oracle_number": "",                     # 월마감이면 공란
      "vat_type": "",                          # 거래명세서 VAT 처리 옵션 라벨
      "items": [{"code": "FIN101110", "qty": 1, "out_qty": 1, "remark": ""}],
      "mail_body": "...혜준대리님 메일 본문 전체..."
    }
    """


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True, help="주문 1건 spec json 경로")
    ap.add_argument("--outdir", default=DEFAULT_OUT)
    ap.add_argument("--headed", action="store_true", help="브라우저를 띄워서 확인")
    args = ap.parse_args()

    spec = json.load(open(args.spec, encoding="utf-8"))
    os.makedirs(args.outdir, exist_ok=True)

    hosp = spec["hospital"]
    date = spec["date"]
    trans_pdf = os.path.join(args.outdir, f"거래명세서_{hosp}_{date}.pdf")
    pre_pdf = os.path.join(args.outdir, f"선출고요청서_{hosp}_{date}.pdf")

    result = {"hospital": hosp, "date": date}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed, channel="msedge")
        ctx = browser.new_context()
        page = ctx.new_page()

        print("1) 거래명세서 생성...")
        result["transaction"] = make_transaction_statement(
            page, spec["mail_body"], spec.get("vat_type"), trans_pdf,
            spec.get("price_override"))
        result["transaction_pdf"] = trans_pdf
        print("   ->", trans_pdf)

        print("2) 선출고 요청서 생성...")
        result["preship"] = make_preship_request(page, spec, pre_pdf)
        result["preship_pdf"] = pre_pdf
        print("   ->", pre_pdf)

        browser.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    main()
