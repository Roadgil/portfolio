# -*- coding: utf-8 -*-
"""이 PC에서 파트오더앱이 돌 수 있는지 점검한다 (아무것도 바꾸지 않는다).

새 PC(보현과장님 등)에 옮길 때 뭐가 없는지 한 번에 보려고 만든 것.
경로는 paths.py가 계정에 맞춰 풀어주므로 여기서는 '있는지'만 본다.

  python env_check.py
"""
import importlib
import os
import shutil
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

OK, NO, WARN = "  [O] ", "  [X] ", "  [!] "
problems, warns = [], []


def need(cond, label, hint="", soft=False):
    if cond:
        print(OK + label)
    elif soft:
        print(WARN + label + (f"  -> {hint}" if hint else ""))
        warns.append(label)
    else:
        print(NO + label + (f"  -> {hint}" if hint else ""))
        problems.append(label)
    return bool(cond)


def has_module(name, python=None):
    """다른 파이썬(콘다 환경)에서도 확인할 수 있다."""
    if python is None:
        try:
            importlib.import_module(name)
            return True
        except Exception:
            return False
    if not os.path.exists(python):
        return False
    try:
        r = subprocess.run([python, "-c", f"import {name}"],
                           capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def port_open(port):
    s = socket.socket()
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        s.close()


print(f"파트오더앱 환경 점검 - {os.environ.get('USERNAME')} @ "
      f"{os.environ.get('COMPUTERNAME')}")
print("=" * 78)

print("\n[1] 폴더 경로 (paths.py가 계정에 맞춰 자동으로 찾음)")
for k, (p, ok) in paths.describe().items():
    need(ok, f"{k:<18} {p}",
         "없으면 paths_override.json 에 직접 지정", soft=(k == "REBALANCE_DIR"))

print("\n[2] 앱 파이썬 패키지 (지금 이 파이썬)")
print(f"      {sys.executable}")
need(has_module("playwright"), "playwright", "pip install playwright")
need(has_module("win32com"), "pywin32 (Outlook 제어)", "pip install pywin32")
need(has_module("tkinter"), "tkinter (화면)")
need(has_module("lxml"), "lxml", "pip install lxml", soft=True)

print("\n[3] 릴리즈용 콘다 환경 (오라클 Pick Release)")
py = paths.PDF_UPDATER_PY
if need(os.path.exists(py), f"pdf_updater 파이썬  {py}",
        "conda create -n pdf_updater 후 아래 패키지 설치"):
    for mod, pip in (("selenium", "selenium"), ("pytesseract", "pytesseract"),
                     ("pandas", "pandas"), ("psutil", "psutil"),
                     ("fitz", "PyMuPDF"), ("win32com", "pywin32")):
        need(has_module(mod, py), f"pdf_updater: {mod}",
             f"conda run -n pdf_updater pip install {pip}")

print("\n[4] 외부 프로그램")
edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
need(os.path.exists(edge), "Microsoft Edge", edge)
tess = os.path.join(paths.USER_HOME, "AppData", "Local", "Programs",
                    "Tesseract-OCR", "tesseract.exe")
need(os.path.exists(tess) or bool(shutil.which("tesseract")),
     "Tesseract-OCR (필증 OCR - 릴리즈 체인이 import함)",
     "https://github.com/UB-Mannheim/tesseract 설치 후 위 경로에")

print("\n[5] 실행 중인 브라우저")
need(port_open(9222), "Salesforce 자동화 Edge (포트 9222)",
     "앱에서 [브라우저 열기]를 누르면 뜸", soft=True)
need(port_open(9333), "오라클 자동화 Edge (포트 9333)",
     "릴리즈할 때 자동으로 뜸", soft=True)
print(f"      SF 프로필: {paths.browser_profile('browser_profile')}")

print("\n[6] Outlook 설정")
try:
    import local_config
    cfg = local_config.load()
    print(f"      메일박스: {cfg['outlook_mailbox']}")
    print(f"      스캔 폴더: {cfg['target_folders']}")
    user_cfg = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            f"local_config.{os.environ.get('USERNAME', '')}.json")
    need(os.path.exists(user_cfg), f"계정별 설정 파일 {os.path.basename(user_cfg)}",
         "없으면 공용 local_config.json 값을 씀 - 본인 값으로 만드세요", soft=True)
    if has_module("win32com"):
        import win32com.client
        ns = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
        names = [f.Name for f in ns.Folders]
        need(cfg["outlook_mailbox"] in names,
             f"Outlook에 메일박스 붙어 있음 ({cfg['outlook_mailbox']})",
             f"현재 붙은 것: {names}")
except Exception as e:
    print(WARN + f"Outlook 확인 실패: {e}")
    warns.append("Outlook 확인")

print("\n" + "=" * 78)
if problems:
    print(f"막히는 항목 {len(problems)}건 - 이것부터 해결해야 합니다:")
    for p in problems:
        print("   -", p)
else:
    print("막히는 항목 없음. 앱을 실행해도 됩니다.")
if warns:
    print(f"\n참고(당장은 괜찮음) {len(warns)}건: " + ", ".join(warns))
