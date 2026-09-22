# -*- coding: utf-8 -*-
"""파트오더 백업 운영 앱 (보현과장님 휴가 등 백업 기간 전용)

탭 1 [생성]   메일 스캔 -> 선택 -> 값 확인/수정 -> 파트오더 생성
              월마감 모드면 거래명세서/선출고요청서 PDF + 선출고 요청 메일 초안까지
탭 2 [승인후] 승인 끝난 PO -> Trigger Interface To Oracle -> Success 확인
              -> 오라클 Release -> 완료 메일

Send To Approval은 앱이 절대 누르지 않는다. 생성 후 사용자가 화면을 보고 직접 누르고,
차종성 차장님/이광열 이사님 승인 메일이 오면 탭 2에서 나머지를 진행한다.

실행:  python part_order_app.py       (또는 파트오더앱.bat)
"""
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from datetime import date, datetime, timedelta
from tkinter import messagebox, ttk

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

import local_config                                  # noqa: E402
import po_create                                     # noqa: E402
import po_finish                                     # noqa: E402
from map_to_servicemax import map_manual_record      # noqa: E402
from parser import parse_email_body                  # noqa: E402
from scan_new_orders import signature_for            # noqa: E402

STATE_LOG = os.path.join(BASE, "processed_log.json")
RESULT = os.path.join(BASE, "batch_result.json")
DOCS = os.path.join(BASE, "preship_docs")
DEBUG_PORT = 9222
MAX_LINES = 6


# =============================================================== 공통 유틸
def load_json(p, default):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(p, obj):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def sf_page():
    """열려 있는 자동화 브라우저에 붙어 Salesforce 탭을 돌려준다."""
    from playwright.sync_api import sync_playwright
    from sf_actions import get_sf_page
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f"http://localhost:{DEBUG_PORT}")
    return pw, browser, get_sf_page(browser.contexts[0])


def scan_mails(days=3):
    """설정된 폴더에서 최근 N일 출고요청 메일을 읽어온다(읽기 전용)."""
    import win32com.client
    cfg = local_config.load()
    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    inbox = ns.Folders[cfg["outlook_mailbox"]].Folders["받은 편지함"]

    out = []
    for path in cfg["target_folders"]:
        folder = inbox
        for name in path:
            nxt = None
            for f in folder.Folders:
                if f.Name == name:
                    nxt = f
                    break
            folder = nxt
            if folder is None:
                break
        if folder is None:
            continue
        items = folder.Items
        items.Sort("[ReceivedTime]", True)
        cutoff = (datetime.now() - timedelta(days=days - 1)).date()
        for it in items:
            try:
                if it.Class != 43:
                    continue
                rt = it.ReceivedTime
            except Exception:
                continue
            rd = rt.date() if hasattr(rt, "date") else None
            if rd is not None and rd < cutoff:
                break
            try:
                out.append({"topic": it.ConversationTopic, "subject": it.Subject,
                            "received": str(rt)[:16], "entry_id": it.EntryID,
                            "body": it.Body})
            except Exception:
                continue
    out.sort(key=lambda m: m["received"], reverse=True)
    return out


def build_default_lines(parsed):
    """파싱 결과로 품목 줄 기본값을 만든다(사용자가 화면에서 수정 가능)."""
    from map_to_servicemax import load_product_codes, to_line_price
    codes = load_product_codes()
    code = parsed.get("part_number") or codes.get(parsed.get("item_name") or "", "")
    qty = parsed.get("item_qty") or 1
    price = to_line_price(parsed.get("amount"), qty) or 0
    return [{"code": code, "qty": qty, "price": price}]


# =============================================================== 앱
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("파트오더 백업 운영 앱")
        self.geometry("1180x820")
        self.q = queue.Queue()
        self.mails = []
        self.busy = False

        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Button(top, text="브라우저 열기", command=self.open_browser).pack(side="left")
        ttk.Button(top, text="브라우저 상태", command=self.check_browser).pack(side="left", padx=4)
        ttk.Separator(top, orient="vertical").pack(side="left", fill="y", padx=8)
        self.month_end = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="월마감 모드 (선출고 문서+초안까지)",
                        variable=self.month_end).pack(side="left")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=6)
        self.tab_create = ttk.Frame(nb)
        self.tab_finish = ttk.Frame(nb)
        nb.add(self.tab_create, text="1. 파트오더 생성")
        nb.add(self.tab_finish, text="2. 승인 후 (오라클 전송·릴리즈·완료메일)")
        self._build_create(self.tab_create)
        self._build_finish(self.tab_finish)

        self.logbox = tk.Text(self, height=12, wrap="word")
        self.logbox.pack(fill="both", expand=False, padx=6, pady=(0, 6))
        self.after(150, self._drain)

    # ---------------------------------------------------------- 로그/스레드
    def log(self, msg):
        self.q.put(str(msg))

    def _drain(self):
        while True:
            try:
                m = self.q.get_nowait()
            except queue.Empty:
                break
            self.logbox.insert("end", m + "\n")
            self.logbox.see("end")
        self.after(150, self._drain)

    def run_bg(self, fn, done=None):
        if self.busy:
            messagebox.showwarning("실행 중", "이전 작업이 아직 끝나지 않았습니다.")
            return
        self.busy = True

        def wrap():
            try:
                r = fn()
                if done:
                    self.after(0, lambda: done(r))
            except Exception as e:
                import traceback
                self.log("[오류] " + traceback.format_exc())
                self.after(0, lambda: messagebox.showerror("오류", str(e)))
            finally:
                self.busy = False
        threading.Thread(target=wrap, daemon=True).start()

    # ---------------------------------------------------------- 브라우저
    def open_browser(self):
        script = os.path.join(BASE, "_diag_open_browser_alt.py")
        if not os.path.exists(script):
            script = os.path.join(BASE, "open_browser.py")
        subprocess.Popen([sys.executable, script], cwd=BASE,
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        self.log("브라우저 실행 요청 - SSO 로그인까지 20~40초 걸립니다.")

    def check_browser(self):
        def job():
            import run_unattended
            ok = run_unattended.browser_ready()
            self.log(f"브라우저 준비: {ok}")
            return ok
        self.run_bg(job)

    # ---------------------------------------------------------- 탭1: 생성
    def _build_create(self, root):
        left = ttk.Frame(root)
        left.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        bar = ttk.Frame(left)
        bar.pack(fill="x")
        ttk.Label(bar, text="최근").pack(side="left")
        self.days = tk.StringVar(value="3")
        ttk.Entry(bar, textvariable=self.days, width=4).pack(side="left", padx=2)
        ttk.Label(bar, text="일").pack(side="left")
        ttk.Button(bar, text="메일 스캔", command=self.do_scan).pack(side="left", padx=6)

        self.tree = ttk.Treeview(left, columns=("recv", "subj", "state"),
                                 show="headings", height=14)
        for c, t, w in (("recv", "수신", 110), ("subj", "제목", 380), ("state", "상태", 90)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self.on_pick)

        right = ttk.Frame(root, width=460)
        right.pack(side="right", fill="y", padx=4, pady=4)

        f = ttk.LabelFrame(right, text="확인 / 수정", padding=6)
        f.pack(fill="x")
        self.v_hosp = tk.StringVar()
        self.v_loc = tk.StringVar()
        self.v_ship = tk.StringVar(value="택배")
        self.v_label = tk.StringVar()
        for lab, var, w in (("병원(검색어)", self.v_hosp, 34),
                            ("Location 정확명", self.v_loc, 34),
                            ("내역 표기", self.v_label, 34)):
            row = ttk.Frame(f)
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=lab, width=14).pack(side="left")
            ttk.Entry(row, textvariable=var, width=w).pack(side="left")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=1)
        ttk.Label(row, text="배송", width=14).pack(side="left")
        ttk.Combobox(row, textvariable=self.v_ship, values=["택배", "퀵"],
                     width=8, state="readonly").pack(side="left")
        ttk.Button(row, text="Location 후보 조회",
                   command=self.do_loc_check).pack(side="left", padx=6)

        g = ttk.LabelFrame(right, text="품목 (코드 / 수량 / 단가) - 빈 줄은 무시", padding=6)
        g.pack(fill="x", pady=6)
        self.line_vars = []
        for i in range(MAX_LINES):
            r = ttk.Frame(g)
            r.pack(fill="x", pady=1)
            c, qv, pv = tk.StringVar(), tk.StringVar(), tk.StringVar()
            ttk.Entry(r, textvariable=c, width=18).pack(side="left")
            ttk.Entry(r, textvariable=qv, width=6).pack(side="left", padx=2)
            ttk.Entry(r, textvariable=pv, width=14).pack(side="left")
            self.line_vars.append((c, qv, pv))
        self.v_sum = tk.StringVar(value="합계 -")
        ttk.Label(g, textvariable=self.v_sum).pack(anchor="w", pady=(4, 0))
        ttk.Button(g, text="합계 계산", command=self.calc_sum).pack(anchor="w")

        ttk.Button(right, text="▶ 파트오더 생성",
                   command=self.do_create).pack(fill="x", pady=8, ipady=6)
        ttk.Label(right, text="※ Send to Approval은 앱이 누르지 않습니다.\n"
                              "   생성 후 화면 확인하고 직접 눌러주세요.",
                  foreground="#a33").pack(anchor="w")

    def do_scan(self):
        def job():
            self.log("메일 스캔 중...")
            ms = scan_mails(int(self.days.get() or 3))
            log = load_json(STATE_LOG, {})
            for m in ms:
                p = parse_email_body(m["body"])
                m["parsed"] = p
                ok = "error" not in p and not any(
                    u.startswith("필수 필드 누락") for u in p.get("unparsed", []))
                sig = signature_for(p) if ok else m["topic"]
                m["sig"] = sig
                m["done"] = sig in log or m["topic"] in log
            return ms

        def done(ms):
            self.mails = ms
            self.tree.delete(*self.tree.get_children())
            for i, m in enumerate(ms):
                self.tree.insert("", "end", iid=str(i),
                                 values=(m["received"], m["subject"],
                                         "처리됨" if m["done"] else "신규"))
            self.log(f"메일 {len(ms)}건 (신규 {sum(1 for m in ms if not m['done'])}건)")
        self.run_bg(job, done)

    def on_pick(self, _evt=None):
        sel = self.tree.selection()
        if not sel:
            return
        m = self.mails[int(sel[0])]
        p = m["parsed"]
        self.v_hosp.set(p.get("hospital_name") or "")
        self.v_loc.set("")
        self.v_label.set(p.get("item_raw") or "")
        body = m["body"]
        self.v_ship.set("퀵" if "퀵" in body[:600] else "택배")
        for c, q, pr in self.line_vars:
            c.set(""); q.set(""); pr.set("")
        for i, ln in enumerate(build_default_lines(p)):
            if i >= MAX_LINES:
                break
            self.line_vars[i][0].set(ln["code"] or "")
            self.line_vars[i][1].set(str(ln["qty"]))
            self.line_vars[i][2].set(str(ln["price"]))
        self.calc_sum()
        if m["done"]:
            self.log(f"[주의] 이미 처리된 건입니다: {m['subject']}")

    def get_lines(self):
        out = []
        for c, q, p in self.line_vars:
            code = c.get().strip()
            if not code:
                continue
            out.append({"code": code, "qty": int(float(q.get() or 1)),
                        "price": int(float(p.get() or 0))})
        return out

    def calc_sum(self):
        try:
            s = sum(l["qty"] * l["price"] for l in self.get_lines())
            self.v_sum.set(f"합계(공급가) {s:,}  /  부가세포함 {int(s * 1.1):,}")
        except Exception:
            self.v_sum.set("합계 - (숫자 확인)")

    def do_loc_check(self):
        kw = self.v_hosp.get().strip()

        def job():
            pw, br, page = sf_page()
            try:
                names = po_create.search_locations(page, kw)
                self.log(f"Location 후보 ({kw}): {names}")
                return names
            finally:
                pw.stop()

        def done(names):
            if len(names) == 1:
                self.v_loc.set(names[0])
            elif names:
                messagebox.showinfo("Location 후보",
                                    "여러 건입니다. 정확명을 골라 입력하세요:\n\n"
                                    + "\n".join(names))
        self.run_bg(job, done)

    def do_create(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning("선택 필요", "메일을 먼저 고르세요.")
            return
        m = self.mails[int(sel[0])]
        lines = self.get_lines()
        if not lines:
            messagebox.showwarning("품목 없음", "품목을 최소 한 줄 입력하세요.")
            return
        if m["done"] and not messagebox.askyesno(
                "이미 처리됨", "이 건은 이미 처리 이력이 있습니다. 그래도 진행할까요?"):
            return
        if not messagebox.askyesno(
                "확인", f"{self.v_hosp.get()}\n품목 {len(lines)}줄\n"
                        f"{'월마감(문서+초안 포함)' if self.month_end.get() else '평상시'}\n\n"
                        "파트오더를 생성할까요?"):
            return

        hosp = self.v_hosp.get().strip()
        loc = self.v_loc.get().strip() or None
        ship = self.v_ship.get()
        label = self.v_label.get().strip()
        month_end = self.month_end.get()
        today = date.today()

        def job():
            base = map_manual_record(
                hospital_name=hosp, item_label=label,
                item_qty=lines[0]["qty"], unit_price=lines[0]["price"],
                received_date=today,
                part_number=lines[0]["code"],
                order_channel=m["parsed"].get("order_channel") or "Service main 전화")
            po = base["parts_order"]
            txt = f"{today.month}월{today.day}일 접수 {label} {ship}"
            po["packing_instructions"] = txt
            po["message_for_shipper"] = txt

            spec = {"hospital_search_keyword": hosp, "location_exact": loc,
                    "case": base["case"], "parts_order": po, "lines": lines}

            pw, br, page = sf_page()
            try:
                res = po_create.create_case_and_po(page, spec, self.log)
                if res.get("status") != "created":
                    return {"res": res}
                info = po_create.read_po_summary(page, res["parts_order_url"])
                self.log(f"  PO {info.get('parts_order_number')} / "
                         f"Case {info.get('Case')} / {info.get('Total Price')}")
            finally:
                pw.stop()

            self._record(m, hosp, res, info, lines, month_end)

            if month_end:
                self._month_end_docs(m, hosp, lines, ship, today)
            return {"res": res, "info": info}

        def done(r):
            res = r["res"]
            if res.get("status") == "created":
                messagebox.showinfo("완료",
                                    f"PO {r['info'].get('parts_order_number')} 생성됨\n"
                                    "Send to Approval은 직접 눌러주세요.")
                self.do_scan()
            else:
                messagebox.showwarning("확인 필요", str(res))
        self.run_bg(job, done)

    def _record(self, m, hosp, res, info, lines, month_end):
        log = load_json(STATE_LOG, {})
        note = (f"{'월마감 선출고' if month_end else '평상시'} 건. "
                f"PO {info.get('parts_order_number')} (Send to Approval 미클릭)")
        log[m["sig"]] = {"status": "created_by_app", "topic": m["topic"],
                         "received": m["received"], "note": note}
        save_json(STATE_LOG, log)

        res_j = load_json(RESULT, {"created": []})
        res_j.setdefault("created", []).append({
            "topic": m["topic"], "hospital": hosp,
            "case_url": res.get("case_url"),
            "parts_order_url": res.get("parts_order_url"),
            "case_number": info.get("Case"),
            "parts_order_number": info.get("parts_order_number"),
            "product_code": " + ".join(l["code"] for l in lines),
            "line_price": lines[0]["price"],
            "expected_qty": lines[0]["qty"],
            "entry_id": m["entry_id"],
            "note": note + " - 릴리즈 대기",
        })
        save_json(RESULT, res_j)
        self.log("  처리 이력 기록 완료")

    def _month_end_docs(self, m, hosp, lines, ship, today):
        import make_preship_docs as mk
        import make_preship_draft as dr
        from playwright.sync_api import sync_playwright

        os.makedirs(DOCS, exist_ok=True)
        ds = today.strftime("%Y-%m-%d")
        tpdf = os.path.join(DOCS, f"거래명세서_{hosp}_{ds}.pdf")
        ppdf = os.path.join(DOCS, f"선출고요청서_{hosp}_{ds}.pdf")
        body = m["body"]
        cut = body.find("감사합니다")
        spec = {"date": ds, "hospital": hosp, "ship": ship,
                "delivery_dt": datetime.now().strftime("%Y-%m-%dT%H:%M"),
                "oracle_number": "", "vat_type": "",
                "items": [{"code": l["code"], "qty": l["qty"], "out_qty": l["qty"],
                           "remark": ""} for l in lines],
                "mail_body": body[:cut if cut > 0 else 1400]}

        self.log("  선출고 문서 생성 중...")
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True, channel="msedge")
            page = b.new_context().new_page()
            r = mk.make_transaction_statement(page, spec["mail_body"], None, tpdf,
                                              spec.get("price_override"))
            self.log(f"  거래명세서: {r.get('status')}")
            mk.make_preship_request(page, spec, ppdf)
            b.close()
        self.log(f"  PDF 2종 생성: {os.path.basename(tpdf)} / {os.path.basename(ppdf)}")

        dr.build_draft(entry_id=m["entry_id"], ship=ship,
                       month=today.month, day=today.day,
                       attachments=[tpdf, ppdf])
        self.log("  선출고 요청 메일 초안 저장 완료")

    # ------------------------------------------------------ 탭2: 승인 후
    def _build_finish(self, root):
        bar = ttk.Frame(root, padding=4)
        bar.pack(fill="x")
        ttk.Button(bar, text="대기 목록 새로고침", command=self.load_pending).pack(side="left")
        ttk.Button(bar, text="① 오라클 전송(Trigger)",
                   command=lambda: self.do_finish("trigger")).pack(side="left", padx=4)
        ttk.Button(bar, text="② 릴리즈",
                   command=lambda: self.do_finish("release")).pack(side="left", padx=4)
        ttk.Button(bar, text="③ 완료메일 발송",
                   command=lambda: self.do_finish("mail")).pack(side="left", padx=4)
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(bar, text="①~③ 한번에",
                   command=lambda: self.do_finish("all")).pack(side="left")

        self.ftree = ttk.Treeview(
            root, columns=("po", "hosp", "case", "note"), show="headings", height=16)
        for c, t, w in (("po", "Parts Order", 110), ("hosp", "병원", 220),
                        ("case", "Case", 110), ("note", "메모", 520)):
            self.ftree.heading(c, text=t)
            self.ftree.column(c, width=w, anchor="w")
        self.ftree.pack(fill="both", expand=True, padx=4, pady=4)
        self.pending = []

    def load_pending(self):
        res = load_json(RESULT, {"created": []})
        self.pending = [c for c in res.get("created", [])
                        if "릴리즈 대기" in (c.get("note") or "")
                        or "Send to Approval 미클릭" in (c.get("note") or "")]
        self.ftree.delete(*self.ftree.get_children())
        for i, c in enumerate(self.pending):
            self.ftree.insert("", "end", iid=str(i),
                              values=(c.get("parts_order_number"), c.get("hospital"),
                                      c.get("case_number"), (c.get("note") or "")[:90]))
        self.log(f"릴리즈 대기 {len(self.pending)}건")

    def do_finish(self, step):
        sel = self.ftree.selection()
        if not sel:
            messagebox.showwarning("선택 필요", "대기 목록에서 건을 고르세요.")
            return
        item = self.pending[int(sel[0])]
        po_no = item.get("parts_order_number")
        po_url = item.get("parts_order_url")
        entry_id = item.get("entry_id")
        hosp = item.get("hospital")

        def job():
            out = {}
            if step in ("trigger", "all"):
                pw, br, page = sf_page()
                try:
                    self.log(f"[{po_no}] 오라클 전송 시도")
                    out["trigger"] = po_finish.trigger_interface(page, po_url, self.log)
                finally:
                    pw.stop()
                st = out["trigger"].get("status")
                if st not in ("success", "already_success"):
                    self.log(f"[{po_no}] 전송 중단: {out['trigger']}")
                    return out
            if step in ("release", "all"):
                self.log(f"[{po_no}] 오라클 릴리즈")
                out["release"] = po_finish.release_order(
                    po_no, f"{hosp} {po_no}", "DCD", self.log)
                if out["release"].get("status") not in ("released", "already_released"):
                    self.log(f"[{po_no}] 릴리즈 중단: {out['release']}")
                    return out
            if step in ("mail", "all"):
                if not entry_id:
                    self.log(f"[{po_no}] 원본 메일 EntryID가 없어 완료메일 생략")
                    return out
                dup = po_finish.already_replied(hosp)
                if dup:
                    self.log(f"[{po_no}] 같은 제목 발송 이력 있음 - 중복 방지로 생략: {dup}")
                    out["mail"] = {"status": "skipped_dup", "hits": dup}
                    return out
                out["mail"] = po_finish.send_completion_mail(entry_id, po_no, self.log)
            return out

        def done(r):
            messagebox.showinfo("결과", json.dumps(r, ensure_ascii=False, indent=2)[:1500])
        self.run_bg(job, done)


if __name__ == "__main__":
    App().mainloop()
