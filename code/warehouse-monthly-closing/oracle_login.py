"""
Oracle Fusion 로그인 공용 모듈 (Playwright).

**2026-09-30 재작성**: 처음엔 마스터 Edge(icbl_ci_watcher.py, 포트 9333)에서 SSO
쿠키를 CDP로 복제하는 방식을 시도했으나, 이 방식 자체가 Claude Code 세션의 안전
분류기("Credential Exploration")에 막혀 검증 불가능했다. 대신 사용자가 알려준 방법
(IDCS 로그인 화면의 **"Sign in with AzureAD" 버튼을 그냥 클릭**하면 회사 Windows
세션으로 즉시 로그인됨 - 비밀번호 입력 자체가 불필요)을 실측 검증(2026-09-30)했고
훨씬 간단하고 안전(브라우저 간 쿠키 복제 없음, 순수 UI 클릭 하나)하다. 로그인 완료
후 최종 도착 URL은 `.../fscmUI/faces/FuseWelcome?...` (title="Oracle Fusion Cloud
Applications")이고, 그 사이 OAuth consent(자동, 사용자 입력 없음) + adfAuthentication
리다이렉트를 몇 초간 거친다 - 넉넉히 기다려야 한다.
"""
import time

ORACLE_HOME_URL = "https://<your-instance>.fa.<region>.oraclecloud.com/fscmUI/faces/FuseWelcome"
_SSO_BUTTON_TEXT = "Sign in with AzureAD"


def open_oracle(playwright, profile_dir, log=print, redirect_wait_rounds=8, redirect_wait_sec=3):
    """전용 프로필로 Oracle Fusion Home(FuseWelcome)을 연다.
    로그인 화면(idcs-signin)이면 "Sign in with AzureAD" 버튼을 클릭하고, OAuth
    consent/adfAuthentication 리다이렉트 체인이 끝나 fscmUI 앱 화면에 도착할 때까지
    기다린다. 그래도 로그인 화면에 머물러 있으면(예: 회사 SSO 세션 자체가 만료된
    극단적인 경우) 자동으로 더 우회하려 하지 않고 그 사실만 로그로 남긴 뒤
    (context, page, False)를 반환한다."""
    context = playwright.chromium.launch_persistent_context(
        profile_dir, headless=False, channel="msedge", accept_downloads=True,
    )
    page = context.pages[0] if context.pages else context.new_page()
    # 2026-09-30: networkidle은 Oracle Fusion Home의 대시보드 위젯들이 계속
    # 백그라운드로 폴링하는 탓에 30초 안에 절대 안 온다(실측: 여러 번 재현) -
    # "load" 이벤트 + 고정 대기로 바꿔야 안정적으로 통과한다.
    page.goto(ORACLE_HOME_URL)
    page.wait_for_load_state("load", timeout=30000)
    page.wait_for_timeout(2000)

    if "idcs" in page.url or "signin" in page.url:
        # IDCS 로그인 페이지 렌더링 속도가 가변적(실측: 어떤 실행은 즉시, 어떤
        # 실행은 몇 초 더 걸림) - 넉넉한 타임아웃으로 기다린다.
        try:
            page.get_by_text(_SSO_BUTTON_TEXT, exact=False).first.click(timeout=20000)
            log(f"[정보] {_SSO_BUTTON_TEXT!r} 버튼 클릭함")
        except Exception as e:
            log(f"[경고] SSO 버튼을 못 찾음/못 누름: {e}")

    for i in range(redirect_wait_rounds):
        page.wait_for_timeout(redirect_wait_sec * 1000)
        url = page.url
        if "fscmUI" in url and "adfAuthentication" not in url and "idcs" not in url:
            break
        log(f"[대기 {i+1}/{redirect_wait_rounds}] 리다이렉트 중... url={url[:80]}...")

    logged_in = "fscmUI" in page.url and "idcs" not in page.url and "signin" not in page.url
    if not logged_in:
        log(f"[경고] 로그인 화면에서 멈춘 것으로 보임 (URL={page.url})")
        log("       자동 로그인을 시도하지 않습니다 - 이 창에서 직접 로그인한 뒤")
        log("       스크립트를 다시 실행하거나, 로그인 상태를 수동으로 만들어주세요.")
    else:
        log(f"[정보] 로그인 확인됨 (title={page.title()!r})")
    return context, page, logged_in
