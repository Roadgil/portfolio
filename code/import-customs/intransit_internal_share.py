# -*- coding: utf-8 -*-
"""
[메일 전용] Intransit 내부공유 메일 발송
- 2026-08-21부터 자동 발송(mail.Send()) — 예전엔 임시보관함에 초안만 저장했음
- 상태파일 기반 중복 발송 방지
- 업데이트(updater.main())는 호출하지 않음
- Urgent Item 시트와 대조하여 요청 품목이 실렸으면 메일 하단(표 아래)에 안내
- 조건:
    1) Urgent P/N == 메일 대상 Item Code
    2) Ship Date > Request Date 인 요청만 인정
    3) 같은 P/N 요청이 여러 개면 Ship Date 이전 요청들 중 가장 최근 Request Date 1건만 선택
    4) 같은 사람 요청건은 사람별로 묶어서 표시
    5) Urgent 매칭이 없으면 Urgent 섹션은 아예 숨김
"""

from __future__ import annotations

import json
import time
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import openpyxl

try:
    import win32com.client as win32  # type: ignore
except Exception:
    win32 = None

import intransit_to_ir_append_only_sorted_paths_set as updater


SHAREPOINT_LINK_BASE = "https://syneron.sharepoint.com/:x:/s/Syneron-CandelaKorea/IQAzAV8trlHcQJsUt0OLVXCyAQqBoReJrj6MhLX2vsRsdzs?e=48Z30w"

TO_RECIPIENTS: List[str] = [
    "ckserviceteam@candelamedical.com",
    "CKSalesTeam@candelamedical.com",
    "CK_clinical@syneron.onmicrosoft.com",
    "hyeinp@candelamedical.com",
    "bohyunk@candelamedical.com",
]

CC_RECIPIENTS: List[str] = [
    "hannap@candelamedical.com",
    "miaej@candelamedical.com",
    "y7221063@yongmalogis.co.kr",
    "y7225055@yongmalogis.co.kr",
]

STATE_PATH = Path(__file__).with_name("intransit_internal_share_state.json")

URGENT_FILE = r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입\IR 신청목록 & Instransit(20260303~).xlsx"
URGENT_SHEET = "Urgent Item"


def _fmt_date(d: Any) -> str:
    if isinstance(d, datetime):
        d = d.date()
    if isinstance(d, date):
        return d.strftime("%Y-%m-%d")
    if d is None:
        return ""
    return str(d)


def _html_escape(s: Any) -> str:
    if s is None:
        return ""
    s = str(s)
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def load_state() -> Dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: Dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_date(v: Any) -> Optional[date]:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v

    if v is None:
        return None

    s = str(v).strip()
    if not s:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d-%b-%Y", "%d-%b-%y", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    return None


def _find_last_row_with_date(ws, col_idx: int, target_date: Optional[date], start_row: int) -> int:
    if target_date is None:
        return start_row - 1
    last = start_row - 1
    for r in range(start_row, ws.max_row + 1):
        v = normalize_date(ws.cell(row=r, column=col_idx).value)
        if v == target_date:
            last = r
    return last


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _norm_pn(v: Any) -> str:
    if v is None:
        return ""
    s = str(v).strip().upper()
    s = s.replace("\t", "").replace(" ", "")
    return s


def _make_row_key(ws, r: int, ship: Optional[date], col_map: Dict[str, int]) -> str:
    parts = [
        ship.strftime("%Y-%m-%d") if ship else "",
        _safe_str(ws.cell(row=r, column=col_map.get("Delivery")).value) if col_map.get("Delivery") else "",
        _safe_str(ws.cell(row=r, column=col_map.get("Transfer order Number")).value) if col_map.get("Transfer order Number") else "",
        _safe_str(ws.cell(row=r, column=col_map.get("Item Code")).value) if col_map.get("Item Code") else "",
        _safe_str(ws.cell(row=r, column=col_map.get("Qty In Transit")).value) if col_map.get("Qty In Transit") else "",
    ]
    return "|".join(parts)


def _gather_new_rows_by_keys(
    ws,
    start_row: int,
    c_hq_ship: int,
    col_map: Dict[str, int],
    last_sent_max_ship: Optional[date],
    sent_keys_for_last_date: set,
) -> List[int]:
    new_rows: List[int] = []
    if last_sent_max_ship is None:
        return new_rows

    for r in range(start_row, ws.max_row + 1):
        ship = normalize_date(ws.cell(row=r, column=c_hq_ship).value)
        if ship is None:
            continue

        if ship > last_sent_max_ship:
            new_rows.append(r)
        elif ship == last_sent_max_ship:
            k = _make_row_key(ws, r, ship, col_map)
            if k and (k not in sent_keys_for_last_date):
                new_rows.append(r)

    return new_rows


def _collect_keys_for_date(ws, start_row: int, c_hq_ship: int, col_map: Dict[str, int], target: date) -> set:
    keys = set()
    for r in range(start_row, ws.max_row + 1):
        ship = normalize_date(ws.cell(row=r, column=c_hq_ship).value)
        if ship != target:
            continue
        k = _make_row_key(ws, r, ship, col_map)
        if k:
            keys.add(k)
    return keys


def _rows_to_dicts(ws, rows: List[int], col_map: Dict[str, int]) -> List[Dict[str, Any]]:
    def val(r: int, key: str) -> Any:
        c = col_map.get(key)
        return ws.cell(row=r, column=c).value if c else ""

    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "From Org": val(r, "From Org"),
            "Ship Date": normalize_date(val(r, "Ship Date")) or val(r, "Ship Date"),
            "Delivery": val(r, "Delivery"),
            "WayBill/Tracking Number": val(r, "WayBill/Tracking Number"),
            "Transfer order Number": val(r, "Transfer order Number"),
            "Item Code": val(r, "Item Code"),
            "Item Description": val(r, "Item Description"),
            "Qty In Transit": val(r, "Qty In Transit"),
        })
    return out


def build_html_table(rows: List[Dict[str, Any]]) -> str:
    cols = [
        "From Org",
        "Ship Date",
        "Delivery",
        "WayBill/Tracking Number",
        "Transfer order Number",
        "Item Code",
        "Item Description",
        "Qty In Transit",
        "본사 선적일자",
        "용마 입고 예정 일자",
    ]

    thead = "".join(
        f"<th style='border:1px solid #ccc;padding:6px;background:#f3f3f3'>{_html_escape(c)}</th>"
        for c in cols
    )

    body_rows = []
    for r in rows:
        ship = r.get("Ship Date")
        ship_d = ship if isinstance(ship, date) else normalize_date(ship)
        yongma = ""
        if isinstance(ship_d, date):
            try:
                yongma = (ship_d + timedelta(days=10)).strftime("%Y-%m-%d")
            except Exception:
                yongma = ""

        vals = {
            **r,
            "본사 선적일자": _fmt_date(ship_d),
            "용마 입고 예정 일자": yongma,
            "Ship Date": _fmt_date(ship_d) if isinstance(ship_d, date) else _html_escape(ship),
        }

        tds = "".join(
            f"<td style='border:1px solid #ccc;padding:6px;white-space:nowrap'>{_html_escape(vals.get(c, ''))}</td>"
            for c in cols
        )
        body_rows.append(f"<tr>{tds}</tr>")

    tbody = "\n".join(body_rows)
    return f"""
    <table style="border-collapse:collapse;font-family:'맑은 고딕', Malgun Gothic, sans-serif;font-size:10.5pt;">
      <thead><tr>{thead}</tr></thead>
      <tbody>{tbody}</tbody>
    </table>
    """


def load_urgent_requests() -> List[Dict[str, Any]]:
    path = Path(URGENT_FILE)
    if not path.exists():
        updater.log(f"[WARN] Urgent 파일 없음: {URGENT_FILE}")
        return []

    wb = openpyxl.load_workbook(path, data_only=True)
    if URGENT_SHEET not in wb.sheetnames:
        updater.log(f"[WARN] Urgent 시트 없음: {URGENT_SHEET}")
        return []

    ws = wb[URGENT_SHEET]

    hdr: Dict[str, int] = {}
    for c in range(1, ws.max_column + 1):
        v = ws.cell(row=1, column=c).value
        if v is not None:
            hdr[str(v).strip()] = c

    need = ["P/N", "Description", "수량", "요청자", "Request Date"]
    missing = [x for x in need if x not in hdr]
    if missing:
        updater.log(f"[WARN] Urgent 시트 필수 컬럼 없음: {missing}")
        return []

    out: List[Dict[str, Any]] = []
    for r in range(2, ws.max_row + 1):
        # 💡 [추가된 로직] '용마입고여부' 컬럼이 존재할 경우 '입고됨'인지 체크해서 건너뜀
        if "용마입고여부" in hdr:
            status = ws.cell(r, hdr["용마입고여부"]).value
            # 공백을 제거한 텍스트가 '입고됨'인지 확인 (예: ' 입고됨 ' 등 오타 방지)
            if _safe_str(status).replace(" ", "") == "입고됨":
                continue

        pn = ws.cell(r, hdr["P/N"]).value
        desc = ws.cell(r, hdr["Description"]).value
        qty = ws.cell(r, hdr["수량"]).value
        requester = ws.cell(r, hdr["요청자"]).value
        req_date = ws.cell(r, hdr["Request Date"]).value

        pn_norm = _norm_pn(pn)
        if not pn_norm:
            continue

        req_date_norm = normalize_date(req_date)
        if req_date_norm is None:
            continue

        requester_txt = _safe_str(requester)
        if not requester_txt:
            continue

        out.append({
            "P/N": _safe_str(pn),
            "P/N_norm": pn_norm,
            "Description": _safe_str(desc),
            "수량": _safe_str(qty),
            "요청자": requester_txt,
            "Request Date": req_date_norm,
        })

    return out


def build_urgent_notice_html(rows: List[Dict[str, Any]], urgent_reqs: List[Dict[str, Any]]) -> str:
    """
    - Item Code == Urgent P/N
    - Ship Date > Request Date
    - 같은 P/N 요청이 여러 개면 Ship Date 이전 요청들 중 가장 최근 Request Date 1건만 선택
    - 같은 사람 요청건은 사람별로 묶어서 표시
    - 매칭 없으면 빈 문자열 반환
    """
    if not rows or not urgent_reqs:
        return ""

    urgent_map: Dict[str, List[Dict[str, Any]]] = {}
    for u in urgent_reqs:
        urgent_map.setdefault(u["P/N_norm"], []).append(u)

    grouped: Dict[str, List[Dict[str, str]]] = {}
    seen_item = set()

    for row in rows:
        item_code = _norm_pn(row.get("Item Code"))
        if not item_code:
            continue

        ship_date = row.get("Ship Date")
        if isinstance(ship_date, datetime):
            ship_date = ship_date.date()
        elif not isinstance(ship_date, date):
            ship_date = normalize_date(ship_date)

        if ship_date is None:
            continue

        matched = urgent_map.get(item_code, [])
        if not matched:
            continue

        valid_requests: List[Dict[str, Any]] = []
        for u in matched:
            req_date = u.get("Request Date")
            if isinstance(req_date, datetime):
                req_date = req_date.date()
            elif not isinstance(req_date, date):
                req_date = normalize_date(req_date)

            if req_date is not None and req_date < ship_date:
                valid_requests.append(u)

        if not valid_requests:
            continue

        valid_requests.sort(
            key=lambda x: x.get("Request Date") or date.min,
            reverse=True
        )
        selected = valid_requests[0]

        requester = _safe_str(selected.get("요청자"))
        if not requester:
            continue

        shipped_pn = _safe_str(row.get("Item Code"))
        shipped_desc = _safe_str(row.get("Item Description")) or _safe_str(selected.get("Description"))
        shipped_qty = _safe_str(row.get("Qty In Transit")) or _safe_str(selected.get("수량"))
        req_date_txt = _fmt_date(selected.get("Request Date"))

        item_key = (requester, shipped_pn, shipped_desc, shipped_qty, req_date_txt)
        if item_key in seen_item:
            continue
        seen_item.add(item_key)

        grouped.setdefault(requester, []).append({
            "pn": shipped_pn,
            "desc": shipped_desc,
            "qty": shipped_qty,
            "req_date": req_date_txt,
        })

    if not grouped:
        return ""

    blocks: List[str] = []

    for requester in sorted(grouped.keys()):
        items = grouped[requester]
        items.sort(key=lambda x: (x["pn"], x["desc"], x["qty"]))

        item_lines = []
        for it in items:
            item_lines.append(
                f"<div style='margin-left:16px; margin-bottom:2px;'>"
                f"- {_html_escape(it['pn'])} / "
                f"{_html_escape(it['desc'])} / "
                f"{_html_escape(it['qty'])} "
                f"(Request Date: {_html_escape(it['req_date'])})"
                f"</div>"
            )

        block = (
            f"<div style='margin:6px 0;'>"
            f"<div><b>@{_html_escape(requester)}</b></div>"
            f"{''.join(item_lines)}"
            f"</div>"
        )
        blocks.append(block)

    return (
        "<div style='font-family:'맑은 고딕', Malgun Gothic, sans-serif;font-size:10.5pt; margin-top:14px;'>"
        "<p><b>Urgent 요청 품목 입고 예정</b></p>"
        + "".join(blocks)
        + "</div>"
    )


def main():
    updater.log("Internal Share(메일 전용) 시작")

    wb_t = openpyxl.load_workbook(updater.TARGET_FILE, data_only=True)
    if updater.TARGET_SHEET not in wb_t.sheetnames:
        raise ValueError(f"대상 시트 '{updater.TARGET_SHEET}'를 찾을 수 없습니다. 시트들: {wb_t.sheetnames}")
    ws_t = wb_t[updater.TARGET_SHEET]

    header_row_t = updater.find_header_row(ws_t, keyword="본사 선적일자", max_scan_rows=80)
    if header_row_t == 1:
        header_row_t = updater.find_header_row(ws_t, keyword="Ship Date", max_scan_rows=80)

    hdr_t = updater.build_col_map_norm(ws_t, header_row_t)

    c_hq_ship = updater.get_col_norm(hdr_t, "본사 선적일자", "본사선적일자", "본사 선적\n일자")
    if c_hq_ship is None:
        raise ValueError("타겟 시트에서 '본사 선적일자' 컬럼을 찾지 못했습니다.")

    col_map = {
        "From Org": updater.get_col_norm(hdr_t, "From Org", "From"),
        "Ship Date": updater.get_col_norm(hdr_t, "Ship Date", "Shipment Date"),
        "Delivery": updater.get_col_norm(hdr_t, "Delivery", "Delivery Number", "Delivery No"),
        "WayBill/Tracking Number": updater.get_col_norm(hdr_t, "WayBill/Tracking Number", "WayBill", "Tracking Number"),
        "Transfer order Number": updater.get_col_norm(hdr_t, "Transfer order Number", "Transfer Order Number", "TO Number"),
        "Item Code": updater.get_col_norm(hdr_t, "Item Code", "Item", "Item Number"),
        "Item Description": updater.get_col_norm(hdr_t, "Item Description", "Description"),
        "Qty In Transit": updater.get_col_norm(hdr_t, "Qty In Transit", "Qty"),
    }
    col_map = {k: v for k, v in col_map.items() if v is not None}

    start_row = header_row_t + 1

    state = load_state()
    last_sent_max_ship = state.get("last_sent_max_ship")
    last_sent_last_row = int(state.get("last_sent_last_row", 0))

    sent_keys = set(state.get("sent_keys", []) or [])
    sent_keys_date = state.get("sent_keys_date")
    sent_keys_for_last_date = set()

    if isinstance(last_sent_max_ship, str) and last_sent_max_ship:
        try:
            last_sent_max_ship = datetime.strptime(last_sent_max_ship, "%Y-%m-%d").date()
        except Exception:
            last_sent_max_ship = None
    elif not isinstance(last_sent_max_ship, date):
        last_sent_max_ship = None

    if isinstance(sent_keys_date, str) and sent_keys_date and isinstance(last_sent_max_ship, date):
        if sent_keys_date == last_sent_max_ship.strftime("%Y-%m-%d"):
            sent_keys_for_last_date = set(sent_keys)

    if (not sent_keys_for_last_date) and isinstance(last_sent_max_ship, date) and last_sent_last_row > 0:
        upper = min(last_sent_last_row, ws_t.max_row)
        for r in range(start_row, upper + 1):
            ship = normalize_date(ws_t.cell(row=r, column=c_hq_ship).value)
            if ship == last_sent_max_ship:
                k = _make_row_key(ws_t, r, ship, col_map)
                if k:
                    sent_keys_for_last_date.add(k)

    max_ship = None
    try:
        max_ship = updater.get_max_existing_shipdate(ws_t, c_hq_ship, start_row=start_row)  # type: ignore
    except TypeError:
        try:
            max_ship = updater.get_max_existing_shipdate(ws_t, c_hq_ship)  # type: ignore
        except Exception:
            max_ship = None

    max_ship = normalize_date(max_ship)
    current_last_row_of_max = _find_last_row_with_date(ws_t, c_hq_ship, max_ship, start_row=start_row)

    new_row_indices = _gather_new_rows_by_keys(
        ws_t,
        start_row,
        c_hq_ship,
        col_map,
        last_sent_max_ship,
        sent_keys_for_last_date,
    )

    if last_sent_max_ship is None:
        if max_ship is not None:
            new_row_indices = []
            for r in range(start_row, ws_t.max_row + 1):
                ship = normalize_date(ws_t.cell(row=r, column=c_hq_ship).value)
                if ship == max_ship:
                    new_row_indices.append(r)
        else:
            new_row_indices = []

    if not new_row_indices:
        updater.log("Internal Share: 신규 없음 → 메일 발송 생략")
        if last_sent_max_ship is None and max_ship is not None and current_last_row_of_max >= start_row:
            save_state({
                "last_sent_max_ship": max_ship.strftime("%Y-%m-%d"),
                "last_sent_last_row": current_last_row_of_max,
                "sent_keys_date": max_ship.strftime("%Y-%m-%d"),
                "sent_keys": sorted(list(_collect_keys_for_date(ws_t, start_row, c_hq_ship, col_map, max_ship))) if max_ship else [],
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            })
        return

    rows_dicts = _rows_to_dicts(ws_t, new_row_indices, col_map)

    # 통합 시트(intransit_to_ir_append_only_...)가 거친 키로 append하다 보니
    # 같은 배송건이 물리적으로 두 줄 중복 저장되는 경우가 있다. 메일 표에 넣기
    # 직전, 같은 배송건(선적일+Delivery+TO+품목코드+수량)이면 한 줄만 남긴다.
    _seen_row_keys = set()
    _deduped_rows = []
    for _d in rows_dicts:
        _ship = _d.get("Ship Date")
        if isinstance(_ship, datetime):
            _ship = _ship.date()
        elif not isinstance(_ship, date):
            _ship = normalize_date(_ship)
        _key = (
            _ship.strftime("%Y-%m-%d") if isinstance(_ship, date) else "",
            _safe_str(_d.get("Delivery")),
            _safe_str(_d.get("Transfer order Number")),
            _safe_str(_d.get("Item Code")),
            _safe_str(_d.get("Qty In Transit")),
        )
        if _key in _seen_row_keys:
            continue
        _seen_row_keys.add(_key)
        _deduped_rows.append(_d)
    rows_dicts = _deduped_rows

    def _sort_key(d):
        sd = d.get("Ship Date")
        if isinstance(sd, datetime):
            sd = sd.date()
        elif not isinstance(sd, date):
            sd = normalize_date(sd)
        return (sd or date.min, str(d.get("Delivery") or ""), str(d.get("Item Code") or ""))

    rows_dicts.sort(key=_sort_key, reverse=True)

    urgent_reqs = load_urgent_requests()
    urgent_html = build_urgent_notice_html(rows_dicts, urgent_reqs)

    today = datetime.now().strftime("%Y%m%d")
    subject = f"Candela Intransit Details Report_{today}"

    if win32 is None:
        raise RuntimeError("pywin32(win32com)이 설치되어 있지 않습니다. `pip install pywin32` 후 재실행하세요.")

    outlook = win32.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.Subject = subject
    mail.To = "; ".join(TO_RECIPIENTS)
    if CC_RECIPIENTS:
        mail.CC = "; ".join(CC_RECIPIENTS)

    # 마지막 데이터 행으로 이동하는 동적 SharePoint 링크 생성
    last_data_row = current_last_row_of_max if current_last_row_of_max >= start_row else start_row
    sharepoint_link = f"{SHAREPOINT_LINK_BASE}&activeCell='Intransit'!A{last_data_row}"

    # ✅ 파일링크 -> 전체 선적 일정 표 -> Urgent 섹션(있을 때만)
    mail_body = f"""
    <div style='font-family:'맑은 고딕', Malgun Gothic, sans-serif;font-size:10.5pt;'>
      <p>안녕하세요 Operation 채윤길입니다.</p>
      <p>금일 선적 일정 공유 드립니다.</p>
      <p><b>파일링크:</b> <a href='{sharepoint_link}'>{_html_escape(updater.TARGET_FILE)}</a></p>
      <p><b>전체 선적 일정</b></p>
    </div>
    """

    mail_body += build_html_table(rows_dicts)

    if urgent_html.strip():
        mail_body += urgent_html

    mail_body += "<p>감사합니다.<br>채윤길 드림</p>"

    mail.HTMLBody = mail_body

    # 2026-08-21 사용자 요청: 초안 저장이 아니라 바로 발송한다.
    # Send() 이후에는 항목이 보낸편지함으로 옮겨져 mail COM 참조가 무효화될 수
    # 있으므로, 아래 상태 저장에서는 mail 객체를 건드리지 않는다(subject 변수만 사용).
    mail.Send()
    updater.log(f"Internal Share: 자동 발송 완료 ({subject})")

    if max_ship is not None:
        save_state({
            "last_sent_max_ship": max_ship.strftime("%Y-%m-%d"),
            "last_sent_last_row": current_last_row_of_max,
            "sent_keys_date": max_ship.strftime("%Y-%m-%d"),
            "sent_keys": sorted(list(_collect_keys_for_date(ws_t, start_row, c_hq_ship, col_map, max_ship))) if max_ship else [],
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        })


if __name__ == "__main__":
    # 2026-09-08: 통합파일이 그 순간 열려있으면 PermissionError로 메일 발송
    # 단계 전체가 스킵되던 문제 재발 방지용 재시도. main()의 가장 첫 동작이
    # 파일 로드(openpyxl.load_workbook)라서, 여기서 실패하면 메일 발송 전이므로
    # 통째로 재시도해도 중복발송 위험이 없다.
    MAX_RETRIES = 5
    RETRY_WAIT_SEC = 60
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            main()
            break
        except PermissionError:
            if attempt < MAX_RETRIES:
                updater.log(f"파일이 열려 있어 접근 실패 ({attempt}/{MAX_RETRIES}). {RETRY_WAIT_SEC}초 후 재시도.")
                time.sleep(RETRY_WAIT_SEC)
            else:
                updater.log("FAILED: 파일이 열려 있음(재시도 소진). 닫고 다시 실행하세요.")
                raise