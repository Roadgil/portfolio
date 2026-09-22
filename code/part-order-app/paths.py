# -*- coding: utf-8 -*-
"""컴퓨터마다 다른 경로를 한 곳에서 풀어준다.

원래는 `C:\\Users\\yoongil.chae\\...` 가 여러 파일에 박혀 있어서 다른 사람 PC에서는
그대로 죽었다(2026-09-02 보현과장님 PC 이관 검토). 사용자 이름이 들어가는 경로는
전부 여기서 만들고, 자동으로 못 찾으면 paths_override.json 으로 직접 지정한다.

  paths_override.json 예시(필요한 것만 적으면 된다):
    {
      "ONEDRIVE": "D:\\\\OneDrive - Candela",
      "PDF_UPDATER_PY": "C:\\\\Anaconda3\\\\envs\\\\pdf_updater\\\\python.exe"
    }

`python paths.py` 로 실행하면 이 PC에서 뭐가 잡히고 뭐가 없는지 보여준다.
"""
import json
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OVERRIDE_PATH = os.path.join(SCRIPT_DIR, "paths_override.json")

_override = {}
if os.path.exists(OVERRIDE_PATH):
    try:
        with open(OVERRIDE_PATH, encoding="utf-8") as f:
            _override = json.load(f)
    except Exception as e:                       # 설정이 깨져도 앱은 떠야 한다
        print(f"[paths] paths_override.json 을 읽지 못했습니다(무시): {e}")


def _pick(key, candidates, must_exist=True):
    """override -> 후보 순으로 실제 존재하는 첫 경로를 고른다."""
    if key in _override:
        return _override[key]
    for c in candidates:
        if c and (not must_exist or os.path.exists(c)):
            return c
    return candidates[0] if candidates else None


USER_HOME = os.path.expanduser("~")

# OneDrive(회사 테넌트) 루트. 환경변수가 제일 확실하고, 없으면 홈에서 찾는다.
ONEDRIVE = _pick("ONEDRIVE", [
    os.environ.get("OneDriveCommercial"),
    os.environ.get("OneDrive"),
    os.path.join(USER_HOME, "OneDrive - Candela"),
])

OPERATION = _pick("OPERATION", [
    os.path.join(ONEDRIVE or "", "Syneron-Candela Korea - Operation"),
])
IMPORT_DIR = _pick("IMPORT_DIR", [os.path.join(OPERATION or "", "10. 수입")])
EXPORT_DIR = _pick("EXPORT_DIR", [os.path.join(OPERATION or "", "12. 수출")])
CREATIVE_DIR = _pick("CREATIVE_DIR", [os.path.join(OPERATION or "", "14. 창작소")])

PICK_DIR = _pick("PICK_DIR",
                 [os.path.join(IMPORT_DIR or "", "DCD 소모품 Pick Release 자동화")])
ICBL_DIR = _pick("ICBL_DIR",
                 [os.path.join(IMPORT_DIR or "", "인천관세법인 C.I 확인")])
REBALANCE_DIR = _pick("REBALANCE_DIR",
                      [os.path.join(EXPORT_DIR or "", "Rebalance TO 자동화")])
FSE_DIR = _pick("FSE_DIR", [os.path.join(CREATIVE_DIR or "", "FSE PO 앱")])

PROCESSED_ORDERS = os.path.join(PICK_DIR or "", "_processed_orders.json")

# 릴리즈(Selenium+pytesseract)를 돌리는 콘다 환경. 앱 기본 파이썬으로는 import가
# 안 되므로 이 exe로 subprocess를 띄운다.
PDF_UPDATER_PY = _pick("PDF_UPDATER_PY", [
    os.path.join(USER_HOME, "Miniconda", "envs", "pdf_updater", "python.exe"),
    os.path.join(USER_HOME, "miniconda3", "envs", "pdf_updater", "python.exe"),
    os.path.join(USER_HOME, "Anaconda3", "envs", "pdf_updater", "python.exe"),
    os.path.join(USER_HOME, "AppData", "Local", "miniconda3", "envs",
                 "pdf_updater", "python.exe"),
    r"C:\ProgramData\Miniconda3\envs\pdf_updater\python.exe",
    r"C:\ProgramData\Anaconda3\envs\pdf_updater\python.exe",
])

# 이 코드 폴더 자체. 사용자 이름이 안 들어가서 각 PC 같은 자리에 복사하면 그대로 맞다.
PART_ORDER_DIR = _pick("PART_ORDER_DIR", [
    os.environ.get("PART_ORDER_DIR"),
    SCRIPT_DIR,
    r"C:\mcp\import_mcp\part_order_backup",
])

# Edge 자동화 프로필. 코드가 OneDrive(창작소)로 옮겨가면서 스크립트 폴더 밑에 두면
# 74MB짜리 프로필이 통째로 동기화되고 잠긴 파일 때문에 충돌한다. 오라클 쪽
# (~/.oracle_ci_automation)과 같이 홈 디렉터리에 둔다.
_LEGACY_PROFILE_ROOT = r"C:\mcp\import_mcp\part_order_backup"
_HOME_PROFILE_ROOT = os.path.join(USER_HOME, ".part_order_automation")


def browser_profile(name="browser_profile"):
    """이 PC의 Edge 자동화 프로필 폴더. 기존 프로필이 있으면 그대로 쓴다."""
    key = "BROWSER_PROFILE" if name == "browser_profile" else "BROWSER_PROFILE2"
    if key in _override:
        return _override[key]
    home = os.path.join(_HOME_PROFILE_ROOT, name)
    if os.path.exists(home):
        return home
    legacy = os.path.join(_LEGACY_PROFILE_ROOT, name)
    if os.path.exists(legacy):          # 윤길 PC의 기존 로그인 세션 유지
        return legacy
    return home                          # 새 PC면 홈에 만든다


BROWSER_PROFILE = browser_profile()

_ITEMS = ["USER_HOME", "ONEDRIVE", "OPERATION", "IMPORT_DIR", "EXPORT_DIR",
          "CREATIVE_DIR", "PICK_DIR", "ICBL_DIR", "REBALANCE_DIR", "FSE_DIR",
          "PROCESSED_ORDERS", "PDF_UPDATER_PY", "PART_ORDER_DIR"]


def describe():
    """{이름: (경로, 존재여부)} - 환경 점검용."""
    g = globals()
    return {k: (g.get(k), bool(g.get(k)) and os.path.exists(g[k])) for k in _ITEMS}


def missing():
    """실제로 없는 항목 이름 목록."""
    return [k for k, (_p, ok) in describe().items() if not ok]


if __name__ == "__main__":
    print(f"이 PC({os.environ.get('USERNAME')})에서 잡힌 경로\n" + "=" * 78)
    for k, (p, ok) in describe().items():
        print(f"  {'O' if ok else 'X'}  {k:<18} {p}")
    bad = missing()
    print("=" * 78)
    if bad:
        print("없는 항목:", ", ".join(bad))
        print(f"paths_override.json 에 직접 지정하세요: {OVERRIDE_PATH}")
    else:
        print("전부 확인됨.")
