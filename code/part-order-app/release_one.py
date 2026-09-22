# -*- coding: utf-8 -*-
"""Parts Order 번호 1건을 오라클에서 Pick Release 한다 (별도 프로세스로 실행됨).

pick_release_watcher는 icbl_ci_watcher를 통해 pytesseract/selenium 등을 쓰므로
`Miniconda\\envs\\pdf_updater` 환경에서만 import된다. 앱(기본 파이썬)에서 직접
import하면 ModuleNotFoundError가 난다(2026-09-01 실측) - 그래서 이 스크립트를
그 환경의 python.exe로 subprocess 실행한다.

  python release_one.py <kind> <order_no> <subject> <out_json>
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths                    # 사용자마다 다른 경로를 이 PC 기준으로 풀어준다

PICK_DIR = paths.PICK_DIR

kind = sys.argv[1]
order_no = sys.argv[2]
subject = sys.argv[3]
out_path = sys.argv[4]

sys.path.insert(0, PICK_DIR)
os.chdir(PICK_DIR)

out = {"order_no": order_no, "kind": kind}
try:
    import pick_release_watcher as w

    if kind not in w.RELEASE_RULES:
        raise SystemExit(f"알 수 없는 kind: {kind}")

    lock = w._acquire_singleton_lock()
    if lock is None:
        out["status"] = "busy"
        out["msg"] = "pick_release_watcher가 실행 중 - 잠시 후 재시도"
    else:
        try:
            state = w.load_state()
            key = w.state_key(kind, order_no)
            if key in state:
                out["status"] = "already_released"
                out["existing"] = state[key]
                print(f"[중단] {order_no}: 이미 릴리즈 이력 있음")
            else:
                try:
                    w.ensure_edge_running()
                except Exception as e:
                    print("Edge 확인 경고(무시):", e)

                # ★ 오라클 로그인 복구를 먼저 한다.
                # pick_release_watcher는 _try_sso_relogin을 정의만 하고 호출하지
                # 않아서, 세션이 끊긴 상태로 돌리면 'Supply Chain Execution 못 찾음'
                # 으로만 3회 실패하고 끝난다(2026-08-27, 09-01 실측).
                try:
                    d = w.get_oracle_driver_isolated()
                    try:
                        ok = w.recover_oracle_login(d, print)
                        print(f"오라클 로그인 상태: {ok}", flush=True)
                    finally:
                        w.close_driver(d)
                except Exception as e:
                    print("오라클 로그인 복구 경고(계속 진행):", e)

                rules = w.RELEASE_RULES[kind]
                print(f"release 시작: {kind} {order_no} rules={rules}", flush=True)
                _, info = w._process_single_order(kind, order_no, rules, state)

                total = sum((r.get("released_lines") or 0)
                            for _, r in info.get("results", []))
                out["released"] = total
                out["results"] = [{"rule": r, "lines": x.get("released_lines"),
                                   "backorder": x.get("backordered_lines"),
                                   "customer": x.get("customer")}
                                  for r, x in info.get("results", [])]
                if info.get("error"):
                    out["status"] = "error"
                    out["error"] = info["error"]
                elif total <= 0:
                    out["status"] = "zero_lines"
                else:
                    out["status"] = "released"
                    state[key] = w._build_order_entry(kind, subject, info)
                    w.save_state(state)
                    print(f"[성공] released_lines {total}건 - 상태파일 기록")
        finally:
            w._release_singleton_lock(lock)
except SystemExit:
    raise
except Exception as e:
    import traceback
    traceback.print_exc()
    out["status"] = "exception"
    out["error"] = f"{type(e).__name__}: {e}"

with open(out_path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(json.dumps(out, ensure_ascii=False))
