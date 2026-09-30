"""
Oracle Fusion > Tools > Reports and Analytics > "Candela Inventory Current On Hand
Balances" 리포트에서 KRP 재고 온핸드 스냅샷을 받는다. 이 리포트는 특정 월이 아니라
'지금 시점' 스냅샷이므로 월 인자가 없다.

대시보드는 이 스크립트가 건드리지 않는다 - 원본 데이터 수집까지만.

**2026-09-30 실측 검증 완료.**
- 화면 경로: 홈 → "Tools" 탭 클릭 → APPS의 "Reports and Analytics" 타일 클릭 →
  Favorites 목록의 "Candela Inventory Current On Hand Balances..." 링크 클릭
  (이 클릭이 **새 팝업 페이지**를 연다 - `context.expect_page()`로 잡아야 함).
- 파라미터 폼은 팝업 페이지 안의 **iframe**(`xmlpserver/Custom/...` URL)에 있다.
- "Inventory Organization" 필드는 자유입력이 아니라 **멀티체크박스 팝업**
  (class="mchoicebox", readonly input) - 클릭하면 체크리스트(GFD 기본 체크,
  KRP 미체크)가 뜨고, GFD 체크 해제 + KRP 체크 후 Apply.

수동 실행법:
    C:\\Users\\yoongil.chae\\Miniconda\\python.exe fse_onhand_puller.py

로그인 실패 시 확인할 것: oracle_login.py 모듈 docstring 참고.
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
import oracle_login  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = BASE_DIR / "fse_onhand_puller.log"

# 2026-09-30: fse_receipt_puller.py와 별도 프로필로 분리 - 같은 프로필을 쓰면
# 두 스크립트를 동시에(병렬) 실행할 때 launch_persistent_context가
# "Opening in existing browser session"으로 충돌한다. 로그인은 AzureAD SSO
# 버튼 클릭이라 프로필이 늘어도 매번 비밀번호 입력 없이 통과된다.
PROFILE_DIR = r"C:\Users\yoongil.chae\.fse_onhand_puller\pw_profile"

REPORT_NAME = "Candela Inventory Current On Hand Balances"
ORG_INPUT_SELECTOR = "#xdo\\:xdo\\:_paramsP_ORG_CODE_div_input"


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _screenshot(page, name):
    path = BASE_DIR / f"error_{name}.png"
    try:
        page.screenshot(path=str(path))
        log(f"  (스크린샷 저장: {path})")
    except Exception:
        pass


def open_report(context, page):
    """홈 -> Tools 탭 -> Reports and Analytics -> 리포트 링크(새 팝업 페이지).
    반환값: 팝업 Page 객체."""
    log("Tools 탭 진입...")
    page.get_by_text("Tools", exact=True).first.click(timeout=30000, force=True)
    page.wait_for_timeout(2000)

    log("Reports and Analytics 타일 클릭...")
    page.get_by_text("Reports and Analytics", exact=True).first.click(timeout=30000, force=True)
    page.wait_for_timeout(4000)

    log(f"'{REPORT_NAME}' 리포트 링크 클릭(새 팝업 대기)...")
    try:
        with context.expect_page(timeout=15000) as new_page_info:
            page.get_by_text(REPORT_NAME, exact=False).first.click(timeout=30000, force=True)
        rp = new_page_info.value
    except Exception as e:
        _screenshot(page, "onhand_report_link_fail")
        raise RuntimeError(f"'{REPORT_NAME}' 리포트 열기 실패: {e}")

    rp.wait_for_load_state("load", timeout=30000)
    rp.wait_for_timeout(8000)
    log(f"리포트 팝업 페이지 도착 (title={rp.title()!r})")
    return rp


def set_organization_krp_and_apply(rp):
    """파라미터 iframe에서 Inventory Organization을 GFD 체크해제+KRP 체크 후 Apply."""
    try:
        param_frame = next(f for f in rp.frames if "xmlpserver/Custom" in f.url)
    except StopIteration:
        _screenshot(rp, "onhand_param_frame_not_found")
        raise RuntimeError("파라미터 iframe(xmlpserver/Custom)을 찾지 못함")

    log("Inventory Organization 체크박스 팝업 여는 중...")
    try:
        org_input = param_frame.locator(ORG_INPUT_SELECTOR)
        org_input.click(timeout=10000, force=True)
        rp.wait_for_timeout(1000)
    except Exception as e:
        _screenshot(rp, "onhand_org_popup_fail")
        raise RuntimeError(f"Inventory Organization 팝업 열기 실패: {e}")

    try:
        checks = param_frame.locator("input[type='checkbox']")
        gfd_cb = None
        krp_cb = None
        for i in range(min(checks.count(), 10)):
            cb = checks.nth(i)
            text = cb.evaluate(
                "e => e.closest('tr') ? e.closest('tr').innerText : "
                "(e.parentElement ? e.parentElement.innerText : '')"
            ).strip()
            if text == "GFD":
                gfd_cb = cb
            elif text == "KRP":
                krp_cb = cb
        if gfd_cb is None or krp_cb is None:
            raise RuntimeError(f"GFD/KRP 체크박스를 못 찾음(gfd_cb={gfd_cb}, krp_cb={krp_cb})")
        if gfd_cb.is_checked():
            gfd_cb.click(force=True)
        if not krp_cb.is_checked():
            krp_cb.click(force=True)
        rp.wait_for_timeout(500)
    except Exception as e:
        _screenshot(rp, "onhand_org_checkbox_fail")
        raise RuntimeError(f"GFD 해제/KRP 체크 실패: {e}")

    # 체크박스 팝업 닫기(바깥 클릭)
    try:
        param_frame.locator("body").click(position={"x": 5, "y": 5}, force=True)
    except Exception:
        pass
    rp.wait_for_timeout(500)

    # 2026-09-30 실측: (1) download 이벤트/save_as()는 "Target page, context or
    # browser has been closed"로 실패(Salesforce 소모량 스크립트와 동일 유형).
    # (2) page.on("response")로 관찰만 해서 resp.body()를 나중에 읽으려 하면
    # "Response body is not available for a response that was navigated away
    # from"로 실패 - CDP가 응답 직후 리소스를 버려서 한 박자 늦다.
    # 최종 해법: page.route()로 요청 자체를 가로채 Playwright가 직접
    # route.fetch()로 재요청한다 - 이 APIResponse는 body가 항상 완전히 버퍼링돼
    # 있어 이후 페이지가 어떻게 되든 안전하다.
    result = {}

    def _handle_route(route):
        req = route.request
        if "body" in result or "xdo?_xdo=" not in req.url:
            route.continue_()
            return
        try:
            resp = route.fetch()
        except Exception as e:
            result["err"] = e
            route.continue_()
            return
        # 실측(2026-09-30): 같은 URL 패턴으로 실제 파일이 오기 전에 "Report
        # Completed"(16바이트, content-disposition 없음) 같은 중간 상태확인
        # 응답이 먼저 온다 - content-disposition: attachment가 있는 진짜 파일
        # 응답만 받아들이고, 아니면 그대로 흘려보내 다음 요청을 계속 기다린다.
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

    rp.route("**/xmlpserver/servlet/xdo**", _handle_route)

    log("Apply 클릭 중... (리포트 생성에 시간이 걸릴 수 있어 최대 4분 대기)")
    try:
        param_frame.get_by_role("button", name="Apply", exact=True).click()
    except Exception as e:
        log(f"[경고] Apply 클릭 중 예외(응답 캡처로 계속 진행): {e}")

    deadline = time.time() + 240
    while time.time() < deadline and "body" not in result and "err" not in result:
        try:
            rp.wait_for_timeout(500)
        except Exception:
            break  # 페이지가 닫혀도 이미 잡힌 응답이 있으면 문제 없음

    if "body" not in result:
        _screenshot_safe(rp)
        raise RuntimeError(f"export 응답을 못 잡음(err={result.get('err')})")

    save_path = DOWNLOAD_DIR / f"krp_onhand_{int(time.time())}.xlsx"
    save_path.write_bytes(result["body"])
    log(f"다운로드 완료: {save_path} ({len(result['body'])} bytes)")
    return save_path


def _screenshot_safe(rp):
    try:
        _screenshot(rp, "onhand_export_capture_fail")
    except Exception:
        pass


def parse_and_aggregate(xlsx_path):
    """2026-09-30 실측: BI Publisher가 만든 진짜 바이너리 .xls(OLE2, 옛 Excel
    포맷) - 앞쪽 13행이 리포트 제목/실행일자/파라미터 블록이라 header=13으로
    읽어야 진짜 컬럼명(Organization, Subinventory, On-hand Qty 등)이 나온다."""
    import pandas as pd

    df = pd.read_excel(xlsx_path, header=13)
    log(f"컬럼: {list(df.columns)}")

    sub_col = "Subinventory" if "Subinventory" in df.columns else None
    qty_col = "On-hand Qty" if "On-hand Qty" in df.columns else None
    if not sub_col or not qty_col:
        log("[경고] Subinventory/On-hand Qty 컬럼을 자동으로 못 찾음 - 전체 컬럼을 보고 수동 확인하세요.")
        print(df.head(20).to_string())
        return None

    fse_df = df[df[sub_col].astype(str).str.startswith("FSE", na=False)]
    totals = fse_df.groupby(sub_col)[qty_col].apply(
        lambda s: pd.to_numeric(s, errors="coerce").sum()
    ).to_dict()
    counts = fse_df.groupby(sub_col).size().to_dict()
    return totals, counts


def main():
    log("===== KRP 재고 On-Hand Oracle pull 시작 =====")
    with sync_playwright() as p:
        context, page, logged_in = oracle_login.open_oracle(p, PROFILE_DIR, log)
        if not logged_in:
            log("[중단] 로그인 확인 안 됨 - 이 창에서 직접 로그인 후 다시 실행하세요.")
            context.close()
            sys.exit(1)
        try:
            rp = open_report(context, page)
            xlsx_path = set_organization_krp_and_apply(rp)
        except Exception as e:
            # 2026-09-30 실측: 그냥 return하면 exit code 0이라 상위 오케스트레이터가
            # 실패를 "성공"으로 오판한다 - 반드시 sys.exit(1)로 전파해야 함.
            log(f"[오류] {e}")
            context.close()
            sys.exit(1)
        context.close()

    log(f"다운로드 완료 - 집계 시작: {xlsx_path}")
    result = parse_and_aggregate(xlsx_path)
    if result is None:
        log("집계 실패 - 위 경고 참고")
        sys.exit(1)
    totals, counts = result
    log("===== FSE코드별 온핸드 재고 집계 결과 (대시보드는 반영하지 않음) =====")
    if not totals:
        log("  (FSE로 시작하는 Subinventory 행이 없음)")
    for code in sorted(totals):
        log(f"  {code}: qty={totals[code]}, lines={counts[code]}")


if __name__ == "__main__":
    main()
