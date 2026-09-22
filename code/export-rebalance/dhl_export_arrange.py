# -*- coding: utf-8 -*-
"""
dhl_export_arrange.py - DHL Express 수출 arrange 자동화 (1차 목업, 2026-09-15)

fedex_ship_watcher.py의 자매 스크립트. Rebalance/RMA 파이프라인에서 FedEx 대신
DHL Express(MyDHL+)로 발송해야 하는 라인(현재는 REMI/일본 고정 하나) 처리용.

**이 파일은 사용자 SOP(2026-09-15 구술 29단계)를 바탕으로 한 1차 목업이다.**
로그인 ~ 주소록 선택 ~ 수취인 상세 확인 화면까지는 실제 라이브 로그인으로
셀렉터를 검증했다(아래 "실측 완료" 참고). 나머지(품목 등록/패키지/청구서/
발송일/픽업/세관문서/반송운송장/동의 후 계속)는 사용자가 구술한 절차를 그대로
코드화한 **미검증 골격**이다 - 사용자 지시: "곧 rebalance 할 거 하나 생기면
그걸로 실제 검증하면 되니까 대충 목업만 짜둬". 실제 건이 오면 이 파일부터
`--stop` 옵션으로 단계별로 실측하며 다듬을 것.

사용자가 구술한 전체 SOP(29단계, 2026-09-15):
  1. 오른쪽 상단 로그인
  2. yoongil.chae@candelamedical.com / (비밀번호는 환경변수 DHL_PASSWORD) 입력
  3. 인증메일 뜨면 Outlook 받은편지함의 "DHL Express 필요한 조치" 메일에서
     8자리 일회용 코드 찾아 입력 후 인증(없으면 그냥 로그인)
  4. (MFA 없으면 곧장 로그인 완료)
  5. B(수취인) 옆 주소록 클릭
  6. REMI 클릭
  7. 다음
  8. 다음 (수취인 상세 확인 화면)
  9. Commercial 클릭
 10. 품목 설명에 "Medical device part"
 11. HS 코드 9018.90
 12. 가격 USD 클릭 후 KRW로 변경
 13. 용마 제원(총 무게/총액)을 수량으로 나눠 개당 무게/금액 계산 + 제조국 기입
 14. 품목이 여러 개면 품목 추가
 15. 다음
 16. "내 인보이스 양식 사용" 클릭 후 다음
 17. my own package: 수량/중량(박스 전체 중량 그대로)/가로/세로/높이 기입
 18. 고객번호 직접 입력(일본 고정이므로 589931353 고정)
 19. 수취인 지불, DAP 고정
 20. 다음
 21. 발송일: FedEx와 동일 컷오프 로직(오후 1시 이전 arrange=당일, 이후=익영업일)
 22. (서비스) 선택
 23. 다음
 24. 세관 문서에 발송용 CI 기입(업로드)
 25. 다음
 26. 픽업 예약: 08:30~16:30, 1시 이후면 가장 이른 시간부터 16:30, front door 고정
 27. 다음
 28. "반송 운송장 필요 없음" 선택
 29. **"동의 후 계속"까지 누르고 멈춘다** - 최종 생성(그 다음 화면)은 사람이
     확인 후 진행한다(fedex_ship_watcher의 "요약 보기까지" 정지 패턴과 같은
     안전장치 - 되돌릴 수 없는 지점 직전에서 자동화를 멈춘다).

실측 완료(2026-09-15, 공유 Edge 라이브 로그인/화면 확인):
  - URL: https://mydhl.express.dhl/kr/ko/home.html (영문 kr/en/home.html도 되고,
    로그인 성공 시 kr/ko로 리다이렉트됨 -> ...?login=successful#/createNewShipmentTab)
  - 로그인: 상단 "Login" -> dhlpass.dhl.com 이동 -> 이메일/비밀번호(공유 Edge에
    저장돼 있어 자동 채워짐, 없으면 직접 입력) -> "Login" 버튼. 2026-09-15
    실측 1회는 MFA 프롬프트 자체가 안 뜨고 바로 createNewShipmentTab으로
    리다이렉트됐다 - 신뢰된 세션이면 3단계(OTP)가 통째로 생략될 수 있다는 뜻.
    **OTP 입력 화면 자체는 못 봤으므로 그 부분 셀렉터는 순수 추정이다.**
  - 대시보드 "새로운 운송장 작성" 위젯: A=발송인(자동 채움), B=수취인(직접 검색).
    B 옆 주소록 아이콘은 <i class="dhlicon-address-book">가 서로 다른 y좌표로
    2개 있다(A/B 각각 하나) - **아래쪽(y가 더 큰) 것이 B(수취인)**다. 반대로
    짚으면 REMI가 A(발송인)에 들어가 버린다(2026-09-15 1차 시도에서 실제로 이
    실수를 했고, "교체" 버튼으로 바로잡았다 - select_recipient_from_address_book
    의 max(icons, key=y) 규칙은 이 교훈을 반영한 것).
  - 주소록 다이얼로그: 검색 없이도 저장된 연락처 전체(5건)가 표에 바로 보인다.
    "Remi at SyneronCandela"(Tokyo, Japan) 행의 <td>를 클릭하면 B 필드에 채워짐.
  - "다음" 클릭 -> URL이 shipment.html#/...#address-details로 바뀌며 발송인/수취인
    상세 확인 화면(이름/회사/주소/우편번호/이메일/전화 등, 각 필드 초록 체크
    표시) 등장. 이 화면 맨 아래에도 "다음" 버튼이 하나 더 있다(우측 하단) -
    그래서 7~8단계는 "다음"을 정확히 두 번 누르는 것으로 구현했다.
  - "다음"(address-details 화면 맨 아래) 클릭 -> shipment.html#...#shipment-type
    화면 등장: 서류/물품 토글(물품이 기본 선택) + "본 발송물의 용도는
    무엇인가요?" select(name="shippingPurpose", 옵션에 'Commercial'이 그대로
    있음 - Gift/Personal, Not for Resale/Sample/Return for Repair/Return after
    Repair/Formal Export, Commercial/Return to Seller도 있어 나중에 RMA 발송
    용도 분기가 필요하면 여기서 고르면 됨).
  - Commercial 선택 후 "다음" -> 품목 등록 화면("발송하는 물건에 대해
    알려주세요"): "품목 설명 입력 (170 최대문자)" placeholder의 자유 텍스트,
    "HS 코드"는 **select가 아니라 일반 텍스트 input**(옆에 '코드 조회' 버튼은
    별도), 수량/단위(Pieces)/품목 개당 가격(통화 표시)/품목 개당 중량(kg),
    "제조국이 어디인가요?"도 **select가 아니라 자유 텍스트+자동완성 input**.
  - **미확인으로 남은 것**: 품목 개당 가격 옆의 통화 표시(USD)를 클릭해 KRW로
    바꾸는 정확한 방법(여러 테스트 탭이 뒤섞여 재현이 애매했다 - 다음 라이브
    건에서 이 부분만 집중 재검증할 것), 그리고 그 뒤(패키지/청구서/발송일/
    세관문서/픽업/반송운송장/동의 화면)는 **아직 한 번도 못 봤다** - 사용자
    구술을 그대로 옮긴 추정 구현이다. 실행할 때 반드시 각 단계 스크린샷으로
    셀렉터를 확인하고 고칠 것(라벨 텍스트 기반 헬퍼라 문구가 조금만 달라도
    못 찾을 수 있다).

CI/제원 값은 fedex_ship_watcher.py가 이미 만들어둔 파서를 그대로 재사용한다 -
같은 rebalance 파이프라인, 같은 CI/제원 소스라서 새로 만들지 않는다
(2026-08-28 "기존 메커니즘 재사용 우선" 원칙, feedback_reuse_existing_mechanism_over_new).
"""

from __future__ import annotations

import os
import re
import sys
import glob
import time
import argparse
from datetime import datetime, timedelta

ICBL_DIR = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\10. 수입\인천관세법인 C.I 확인"
)
sys.path.insert(0, ICBL_DIR)
from icbl_ci_watcher import (  # noqa: E402
    ensure_edge_running,
    close_driver,
    is_session_dead_error,
    wait_or_sleep,
    element_present,
    _wait_find,
    _resolve_edge_target,
    acquire_oracle_lock,
    release_oracle_lock,
    set_edge_owner,
)

ROOT = os.path.dirname(__file__)
sys.path.insert(0, ROOT)
# 같은 폴더의 fedex_ship_watcher.py - 용마 제원 파싱/CI 파싱/발송 규칙을 그대로
# 재사용한다(중복 구현 금지 원칙, 2026-08-28 feedback_reuse_existing_mechanism_over_new).
from fedex_ship_watcher import (  # noqa: E402
    parse_yongma_dims,
    _find_yongma_reply_body,
    parse_ci_pdf_items,
    crosscheck_export_declaration,
    CI_FOLDER_PATH,
    SERVICE_CUTOFF_HOUR,
    FEDEX_HOLIDAYS,          # 이름은 FedEx지만 대한민국 공휴일 목록이라 공용
    ORIGIN_CODE_TO_FEDEX,    # 원산지 2자 코드 -> 영문 국가명(제조국 select용, DHL 표기와 다를 수 있어 실측 필요)
    write_tracking_to_sharepoint,
    send_label_to_yongma_draft,
)

# 2026-09-18: 이 프로세스는 자기 전용 Edge(포트/프로필)를 쓴다. **반드시 위
# fedex_ship_watcher import 뒤에 와야 함** - 그 모듈이 import되는 순간 자기
# 자신을 owner로 세팅해버리므로, 이 줄이 마지막에 다시 덮어써야 이 프로세스가
# 진짜 dhl_export_arrange owner로 남는다.
set_edge_owner("dhl_export_arrange")

LOG_PATH = os.path.join(ROOT, "dhl_export_arrange.log")
LOCK_FILE_PATH = os.path.join(ROOT, "_dhl_export_arrange.lock")

DHL_HOME_URL = "https://mydhl.express.dhl/kr/ko/home.html"

# 2026-09-15 사용자 제공 계정. 비밀번호는 코드에 하드코딩하지 않고 환경변수로 받는다
# (2026-09-22, 포트폴리오 공개 저장소에 평문 노출됐던 사고 이후 수정).
# setx DHL_PASSWORD "실제비밀번호" 로 1회 등록해두면 작업 스케줄러 실행 시에도 읽힌다.
DHL_USER_EMAIL = "yoongil.chae@candelamedical.com"
DHL_PASSWORD = os.environ["DHL_PASSWORD"]

# 이 자동화는 현재 REMI(일본) 고정 라인 하나만 처리한다(사용자 SOP: "일본
# 고정이기에 589931353 고정"). 다른 나라가 생기면 fedex_ship_watcher처럼
# 국가별 매핑 테이블로 확장할 것.
RECIPIENT_SEARCH_NAME = "Remi"
DHL_CUSTOMER_NUMBER = "589931353"
INCOTERM = "DAP"

ITEM_DESC_SUFFIX = "Medical device part"
HS_CODE_FALLBACK = "9018.90"

# DHL 검증 규칙(2026-09-15 실측): "포장 완료된 발송물의 무게는 품목 중량의
# 총합계보다 커야 합니다" - 등호 불허. 품목 순중량 합계=박스 총중량이라 그대로
# 넣으면 항상 걸린다(포장재 무게만큼의 여유로 해석해 더해준다).
PACKAGE_WEIGHT_BUFFER_KG = 0.1

# 픽업 시간대(2026-09-15 사용자 지시 - fedex_ship_watcher의 용마 마감 로직과
# 같은 취지: "오전 8시30분부터 오후 4시 30분까지, 1시 이후면 가장 빠른 시간부터
# 4시 30분으로")
PICKUP_WINDOW_OPEN_MIN = 8 * 60 + 30    # 08:30
PICKUP_WINDOW_CLOSE_MIN = 16 * 60 + 30  # 16:30
PICKUP_LOCATION = "Front door"  # _TODO_실측: 실제 select 옵션 문구 확인 필요

# 라벨 PDF 저장 위치(FedEx의 "FedEx 라벨" 폴더와 같은 자리 규칙, CI 파일명과
# 헷갈리지 않게 접미사를 붙인다 - 2026-09-15 사용자 지시: "CI랑 이름이 겹칠 수
# 있으니까 라벨 이름은 좀 차이를 주면 좋겠네").
DHL_LABEL_FOLDER = os.path.join(
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\12. 수출",
    "DHL 라벨",
)

ALERT_MAIL_TO = "yoongil.chae@candelamedical.com"

# Outlook에서 DHL MFA 코드 메일을 찾을 조건(사용자 구술 그대로) - _TODO_실측:
# 실제 메일 제목/발신자를 한 번도 못 봤다(2026-09-15 시도 때 MFA 자체가 안 떴음).
DHL_OTP_SUBJECT_HINTS = ("DHL Express", "필요한 조치")
_OTP_CODE_PATTERN = re.compile(r"\b(\d{8})\b")


def log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(line.encode(enc, "replace").decode(enc, "replace"))
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def send_alert(subject: str, body: str):
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = ALERT_MAIL_TO
    mail.Subject = subject
    mail.Body = body
    mail.Save()
    log(f"알림 메일 초안 저장: {subject}")


def _save_diag(driver, tag: str) -> str:
    path = os.path.join(ROOT, f"_diag_dhl_{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
    try:
        driver.save_screenshot(path)
        log(f"  [진단] 화면 캡처: {os.path.basename(path)} (URL: {driver.current_url})")
    except Exception as e:
        log(f"  [진단] 스크린샷 실패: {e}")
    return path


def _acquire_singleton_lock():
    import msvcrt
    f = open(LOCK_FILE_PATH, "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


def get_dhl_driver():
    """공유 Edge(디버그 포트)에 새 탭을 열어 붙는다(fedex_ship_watcher.get_fedex_driver
    와 같은 패턴 - 오라클 탭을 새로 열지 않고, 이동도 DHL로 바로 한다)."""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options

    port, _ = _resolve_edge_target()
    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    driver = webdriver.Edge(options=options)
    try:
        driver.set_page_load_timeout(60)
        driver.set_script_timeout(30)
    except Exception:
        pass
    driver.switch_to.new_window("tab")
    return driver


def _advance_to_next_step(driver, marker_text: str, timeout: float = 12.0) -> None:
    """'다음' 버튼을 누르고, marker_text(현재 화면 특징 텍스트)가 화면에서
    사라질 때까지 확인한다. 실측(2026-09-15): 패키지 화면에서 필드를 다 채우고
    바로 '다음'을 누르면 버튼은 분명 활성 상태(ng-disabled=false)인데도 클릭이
    반응하지 않는 경우가 있었다(Angular 유효성 검증이 아직 안 끝난 타이밍
    문제로 추정 - 몇 초 뒤 사람이 다시 누르면 바로 넘어갔다). 그래서 한 번에
    안 넘어가면 잠깐 쉬었다 다시 누른다."""
    from selenium.webdriver.common.by import By

    start_url = driver.current_url or ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        _click_first_visible(driver, ["다음"])
        time.sleep(1.5)
        # 2026-09-15 실측: marker_text가 상단 요약줄에 남는 화면도 있어서(예:
        # 발송일 선택 완료 후에도 관련 텍스트가 어딘가 남을 수 있음) 텍스트
        # 소멸만으로 판단하면 이미 넘어갔는데도 오탐할 수 있다 - URL이
        # 바뀌었으면 그것만으로도 성공으로 본다.
        if (driver.current_url or "") != start_url:
            return
        still_there = any(e.is_displayed() for e in driver.find_elements(
            By.XPATH, f"//*[contains(normalize-space(.),'{marker_text}')]"))
        if not still_there:
            return
        time.sleep(1)
    _save_diag(driver, "advance_stuck")
    raise RuntimeError(f"'다음' 클릭을 반복해도 '{marker_text}' 화면을 벗어나지 못함")


_CLICKABLE_TAG_RANK = {"button": 0, "a": 0, "input": 0}  # 낮을수록 우선(실제 클릭 대상)


def _click_first_visible(driver, texts, timeout: float = 8.0):
    """fedex_ship_watcher._click_first_visible과 비슷한 로직이되, DHL 화면에서
    실제로 걸린 함정 하나를 더 막는다: 버튼 텍스트가 짧으면("다음" 등) 그 버튼을
    감싸는 wrapper <div>의 normalize-space(.)도 같은 텍스트 길이가 된다(자식이
    그 버튼 하나뿐이라서). 길이만으로 고르면 **wrapper div가 먼저 잡혀 클릭해도
    아무 반응이 없다**(2026-09-15 실측: '다음' 두 번을 눌러도 화면이 안 바뀜 -
    원인이 이거였다). 그래서 (텍스트 길이, 태그 우선순위) 튜플로 비교해 길이가
    같으면 button/a/input을 div/span/td보다 우선한다."""
    from selenium.webdriver.common.by import By

    deadline = time.time() + timeout
    tags = ("self::a or self::button or self::span or self::div or self::td or "
            "self::*[@role='button' or @role='link']")
    exact_xpath = "//*[" + tags + "][" + " or ".join(
        f"normalize-space(.)='{t}'" for t in texts) + "]"
    contains_xpath = "//*[" + tags + "][" + " or ".join(
        f"contains(normalize-space(.),'{t}')" for t in texts) + "]"

    while time.time() < deadline:
        for xpath in (exact_xpath, contains_xpath):
            best = best_key = None
            for el in driver.find_elements(By.XPATH, xpath):
                try:
                    if not (el.is_displayed() and el.is_enabled()):
                        continue
                    txt = (el.text or "").strip()
                except Exception as e:
                    if is_session_dead_error(e):
                        raise
                    continue
                if not txt:
                    continue
                key = (len(txt), _CLICKABLE_TAG_RANK.get(el.tag_name, 1))
                if best is None or key < best_key:
                    best, best_key = el, key
            if best is not None:
                txt = (best.text or "").strip()
                try:
                    best.click()
                except Exception:
                    driver.execute_script("arguments[0].click();", best)
                log(f"[DHL] 클릭: '{txt[:40]}' (후보 텍스트={texts})")
                time.sleep(1.5)
                return best
        time.sleep(0.5)
    _save_diag(driver, "click_" + re.sub(r"\W+", "_", texts[0])[:20])
    raise RuntimeError(f"DHL 화면에서 클릭 대상을 못 찾음: {texts}")


def _fill_by_name(driver, name: str, value: str, occurrence: int = 0) -> bool:
    """input[name=...]로 직접 채운다 - 라벨 텍스트 추정(following::)보다 훨씬
    안정적이다. 실측(2026-09-15): 품목 등록 화면 input들의 실제 name 속성이
    description/commodityCode/quantity/itemValue/weight/countryName으로
    고정돼 있는 걸 확인했다(라벨 기반 매칭이 화면 재렌더링 중 엉뚱한 필드에
    값을 꽂는 버그를 반복적으로 냈다 - 사용자 지적: "너부 데이터를 잘못
    넣는데?"). 앞으로 이 화면은 라벨 매칭 대신 이 함수를 쓴다."""
    from selenium.webdriver.common.by import By
    els = [e for e in driver.find_elements(By.NAME, name) if e.is_displayed()]
    if len(els) <= occurrence:
        log(f"  [경고] name='{name}' 입력칸을 못 찾음(값 '{value}' 미입력) - 셀렉터 실측 필요")
        return False
    el = els[occurrence]
    el.click(); el.clear(); el.send_keys(value)
    log(f"  [DHL] name='{name}' 입력: {value}")
    return True


def _fill_autocomplete_by_name(driver, name: str, value: str, occurrence: int = 0) -> bool:
    """_fill_by_name과 같은 안정적 name 기반이되, 입력 후 자동완성 li 목록에서
    첫 항목을 클릭한다(제조국 필드용)."""
    from selenium.webdriver.common.by import By
    els = [e for e in driver.find_elements(By.NAME, name) if e.is_displayed()]
    if len(els) <= occurrence:
        log(f"  [경고] name='{name}' 입력칸을 못 찾음(값 '{value}' 미입력) - 셀렉터 실측 필요")
        return False
    el = els[occurrence]
    el.click(); el.clear(); el.send_keys(value)
    time.sleep(1.2)
    options = [o for o in driver.find_elements(
        By.XPATH, "//li[contains(@class,'option') or contains(@class,'suggest')] | //ul[contains(@class,'dropdown')]//li")
        if o.is_displayed()]
    if options:
        picked_text = (options[0].text or "").strip()[:30]
        driver.execute_script("arguments[0].click();", options[0])
        log(f"  [DHL] name='{name}' 자동완성 선택: {picked_text}")
    else:
        log(f"  [DHL] name='{name}' 직접 입력(자동완성 목록 없음): {value}")
    return True


def _visible_labeled_targets(driver, lt: str, tag: str):
    """lt 텍스트를 포함하면서 **화면에 실제로 보이는** 요소 각각에서
    following::{tag}[1]을 구해, 그중 보이는 것만 순서대로 돌려준다(중복 제거).

    실측 버그(2026-09-15): 예전엔 라벨 자체의 가시성은 안 보고 결과 input만
    보이는지 걸렀다. Angular SPA는 다음/이전 단계 템플릿을 화면에 안 보이는
    채로 DOM에 같이 갖고 있는 경우가 있어서, **화면 밖에 숨은 라벨**(예: 아직
    도달하지 않은 '고객번호' 단계) 뒤의 following::input[1]이 우연히 **현재
    화면에 보이는 엉뚱한 입력칸**(포장 종류)을 가리켜버렸다 - 라벨이 안 보이면
    애초에 그 라벨을 기준으로 following을 구하지 않아야 이 함정을 막는다."""
    from selenium.webdriver.common.by import By
    anchors = [e for e in driver.find_elements(
        By.XPATH, f"//*[contains(normalize-space(.),'{lt}')]") if e.is_displayed()]
    out = []
    for a in anchors:
        for t in a.find_elements(By.XPATH, f"following::{tag}[1]"):
            if t.is_displayed() and t not in out:
                out.append(t)
    return out


def _fill_labeled_input(driver, label_texts, value: str, occurrence: int = 0) -> bool:
    """라벨 텍스트 근처(뒤에 오는 첫 input)의 입력칸에 값을 넣는다(occurrence번째
    매칭 - 품목/패키지가 여러 개일 때 사용). _TODO_실측: 실제 DOM이 라벨+following
    구조가 아니면(예: placeholder만 있는 경우) 못 찾을 수 있다 - 그때는 placeholder
    기반 매칭을 추가할 것."""
    from selenium.webdriver.common.by import By
    for lt in label_texts:
        visible = _visible_labeled_targets(driver, lt, "input")
        if not visible:
            visible = [e for e in driver.find_elements(
                By.XPATH, f"//input[contains(@placeholder,'{lt}')]") if e.is_displayed()]
        if len(visible) > occurrence:
            el = visible[occurrence]
            el.click(); el.clear(); el.send_keys(value)
            log(f"  [DHL] '{lt}' 입력: {value}")
            return True
    log(f"  [경고] 라벨 {label_texts} 근처 입력칸을 못 찾음(값 '{value}' 미입력) - 셀렉터 실측 필요")
    return False


def _select_labeled_dropdown(driver, label_texts, value: str, occurrence: int = 0) -> bool:
    """라벨 근처 select에서 value와 일치(완전 일치 우선, 없으면 부분 일치)하는
    옵션을 고른다."""
    from selenium.webdriver.support.ui import Select
    for lt in label_texts:
        visible = _visible_labeled_targets(driver, lt, "select")
        if len(visible) > occurrence:
            sel = Select(visible[occurrence])
            try:
                sel.select_by_visible_text(value)
                log(f"  [DHL] '{lt}' 선택: {value}")
                return True
            except Exception:
                for opt in sel.options:
                    if value.lower() in (opt.text or "").lower():
                        sel.select_by_visible_text(opt.text)
                        log(f"  [DHL] '{lt}' 선택(부분일치): {opt.text}")
                        return True
    log(f"  [경고] 라벨 {label_texts} 근처 select를 못 찾음(값 '{value}' 미선택) - 셀렉터 실측 필요")
    return False


def _fill_autocomplete_input(driver, label_texts, value: str, occurrence: int = 0) -> bool:
    """라벨 근처의 입력칸에 값을 타이핑하고, 자동완성 드롭다운(li/옵션)이 뜨면
    첫 항목을 클릭한다 - 드롭다운이 안 뜨면 타이핑한 값 그대로 둔다(자유 입력도
    허용하는 필드일 수 있음). 실측(2026-09-15): 품목 등록 화면의 '제조국이
    어디인가요?'는 <select>가 아니라 이런 자유 텍스트+자동완성 input이었다."""
    from selenium.webdriver.common.by import By
    for lt in label_texts:
        visible = _visible_labeled_targets(driver, lt, "input")
        if len(visible) > occurrence:
            el = visible[occurrence]
            el.click(); el.clear(); el.send_keys(value)
            time.sleep(1.2)
            options = [o for o in driver.find_elements(
                By.XPATH, "//li[contains(@class,'option') or contains(@class,'suggest')] | //ul[contains(@class,'dropdown')]//li")
                if o.is_displayed()]
            if options:
                # 클릭하면 드롭다운이 사라지면서 요소가 stale해지므로, 로그에
                # 쓸 텍스트는 클릭 **전에** 미리 읽어둔다(2026-09-15 실측 버그).
                picked_text = (options[0].text or "").strip()[:30]
                driver.execute_script("arguments[0].click();", options[0])
                log(f"  [DHL] '{lt}' 자동완성 선택: {picked_text}")
            else:
                log(f"  [DHL] '{lt}' 직접 입력(자동완성 목록 없음): {value}")
            return True
    log(f"  [경고] 라벨 {label_texts} 근처 입력칸을 못 찾음(값 '{value}' 미입력) - 셀렉터 실측 필요")
    return False


def _dismiss_cookie_banner(driver) -> None:
    """DHL/DHL Pass 쿠키 동의 배너 닫기. FedEx의 Usercentrics(섀도우 DOM)류가
    아니라 일반 DOM 버튼("Accept All")이라 평범한 클릭으로 닫힌다(2026-09-15 실측).

    2026-09-18 실측(Edge 전체 분리로 dhl_export_arrange 전용 프로필이 처음
    생기면서 첫 방문 배너를 처음 실측함): 실제 한글 버튼 문구는 "모두 수락"이지
    "전체 동의"/"모두 동의"가 아니었다 - 기존 후보 문구 4개 중 어느 것도
    매칭이 안 돼 배너가 계속 안 닫혔고, 뒤에 남은 어두운 배경막
    (onetrust-pc-dark-filter)이 email 입력칸을 가려 클릭이 튕겼다(예전 공유
    프로필은 이미 동의를 마친 상태라 이 배너 자체가 다시 안 떠서 지금까지
    안 드러난 버그). "모두 수락"을 후보에 추가."""
    from selenium.webdriver.common.by import By
    for txt in ("모두 수락", "Accept All", "Accept all", "전체 동의", "모두 동의"):
        els = [e for e in driver.find_elements(By.XPATH, f"//*[normalize-space(.)='{txt}']")
               if e.is_displayed()]
        if els:
            try:
                els[0].click()
            except Exception:
                driver.execute_script("arguments[0].click();", els[0])
            log(f"[DHL] 쿠키 배너 닫음('{txt}')")
            time.sleep(1)
            return


# ==============================================================
# 1~4단계) 로그인 + MFA(OTP) - MFA 분기는 미검증(_TODO_실측)
# ==============================================================
def _find_dhl_otp_code() -> str | None:
    """Outlook 받은편지함에서 DHL MFA 메일을 찾아 8자리 코드를 뽑는다.
    _TODO_실측: 2026-09-15 시도에서는 MFA 화면 자체가 안 떠서 실제 메일을 한 번도
    못 봤다 - 제목 조건과 코드 위치(본문 어디)는 사용자 구술만 반영한 추정이다.
    실제 코드 메일이 오면 이 함수부터 검증할 것."""
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    inbox = outlook.GetDefaultFolder(6)
    items = inbox.Items
    items.Sort("[ReceivedTime]", True)
    for i in range(1, min(items.Count, 30) + 1):
        try:
            mail = items.Item(i)
        except Exception:
            continue
        if getattr(mail, "Class", None) != 43:
            continue
        subj = str(mail.Subject or "")
        if not any(h in subj for h in DHL_OTP_SUBJECT_HINTS):
            continue
        body = str(mail.Body or "")
        m = _OTP_CODE_PATTERN.search(body) or _OTP_CODE_PATTERN.search(subj)
        if m:
            log(f"[DHL] OTP 메일 발견: '{subj[:60]}' -> 코드 {m.group(1)}")
            return m.group(1)
    return None


def open_and_login(driver) -> None:
    """1~4단계: 홈 접속 -> Login -> ID/PW -> (MFA 뜨면 Outlook 코드 자동입력).

    2026-09-15 실측: 공유 Edge에 이미 신뢰된 세션이 있으면 ID/PW조차 자동으로
    채워져 있고 MFA 프롬프트 없이 바로 createNewShipmentTab으로 리다이렉트된다.
    아래는 "이미 로그인/자동완성"과 "완전 처음부터"를 둘 다 처리하되, MFA 분기는
    미검증 상태다(_find_dhl_otp_code 참고)."""
    from selenium.webdriver.common.by import By

    log("[DHL] 홈 접속")
    driver.get(DHL_HOME_URL)
    wait_or_sleep(driver, element_present(By.TAG_NAME, "body"), 10)
    time.sleep(2)
    _dismiss_cookie_banner(driver)

    url = driver.current_url or ""
    if "login=successful" in url or "createNewShipmentTab" in url:
        log("[DHL] 이미 로그인된 세션 - 로그인 단계 건너뜀")
        return

    # 2026-09-15 실측 버그: 후보 중 첫 번째가 실제 <a>가 아니라 그걸 감싼 <td>
    # (전체 셀)일 수 있다 - 텍스트가 같으니 [0]을 그냥 쓰면 감싸는 컨테이너를
    # 클릭해 아무 반응이 없다(_click_first_visible의 태그 우선순위 함정과 동일
    # 패턴). a/button을 우선한다.
    login_links = [e for e in driver.find_elements(
        By.XPATH, "//*[normalize-space(.)='Login' or normalize-space(.)='로그인']")
        if e.is_displayed()]
    login_links.sort(key=lambda e: _CLICKABLE_TAG_RANK.get(e.tag_name, 1))
    if login_links:
        try:
            login_links[0].click()
        except Exception:
            driver.execute_script("arguments[0].click();", login_links[0])
        time.sleep(3)

    if "dhlpass.dhl.com" in (driver.current_url or ""):
        _dismiss_cookie_banner(driver)
        time.sleep(1.5)  # 브라우저 저장 자격증명 자동채움이 늦게 붙는 경우가 있어 먼저 안정화될 시간을 준다
        email_el = _wait_find(driver, By.CSS_SELECTOR,
                               "input[type='email'], input[name*='mail' i]", timeout=10)
        pw_el = _wait_find(driver, By.CSS_SELECTOR, "input[type='password']", timeout=10)
        # 2026-09-18 실측 발견: 완전히 처음 방문하는 프로필(Edge 전체 분리로
        # dhl_export_arrange 전용 프로필이 새로 생기면서 드러남)에서는 위
        # _dismiss_cookie_banner 호출 시점에 OneTrust 배너가 아직 안 뜬 채로
        # 지나가고, 그 뒤에 배너의 어두운 배경막(onetrust-pc-dark-filter)이
        # 렌더링되면서 email 입력칸을 가려 클릭이 튕긴다
        # (ElementClickInterceptedException). 기존 공유 프로필은 예전에 이미
        # 쿠키 동의를 마쳐서 이 배너 자체가 다시 안 뜨는 상태였을 뿐이라 지금까지
        # 안 드러났다. click() 직전에 한 번 더 배너 닫기를 시도해 이 타이밍
        # 창을 없앤다.
        _dismiss_cookie_banner(driver)
        # 2026-09-15 실측 버그: 값이 비어있는지 확인 후 send_keys 하는 방식은
        # 확인 시점과 실제 타이핑 사이에 Edge 저장 자격증명 자동채움이 끼어들어
        # "yoongil.chae@...comyoongil.chae@...com"처럼 겹쳐 써지는 경우가 있었다.
        # 그래서 항상 완전히 지우고 다시 채운 뒤 값이 정확한지 재확인한다.
        try:
            email_el.click()
        except Exception:
            # 2026-09-18: 그래도 여전히 가려져 있으면 배너가 이번엔 확실히
            # 떠 있는 상태이므로 다시 닫고 한 번만 재시도한다.
            _dismiss_cookie_banner(driver)
            time.sleep(0.5)
            email_el.click()
        driver.execute_script(
            "arguments[0].value=''; arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
            email_el)
        email_el.send_keys(DHL_USER_EMAIL)
        time.sleep(0.5)
        if (email_el.get_attribute("value") or "").strip() != DHL_USER_EMAIL:
            driver.execute_script(
                "arguments[0].value=arguments[1];"
                "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                email_el, DHL_USER_EMAIL)
        pw_el.click()
        driver.execute_script(
            "arguments[0].value=''; arguments[0].dispatchEvent(new Event('input',{bubbles:true}));",
            pw_el)
        pw_el.send_keys(DHL_PASSWORD)

        # 화면이 한국어 로케일(kr/ko)이면 버튼 문구가 'Login'이 아니라 '로그인'이다
        # (2026-09-15 실측 - DHL_HOME_URL이 kr/ko라서 항상 이 경로를 탄다).
        btns = [b for b in driver.find_elements(
            By.XPATH, "//button[normalize-space(.)='Login' or normalize-space(.)='로그인']")
            if b.is_displayed()]
        if not btns:
            _save_diag(driver, "no_login_button")
            raise RuntimeError("DHL Pass 로그인 화면에서 Login/로그인 버튼을 못 찾음")
        driver.execute_script("arguments[0].click();", btns[0])
        log("[DHL] ID/PW 제출")
        time.sleep(4)

    # MFA(OTP) 분기 - _TODO_실측: 입력칸이 한 칸짜리 텍스트인지 여러 칸(자리별)
    # input인지 모른다. 우선 흔한 패턴(단일 input, name/id에 otp/code류)으로
    # 시도하고, 여러 칸이면 순서대로 한 자리씩 넣는다.
    otp_deadline = time.time() + 20
    otp_inputs = []
    while time.time() < otp_deadline:
        url = driver.current_url or ""
        if "login=successful" in url or "createNewShipmentTab" in url:
            break
        otp_inputs = [e for e in driver.find_elements(
            By.CSS_SELECTOR,
            "input[name*='otp' i], input[name*='code' i], input[id*='otp' i], input[id*='code' i]")
            if e.is_displayed()]
        if otp_inputs:
            break
        time.sleep(1)

    if otp_inputs:
        log(f"[DHL] MFA 입력칸 발견({len(otp_inputs)}개) - Outlook에서 코드 조회")
        code = None
        code_deadline = time.time() + 60
        while time.time() < code_deadline and not code:
            code = _find_dhl_otp_code()
            if not code:
                time.sleep(5)
        if not code:
            _save_diag(driver, "otp_mail_not_found")
            raise RuntimeError("DHL MFA 코드 메일을 못 찾음(Outlook) - 수동 로그인 필요")
        if len(otp_inputs) == 1:
            otp_inputs[0].click(); otp_inputs[0].send_keys(code)
        else:
            for ch, el in zip(code, otp_inputs):
                el.send_keys(ch)
        _click_first_visible(driver, ["인증", "확인", "Verify", "Submit", "Continue"])
        time.sleep(3)

    deadline = time.time() + 20
    while time.time() < deadline:
        url = driver.current_url or ""
        if "login=successful" in url or "createNewShipmentTab" in url or "shipment" in url.lower():
            log(f"[DHL] 로그인 완료 확인: {url[:80]}")
            return
        time.sleep(1)
    _save_diag(driver, "after_login")
    raise RuntimeError("DHL 로그인 후 상태를 확인 못 함")


# ==============================================================
# 5~8단계) 수취인 주소록 선택 + 상세 확인 화면 (실측 완료)
# ==============================================================
def select_recipient_from_address_book(driver, search_name: str = RECIPIENT_SEARCH_NAME) -> None:
    """5~6단계: B(수취인) 입력칸 포커스 -> 옆 주소록 아이콘 클릭 -> search_name 행 클릭.

    실측(2026-09-15): 대시보드 위젯 안에 <i class="dhlicon-address-book">가 A/B
    각각 하나씩, 총 2개 있다. **아래쪽(rect.y가 더 큰) 것이 B(수취인)**다 - 반대로
    집으면 REMI가 A(발송인)에 들어가 버린다(실제로 한 번 그렇게 됐다가 '교체'
    버튼으로 바로잡았다).

    **함정(2026-09-15 재현)**: 이 아이콘을 execute_script로 바로 클릭하면
    다이얼로그가 안 열릴 때가 있다 - B 입력칸을 먼저 클릭(포커스)한 뒤에 아이콘을
    누르면 열린다(Angular 쪽 상태가 입력칸 포커스를 선행 조건으로 보는 듯).
    그래서 아래는 항상 입력칸 클릭 -> 아이콘 클릭(네이티브 우선, 실패시 JS 폴백)
    순서로 하고, 다이얼로그가 실제로 뜰 때까지 폴링한다(빈 슬립 대신 실패를
    조기에 잡기 위함). 다이얼로그는 검색 없이도 저장된 연락처 전체가 표에 바로
    나온다 - search_name이 포함된 행(<td>, 가장 짧은 매칭) 클릭."""
    from selenium.webdriver.common.by import By

    def _find_recipient_input():
        # 2026-09-15 실측 버그: 발송인(A)과 수취인(B) 입력칸이 **같은 placeholder**
        # ("도로명, 도시, 우편번호, 국가...")를 쓴다. 첫 번째로 찾은 걸 그냥
        # 반환하면 항상 A(이미 채워진 발송인)가 잡혀서, 이 함수로 B 값을 확인하는
        # 코드가 "Remi가 실제로 채워졌는데도 못 채웠다"고 오판했다. 대시보드
        # 위젯은 항상 A가 위, B가 아래(document order)라 **마지막 매칭**을 쓴다.
        matches = [el for el in driver.find_elements(By.CSS_SELECTOR, "input")
                   if el.is_displayed() and
                   ("도로명" in (el.get_attribute("placeholder") or "")
                    or "우편번호" in (el.get_attribute("placeholder") or ""))]
        return matches[-1] if matches else None

    # 2026-09-15 실측: 로그인 직후 리다이렉트된 대시보드가 완전히 렌더될 때까지
    # 살짝 지연이 있다 - 곧바로 조회하면 이 입력칸이 아직 DOM에 없어 실패한다.
    recipient_input = None
    deadline = time.time() + 10
    while time.time() < deadline:
        recipient_input = _find_recipient_input()
        if recipient_input is not None:
            break
        time.sleep(0.5)
    if recipient_input is None:
        _save_diag(driver, "recipient_input_missing")
        raise RuntimeError("수취인(B) 입력칸을 못 찾음")
    # 2026-09-15 재확인: 처음엔 이 클릭들을 JS로 바꿨다가(공유 Edge 창가림 =
    # visibilityState hidden 이론 - selenium-native-click-swallowed 메모리)
    # 오히려 다이얼로그가 안 열리는 회귀가 생겼다. 실측 재검증 결과 이 특정
    # 상호작용(입력칸 포커스 -> 주소록 아이콘)은 **네이티브 클릭이 있어야
    # 열린다**(JS로 focus()+click()을 흉내 내도 Angular 쪽에서 "진짜 사용자
    # 제스처"로 인식하지 않는 듯) - 원래의 네이티브 우선/JS 폴백 패턴으로
    # 되돌린다. ('다음' 버튼이 막혔던 진짜 원인은 이후 확인한 별개의 문제였다 -
    # 실험 중 실수로 띄운 '포장 설정' 확인 모달이 화면을 가리고 있었던 것.)
    try:
        recipient_input.click()
    except Exception:
        driver.execute_script("arguments[0].focus(); arguments[0].click();", recipient_input)
    time.sleep(1)

    icons = [e for e in driver.find_elements(By.CSS_SELECTOR, "i.dhlicon-address-book")
             if e.is_displayed()]
    if len(icons) < 2:
        _save_diag(driver, "address_book_icons")
        raise RuntimeError(f"주소록 아이콘을 2개(A/B) 못 찾음(발견 {len(icons)}개)")
    recipient_icon = max(icons, key=lambda e: e.rect["y"])
    btn = recipient_icon.find_element(By.XPATH, "./ancestor::button[1] | ./ancestor::a[1]")
    try:
        btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", btn)

    deadline = time.time() + 8
    rows = []
    while time.time() < deadline:
        # 사용자 지시(2026-09-15): "이름 열에 REMI 클릭하면 되잖아" - '이름'
        # 컬럼 셀은 텍스트가 search_name과 **정확히** 일치한다(예: 'Remi').
        # '닉네임' 컬럼(예: 'Remi at SyneronCandela')이나, 예전 테스트 중 실수로
        # 남은 '진행이 필요한 발송물' 임시저장 카드(예: 'XVRTEO\nRemi at
        # SyneronCandela\nTokyo\n...' - 페이지 전체에서 찾다 보니 같이 걸림)는
        # 정확히 일치하지 않으므로 자동으로 걸러진다.
        rows = [e for e in driver.find_elements(
            By.XPATH, f"//td[normalize-space(.)='{search_name}']") if e.is_displayed()]
        if rows:
            break
        time.sleep(0.5)
    if not rows:
        _save_diag(driver, "address_book_search")
        raise RuntimeError(f"주소록에서 '{search_name}'을 못 찾음(다이얼로그가 안 열렸을 수 있음)")
    row = rows[0]
    # 네이티브 우선, 가로채짐 등 예외 시 JS 폴백(재검증 결과 이 다이얼로그
    # 선택은 네이티브 클릭이 필요했다 - 위 recipient_input/아이콘 클릭과 같은 이유).
    from selenium.common.exceptions import ElementClickInterceptedException
    for attempt in range(3):
        try:
            row.click()
            break
        except ElementClickInterceptedException:
            time.sleep(1)
    else:
        driver.execute_script("arguments[0].click();", row)
    log(f"[DHL] 주소록에서 수취인 선택 클릭: {search_name}")

    # 다이얼로그가 실제로 닫히고 B 필드가 채워졌는지 확인한다(빈 슬립 대신
    # 조기에 실패를 잡기 위함 - 위 버그가 재발하면 바로 알 수 있도록).
    deadline = time.time() + 8
    filled_value = None
    while time.time() < deadline:
        try:
            cur = _find_recipient_input()
            val = (cur.get_attribute("value") or "").strip() if cur else ""
        except Exception:
            val = ""
        if val and "yoongil chae" not in val.lower():
            filled_value = val
            break
        time.sleep(0.5)
    if not filled_value:
        _save_diag(driver, "address_book_not_filled")
        raise RuntimeError(f"주소록에서 '{search_name}' 클릭 후에도 수취인(B) 필드가 안 채워짐")
    log(f"[DHL] 주소록에서 수취인 선택 확인: {filled_value}")
    time.sleep(1)


def confirm_addresses_and_continue(driver) -> None:
    """7~8단계: '다음'을 정확히 두 번 누른다 - 대시보드 위젯의 다음(주소 확인
    화면 shipment.html#...#address-details로 이동) -> 그 화면 맨 아래의 다음
    (shipment.html#...#shipment-type 화면 - 서류/물품 + '본 발송물의 용도'
    선택 화면으로 이동, 9단계 Commercial은 이 화면에서 고른다). 실측
    완료(2026-09-15).

    **함정(2026-09-15 실측)**: '다음' 버튼을 감싼 wrapper <div>의 텍스트도
    똑같이 '다음'이라서, 텍스트 길이만으로 후보를 고르면 클릭해도 아무 반응이
    없는 wrapper div가 걸린다 - _click_first_visible의 태그 우선순위 규칙으로
    고쳤다(버튼/a/input 우선)."""
    _click_first_visible(driver, ["다음"])
    time.sleep(3)
    _click_first_visible(driver, ["다음"])
    time.sleep(2)


# ==============================================================
# 9~15단계) Commercial 선택 + 품목 등록
# ==============================================================
def _format_hs_for_dhl(hs_digits: str | None) -> str:
    """CI 파서가 주는 6자리 HS 숫자(예: '901890')를 DHL 표기(9018.90)로 변환.
    자리수가 안 맞으면 사용자 구술 기본값(HS_CODE_FALLBACK)을 쓴다."""
    d = "".join(ch for ch in str(hs_digits or "") if ch.isdigit())
    if len(d) >= 6:
        return f"{d[:4]}.{d[4:6]}"
    return HS_CODE_FALLBACK


def select_commercial_purpose(driver) -> None:
    """9단계: shipment-type 화면에서 발송 용도를 'Commercial'로 선택 -> 다음.

    실측 완료(2026-09-15): '물품'(Goods) 타일은 기본으로 이미 선택돼 있었다
    (서류/물품 중 물품). '본 발송물의 용도는 무엇인가요?' select의 name 속성이
    정확히 shippingPurpose이고, 옵션 목록에 'Commercial'이 그대로 있다(다른
    옵션: Gift/Personal, Not for Resale/Sample/Return for Repair/Return after
    Repair/Formal Export, Commercial/Return to Seller - RMA 건은 나중에
    'Return for Repair' 등으로 분기할 수 있다, fedex_ship_watcher의 RMA
    발송용도 분기와 같은 개념)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    goods_tiles = [e for e in driver.find_elements(
        By.XPATH, "//*[normalize-space(.)='물품' or normalize-space(.)='Non-Documents']")
        if e.is_displayed()]
    if goods_tiles:
        driver.execute_script("arguments[0].click();", goods_tiles[0])
        time.sleep(1)

    sel_els = driver.find_elements(By.NAME, "shippingPurpose")
    if not sel_els:
        _save_diag(driver, "no_shipping_purpose")
        raise RuntimeError("shippingPurpose select를 못 찾음")
    Select(sel_els[0]).select_by_visible_text("Commercial")
    log("[DHL] 발송 용도: Commercial 선택")
    time.sleep(1)
    _click_first_visible(driver, ["다음"])
    time.sleep(2)


def fill_items(driver, ci_rows: list[dict], total_weight_kg: float | None) -> None:
    """10~15단계: 품목별 설명/HS/가격(KRW)/중량/제조국 기입 -> 필요시 품목 추가 -> 다음.

    실측 완료(2026-09-15, 화면 구조): 품목 등록 화면은 '품목 세부사항 입력'
    (수동, 기본 선택) / '품목 세부정보 파일 업로드' 탭으로 나뉜다. 수동 입력 쪽
    필드는:
      - "품목 설명 입력 (170 최대문자)" placeholder를 가진 자유 텍스트 input
        (또는 '품목 설명 생성하기' 버튼으로 생성 - 여기선 안 씀)
      - "HS 코드" 라벨 옆 - **select가 아니라 일반 텍스트 input**('코드 조회'
        버튼과 별개로 직접 입력 가능)
      - "수량"(기본값 1) / "단위(물품 포장 방식)" 드롭다운(기본 Pieces)
      - "품목 개당 가격"(오른쪽에 통화 표시, 기본 USD로 보였다 - _TODO_실측:
        이 통화 표시를 클릭해 KRW로 바꾸는 정확한 방법은 못 구했다. 여러 탭이
        섞여 있어서 재현이 애매했다 - 다음 라이브 건 때 이 부분만 집중 재검증할 것)
      - "품목 개당 중량"(kg)
      - "제조국이 어디인가요?" - **select가 아니라 자유 텍스트+자동완성
        input**(_fill_autocomplete_input 참고, ORIGIN_CODE_TO_FEDEX로 얻은
        영문 국가명을 그대로 타이핑)

    ci_rows/total_weight_kg 의미는 이전 버전과 동일(합계 중량을 전체 수량으로
    나눠 개당 중량 추정, CI가 가격/원산지 정답)."""
    total_qty = sum((r.get("qty") or 1) for r in ci_rows) or None

    for idx, row in enumerate(ci_rows):
        qty = row.get("qty") or 1
        unit_price = (row["amount"] / qty) if row.get("amount") is not None and qty else None
        unit_weight = (total_weight_kg / total_qty) if (total_weight_kg and total_qty) else None
        hs = _format_hs_for_dhl(row.get("hs_code"))
        desc = f"{row.get('description') or ''} {ITEM_DESC_SUFFIX}".strip()
        origin_name = ORIGIN_CODE_TO_FEDEX.get(row.get("origin"), row.get("origin"))

        log(f"[DHL] 품목 {idx + 1}: 설명='{desc}', HS={hs}, 개당가격(KRW로 넣을 값)={unit_price}, "
            f"개당중량(kg)={unit_weight}, 원산지={origin_name}, 수량={qty}")

        if idx > 0:
            _click_first_visible(driver, ["품목추가", "품목 추가", "Add Item"])
            time.sleep(1)

        # 2026-09-15 실측: 라벨 텍스트 기반(following::input) 매칭이 화면
        # 재렌더링 중 값이 엉뚱한 필드로 밀리는 버그를 반복적으로 냈다(예: HS
        # 코드값이 수량 칸에 들어감) - 이 화면은 name 속성이 고정돼 있어
        # _fill_by_name으로 직접 채운다(사용자 지적: "너무 데이터를 잘못
        # 넣는데?" - 라벨 추정 대신 안정적인 속성을 쓰라는 교훈).
        _fill_by_name(driver, "description", desc, idx)
        _fill_by_name(driver, "commodityCode", hs, idx)
        _switch_price_currency_to_krw(driver, idx)
        if unit_price is not None:
            _fill_by_name(driver, "itemValue", f"{unit_price:.2f}", idx)
        if unit_weight is not None:
            _fill_by_name(driver, "weight", f"{unit_weight:.3f}", idx)
        _fill_by_name(driver, "quantity", str(qty), idx)
        if origin_name:
            _fill_autocomplete_by_name(driver, "countryName", origin_name, idx)

    _click_first_visible(driver, ["다음"])
    time.sleep(2)


def _switch_price_currency_to_krw(driver, occurrence: int = 0) -> None:
    """12단계: 가격 통화를 USD -> KRW로 변경.

    실측 완료(2026-09-15): "USD" 표시가 눈에 보이는 뱃지라 클릭하는 방식으로
    처음 접근했는데, 그 근처의 "USD" 텍스트는 여러 개(다른 섹션의 통화 표시들과
    뒤섞임)라 엉뚱한 걸 클릭했고, 겉보기엔 성공 로그가 찍혔지만 실제로는 화면에
    여전히 USD로 남아 있었다(총액이 USD 그대로라 "최대 신고 가격" 초과 경고가
    뜸 - 원인 확정). 진짜 통화 선택기는 **`<select name="currentCurrency">`**
    (일반 select, 옵션에 3자리 통화 코드 전부 포함, 'KRW' 있음)였다."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    sel_els = [e for e in driver.find_elements(By.NAME, "currentCurrency") if e.is_displayed()]
    if len(sel_els) <= occurrence:
        log("  [경고] currentCurrency select를 못 찾음(값 'KRW' 미선택) - 셀렉터 실측 필요")
        return
    Select(sel_els[occurrence]).select_by_visible_text("KRW")
    log("  [DHL] 통화 USD -> KRW 변경")


# ==============================================================
# 16~20단계) 인보이스 양식 + 패키지 + 고객번호/인코텀
# ==============================================================
def _select_my_own_package(driver, occurrence: int = 0) -> None:
    """'포장 종류를 선택해 주세요' 자동완성 입력칸(name="packagingName")을 열어
    'My Own Package'(임의 크기, 0x0x0cm 기본) 옵션을 고른다.

    실측 완료(2026-09-15): input의 실제 name은 packagingName(라벨 텍스트
    following::이 아니라 이 name으로 직접 찾아야 안정적이다 - 사용자 지적:
    "너무 데이터를 잘못 넣는데?"). 그리고 **사용자 지시**: "My own package를
    먼저 누르고 숫자 기입해야 해" - 옵션 클릭 확정(드롭다운 닫힘) 여부를 반드시
    확인한다. **진짜 원인(2026-09-15 확정)**: 공유 Edge 창이 가려지면
    document.visibilityState가 hidden이 되어 네이티브 클릭이 예외 없이 씹힌다
    (selenium-native-click-swallowed 메모리) - 그래서 옵션 클릭이 간헐적으로
    안 먹혔던 것이지 JS 클릭 자체의 문제는 아니었다. JS 클릭만 쓰고, 그래도
    확정 여부는 계속 확인한다(창 상태와 무관하게 안전하도록)."""
    from selenium.webdriver.common.by import By

    inputs = [e for e in driver.find_elements(By.NAME, "packagingName") if e.is_displayed()]
    if len(inputs) <= occurrence:
        _save_diag(driver, "no_packaging_input")
        raise RuntimeError("포장 종류 입력칸(packagingName)을 못 찾음")
    pkg_input = inputs[occurrence]
    pkg_input.click()
    time.sleep(1)
    opts = [o for o in driver.find_elements(
        By.XPATH, "//li[contains(normalize-space(.),'My Own Package')]") if o.is_displayed()]
    if not opts:
        _save_diag(driver, "no_my_own_package_option")
        raise RuntimeError("'My Own Package' 옵션을 못 찾음")

    def _confirmed() -> bool:
        cur = [e for e in driver.find_elements(By.NAME, "packagingName") if e.is_displayed()]
        return bool(cur and "My Own Package" in (cur[0].get_attribute("value") or ""))

    # 2026-09-15 실측: 이 옵션 클릭은 네이티브/JS 어느 쪽이 먹힐지 그때그때
    # 달랐다(둘 다 예외 없이 "성공한 것처럼" 보이지만 실제로 드롭다운이 안
    # 닫히는 경우가 있었다) - 그래서 방법을 바꿔가며 재시도하고, 매번 실제로
    # 확정됐는지(입력칸에 값이 들어갔는지) 확인한다.
    confirmed = False
    for method in ("native", "js", "native", "js"):
        try:
            if method == "native":
                opts[0].click()
            else:
                driver.execute_script("arguments[0].click();", opts[0])
        except Exception:
            pass
        time.sleep(1)
        if _confirmed():
            confirmed = True
            break
        opts = [o for o in driver.find_elements(
            By.XPATH, "//li[contains(normalize-space(.),'My Own Package')]") if o.is_displayed()]
        if not opts:
            break
    if not confirmed:
        _save_diag(driver, "my_own_package_not_confirmed")
        raise RuntimeError("'My Own Package' 선택이 확정되지 않음(입력칸에 값이 안 들어감)")
    log("  [DHL] 포장 종류: My Own Package 선택 확인")


def use_own_invoice_and_package(driver, packages: list[dict]) -> None:
    """16~17단계: '내 인보이스 양식 사용' -> 다음 -> My Own Package 선택 ->
    수량/중량/가로/세로/높이 기입.

    packages: parse_yongma_dims() 반환 형식 [{"weight","L","W","H"}, ...].
    사용자 구술 17단계: "중량은 물건 전체 중량 넣으면 됨" - FedEx(개당 중량 계산)
    와 달리 여기 패키지 중량칸은 박스 그대로의 총중량을 넣는다는 점에 주의.

    실측 버그(2026-09-15): fill_items()의 품목 순중량은 total_weight_kg(=이
    packages 총중량)을 총수량으로 나눈 값이라, 품목 순중량 합계가 이 패키지
    총중량과 **수학적으로 정확히 같다**. 그런데 DHL은 "포장 완료된 발송물의
    무게는 품목 중량의 총합계보다 **커야** 합니다"(등호 불허, FedEx의 '초과
    불가'=등호 허용과 다름)로 검증한다 - 그대로 넣으면 항상 이 검증에 걸린다.
    포장재 무게만큼 실제 총중량이 순수 내용물 중량보다 크다고 보고
    PACKAGE_WEIGHT_BUFFER_KG만큼 여유를 더해 채운다(내용물 순중량 자체는
    안 건드림 - 관세 신고 금액과 무관, 포장 배송물 중량 필드에만 적용).

    실측(2026-09-15): 수량/중량/가로/세로/높이 input의 실제 name은
    quantity/weight/length/width/height - 라벨 following:: 대신 이 name으로
    직접 채운다(품목 등록 화면과 같은 이유로 값이 밀리는 버그가 있었다)."""
    from selenium.webdriver.common.by import By

    _click_first_visible(driver, ["내 인보이스 양식 사용", "Use my own invoice"])
    time.sleep(1)
    _click_first_visible(driver, ["다음"])
    time.sleep(2)

    for idx, box in enumerate(packages):
        if idx > 0:
            _click_first_visible(driver, ["포장종류 추가", "포장 종류 추가", "Add Package"])
            time.sleep(1)
        _select_my_own_package(driver, idx)
        pkg_weight = (box.get("weight") or 0) + PACKAGE_WEIGHT_BUFFER_KG
        _fill_by_name(driver, "quantity", "1", idx)
        _fill_by_name(driver, "weight", f"{pkg_weight:.3f}", idx)
        _fill_by_name(driver, "length", str(box.get("L")), idx)
        _fill_by_name(driver, "width", str(box.get("W")), idx)
        _fill_by_name(driver, "height", str(box.get("H")), idx)

    # 2026-09-15 실측 버그: 필드를 다 채운 뒤에도 '포장 종류' 자동완성
    # 드롭다운이 다시 열리며 입력칸 값이 통째로 비는 경우가 있었다(그 상태로
    # '다음'을 누르면 당연히 못 넘어간다). '다음'을 누르기 전에 제목을 한 번
    # 클릭해 드롭다운을 확실히 닫고, 값이 비어 있으면 다시 채운다.
    title = [e for e in driver.find_elements(
        By.XPATH, "//*[contains(normalize-space(.),'포장 종류를 선택해')]") if e.is_displayed()]
    if title:
        try:
            title[0].click()
        except Exception:
            driver.execute_script("arguments[0].click();", title[0])
        time.sleep(1)

    for idx, box in enumerate(packages):
        cur = [e for e in driver.find_elements(By.NAME, "packagingName") if e.is_displayed()]
        if len(cur) > idx and not (cur[idx].get_attribute("value") or "").strip():
            log("  [경고] 포장 종류 드롭다운이 다시 비어 있음 - 재입력")
            _select_my_own_package(driver, idx)
            pkg_weight = (box.get("weight") or 0) + PACKAGE_WEIGHT_BUFFER_KG
            _fill_by_name(driver, "quantity", "1", idx)
            _fill_by_name(driver, "weight", f"{pkg_weight:.3f}", idx)
            _fill_by_name(driver, "length", str(box.get("L")), idx)
            _fill_by_name(driver, "width", str(box.get("W")), idx)
            _fill_by_name(driver, "height", str(box.get("H")), idx)

    _advance_to_next_step(driver, "포장 종류를 선택해")


def fill_customer_number_and_incoterm(driver) -> None:
    """18~20단계: 고객번호 직접 입력(589931353 고정) + 수취인 지불 + DAP 고정 -> 다음.

    실측 완료(2026-09-15): 이 화면(지불 방법을 선택해 주세요)은 텍스트 입력이
    아니라 select 2개 + (조건부) input 1개 구조다:
      - select[name="transportationPaymentType"]: 기본값이 **다른 사람 계정**
        ("957045723 - John")으로 미리 채워져 있다 - 이게 사용자 SOP의 '고객번호
        직접 입력'을 강제하는 이유였다. 값을 'ALTERNATE_DHLACCOUNT'로 바꾸면
        input[name="accountNumber"]가 나타난다.
      - select[name="dutiesPaymentType"]: 기본값이 이미 '수취인 지불'이라
        보통 바꿀 필요가 없다(그래도 명시적으로 맞춰 확인한다).
      - select[name="incoterm"]: 기본값이 이미 'DAP - Delivered at Place'다.
    **실측으로 확정된 버그**: 이 화면에서 기본값(957045723)을 그대로 두고
    '다음'을 누르면 **에러 배너 없이 조용히 화면이 안 넘어간다** - 클릭 방식
    (네이티브/JS/실제 OS 마우스 클릭 전부 시도)의 문제가 전혀 아니었다. 반드시
    accountNumber를 진짜 채워야 한다."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    sel = driver.find_element(By.NAME, "transportationPaymentType")
    Select(sel).select_by_value("ALTERNATE_DHLACCOUNT")
    time.sleep(1)
    _fill_by_name(driver, "accountNumber", DHL_CUSTOMER_NUMBER)

    duties_sel = driver.find_element(By.NAME, "dutiesPaymentType")
    duties_select = Select(duties_sel)
    if "수취인" not in (duties_select.first_selected_option.text or ""):
        for opt in duties_select.options:
            if "수취인" in opt.text or "Recipient" in opt.text or "Receiver" in opt.text:
                duties_select.select_by_visible_text(opt.text)
                break

    incoterm_sel = driver.find_element(By.NAME, "incoterm")
    incoterm_select = Select(incoterm_sel)
    if "DAP" not in (incoterm_select.first_selected_option.text or ""):
        for opt in incoterm_select.options:
            if "DAP" in opt.text:
                incoterm_select.select_by_visible_text(opt.text)
                break

    log(f"[DHL] 고객번호={DHL_CUSTOMER_NUMBER}, 관부가세={duties_select.first_selected_option.text}, "
        f"인코텀={incoterm_select.first_selected_option.text}")
    _advance_to_next_step(driver, "지불 방법을 선택해")


# ==============================================================
# 21~23단계) 발송일 + 서비스 선택 (미검증 - _TODO_실측)
# ==============================================================
def select_ship_date_and_service(driver) -> None:
    """21~23단계: 발송일 로직은 fedex_ship_watcher와 동일한 컷오프(오후 1시) -
    실행 시각이 컷오프 이전이면 당일, 이후면 다음 영업일(주말/공휴일 제외,
    FEDEX_HOLIDAYS를 그대로 공용 공휴일 목록으로 재사용).

    실측 완료(2026-09-15): '발송일을 선택해 주세요' 화면은 날짜 탭(9월15,16,17...)
    이 가로로 나열돼 있고 오늘 날짜가 기본 선택돼 있다 - 컷오프를 넘겼으면
    반드시 우리가 원하는 날짜 탭으로 바꿔야 한다(안 그러면 오늘 날짜로 그대로
    진행됨). 탭의 실제 클릭 대상은 날짜 숫자 div가 아니라 그 조상의
    `div.delivery-tabs__item-content`(ng-click="deliveryDateTabsCtrl.
    selectDate(...)")다. 서비스 선택은 카드 안의 '선택' 텍스트를 가진
    `<a class="btn btn_success">`(버튼 태그가 아니라 a 태그)를 누른다."""
    from selenium.webdriver.common.by import By

    now = datetime.now()
    target = now.date() if now.hour < SERVICE_CUTOFF_HOUR else now.date() + timedelta(days=1)
    while target.weekday() >= 5 or target.strftime("%Y-%m-%d") in FEDEX_HOLIDAYS:
        target += timedelta(days=1)
    target_day = str(target.day)
    log(f"[DHL] 발송일 계산: {target.strftime('%Y-%m-%d')}(컷오프 {SERVICE_CUTOFF_HOUR}시 기준)")

    if target != now.date():
        day_els = [e for e in driver.find_elements(
            By.XPATH, f"//*[normalize-space(.)='{target_day}']") if e.is_displayed()]
        clicked = False
        for d in day_els:
            try:
                tab = d.find_element(
                    By.XPATH, "./ancestor::*[contains(@class,'delivery-tabs__item-content')][1]")
            except Exception:
                continue
            try:
                tab.click()
            except Exception:
                driver.execute_script("arguments[0].click();", tab)
            clicked = True
            time.sleep(2)
            break
        if not clicked:
            log(f"  [경고] 발송일 탭에서 '{target_day}'일을 못 찾음(더 보기 안에 있을 수 있음) - 기본 선택값(오늘)으로 진행")
    else:
        log("[DHL] 오늘 날짜가 이미 컷오프 기준과 일치 - 탭 변경 불필요")

    # 날짜를 바꾸면 요금을 비동기로 다시 계산한다(화면에 로딩 스피너/지구본
    # 애니메이션이 뜬다) - 서비스 카드가 뜰 때까지 기다린다.
    deadline = time.time() + 20
    select_links = []
    while time.time() < deadline:
        select_links = [e for e in driver.find_elements(
            By.XPATH, "//a[normalize-space(.)='선택' or normalize-space(.)='Select']") if e.is_displayed()]
        if select_links:
            break
        time.sleep(1)
    if not select_links:
        _save_diag(driver, "no_service_select")
        raise RuntimeError("서비스 '선택' 버튼을 못 찾음")
    try:
        select_links[0].click()
    except Exception:
        driver.execute_script("arguments[0].click();", select_links[0])
    log("[DHL] 서비스 선택")
    _advance_to_next_step(driver, "발송일을 선택해")


# ==============================================================
# 24~25단계) 세관 문서(CI) 첨부 (미검증 - _TODO_실측)
# ==============================================================
def attach_customs_document(driver, ci_paths: list[str]) -> None:
    """24~25단계: 세관 문서(digital_customs_invoice 화면)에 발송용 CI 첨부.

    실측 완료(2026-09-15): '세관문서 업로드' 섹션의 "이미지 파일을
    업로드하시겠습니까?" 체크박스가 기본으로 이미 체크돼 있고, 그 아래
    input[type=file]에 경로를 send_keys하면 바로 업로드된다("파일이 업로드
    되었으며, 검토준비가 되었습니다" 초록 배너로 확인). '기타 세관 서류
    업로드'는 선택사항 체크박스라 건드리지 않는다. CI가 여러 장이어도
    업로드 슬롯은 하나뿐이라(FedEx와 동일 관례) rebalance_watcher가 이미
    한 PDF로 합쳐 넘겨준다는 전제로 **첫 번째 경로만** 쓴다."""
    from selenium.webdriver.common.by import By

    file_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='file']")
    if not file_inputs:
        _save_diag(driver, "no_file_input")
        raise RuntimeError("세관 문서 업로드용 file input을 못 찾음")
    path = ci_paths[0]
    file_inputs[0].send_keys(path)
    log(f"[DHL] 세관 문서 첨부: {os.path.basename(path)}")

    deadline = time.time() + 10
    uploaded = False
    while time.time() < deadline:
        if any(e.is_displayed() for e in driver.find_elements(
                By.XPATH, "//*[contains(normalize-space(.),'업로드 되었으며')]")):
            uploaded = True
            break
        time.sleep(0.5)
    if not uploaded:
        log("  [경고] 업로드 완료 배너를 못 봤음 - 그래도 진행")

    _advance_to_next_step(driver, "세관문서 업로드")


# ==============================================================
# 26~29단계) 픽업 예약 + 반송 운송장 + 동의 후 계속 (미검증 - _TODO_실측)
# ==============================================================
def _drag_pickup_latest_time(driver, target_minutes: int) -> None:
    """'가장 늦은 시간' 슬라이더(ion.rangeSlider, span.irs-slider.to)를 원하는
    시각(분 단위)으로 드래그한다. '가장 이른 시간'은 사용자 지시(2026-09-15
    "가장 늦은 시간만 16시 30분으로 하면 돼")대로 건드리지 않는다.

    실측 완료(라이브, TO 7881033): 트랙(span.irs-line)의 실제 픽셀 폭과, 라벨에
    표시된 현재 최소/최대 시각(예: '가장 빠른 시간 10:30'/'가장 늦은 시간
    17:30' - 그날의 실제 예약 가능 범위, 고정값이 아니다)을 읽어 비율로 드래그
    좌표를 계산했다. 16:30 목표로 정확히 이동 확인됨."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    import re as _re

    def _read_minutes(heading: str) -> int | None:
        deadline = time.time() + 6
        while time.time() < deadline:
            els = [e for e in driver.find_elements(
                By.XPATH, f"//*[contains(normalize-space(.),'{heading}')]") if e.is_displayed()]
            for e in els:
                m = _re.search(r"(\d{1,2}):(\d{2})", e.text or "")
                if m:
                    return int(m.group(1)) * 60 + int(m.group(2))
            time.sleep(0.5)
        return None

    min_minutes = _read_minutes("가장 빠른 시간")
    max_minutes = _read_minutes("가장 늦은 시간")
    if min_minutes is None or max_minutes is None or max_minutes <= min_minutes:
        log("  [경고] 픽업 시간 슬라이더 범위를 못 읽음 - 가장 늦은 시간 조정 생략")
        return
    if target_minutes >= max_minutes:
        log(f"  [정보] 목표 시각이 이미 최대값({max_minutes//60:02d}:{max_minutes%60:02d}) "
            f"이상 - 조정 불필요")
        return

    to_handle = driver.find_element(By.CSS_SELECTOR, "span.irs-slider.to")
    line = driver.find_element(By.CSS_SELECTOR, "span.irs-line")
    frac = (target_minutes - min_minutes) / (max_minutes - min_minutes)
    target_x = line.rect["x"] + line.rect["width"] * frac
    handle_cx = to_handle.rect["x"] + to_handle.rect["width"] / 2
    offset_x = int(target_x - handle_cx)
    ActionChains(driver).click_and_hold(to_handle).move_by_offset(offset_x, 0).release().perform()
    time.sleep(1)
    log(f"  [DHL] 픽업 가장 늦은 시간을 {target_minutes//60:02d}:{target_minutes%60:02d}로 드래그")


def reserve_pickup(driver) -> None:
    """26~27단계: 픽업 예약 - '네 - 픽업 예약' 명시적 선택 -> 가장 늦은 시간을
    16:30으로 슬라이더 드래그(가장 이른 시간은 그대로 둔다) -> 픽업 위치
    'Front Door' 선택 -> 다음.

    실측 완료(2026-09-15, 라이브 TO 7881033 - 실제 발송물 생성까지 검증):
      - '네 - 픽업 예약' 타일은 얼핏 보면 이미 선택된 것처럼 회색으로 보이지만
        실제로는 선택된 상태가 **아니다** - 명시적으로 클릭해야 픽업 시간/위치
        입력 폼이 펼쳐진다(안 그러면 '픽업예약을 하실건가요?' 검증 에러가 뜬다).
      - 시간 입력은 select가 아니라 ion.rangeSlider(위 _drag_pickup_latest_time).
      - 픽업 위치 select의 실제 name은 'pickupLocation', 옵션은 정확히
        'Front Door'/'Reception'/'기타'."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    yes_tiles = [e for e in driver.find_elements(
        By.XPATH, "//*[contains(normalize-space(.),'네 - 픽업 예약')]") if e.is_displayed()]
    if not yes_tiles:
        _save_diag(driver, "no_pickup_yes_tile")
        raise RuntimeError("'네 - 픽업 예약' 옵션을 못 찾음")
    target = min(yes_tiles, key=lambda e: len(e.text or ""))
    try:
        target.click()
    except Exception:
        driver.execute_script("arguments[0].click();", target)
    time.sleep(1.5)

    _drag_pickup_latest_time(driver, PICKUP_WINDOW_CLOSE_MIN)

    loc_sel = driver.find_elements(By.NAME, "pickupLocation")
    if loc_sel:
        Select(loc_sel[0]).select_by_visible_text(PICKUP_LOCATION)
        log(f"[DHL] 픽업 위치: {PICKUP_LOCATION}")
    else:
        log("  [경고] pickupLocation select를 못 찾음")

    _advance_to_next_step(driver, "픽업 예약을 하시겠습니까")


def skip_return_waybill(driver) -> None:
    """28단계: '반송 운송장 필요 없음'('아니요') 선택 -> 다음.

    실측 완료(2026-09-15): 이 화면은 기본값이 이미 '아니요'(체크 표시)라 보통
    클릭 없이 바로 '다음'만 눌러도 되지만, 혹시 기본값이 바뀌어 있을 경우를
    대비해 명시적으로 확인/클릭한다."""
    from selenium.webdriver.common.by import By

    no_tiles = [e for e in driver.find_elements(
        By.XPATH, "//*[normalize-space(.)='아니요']") if e.is_displayed()]
    if no_tiles:
        target = min(no_tiles, key=lambda e: len(e.text or ""))
        try:
            target.click()
        except Exception:
            driver.execute_script("arguments[0].click();", target)
        time.sleep(1)
    _advance_to_next_step(driver, "반송 운송장이 필요")


def agree_and_continue(driver) -> None:
    """29단계: '동의 후 계속'까지 누르고 **여기서 멈춘다** - 최종 생성(운송장
    확정)은 사람이 화면을 확인한 뒤 직접 진행한다(fedex_ship_watcher의 '요약
    보기까지'와 같은 안전장치 - 되돌릴 수 없는 지점 직전에서 자동화를 멈춘다).
    사용자 지시(2026-09-15): "동의 후 계속까지 하고 말해줘".

    실측 버그(2026-09-15): "이용약관" 안내 문장 안에 굵은 글씨로 "동의 후
    계속"이 그대로 다시 들어있어서(예: "By clicking on **동의 후 계속** I am
    agreeing to..."), 텍스트로만 찾으면 그 문장 속 <b> 태그가 먼저 걸려 실제
    버튼이 눌리지 않는다. 실제 버튼은 `<button class="btn_success">`이므로
    태그까지 명시해서 찾는다. 실측(라이브, TO 7881033)으로 이 버튼을 누르면
    "전자 세관 인보이스가 전송 되었습니다" 확인 모달(완료 버튼)이 하나 더
    뜨고, 그걸 누르면 실제 운송장이 생성되며 #/complete?shipmentId=...로 이동한다
    - **정말로 되돌릴 수 없는 지점은 이 함수가 아니라 그 확인 모달**이다."""
    from selenium.webdriver.common.by import By

    btns = [b for b in driver.find_elements(
        By.XPATH, "//button[contains(@class,'btn_success')][normalize-space(.)='동의 후 계속']")
        if b.is_displayed()]
    if not btns:
        _save_diag(driver, "no_agree_button")
        raise RuntimeError("'동의 후 계속' 버튼(button.btn_success)을 못 찾음")
    try:
        btns[0].click()
    except Exception:
        driver.execute_script("arguments[0].click();", btns[0])
    time.sleep(2)
    _save_diag(driver, "stop_agree_and_continue")
    log("[DHL] '동의 후 계속' 클릭 완료 - 여기서 정지. 화면을 확인하고(전자 세관 "
        "인보이스 전송 확인 모달이 뜰 수 있음) 최종 생성을 진행해주세요.")


def _click_final_complete(driver, timeout: float = 45.0) -> None:
    """'동의 후 계속' 뒤 뜨는 '전자 세관 인보이스가 전송 되었습니다' 확인
    모달의 '완료' 버튼을 눌러 **실제 운송장을 생성한다**(진짜 되돌릴 수 없는
    지점). fedex_ship_watcher의 같은 원칙(2026-08-27)과 동일하게, 실패해도
    자동으로 다시 누르지 않는다(중복 발송물 생성 방지) - 실패 시 화면을
    남기고 사람이 확인한다.

    2026-09-15 사용자 확인: "완료까지 전부 자동(FedEx와 동일)" - DHL도
    FedEx처럼 이 클릭까지 자동으로 진행하도록 확정(그 전까지는 사람이 직접
    누르는 안전장치였다)."""
    from selenium.webdriver.common.by import By

    deadline = time.time() + timeout
    btn = None
    while time.time() < deadline:
        cands = [b for b in driver.find_elements(By.XPATH, "//button[normalize-space(.)='완료']")
                 if b.is_displayed()]
        if cands:
            btn = cands[0]
            break
        time.sleep(1)
    if btn is None:
        _save_diag(driver, "no_final_complete_button")
        raise RuntimeError("'전자 세관 인보이스 전송' 확인 모달의 '완료' 버튼을 못 찾음")

    log("[DHL] === 최종 '완료' 클릭 - 실제 운송장을 생성합니다 ===")
    try:
        btn.click()
    except Exception:
        driver.execute_script("arguments[0].click();", btn)

    deadline = time.time() + timeout
    while time.time() < deadline:
        url = driver.current_url or ""
        if "complete" in url and "shipmentId" in url:
            _save_diag(driver, "after_final_complete")
            log(f"[DHL] 운송장 생성 완료: {url}")
            return
        time.sleep(1)
    _save_diag(driver, "final_complete_no_redirect")
    raise RuntimeError(
        "'완료' 클릭 후 '#/complete?shipmentId=...' 화면으로 못 감 - 생성 여부를 "
        "DHL 화면에서 직접 확인하세요(중복 생성 방지를 위해 자동 재시도하지 않습니다)")


# ==============================================================
# 완료 후속 처리(라벨 다운로드 + 용마 발송 + SharePoint 기입)
# ==============================================================
# 2026-09-15 실측 경로 변경: 처음엔 '문서 재출력'(edge://print 네이티브 인쇄
# 미리보기, Fluent UI Shadow DOM이라 셀레늄 클릭이 안 먹고 driver.get_window_
# position()도 'Browser window not found'로 실패) -> Microsoft Print to PDF
# 프린터 변경 -> 저장 다이얼로그, 이 전 구간을 win32 OS 클릭으로 우회해서
# 겨우 성공시켰었다. 그런데 **완료 화면(#/complete?shipmentId=...)에는
# '문서 다운로드' 링크가 따로 있고, 이걸 누르면 그냥 진짜 파일 다운로드가
# 바로 일어난다**(Shipment <id>.zip 안에 TransportLabel_<AWB>.pdf/WaybillDoc_
# <AWB>.pdf/ShipmentReceipt_<AWB>.pdf 3개, 전부 실제 텍스트 레이어가 있는
# 정상 PDF) - win32/OS 클릭이 통째로 필요 없다. 위의 print-preview 우회는
# 전부 삭제하고 이 방법으로 교체했다.
DHL_DOWNLOAD_DIR = os.path.join(os.path.expanduser("~"), "Downloads")


def _zip_snapshot(folder: str) -> set[str]:
    try:
        return {f for f in os.listdir(folder) if f.lower().endswith(".zip")}
    except FileNotFoundError:
        return set()


def download_dhl_label(driver, save_path: str) -> str:
    """완료 화면(#/complete?shipmentId=...)의 '문서 다운로드' 링크를 눌러
    받아지는 zip에서 TransportLabel_*.pdf만 꺼내 save_path로 저장한다.
    **현재 화면이 그 완료 화면이어야 한다**(agree_and_continue 이후 사람이
    '완료'를 눌러 실제 운송장이 생성된 뒤)."""
    from selenium.webdriver.common.by import By

    before_zips = _zip_snapshot(DHL_DOWNLOAD_DIR)
    before_handles = set(driver.window_handles)

    links = [e for e in driver.find_elements(By.XPATH, "//a[normalize-space(.)='문서 다운로드']")
             if e.is_displayed()]
    if not links:
        _save_diag(driver, "no_doc_download_link")
        raise RuntimeError("'문서 다운로드' 링크를 못 찾음(완료 화면인지 확인)")
    try:
        links[0].click()
    except Exception:
        driver.execute_script("arguments[0].click();", links[0])

    deadline = time.time() + 30
    zip_path = None
    while time.time() < deadline:
        new = _zip_snapshot(DHL_DOWNLOAD_DIR) - before_zips
        done = [f for f in new if not os.path.exists(
            os.path.join(DHL_DOWNLOAD_DIR, f + ".crdownload"))]
        if done:
            zip_path = os.path.join(
                DHL_DOWNLOAD_DIR,
                sorted(done, key=lambda f: os.path.getmtime(os.path.join(DHL_DOWNLOAD_DIR, f)))[-1])
            break
        time.sleep(1)
    if zip_path is None:
        _save_diag(driver, "doc_download_timeout")
        raise RuntimeError("'문서 다운로드' 클릭 후 zip 파일이 안 생김(Downloads 폴더 확인)")

    # 다운로드가 시작되면 edge://downloads-hub 탭이 새로 뜬다(2026-09-15
    # 실측) - 남겨두면 자동화 흐름에 섞이니 닫고 원래 탭으로 돌아간다.
    for h in set(driver.window_handles) - before_handles:
        try:
            driver.switch_to.window(h)
            if "downloads" in (driver.current_url or ""):
                driver.close()
        except Exception:
            pass
    remaining = list(before_handles & set(driver.window_handles))
    if remaining:
        driver.switch_to.window(remaining[0])

    import zipfile
    with zipfile.ZipFile(zip_path) as z:
        label_names = [n for n in z.namelist() if n.startswith("TransportLabel_")]
        if not label_names:
            raise RuntimeError(f"zip 안에 TransportLabel_*.pdf가 없음: {z.namelist()}")
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with z.open(label_names[0]) as src, open(save_path, "wb") as dst:
            dst.write(src.read())
    try:
        os.remove(zip_path)
    except Exception:
        pass

    log(f"[DHL] 라벨 PDF 저장 완료: {save_path} (원본 zip: {os.path.basename(zip_path)})")
    return save_path


def _extract_awb_from_complete_page(driver) -> str | None:
    """완료 화면 본문 텍스트의 '운송장 번호\\n1384512964' 표기에서 AWB를
    뽑는다(fedex_ship_watcher와 같은 원칙 - AWB는 성공 화면에서만 읽는다,
    다른 탭/파일은 보지 않는다)."""
    from selenium.webdriver.common.by import By

    body = driver.find_element(By.TAG_NAME, "body").text or ""
    m = re.search(r"운송장\s*번호\s*\n\s*(\d{8,14})", body)
    return m.group(1) if m else None


def finalize_after_creation(driver, to_number: str, delivery_number: str | None = None) -> dict:
    """29단계(동의 후 계속) 뒤, **사람이 화면을 확인하고 '완료'를 눌러 실제
    운송장이 생성된 뒤**(현재 화면이 '#/complete?shipmentId=...') 실행한다.
    사용자 지시(2026-09-15): "선택된 문서 출력 누르고 용마한테 보내주면 돼
    첨부해서 AWB apac movement에 기입하고 여기까지 자동화해줘".

    순서: 완료 화면 본문에서 AWB 우선 확인 -> 라벨 PDF 다운로드
    (download_dhl_label, zip 파일명의 AWB와 교차검증) -> 용마 답장 초안에
    라벨 첨부 후 발송(fedex_ship_watcher.send_label_to_yongma_draft 재사용)
    -> SharePoint APAC Stock Movements에 AWB 기입(fedex_ship_watcher.
    write_tracking_to_sharepoint 재사용).

    최종 생성(그 '완료' 클릭) 자체는 이 함수가 하지 않는다 - agree_and_continue
    가 멈추는 지점 뒤에서 사람이 이미 확인/승인했다는 전제로 호출한다."""
    url = driver.current_url or ""
    if "complete" not in url or "shipmentId" not in url:
        raise RuntimeError(
            "현재 화면이 '#/complete?shipmentId=...'가 아님 - '완료'를 눌러 실제 "
            "운송장을 생성한 뒤 실행하세요")

    awb = _extract_awb_from_complete_page(driver)

    label_tag = delivery_number or to_number or "label"
    os.makedirs(DHL_LABEL_FOLDER, exist_ok=True)
    save_path = os.path.join(DHL_LABEL_FOLDER, f"KRP-JPP {label_tag}-DHL-발송-라벨.pdf")
    download_dhl_label(driver, save_path)

    # save_path는 우리가 정한 이름(AWB 없음)이라, 라벨 PDF 본문에서 AWB를
    # 다시 읽어 완료화면 값과 교차검증한다.
    awb_from_zip = None
    import pdfplumber
    with pdfplumber.open(save_path) as pdf:
        label_text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    lm = re.search(r"WAYBILL\s+([\d ]{8,14})", label_text)
    if lm:
        awb_from_zip = re.sub(r"\D", "", lm.group(1)) or None

    if awb and awb_from_zip and awb != awb_from_zip:
        log(f"[경고] 완료화면 AWB({awb})와 라벨 PDF AWB({awb_from_zip})가 다름 - 라벨 PDF 값을 신뢰")
        awb = awb_from_zip
    awb = awb or awb_from_zip

    if awb:
        log(f"[DHL] AWB 확인: {awb}")
    else:
        log("[경고] AWB를 못 읽음 - 화면/파일을 직접 확인 필요")

    if to_number:
        send_label_to_yongma_draft(to_number, save_path, send=True)
        if awb:
            write_tracking_to_sharepoint(driver, to_number, awb)
            log(f"[DHL] SharePoint APAC Stock Movements 기입 완료: TO {to_number} -> {awb}")
    else:
        log("[정보] to_number가 없어 용마 발송/SharePoint 기입은 건너뜀(라벨만 저장)")

    return {"awb": awb, "label_path": save_path}


# ==============================================================
# 파이프라인 + CLI
# ==============================================================
def arrange_dhl_shipment(*, to_number: str | None = None, ci_pdf_path=None,
                          packages: list[dict] | None = None,
                          stop_at: str | None = None,
                          confirm: bool = False) -> dict | None:
    """DHL Express 픽업 arrange 전체 순서(1~29단계). stop_at으로 중간 정지 가능
    (실측/디버깅용). confirm=False(기본, 수동 실행용 안전장치)면 29단계(동의
    후 계속)까지 진행 후 자동 정지 - 최종 생성(그 다음 확인 모달의 '완료')은
    사람이 직접 확인 후 누른다. confirm=True(rebalance_watcher가 씀, 2026-09-15
    사용자 확인 "완료까지 전부 자동")면 '완료'까지 눌러 실제 운송장을 생성하고
    finalize_after_creation(라벨 다운로드+용마 발송+SharePoint 기입)까지
    이어서 실행한 뒤 그 결과 dict를 반환한다."""
    if ci_pdf_path is None:
        ci_paths: list[str] = []
    elif isinstance(ci_pdf_path, str):
        ci_paths = [ci_pdf_path]
    else:
        ci_paths = list(ci_pdf_path)

    packages = packages or []
    total_weight_kg = sum((p.get("weight") or 0) for p in packages) or None

    ensure_edge_running()
    driver = get_dhl_driver()
    try:
        open_and_login(driver)
        if stop_at == "login":
            _save_diag(driver, "stop_login")
            return

        select_recipient_from_address_book(driver)
        if stop_at == "address":
            _save_diag(driver, "stop_address")
            return

        confirm_addresses_and_continue(driver)
        if stop_at == "confirm":
            _save_diag(driver, "stop_confirm")
            return

        if not ci_paths:
            hits = sorted(glob.glob(os.path.join(CI_FOLDER_PATH, "KRP-JPP *.pdf")),
                          key=os.path.getmtime)
            if hits:
                ci_paths = [hits[-1]]
                log(f"[정보] --ci 미지정 - CI 폴더 최신 파일 사용: {os.path.basename(ci_paths[0])}")
        if not ci_paths:
            raise FileNotFoundError("CI PDF가 없음 - --ci로 경로를 지정하세요")
        ci_rows = parse_ci_pdf_items(ci_paths)
        decl_warnings: list[str] = []
        if to_number:
            decl_warnings = crosscheck_export_declaration(to_number, ci_rows)

        select_commercial_purpose(driver)
        fill_items(driver, ci_rows, total_weight_kg)
        if stop_at == "items":
            _save_diag(driver, "stop_items")
            return

        use_own_invoice_and_package(driver, packages)
        if stop_at == "package":
            _save_diag(driver, "stop_package")
            return

        fill_customer_number_and_incoterm(driver)
        if stop_at == "billing":
            _save_diag(driver, "stop_billing")
            return

        select_ship_date_and_service(driver)
        if stop_at == "service":
            _save_diag(driver, "stop_service")
            return

        attach_customs_document(driver, ci_paths)
        if stop_at == "customs":
            _save_diag(driver, "stop_customs")
            return

        reserve_pickup(driver)
        if stop_at == "pickup":
            _save_diag(driver, "stop_pickup")
            return

        skip_return_waybill(driver)
        if stop_at == "return":
            _save_diag(driver, "stop_return")
            return

        agree_and_continue(driver)

        if not confirm:
            send_alert(
                f"[DHL] {to_number or ''} 수출 arrange 사전입력 완료 - 화면 확인 후 최종 생성해주세요",
                "브라우저의 DHL '동의 후 계속' 다음 화면에서 내용을 확인하고 최종 생성을 진행해주세요.\n"
                "(이 스크립트는 최종 생성 버튼은 절대 누르지 않습니다.)\n"
                + (("\n[확인 필요] 수출신고실적이 CI와 다릅니다(DHL에는 CI 값을 넣었습니다):\n  - "
                    + "\n  - ".join(decl_warnings)) if decl_warnings else ""),
            )
            return None

        _click_final_complete(driver)
        delivery_number = None
        if ci_paths:
            m = re.search(r"(\d{5,8})", os.path.basename(ci_paths[0]))
            delivery_number = m.group(1) if m else None
        result = finalize_after_creation(driver, to_number, delivery_number)
        if decl_warnings:
            send_alert(
                f"[DHL] {to_number or ''} 확인 필요 - 수출신고실적이 CI와 다릅니다",
                "발송물 생성은 완료됐습니다(DHL에는 CI 값을 넣었습니다):\n  - "
                + "\n  - ".join(decl_warnings),
            )
        return result
    except Exception:
        # fedex_ship_watcher와 같은 이유(2026-08-27) - 실패해도 탭을 남겨 사람이
        # 이어서 하거나 화면 상태를 볼 수 있게 한다.
        log("[정보] 실패로 종료 - 확인할 수 있게 DHL 탭은 닫지 않고 남겨둡니다")
        raise
    else:
        close_driver(driver)


def _find_existing_dhl_print_tab(driver):
    """finalize 모드용: 이미 열려 있는 공유 Edge 탭들 중 '완료'가 눌려 실제
    운송장이 생성된 화면(#/complete?shipmentId=...)을 찾는다. 새 탭을 열지
    않는다 - arrange_dhl_shipment가 멈춘 뒤 사람이 같은 브라우저에서 '완료'를
    누른 바로 그 탭을 이어서 쓰기 위함."""
    for h in driver.window_handles:
        try:
            driver.switch_to.window(h)
        except Exception:
            continue
        url = driver.current_url or ""
        if "complete" in url and "shipmentId" in url:
            return h
    return None


def _resolve_packages(to_number: str | None) -> list[dict]:
    if not to_number:
        return []
    body = _find_yongma_reply_body(to_number)
    if not body:
        log(f"[경고] TO {to_number} 용마 회신을 못 찾음 - packages 없이 진행")
        return []
    packages = parse_yongma_dims(body)
    if not packages:
        log(f"[경고] TO {to_number} 용마 회신에서 제원을 못 뽑음")
        return []
    return packages


def main():
    parser = argparse.ArgumentParser(description="DHL Express 수출 arrange 자동화(1차 목업)")
    parser.add_argument("mode", choices=["login", "ship", "finalize"])
    parser.add_argument("--to", help="TO번호(CI/제원 조회용)")
    parser.add_argument("--ci", action="append", help="업로드할 CI PDF 경로(반복 가능, 미지정시 CI 폴더 최신 파일)")
    parser.add_argument("--boxes", help="박스 제원 JSON(생략하면 --to의 용마 회신에서 자동 추출)")
    parser.add_argument("--delivery", help="라벨 파일명에 쓸 Delivery Number(미지정시 --ci 파일명에서 자동 추출, "
                                            "finalize 모드에서만 사용)")
    parser.add_argument("--stop", choices=["login", "address", "confirm", "items", "package",
                                           "billing", "service", "customs", "pickup", "return"],
                        help="지정 단계까지만 실행(단계별 실측용)")
    parser.add_argument("--confirm", action="store_true",
                        help="'동의 후 계속' 뒤 '완료'까지 눌러 실제 운송장을 생성하고 "
                             "라벨 다운로드+용마 발송+SharePoint 기입까지 이어서 실행 "
                             "(rebalance_watcher가 씀 - 되돌릴 수 없는 지점이니 수동 실행 시 주의)")
    args = parser.parse_args()

    if args.mode == "login":
        arrange_dhl_shipment(stop_at="login")
        return

    if args.mode == "finalize":
        # agree_and_continue가 멈춘 뒤 사람이 브라우저에서 직접 '완료'를 눌러
        # 실제 운송장을 생성했다는 전제(2026-09-15: 이 최종 클릭은 자동화하지
        # 않는다 - 되돌릴 수 없는 지점이라 사람이 확인 후 누른다). 그 다음
        # 단계(라벨 다운로드+용마 발송+SharePoint 기입)만 이어서 자동화한다.
        from selenium import webdriver
        from selenium.webdriver.edge.options import Options

        ensure_edge_running()
        port, _ = _resolve_edge_target()
        options = Options()
        options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
        driver = webdriver.Edge(options=options)
        handle = _find_existing_dhl_print_tab(driver)
        if handle is None:
            log("[에러] '#/complete?shipmentId=...' 화면(발송 완료 화면)이 열린 DHL 탭을 "
                "못 찾음 - 먼저 브라우저에서 '완료'까지 눌러 운송장을 생성해주세요")
            return
        delivery_number = args.delivery
        if not delivery_number and args.ci:
            m = re.search(r"(\d{5,8})", os.path.basename(args.ci[0]))
            delivery_number = m.group(1) if m else None
        result = finalize_after_creation(driver, args.to, delivery_number)
        log(f"[DHL] finalize 완료: {result}")
        return

    lock = _acquire_singleton_lock()
    if lock is None:
        log("이미 다른 인스턴스가 실행 중 - 종료")
        return
    # 2026-09-18: 공유 Edge 락을 걸었다가(TO 7882258 실사고로 도입) 같은 날
    # stale 판정 구멍으로 또 실전 충돌이 났다 - 대신 이 스크립트를 전용
    # Edge(포트/프로필)로 완전히 분리해 겹칠 일 자체를 없앴다
    # (set_edge_owner("dhl_export_arrange") 참고). 락 제거.
    log("===== dhl_export_arrange 시작 =====")
    try:
        if args.boxes:
            import json
            packages = json.loads(args.boxes)
        else:
            packages = _resolve_packages(args.to)
        arrange_dhl_shipment(to_number=args.to, ci_pdf_path=args.ci, packages=packages,
                             stop_at=args.stop, confirm=args.confirm)
    except Exception as e:
        import traceback
        log(f"[에러] {e}\n{traceback.format_exc()}")
        send_alert("[DHL] 수출 arrange 자동화 실행 에러", f"{e}\n\n{traceback.format_exc()}")
    finally:
        try:
            lock.close()
        except Exception:
            pass
    log("===== dhl_export_arrange 종료 =====")


if __name__ == "__main__":
    main()
