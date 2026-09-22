# -*- coding: utf-8 -*-
"""
oracle_shipment_tracking.py - 오라클 Manage Shipments의 Tracking # 기입 자동화

배경(2026-09-11 사용자 지시): WAY(미국)향 수출(Rebalance/RMA 모두 포함)을 FedEx로
arrange하면 fedex_ship_watcher.py의 track 단계가 수출신고실적 B/L번호 +
SharePoint Tracking Number를 채운다. 여기에 오라클 Shipment 레코드에도 같은 AWB를
넣어야 한다는 요청이 추가됐다 - 대상 필드는 사용자 확인: **Tracking #**
(Additional Information 섹션, Waybill 필드 아님).

수동 절차(사용자 설명):
  Shipment > Manage Shipment 진입 -> Shipment 번호로 검색 -> 해당 건 열기 ->
  Tracking # 입력 -> 저장.

이 파일의 navigate_to_manage_shipments()는 ship_confirm_watcher.py의
navigate_to_manage_shipment_lines()와 같은 골격(Tasks 패널 -> Shipments 카테고리)
이고, 작업 이름만 'Manage Shipments'로 다르다.

실행 방법:
  python oracle_shipment_tracking.py write <Shipment#> <Tracking#>
  python oracle_shipment_tracking.py backfill   # 8/15 이후 WAY행 일괄 처리(수출신고실적에서 자동 추출)
"""

from __future__ import annotations

import os
import re
import sys
import time
import argparse
import datetime as _dt

ICBL_DIR = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\10. 수입\인천관세법인 C.I 확인"
)
sys.path.insert(0, ICBL_DIR)
from icbl_ci_watcher import (  # noqa: E402
    ensure_edge_running,
    get_oracle_driver_isolated,
    close_driver,
    is_session_dead_error,
    exc_detail,
    sso_relogin,
    recover_oracle_login,
    oracle_is_logged_in,
    OracleLoginRequired,
    ORACLE_HOME_URL,
    _click_text,
    _js_click_text,
    tasks_panel_open,
    wait_or_sleep,
    text_visible,
    element_present,
    _wait_find,
)

ROOT = os.path.dirname(__file__)
LOG_PATH = os.path.join(ROOT, "oracle_shipment_tracking.log")

EXPORT_DECLARATION_PATH = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\12. 수출\수출신고실적20260126~.xlsx"
)

INV_PAGE_READY_TIMEOUT_SEC = 40

# 2026-09-11 사용자 지시: WAY(미국)향만 대상. Rebalance/RMA 둘 다 포함(Purpose로
# 거르지 않는다 - Destination만 본다). 2026-09-16 수정: RMA는 수출신고실적에
# Destination="FA LAB"로 기입되므로([[rebalance-rma-branch]]) "WAY" 단일값
# 비교로는 RMA가 전부 빠졌었다(주석의 의도와 실제 코드가 어긋난 사례,
# fedex_ship_watcher.update_export_declaration_bl과 같은 버그) - 집합으로 바꿈.
TARGET_DESTINATIONS = {"WAY", "FA LAB"}
BACKFILL_CUTOFF = _dt.datetime(2026, 8, 15)


def log(msg: str):
    line = f"[{_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"))
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _save_diag(driver, tag: str) -> str:
    path = os.path.join(ROOT, f"_diag_oracletrack_{tag}_{_dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    try:
        driver.save_screenshot(path)
        log(f"  [진단] 화면 캡처: {os.path.basename(path)} (URL: {driver.current_url})")
    except Exception as e:
        log(f"  [진단] 스크린샷 실패: {e}")
    return path


# ==============================================================
# 8/15 이후 WAY행 추출(수출신고실적에서 SO/Delivery Number/B_L번호)
# ==============================================================
def find_way_shipments_since(cutoff: _dt.datetime = BACKFILL_CUTOFF) -> list[dict]:
    """수출신고실적에서 Destination=WAY, 신고일>=cutoff인 행들의
    {to_number, shipment_no, awb, date, purpose}를 (SO, Delivery Number) 단위로
    중복 없이 반환. B/L번호가 비어있거나 N/A인 행은 건너뜀(AWB 없으면 기입할 게 없음)."""
    import openpyxl

    wb = openpyxl.load_workbook(EXPORT_DECLARATION_PATH, data_only=True, read_only=True)
    ws = wb["Sheet1"]
    seen: dict[tuple, dict] = {}
    for r in ws.iter_rows(min_row=2, values_only=True):
        dest = str(r[0] or "")
        if dest not in TARGET_DESTINATIONS:
            continue
        d = r[2]
        if not isinstance(d, _dt.datetime) or d < cutoff:
            continue
        awb = str(r[3] or "").strip()
        if not awb or awb.upper() == "N/A":
            continue
        so = str(r[10] or "").strip()
        dn_raw = str(r[11] or "").strip()
        if not so or not dn_raw:
            continue
        # Delivery Number가 "9976051/9976055"처럼 여러 개일 수 있음(같은 CI, 배송 쪼개짐).
        for dn in re.split(r"[\/,]", dn_raw):
            dn = dn.strip()
            if not dn:
                continue
            key = (so, dn)
            if key not in seen:
                seen[key] = {
                    "to_number": so, "shipment_no": dn, "awb": awb,
                    "date": d.strftime("%Y-%m-%d"), "purpose": str(r[1] or ""),
                }
    wb.close()
    return sorted(seen.values(), key=lambda x: x["date"])


# ==============================================================
# 오라클 Manage Shipments 네비게이션 + Tracking # 기입
# ==============================================================
def navigate_to_manage_shipments(driver):
    """Home -> Supply Chain Execution -> Inventory Management -> Tasks ->
    Shipments 카테고리 -> Manage Shipments.
    ship_confirm_watcher.navigate_to_manage_shipment_lines()와 같은 골격,
    작업 이름만 다르다(재시도 2회 동일 이유)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    last_err = None
    for attempt in range(2):
        try:
            driver.get(ORACLE_HOME_URL)
            wait_or_sleep(driver, text_visible("Supply Chain Execution"), 5)
            _js_click_text(driver, "Supply Chain Execution")
            time.sleep(3)
            _js_click_text(driver, "Inventory Management")
            wait_or_sleep(driver, element_present(By.XPATH, "//img[@title='Tasks']"), 5)

            tasks_icon = _wait_find(driver, By.XPATH, "//img[@title='Tasks']",
                                     timeout=INV_PAGE_READY_TIMEOUT_SEC)
            if not tasks_panel_open(driver):
                driver.execute_script("arguments[0].click();", tasks_icon)
            wait_or_sleep(driver, element_present(
                By.XPATH, "//select[option[normalize-space(text())='Shipments']]"), 2)

            sel_el = _wait_find(driver, By.XPATH,
                                 "//select[option[normalize-space(text())='Shipments']]",
                                 timeout=INV_PAGE_READY_TIMEOUT_SEC)
            Select(sel_el).select_by_visible_text("Shipments")
            wait_or_sleep(driver, text_visible("Manage Shipments"), 2)

            if os.environ.get("_ORACLE_TRACK_DIAG_TASKS"):
                _save_diag(driver, "tasks_shipments_category")
                task_texts = [el.text.strip() for el in driver.find_elements(
                    By.XPATH, "//a | //span") if el.is_displayed() and el.text.strip()]
                log("[진단] Shipments 카테고리 화면의 텍스트 후보: "
                    + " | ".join(sorted(set(t for t in task_texts if len(t) < 40))))

            _js_click_text(driver, "Manage Shipments")
            wait_or_sleep(driver, element_present(
                By.XPATH, "//input[normalize-space(@aria-label)='Shipment']"), 5)
            return
        except Exception as e:
            last_err = e
            log(f"[경고] Manage Shipments 네비게이션 실패(시도 {attempt + 1}/2): {exc_detail(e)}")
    raise last_err


def _search_shipment(driver, shipment_no: str) -> None:
    """Manage Shipments 화면에서 Shipment 번호로 검색.

    2026-09-11 실측: 정확히 일치하는 건 하나뿐이면 Enter만으로 결과 목록을
    거치지 않고 바로 Edit Shipment 화면으로 넘어간다(별도 링크 클릭 불필요).
    그래도 목록이 뜨는 경우에 대비해, 먼저 Edit Shipment 진입을 기다리고
    안 되면 결과 링크 클릭을 시도한다."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    box = _wait_find(driver, By.XPATH, "//input[normalize-space(@aria-label)='Shipment']", timeout=10)
    box.click()
    box.send_keys(shipment_no)
    box.send_keys(Keys.ENTER)

    def _on_edit_page():
        els = driver.find_elements(By.XPATH, "//*[contains(text(),'Edit Shipment:')]")
        return any(shipment_no in (el.text or "") for el in els if el.is_displayed())

    deadline = time.time() + 30
    while time.time() < deadline and not _on_edit_page():
        # 목록 화면이면 결과 링크를 클릭해본다(직접 진입 안 된 경우의 폴백).
        cands = [el for el in driver.find_elements(
            By.XPATH, f"//a[normalize-space(text())='{shipment_no}']") if el.is_displayed()]
        if cands:
            try:
                cands[0].click()
            except Exception:
                driver.execute_script("arguments[0].click();", cands[0])
        time.sleep(1)

    if not _on_edit_page():
        _save_diag(driver, f"search_no_result_{shipment_no}")
        raise RuntimeError(f"Manage Shipments에서 Shipment {shipment_no}의 Edit 화면으로 못 들어감")
    log(f"[Oracle] Edit Shipment {shipment_no} 화면 진입 확인")


def _fill_tracking_number(driver, shipment_no: str, tracking_no: str) -> None:
    """Additional Information 섹션의 Tracking # 필드에 값 기입(이미 값이 있고
    같으면 건드리지 않음 - 재실행 안전)."""
    from selenium.webdriver.common.by import By

    # 섹션이 접혀 있을 수 있어(2026-09-11 실측: 기본이 접힘) 필드가 안 보이면
    # 헤더를 펼친다. 헤더 텍스트가 accesskey 밑줄 표시로 여러 자식 노드로
    # 쪼개질 수 있어(rebalance_watcher/ship_confirm_watcher와 같은 함정)
    # textContent 기준 JS 클릭 헬퍼를 쓴다.
    if not any(el.is_displayed() for el in driver.find_elements(
            By.XPATH, "//*[normalize-space(text())='Tracking #']")):
        # 2026-09-11 사용자 확인: "additional information 왼쪽에 화살표 누르면
        # 기입하는 창 열려" - 텍스트가 아니라 왼쪽 삼각형(disclosure) 아이콘이
        # 실제 토글이다. 보이는 "Additional Information" 텍스트 요소를 찾고,
        # 같은 헤더 행(가장 가까운 공통 조상) 안에서 아이콘 요소를 눌러본다.
        visible_headers = [el for el in driver.find_elements(
            By.XPATH, "//*[normalize-space(text())='Additional Information']") if el.is_displayed()]
        if not visible_headers:
            _save_diag(driver, f"additional_info_header_not_found_{shipment_no}")
            raise RuntimeError(f"Shipment {shipment_no}: 'Additional Information' 헤더를 못 찾음")
        # 2026-09-11 사용자 확인: 텍스트 왼쪽의 삼각형을 눌러야 열린다. 여러
        # 지점을 한꺼번에 다 클릭하면 같은 토글 링크를 여러 번 눌러 도로
        # 닫혀버리는 것이 실측됨(짝수 번 클릭=순변화 없음) - 한 지점씩 클릭하고
        # 즉시 펼쳐졌는지 확인, 펼쳐지면 더 누르지 않고 멈춘다.
        click_one_script = """
        var textEl = arguments[0];
        var offset = arguments[1];
        var r = textEl.getBoundingClientRect();
        var y = r.top + r.height/2;
        var x = r.left - offset;
        if (x < 0) return 'skip-negative-x';
        var el = document.elementFromPoint(x, y);
        if (!el) return 'no-element-at-point';
        el.click();
        return el.tagName + '.' + (el.className||'');
        """
        for offset in (18, 14, 22, 26, 30, 10):
            fresh = [el for el in driver.find_elements(
                By.XPATH, "//*[normalize-space(text())='Additional Information']") if el.is_displayed()]
            if not fresh:
                break
            try:
                hit = driver.execute_script(click_one_script, fresh[0], offset)
            except Exception as e:
                log(f"  [정보] {offset}px 클릭 중 예외({exc_detail(e)}) - 다음 지점 시도")
                continue
            log(f"  [정보] 'Additional Information' 좌측 {offset}px 지점 클릭: {hit}")
            wait_or_sleep(driver, element_present(
                By.XPATH, "//*[normalize-space(text())='Tracking #']"), 2)
            if any(el.is_displayed() for el in driver.find_elements(
                    By.XPATH, "//*[normalize-space(text())='Tracking #']")):
                log("  [정보] Additional Information 펼침 확인 - 추가 클릭 중단")
                break
        time.sleep(1)

    if not any(el.is_displayed() for el in driver.find_elements(
            By.XPATH, "//*[normalize-space(text())='Tracking #']")):
        _save_diag(driver, f"additional_info_not_expanded_{shipment_no}")

    # label을 쓰고 바로 이어서 참조하면 방금 있었던 재렌더 때문에
    # StaleElementReferenceException이 났다(2026-09-11 실측) - label과 input을
    # 각각 driver 기준 새 쿼리로 조회해 참조를 안 남긴다.
    label = _wait_find(driver, By.XPATH, "//*[normalize-space(text())='Tracking #']", timeout=10)
    field = None
    input_id = label.get_attribute("for")
    if input_id:
        cands = driver.find_elements(By.ID, input_id)
        if cands:
            field = cands[0]
    if field is None:
        cands = driver.find_elements(
            By.XPATH, "//*[normalize-space(text())='Tracking #']/following::input[1]")
        if cands:
            field = cands[0]
    if field is None:
        _save_diag(driver, f"trackingfield_notfound_{shipment_no}")
        raise RuntimeError(f"Shipment {shipment_no}: Tracking # 입력창을 못 찾음")

    current = (field.get_attribute("value") or "").strip()
    if current == str(tracking_no).strip():
        log(f"[Oracle] Shipment {shipment_no}: Tracking #가 이미 {tracking_no}로 동일 - 건드리지 않음")
        return
    if current:
        log(f"[경고] Shipment {shipment_no}: Tracking #에 다른 값이 이미 있음"
            f"(기존={current!r}, 새 값={tracking_no!r}) - 덮어씀")

    field.click()
    field.send_keys(__import__("selenium.webdriver.common.keys", fromlist=["Keys"]).Keys.CONTROL, "a")
    field.send_keys(tracking_no)
    driver.switch_to.active_element.send_keys("\t")
    time.sleep(1)
    log(f"[Oracle] Shipment {shipment_no}: Tracking # = {tracking_no} 입력")


def _click_save(driver, shipment_no: str) -> None:
    """상단 Save 클릭(accesskey 밑줄로 텍스트가 쪼개질 수 있어 JS textContent 매칭)."""
    from selenium.webdriver.common.by import By

    script = """
        var els = document.querySelectorAll('button, a');
        for (var i=0;i<els.length;i++){
            var t = (els[i].textContent || '').replace(/\\s+/g, ' ').trim();
            if (t === 'Save') {
                var rect = els[i].getBoundingClientRect();
                if (rect.width>0 && rect.height>0 && !els[i].disabled){
                    els[i].scrollIntoView(true);
                    els[i].click();
                    return true;
                }
            }
        }
        return false;
        """
    clicked = driver.execute_script(script)
    if not clicked:
        _save_diag(driver, f"save_button_notfound_{shipment_no}")
        raise RuntimeError(f"Shipment {shipment_no}: Save 버튼을 못 찾음")
    time.sleep(3)

    # 저장 후 경고/확인 다이얼로그가 뜨면 OK로 닫는다(예: Closed 배송 재저장 경고).
    ok_btns = [el for el in driver.find_elements(By.XPATH, "//*[normalize-space(text())='OK']") if el.is_displayed()]
    if ok_btns:
        driver.execute_script("arguments[0].click();", ok_btns[-1])
        time.sleep(1)
    log(f"[Oracle] Shipment {shipment_no}: Save 클릭 완료")


def write_tracking_number_to_oracle_shipment(shipment_no: str, tracking_no: str) -> None:
    """공개 진입점 - 공유 Edge를 열어 Manage Shipments에서 이 Shipment의
    Tracking #를 채우고 저장한 뒤 탭을 닫는다."""
    ensure_edge_running()
    driver = get_oracle_driver_isolated()
    try:
        if not oracle_is_logged_in(driver):
            recover_oracle_login(driver)
        navigate_to_manage_shipments(driver)
        _search_shipment(driver, shipment_no)
        _fill_tracking_number(driver, shipment_no, tracking_no)
        _click_save(driver, shipment_no)
    except OracleLoginRequired:
        raise
    finally:
        close_driver(driver)


def backfill(cutoff: _dt.datetime = BACKFILL_CUTOFF) -> None:
    rows = find_way_shipments_since(cutoff)
    log(f"[백필] WAY, {cutoff.date()} 이후, AWB 있는 shipment {len(rows)}건")
    for row in rows:
        log(f"  - TO {row['to_number']} / Shipment {row['shipment_no']} / AWB {row['awb']} "
            f"({row['date']}, {row['purpose']})")
    ok, fail = 0, 0
    for row in rows:
        try:
            write_tracking_number_to_oracle_shipment(row["shipment_no"], row["awb"])
            ok += 1
        except Exception as e:
            fail += 1
            log(f"[실패] Shipment {row['shipment_no']}: {exc_detail(e)}")
    log(f"[백필 완료] 성공 {ok}건 / 실패 {fail}건")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_write = sub.add_parser("write")
    p_write.add_argument("shipment_no")
    p_write.add_argument("tracking_no")

    sub.add_parser("backfill")

    p_find = sub.add_parser("find")

    args = parser.parse_args()
    if args.cmd == "write":
        write_tracking_number_to_oracle_shipment(args.shipment_no, args.tracking_no)
    elif args.cmd == "backfill":
        backfill()
    elif args.cmd == "find":
        for row in find_way_shipments_since():
            print(row)
