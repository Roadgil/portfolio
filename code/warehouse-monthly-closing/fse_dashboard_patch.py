"""
FSE_CONSUMPTION_SEED / FSE_RECEIPT_SEED에 지정한 달(YYYY-MM) 데이터를 추가해
monthly_closing_dashboard.html에 패치한다.

**대시보드 직접 수정 스크립트다 - 반드시 백업 먼저 만들고, 기존 BEGIN/END 마커
사이만 교체한다(재생성 아님, 파일 전체를 openpyxl 등으로 다시 쓰지 않음 - 이
파일은 살아있는 HTML/JS라 통째로 재생성하면 포맷이 깨질 위험이 있음).**

On-Hand(온핸드)는 이 스크립트가 다루지 않는다 - 대시보드의 온핸드 수치는
"latest period"의 TS_DATA(창고 전체 마감자료, 별도 마스터 파일 업로드 흐름)에서
오는 것이라 FSE_CONSUMPTION_SEED/FSE_RECEIPT_SEED처럼 간단히 패치할 수 있는
구조가 아니다 - 온핸드는 기존 방식(마스터 파일 업로드)을 그대로 쓸 것.

금액(a) 계산: 대시보드의 ITEM_COST_LOOKUP(품목코드->USD단가)을 그대로 재사용해
수량×단가로 추정한다(기존 수기 반영 방식과 동일 원칙). 매칭 안 되는 품목코드는
수량 집계에는 포함하되 금액에서만 빠진다(기존 방식과 동일).

사용법:
    python fse_dashboard_patch.py --month 2026-09
    (--dry로 실제 파일은 안 건드리고 계산 결과만 확인 가능)
"""
import argparse
import calendar
import json
import re
import time
from datetime import date
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
DOWNLOAD_DIR = BASE_DIR / "downloads"
DASHBOARD_PATH = Path(
    r"C:\Users\yoongil.chae\OneDrive - Candela\바탕 화면\Monthly Closing\monthly_closing_dashboard.html"
)

KOREA_FSE_CODES = {
    "FSE002", "FSE003", "FSE004", "FSE006", "FSE007", "FSE012",
    "FSE013", "FSE014", "FSE015", "FSE016", "FSE017", "FSE018",
}

PN_RE = re.compile(r"PN:(\S+)")


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_item_cost_lookup(html_text):
    m = re.search(r"const ITEM_COST_LOOKUP = (\{.*?\});", html_text)
    if not m:
        raise RuntimeError("ITEM_COST_LOOKUP을 대시보드에서 못 찾음")
    return json.loads(m.group(1))


def load_seed(html_text, name):
    # BEGIN 마커와 실제 const 선언 사이에 설명 주석 줄이 끼어있는 경우가 있어
    # (예: "// 2026-09-15: ...") \s*가 아니라 [\s\S]*?로 그 사이를 통째로 건너뛴다.
    m = re.search(
        rf"/\* {name}_BEGIN \*/[\s\S]*?const {name} =\s*(\{{.*?\}});\s*/\* {name}_END \*/",
        html_text, re.DOTALL,
    )
    if not m:
        raise RuntimeError(f"{name} 블록을 못 찾음")
    return json.loads(m.group(1))


def save_seed(html_text, name, data):
    # BEGIN/END 마커 사이의 설명 주석 등은 그대로 두고, "const NAME = {...};"
    # 선언 부분만 정확히 교체한다(주석까지 통째로 날리지 않기 위해 - 2026-09-30
    # 실측으로 이 사이에 출처 설명 주석이 들어있는 걸 발견함).
    new_decl = f"const {name} = {json.dumps(data)};"
    pattern = rf"(/\* {name}_BEGIN \*/[\s\S]*?)const {name} =\s*\{{.*?\}};([\s\S]*?/\* {name}_END \*/)"
    new_text, n = re.subn(
        pattern,
        lambda mm: mm.group(1) + new_decl.replace("\\", "\\\\") + mm.group(2),
        html_text, count=1, flags=re.DOTALL,
    )
    if n != 1:
        raise RuntimeError(f"{name} 블록 치환 실패(매칭 {n}회)")
    return new_text


def extract_pn(raw):
    raw = str(raw).strip()
    m = PN_RE.search(raw)
    return m.group(1) if m else raw


def compute_consumption(month_str, item_cost):
    y, mth = map(int, month_str.split("-"))
    first = date(y, mth, 1)
    last = date(y, mth, calendar.monthrange(y, mth)[1])
    csv_path = DOWNLOAD_DIR / f"korea_fse_consumed_{first.isoformat()}_{last.isoformat()}.csv"
    if not csv_path.exists():
        raise RuntimeError(f"소모량 원본 파일 없음: {csv_path} - fse_consumption_puller.py를 먼저 실행하세요")
    df = pd.read_csv(csv_path, encoding="utf-8")
    df = df[df["Oracle Subinventory"].astype(str).isin(KOREA_FSE_CODES)]

    result = {}
    for code, sub in df.groupby("Oracle Subinventory"):
        qty = pd.to_numeric(sub["Line Qty"], errors="coerce").sum()
        amt = 0.0
        matched_amt = False
        for _, row in sub.iterrows():
            pn = extract_pn(row["Consumed Part Code and Serial"])
            cost = item_cost.get(pn)
            q = pd.to_numeric(row["Line Qty"], errors="coerce") or 0
            if cost is not None:
                amt += q * cost
                matched_amt = True
        result[code] = {"q": -float(qty), "a": -float(amt) if matched_amt else None}
    return result


def compute_receipt(month_str, item_cost):
    # 최신 receipt_completed_transactions_*.xlsx 중 이 달에 해당하는 걸 못
    # 구분하므로(파일명에 타임스탬프만 있음), 가장 최근 파일을 그 달 것으로 간주한다
    # - fse_receipt_puller.py를 그 달 마감 시점에 막 돌린 뒤 바로 이 스크립트를
    # 실행하는 흐름을 전제로 한다.
    files = sorted(DOWNLOAD_DIR.glob("receipt_completed_transactions_*.xlsx"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise RuntimeError("입고 원본 파일이 없음 - fse_receipt_puller.py를 먼저 실행하세요")
    latest = files[-1]
    log(f"입고 원본 파일: {latest.name}")
    tables = pd.read_html(latest, encoding="utf-8")
    df = max(tables, key=len)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[-1] for c in df.columns]
    df = df[df["Subinventory"].astype(str).str.startswith("FSE", na=False)]
    df = df[pd.to_numeric(df["Transaction Quantity"], errors="coerce") > 0]

    result = {}
    for code, sub in df.groupby("Subinventory"):
        qty = pd.to_numeric(sub["Transaction Quantity"], errors="coerce").sum()
        amt = 0.0
        matched_amt = False
        for _, row in sub.iterrows():
            pn = str(row["Item"]).strip()
            cost = item_cost.get(pn)
            q = pd.to_numeric(row["Transaction Quantity"], errors="coerce") or 0
            if cost is not None:
                amt += q * cost
                matched_amt = True
        result[code] = {"q": float(qty), "a": float(amt) if matched_amt else None}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--dry", action="store_true", help="계산만 하고 파일은 안 건드림")
    args = parser.parse_args()

    y, m = map(int, args.month.split("-"))
    period_key = f"{y}.{m}"

    html_text = DASHBOARD_PATH.read_text(encoding="utf-8")
    item_cost = load_item_cost_lookup(html_text)
    log(f"ITEM_COST_LOOKUP {len(item_cost)}개 품목 로드")

    consumption = compute_consumption(args.month, item_cost)
    receipt = compute_receipt(args.month, item_cost)

    log(f"===== {period_key} 소모 =====")
    for code in sorted(consumption):
        log(f"  {code}: {consumption[code]}")
    log(f"===== {period_key} 입고 =====")
    for code in sorted(receipt):
        log(f"  {code}: {receipt[code]}")

    if args.dry:
        log("[dry] 파일은 건드리지 않음")
        return

    cons_seed = load_seed(html_text, "FSE_CONSUMPTION_SEED")
    recv_seed = load_seed(html_text, "FSE_RECEIPT_SEED")

    if period_key in cons_seed or period_key in recv_seed:
        log(f"[경고] {period_key}이 이미 시드에 존재함 - 덮어씀")

    cons_seed[period_key] = consumption
    recv_seed[period_key] = receipt

    backup_path = DASHBOARD_PATH.with_name(
        f"monthly_closing_dashboard_backup_{time.strftime('%Y%m%d_%H%M%S')}.html"
    )
    backup_path.write_text(html_text, encoding="utf-8")
    log(f"백업 완료: {backup_path.name}")

    new_text = save_seed(html_text, "FSE_CONSUMPTION_SEED", cons_seed)
    new_text = save_seed(new_text, "FSE_RECEIPT_SEED", recv_seed)
    DASHBOARD_PATH.write_text(new_text, encoding="utf-8")
    log(f"패치 완료: {DASHBOARD_PATH.name}에 {period_key} 추가됨")


if __name__ == "__main__":
    main()
