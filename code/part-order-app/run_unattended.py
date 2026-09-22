"""사람이 옆에서 지켜보지 않는 상태로 run_batch를 돌리기 위한 진입점.

run_batch.py 자체는 이미 "자동생성 가능(ready)한 건만 Save까지 자동 처리"하지만,
브라우저/로그인이 준비됐다는 전제로 바로 connect_over_cdp를 시도한다. 무인
실행에서는 그 전제가 성립하지 않을 수 있으므로(open_browser.py가 막 떠서 아직
로그인 중이거나, SSO 자동 로그인이 실패해 사람 로그인이 필요한 경우) 여기서
먼저 준비 상태를 확인하고, 준비가 안 되면 무한정 기다리지 않고 실패를 명확히
남긴 뒤 중단한다.

완료 후에는 batch_result.json을 다시 읽어 사람이 바로 읽을 수 있는
last_batch_summary.txt를 남긴다 (Claude Code 없이 팀원이 직접 확인해야 하므로).
"""

import json
import os
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

import run_batch
from sf_actions import get_sf_page

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULT_PATH = os.path.join(SCRIPT_DIR, "batch_result.json")
SUMMARY_PATH = os.path.join(SCRIPT_DIR, "last_batch_summary.txt")
DEBUG_PORT = 9222

READY_TIMEOUT_SEC = 90
READY_POLL_INTERVAL_SEC = 3


def browser_ready():
    """CDP로 연결해서 Salesforce/ServiceMax 탭이 실제로 열려 있는지 확인한다.
    get_sf_page()가 예외 없이 반환하면 로그인된 상태로 간주한다(get_sf_page
    자체가 'salesforce.com' 또는 'vf.force.com' 탭을 찾는 기준이므로 그 판단을
    그대로 재사용 - ServiceMax 화면은 vf.force.com 도메인이라 'salesforce.com'
    문자열만 검사하면 오탐(false negative)이 남)."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
            context = browser.contexts[0]
            get_sf_page(context)
            return True
    except Exception:
        return False


def wait_until_ready(timeout_sec=READY_TIMEOUT_SEC, interval_sec=READY_POLL_INTERVAL_SEC):
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if browser_ready():
            return True
        time.sleep(interval_sec)
    return False


def write_summary(ok, fail_reason=None):
    lines = [f"실행 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]

    if not ok:
        lines.append(f"배치 미실행: {fail_reason}")
        with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return

    results = {"created": [], "needs_review": [], "location_review": [], "errors": []}
    if os.path.exists(RESULT_PATH):
        with open(RESULT_PATH, "r", encoding="utf-8") as f:
            results = json.load(f)

    lines.append(f"생성 완료: {len(results.get('created', []))}건")
    lines.append(f"확인 필요(경고): {len(results.get('needs_review', []))}건")
    lines.append(f"Location 확인 필요: {len(results.get('location_review', []))}건")
    lines.append(f"오류: {len(results.get('errors', []))}건")

    for label, key in [
        ("확인 필요(경고)", "needs_review"),
        ("Location 확인 필요", "location_review"),
        ("오류", "errors"),
    ]:
        items = results.get(key, [])
        if items:
            lines.append(f"\n[{label}]")
            for item in items:
                lines.append(f"  - {item.get('hospital', '?')}: {item.get('reason') or item.get('error')}")

    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    print("브라우저/로그인 준비 확인 중...")
    if not wait_until_ready():
        reason = "브라우저/로그인 확인 실패 - 수동 로그인 필요, 배치 미실행"
        print(reason)
        write_summary(ok=False, fail_reason=reason)
        raise SystemExit(1)

    print("준비 완료. 배치 실행...")
    run_batch.main(rescan=True)

    write_summary(ok=True)
    print(f"요약 저장: {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
