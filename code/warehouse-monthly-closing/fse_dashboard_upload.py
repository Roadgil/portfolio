"""
monthly_closing_dashboard.html의 "📦 현재 월 업로드" 탭에 온핸드(Inventory On-hand)
+ Intransit Details Report 파일을 실제로 넣고 저장한 뒤, "📥 공유용 HTML 다운로드"
기능으로 현재 상태(온핸드가 반영된 새 기간 + 기존 FSE_CONSUMPTION_SEED/
FSE_RECEIPT_SEED)를 통째로 구워낸 새 파일을 받아 원본을 교체한다.

**소모/입고(FSE_CONSUMPTION_SEED/FSE_RECEIPT_SEED)는 이 스크립트가 업로드하지
않는다** - fse_dashboard_patch.py로 이미 파일에 직접 패치돼 있고(2026-09-30),
"공유용 HTML 다운로드"는 현재 페이지에 로드된 fseConsumption/fseReceipt(=이미
패치된 SEED에서 초기화됨)를 그대로 재직렬화하므로 자동으로 같이 보존된다.

**대시보드는 이 스크립트가 아니라 브라우저 자바스크립트(aggregateLive 등)가
계산한다** - 온핸드 파일 파싱/카테고리 집계는 전부 대시보드 자체 JS 로직을 그대로
쓴다(Python으로 따로 재구현하지 않음 - 재구현 시 대시보드 로직과 미묘하게
어긋날 위험을 피하기 위함).

사용법:
    python fse_dashboard_upload.py --month 2026.9 --onhand <온핸드 xlsx 경로> --intransit <Intransit xlsx 경로>
    (인자 생략 시 downloads 폴더의 최신 온핸드 파일 + 오늘 날짜의 Intransit 파일을 자동으로 찾는다)
"""
import argparse
import shutil
import sys
import time
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

# Windows 콘솔 코드페이지(cp949)로 인해 "✓" 같은 문자에서 print()가 죽는 문제
# 방지(2026-09-30 실측) - stdout을 강제로 UTF-8로 재설정.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
import os
DASHBOARD_PATH = Path(os.environ.get("FSE_DASHBOARD_PATH") or
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\19. Monthly Closing\monthly_closing_dashboard.html"
)  # 시험 시 환경변수 FSE_DASHBOARD_PATH로 복사본을 가리킬 수 있음
INTRANSIT_DIR = Path(
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\10. 수입\Intransit Details Report"
)
INTRANSIT_FILENAME_FMT = "APAC Candela Intransit Details Report_{ymd}.xlsx"
PROFILE_DIR = r"C:\Users\yoongil.chae\.fse_dashboard_upload\pw_profile"


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def find_latest_onhand():
    files = sorted(DOWNLOAD_DIR.glob("krp_onhand_*.xlsx"), key=lambda p: p.stat().st_mtime)
    files = [f for f in files if f.stat().st_size > 1000]  # 실패한 16바이트 파일 등 제외
    if not files:
        raise RuntimeError("온핸드 원본 파일이 없음 - fse_onhand_puller.py를 먼저 실행하세요")
    return files[-1]


def find_intransit_for_today():
    ymd = date.today().strftime("%Y%m%d")
    path = INTRANSIT_DIR / INTRANSIT_FILENAME_FMT.format(ymd=ymd)
    if not path.exists():
        raise RuntimeError(f"오늘({ymd}) Intransit 파일이 없음: {path}")
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help='기간 라벨, 예: "2026.9"')
    parser.add_argument("--onhand", help="온핸드 xlsx 경로(생략 시 최신 파일 자동 탐색)")
    parser.add_argument("--intransit", help="Intransit xlsx 경로(생략 시 오늘 날짜 파일 자동 탐색)")
    args = parser.parse_args()

    onhand_path = Path(args.onhand) if args.onhand else find_latest_onhand()
    intransit_path = Path(args.intransit) if args.intransit else find_intransit_for_today()
    log(f"온핸드 파일: {onhand_path.name}")
    log(f"Intransit 파일: {intransit_path.name}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=False, channel="msedge", accept_downloads=True,
        )
        page = context.pages[0] if context.pages else context.new_page()

        # 확인 대화상자(같은 기간 재저장 등)가 뜨면 항상 수락 - 마감 자동화라
        # 사람이 지켜보지 않아도 진행돼야 함.
        page.on("dialog", lambda d: d.accept())

        log("대시보드 열기...")
        page.goto(DASHBOARD_PATH.as_uri())
        page.wait_for_load_state("load", timeout=15000)
        # 2026-10-07: 이 프로필의 localStorage에 이전 자동 실행이 저장해 둔 월 데이터가 남아 있으면 대시보드가
        # 파일에 구워진 값(사용자가 나중에 적은 특이사항 등)보다 그 저장본을 우선해서, 내보내기 때 지난달
        # 특이사항이 통째로 지워진다(시험에서 2026.9 MRB/RMA_NV 특이사항 소실로 발견). 매번 비우고 파일 기준으로 시작.
        page.evaluate("() => { try { localStorage.clear(); } catch (e) {} }")
        page.reload()
        page.wait_for_load_state("load", timeout=15000)
        page.wait_for_timeout(1000)

        log("'현재 월 업로드' 탭 클릭...")
        page.get_by_text("현재 월 업로드", exact=False).first.click(timeout=10000)
        page.wait_for_timeout(500)

        log("온핸드 파일 업로드...")
        page.locator("#file-inv").set_input_files(str(onhand_path))
        page.wait_for_timeout(2000)

        log("Intransit 파일 업로드...")
        page.locator("#file-int").set_input_files(str(intransit_path))
        page.wait_for_timeout(2000)

        save_btn = page.locator("#btn-save-period")
        if save_btn.is_disabled():
            path = BASE_DIR / "error_upload_not_enabled.png"
            page.screenshot(path=str(path))
            status_text = page.locator("#status").inner_text()
            raise RuntimeError(f"저장 버튼이 활성화되지 않음(파일 파싱 실패로 추정) - status={status_text!r}, 스크린샷={path}")

        log(f"기간 라벨 '{args.month}' 입력...")
        label_input = page.locator("#live-label")
        label_input.fill("")
        label_input.fill(args.month)

        # 같은 기간을 다시 저장(재시도/재실행)하면 대시보드가 입력칸 값만 쓰기 때문에 그 달에 이미 적혀 있던
        # 특이사항이 지워진다 - 기존 특이사항을 미리 입력칸에 채워 넣어 보존한다.
        existing = page.evaluate("""(l) => {
            const d = (typeof savedPeriods !== 'undefined' && savedPeriods[l]) || (TS_DATA.data && TS_DATA.data[l]);
            if (!d) return {};
            const o = {};
            CATEGORIES.forEach(c => { if (d[c] && d[c].r) o[c] = d[c].r; });
            return o;
        }""", args.month)
        if existing:
            filled = 0
            for cat, text in existing.items():
                inp = page.locator(f'#live-table-wrap input.remark-input[data-mode="live"][data-cat="{cat}"]')
                if inp.count() and not inp.first.input_value().strip():
                    inp.first.fill(text)
                    filled += 1
            log(f"기존 특이사항 {filled}건 보존(같은 기간 재저장)")

        log("저장 & 시계열에 추가 클릭...")
        save_btn.click()
        page.wait_for_timeout(2000)
        status_text = page.locator("#status").inner_text()
        log(f"저장 상태: {status_text}")
        if "저장되었습니다" not in status_text and "세션에 추가" not in status_text:
            path = BASE_DIR / "error_save_status_unclear.png"
            page.screenshot(path=str(path))
            log(f"[경고] 저장 성공 여부 불확실 - 스크린샷 확인: {path}")

        # 2026-10-07: "공유용 HTML 다운로드" 버튼 클릭 + download 이벤트 방식은 이 환경에서 불안정해서
        # (Download.save_as: Target page, context or browser has been closed - 시험 중 실제 발생) 쓰지 않는다.
        # 대시보드의 buildStandaloneHTML()이 돌려주는 문자열을 직접 받아 파일로 쓴다(같은 내용, 다운로드 경로 없음).
        log("공유용 HTML 생성(buildStandaloneHTML)...")
        html = page.evaluate("() => { const b = buildStandaloneHTML(); return b ? b.html : null; }")
        if not html or not html.rstrip().endswith("</html>"):
            raise RuntimeError("공유용 HTML 생성 실패(문자열이 비었거나 </html>로 끝나지 않음)")
        if f'"{args.month}"' not in html:
            raise RuntimeError(f"생성된 HTML에 새 기간 '{args.month}'이 없음 - 원본을 교체하지 않음")
        tmp_path = DOWNLOAD_DIR / f"dashboard_export_{int(time.time())}.html"
        tmp_path.write_text(html, encoding="utf-8", newline="")
        log(f"내보내기 완료: {tmp_path} ({tmp_path.stat().st_size} bytes)")

        context.close()

    backup_path = DASHBOARD_PATH.with_name(
        f"monthly_closing_dashboard_backup_{time.strftime('%Y%m%d_%H%M%S')}.html"
    )
    shutil.copy2(DASHBOARD_PATH, backup_path)
    log(f"백업 완료: {backup_path.name}")

    shutil.copy2(tmp_path, DASHBOARD_PATH)
    log(f"원본 교체 완료: {DASHBOARD_PATH.name}")


if __name__ == "__main__":
    main()
