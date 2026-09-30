"""
Salesforce Classic 리포트 "Korea_FSE_Consumed Part"(Id=00OPY00000QPIFl2AP,
Unfiled Public Reports)를 열어 Time Frame 필터를 지정한 달의 1일~말일로 맞추고
Export(UTF-8 CSV)를 받아 FSE 코드별 소모 수량을 집계해 콘솔에 출력한다.

대시보드(FSE_CONSUMPTION_SEED)는 이 스크립트가 건드리지 않는다 — 원본 데이터 수집까지만.

Playwright 기반(2026-09-29, Selenium에서 전환). 로그인은 회사 SSO(Windows 세션)에
맡긴다 - 전용 프로필(포트 불필요, launch_persistent_context가 자체 CDP 포트를 관리)을
쓰면 최초 로그인 이후로는 로그인 화면 자체가 안 뜬다(실측 확인, 2026-09-29).

**중요 - 미해결 필터 문제(2026-09-29 발견)**: 이 리포트의 저장된 기본 필터에
"Work Order Status not equal to Closed"가 걸려 있다. 즉 이 스크립트를 그 달이
지난 뒤(예: 다음 달 이후) 재실행하면, 그 사이 Closed 처리된 Work Order들이 결과에서
빠져 실제보다 훨씬 적은 수치가 나온다(실측: 2026-09-29에 2026-08을 다시 뽑으니 15줄뿐 -
기존 FSE_CONSUMPTION_SEED의 2026.8 수치와 비교하면 터무니없이 적음). 반대로 그 달이
끝난 직후(WO들이 아직 안 닫혔을 때) 실행하면 값이 맞을 가능성이 높다. 이 리포트를
과거 달 재현/백필 용도로 쓰지 말 것 - 매달 초입(월 마감 직후)에만 그 달분을 pull하는
용도로 쓸 것. 필터를 Clear하고 뽑아야 하는지는 확인 안 됐으므로 선택자를 임의로
바꾸지 않았다(저장된 리포트 필터 그대로 사용).

사용법: python fse_consumption_puller.py --month 2026-09
"""
import argparse
import calendar
import sys
import time
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = BASE_DIR / "fse_consumption_puller.log"

REPORT_URL = "https://<your-org>.my.salesforce.com/<report-id>"
PROFILE_DIR = r"C:\Users\yoongil.chae\.fse_consumption_puller\pw_profile"

# Korea FSE 서브인벤토리 화이트리스트 - 대시보드 FSE_CONSUMPTION_SEED/FSE_RECEIPT_SEED에
# 실제 등장한 적 있는 전체 코드(현직 10명 FSE_NAMES + 이력에 남은 FSE003/FSE015).
KOREA_FSE_CODES = {
    "FSE002", "FSE003", "FSE004", "FSE006", "FSE007", "FSE012",
    "FSE013", "FSE014", "FSE015", "FSE016", "FSE017", "FSE018",
}


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def fmt_date_kr(d):
    return f"{d.year}. {d.month}. {d.day}"


def month_range(month_str):
    y, m = map(int, month_str.split("-"))
    first = date(y, m, 1)
    last = date(y, m, calendar.monthrange(y, m)[1])
    return first, last


def run_export(from_date, to_date):
    """2026-09-29 재작성: 처음엔 Export Details 모달 -> "Export" 버튼 클릭 ->
    Playwright download 이벤트를 기다리는 방식으로 짰으나, 클릭 후 정확히
    ~241초 지점에서 매번(좀비 프로세스 정리 후에도 재현) "Target page, context
    or browser has been closed"로 실패했다 - 서버측 export 생성이 오래 걸리는
    것과 무관하게, 이 리포트/프로필 조합에서 Playwright의 download 이벤트
    자체가 구조적으로 신뢰 불가능한 것으로 판단.

    대신 Run Report까지만 화면으로 진행(서버에 Time Frame 필터를 세션에
    반영시키기 위해 필요)한 뒤, Classic 리포트의 export URL
    (`?export=1&enc=...&xf=csv`)을 `context.request`로 직접 GET 해서 응답
    바이트를 그대로 받는다 - 같은 인증 세션(쿠키)을 그대로 쓰므로 로그인은
    그대로 재사용되고, 브라우저 다운로드 메커니즘을 아예 안 거치므로 위
    문제가 원천적으로 없다(실측: 200, 즉시 응답, CSV 24,663바이트 - Export
    Details/버튼 클릭 전체를 건너뛰어도 됨이 확인됨, 2026-09-29)."""
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=False, channel="msedge", accept_downloads=True,
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            log("1) 리포트 페이지 여는 중...")
            page.goto(REPORT_URL)
            page.wait_for_load_state("load", timeout=20000)
            page.wait_for_timeout(1500)
            if "FSE" not in page.title().upper():
                shot = BASE_DIR / "error_report_load.png"
                page.screenshot(path=str(shot))
                raise RuntimeError(f"리포트 페이지를 확인 못함 (title={page.title()!r}, 스크린샷: {shot})")
            log(f"   로드 확인 (title={page.title()!r})")

            log("2) Time Frame 필터 설정 중...")
            page.select_option("#colDt_q", "custom")
            page.fill("#colDt_s", fmt_date_kr(from_date))
            page.fill("#colDt_e", fmt_date_kr(to_date))
            page.click("input[name='run']")
            page.wait_for_load_state("load", timeout=20000)
            page.wait_for_timeout(2000)
            log(f"   Time Frame 설정 완료: {fmt_date_kr(from_date)} ~ {fmt_date_kr(to_date)}")

            log("3) Export URL 직접 호출 중...")
            export_url = page.url.split("?")[0] + "?export=1&enc=UTF-8&xf=csv"
            resp = context.request.get(export_url, timeout=60000)
            if resp.status != 200:
                shot = BASE_DIR / "error_export.png"
                page.screenshot(path=str(shot))
                raise RuntimeError(f"Export 요청 실패 (status={resp.status}, 스크린샷: {shot})")
            body = resp.body()
            save_path = DOWNLOAD_DIR / f"korea_fse_consumed_{from_date.isoformat()}_{to_date.isoformat()}.csv"
            save_path.write_bytes(body)
            log(f"   Export 완료: {save_path} ({len(body)} bytes)")
            return save_path
        except Exception:
            shot = BASE_DIR / "error_export.png"
            try:
                page.screenshot(path=str(shot))
                log(f"   [오류] 스크린샷 저장: {shot}")
            except Exception:
                pass
            raise
        finally:
            context.close()


def parse_and_aggregate(csv_path):
    """2026-09-29: export URL에 enc=UTF-8&xf=csv로 직접 요청하므로 순수 UTF-8
    CSV가 내려온다(예전 xls/HTML 테이블 파싱 방식 불필요)."""
    import pandas as pd

    df = pd.read_csv(csv_path, encoding="utf-8")
    log(f"  read_csv 성공: {len(df)}행, 컬럼={list(df.columns)}")

    sub_col = "Oracle Subinventory" if "Oracle Subinventory" in df.columns else None
    qty_col = "Line Qty" if "Line Qty" in df.columns else None
    if not sub_col or not qty_col:
        log("  [경고] 예상 컬럼명이 안 보입니다 - 전체 컬럼을 확인해 수동으로 매핑하세요.")
        print(df.head(20).to_string())
        return None

    df = df[df[sub_col].astype(str).isin(KOREA_FSE_CODES)]
    totals = df.groupby(sub_col)[qty_col].apply(
        lambda s: pd.to_numeric(s, errors="coerce").sum()
    ).to_dict()
    counts = df.groupby(sub_col).size().to_dict()
    return totals, counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args()

    from_date, to_date = month_range(args.month)
    log(f"===== FSE 소모량 Salesforce 리포트 pull 시작: {args.month} ({from_date} ~ {to_date}) =====")

    # run_export()가 이제 직접 export URL fetch 방식이라 다운로드 이벤트발
    # 실패 자체가 없어졌지만, 네트워크 일시 오류 등 다른 이유의 실패에 대비해
    # 재시도는 그대로 남겨둔다(이 프로젝트의 다른 자동화들과 동일 패턴).
    path = None
    last_err = None
    for attempt in range(1, 4):
        try:
            path = run_export(from_date, to_date)
            break
        except Exception as e:
            last_err = e
            log(f"[재시도 {attempt}/3] 다운로드 실패({e.__class__.__name__}: {e}) - 다시 시도")
    if path is None:
        log(f"[실패] 3회 재시도 모두 실패. 마지막 오류: {last_err}")
        sys.exit(1)
    result = parse_and_aggregate(path)
    if result is None:
        log("집계 실패 - 위 경고 참고")
        sys.exit(1)
    totals, counts = result
    log("===== FSE코드별 집계 결과 (대시보드는 반영하지 않음) =====")
    if not totals:
        log("  (Korea FSE 코드 화이트리스트에 해당하는 행이 없음)")
    for code in sorted(totals):
        log(f"  {code}: qty={totals[code]}, lines={counts[code]}")


if __name__ == "__main__":
    main()
