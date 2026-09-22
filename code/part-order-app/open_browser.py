"""ServiceMax 자동화용 브라우저를 띄운다 (회사 SSO 세션이 살아있으면 자동 로그인).

이 프로세스는 백그라운드에서 계속 떠 있어야 한다 (닫으면 브라우저도 닫힘).

로그인 정보(비밀번호 등)는 이 스크립트가 절대 입력/열람하지 않는다 - 회사 SSO(Azure AD)가
Windows 로그인 세션으로 이미 인증돼 있어서, 계정 선택 화면에 뜨는 계정 타일을 클릭하는 것만으로
로그인이 끝난다(비밀번호 입력 단계 자체가 없음). 이 타일 클릭 외의 경우(다른 계정 로그인,
비밀번호 입력 요구 등)는 자동화하지 않고 사용자에게 맡긴다.

로그인 후, 별도 스크립트(inspect_page.py)가 동일 브라우저에
remote-debugging-port로 접속해 현재 화면을 스크린샷으로 확인한다.
"""

import os

from playwright.sync_api import sync_playwright

import local_config
import paths

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 스크립트 폴더가 OneDrive로 옮겨가도 프로필(74MB, 잠긴 파일)은 로컬에 둔다
PROFILE_DIR = paths.browser_profile("browser_profile")
DEBUG_PORT = 9222
START_URL = "https://candelamedical.my.salesforce.com"
SSO_ACCOUNT_HINT = local_config.load()["sso_hint"]


def try_auto_login(page):
    """Azure AD 계정 선택 화면이면 Windows 연결된 계정 타일을 클릭해 로그인을 완료한다.
    이미 로그인돼 있거나(바로 salesforce.com으로 감) 계정 타일이 안 보이면(비밀번호 입력
    요구 등 다른 상황) 아무것도 하지 않고 사용자 수동 로그인에 맡긴다."""
    try:
        page.wait_for_load_state("load", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1500)

    if "salesforce.com" in page.url:
        print("이미 로그인된 세션입니다.", flush=True)
        return True

    tile = page.get_by_text(SSO_ACCOUNT_HINT, exact=False)
    if tile.count() == 0:
        print("자동 로그인 가능한 계정 타일을 찾지 못했습니다 - 직접 로그인해주세요.", flush=True)
        return False

    tile.first.click()
    try:
        page.wait_for_load_state("load", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1500)

    if "salesforce.com" in page.url:
        print("SSO 자동 로그인 완료.", flush=True)
        return True

    print(f"계정 타일을 클릭했지만 아직 Salesforce로 넘어오지 못했습니다 (현재 URL: {page.url}) - 직접 확인해주세요.", flush=True)
    return False


def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            channel="msedge",
            args=[f"--remote-debugging-port={DEBUG_PORT}"],
        )
        page = context.new_page()
        page.goto(START_URL)
        print(f"브라우저 열림. (디버그 포트: {DEBUG_PORT})", flush=True)

        try_auto_login(page)

        print("이 창은 계속 떠 있습니다.", flush=True)

        # 프로세스를 계속 살려서 브라우저가 닫히지 않도록 함
        page.wait_for_timeout(3600 * 1000 * 6)  # 최대 6시간


if __name__ == "__main__":
    main()
