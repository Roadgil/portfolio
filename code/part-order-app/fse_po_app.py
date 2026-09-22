# -*- coding: utf-8 -*-
"""FSE PO(Shipping Only) 처리 원클릭 앱 - 임시 백업 업무용(이번 주까지만 사용 예정).

버튼 하나로 fse_po_release.py scan을 실행한다. 실제 로직(메일 발송/오라클 release)은
전부 fse_po_release.py에 있고, 이 앱은 그걸 구동하는 얇은 GUI 껍데기일 뿐이다
(part_order_backup\\part_order_app.py와 같은 패턴: 백그라운드 스레드 + 큐로 로그
스트리밍, 실행 중 중복 클릭 방지).

실행: python fse_po_app.py   (또는 FSE_PO_실행.bat 더블클릭)
"""
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk

BASE = os.path.dirname(os.path.abspath(__file__))
DEBUG_PORT = 9222


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FSE PO Shipping Only 자동화 (백업용)")
        self.geometry("820x560")
        self.q = queue.Queue()
        self.busy = False
        self.proc = None

        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(
            top,
            text="Order Type=Shipping Only 인 FSE 파트오더만 골라 용마 앞 출고요청 메일을 "
                 "보내고 오라클에서 release합니다.\nBillable Parts Order는 건드리지 않습니다.",
            justify="left",
        ).pack(anchor="w")

        bar = ttk.Frame(self, padding=(8, 0, 8, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="① 브라우저 열기(SF 로그인)", command=self.open_browser).pack(side="left")
        self.run_btn = ttk.Button(bar, text="▶ ② 실행 (스캔 + 메일발송 + release)",
                                   command=self.do_run)
        self.run_btn.pack(side="left", padx=8)
        self.status = ttk.Label(bar, text="대기 중")
        self.status.pack(side="left", padx=8)

        self.logbox = tk.Text(self, wrap="word")
        self.logbox.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.logbox.tag_config("warn", foreground="#b00")

        self.log("준비 완료. 순서: ① 브라우저 열기(SF 로그인 대기 20~30초) -> ② 실행.")
        self.log("이미 SF 브라우저가 떠 있으면 ①은 다시 안 눌러도 됩니다.")
        self.after(150, self._drain)

    # ---------------------------------------------------------- 로그
    def log(self, msg, warn=False):
        self.q.put((str(msg), warn))

    def _drain(self):
        while True:
            try:
                msg, warn = self.q.get_nowait()
            except queue.Empty:
                break
            self.logbox.insert("end", msg + "\n", ("warn",) if warn else ())
            self.logbox.see("end")
        self.after(150, self._drain)

    # ---------------------------------------------------------- 브라우저
    def open_browser(self):
        script = os.path.join(r"C:\mcp\import_mcp\part_order_backup", "open_browser.py")
        subprocess.Popen([sys.executable, script],
                          cwd=r"C:\mcp\import_mcp\part_order_backup",
                          creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        self.log("브라우저 실행 요청 - SSO 로그인까지 20~30초 걸립니다. 로그인 완료 후 ②를 누르세요.")

    # ---------------------------------------------------------- 실행
    def do_run(self):
        if self.busy:
            self.log("이미 실행 중입니다.", warn=True)
            return
        self.busy = True
        self.run_btn.state(["disabled"])
        self.status.config(text="실행 중...")
        self.log("=" * 60)
        self.log("스캔 시작...")

        def job():
            try:
                proc = subprocess.Popen(
                    [sys.executable, os.path.join(BASE, "fse_po_release.py"), "scan"],
                    cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self.proc = proc
                for line in proc.stdout:
                    line = line.rstrip("\n")
                    if line:
                        self.log(line, warn=("실패" in line or "오류" in line or "경고" in line))
                proc.wait()
                self.log(f"종료(코드 {proc.returncode})")
            except Exception as e:
                import traceback
                self.log("[예외] " + traceback.format_exc(), warn=True)
            finally:
                self.proc = None
                self.busy = False
                self.after(0, lambda: (self.run_btn.state(["!disabled"]),
                                        self.status.config(text="대기 중")))

        threading.Thread(target=job, daemon=True).start()


if __name__ == "__main__":
    App().mainloop()
