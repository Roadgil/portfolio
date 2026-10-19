"""
FSE 품목별 입고/소모 통계 + 분류 빌더 (2026-10-07, 신규).

입력 (downloads/item_stats/):
  receipt_YYYY-MM.xlsx           Oracle Review Completed Transactions(Transfer Order) 월별 원본 (HTML 마크업)
  sf_consumed_YYYY-MM.csv        Salesforce Korea_FSE_Consumed Part 월별(Scheduled Date 기준, 취소건 제외)
  ../krp_onhand_*.xlsx           현재 On-hand (가장 최근 유효 파일)
출력: Monthly Closing\\FSE_품목통계_2026-01_09.xlsx  (대시보드/state는 건드리지 않음)

정의
  입고 = Transaction Type 'Transfer Order Intraorganization Transfer' AND Subinventory가 FSE로 시작 AND 수량>0
  소모 = Salesforce Work Detail Line Qty (Oracle Subinventory가 FSE, Work Order Status != Canceled)
  자주 소모 = 9개월 중 6개월 이상 소모 / 보통 3~5개월 / 간헐 1~2개월 / 미사용 = 소모 0 + 현재고 > 0
  핵심(Hot 후보) = 자주 소모 중 소모량 누적 80% 이내
"""
import glob
import json
import re
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent
IS = BASE / "downloads" / "item_stats"
import os
DASH = Path(os.environ.get("FSE_DASHBOARD_PATH") or (BASE.parent / "monthly_closing_dashboard.html"))  # 시험 시 복사본 지정 가능
OUT = BASE.parent / "FSE_품목통계_2026-01_09.xlsx"
MONTHS = [f"2026-{i:02d}" for i in range(1, 10)]


def load_tool_items():
    """소모되지 않는 공구/지그 품번 집합(fse_tool_items.json). 파일이 없으면 제외 없음."""
    p = BASE / "fse_tool_items.json"
    if not p.exists():
        return set()
    return set(json.load(open(p, encoding="utf-8")).get("items", {}).keys())


TOOL_ITEMS = load_tool_items()


def pn_of(s):
    s = str(s).strip()
    m = re.search(r"PN:\s*(\S+)", s)
    return m.group(1) if m else s


def read_receipt(path):
    df = max(pd.read_html(str(path), encoding="utf-8"), key=len)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[-1] for c in df.columns]
    return df


def load_receipts():
    rows, status = [], {}
    for m in MONTHS:
        p = IS / f"receipt_{m}.xlsx"
        if not p.exists():
            status[m] = "없음"
            continue
        df = read_receipt(p)
        sub = df["Subinventory"].astype(str)
        q = pd.to_numeric(df["Transaction Quantity"], errors="coerce")
        f = df[(df["Transaction Type"] == "Transfer Order Intraorganization Transfer") & sub.str.startswith("FSE") & (q > 0)].copy()
        f["qty"] = pd.to_numeric(f["Transaction Quantity"])
        f["item"] = f["Item"].astype(str).str.strip()
        f["desc"] = f["Item Description"].astype(str)
        f["fse"] = f["Subinventory"].astype(str)
        f = f[~f["item"].isin(TOOL_ITEMS)]          # 공구는 재고 구성 분석에서 제외
        f["month"] = m
        rows.append(f[["month", "fse", "item", "desc", "qty"]])
        status[m] = f"{len(df)}행 → FSE 입고 {len(f)}건"
    return (pd.concat(rows) if rows else pd.DataFrame(columns=["month", "fse", "item", "desc", "qty"])), status


def load_consumption():
    rows = []
    for m in MONTHS:
        p = IS / f"sf_consumed_{m}.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p, encoding="utf-8-sig")
        df["month"] = m
        df["fse"] = df["Oracle Subinventory"].astype(str)
        df["item"] = df["Consumed Part Code and Serial"].map(pn_of)
        df["desc"] = df["Part"].astype(str)
        df["qty"] = pd.to_numeric(df["Line Qty"], errors="coerce")
        rows.append(df[["month", "fse", "item", "desc", "qty"]])
    df = pd.concat(rows)
    excluded = df[df["item"].str.upper().str.startswith(("KR-", "LABOR", "TRAVEL", "EXPENSE"))]
    df = df[~df["item"].str.upper().str.startswith(("KR-", "LABOR", "TRAVEL", "EXPENSE"))]
    df = df[~df["item"].isin(TOOL_ITEMS)]          # 공구는 재고 구성 분석에서 제외
    return df, sorted(excluded["item"].unique())


def load_onhand():
    cands = sorted(glob.glob(str(BASE / "downloads" / "krp_onhand_*.xlsx")), key=lambda p: Path(p).stat().st_mtime, reverse=True)
    for p in cands:
        if Path(p).stat().st_size < 100000:
            continue
        x = pd.read_excel(p, sheet_name="Sheet1", header=None)
        hdr = x.index[x.iloc[:, 0].astype(str).eq("Organization")].tolist()
        if not hdr:
            continue
        df = x.iloc[hdr[0] + 1:].copy()
        df.columns = [str(c).strip() for c in x.iloc[hdr[0]].tolist()]
        run = str(x.iloc[3, 1])
        cols = list(df.columns)
        sub = next(c for c in cols if c == "Subinventory")
        item = next(c for c in cols if c == "item")
        desc = next(c for c in cols if c == "Description")
        qty = next(c for c in cols if c.startswith("On-hand Qty"))
        df = df[df[sub].astype(str).str.startswith("FSE")]
        out = pd.DataFrame({"fse": df[sub].astype(str), "item": df[item].astype(str).str.strip(),
                            "desc": df[desc].astype(str), "qty": pd.to_numeric(df[qty], errors="coerce").fillna(0),
                            # Oracle 온핸드 리포트의 품목별 재고금액(USD) - 단가표(ITEM_COST_LOOKUP)에 없는 품목도 장부 금액을 알 수 있다
                            "val": pd.to_numeric(df["Item Value USD"], errors="coerce").fillna(0) if "Item Value USD" in df.columns else 0.0})
        out = out[~out["item"].isin(TOOL_ITEMS)]    # 공구는 재고 구성 분석에서 제외
        return out, run, Path(p).name
    raise RuntimeError("On-hand 파일 없음")


def cost_lookup():
    h = DASH.read_text(encoding="utf-8")
    m = re.search(r"const ITEM_COST_LOOKUP\s*=\s*(\{.*?\});", h, re.S)
    return json.loads(m.group(1)) if m else {}


def classify(r):
    if r["소모량합"] == 0:
        return "🧊 미사용(재고만 보유)" if r["현재고"] > 0 else "기록없음"
    if r["소모월수"] >= 6:
        return "🔥 자주 소모"
    if r["소모월수"] >= 3:
        return "보통"
    return "간헐"


def build_stats(rec, con, onh, cost, key):
    """key = ['item'] (전체) 또는 ['fse','item'] (FSE별)"""
    cm = con.pivot_table(index=key, columns="month", values="qty", aggfunc="sum", fill_value=0).reindex(columns=MONTHS, fill_value=0)
    rm = rec.pivot_table(index=key, columns="month", values="qty", aggfunc="sum", fill_value=0).reindex(columns=MONTHS, fill_value=0)
    oh = onh.groupby(key)["qty"].sum().rename("현재고")
    idx = cm.index.union(rm.index).union(oh.index)
    out = pd.DataFrame(index=idx)
    out["현재고"] = oh.reindex(idx).fillna(0)
    out["소모량합"] = cm.sum(axis=1).reindex(idx).fillna(0)
    out["소모월수"] = (cm > 0).sum(axis=1).reindex(idx).fillna(0).astype(int)
    out["월평균소모"] = (out["소모량합"] / len(MONTHS)).round(2)
    out["입고량합"] = rm.sum(axis=1).reindex(idx).fillna(0)
    out["입고월수"] = (rm > 0).sum(axis=1).reindex(idx).fillna(0).astype(int)
    out["순증(입고-소모)"] = out["입고량합"] - out["소모량합"]
    out["재고월수"] = (out["현재고"] / out["월평균소모"].where(out["월평균소모"] > 0)).round(1)
    last = cm.gt(0).apply(lambda r: max([m for m in MONTHS if r[m]], default=""), axis=1)
    out["마지막소모월"] = last.reindex(idx).fillna("")
    for m in MONTHS:
        out[f"소모_{m[5:]}월"] = cm[m].reindex(idx).fillna(0)
    for m in MONTHS:
        out[f"입고_{m[5:]}월"] = rm[m].reindex(idx).fillna(0)
    out = out.reset_index()
    names = pd.concat([con[["item", "desc"]], rec[["item", "desc"]], onh[["item", "desc"]]]).drop_duplicates("item").set_index("item")["desc"]
    out.insert(len(key), "품목명", out["item"].map(names).fillna(""))
    out["단가USD"] = out["item"].map(cost)
    out["재고금액USD"] = (out["현재고"] * out["단가USD"]).round(0)
    out["분류"] = out.apply(classify, axis=1)
    return out


def flag_core(items):
    f = items[items["분류"] == "🔥 자주 소모"].sort_values("소모량합", ascending=False)
    cum = f["소모량합"].cumsum() / f["소모량합"].sum()
    core = set(f.loc[cum.shift(fill_value=0) < 0.8, "item"])
    items["핵심(Hot 후보)"] = items["item"].isin(core).map({True: "Y", False: ""})
    return items


def flags(r):
    out = []
    if r["분류"] == "🔥 자주 소모" and pd.notna(r["재고월수"]) and r["재고월수"] < 1:
        out.append("⚠ 부족위험(재고<1개월분)")
    if r["분류"] in ("보통", "간헐", "🔥 자주 소모") and pd.notna(r["재고월수"]) and r["재고월수"] > 6:
        out.append("과다보유(>6개월분)")
    if r["분류"] in ("보통", "간헐") and r["현재고"] > 0 and r["마지막소모월"] and r["마지막소모월"] <= "2026-05":
        out.append("최근4개월 소모없음")
    if r["순증(입고-소모)"] > 0 and r["현재고"] > 0 and r["소모량합"] > 0 and r["순증(입고-소모)"] > r["월평균소모"] * 3:
        out.append("입고>소모 누적")
    return " / ".join(out)


def validate(rec, con, status):
    h = DASH.read_text(encoding="utf-8")
    rs = json.loads(re.search(r"FSE_RECEIPT_SEED_BEGIN \*/\s*const FSE_RECEIPT_SEED\s*=\s*(\{.*?\});\s*/\* FSE_RECEIPT_SEED_END", h, re.S).group(1))
    cs = json.loads(re.search(r"const FSE_CONSUMPTION_SEED\s*=\s*(\{.*?\});\s*\n", h, re.S).group(1))
    rows = []
    for m in MONTHS:
        key = f"{m[:4]}.{int(m[5:])}"
        for label, df, seed, sign in (("입고", rec, rs, 1), ("소모", con, cs, -1)):
            mine = df[df.month == m].groupby("fse")["qty"].sum().round().astype(int).to_dict()
            sd = {k: int(round(sign * v["q"])) for k, v in seed.get(key, {}).items()}
            diff = {k: (mine.get(k, 0), sd.get(k, 0)) for k in sorted(set(mine) | set(sd)) if mine.get(k, 0) != sd.get(k, 0)}
            rows.append({"월": m, "구분": label, "이번집계합": sum(mine.values()), "대시보드seed합": sum(sd.values()),
                         "일치여부": "일치" if not diff else "불일치", "불일치(FSE:이번,seed)": json.dumps(diff, ensure_ascii=False) if diff else ""})
    return pd.DataFrame(rows)


def main():
    rec, status = load_receipts()
    con, excl = load_consumption()
    onh, run, onname = load_onhand()
    cost = cost_lookup()
    items = flag_core(build_stats(rec, con, onh, cost, ["item"]))
    items["주의"] = items.apply(flags, axis=1)
    items = items.sort_values(["소모량합"], ascending=False)

    fi = build_stats(rec, con, onh, cost, ["fse", "item"])
    used_by_any = items.set_index("item")["소모량합"]
    fi["전체소모량(타FSE포함)"] = fi["item"].map(used_by_any)
    fi["주의"] = fi.apply(lambda r: "이 FSE 미사용·타FSE 사용(재배치 후보)" if r["분류"].startswith("🧊") and r["전체소모량(타FSE포함)"] > 0 else flags(r), axis=1)
    fi = fi.sort_values(["fse", "소모량합"], ascending=[True, False])

    val = validate(rec, con, status)

    dead = items[items["분류"].str.startswith("🧊")].sort_values("재고금액USD", ascending=False)
    fast = items[items["분류"] == "🔥 자주 소모"].sort_values("소모량합", ascending=False)

    summ = []
    summ.append(["기준", f"입고 Oracle 월별 {sum(1 for v in status.values() if v != '없음')}/9개월 · 소모 Salesforce 9개월 · On-hand {onname} (Report Run Date {run})"])
    for m, s in status.items():
        summ.append([f"  입고 {m}", s])
    summ.append(["품목 수(전체)", len(items)])
    for c, n in items["분류"].value_counts().items():
        summ.append([f"  {c}", int(n)])
    summ.append(["핵심(Hot 후보) 품목 수", int((items["핵심(Hot 후보)"] == "Y").sum())])
    summ.append(["미사용 재고금액 합계(USD, 단가표 매칭분)", float(dead["재고금액USD"].sum())])
    summ.append(["소모 집계 제외 품목(비부품)", ", ".join(excl)])
    summ.append(["정의", "자주 소모=9개월 중 6개월+ 소모 / 보통=3~5 / 간헐=1~2 / 미사용=소모0+현재고>0 / 핵심=자주 소모 중 소모량 누적80%"])
    summ.append(["주의", "구간 수치는 잠정 기준. 단가표(ITEM_COST_LOOKUP)에 없는 품목은 금액이 비어 있음."])

    with pd.ExcelWriter(OUT, engine="openpyxl") as xw:
        pd.DataFrame(summ, columns=["항목", "값"]).to_excel(xw, sheet_name="요약", index=False)
        items.to_excel(xw, sheet_name="품목통계(전체)", index=False)
        fast.to_excel(xw, sheet_name="자주소모", index=False)
        dead.to_excel(xw, sheet_name="미사용(장기보유)", index=False)
        fi.to_excel(xw, sheet_name="FSE별×품목", index=False)
        val.to_excel(xw, sheet_name="검증(seed대조)", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                w = max(len(str(c.value)) if c.value is not None else 0 for c in list(col)[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(8, w + 2), 40)
    print("저장:", OUT)
    print(pd.DataFrame(summ).to_string(index=False, header=False))
    print(val.to_string(index=False))


if __name__ == "__main__":
    main()
