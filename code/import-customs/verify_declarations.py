# -*- coding: utf-8 -*-
"""
수입신고필증(PDF) ↔ 수입신고실적 엑셀 금액 대조 검증
==============================================================
[왜 필요한가 / 2026-08-20]
신고번호 4482026721281M 에서 8050-00-9004 렌즈 4 EA(143,364원) 가 실적파일에
누락된 사고가 있었다. 원인은 auto_import_complete.py 의 중복키에 수량이 없어서,
Lot/Serial 없는 부품이 같은 TO Line 에서 두 줄로 쪼개져 올 때(1 EA + 4 EA)
뒷줄이 조용히 버려진 것. 그 원인은 auto_import_complete.py 에서 고쳤지만,
'조용히 틀려도 아무도 모른다'는 구조 자체가 진짜 문제였다.

이 스크립트는 원인과 무관하게 '결과'를 검증한다.
필증은 관세청이 발행한 확정 증빙이므로, 필증 금액과 실적파일 합계가 맞으면 맞는 것이고
어긋나면 원인이 append 유실이든 중복이든 신고번호 오기입이든 수동 편집 실수든 걸린다.

[대조 기준]
필증 54번 '결제금액'(예: DAP-KRW-234,506,815-TT) vs 실적파일의 해당 신고번호 금액 합계.
  - 라벨 형식이 고정돼 있어 파싱이 매우 안정적이다.
  - 실측(필증 170건): 47건 정확히 0원, 115건 1~10원, 5건 11~100원 차이.
    이 오차는 필증이 란별 과세가격을 안분·반올림하기 때문이며 정상이다.
  - 품목 단위 파싱은 필증 레이아웃이 여러 가지여서 오탐이 많아 '경고 판정'에는 쓰지 않고,
    이미 금액이 어긋난 건의 원인 파악을 돕는 참고 정보로만 출력한다.

- 읽기 전용. 어떤 파일도 수정하지 않는다.
- 파싱 결과는 캐시(json)에 저장 → 매 실행 시 새/변경된 PDF만 파싱한다.
- 불일치는 [ALERT] 로 출력. group_b.py 가 stdout 을 run_log.txt 에 남기므로 로그만 봐도 발견된다.
==============================================================
"""
import os
import re
import json
import glob
from collections import defaultdict

import pdfplumber
import openpyxl

BASE       = r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입"
PDF_DIR    = os.path.join(BASE, "수입신고필증_자동화")
EXCEL_FILE = os.path.join(BASE, "수입신고실적(20260211)자동화.xlsx")
SHEET_NAME = "수입신고실적(20260211)"
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_pdf_cache.json")
# 캐시에 담는 항목이 바뀌면 이 값을 올린다 → 옛 캐시가 자동 무효화되어 재파싱된다.
# (v1: 품목만 저장 / v2: 결제금액 추가)
CACHE_VERSION = 2

# 필증의 란별 안분 반올림 오차 허용치(원). 실측 최대 100원이라 500원이면 충분히 여유가 있고,
# 가장 싼 품목(수만 원대)이 빠져도 잡힌다.
AMOUNT_TOLERANCE = 500

# 54번 결제금액: "<인도조건>-<통화>-<금액>-<결제방법>" 형태
PAY_RE  = re.compile(r'-KRW-([\d,]+)-')
ITEM_RE  = re.compile(r'^([0-9A-Z][0-9A-Z\-]{5,})=.*?\s(\d[\d,]*)\s+(EA|SET|PCS|KG|U)\s+([\d,]+)\s+([\d,]+)\s*$')
ITEM_RE2 = re.compile(r'^(\d[\d,]*)\s+(EA|SET|PCS|KG|U)\s+([\d,]+)\s+([\d,]+)\s*$')
CODE_RE  = re.compile(r'^([0-9A-Z][0-9A-Z\-]{5,})=')


def log(msg):
    print(msg, flush=True)


def _fix(s):
    """pdfplumber 가 필증 PDF의 cp949 텍스트를 latin-1 로 잘못 디코드해 오는 것을 되돌린다."""
    try:
        return s.encode('latin-1', 'ignore').decode('cp949', 'ignore')
    except Exception:
        return s


def parse_pdf(path):
    """필증에서 (결제금액, {자재코드: [수량합, 금액합]}) 을 뽑는다.
    결제금액은 1페이지 헤더에만 있으므로 1페이지에서 찾는다."""
    pay = None
    agg = defaultdict(lambda: [0, 0])
    pend = None
    with pdfplumber.open(path) as pdf:
        for pi, pg in enumerate(pdf.pages):
            txt = _fix(pg.extract_text() or "")
            if pay is None:
                m = PAY_RE.search(txt)
                if m:
                    pay = int(m.group(1).replace(',', ''))
            for ln in txt.split("\n"):
                s = ln.strip()
                m1 = ITEM_RE.match(s)
                if m1:
                    code = m1.group(1)
                    agg[code][0] += int(m1.group(2).replace(',', ''))
                    agg[code][1] += int(m1.group(5).replace(',', ''))
                    pend = None
                    continue
                m2 = ITEM_RE2.match(s)
                if m2:
                    pend = (int(m2.group(1).replace(',', '')), int(m2.group(4).replace(',', '')))
                    continue
                if pend:
                    mc = CODE_RE.match(s)
                    if mc:
                        agg[mc.group(1)][0] += pend[0]
                        agg[mc.group(1)][1] += pend[1]
                        pend = None
    return pay, {k: v for k, v in agg.items()}


def load_cache():
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(cache):
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False)
    os.replace(tmp, CACHE_FILE)   # 원자적 교체 (중간에 죽어도 캐시가 반쪽 안 됨)


def collect_pdfs():
    """신고번호 → 가장 최신 PDF 경로 (정정 필증이 여러 개면 mtime 최신 것)"""
    latest = {}
    for p in glob.glob(os.path.join(PDF_DIR, "_IMP_*.pdf")):
        m = re.search(r'_IMP_(\d{13,14}[A-Z])', os.path.basename(p))
        if not m:
            continue
        decl = m.group(1)
        try:
            mt = os.path.getmtime(p)
        except OSError:
            continue
        if decl not in latest or mt > latest[decl][1]:
            latest[decl] = (p, mt)
    return {d: v[0] for d, v in latest.items()}


def _num(v):
    """실적파일의 수량/금액은 숫자와 '1,234' 같은 문자열이 섞여 있어 강제 변환한다."""
    if v is None or v == '':
        return 0
    if isinstance(v, (int, float)):
        return v
    t = str(v).replace(',', '').replace('₩', '').strip()
    try:
        return float(t) if '.' in t else int(t)
    except ValueError:
        return 0


def read_excel():
    """신고번호 → (금액합, 행수, {자재코드: [수량합, 금액합]})"""
    wb = openpyxl.load_workbook(EXCEL_FILE, read_only=True, data_only=True)
    ws = wb[SHEET_NAME]
    it = ws.iter_rows(values_only=True)
    hdr = [str(h).strip() if h is not None else '' for h in next(it)]
    ix = {n: hdr.index(n) for n in ('신고번호', '자재코드', '수량', '금액') if n in hdr}
    tot = defaultdict(int)
    cnt = defaultdict(int)
    items = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for r in it:
        decl = str(r[ix['신고번호']]).strip() if r[ix['신고번호']] else ''
        if not decl:
            continue
        amt = _num(r[ix['금액']])
        tot[decl] += amt
        cnt[decl] += 1
        code = str(r[ix['자재코드']]).strip() if r[ix['자재코드']] else ''
        if code:
            items[decl][code][0] += _num(r[ix['수량']])
            items[decl][code][1] += amt
    wb.close()
    return tot, cnt, items


def main():
    log("=== 필증 ↔ 실적파일 금액 대조 검증 시작 ===")
    if not os.path.isdir(PDF_DIR):
        log(f"[ABORT] 필증 폴더 없음: {PDF_DIR}")
        return 0

    pdfs = collect_pdfs()
    cache = load_cache()
    parsed = {}          # decl -> (pay, items)
    newly = 0
    for decl, path in pdfs.items():
        try:
            st = os.stat(path)
            sig = f"v{CACHE_VERSION}|{os.path.basename(path)}|{int(st.st_mtime)}|{st.st_size}"
        except OSError:
            continue
        ent = cache.get(decl)
        if ent and ent.get("sig") == sig:
            parsed[decl] = (ent.get("pay"), {k: v for k, v in ent.get("items", {}).items()})
            continue
        try:
            pay, items = parse_pdf(path)
        except Exception as e:
            log(f"[WARN] 필증 파싱 실패 → 검증 제외: {os.path.basename(path)} ({type(e).__name__}: {e})")
            continue
        parsed[decl] = (pay, items)
        cache[decl] = {"sig": sig, "pay": pay, "items": {k: list(v) for k, v in items.items()}}
        newly += 1
    save_cache(cache)
    log(f"필증 {len(pdfs)}건 (신규 파싱 {newly}건, 캐시 재사용 {len(parsed) - newly}건)")

    xtot, xcnt, xitems = read_excel()
    log(f"실적파일 신고번호 {len(xtot)}건")

    checked = 0
    nopay = []
    alerts = []
    for decl in sorted(parsed):
        pay, pitems = parsed[decl]
        if decl not in xtot:
            continue                     # 아직 실적파일에 안 들어온 건은 판정 보류
        if not pay:
            nopay.append(decl)           # 결제금액을 못 읽은 필증 (판정 제외)
            continue
        checked += 1
        xs = xtot[decl]
        if abs(xs - pay) > AMOUNT_TOLERANCE:
            alerts.append((decl, pay, xs, xcnt[decl], pitems, xitems.get(decl, {})))

    log("")
    if nopay:
        log(f"[WARN] 결제금액을 못 읽어 판정 제외한 필증 {len(nopay)}건: {', '.join(sorted(nopay)[:10])}"
            + (" ..." if len(nopay) > 10 else ""))

    if not alerts:
        log(f"[OK] 대조 {checked}건 전부 일치 (허용오차 {AMOUNT_TOLERANCE:,}원 이내)")
    else:
        log(f"[ALERT] 대조 {checked}건 중 {len(alerts)}건 금액 불일치 — 확인 필요")
        for decl, pay, xs, nrow, pitems, xi in alerts:
            log(f"  ── 신고번호 {decl} | 필증 결제금액 {pay:,} vs 실적 합계 {xs:,} "
                f"(차액 {xs - pay:+,}, 실적 {nrow}행)")
            # 참고용 품목 비교. 필증 레이아웃에 따라 파싱이 어긋날 수 있어 '참고'로만 본다.
            diffs = []
            for code in sorted(set(pitems) | set(xi)):
                pq, pa = (pitems.get(code) or [0, 0])[0], (pitems.get(code) or [0, 0])[1]
                xq, xa = (xi.get(code) or [0, 0])[0], (xi.get(code) or [0, 0])[1]
                if pq != xq or abs(pa - xa) > AMOUNT_TOLERANCE:
                    diffs.append((code, pq, xq, pa, xa))
            if diffs:
                # 전 품목이 같은 비율로 어긋나면 행 누락이 아니라 단가/환율 기준 차이다.
                ratios = [xa / pa for _, pq, xq, pa, xa in diffs if pa and xa and pq == xq]
                if len(ratios) >= 5 and (max(ratios) - min(ratios)) < 0.005:
                    log(f"       → 수량은 전부 일치하고 금액만 일정 비율({sum(ratios)/len(ratios):.4f})로 "
                        f"어긋남. 행 누락이 아니라 단가/환율 기준 차이로 보임.")
                log("       (참고: 품목 단위 비교 — 필증 파싱이 불완전할 수 있어 참고용)")
                for code, pq, xq, pa, xa in diffs[:8]:
                    log(f"         {code:<16} 필증 {pq:>5} / {pa:>13,}   실적 {xq:>5} / {xa:>13,}")
                if len(diffs) > 8:
                    log(f"         ... 외 {len(diffs) - 8}개")
    log("=== 검증 종료 ===")
    return len(alerts)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        log(f"[ERROR] 검증 실패: {type(e).__name__}: {e}")
        traceback.print_exc()
