# -*- coding: utf-8 -*-
"""ServiceMax Case + Billable Parts Order 생성 (품목 N개 지원).

배포본 sf_actions.create_parts_order_from_case는 품목 1줄만 넣는다.
여기서는 Lines 그리드에 여러 줄을 채운다. 2026-08-31 원스의원 수원 건으로 실증.

이 그리드의 함정 두 가지(실측):
1) '찔러보기' 더블클릭은 **첫 행에만** 필요하다. 빈 마지막 행을 처음 건드리면
   그리드가 다음 placeholder 행을 추가하며 편집 포커스를 뺏어서 두 번 눌러야 한다.
   반대로 둘째 행부터는 앞 행 커밋으로 이미 만들어진 행이라 한 번만 눌러야 하고,
   두 번 누르면 편집모드가 토글돼 꺼지면서 lookup 아이콘이 사라진다.
2) lookup 아이콘은 반드시 **Product 열 x범위 + 같은 y**로 찾는다.
   편집모드에서 ancestor::tr 로 좁히면 레이아웃 테이블 행이 잡혀
   From Location 아이콘을 눌러 Location search 팝업이 뜬다.

금액은 'Use Price From Pricebook'을 해제하고 Line Price에 직접 넣는다(사용자 지시).
Send To Approval은 절대 누르지 않는다(사용자 지시).
"""
import re  # noqa: F401  (Parts Orders 개수/PO 번호 파싱에 사용)
from datetime import date

from sf_actions import (
    create_case_from_location,
    wait_for_frame_with_text,
    _click_save_icon,
    _wait_for_record_redirect,
    _fill_from_location,
    _select_first_visible_result,
    _visible_icon_boxes,
    _box_in,
)
from sf_form_helpers import find_field_row, fill_text_field, select_picklist

HOME_URL = "https://candelamedical.my.salesforce.com/home/home.jsp"

PRODUCT_CELL = "td.svmx-grid-cell-gridcolumn-1103"
CODE_CELL = "td.svmx-grid-cell-gridcolumn-1105"
QTY_CELL = "td.svmx-grid-cell-gridcolumn-1106"
PRICE_CELL = "td.svmx-grid-cell-gridcolumn-1107"
CHECK_CELL = "td.svmx-grid-cell-svmx-columncheck-1109"


def _settle(page, timeout=20000, marker=None):
    """페이지가 자리잡을 때까지 기다리되, 못 기다려도 죽지 않는다.

    Salesforce/ServiceMax는 백그라운드 폴링을 계속 물고 있어서 networkidle이
    영영 안 오는 경우가 있다. 화면은 멀쩡히 떠 있는데 대기에서만 터진다
    (2026-09-02 포레나의원 - Location 클릭 후 networkidle 20초 초과로 생성 실패.
    같은 배치의 다른 건은 통과해서 '가끔 실패'처럼 보였다).
    marker를 주면 networkidle 대신 그 글자가 뜨는 것으로 판단한다.
    """
    try:
        page.wait_for_load_state("networkidle", timeout=timeout)
        return True
    except Exception:
        pass
    try:
        page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    if marker:
        try:
            page.wait_for_selector(f"text={marker}", timeout=10000)
            return True
        except Exception:
            return False
    page.wait_for_timeout(2000)
    return True


def search_locations(page, keyword):
    """검색 결과의 Location 이름 목록을 돌려준다(클릭하지 않음)."""
    page.goto(HOME_URL)
    _settle(page)
    box = page.get_by_placeholder("Search...")
    box.click()
    box.fill(keyword)
    page.get_by_role("button", name="Search", exact=True).click()
    _settle(page, marker="Search Results")

    header = page.locator("text=Locations (")
    if header.count() == 0:
        return []
    names = []
    rows = page.locator("#SVMXC__Site__c_body").locator("tr")
    # 0번 행은 컬럼 헤더다. 헤더의 정렬 링크("Location Name")가 결과로 섞이면
    # 검색결과 건수를 1건 더 세서 "여러 건"으로 오판한다.
    for i in range(1, rows.count()):
        link = rows.nth(i).locator("th a").first
        if link.count():
            names.append(link.inner_text().strip())
    return names


def open_location(page, keyword, exact=None, log=print):
    names = search_locations(page, keyword)
    log(f"  Location 검색 '{keyword}' -> {len(names)}건: {names}")
    if not names:
        raise RuntimeError(f"Location 검색결과 0건 ({keyword!r})")
    if exact is None and len(names) > 1:
        raise RuntimeError(f"Location 후보가 여러 건이라 지정 필요: {names}")
    want = exact or names[0]

    rows = page.locator("#SVMXC__Site__c_body").locator("tr")
    for i in range(rows.count()):
        link = rows.nth(i).locator("th a").first
        if link.count() and link.inner_text().strip() == want:
            log(f"  Location 선택: {want!r}")
            link.click()
            # networkidle을 못 기다려도 화면은 떠 있다 - 이름이 보이면 진행
            if not _settle(page, marker=want):
                log("  (Location 화면 로딩 확인 실패 - 그래도 계속 진행)")
            return want
    raise RuntimeError(f"'{want}' 를 검색결과에서 찾지 못함 (후보 {names})")


def _fill_row(page, form, idx, code, qty, price, log=print):
    page.keyboard.press("Escape")
    page.wait_for_timeout(900)

    cells = form.locator(PRODUCT_CELL)
    if cells.count() <= idx:
        raise RuntimeError(f"행 {idx} 없음 (현재 {cells.count()}행)")
    cell = cells.nth(idx)
    cell.scroll_into_view_if_needed()

    if idx == 0:                      # 찔러보기는 첫 행에만 (모듈 설명 참고)
        cell.dblclick()
        page.wait_for_timeout(1000)
        page.keyboard.press("Escape")
        page.wait_for_timeout(600)
        cell = form.locator(PRODUCT_CELL).nth(idx)
        cell.scroll_into_view_if_needed()

    cell_box = cell.bounding_box()
    boxes_before = _visible_icon_boxes(form.locator(".svmx_lookup_icon"))

    cell.dblclick()
    page.wait_for_timeout(1000)

    for _ in range(3):                # Product 칸에서 편집이 열렸는지 확인
        inputs = form.locator("input[type='text']")
        hit = False
        for i in range(inputs.count()):
            inp = inputs.nth(i)
            if not inp.is_visible():
                continue
            b = inp.bounding_box()
            if b and abs(b["y"] - cell_box["y"]) < 15 and \
               cell_box["x"] - 10 <= b["x"] <= cell_box["x"] + cell_box["width"]:
                hit = True
                break
        if hit:
            break
        cell.dblclick()
        page.wait_for_timeout(800)

    page.keyboard.type(code)
    page.wait_for_timeout(700)

    def in_col(b):
        return cell_box and cell_box["x"] - 10 <= b["x"] <= cell_box["x"] + cell_box["width"] + 40

    def near(b):
        return cell_box and abs(b["y"] - cell_box["y"]) <= 25

    target, seen = None, []
    for _ in range(20):
        icons = form.locator(".svmx_lookup_icon")
        seen, new_i, old_i = [], None, None
        for i in range(icons.count()):
            ic = icons.nth(i)
            if not ic.is_visible():
                continue
            b = ic.bounding_box()
            if b is None:
                continue
            seen.append((round(b["x"]), round(b["y"])))
            if not (in_col(b) and near(b)):
                continue
            if not _box_in(b, boxes_before):
                new_i = new_i or ic
            elif old_i is None:
                old_i = ic
        target = new_i or old_i
        if target is not None:
            break
        page.wait_for_timeout(400)
    if target is None:
        raise RuntimeError(f"행 {idx}: Product lookup 아이콘 없음. "
                           f"cell={cell_box} 아이콘={seen} 편집전={boxes_before}")
    target.click()
    page.wait_for_timeout(1500)
    _select_first_visible_result(page, code)

    for _ in range(20):
        cc = form.locator(CODE_CELL)
        if cc.count() > idx and code in cc.nth(idx).inner_text():
            break
        page.wait_for_timeout(750)
    cc = form.locator(CODE_CELL)
    got = cc.nth(idx).inner_text().strip() if cc.count() > idx else ""
    if code not in got:
        raise RuntimeError(f"행 {idx}: Product Code가 {code}로 안 들어감 (실제 {got!r})")

    form.locator(QTY_CELL).nth(idx).dblclick()
    page.wait_for_timeout(400)
    page.keyboard.press("Control+A")
    page.keyboard.type(str(qty))
    page.wait_for_timeout(200)

    form.locator(PRICE_CELL).nth(idx).dblclick()
    page.wait_for_timeout(400)
    page.keyboard.press("Control+A")
    page.keyboard.type(str(price))
    page.wait_for_timeout(200)
    page.keyboard.press("Tab")
    page.wait_for_timeout(400)

    chk = form.locator(CHECK_CELL).nth(idx)          # Use Price From Pricebook 해제
    if "svmx-grid-checkheader-checked" in (chk.inner_html() or ""):
        chk.click()
        page.wait_for_timeout(300)

    log(f"  행 {idx}: {code} qty={qty} price={price:,}")


def _delete_trailing_empty(page, form, keep, log=print):
    for _ in range(5):
        if form.locator(PRODUCT_CELL).count() <= keep:
            break
        dels = form.locator(".svmx-sfmd-delete-icon")
        boxes = [(i, dels.nth(i).bounding_box()) for i in range(dels.count())]
        boxes = [b for b in boxes if b[1] is not None]
        boxes.sort(key=lambda t: t[1]["y"])
        if not boxes:
            break
        dels.nth(boxes[-1][0]).click()
        page.wait_for_timeout(800)
    log(f"  최종 품목 행수: {form.locator(PRODUCT_CELL).count()}")


_CASE_ROW_RE = re.compile(
    r"CA(\d+)\t([^\t]+)\t[^\t]+\t(\d{4}\.\s*\d{1,2}\.\s*\d{1,2}\.\s*[AP]M\s*\d{1,2}:\d{2})")


def find_today_open_case(page, subject_hint, log=print):
    """현재 Location 상세 화면(open_location 직후)의 'Cases Reported From This Site'
    관련목록에서 오늘 만들어졌고 제목이 같은 내역으로 시작하는 Case가 있는지 찾는다.

    2026-09-03 도입 배경: 보현과장님 복귀 후 이 앱을 두 사람이 동시에 쓰게 되는데,
    로컬 batch_result.json(_same_day_duplicate가 씀)은 OneDrive 동기화 지연 때문에
    상대 PC가 방금 만든 건을 못 볼 수 있다. 두 사람이 공통으로 보는 Salesforce
    자체를 직접 확인하면 이 지연 문제와 무관하게 중복을 잡을 수 있다. 관련목록은
    Location 상세 페이지에 이미 인라인으로 렌더링돼 있어(별도 페이지 이동 불필요)
    추가 네비게이션 비용이 거의 없다.

    같은 근본 원인(networkidle 타임아웃)으로 저장은 됐는데 앱이 '실패'로 오판해
    로컬 이력에 안 남는 경우([[po-create-networkidle-false-failure]])도 이걸로
    같이 잡힌다."""
    if not subject_hint:
        return None
    try:
        body = page.locator("body").inner_text()
    except Exception:
        return None
    today_tag = f"{date.today().year}. {date.today().month}. {date.today().day}."
    hint = subject_hint.strip()
    for m in _CASE_ROW_RE.finditer(body):
        case_no, subject, when = f"CA{m.group(1)}", m.group(2).strip(), m.group(3)
        if not when.startswith(today_tag):
            continue
        if subject.startswith(hint):
            log(f"  [중복의심] 오늘 이미 같은 내역의 Case 있음: {case_no} ({subject})")
            return {"case_number": case_no, "subject": subject}
    return None


def create_case_and_po(page, spec, log=print):
    """spec: {case, parts_order, hospital_search_keyword, location_exact?,
             lines: [{code, qty, price}], existing_case_url?}
    반환: {case_url, parts_order_url, status, location_name?}"""
    out = {}

    existing = spec.get("existing_case_url")
    if existing:
        log(f"기존 Case 사용: {existing}")
        try:
            page.goto(existing, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log(f"  goto 경고(무시): {e}")
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(2500)
        m = re.search(r"Parts Orders\s*[\[(](\d+)[\])]", page.locator("body").inner_text())
        if m is None:
            raise RuntimeError("Parts Orders 개수를 못 읽음 - 중복 위험이라 중단")
        if int(m.group(1)) > 0:
            out["status"] = "already_has_po"
            out["case_url"] = existing
            log(f"[중단] 이 Case에 이미 Parts Order {m.group(1)}건 있음")
            return out
        case_url = existing
    else:
        out["location_name"] = open_location(
            page, spec["hospital_search_keyword"], spec.get("location_exact"), log)
        out["location_url"] = page.url

        dup = find_today_open_case(page, (spec.get("case") or {}).get("subject", ""), log)
        if dup:
            out.update(status="duplicate_today_sf", case_number=dup["case_number"],
                      duplicate_subject=dup["subject"])
            return out

        case_url = create_case_from_location(page, spec["case"])
        log(f"Case 생성: {case_url}")
        if "vf.force.com" in case_url:
            out.update(case_url=case_url, status="case_save_failed")
            return out
    out["case_url"] = case_url

    po = spec["parts_order"]
    fr = wait_for_frame_with_text(page, "Create Billable Parts Order")
    if fr is None:
        raise RuntimeError("Create Billable Parts Order 링크를 찾지 못함")
    fr.get_by_text("Create Billable Parts Order", exact=False).first.click()
    _settle(page)                      # 다음 줄이 프레임을 폴링하므로 못 기다려도 됨
    page.wait_for_timeout(1000)

    form = wait_for_frame_with_text(page, "Create Billable Parts Order From Case")
    if form is None:
        raise RuntimeError("Parts Order 생성 폼을 찾지 못함")

    select_picklist(page, form, "Ship Via Master:", po["ship_via_master"], exact=True)
    select_picklist(page, form, "Ship Via:", po["ship_via"], exact=False)
    find_field_row(form, "Packing Instructions:").locator("textarea").first.fill(po["packing_instructions"])
    find_field_row(form, "Message For Shipper:").locator("textarea").first.fill(po["message_for_shipper"])
    fill_text_field(form, "Expected Receipt Date:", po["expected_receipt_date"])
    _fill_from_location(page, form, po["from_location"])

    for i, ln in enumerate(spec["lines"]):
        _fill_row(page, form, i, ln["code"], ln["qty"], ln["price"], log)
    _delete_trailing_empty(page, form, len(spec["lines"]), log)

    _click_save_icon(page, form)
    _wait_for_record_redirect(page)
    po_url = page.url
    log(f"Parts Order 생성: {po_url}")
    out["parts_order_url"] = po_url
    out["status"] = "po_save_failed" if "vf.force.com" in po_url else "created"
    log("※ Send To Approval은 누르지 않았습니다 - 화면 확인 후 직접 눌러주세요.")
    return out


def read_po_summary(page, po_url, tries=6, wait_ms=2500):
    """생성된 Parts Order의 번호/Case/합계/라인을 읽어온다(검증용).

    화면이 늦게 뜨면 제목에서 PO 번호를 못 읽고 None이 기록된다. PO 번호가 없으면
    나중에 승인 메일(제목의 PO 번호)과 대조가 안 돼 '승인 완료'로 안 잡힌다
    (2026-09-02 베일러의원 실측 - null로 기록돼 앱 목록에서 진행이 멈췄다).
    그래서 번호가 잡힐 때까지 폴링한다."""
    try:
        page.goto(po_url, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    m = None
    for _ in range(tries):
        page.wait_for_timeout(wait_ms)
        m = re.search(r"Parts Order:\s*(\d+)", page.title())
        if m:
            break
        try:                      # 아직이면 한 번 더 받아본다
            page.reload(wait_until="domcontentloaded", timeout=30000)
        except Exception:
            pass
    info = {"parts_order_number": m.group(1) if m else None}
    if m is None:
        print(f"  [경고] PO 번호를 못 읽음 - 나중에 _diag_backfill_po_number.py로 보정할 것 ({po_url})")

    labels = page.locator("td.labelCol")
    for i in range(labels.count()):
        try:
            lab = labels.nth(i).inner_text().strip()
            if lab in ("Case", "Total Price", "Order Status", "Account",
                       "Interface To Oracle", "Oracle Order Number"):
                val = labels.nth(i).locator("xpath=following-sibling::td[1]").first.inner_text().strip()
                info[lab] = val
        except Exception:
            continue
    return info
