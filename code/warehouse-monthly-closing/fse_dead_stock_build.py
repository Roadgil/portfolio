"""
FSE 6개월 미소모(Dead) 재고 추적 (2026-10-07, 신규 / 같은 날 단순화).

정의: 기준월 포함 최근 6개월 동안 그 FSE가 해당 품목을 한 번도 소모하지 않았는데 On-hand가 있는 것.
  보여주는 것은 엔지니어별로 "마지막 소모월"뿐이다. 마지막 소모가 6개월을 넘었으면 SP/FG로 돌려보낸다.
  (사용자 지시: 구분 A/B, 반환처 추정, 재배치 후보 등은 넣지 않는다 - FSE 간 이동은 하지 않음)
산출:
  1) Monthly Closing\\FSE_Dead재고_6개월미소모.xlsx (요약/상세)
  2) monthly_closing_dashboard.html의 FSE_DEAD_SEED 블록(마커 사이) 교체 — 없으면 FSE_RECEIPT_SEED_END 뒤에 삽입
입력은 fse_item_stats_build.py와 동일(월별 입고/소모 원본 + 최신 On-hand). 대시보드 패치 전 백업 생성.
사용법: python fse_dead_stock_build.py [--month YYYY-MM] [--no-patch]
  --month 생략 시 sf_consumed_YYYY-MM.csv 중 가장 최근 달. 확인 구간은 대상월 포함 최근 6개월.
  월마감 러너(fse_monthly_runner.py)가 수집 성공 후 자동으로 --month <그 달>로 호출한다.
seed row = [fse, item, desc, qty, cost, 마지막소모월('' = 1월 이후 소모 없음), 활동월수]
"""
import json
import re
import shutil
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fse_item_stats_build as B

WINDOW = 6
OUT = B.OUT.parent / "FSE_Dead재고_6개월미소모.xlsx"
DASH = B.DASH
BEGIN, END = "/* FSE_DEAD_SEED_BEGIN */", "/* FSE_DEAD_SEED_END */"


def compute():
    con, _ = B.load_consumption()
    onh, run, onname = B.load_onhand()
    cost = B.cost_lookup()
    win = B.MONTHS[-WINDOW:]

    fm = con.groupby(["fse", "month"])["qty"].sum()
    active = fm[fm > 0].groupby("fse").size().to_dict()

    oh = onh.groupby(["fse", "item"])["qty"].sum().reset_index()
    oh = oh[oh["qty"] > 0]
    desc = pd.concat([onh[["item", "desc"]], con[["item", "desc"]]]).drop_duplicates("item").set_index("item")["desc"]

    c_win = con[con.month.isin(win)].groupby(["fse", "item"])["qty"].sum()
    last_c = con[con.qty > 0].groupby(["fse", "item"])["month"].max()

    rows = []
    for _, r in oh.iterrows():
        k = (r["fse"], r["item"])
        if c_win.get(k, 0) > 0:
            continue
        rows.append({"fse": r["fse"], "item": r["item"], "desc": str(desc.get(r["item"], "")), "qty": int(r["qty"]),
                     "cost": cost.get(r["item"]), "last": last_c.get(k, ""), "act": int(active.get(r["fse"], 0))})
    df = pd.DataFrame(rows)
    df["val"] = (df["qty"] * df["cost"]).round(0)
    # 소모 이력 없는 것('')과 오래전에 마지막으로 쓴 것이 위로
    df = df.sort_values(["fse", "last", "qty"], ascending=[True, True, False])
    return df, run, onname, win, oh


def seed_json(df, run, onname, win):
    return {
        "asOf": run, "window": f"{win[0]}~{win[-1]}", "src": onname,
        "rows": [[r.fse, r.item, r.desc, r.qty, (None if pd.isna(r.cost) else float(r.cost)), r.last, r.act] for r in df.itertuples()],
    }


def patch_dashboard(seed):
    h = DASH.read_text(encoding="utf-8")
    # 공구 목록(fse_tool_items.json) 내장본 동기화 - 업로드 때 회전율용 '공구 제외 On-hand'를 계산하는 데 쓰인다
    tb, te = "/* FSE_TOOL_SEED_BEGIN */", "/* FSE_TOOL_SEED_END */"
    tool_block = tb + "\nconst FSE_TOOL_ITEMS = new Set(" + json.dumps(sorted(B.TOOL_ITEMS), ensure_ascii=False, separators=(",", ":")) + ");\n" + te
    if tb in h:
        h = re.sub(re.escape(tb) + r"[\s\S]*?" + re.escape(te), lambda m: tool_block, h, count=1)
    elif BEGIN in h:
        h = h.replace(BEGIN, tool_block + "\n" + BEGIN, 1)
    block = f"{BEGIN}\nconst FSE_DEAD_SEED = " + json.dumps(seed, ensure_ascii=False, separators=(",", ":")) + f";\n{END}"
    if BEGIN in h:
        h2 = re.sub(re.escape(BEGIN) + r"[\s\S]*?" + re.escape(END), lambda m: block, h, count=1)
    else:
        anchor = "/* FSE_RECEIPT_SEED_END */"
        if anchor not in h:
            raise RuntimeError("FSE_RECEIPT_SEED_END 마커를 못 찾음")
        h2 = h.replace(anchor, anchor + "\n" + block, 1)
    # 백업은 월 1개만(자동 실행이 매달 돌아도 파일이 계속 쌓이지 않게) - 이미 이번 달 백업이 있으면 그대로 둔다
    bak = DASH.with_name(f"monthly_closing_dashboard_backup_{time.strftime('%Y%m')}_dead.html")
    if not bak.exists():
        shutil.copy2(DASH, bak)
    DASH.write_text(h2, encoding="utf-8", newline="")
    return bak


def pick_months(target):
    """sf_consumed_YYYY-MM.csv 파일이 있는 달 중 2026-01 이후 ~ 대상월."""
    have = sorted(m.stem.replace("sf_consumed_", "") for m in (B.IS).glob("sf_consumed_20??-??.csv"))
    have = [m for m in have if m >= "2026-01"]
    if target:
        if target not in have:
            raise SystemExit(f"[중단] {target} 소모 파일(sf_consumed_{target}.csv)이 없음 - 소모 수집이 먼저 성공해야 함")
        have = [m for m in have if m <= target]
    if not have:
        raise SystemExit("[중단] sf_consumed_*.csv 파일이 없음")
    return have


def main():
    target = None
    if "--month" in sys.argv:
        target = sys.argv[sys.argv.index("--month") + 1]
    B.MONTHS = pick_months(target)          # fse_item_stats_build의 로더들이 이 목록을 읽는다
    print("대상 월 목록:", B.MONTHS[0], "~", B.MONTHS[-1], f"({len(B.MONTHS)}개월)")
    df, run, onname, win, oh = compute()
    seed = seed_json(df, run, onname, win)
    tot_oh = oh.groupby("fse")["qty"].sum()
    summ = df.groupby("fse").agg(품목수=("item", "count"), 수량=("qty", "sum"), 금액USD=("val", "sum")).reset_index()
    summ["FSE 보유수량"] = summ["fse"].map(tot_oh)
    summ["Dead 수량%"] = (summ["수량"] / summ["FSE 보유수량"] * 100).round(1)
    summ["관찰기간(활동월)"] = summ["fse"].map(df.groupby("fse")["act"].first())
    det = df.assign(last=df["last"].replace("", "소모 없음(1월~)"))[["fse", "item", "desc", "qty", "cost", "val", "last", "act"]]
    det.columns = ["FSE", "품목", "품목명", "현재고", "단가USD", "재고금액USD", "마지막 소모월", "활동월수"]
    note = pd.DataFrame([
        ["기준", f"On-hand {onname} ({run}) / 소모 Salesforce {B.MONTHS[0]}~{B.MONTHS[-1]}"],
        ["Dead 정의", f"최근 {WINDOW}개월({win[0]}~{win[-1]}) 그 FSE 소모 0 + On-hand > 0. 마지막 소모가 6개월을 넘었으면 SP/FG로 돌려보낸다."],
        ["제외", f"소모되지 않는 공구/지그 {len(B.TOOL_ITEMS)}개 품목은 제외(재고지만 이 도구로 부품을 수리하는 용도) - fse_tool_items.json 참고"],
        ["한계", "데이터가 2026-01부터라 '소모 없음(1월~)'은 최소 9개월 무소모라는 뜻. 활동월수 6 미만 FSE(신규 담당)는 참고용. 단가표에 없는 품목은 금액 공란."],
    ], columns=["항목", "내용"])
    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        note.to_excel(xw, sheet_name="설명", index=False)
        summ.to_excel(xw, sheet_name="FSE별 요약", index=False)
        det.to_excel(xw, sheet_name="Dead 상세", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                w = max(len(str(c.value)) if c.value is not None else 0 for c in list(col)[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(8, w + 2), 44)
    print("저장:", OUT)
    pd.set_option("display.width", 240, "display.max_columns", 30)
    print(summ.to_string(index=False))
    print("합계: 품목", len(df), "수량", int(df.qty.sum()), "금액(매칭분)", float(df.val.sum()),
          "| 소모 없음(1월~)", int((df["last"] == "").sum()), "| 과거 소모 있음", int((df["last"] != "").sum()))
    if "--no-patch" not in sys.argv:
        bak = patch_dashboard(seed)
        print("대시보드 seed 갱신 완료 / 백업:", bak.name)


if __name__ == "__main__":
    main()
