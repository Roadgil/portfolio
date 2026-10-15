"""
Salesforce Classic 리포트 "Korea_FSE_Consumed Part"(Id=<report-id>)에서 FSE 소모 내역을 받는다.

2026-10-07 재작성 (이전 버전 백업: fse_consumption_puller_backup_20261007b.py).
이전 버전은 화면에서 기간을 지정해도 `?export=1` GET이 그 기간을 무시하고 저장된 기본값(현재 분기)을
내려줘서 월 필터가 사실상 안 먹혔고(8월/9월 파일이 동일했음), 리포트 기본 필터
"Work Order Status not equal to Closed" 때문에 이미 마감된 WO의 소모가 빠졌다.

지금 방식(실측 검증: 2~5월 기존 수기 집계와 수량·금액까지 일치):
  1) 리포트를 열고 "Work Order Status not equal to Closed" 필터만 이번 실행에서 해제(저장 안 함)
  2) Time Frame = Work Detail: Created Date, 대상월 기준 12개월 전 1일 ~ 오늘 (넓게 한 번에 받음)
  3) 화면 폼 상태 그대로 POST로 CSV export (export URL GET 아님)
  4) 소모월은 Scheduled Date Time 기준으로 분류, Canceled WO 제외, Oracle Subinventory가 FSE인 행만
출력: downloads/item_stats/sf_consumed_YYYY-MM.csv (월별), sf_consumed_range_latest.csv (원본 전체)
대시보드(FSE_CONSUMPTION_SEED)는 건드리지 않는다 — 원본 데이터 수집까지만.
로그인은 회사 SSO(Windows 세션) - 전용 프로필 사용.

사용법: python fse_consumption_puller.py --month 2026-09
종료 코드: 성공 0 / 실패 1 (대상월 소모 행이 하나도 없어도 실패로 본다)
"""
import argparse
import calendar
import re
import sys
import time
from datetime import date
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "downloads" / "item_stats"
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = BASE_DIR / "fse_consumption_puller.log"

REPORT_URL = "https://<your-org>.my.salesforce.com/<report-id>"
PROFILE_DIR = r"C:\Users\yoongil.chae\.fse_consumption_puller\pw_profile"
START_FSE_PREFIX = "FSE"


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


def filter_text(page):
    t = page.evaluate("()=>document.body.innerText").replace("\xa0", " ")
    i = t.find("Filtered By")
    return t[i:i + 400] if i >= 0 else ""


EXPORT_JS = """async()=>{
  const f=document.report; const params=new URLSearchParams(new FormData(f));
  params.set('export','1'); params.set('enc','UTF-8'); params.set('xf','csv'); params.set('runPageAction','EXPORT');
  const r=await fetch(f.action,{method:'POST',body:params,credentials:'include',headers:{'Content-Type':'application/x-www-form-urlencoded'}});
  return [r.status, await r.text()];
}"""


def fetch_report_csv(from_date, to_date):
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(PROFILE_DIR, headless=False, channel="msedge")
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(60000)
        try:
            log("1) 리포트 여는 중...")
            page.goto(REPORT_URL)
            page.wait_for_load_state("load", timeout=30000)
            page.wait_for_timeout(2500)
            if "FSE" not in page.title().upper():
                raise RuntimeError(f"리포트 페이지를 확인 못함 (title={page.title()!r})")

            log("2) 'Closed 제외' 필터 해제(이번 실행에서만, 저장 안 함)...")
            cleared = page.evaluate("""()=>{const as=[...document.querySelectorAll('a')].filter(a=>a.textContent.trim()==='Clear'&&/Closed/.test(a.parentElement.textContent)); if(!as.length) return false; as[0].click(); return true}""")
            if cleared:
                page.wait_for_load_state("load", timeout=30000)
                page.wait_for_timeout(2500)
            if "not equal to Closed" in filter_text(page):
                raise RuntimeError("Closed 제외 필터를 해제하지 못함")
            log(f"   해제 {'완료' if cleared else '불필요(이미 없음)'}")

            log(f"3) 기간 설정(Created Date): {fmt_date_kr(from_date)} ~ {fmt_date_kr(to_date)}")
            page.select_option("#colDt_q", "custom")
            page.fill("#colDt_s", fmt_date_kr(from_date))
            page.fill("#colDt_e", fmt_date_kr(to_date))
            page.click("input[name='run']")
            page.wait_for_load_state("load", timeout=30000)
            page.wait_for_timeout(2500)
            if "not equal to Closed" in filter_text(page):
                raise RuntimeError("Run 후 Closed 제외 필터가 다시 걸려 있음")

            log("4) 폼 상태 그대로 CSV export(POST)...")
            status, body = page.evaluate(EXPORT_JS)
            if status != 200 or not body.startswith('"Work Order Status"'):
                raise RuntimeError(f"export 응답 이상 (status={status}, head={body[:80]!r})")
            log(f"   수신 {len(body):,} bytes")
            return body
        except Exception:
            try:
                page.screenshot(path=str(BASE_DIR / "error_export.png"))
            except Exception:
                pass
            raise
        finally:
            context.close()


def split_and_save(csv_text, target_month):
    import io
    import pandas as pd

    (OUT_DIR / "sf_consumed_range_latest.csv").write_text(csv_text, encoding="utf-8", newline="")
    df = pd.read_csv(io.StringIO(csv_text))
    log(f"  read_csv: {len(df)}행")
    d = df["Scheduled Date Time"].astype(str).str.extract(r"(\d{4})\. (\d+)\. (\d+)")
    df["ym"] = d[0] + "-" + d[1].str.zfill(2)
    df = df[df["Oracle Subinventory"].astype(str).str.startswith(START_FSE_PREFIX)
            & (df["Work Order Status"] != "Canceled") & df["ym"].notna()]
    months = sorted(df["ym"].unique())
    for m in months:
        if m < "2026-01":
            continue  # 마감 이력 시작(2026-01) 이전은 보관하지 않음
        df[df["ym"] == m].drop(columns="ym").to_csv(OUT_DIR / f"sf_consumed_{m}.csv", index=False, encoding="utf-8-sig")
    tgt = df[df["ym"] == target_month]
    if tgt.empty:
        raise RuntimeError(f"대상월 {target_month} 소모 행이 하나도 없음 (필터/기간 이상 가능)")
    log(f"  저장 완료: {len([m for m in months if m >= '2026-01'])}개월분 / 대상월 {target_month} 소모 {int(tgt['Line Qty'].sum())}개, {len(tgt)}행")
    for code, g in tgt.groupby("Oracle Subinventory"):
        log(f"  {code}: qty={int(g['Line Qty'].sum())}, lines={len(g)}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    args = parser.parse_args()
    y, m = map(int, args.month.split("-"))
    from_date = date(y - 1, m, 1)
    to_date = date.today()
    log(f"===== FSE 소모량 Salesforce pull 시작: {args.month} (Created {from_date} ~ {to_date}) =====")

    body, last_err = None, None
    for attempt in range(1, 4):
        try:
            body = fetch_report_csv(from_date, to_date)
            break
        except Exception as e:
            last_err = e
            log(f"[재시도 {attempt}/3] 실패({e.__class__.__name__}: {e})")
    if body is None:
        log(f"[실패] 3회 모두 실패. 마지막 오류: {last_err}")
        sys.exit(1)
    try:
        split_and_save(body, args.month)
    except Exception as e:
        log(f"[실패] 저장/검증 단계: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
