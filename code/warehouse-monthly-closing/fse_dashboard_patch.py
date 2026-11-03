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
import os
DASHBOARD_PATH = Path(os.environ.get("FSE_DASHBOARD_PATH") or
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\19. Monthly Closing\monthly_closing_dashboard.html"
)  # 시험 시 환경변수 FSE_DASHBOARD_PATH로 복사본을 가리킬 수 있음
ITEM_STATS_DIR = DOWNLOAD_DIR / "item_stats"

KOREA_FSE_CODES = {
    "FSE002", "FSE003", "FSE004", "FSE006", "FSE007", "FSE012",
    "FSE013", "FSE014", "FSE015", "FSE016", "FSE017", "FSE018",
}

PN_RE = re.compile(r"PN:(\S+)")


def load_tool_items():
    """소모되지 않는 공구/지그(fse_tool_items.json) - 회전율용 소모·입고 집계에서 제외 (2026-10-15)."""
    p = BASE_DIR / "fse_tool_items.json"
    return set(json.loads(p.read_text(encoding="utf-8")).get("items", {})) if p.exists() else set()


TOOL_ITEMS = load_tool_items()


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
    # 2026-10-07: 새 소모 풀러가 만든 월별 파일(Closed 필터 해제, Scheduled 월 기준, Canceled 제외 - 기존 수기 집계와 일치 검증됨)
    csv_path = ITEM_STATS_DIR / f"sf_consumed_{y}-{mth:02d}.csv"
    if not csv_path.exists():
        raise RuntimeError(f"소모량 원본 파일 없음: {csv_path} - fse_consumption_puller.py를 먼저 실행하세요")
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    df = df[df["Oracle Subinventory"].astype(str).isin(KOREA_FSE_CODES)]
    df = df[~df["Consumed Part Code and Serial"].map(extract_pn).isin(TOOL_ITEMS)]   # 공구 제외

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
        result[code] = {"q": int(round(-qty)), "a": round(float(-amt), 2) if matched_amt else None}
    return result


def compute_receipt(month_str, item_cost):
    # 2026-10-07: 입고 풀러가 월별로 보관한 파일(item_stats/receipt_YYYY-MM.xlsx, 거래일 월범위 검증 통과본)을 쓴다.
    # (예전엔 '가장 최근 다운로드'를 그 달 것으로 간주해서 다른 달 파일을 집을 위험이 있었음)
    latest = ITEM_STATS_DIR / f"receipt_{month_str}.xlsx"
    if not latest.exists():
        raise RuntimeError(f"입고 원본 파일이 없음: {latest} - fse_receipt_puller.py를 먼저 실행하세요")
    log(f"입고 원본 파일: {latest.name}")
    tables = pd.read_html(latest, encoding="utf-8")
    df = max(tables, key=len)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[-1] for c in df.columns]
    df = df[df["Subinventory"].astype(str).str.startswith("FSE", na=False)]
    df = df[df["Transaction Type"] == "Transfer Order Intraorganization Transfer"]   # 대시보드 입고 정의와 동일
    df = df[~df["Item"].astype(str).str.strip().isin(TOOL_ITEMS)]                     # 공구 제외
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
        result[code] = {"q": int(round(qty)), "a": round(float(amt), 2) if matched_amt else None}
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
