# -*- coding: utf-8 -*-
"""Oracle Order Number 1건을 Transfer order로 SP release(부품이라 SP 1회로 충분),
backorder가 나오면 FG를 추가로 1회 더 돈다. FG는 재시도하지 않는다(2026-09-01
사용자 확인 - "냅둬 한번씩 하면 된거야").

pick_release_watcher/rebalance_watcher는 Selenium 등 pdf_updater 콘다 환경에서만
import되므로, 이 스크립트는 그 환경의 python.exe로 별도 프로세스 실행해야 한다
(fse_po_release.py가 subprocess로 호출).

  python fse_po_oracle_release.py <oracle_order_no> <out_json_path>
"""
import json
import os
import sys
import time

# 사용자마다 다른 경로는 part_order_backup\paths.py 가 이 PC 기준으로 풀어준다
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, next(
    (d for d in (os.environ.get("PART_ORDER_DIR"),
                 os.path.join(os.path.dirname(_HERE), "part_order_backup"),
                 r"C:\mcp\import_mcp\part_order_backup") if d and os.path.isdir(d)),
    r"C:\mcp\import_mcp\part_order_backup"))
import paths                                                        # noqa: E402

PICK_RELEASE_DIR = paths.PICK_DIR
REBALANCE_DIR = paths.REBALANCE_DIR

sys.path.insert(0, PICK_RELEASE_DIR)
sys.path.insert(0, REBALANCE_DIR)

order_no = sys.argv[1]
out_path = sys.argv[2]
MAX_ATTEMPTS = 4

import pick_release_watcher as prw
import rebalance_watcher as rw

# 2026-10-07: rebalance_watcher import로 owner가 rebalance_watcher(9335)가 되어 Rebalance_TO_*와
# 같은 Edge를 공유하던 것을 전용 Edge(포트 9342/전용 프로필)로 분리. import 뒤에 불러야 덮어써진다.
rw.set_edge_owner("fse_po_release")

# pick_release_watcher의 락은 Edge 공유 때문에 빌려 쓰던 것 - 이제 Edge가 분리됐으니
# Pick Release 실행 여부와 무관하게 돌도록 FSE PO 전용 락으로 교체(FSE PO끼리의 직렬화는 유지).
_FSE_LOCK_PATH = os.path.join(_HERE, "_fse_po_oracle_release.lock")


def _acquire_fse_lock():
    import msvcrt
    f = open(_FSE_LOCK_PATH, "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


def _release_fse_lock(f):
    import msvcrt
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()
    except Exception as e:
        print("락 해제 경고(무시):", e)

out = {"oracle_no": order_no, "rules": {}}

lock = _acquire_fse_lock()
if lock is None:
    out["status"] = "busy"
    out["msg"] = "다른 FSE PO 릴리즈가 실행 중 - 잠시 후 재시도"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)

driver = None
try:
    try:
        rw.ensure_edge_running()
    except Exception as e:
        print("Edge 확인 경고(무시):", e)

    driver = rw.get_oracle_driver_isolated()
    ok, driver = rw.recover_oracle_login(driver, print, allow_restart=True)
    print(f"오라클 로그인 상태: {ok}")
    time.sleep(3)

    def read_shipment_lines(driver, order_no):
        """Shipments > Manage Shipment Lines에서 Order 번호로 한 번 검색해 그 오더의
        모든 라인(품목 / Line Status / Requested Quantity)을 **읽기만** 한다(2026-10-07,
        Pick Slip을 열던 방식 대체 - 슬립이 몇 장이든 한 번에 보고, 릴리즈 팝업의
        backordered 숫자(라인 수와 안 맞는 경우가 있었음)보다 정확하다).
        Summary 탭에 Order Line/Line Status/Requested Quantity가 있고, Item은 왼쪽
        고정 열(링크)에 같은 순서로 있다. 행을 클릭하지 않는다(행 클릭은 상세로 튄다)."""
        import re
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import Select

        rw._ensure_my_tab(driver)
        driver.get(rw.ORACLE_HOME_URL)
        rw.wait_or_sleep(driver, rw.text_visible("Supply Chain Execution"), 5)
        rw._click_text(driver, "Supply Chain Execution")
        time.sleep(3)
        rw._click_text(driver, "Inventory Management")
        rw.wait_or_sleep(driver, rw.element_present(By.XPATH, "//img[@title='Tasks']"), 5)
        tasks_icon = rw._wait_find(driver, By.XPATH, "//img[@title='Tasks']", timeout=40)
        if not rw.tasks_panel_open(driver):
            driver.execute_script("arguments[0].click();", tasks_icon)
        sel_el = rw._wait_find(
            driver, By.XPATH, "//select[option[normalize-space(text())='Shipments']]", timeout=20)
        Select(sel_el).select_by_visible_text("Shipments")
        rw.wait_or_sleep(driver, rw.text_visible("Manage Shipment Lines"), 2)
        rw._click_text(driver, "Manage Shipment Lines")
        rw.wait_or_sleep(driver, rw.element_present(
            By.XPATH, "//input[normalize-space(@aria-label)='Order']"), 5)
        o = rw._wait_find(driver, By.XPATH,
                          "//input[@type='text' and normalize-space(@aria-label)='Order']")
        o.click(); o.clear(); o.send_keys(order_no)
        time.sleep(1)
        for el in driver.find_elements(By.XPATH, "//*[normalize-space(text())='Search']"):
            if el.is_displayed():
                el.click()
                break
        else:
            raise RuntimeError("Manage Shipment Lines Search 버튼을 못 찾음")

        def _summary_rows():
            """Summary 탭을 열고 (order_line, status, qty) 행들과 품목 목록을 읽는다."""
            for el in driver.find_elements(By.XPATH, "//a[normalize-space(text())='Summary']"):
                if el.is_displayed():
                    driver.execute_script("arguments[0].click();", el)
                    break
            time.sleep(3)
            body = driver.find_element(By.TAG_NAME, "body").text
            rows = re.findall(
                rf"{re.escape(order_no)}\s*\n\s*(\d+)\s+Transfer order\s*\n\s*(.+?)\s+[A-Z]+\s+(\d+)\b", body)
            # 품번 형식이 제각각(ELE100959, 9908-17-0408 ...)이라 패턴 대신 구조로 찾는다:
            # 데이터 행의 링크들은 id에 table1:{행번호}: 를 갖고, 품목 링크(id 없음)는 그
            # 행의 첫 id 링크 바로 앞에 온다. 고정 열이 DOM에 두 벌이어도 행번호로 중복 제거.
            items = driver.execute_script(
                "var as=Array.prototype.slice.call(document.querySelectorAll('a'));"
                "var seen={},out=[];"
                "for(var k=1;k<as.length;k++){"
                "var m=/table1:([0-9]+):/.exec(as[k].id||'');"
                "if(m&&!seen[m[1]]){seen[m[1]]=1;out.push([parseInt(m[1],10),"
                "(as[k-1].textContent||'').trim()]);}}"
                "out.sort(function(a,b){return a[0]-b[0];});"
                "return out.map(function(x){return x[1];});")
            uniq = items
            return rows, uniq

        # 결과 표가 행 단위로 늘어나므로 같은 결과가 두 번 연속 나올 때까지 기다린다
        deadline, prev, rows, items = time.time() + 40, None, [], []
        while time.time() < deadline:
            time.sleep(2)
            body = driver.find_element(By.TAG_NAME, "body").text
            if "Edit Shipment Line" in body:
                # 라인이 1개뿐인 주문은 오라클이 목록 대신 그 라인의 상세로 바로 연다
                # (2026-10-07 7890442 실측) - 상세 화면의 라벨/값에서 읽는다.
                def _val(label):
                    return driver.execute_script(
                        "var ls=document.querySelectorAll('label');"
                        "for(var i=0;i<ls.length;i++){"
                        "if((ls[i].textContent||'').trim()===arguments[0]){"
                        "var td=ls[i].closest('td');"
                        "return td&&td.nextElementSibling?td.nextElementSibling.textContent.replace(/ +/g,' ').trim():'';}}"
                        "return '';", label)
                item = _val("Item")
                status = _val("Line Status")
                req = re.match(r"(\d+)", _val("Requested Quantity"))
                if not (item and status and req):
                    raise RuntimeError(
                        f"라인 상세에서 값을 못 읽음(Item={item!r}, Line Status={status!r})")
                return [{"item": item, "order_line": _val("Order Line"),
                         "line_status": status, "requested": req.group(1)}]
            rows, items = _summary_rows()
            if rows and (rows, items) == prev:
                break
            prev = (rows, items)
        if not rows:
            raise RuntimeError(f"오더 {order_no}의 Manage Shipment Lines 결과를 못 읽음")
        if len(items) != len(rows):
            raise RuntimeError(
                f"품목 {len(items)}개와 라인 {len(rows)}개가 안 맞아 짝지을 수 없음")
        return [{"item": it, "order_line": ln, "line_status": st.strip(), "requested": q}
                for it, (ln, st, q) in zip(items, rows)]

    def try_rule(rule, attempts=MAX_ATTEMPTS):
        for attempt in range(1, attempts + 1):
            try:
                rw.create_pick_wave_transfer_order(driver, order_no, release_rule=rule)
                r = rw.release_pick_wave_now(driver, rule=rule)
                print(f"[성공] Oracle#{order_no} {rule} (시도{attempt}): "
                      f"released={r.get('released_lines')} backordered={r.get('backordered_lines')}")
                return r
            except Exception as e:
                print(f"  [재시도 {attempt}/{attempts}] {rule}: {type(e).__name__}: {e} - 8초 대기")
                time.sleep(8)
        return {"error": f"failed after {attempts} attempts"}

    sp_result = try_rule("KRP_Pick_Release_SP")
    out["rules"]["KRP_Pick_Release_SP"] = sp_result

    # 2026-10-06 사용자 지정 순서: SP -> FG release -> backorder가 남으면 Confirm
    # Manage Shipment Lines에서 어떤 품목이 빠졌는지 확인 -> (호출부가) 메일 회신.
    # SP에서 backorder가 0이면 FG는 뽑을 라인이 없어 "Customer 미표시"로 끝날
    # 뿐이라 생략한다(결과는 동일, 오라클 화면 이동만 아낀다).
    final_bo = sp_result.get("backordered_lines")
    if sp_result.get("backordered_lines"):
        print(f"  backorder {sp_result['backordered_lines']}건 - FG 1회 추가 실행"
              f"(FG는 재시도하지 않음)")
        fg_result = try_rule("KRP_Pick_Release_FG", attempts=1)
        out["rules"]["KRP_Pick_Release_FG"] = fg_result
        # FG가 성공했으면 FG 이후에 남은 수가 최종 backorder, FG가 못 뽑았으면
        # (에러/뽑을 라인 없음) SP 결과가 그대로 최종이다.
        if not fg_result.get("error") and fg_result.get("backordered_lines") is not None:
            final_bo = fg_result["backordered_lines"]
    else:
        print("  backorder 없음 - FG 생략")
    out["final_backordered_lines"] = final_bo

    if final_bo:
        try:
            out["shipment_lines"] = read_shipment_lines(driver, order_no)
            print(f"  Manage Shipment Lines 라인 {len(out['shipment_lines'])}개 읽음: "
                  + "; ".join(f"{l['item']} x{l['requested']} [{l['line_status']}]"
                              for l in out["shipment_lines"]))
        except Exception as e:
            out["shipline_error"] = f"{type(e).__name__}: {e}"
            print(f"  [경고] Manage Shipment Lines 조회 실패(백오더 품목 특정 불가): {out['shipline_error']}")

    out["status"] = "done"
except Exception as e:
    import traceback
    traceback.print_exc()
    out["status"] = "exception"
    out["error"] = f"{type(e).__name__}: {e}"
finally:
    if driver is not None:
        try:
            rw.close_driver(driver)
        except Exception:
            pass
    _release_fse_lock(lock)

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(json.dumps(out, ensure_ascii=False))
