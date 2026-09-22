# -*- coding: utf-8 -*-
"""파트오더 만들기 전에 Finance의 입금내역에서 해당 입금이 들어왔는지 확인한다.

대상은 **혜준대리님 메일의 결제수단이 '계좌이체'인 건**뿐이다. 카드/톡결제는
입금내역 시트에 개별 건으로 안 잡히므로(KG이니시스 등으로 합산되어 들어옴)
확인 대상이 아니다.

  파일: Finance\\AR\\★입금 내역 Mapping.xlsx  시트 '입금내역' (4행이 헤더)
  쓰는 열: 입금일시 / 적요(Remitter) / 입금(원) Amount

매칭 기준
  1) 금액이 정확히 일치      <- 제일 확실한 키
  2) 입금일이 결제일 앞뒤로 며칠 안
  3) 적요에 병원명 조각이 들어있으면 확신 (예: '베일러의원강지민', '김성원(원스의원)')
     적요가 사람이름/영문일 때가 흔해서(예: 'CHOUHOYE') 이건 가점이지 필수는 아니다.

읽기 전용이다. 이 파일을 쓰지 않는다.

  python deposit_check.py 1650000 베일러의원 2026-09-01
"""
import os
import re
import sys
from datetime import date, datetime, timedelta

import paths

DEPOSIT_XLSX = os.path.join(
    paths.ONEDRIVE or "", "Syneron-Candela Korea - Finance", "AR",
    "★입금 내역 Mapping.xlsx")
SHEET = "입금내역"
HEADER_ROW = 4
COL_DATE, COL_REMITTER, COL_AMOUNT = 1, 4, 10     # 0-based

_cache = {"mtime": None, "rows": None}
_DATE_RE = re.compile(r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})")
# 병원명에서 떼어낼 흔한 꼬리말 - '밴스의원 구월' -> '밴스', '구월'
_DROP = ("의원", "병원", "피부과", "클리닉", "점", "(주)", "주식회사")


def _parse_date(v):
    if isinstance(v, datetime):
        return v.date()
    m = _DATE_RE.search(str(v or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def load_deposits(force=False):
    """[{date, remitter, amount, row}] - 파일이 안 바뀌었으면 캐시를 쓴다."""
    if not os.path.exists(DEPOSIT_XLSX):
        raise FileNotFoundError(f"입금내역 파일을 찾을 수 없습니다: {DEPOSIT_XLSX}")
    mt = os.path.getmtime(DEPOSIT_XLSX)
    if not force and _cache["mtime"] == mt and _cache["rows"] is not None:
        return _cache["rows"]

    import openpyxl
    wb = openpyxl.load_workbook(DEPOSIT_XLSX, read_only=True, data_only=True)
    try:
        ws = wb[SHEET]
        out = []
        for i, r in enumerate(ws.iter_rows(min_row=HEADER_ROW + 1,
                                           max_col=COL_AMOUNT + 1,
                                           values_only=True), HEADER_ROW + 1):
            amt = r[COL_AMOUNT]
            if r[COL_DATE] is None or not isinstance(amt, (int, float)):
                continue
            d = _parse_date(r[COL_DATE])
            if d is None:
                continue
            out.append({"date": d, "remitter": str(r[COL_REMITTER] or "").strip(),
                        "amount": int(round(amt)), "row": i})
    finally:
        wb.close()
    _cache.update(mtime=mt, rows=out)
    return out


def _tokens(hospital):
    """'밴스의원 구월' -> ['밴스', '구월'] (2글자 이상만)."""
    s = str(hospital or "")
    for d in _DROP:
        s = s.replace(d, " ")
    return [t for t in re.split(r"[\s,()]+", s) if len(t) >= 2]


def _name_hit(remitter, hospital):
    """적요에 병원 '브랜드명'이 들어있나. 공백을 지우고 본다.

    지점명만 맞는 건 인정하지 않는다. '오블리브의원 서울 오리진'이 적요
    '서울라온의원이'와 '서울' 하나로 매칭돼 엉뚱한 입금을 잡았다(2026-09-02).
    첫 토큰(브랜드명)이 맞거나, 3글자 이상 토큰이 맞아야 한다.
    """
    rem = re.sub(r"\s+", "", remitter)
    toks = _tokens(hospital)
    if not toks:
        return False
    if toks[0] in rem:
        return True
    return any(len(t) >= 3 and t in rem for t in toks[1:])


def find_deposit(amount, hospital=None, pay_date=None, back_days=5, fwd_days=3):
    """입금 확인 결과를 돌려준다.

    status: found       금액·날짜 일치 + 적요에 병원명 (확실)
            amount_only 금액·날짜는 맞는데 적요가 병원명과 무관 (사람이름 입금 등)
            not_found   해당 금액 입금이 없음
    """
    if not amount:
        return {"status": "not_found", "reason": "메일에서 입금액을 못 읽음",
                "matches": []}
    rows = load_deposits()
    amount = int(round(amount))
    if isinstance(pay_date, str):
        pay_date = _parse_date(pay_date)
    lo = (pay_date - timedelta(days=back_days)) if pay_date else None
    hi = (pay_date + timedelta(days=fwd_days)) if pay_date else None

    hits = [r for r in rows if r["amount"] == amount
            and (lo is None or r["date"] >= lo)
            and (hi is None or r["date"] <= hi)]
    if not hits:
        # 날짜를 무시하면 있는지도 알려준다(입금일이 어긋난 경우 판단용)
        any_amt = [r for r in rows if r["amount"] == amount]
        return {"status": "not_found", "matches": [],
                "reason": (f"같은 금액 입금이 날짜 밖에 {len(any_amt)}건 있음"
                           if any_amt else "같은 금액 입금 없음"),
                "other_dates": [str(r["date"]) for r in any_amt[-3:]]}

    named = [r for r in hits if hospital and _name_hit(r["remitter"], hospital)]
    if named:
        return {"status": "found", "matches": named}
    return {"status": "amount_only", "matches": hits,
            "reason": "금액·날짜는 맞는데 입금자명이 병원명과 안 맞음"}


def check_mail(parsed, hospital=None):
    """파싱된 메일 하나에 대한 입금 확인. 계좌이체가 아니면 확인하지 않는다."""
    method = (parsed.get("payment_method") or "").strip()
    hosp = hospital or parsed.get("hospital_name")
    if "계좌이체" not in method:
        return {"status": "skip", "method": method or "(없음)",
                "reason": "계좌이체가 아니라 확인 대상 아님", "matches": []}
    r = find_deposit(parsed.get("amount"), hosp, parsed.get("payment_date"))
    r["method"] = method
    return r


LABEL = {"found": "입금확인", "amount_only": "입금확인(이름불일치)",
         "not_found": "입금없음", "skip": "해당없음", "error": "확인실패"}


if __name__ == "__main__":
    amt = int(sys.argv[1]) if len(sys.argv) > 1 else 1650000
    hosp = sys.argv[2] if len(sys.argv) > 2 else None
    d = sys.argv[3] if len(sys.argv) > 3 else None
    print("파일:", DEPOSIT_XLSX)
    rows = load_deposits()
    print(f"입금내역 {len(rows)}건 (최근 {rows[-1]['date']})")
    r = find_deposit(amt, hosp, d)
    print(f"\n결과: {LABEL.get(r['status'])}  {r.get('reason','')}")
    for m in r["matches"][:5]:
        print(f"   {m['date']}  {m['remitter'][:28]:<30} {m['amount']:>12,}  (행{m['row']})")
    if r.get("other_dates"):
        print("   날짜 밖 같은 금액:", r["other_dates"])
