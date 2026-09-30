"""
Monthly Closing 마감 자료 4종 월간 자동 수집 오케스트레이터.

마감 파일을 만들려면 그 달의 자료 4개가 필요하다:
  1. 소모(Consumption) - Salesforce "Korea_FSE_Consumed Part" 리포트 -> fse_consumption_puller.py
  2. 입고(Receipt) - Oracle "Review Completed Transactions"(Transfer Order) -> fse_receipt_puller.py
  3. 온핸드(On-Hand) - Oracle "Candela Inventory Current On Hand Balances" 리포트 -> fse_onhand_puller.py
  4. Intransit Details Report - 매일 오전 10시에 이미 별도 자동화(outlook_intransit_downloader.py
     계열, "10. 수입" 프로젝트)가 자동 다운로드하는 파일. 여기서는 새로 받지 않고
     그 날짜의 파일이 이미 와 있는지 확인만 한다(그래서 이 스크립트를 10시 이후인
     11시에 도는 걸로 잡음).

매달 마지막 영업일 11:00에 실행되도록 스케줄러에 등록한다(Task Scheduler는 매일
11:00에 이 스크립트를 트리거하지만, 내부에서 오늘이 이번 달 마지막 영업일인지
판단해서 아니면 대기한다 - wd_cost_monthly_updater.py 등 기존 스크립트들과 동일한
날짜 가드 패턴).

캐치업: 지난달이 아직 처리 안 됐으면(트리거를 통째로 놓친 경우) 이번 달 가드보다
먼저 지난달분을 자동으로 복구한다(wd_cost_monthly_updater.py와 동일 패턴).
**주의**: 소모량 리포트는 "Work Order Status not equal to Closed" 필터가 있어
지난달로 캐치업 재조회하면 그 사이 마감된 WO가 빠져 실제보다 적게 나올 수 있다
(fse_consumption_puller.py 자체 문서 참고) - 캐치업 로그에 경고를 남긴다.

이 스크립트는 4개 파일을 "모으기"까지만 하고, Monthly Closing 대시보드
(monthly_closing_dashboard.html)에 반영하는 건 하지 않는다(원본 데이터 수집까지만).

수동 실행법:
    C:\\Users\\yoongil.chae\\Miniconda\\python.exe fse_monthly_runner.py
    (테스트용) --now 2026-09-30 으로 특정 날짜인 것처럼 가드를 통과시킬 수 있음.
"""
import argparse
import json
import os
import subprocess
import time
from datetime import date, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "fse_monthly_runner.log"
STATE_PATH = BASE_DIR / "fse_monthly_runner_state.json"
PYTHON_EXE = r"C:\Users\yoongil.chae\Miniconda\python.exe"

INTRANSIT_DIR = Path(
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\10. 수입\Intransit Details Report"
)
INTRANSIT_FILENAME_FMT = "APAC Candela Intransit Details Report_{ymd}.xlsx"

# wd_cost_monthly_updater.py와 동일 목록 유지(한국 공휴일)
KR_HOLIDAYS = {
    "2026-01-01",
    "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-03-01", "2026-03-02",
    "2026-05-05",
    "2026-05-24", "2026-05-25",
    "2026-06-03",
    "2026-06-06",
    "2026-07-17",
    "2026-08-15", "2026-08-17",
    "2026-09-24", "2026-09-25", "2026-09-26", "2026-09-28",
    "2026-10-03", "2026-10-05",
    "2026-10-09",
    "2026-12-25",
    "2027-01-01",
    "2027-02-05", "2027-02-06", "2027-02-07", "2027-02-08",
    "2027-03-01",
    "2027-05-05",
    "2027-05-13",
    "2027-06-06",
    "2027-07-17",
    "2027-08-15", "2027-08-16",
    "2027-09-14", "2027-09-15", "2027-09-16",
    "2027-10-03", "2027-10-04",
    "2027-10-09", "2027-10-11",
    "2027-12-25", "2027-12-27",
    "2028-01-01",
    "2028-01-25", "2028-01-26", "2028-01-27",
    "2028-03-01",
    "2028-04-12",
    "2028-05-02",
    "2028-05-05",
    "2028-06-06",
    "2028-07-17",
    "2028-08-15",
    "2028-10-02", "2028-10-03", "2028-10-04", "2028-10-05",
    "2028-10-09",
    "2028-12-25",
}


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [FSE_Monthly] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def is_working_day(d):
    return d.weekday() < 5 and d.strftime("%Y-%m-%d") not in KR_HOLIDAYS


def last_working_day_of_month(year, month):
    if month == 12:
        last_cal_day = date(year, 12, 31)
    else:
        last_cal_day = date(year, month + 1, 1) - timedelta(days=1)
    cur = last_cal_day
    while not is_working_day(cur):
        cur -= timedelta(days=1)
    return cur


def prev_month(year, month):
    if month == 1:
        return year - 1, 12
    return year, month - 1


def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"history": []}


def save_state(state):
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log(f"[경고] 상태 파일 저장 실패: {e}")


def month_already_processed(state, month_key):
    return any(
        h.get("month") == month_key and h.get("all_ok")
        for h in state.get("history", [])
    )


def _cleanup_zombie_edge():
    """이전 시도가 비정상 종료해 Edge 프로세스가 남아있으면 다음 launch_persistent_context가
    "Opening in existing browser session"으로 막힌다(이번 세션에서 여러 번 실측) - 재시도
    전에 이 자동화 전용 프로필에 물린 msedge.exe만 정리한다(다른 자동화 프로필은 안 건드림)."""
    try:
        subprocess.run(
            [
                "powershell", "-NoProfile", "-Command",
                "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | "
                "Where-Object { $_.CommandLine -like '*fse_oracle_puller*' -or "
                "$_.CommandLine -like '*fse_onhand_puller*' -or "
                "$_.CommandLine -like '*fse_consumption_puller*' } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }",
            ],
            capture_output=True, timeout=30,
        )
    except Exception:
        pass


def _start_script(args, label):
    # subprocess로 자식 스크립트를 띄우면 Windows 콘솔 코드페이지(cp949)를
    # 물려받아 자식의 print()가 특정 문자에서 UnicodeEncodeError로 죽는다
    # (부모 쪽 encoding="utf-8"는 부모가 자식 출력을 "읽는" 인코딩일 뿐, 자식
    # 자신의 stdout 인코딩은 별개) - PYTHONIOENCODING을 강제로 지정해야 함.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    log(f"[{label}] 실행 시작: {' '.join(args[1:])}")
    return subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=str(BASE_DIR), encoding="utf-8", errors="replace", env=env,
    )


def _finish_script(proc, label, timeout=600):
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        log(f"[{label}] [오류] 10분 타임아웃")
        return False
    if stdout:
        log(f"[{label}] 출력(마지막 3000자):\n{stdout[-3000:]}")
    if proc.returncode != 0:
        log(f"[{label}] [오류] exit={proc.returncode}")
        if stderr:
            log(f"[{label}] stderr(마지막 1500자):\n{stderr[-1500:]}")
        return False
    log(f"[{label}] 완료")
    return True


def run_scripts_parallel(script_specs, attempts=3, retry_wait_sec=20):
    """script_specs: [(args, label), ...]. 2026-09-30: 세 스크립트가 이제 서로
    다른 Playwright 프로필(fse_consumption_puller/fse_oracle_puller/
    fse_onhand_puller)을 써서 동시 실행이 안전해졌다 - subprocess.Popen으로
    한꺼번에 띄우고 전부 끝날 때까지 기다린다(순차 실행 대비 훨씬 빠름).
    실패한 것만 재시도한다(이미 성공한 건 다시 안 돌림) - 마감 작업이라 하루
    늦게 넘어가면 안 되므로 같은 실행 안에서 최대 attempts회 재시도."""
    results = {}
    pending = list(script_specs)
    for attempt in range(1, attempts + 1):
        if not pending:
            break
        _cleanup_zombie_edge()
        if attempt > 1:
            log(f"[재시도 {attempt}/{attempts}] 실패했던 {len(pending)}개 동시 재시작: "
                f"{', '.join(label for _, label in pending)}")
        procs = [(_start_script(args, label), args, label) for args, label in pending]
        still_failed = []
        for proc, args, label in procs:
            ok = _finish_script(proc, label)
            results[label] = ok
            if not ok:
                still_failed.append((args, label))
        pending = still_failed
        if pending and attempt < attempts:
            log(f"{retry_wait_sec}초 후 재시도합니다...")
            time.sleep(retry_wait_sec)

    for _, label in pending:
        log(f"[{label}] [최종실패] {attempts}회 모두 실패")
    return results


def check_intransit_file(target_date):
    ymd = target_date.strftime("%Y%m%d")
    path = INTRANSIT_DIR / INTRANSIT_FILENAME_FMT.format(ymd=ymd)
    if path.exists():
        log(f"[Intransit] 확인됨: {path.name}")
        return True
    log(f"[Intransit][경고] {path.name} 파일이 없음 - 매일 10시 자동 다운로드가 그날 실패했을 수 있음")
    return False


def process_month(year, month, target_date, label=""):
    month_key = f"{year}-{month:02d}"
    consumption_label, receipt_label, onhand_label = (
        f"{label}소모량", f"{label}입고", f"{label}온핸드",
    )
    specs = [
        ([PYTHON_EXE, "fse_consumption_puller.py", "--month", month_key], consumption_label),
        ([PYTHON_EXE, "fse_receipt_puller.py", "--month", month_key], receipt_label),
        ([PYTHON_EXE, "fse_onhand_puller.py"], onhand_label),
    ]
    results = run_scripts_parallel(specs)
    ok_consumption = results[consumption_label]
    ok_receipt = results[receipt_label]
    ok_onhand = results[onhand_label]
    ok_intransit = check_intransit_file(target_date)
    all_ok = ok_consumption and ok_receipt and ok_onhand and ok_intransit

    # 4개 중 하나라도 실패하면 "완료"로 기록하지 않는다 - month_already_processed()가
    # all_ok만 보고 판단하므로, 실패한 달은 다음 트리거(내일 이 시각)에서 자동으로
    # 다시 캐치업 시도된다(wd_cost_monthly_updater.py와 동일 원칙: 실패는 상태에
    # "완료"로 남기지 않는다).
    state = load_state()
    state.setdefault("history", []).append({
        "month": month_key,
        "run_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "consumption_ok": ok_consumption,
        "receipt_ok": ok_receipt,
        "onhand_ok": ok_onhand,
        "intransit_ok": ok_intransit,
        "all_ok": all_ok,
    })
    state["history"] = state["history"][-24:]
    save_state(state)
    if not all_ok:
        log(f"{label}[미완료] {month_key} - 하나 이상 실패, 다음 실행에서 재시도됨(상태에 완료로 기록 안 함)")

    log(
        f"{label}[완료] {month_key} - 소모={ok_consumption} 입고={ok_receipt} "
        f"온핸드={ok_onhand} Intransit={ok_intransit}"
    )
    return ok_consumption and ok_receipt and ok_onhand and ok_intransit


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--now", help="YYYY-MM-DD (테스트용, 오늘 날짜를 이 값으로 취급)")
    args = parser.parse_args()

    today = date.fromisoformat(args.now) if args.now else date.today()
    log(f"===== FSE 월간 마감자료 4종 수집 시작 (기준일: {today}) =====")

    state = load_state()

    # 캐치업: 지난달 트리거가 통째로 안 걸렸으면 이번 달 가드보다 먼저 복구
    py, pm = prev_month(today.year, today.month)
    prev_key = f"{py}-{pm:02d}"
    if not month_already_processed(state, prev_key):
        log(f"[캐치업] 지난달({prev_key}) 처리 기록 없음 - 놓친 트리거로 판단, 캐치업 실행")
        log("[캐치업][주의] 소모량 리포트는 'Work Order Status not equal to Closed' 필터가 있어 "
            "지난달 재조회 시 그 사이 마감된 WO가 빠져 실제보다 적게 나올 수 있음 - 결과 확인 필요")
        prev_last_bd = last_working_day_of_month(py, pm)
        process_month(py, pm, prev_last_bd, label="[캐치업]")
        state = load_state()

    this_month_key = f"{today.year}-{today.month:02d}"
    if month_already_processed(state, this_month_key):
        log(f"[스킵] 이번 달({this_month_key})은 이미 처리 완료")
        return

    last_bd = last_working_day_of_month(today.year, today.month)
    if today < last_bd:
        log(f"[대기] 오늘({today})은 이번 달 마지막 영업일({last_bd}) 이전 - 대기")
        return

    log(f"[실행] 오늘({today}) >= 이번 달 마지막 영업일({last_bd}) - {this_month_key} 자료 수집 시작")
    process_month(today.year, today.month, today)


if __name__ == "__main__":
    main()
