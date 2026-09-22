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

out = {"oracle_no": order_no, "rules": {}}

lock = prw._acquire_singleton_lock()
if lock is None:
    out["status"] = "busy"
    out["msg"] = "pick_release_watcher가 실행 중 - 잠시 후 재시도"
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

    if sp_result.get("backordered_lines"):
        print(f"  backorder {sp_result['backordered_lines']}건 - FG 1회만 추가 실행"
              f"(FG는 재시도하지 않음)")
        fg_result = try_rule("KRP_Pick_Release_FG", attempts=1)
        out["rules"]["KRP_Pick_Release_FG"] = fg_result
    else:
        print("  backorder 없음 - FG 생략")

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
    prw._release_singleton_lock(lock)

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(json.dumps(out, ensure_ascii=False))
