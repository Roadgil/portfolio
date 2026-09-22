"""ServiceMax에서 Location 검색 -> Case 생성 -> Billable Parts Order 생성까지
전체 플로우를 수행하는 고수준 함수들. sf_form_helpers.py의 저수준 헬퍼를 사용한다.

각 함수는 예외 발생 시 그대로 raise한다 - 호출부(run_batch.py)에서 건별로
try/except 처리해서 한 건 실패가 전체를 막지 않도록 한다.
"""

from playwright.sync_api import sync_playwright
from sf_form_helpers import find_field_row, fill_text_field, select_picklist

DEBUG_PORT = 9222


def get_sf_page(context):
    for pg in context.pages:
        if "salesforce.com" in pg.url or "vf.force.com" in pg.url:
            return pg
    raise RuntimeError("Salesforce 탭을 찾지 못함")


def get_frame_with_text(page, text):
    for fr in page.frames:
        if fr.get_by_text(text, exact=False).count() > 0:
            return fr
    return None


def wait_for_frame_with_text(page, text, timeout_ms=15000, interval_ms=500):
    """VF 페이지/프레임 로딩이 환경에 따라 느릴 수 있어, 프레임을 찾을 때까지
    폴링한다. get_frame_with_text를 한 번만 호출하면 로딩 중일 때 조기 실패함."""
    waited = 0
    while waited <= timeout_ms:
        fr = get_frame_with_text(page, text)
        if fr is not None:
            return fr
        page.wait_for_timeout(interval_ms)
        waited += interval_ms
    return None


def search_and_open_location(page, hospital_name):
    """상단 검색으로 병원명을 찾아 Location이 정확히 1개면 클릭해서 연다.
    반환: (성공여부: bool, 사유: str)"""
    search_box = page.get_by_placeholder("Search...")
    search_box.click()
    search_box.fill(hospital_name)
    page.get_by_role("button", name="Search", exact=True).click()
    page.wait_for_load_state("networkidle", timeout=15000)

    # Locations 섹션 결과 개수 확인
    locations_header = page.locator("text=Locations (")
    if locations_header.count() == 0:
        return False, "Locations 섹션 없음"

    header_text = locations_header.first.inner_text()
    import re
    m = re.search(r"Locations\s*\((\d+)", header_text)
    count = int(m.group(1)) if m else 0

    if count == 0:
        return False, "Location 검색결과 0건"
    if count > 1:
        return False, f"Location 검색결과 {count}건 (애매함)"

    # 결과가 정확히 1건이면, 실제 Location명이 이메일의 병원명과 정확히 같지
    # 않아도(예: "P_모던스탠다드의원 강남" vs "모던스탠다드의원") 그 1건을 그대로 연다.
    # 메인 결과 테이블(#SVMXC__Site__c_body)의 첫 데이터 행에서 Location Name 링크
    # (Action 열의 "Edit" 링크 다음에 오는 두 번째 td의 링크)를 찾는다.
    # Location Name 셀은 <th scope="row"> (Action=td, Account=td와 구분됨)
    container = page.locator("#SVMXC__Site__c_body")
    first_row = container.locator("tr").nth(1)
    link = first_row.locator("th a").first
    link.click()
    page.wait_for_load_state("networkidle", timeout=15000)
    return True, "OK"


def create_case_from_location(page, case_fields):
    """현재 Location 상세 화면에서 Case를 생성하고 저장한다.
    case_fields: {action_taken, why_called, subject, problem_type, description, caller_last_name}
    반환: 생성된 Case의 URL (저장 후 이동한 페이지)"""
    target_frame = wait_for_frame_with_text(page, "Create Case From Location")
    if target_frame is None:
        raise RuntimeError("Create Case From Location 링크를 찾지 못함")
    target_frame.get_by_text("Create Case From Location", exact=False).first.click()
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(500)

    form_frame = wait_for_frame_with_text(page, "Create Case From Location Custom")
    if form_frame is None:
        raise RuntimeError("Case 생성 폼을 찾지 못함")

    select_picklist(page, form_frame, "Action Taken:", case_fields["action_taken"], exact=False)
    select_picklist(page, form_frame, "Why Called?:", case_fields["why_called"], exact=True)
    fill_text_field(form_frame, "Subject:", case_fields["subject"])
    select_picklist(page, form_frame, "Problem Type:", case_fields["problem_type"], exact=True)
    fill_text_field(form_frame, "Description:", case_fields["description"])
    fill_text_field(form_frame, "Caller Last Name:", case_fields["caller_last_name"])

    _click_save_icon(page, form_frame)
    _wait_for_record_redirect(page)
    return page.url


def set_case_billing_type(page, billing_type="Sales Support"):
    """Case 상세 화면(현재 그 Case 페이지에 있어야 함) 자체의 Billing Type 필드를
    바꾸고 저장한다 - Parts Order 생성 폼의 Billing Type과는 별개의 필드다.

    Non-Billable/Exchange Parts Order를 만들기 전에 반드시 이 값을 Sales Support로
    바꿔둬야 한다(실전에서 확인됨: Case가 기본값 "Billable"인 채로 두고 Parts Order를
    생성했더니 나중에 수정이 필요했음 - 생성 폼 자체의 Billing Type이 Sales Support로
    보여도 Case 쪽 값이 Billable로 남아있으면 안 됨).

    이 필드는 SVMX 폼이 아니라 Salesforce Classic 기본 인라인 편집 방식이다 -
    라벨 셀(td.labelCol) 옆 값 셀을 더블클릭하면 그 자리에 select가 나타나고,
    페이지 상단/하단에 별도의 Save 버튼(input[title='Save'])이 생긴다."""
    label = page.locator("td.labelCol", has_text="Billing Type")
    if label.count() == 0:
        raise RuntimeError("Case 화면에서 Billing Type 라벨을 찾지 못함")
    value_cell = label.first.locator("xpath=following-sibling::td[1]")
    value_cell.scroll_into_view_if_needed()
    value_cell.dblclick()
    page.wait_for_timeout(600)

    selects = page.locator("select")
    target = None
    for i in range(selects.count()):
        el = selects.nth(i)
        if el.is_visible():
            target = el
            break
    if target is None:
        raise RuntimeError("Billing Type 인라인 편집 select를 찾지 못함")
    target.select_option(label=billing_type)

    page.locator("input[title='Save']").first.click()
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(800)

    # 이 Save 직후에는 Service Flow Wizards 쪽 비동기 프레임(예: Create
    # Non-Billable/Exchange Parts Order 위저드)이 아직 준비되지 않은 상태가
    # 실전에서 반복 재현됨 - reload로 한 번 완전히 다시 그리게 하면 안정적으로
    # 잡힌다(단순히 더 오래 기다리는 것만으로는 불충분했음).
    page.reload()
    page.wait_for_load_state("networkidle", timeout=20000)
    page.wait_for_timeout(1000)


def _click_save_icon(page, form_frame):
    """폼 상단의 저장(디스크) 아이콘 클릭. 실제 DOM에서 확인된 클래스명 사용
    (title/alt 속성이 없어서 텍스트 기반으로는 못 찾음)."""
    icon = form_frame.locator(".svmx-sfmd-save-icon").first
    icon.click()


def _wait_for_record_redirect(page, timeout_ms=15000):
    """Save 클릭 후 vf.force.com 폼 화면을 벗어나 실제 레코드 화면
    (my.salesforce.com/<recordId>)으로 리다이렉트될 때까지 기다린다.
    필수 필드 누락 등으로 저장이 실패하면 그대로 폼에 머물러 있으므로,
    호출부에서 반환된 URL이 여전히 vf.force.com이면 저장 실패로 간주할 수 있다.

    2026-09-03 실전 확인: URL이 이미 레코드 화면으로 바뀐 뒤(=저장은 이미 성공)에도
    Lightning 배경 폴링 때문에 networkidle을 15초 안에 못 잡는 경우가 있다(특히
    같은 자동화 브라우저에서 다른 탭이 동시에 돌 때 - 데이뷰의원 강서 00601242 건,
    FSE PO 스캔과 겹친 순간 재현). 그때까지는 이 줄만 try/except 없이 그대로
    두어서, 저장은 이미 끝난 Case를 "실패"로 잘못 보고하고 이력에도 안 남는
    고아 레코드가 생겼다(CA1472257, 뒤에 existing_case_url로 수동 이어붙임).
    URL 확인이 이미 성공 여부의 진짜 근거이므로 networkidle은 참고용 대기로만
    쓰고 실패해도 진행한다."""
    try:
        page.wait_for_url(lambda url: "vf.force.com" not in url, timeout=timeout_ms)
    except Exception:
        pass
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(800)


def create_parts_order_from_case(page, po_fields):
    """현재 Case 상세 화면에서 Billable Parts Order를 생성하고 저장한다.
    po_fields: dict from map_to_servicemax.py의 parts_order 섹션 + item_name(제품명 힌트)
    반환: 저장 후 페이지 URL"""
    target_frame = wait_for_frame_with_text(page, "Create Billable Parts Order")
    if target_frame is None:
        raise RuntimeError("Create Billable Parts Order 링크를 찾지 못함")
    target_frame.get_by_text("Create Billable Parts Order", exact=False).first.click()
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(800)

    form_frame = wait_for_frame_with_text(page, "Create Billable Parts Order From Case")
    if form_frame is None:
        raise RuntimeError("Parts Order 생성 폼을 찾지 못함")

    select_picklist(page, form_frame, "Ship Via Master:", po_fields["ship_via_master"], exact=True)
    select_picklist(page, form_frame, "Ship Via:", po_fields["ship_via"], exact=False)

    row = find_field_row(form_frame, "Packing Instructions:")
    row.locator("textarea").first.fill(po_fields["packing_instructions"])
    row = find_field_row(form_frame, "Message For Shipper:")
    row.locator("textarea").first.fill(po_fields["message_for_shipper"])

    fill_text_field(form_frame, "Expected Receipt Date:", po_fields["expected_receipt_date"])

    _fill_from_location(page, form_frame, po_fields["from_location"])
    _fill_product_line(page, form_frame, po_fields["product_code"],
                        po_fields["expected_qty"], po_fields["line_price"])

    _click_save_icon(page, form_frame)
    _wait_for_record_redirect(page)
    return page.url


def _fill_from_location(page, form_frame, location_code):
    row = find_field_row(form_frame, "From Location:")
    text_input = row.locator("input[type='text']").first
    text_input.click()
    text_input.fill(location_code)
    page.wait_for_timeout(300)

    icons = form_frame.locator(".svmx_lookup_icon")
    visible_indices = [i for i in range(icons.count()) if icons.nth(i).is_visible()]
    if not visible_indices:
        raise RuntimeError("From Location lookup 아이콘을 찾지 못함")
    icons.nth(visible_indices[0]).click()
    page.wait_for_timeout(1200)

    _select_first_visible_result(page, location_code)


def _visible_icon_boxes(icons):
    boxes = []
    for i in range(icons.count()):
        ic = icons.nth(i)
        if not ic.is_visible():
            continue
        box = ic.bounding_box()
        if box is not None:
            boxes.append(box)
    return boxes


def _box_in(box, box_list, tolerance=3):
    for b in box_list:
        if abs(box["x"] - b["x"]) <= tolerance and abs(box["y"] - b["y"]) <= tolerance:
            return True
    return False


def _fill_product_line(page, form_frame, product_code, qty, line_price):
    page.keyboard.press("Escape")
    # From Location 팝업이 방금 닫힌 직후라 그리드 재렌더링/포커스 이동이 아직
    # 진행 중일 수 있음 - 충분히 가라앉을 시간을 준다.
    page.wait_for_timeout(1000)

    cells = form_frame.locator("td.svmx-grid-cell-gridcolumn-1103")
    n = cells.count()
    if n != 1:
        raise RuntimeError(f"Product 셀이 {n}개 발견됨 (1개여야 정상) - 그리드에 예상치 못한 행이 있음")

    cell = cells.first
    cell_box = cell.bounding_box()

    # 이 그리드는 (비어있는) 마지막 행을 처음 건드리는 순간 바로 다음 빈
    # placeholder 행을 추가하면서 편집 포커스를 새 행의 "첫번째 칸"(Warehouse)
    # 으로 빼앗아가는 버릇이 있다 - 그래서 Product 셀을 더블클릭했는데 실제
    # 입력창은 엉뚱하게 Warehouse 칸 위치에 뜨는 현상이 실전에서 반복 재현됨.
    # 첫 더블클릭은 "찔러보기"로 취급해 이 현상을 트리거시키고, 생긴 빈 행을
    # 지운 뒤 다시 한번 더블클릭해야 실제로 Product 칸에서 편집이 시작된다.
    cell.scroll_into_view_if_needed()
    cell.dblclick()
    page.wait_for_timeout(1000)
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

    cells_after_prime = form_frame.locator("td.svmx-grid-cell-gridcolumn-1103")
    if cells_after_prime.count() == 2:
        delete_icons = form_frame.locator(".svmx-sfmd-delete-icon")
        boxes = [(i, delete_icons.nth(i).bounding_box()) for i in range(delete_icons.count())]
        boxes = [b for b in boxes if b[1] is not None]
        boxes.sort(key=lambda t: t[1]["y"])
        if boxes:
            delete_icons.nth(boxes[-1][0]).click()
            page.wait_for_timeout(800)

    cells = form_frame.locator("td.svmx-grid-cell-gridcolumn-1103")
    n = cells.count()
    if n != 1:
        raise RuntimeError(f"찔러보기 이후 Product 셀이 {n}개 (1개여야 정상)")
    cell = cells.first
    cell_box = cell.bounding_box()

    # ExtJS 리스트/팝업 잔재로 인해 이전 필드(From Location)의 lookup 아이콘이
    # 여전히 DOM에 "보이는" 상태로 남아있을 수 있어, "마지막으로 보이는 아이콘"
    # 같은 DOM-순서 기반 판단은 신뢰할 수 없음(실전에서 반복 재현됨: From Location
    # 아이콘을 잘못 클릭해 엉뚱한 Location search 팝업이 뜸). 대신 Product 셀을
    # 편집모드로 만들기 "전"에 보이던 아이콘 위치들을 기억해두고, 편집모드 진입
    # "후"에 새로 나타난 아이콘(= Product 전용 lookup 아이콘)만 클릭한다.
    icons = form_frame.locator(".svmx_lookup_icon")
    boxes_before = _visible_icon_boxes(icons)

    cell.scroll_into_view_if_needed()
    cell.dblclick()
    page.wait_for_timeout(1000)

    # 실제로 Product 칸 위치에서 편집이 시작됐는지 확인 - 여전히 엉뚱한 칸이면
    # 한번 더 더블클릭을 재시도한다.
    for attempt in range(3):
        inputs = form_frame.locator("input[type='text']")
        active_in_range = False
        for i in range(inputs.count()):
            inp = inputs.nth(i)
            if not inp.is_visible():
                continue
            box = inp.bounding_box()
            if box is None:
                continue
            if abs(box["y"] - cell_box["y"]) < 15 and \
               cell_box["x"] - 10 <= box["x"] <= cell_box["x"] + cell_box["width"]:
                active_in_range = True
                break
        if active_in_range:
            break
        cell.dblclick()
        page.wait_for_timeout(800)

    page.keyboard.type(product_code)
    page.wait_for_timeout(600)

    def in_product_x_range(box):
        return cell_box is not None and \
            cell_box["x"] <= box["x"] <= cell_box["x"] + cell_box["width"]

    # 반드시 Product 열 x범위 안에 있는 아이콘만 후보로 삼는다. x범위 밖의
    # "새로 나타난" 아이콘(예: 다른 필드의 comment 아이콘이 스크롤 위치에 따라
    # boxes_before에 잡히지 않았던 경우)을 잘못 클릭해 엉뚱한 팝업이 열리는
    # 문제가 실전에서 반복 재현됨 - 위치 조건을 필수로 강제한다.
    target_icon = None
    for attempt in range(20):
        icons = form_frame.locator(".svmx_lookup_icon")
        new_in_range = None
        old_in_range = None
        for i in range(icons.count()):
            ic = icons.nth(i)
            if not ic.is_visible():
                continue
            box = ic.bounding_box()
            if box is None or not in_product_x_range(box):
                continue
            if not _box_in(box, boxes_before):
                if new_in_range is None:
                    new_in_range = ic
            elif old_in_range is None:
                old_in_range = ic
        target_icon = new_in_range or old_in_range
        if target_icon is not None:
            break
        page.wait_for_timeout(400)

    if target_icon is None:
        raise RuntimeError("Product lookup 아이콘을 찾지 못함")
    target_icon.click()
    page.wait_for_timeout(1500)

    _select_first_visible_result(page, product_code)

    # 팝업에서 선택한 뒤 실제 행에 Product/Product Code/가격 등이 채워지기까지
    # 서버 조회(비동기)가 걸릴 수 있어 최대 15초 정도 폴링한다. gridcolumn-1103
    # ("Product")은 품명/설명 텍스트가 표시되는 칸이라 product_code가 그대로
    # 나타나지 않는다 - 실제 코드가 그대로 보이는 gridcolumn-1105("Product Code")
    # 칸으로 검증해야 한다.
    product_code_cells = form_frame.locator("td.svmx-grid-cell-gridcolumn-1105")
    first_code_text = ""
    for attempt in range(20):
        if product_code_cells.count() > 0:
            first_code_text = product_code_cells.first.inner_text().strip()
            if product_code in first_code_text:
                break
        page.wait_for_timeout(750)

    product_cells = form_frame.locator("td.svmx-grid-cell-gridcolumn-1103")
    cells_after = product_cells.count()
    if cells_after == 2:
        # 이 그리드는 값이 커밋되면 자동으로 다음 빈 placeholder 행을 추가한다
        # (Ver2 폼의 정상 동작). 첫 행에 값이 들어갔는지 확인하고, 남은 빈 두번째
        # 행은 저장 전에 지운다 - 안 지우고 저장을 시도하면 실패하는 경우가 있었음.
        second_text = product_cells.nth(1).inner_text()
        if product_code not in first_code_text or second_text.strip():
            raise RuntimeError(
                f"Product 선택 후 예상과 다른 상태 (Product Code 행1={first_code_text!r}, Product 행2={second_text!r})"
            )
        delete_icons = form_frame.locator(".svmx-sfmd-delete-icon")
        if delete_icons.count() < 2:
            raise RuntimeError(f"빈 행을 지우려 했으나 삭제 아이콘이 {delete_icons.count()}개뿐임")
        boxes = [(i, delete_icons.nth(i).bounding_box()) for i in range(delete_icons.count())]
        boxes = [b for b in boxes if b[1] is not None]
        boxes.sort(key=lambda t: t[1]["y"])
        delete_icons.nth(boxes[-1][0]).click()
        page.wait_for_timeout(800)
        cells_after = form_frame.locator("td.svmx-grid-cell-gridcolumn-1103").count()

    if cells_after != 1:
        raise RuntimeError(f"Product 선택 후 행이 {cells_after}개가 됨 (1개여야 정상)")
    if product_code not in first_code_text:
        raise RuntimeError(f"Product Code가 '{product_code}'로 설정되지 않음 (실제: {first_code_text!r})")

    qty_cell = form_frame.locator("td.svmx-grid-cell-gridcolumn-1106").first
    qty_cell.dblclick()
    page.wait_for_timeout(400)
    page.keyboard.press("Control+A")
    page.keyboard.type(str(qty))
    page.wait_for_timeout(200)

    price_cell = form_frame.locator("td.svmx-grid-cell-gridcolumn-1107").first
    price_cell.dblclick()
    page.wait_for_timeout(400)
    page.keyboard.press("Control+A")
    page.keyboard.type(str(line_price))
    page.wait_for_timeout(200)

    page.keyboard.press("Tab")
    page.wait_for_timeout(300)

    checkbox_cell = form_frame.locator("td.svmx-grid-cell-svmx-columncheck-1109").first
    is_checked = "svmx-grid-checkheader-checked" in (checkbox_cell.inner_html() or "")
    if is_checked:
        checkbox_cell.click()
        page.wait_for_timeout(300)


def create_non_billable_parts_order_from_case(page, po_fields):
    """현재 Case 상세 화면에서 Non-Billable/Exchange Parts Order를 생성하고 저장한다.
    po_fields: dict from map_to_servicemax.py의 map_manual_record_non_billable()
    parts_order 섹션 (order_type, non_billable_category, billing_type,
    from_location, message_for_shipper, expected_receipt_date, product_code,
    expected_qty, ib_serial_to_return, fault_on).

    Billable Parts Order 폼과 달리 이 폼(Create Non-Billable/Exchange Parts Order
    From Case)에는 ExtJS Product 그리드가 없다 - "Part To Be Shipped"가 단일 lookup
    필드라 라벨과 같은 행(tr) 안에서만 lookup 아이콘을 찾으면 되고(프레임 전체에서
    "보이는 아이콘 순서"를 추측할 필요가 없음 - 라이브로 확인됨), 저장하면 Qty=1인
    라인이 하나 생성된다.

    주의: expected_qty가 1이 아닌 경우 이 함수는 그 값을 반영하지 못한다 - 이 폼
    자체에 Qty 입력이 없기 때문에, 저장 후 Parts Order Line을 별도로 수정하는
    로직이 필요하다(아직 미구현 - 실제로 수량>1인 요청이 들어오면 그 화면을 먼저
    라이브로 확인하고 추가할 것. map_to_servicemax.py가 이 경우 warnings에 남겨둠).

    반환: 저장 후 페이지 URL"""
    target_frame = wait_for_frame_with_text(page, "Create Non-Billable/Exchange Parts Order")
    if target_frame is None:
        raise RuntimeError("Create Non-Billable/Exchange Parts Order 링크를 찾지 못함")
    target_frame.get_by_text("Create Non-Billable/Exchange Parts Order", exact=False).first.click()
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(800)

    form_frame = wait_for_frame_with_text(page, "Create Non-Billable/Exchange Parts Order From Case")
    if form_frame is None:
        raise RuntimeError("Non-Billable/Exchange Parts Order 생성 폼을 찾지 못함")

    select_picklist(page, form_frame, "Order type:", po_fields["order_type"], exact=True)

    if po_fields.get("non_billable_category"):
        select_picklist(page, form_frame, "Non Billable Category:", po_fields["non_billable_category"], exact=True)

    select_picklist(page, form_frame, "Billing Type:", po_fields.get("billing_type", "Sales Support"), exact=True)

    if po_fields.get("fault_on"):
        select_picklist(page, form_frame, "Fault On:", po_fields["fault_on"], exact=True)

    _fill_lookup_field_by_row(page, form_frame, "Part To Be Shipped:", po_fields["product_code"])

    if po_fields.get("ib_serial_to_return"):
        _fill_lookup_field_by_row(page, form_frame, "IB Serial To Return:", po_fields["ib_serial_to_return"])

    _fill_lookup_field_by_row(page, form_frame, "From Location:", po_fields["from_location"])

    if po_fields.get("message_for_shipper"):
        row = find_field_row(form_frame, "Message For Shipper:")
        row.locator("textarea").first.fill(po_fields["message_for_shipper"])

    fill_text_field(form_frame, "Expected Receipt Date:", po_fields["expected_receipt_date"])

    _click_save_icon(page, form_frame)
    _wait_for_record_redirect(page)
    return page.url


def _fill_lookup_field_by_row(page, frame, label_text, search_text):
    """라벨과 같은 행(tr) 범위 안에서만 lookup 아이콘을 찾아 클릭한다.
    Billable 폼의 Product 그리드(_fill_product_line)는 편집모드 진입 전/후로
    새로 나타나는 아이콘을 프레임 전체에서 구분해야 했지만, 이 폼의 lookup
    필드들(Part To Be Shipped/IB Serial To Return/From Location)은 그리드가 아닌
    고정된 행이라 행 범위로 좁히는 것만으로 충분하다(라이브로 확인됨)."""
    row = find_field_row(frame, label_text)
    text_input = row.locator("input[type='text']").first
    text_input.click()
    text_input.fill(search_text)
    page.wait_for_timeout(400)
    icon = row.locator(".svmx_lookup_icon").first
    icon.click()
    page.wait_for_timeout(1200)
    _select_first_visible_result(page, search_text)


def _select_first_visible_result(page, search_text, retries=6, retry_wait_ms=500):
    # 검색 팝업이 네트워크 응답을 기다리는 동안 결과 행이 비어있게 렌더링될 수
    # 있으므로, 바로 실패 처리하지 않고 잠깐씩 재시도한다.
    candidates = page.get_by_text(search_text, exact=True)
    for attempt in range(retries):
        n = candidates.count()
        for i in range(n):
            el = candidates.nth(i)
            if el.is_visible():
                _click_result_and_select(page, el)
                return
        page.wait_for_timeout(retry_wait_ms)
    raise RuntimeError(f"검색 팝업에서 '{search_text}' 결과를 찾지 못함")


def _click_result_and_select(page, el):
    el.click()
    page.wait_for_timeout(400)
    # 팝업에 따라 행 클릭만으로 바로 선택/닫힘 처리되는 경우가 있어
    # Select 버튼이 실제로 남아있을 때만 클릭한다.
    select_btn = page.get_by_role("button", name="Select")
    if select_btn.count() > 0 and select_btn.first.is_visible():
        select_btn.first.click()
        page.wait_for_timeout(800)
