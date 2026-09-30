"""
Oracle Fusion Inventory Management > "Review Completed Transactions" 화면에서
FSE 입고(Transfer Order) 데이터를 뽑아 FSE 코드별 입고 수량을 집계한다.

대시보드(FSE_RECEIPT_SEED)는 이 스크립트가 건드리지 않는다 - 원본 데이터 수집까지만.

**2026-09-30: 로그인+네비게이션+필터 전부 실측 검증 완료.**
- 로그인: oracle_login.py의 "Sign in with AzureAD" 버튼 클릭(비밀번호 불필요).
- 화면 이동: 홈 → "Inventory Management (Classic)" 타일 클릭 → title="Tasks" 아이콘
  클릭 → "Review Completed Transactions" 텍스트 클릭.
- Source Type 필드는 select가 아니라 자유입력 콤보박스(input) - 드롭다운 목록엔
  "Transfer Order"가 안 보이지만(quick-pick 10개 안에 없음) **그냥 텍스트로
  "Transfer Order"를 타이핑하고 Tab하면 값이 그대로 확정된다**(실측 확인, 목록에서
  클릭할 필요 없음).
- Transaction Date는 label "Transaction Date"로 3개 엘리먼트가 잡힘: [0]=Between
  선택 select, [1]=From input, [2]=To input. 날짜 형식은 "M/D/YY"(0패딩 없음).
Export to Excel(Actions 메뉴)은 아직 미검증 - 막히면 `error_*.png` 스크린샷을 보고
선택자를 수정할 것.

수동 실행법:
    C:\\Users\\yoongil.chae\\Miniconda\\python.exe fse_receipt_puller.py --month 2026-09
"""
import argparse
import calendar
import sys
import time
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oracle_login  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = BASE_DIR / "fse_receipt_puller.log"

PROFILE_DIR = r"C:\Users\yoongil.chae\.fse_oracle_puller\pw_profile"


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def fmt_date_us(d):
    # 화면 예시가 "9/29/26" 형태(M/D/YY, 0패딩 없음)로 보였다 - 미검증.
    return f"{d.month}/{d.day}/{d.year % 100}"


def month_range(month_str):
    y, m = map(int, month_str.split("-"))
    first = date(y, m, 1)
    last = date(y, m, calendar.monthrange(y, m)[1])
    return first, last


def _screenshot(page, name):
    path = BASE_DIR / f"error_{name}.png"
    try:
        page.screenshot(path=str(path))
        log(f"  (스크린샷 저장: {path})")
    except Exception:
        pass


def navigate_to_review_completed_transactions(page):
    """Oracle Fusion Home에서 'Review Completed Transactions' 작업 화면으로 이동한다.

    **2026-09-30 실측 검증 완료** (사용자가 알려준 경로): 홈 화면의 "Inventory
    Management (Classic)" 앱 타일 클릭 → 그 안에서 title="Tasks"인 아이콘(우측
    사이드바 3개 아이콘 중 첫번째, aria-label/role 없이 title 속성만 있음 - DOM
    조사로 확인) 클릭 → "Show Tasks" 패널의 기본(Inventory) 카테고리에
    "Review Completed Transactions"가 바로 나타남 → 클릭.
    """
    # 2026-09-30 실측(진짜 원인 확정): "60초까지 늘려도 타임아웃"이길래 처음엔
    # 부하 문제로 의심했으나, 실패 스크린샷을 보니 홈 화면이 "Supply Chain
    # Execution" 탭이 아니라 **"Tools" 탭**에 가 있었다 - Oracle Fusion Home은
    # 마지막으로 봤던 탭을 프로필(브라우저 저장소)에 기억해뒀다가 다음 방문 때
    # 그대로 띄운다. 이 프로필을 예전에 온핸드 스크립트와 공유하던 시절 "Tools"
    # 탭을 방문한 기록이 남아있었던 것 - 탭이 안 맞으니 아무리 기다려도
    # "Inventory Management (Classic)"가 안 보이는 게 당연했다. 어느 탭이
    # 기본으로 뜨든 상관없게 "Supply Chain Execution" 탭을 명시적으로 먼저
    # 클릭한다.
    log("Supply Chain Execution 탭 클릭...")
    try:
        page.get_by_text("Supply Chain Execution", exact=True).first.click(timeout=30000, force=True)
    except Exception as e:
        _screenshot(page, "sce_tab_not_found")
        raise RuntimeError(f"'Supply Chain Execution' 탭 클릭 실패: {e}")
    page.wait_for_timeout(1500)

    log("Inventory Management (Classic) 진입...")
    try:
        page.get_by_text("Inventory Management (Classic)", exact=False).first.click(timeout=60000)
    except Exception as e:
        _screenshot(page, "inventory_mgmt_tile_not_found")
        raise RuntimeError(f"'Inventory Management (Classic)' 타일 클릭 실패: {e}")
    page.wait_for_timeout(5000)

    log("Tasks 패널 열기...")
    try:
        page.locator("[title='Tasks']").first.click(timeout=30000, force=True)
    except Exception as e:
        _screenshot(page, "tasks_icon_not_found")
        raise RuntimeError(f"Tasks 아이콘(title='Tasks') 클릭 실패: {e}")
    page.wait_for_timeout(1500)

    log("'Review Completed Transactions' 클릭...")
    try:
        page.get_by_text("Review Completed Transactions", exact=False).first.click(timeout=30000, force=True)
    except Exception as e:
        _screenshot(page, "rct_link_not_found")
        raise RuntimeError(f"'Review Completed Transactions' 링크 클릭 실패: {e}")
    page.wait_for_timeout(4000)

    if "Review Completed Transactions" not in page.title():
        _screenshot(page, "review_completed_transactions_not_loaded")
        raise RuntimeError(f"Review Completed Transactions 화면 로드 확인 못함(title={page.title()!r}, 스크린샷 확인)")
    log(f"Review Completed Transactions 화면 도착 확인 (title={page.title()!r}).")


def set_filters_and_search(page, from_date, to_date):
    """검색 폼 필터 설정. Organization은 화면에 기본값 KRP가 이미 선택돼 있는 걸로
    스크린샷에서 확인했으므로 건드리지 않는다. Source Type=Transfer Order,
    Transaction Date=대상월 범위만 설정한다(Subinventory는 폼에서 필터링 시도하지
    않고, 전체를 받아서 다운로드 후 pandas로 FSE만 골라낸다 - Oracle LOV가 접두어
    검색을 지원하는지 불확실하기 때문).

    **2026-09-30 실측 검증 완료.**
    """
    log("필터 설정 중...")
    try:
        src_input = page.get_by_label("Source Type", exact=False).first
        src_input.click()
        src_input.fill("Transfer Order")
        page.keyboard.press("Tab")
        page.wait_for_timeout(500)
        # 콤보박스 타이핑이 내부 LOV 팝업을 남겨서 이후 "Search" 버튼이 2개로
        # 잡히는 strict mode 위반이 남(실측 확인, 2026-09-30) - Escape로 정리.
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception as e:
        _screenshot(page, "source_type_fail")
        raise RuntimeError(f"Source Type 입력 실패: {e}")

    try:
        # get_by_label("Transaction Date")는 3개가 잡힘: [0]=Between select,
        # [1]=From input, [2]=To input (실측 확인, 2026-09-30).
        date_inputs = page.get_by_label("Transaction Date", exact=False)
        if date_inputs.count() >= 3:
            date_inputs.nth(1).fill(fmt_date_us(from_date))
            date_inputs.nth(2).fill(fmt_date_us(to_date))
        else:
            raise RuntimeError(f"Transaction Date 입력 필드를 3개 못 찾음(찾은 개수: {date_inputs.count()})")
    except Exception as e:
        _screenshot(page, "date_range_fail")
        raise RuntimeError(f"Transaction Date 범위 설정 실패: {e}")

    try:
        # "Collapse Search"(검색패널 접기 링크)와 이름이 겹쳐 strict mode 위반이
        # 나서 exact=True로 진짜 Search 버튼만 특정한다(실측 확인, 2026-09-30).
        # 그래도 LOV 팝업 잔재로 2개 잡힐 수 있어 .first로 안전하게 마무리.
        page.get_by_role("button", name="Search", exact=True).first.click()
    except Exception as e:
        _screenshot(page, "search_button_fail")
        raise RuntimeError(f"Search 버튼 클릭 실패: {e}")
    page.wait_for_timeout(4000)
    log(f"필터 설정 완료: Source Type=Transfer Order, {fmt_date_us(from_date)} ~ {fmt_date_us(to_date)}")


def export_to_excel(page):
    """Search Results의 Actions 메뉴 > Export to Excel.

    **2026-09-30: expect_download()/save_as() 방식을 폐기함** - 반복 실전 테스트에서
    "Target page, context or browser has been closed"로 계속 실패했다(Salesforce
    소모량/Oracle 온핸드 스크립트에서 겪은 것과 완전히 동일한 유형의 문제 -
    Playwright의 download 이벤트가 이 환경에서 구조적으로 불안정). 대신 route
    가로채기로 직접 fetch한다(온핸드 스크립트와 동일 원리). 이 화면(fscmUI ADF)의
    정확한 export URL 패턴은 아직 모르므로 전체 요청을 가로채 content-disposition:
    attachment 헤더로 실제 파일 응답만 골라낸다(대부분의 요청은 그냥 통과시키므로
    오버헤드는 크지 않음)."""
    log("Actions > Export to Excel 시도...")
    try:
        # 실측(2026-09-30): role=button으로 안 잡힘 - 검색결과 그리드 툴바의
        # 텍스트 드롭다운 트리거("Actions ▾")라 텍스트 기반으로 클릭.
        page.get_by_text("Actions", exact=True).first.click(timeout=10000, force=True)
        page.wait_for_timeout(500)
    except Exception as e:
        _screenshot(page, "actions_menu_fail")
        raise RuntimeError(f"Actions 메뉴 클릭 실패: {e}")

    result = {}

    def _handle_route(route):
        if "body" in result:
            route.continue_()
            return
        try:
            resp = route.fetch()
        except Exception as e:
            result.setdefault("err", e)
            route.continue_()
            return
        cd = resp.headers.get("content-disposition", "")
        if "attachment" in cd:
            result["body"] = resp.body()
        try:
            route.fulfill(response=resp)
        except Exception:
            try:
                route.abort()
            except Exception:
                pass

    page.route("**/*", _handle_route)
    try:
        # 실측(2026-09-30): "Export to Excel" 텍스트가 실제 메뉴항목(<td class="xo2">)과
        # 화면에 안 보이는 접근성용 설명 span 2곳에 있음 - 진짜 메뉴항목 태그(td)로 직접 지정.
        page.locator("td", has_text="Export to Excel").first.click(force=True)
    except Exception as e:
        page.unroute("**/*", _handle_route)
        _screenshot(page, "export_to_excel_fail")
        raise RuntimeError(f"Export to Excel 클릭 실패: {e}")

    deadline = time.time() + 240
    while time.time() < deadline and "body" not in result and "err" not in result:
        try:
            page.wait_for_timeout(500)
        except Exception:
            break
    page.unroute("**/*", _handle_route)

    if "body" not in result:
        try:
            _screenshot(page, "export_capture_fail")
        except Exception:
            pass
        raise RuntimeError(f"export 응답을 못 잡음(err={result.get('err')})")

    save_path = DOWNLOAD_DIR / f"receipt_completed_transactions_{int(time.time())}.xlsx"
    save_path.write_bytes(result["body"])
    log(f"다운로드 완료: {save_path} ({len(result['body'])} bytes)")
    return save_path


def parse_and_aggregate(xlsx_path):
    """2026-09-30 실측: 확장자는 .xlsx지만 실제 내용은 Excel용 HTML 마크업
    (xmlns:x="urn:schemas-microsoft-com:office:excel")이라 read_excel이 아니라
    read_html로 파싱해야 한다(Salesforce classic export와 동일 패턴)."""
    import pandas as pd

    tables = None
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            tables = pd.read_html(xlsx_path, encoding=enc)
            log(f"  read_html 성공 (encoding={enc}, 테이블 {len(tables)}개)")
            break
        except Exception as e:
            log(f"  read_html 실패(encoding={enc}): {e}")
    if not tables:
        log("[오류] HTML 테이블 파싱 실패 - 파일을 직접 확인 필요")
        return None
    df = max(tables, key=len)

    # "Project Details" 같은 병합 헤더 때문에 컬럼이 튜플(MultiIndex)로 들어옴
    # (실측: ('Subinventory','Subinventory'), ('Project Details','Task Number') 등) -
    # 마지막 레벨(실제 컬럼명)만 남겨 평탄화한다.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[-1] for c in df.columns]

    log(f"컬럼: {list(df.columns)}")
    sub_col = next((c for c in df.columns if "subinventory" in str(c).lower()), None)
    # "Transaction Quantity"와 별개로 "Quantity"(2차 단위 등 다른 의미) 컬럼도
    # 있어 모호하므로, 정확히 "Transaction Quantity"를 우선 찾는다.
    qty_col = next((c for c in df.columns if str(c).strip().lower() == "transaction quantity"), None)
    if not qty_col:
        qty_col = next((c for c in df.columns if "quantity" in str(c).lower()), None)
    if not sub_col or not qty_col:
        log("[경고] Subinventory/Quantity 컬럼을 자동으로 못 찾음 - 아래 전체 컬럼/샘플을 보고 수동 확인하세요.")
        print(df.head(20).to_string())
        return None

    fse_df = df[df[sub_col].astype(str).str.startswith("FSE", na=False)]
    positive_df = fse_df[pd.to_numeric(fse_df[qty_col], errors="coerce") > 0]
    totals = positive_df.groupby(sub_col)[qty_col].apply(
        lambda s: pd.to_numeric(s, errors="coerce").sum()
    ).to_dict()
    counts = positive_df.groupby(sub_col).size().to_dict()
    return totals, counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args()

    from_date, to_date = month_range(args.month)
    log(f"===== FSE 입고(Receipt) Oracle pull 시작: {args.month} ({from_date} ~ {to_date}) =====")

    with sync_playwright() as p:
        context, page, logged_in = oracle_login.open_oracle(p, PROFILE_DIR, log)
        if not logged_in:
            log("[중단] 로그인 확인 안 됨 - 이 창에서 직접 로그인 후 다시 실행하세요.")
            context.close()
            sys.exit(1)
        try:
            navigate_to_review_completed_transactions(page)
            set_filters_and_search(page, from_date, to_date)
            xlsx_path = export_to_excel(page)
        except Exception as e:
            # 2026-09-30 실측: 여기서 그냥 return하면 exit code가 0이라 상위
            # 오케스트레이터(subprocess.run)가 "성공"으로 오판한다(실제로는 실패) -
            # 마감 자동화라 반드시 실패를 정확히 전파해야 함.
            log(f"[오류] {e}")
            context.close()
            sys.exit(1)
        context.close()

    result = parse_and_aggregate(xlsx_path)
    if result is None:
        log("집계 실패 - 위 경고 참고")
        sys.exit(1)
    totals, counts = result
    log("===== FSE코드별 입고 집계 결과 (대시보드는 반영하지 않음) =====")
    if not totals:
        log("  (FSE로 시작하는 Subinventory + 양수 수량 조건에 해당하는 행이 없음)")
    for code in sorted(totals):
        log(f"  {code}: qty={totals[code]}, lines={counts[code]}")


if __name__ == "__main__":
    main()
