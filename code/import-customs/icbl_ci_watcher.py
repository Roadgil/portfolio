# -*- coding: utf-8 -*-
"""
icbl_ci_watcher.py

인천관세법인(icbl.kr)에서 오는 "수입 통관 정보 제출 안내 - AWB #..." 메일을
감시하여, AWB 첨부 PDF의 C.I(Commercial Invoice) 정보를 오라클 Fusion의
실제 데이터와 대조하고, 인천관세법인 메일에 답장한다.

- 받은편지함 > 인천관세법인 폴더에서 제목에 "수입 통관 정보 제출 안내"가
  포함되고 첨부파일명이 AWB로 시작하는 메일을 찾는다.
- AWB 번호 기준으로 이미 처리한 건은 건너뜀 (중복 방지, _processed_awb.json).
- 첨부 PDF(스캔 이미지 PDF, 자체 텍스트 없음)를 이미지로 변환 후 OCR(Tesseract)로
  Delivery Number(9로 시작 7자리)와 Ship From 지역을 추출.
- Ship From -> 오라클 Ship-from Organization 코드 매핑(SHIP_FROM_ORG_MAP).
- 회신(=통관 진행 승인) 전 안전장치: 그 Delivery Number가 수입신고실적 파일에
  이미 깔려 있는지 확인한다(Intransit 미반영 건으로 통관하면 나중에 필증을
  파싱할 행이 없어 실적이 조용히 빔). DECL_REGISTER_GUARD 설명 참고.
- 오라클 Fusion(Scheduled Processes > Print Commercial Invoice Report)을
  Selenium(Edge, 디버그 포트 9333 고정 인스턴스에 접속)으로 실행하여
  XML 데이터를 받아 금액을 대조.
  - 금액 일치(이상 없음): 원본 C.I 그대로 답장(ReplyAll)을 바로 발송
    (2026-07-24 사용자 요청 - 사람이 볼 것도 없이 확정된 건이라 초안 없이 발송).
  - 금액 불일치: 오라클에서 PDF Export까지 시도해서 그 PDF를 첨부한 답장을
    바로 발송 (2026-08-21 사용자 요청 - 예전엔 초안만 만들고 사람 검토를
    기다렸는데, 결국 항상 그대로 보내게 되어 자동 발송으로 전환).
    사후 확인용 알림 메일은 계속 임시보관함에 남긴다.
  - 오라클 접속 실패(로그인 세션 끊김 등): 사람이 봐야 하는 상태로 로그만
    남기고 스킵 (다음 주기에 재시도).

주의:
- Edge가 디버그 포트 9333으로 미리 떠 있어야 함 (오라클 로그인 세션 유지).
  꺼져 있으면 저장된 프로필로 재실행을 시도하되, 로그인 페이지가 뜨면
  사람이 한 번 더 로그인해야 함 - 이 경우 로그만 남기고 스킵.
- 스크립트 자체는 죽지 않게 하고(단계별 try/except), 다음 실행에서
  재시도 가능하도록 idempotent하게 작성한다.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime

import pandas as pd
import pypdfium2 as pdfium
import pytesseract
from PIL import Image

# ==============================================================
# 경로/설정
# ==============================================================
ROOT = r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입\인천관세법인 C.I 확인"
LOG_PATH = os.path.join(ROOT, "icbl_ci_watcher.log")
STATE_PATH = os.path.join(ROOT, "_processed_awb.json")
# 2026-07-10: 제출한 오라클 Print Commercial Invoice Report의 Process ID를
# (org_code, delivery_no) 단위로 저장. Succeeded 대기가 오래 걸려서(최대
# 2시간) 이번 실행이 타임아웃/중단되더라도, 다음 20분 주기 실행이 같은 건을
# 또 "Schedule New Process"로 새로 제출하지 않고 저장된 Process ID를 이어서
# 확인하게 하기 위함 — 같은 delivery에 대해 오라클에 중복 리포트가 쌓이는 것 방지.
ORACLE_PROCESS_STATE_PATH = os.path.join(ROOT, "_oracle_process_state.json")
# 2026-07-14: "사람 확인 필요"류 알림(C.I 확인 필요/오라클 재로그인 필요/오라클
# 조회 실패)은 처리가 안 끝나면(state에 안 찍히면) 20분마다 계속 재시도되고,
# 그때마다 똑같은 알림 초안이 또 쌓인다(사용자 확인 - 재발송 메일 기다리는 동안
# 20분마다 중복 알림). 같은 메일(entry_id)에 대해 같은 이유로는 일정 시간 안에
# 한 번만 알림을 보내도록 dedup_key별 마지막 발송 시각을 저장해둔다.
ALERTED_STATE_PATH = os.path.join(ROOT, "_alerted_entries.json")
ALERT_DEDUP_TTL_HOURS = 6.0
# 2026-09-17: 시료확인서(SAMPLE_CONFIRM_PART_NUMBERS)는 품목당 1회만 첨부하면
# 되는 문서다(사용자 확인 - "품목별로 한번 나가면 그 이후엔 안 보내도 돼"). 이미
# 첨부해서 보낸 품목번호를 여기에 기록해, 같은 품목이 나중에 또 다른 CI로 오면
# 확인서 없이 그냥 평소처럼 회신하도록 한다.
SAMPLE_CONFIRM_SENT_STATE_PATH = os.path.join(ROOT, "_sample_confirm_sent_state.json")
# 2026-08-06 사용자 요청: AWB(FedEx)/DHL 번호별 "추출 결과"를 저장해서, 같은 건이
# 다음 주기에 또 잡혔을 때 OCR을 처음부터 다시 돌리지 않게 한다(Process ID를
# _oracle_process_state.json에 저장해 재사용하는 것과 같은 취지). 배경: 오라클
# Succeeded 대기가 20분 주기를 넘기면 그 메일은 state(_processed_awb.json)에 아직
# 안 찍히므로 다음 실행에서 계속 "신규 건"으로 잡히고, Phase A가 첨부 저장 + OCR을
# 매번 반복했다(실측: DHL 1670899683이 매 회차 약 46초 - 10:43:21 발견 -> 10:44:07
# 추출 완료). 캐시는 (state_key -> 추출 결과 case) 형태이고, 메일이 재발송되면
# entry_id가 달라지므로 그때는 캐시를 무시하고 새로 추출한다.
EXTRACT_CACHE_PATH = os.path.join(ROOT, "_awb_extract_cache.json")
EXTRACT_CACHE_TTL_HOURS = 24.0 * 7
PDF_SAVE_DIR = os.path.join(ROOT, "AWB_PDF")

# 2026-07-08: pick_release_watcher.py(DCD/소모품 출고 자동화)와 같은 Edge
# 디버그 인스턴스(포트 9333)를 공유한다. 두 스크립트가 동시에 오라클/FedEx
# 화면을 조작하면 서로의 네비게이션·클릭을 방해해 진짜로 깨질 수 있어서,
# 파일 기반 락으로 겹침을 막는다.
#
# 2026-09-18 재정비(사용자 지적 "겹쳐도 잘 돌게 해줘"): 이 락은 원래부터
# 정의만 돼 있고 **어느 스크립트도 실제로 호출하지 않던 죽은 코드**였다
# (rebalance_watcher.py trigger 스캔과 fedex_ship_watcher.py 수동 실행이
# 같은 Edge에서 겹쳐 클릭이 3연속 다른 지점에서 씹힌 실사고로 발견 - TO
# 7882258 FedEx 어레인지). "icbl만 상대 락을 확인해서 양보"하던 예전 설계도
# 편도라 실질적 상호배제가 아니었다. 이제 이 파일을 가져다 쓰는 모든
# 스크립트(icbl_ci_watcher/rebalance_watcher/fedex_ship_watcher/
# pick_release_watcher/ship_confirm_watcher/sco_cancel_watcher 등)가
# main() 진입 시 이 락을 걸고(안 되면 최대 wait_sec까지 대기) 끝날 때 푸는
# **대칭적** 방식으로 바꿨다 - acquire_oracle_lock 참고.
# 2026-09-18(같은 날 재정비 직후 완전 분리로 대체): 위 상호배제 락은 하루도
# 못 가 stale 판정 구멍(5분 넘는 배치 중 갱신 안 됨)으로 또 실전 충돌을 냈다
# (shared-edge-cross-script-lock-implemented.md). 근본 해법으로 7개 스크립트를
# 완전히 분리된 Edge 프로세스/프로필/포트로 바꿔서(EDGE_OWNER_CONFIGS 참고)
# 애초에 겹칠 일을 없앴다 - 이제 아래 acquire_oracle_lock/release_oracle_lock/
# oracle_lock_held_by_other와 이 세 상수는 **아무 스크립트도 호출하지 않는
# 죽은 코드**다. 삭제하지 않고 남겨두는 이유는 혹시 남아있을 외부 참조를
# 깨지 않기 위함(이 코드베이스 관례) - 새로 뭔가를 공유 자원 보호에 쓰려면
# 이 락을 되살리기보다 오늘처럼 owner별로 완전히 분리하는 쪽을 먼저 검토할 것.
ORACLE_LOCK_PATH = os.path.join(os.path.dirname(ROOT), "_oracle_browser.lock")
ORACLE_LOCK_STALE_SECONDS = 300  # 이보다 오래된 락은 죽은 것으로 간주하고 무시
ORACLE_LOCK_DEFAULT_WAIT_SEC = 600  # acquire_oracle_lock 기본 대기 한도(10분)


class OracleBusyElsewhere(Exception):
    pass


class DeclarationFileLocked(Exception):
    """2026-07-23: 실적 파일(수입신고실적 자동화.xlsx)이 사용자 쪽에서 Excel로
    열려 있어 읽기(PermissionError)가 실패한 경우. 데이터가 없는 게 아니라
    일시적으로 못 읽는 것뿐이라 재시도하면 풀린다 - "Ship From 확정 불가"로
    오판해 사람 확인 알림을 보내면 안 되고, 이번 회차만 조용히 넘기고 다음
    스케줄 실행에서 다시 시도해야 한다."""
    pass


def oracle_lock_held_by_other(self_owner: str) -> bool:
    if not os.path.exists(ORACLE_LOCK_PATH):
        return False
    try:
        with open(ORACLE_LOCK_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        owner = lines[0].strip() if lines else ""
        if owner == self_owner or not owner:
            return False
        ts = datetime.fromisoformat(lines[1].strip()) if len(lines) > 1 else None
        if ts is None:
            return False
        return (datetime.now() - ts).total_seconds() < ORACLE_LOCK_STALE_SECONDS
    except Exception:
        return False


def acquire_oracle_lock(owner: str, wait_sec: int = ORACLE_LOCK_DEFAULT_WAIT_SEC) -> bool:
    """다른 스크립트가 이미 이 락을 쥐고 있으면(오래되지 않았으면) 최대
    wait_sec까지 3초 간격으로 기다렸다가 잡는다. 못 잡으면 False를 반환하고
    - 호출부는 이번 회차를 조용히 건너뛰어야 한다(억지로 진행하면 두 스크립트가
    같은 Edge를 동시에 조작하게 된다). 성공하면 True."""
    deadline = time.time() + wait_sec
    waited_logged = False
    while oracle_lock_held_by_other(owner):
        if time.time() >= deadline:
            log(f"[정보] {owner}: 공유 브라우저 락을 {wait_sec}초 안에 못 얻음 - 이번 회차 건너뜀")
            return False
        if not waited_logged:
            log(f"[정보] {owner}: 다른 자동화가 공유 브라우저 사용 중 - 대기")
            waited_logged = True
        time.sleep(3)
    try:
        with open(ORACLE_LOCK_PATH, "w", encoding="utf-8") as f:
            f.write(f"{owner}\n{datetime.now().isoformat()}\n")
    except Exception as e:
        # 2026-08-06: 락 파일을 못 쓰면 상대 자동화가 "비어 있음"으로 보고
        # 같은 시간에 같이 들어와 탭이 충돌한다(stale element/요소 못 찾음
        # 연쇄 실패의 알려진 원인). 동작은 그대로(무시하고 진행) 두되,
        # 그날 충돌이 났을 때 원인을 찾을 수 있도록 흔적을 남긴다.
        log(f"[경고] 오라클 락 파일 쓰기 실패({type(e).__name__}: {e}) - "
            f"다른 자동화와 동시 실행 충돌이 날 수 있음")
    return True


def release_oracle_lock(owner: str):
    try:
        if os.path.exists(ORACLE_LOCK_PATH):
            with open(ORACLE_LOCK_PATH, "r", encoding="utf-8") as f:
                existing_owner = f.readline().strip()
            if existing_owner == owner:
                os.remove(ORACLE_LOCK_PATH)
    except Exception as e:
        # 2026-08-06: 락이 안 풀리면 상대 자동화가 최대 ORACLE_LOCK_STALE_SECONDS
        # (300초) 동안 계속 양보하며 그냥 넘어간다 - 조용히 실패하면 "왜 저쪽이
        # 계속 일을 안 하지"의 원인을 못 찾는다.
        log(f"[경고] 오라클 락 해제 실패({type(e).__name__}: {e}) - "
            f"다른 자동화가 최대 {ORACLE_LOCK_STALE_SECONDS}초간 양보할 수 있음")

TESSERACT_PATH = r"C:\Users\yoongil.chae\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# 2026-09-18: 7개 스크립트(icbl_ci_watcher/pick_release_watcher/rebalance_watcher/
# fedex_ship_watcher/dhl_export_arrange/ship_confirm_watcher/sco_cancel_watcher)가
# 전부 이 하나의 Edge(포트 9333)를 공유하던 것을 완전 분리한다 - 오늘 낮에 같은
# Edge를 pick_release_watcher가 오래 붙잡고 있는 사이 rebalance_watcher가
# "죽은 락"으로 오판해 끼어들어 클릭/입력이 씹히는 사고가 실전에서 확인됐다
# (shared-edge-cross-script-lock-implemented.md). 락으로 순서를 강제하는 대신,
# 스크립트마다 완전히 독립된 Edge 프로세스/프로필/디버그포트를 줘서 애초에
# 겹칠 일이 없게 한다.
#
# 문제는 오라클 SSO가 회사 Azure AD 연동 MFA라 사람 개입 없이는 로그인을 새로
# 뚫을 수 없다는 것 - 지금까지는 이 프로필 하나에 실제 사람이 로그인해서 남긴
# SSO 세션 쿠키를 전 스크립트가 공유해왔다. 분리하면서도 이 이점을 유지하려고,
# icbl_ci_watcher(아래 MASTER_EDGE_OWNER)의 기존 프로필을 "진짜 로그인 이력이
# 쌓이는 원본"으로 그대로 남겨두고, 나머지 6개는 각자 자기 프로필로 완전히
# 분리한 뒤 - 로그인이 필요할 때마다(sso_relogin 참고) 마스터의 살아있는 Edge에서
# CDP로 SSO 관련 쿠키(로그인 유지 쿠키: login.microsoftonline.com/.sharepoint.com/
# *.oraclecloud.com 도메인)만 실시간으로 읽어와 자기 프로필에 주입한다(파일
# 복사가 아니라 브라우저간 쿠키 값 복제 - Cookies SQLite 파일은 그 프로필의
# Edge가 켜져 있는 동안 계속 잠겨 있어 파일 복사 자체가 불가능함을 실측 확인함,
# `edge-per-script-separation.md` 참고). 실측 검증: 이 12개 쿠키만 새 프로필에
# 주입한 뒤 `recover_oracle_login()`을 그대로 호출하면 MFA 없이 바로
# FuseWelcome까지 도착함(2026-09-18 확인).
EDGE_PROFILE_ROOT = r"C:\Users\yoongil.chae\.oracle_ci_automation"
MASTER_EDGE_OWNER = "icbl_ci_watcher"
EDGE_OWNER_CONFIGS = {
    "icbl_ci_watcher": {
        "port": 9333,
        "profile_dir": EDGE_PROFILE_ROOT + r"\browser_profile",
    },
    "pick_release_watcher": {
        "port": 9334,
        "profile_dir": EDGE_PROFILE_ROOT + r"\browser_profile_pick_release_watcher",
    },
    "rebalance_watcher": {
        "port": 9335,
        "profile_dir": EDGE_PROFILE_ROOT + r"\browser_profile_rebalance_watcher",
    },
    "fedex_ship_watcher": {
        "port": 9336,
        "profile_dir": EDGE_PROFILE_ROOT + r"\browser_profile_fedex_ship_watcher",
    },
    "dhl_export_arrange": {
        "port": 9337,
        "profile_dir": EDGE_PROFILE_ROOT + r"\browser_profile_dhl_export_arrange",
    },
    "ship_confirm_watcher": {
        "port": 9338,
        "profile_dir": EDGE_PROFILE_ROOT + r"\browser_profile_ship_confirm_watcher",
    },
    "sco_cancel_watcher": {
        "port": 9339,
        "profile_dir": EDGE_PROFILE_ROOT + r"\browser_profile_sco_cancel_watcher",
    },
    # 2026-09-21: FIN101110 라인만 골라 unassign→autocreate shipment→ship confirm
    # 하는 일회성 수동 작업(사용자가 지켜보며 진행)용. 스케줄러 작업이 아니라
    # 상시 운영 owner는 아니지만, 동시에 도는 다른 오라클 자동화와 Edge 포트/
    # 프로필이 겹치지 않도록 별도 슬롯을 둔다.
    "fin101110_manual": {
        "port": 9340,
        "profile_dir": EDGE_PROFILE_ROOT + r"\browser_profile_fin101110_manual",
    },
}
# 이 프로세스가 어느 스크립트로 실행 중인지 - 각 스크립트가 자기 import 직후
# `set_edge_owner("자기이름")`을 한 번 불러서 바꾼다(icbl_ci_watcher 자신은 기본값
# 그대로라 아무것도 안 해도 됨, 기존 동작 100% 유지). 프로세스마다 완전히 분리된
# 파이썬 인터프리터라 스레드 간 경합 걱정 없음(main에서 한 번 세팅 후 읽기만 함).
_CURRENT_EDGE_OWNER = {"name": MASTER_EDGE_OWNER}


def set_edge_owner(name: str):
    if name not in EDGE_OWNER_CONFIGS:
        raise ValueError(f"알 수 없는 Edge owner: {name!r} (가능: {list(EDGE_OWNER_CONFIGS)})")
    _CURRENT_EDGE_OWNER["name"] = name


def _resolve_edge_target(owner: str = None):
    name = owner or _CURRENT_EDGE_OWNER["name"]
    cfg = EDGE_OWNER_CONFIGS.get(name, EDGE_OWNER_CONFIGS[MASTER_EDGE_OWNER])
    return cfg["port"], cfg["profile_dir"]


# 예전 코드 호환용 - 지금 프로세스의 owner 기준 포트/프로필을 가리키는 값처럼
# 보이지만, owner가 바뀌면 이 두 상수는 갱신되지 않는다(모듈 로드 시점 값으로
# 고정). 이 파일 내부에서는 더 이상 참조하지 않고 항상 _resolve_edge_target()을
# 쓴다 - 혹시 남아있을 외부 참조를 위해서만 값을 유지해둔다.
EDGE_PROFILE_DIR = EDGE_OWNER_CONFIGS[MASTER_EDGE_OWNER]["profile_dir"]
EDGE_DEBUG_PORT = EDGE_OWNER_CONFIGS[MASTER_EDGE_OWNER]["port"]

# 로그인 유지에 필요한 쿠키만 골라서 마스터 프로필 -> 각 스크립트 프로필로
# 실시간 복제한다(2026-09-18 실측으로 확정된 목록 - 오라클 자체 도메인에는
# Akamai 봇매니저 쿠키만 있고, 실제 "로그인 유지"는 회사 Azure AD 연동
# (login.microsoftonline.com)과 SharePoint(FedAuth) 쿠키가 쥐고 있음).
SSO_COOKIE_DOMAIN_KEYWORDS = ("microsoftonline", "sharepoint", "oraclecloud")
# Edge를 새로 띄운 뒤 디버그 포트가 열리기를 기다리는 한도(2026-09-14 추가)
EDGE_LAUNCH_WAIT_SEC = 30
ORACLE_HOME_URL = "https://ekkw.fa.us6.oraclecloud.com/fscmUI/faces/FuseWelcome"
# 오라클 Fusion 앱 도메인 - "지금 정말 앱 안에 들어와 있는가"를 판정할 때 쓴다
# (oracle_is_logged_in 설명 참고, 2026-08-06 추가). 리포트 뷰어(xmlpserver)도
# 같은 도메인이라 같이 커버된다.
ORACLE_APP_HOST = "ekkw.fa.us6.oraclecloud.com"

OUTLOOK_INBOX_SUBFOLDER = "인천관세법인"
# 2026-07-08: 포워더별로 메일 형식이 다름 — FedEx는 AWB 스캔 PDF 1장,
# DHL은 EWB/HWB(텍스트 PDF, waybill)+INV(스캔, 1~2장 — Commercial Invoice와
# Delivery Note가 둘 다 "INV"로 시작해서 섞여 옴) 구조. 둘 다 지원한다.
FEDEX_SUBJECT_CONTAINS = "수입 통관 정보 제출 안내"
DHL_SUBJECT_CONTAINS = "통관 정보 제출 요청"

# 스레드(요청 메일 [FW]/[RE]... 답장) 전체에서 공통되는 고유 키를 제목에서
# 뽑는다 — 답장(RE) 메일은 원본과 첨부가 다를 수 있어 첨부명보다 제목이 안전.
FEDEX_KEY_RE = re.compile(r"AWB\s*#\s*-?\s*(\d+)")
DHL_KEY_RE = re.compile(r"DHL\s+(\d+)")

# 인천관세법인이 통관 완료 후 회신하는 메일은 수입신고필증(_IMP_*.pdf)을
# 첨부해서 온다 — 이 첨부가 있으면 그 건은 이미 처리 완료된 것으로 간주(스킵).
IMP_ATTACHMENT_PREFIX = "_imp_"

# 2026-08-14 사용자 요청: FedEx 안내 메일 본문의 "화물 정보" 블록에는
#   수입자: SYNERON CANDELA KOREA CO., LTD.
#   수출업체: CEVA LOGISTICS
#   선적국가: US
# 형태로 수출업체가 찍혀 나온다. 이 자동화가 다루는 건 우리 본사 물류 경로
# (Syneron 계열 법인 발송 / 미국 CEVA Logistics 발송)뿐인데, 지금까지는 이
# 필드를 아예 안 보고 제목·첨부만으로 걸러서 타사 발송 건(2026-08-14 COHERENT
# CORP, 2026-08-03 ZIMMER MEDIZINSYSTEME GMBH)까지 집어 들었다. 그 건들은
# 오라클에 대조할 Delivery가 없으니 결국 "정보 부족 -> 사람 확인" 알림으로
# 끝나는데, 그 전까지 매 20분마다 첨부 저장 + OCR을 반복했다(실측: 08-03
# ZIMMER 건이 하루 종일 재시도됨). 그래서 메일 스캔 단계에서 바로 걸러낸다.
# DHL 형식 메일은 본문에 이 필드가 없으므로(수출업체는 제목 괄호에 들어옴)
# 필드가 없으면 기존 동작 그대로 통과시킨다 — 지금까지 정상 처리해온
# "(CANDELA MEDICAL)" 건들을 이 필터로 죽이지 않기 위함.
# 값은 반드시 같은 줄에서만 읽는다([^\r\n]*). \s*로 받으면 수출업체가 빈칸인
# 메일(2026-07-20 AWB 874456365610, 중국발 Rebalance 건 - 실제로 WAY 재배치로
# 정상 처리된 우리 건이다)에서 개행을 넘어가 다음 줄 "선적국가: CN"을 수출업체로
# 읽어버린다 -> 우리 건을 타사 건으로 오판해 통째로 스킵하게 됨.
EXPORTER_LINE_RE = re.compile(r"수출업체\s*[:：][ \t]*([^\r\n]*)")
# CANDELA를 넣은 이유(2026-08-14 실측): 사용자가 말한 기준은 "Syneron 또는 CEVA
# Logistics"인데, 실제 메일에는 같은 우리 본사 물량이 "CANDELA CO FEDEX
# LOGISTICS"(AWB 513914060630, FSD=San Diego발)로 찍혀 오고 정상 처리(가격 일치
# -> 답장 초안)까지 끝난 이력이 있다. 이걸 빼면 멀쩡한 우리 건을 조용히
# 놓치므로(자동화가 안 하고 사람도 모르는 게 제일 위험) 사명 표기 변형으로 보고
# 허용에 포함한다. 반대로 COHERENT/ZIMMER 같은 외부 업체는 계속 차단된다.
EXPORTER_ALLOW_KEYWORDS = ("SYNERON", "CANDELA", "CEVA LOGISTICS")

# 2026-09-17 사용자 요청: 이 품목번호가 포함된 CI는 표준통관을 위해 RA팀이 받은
# 시료확인서(한국산업기술시험원 발급, 산기 26-10478호)를 인천관세법인 회신에
# 같이 첨부해야 한다. 처음엔 "CI 올 때까지 회신 보류(홀딩)"로 짰다가, 실제로는
# 홀딩이 필요한 게 아니라 확인서를 인천관세법인에 미리 보내두면 되는 것으로
# 정정되어(2026-09-17 12:02 발송 완료) 홀딩 로직은 제거함. 그런데 앞으로 이
# 품목들이 실린 CI가 실제로 오면 그 회신에도 이 확인서를 한 번 첨부해서 보내야
# 한다는 요구가 남아있어 - 회신 자체는 지연시키지 않고(홀딩 아님) 자동 회신에
# 이 PDF만 추가로 첨부하는 방식으로 재구현함(find_sample_confirm_part_number).
SAMPLE_CONFIRM_PART_NUMBERS = {"9914-00-9092", "SBA102908", "FIN104727"}
SAMPLE_CONFIRM_PDF_PATH = os.path.join(
    ROOT, "시료확인서", "시료확인서_9914-00-9092_FIN104727_SBA102908_VbeamPro_20260917.pdf")
# 2026-09-18 사용자 확인: 위 PDF가 잘못 만들어짐(제조원이 실제 말레이시아
# Plexus Manufacturing인데 멕시코 NPA de Mexico로 잘못 찍혀 있었음) - RA팀이
# 수정본 재발급 예정이라 그 전까지 첨부 기능만 잠시 껐었음.
# 2026-09-21 재개: RA팀(Miae Jang 경유, "FW: next 5 Vbeam Pro allocations -
# 1 to follow" 메일, 2026-09-21 10:36) 수정본 확인 - 제조원이 Plexus
# Manufacturing Sdn. Bhd.(말레이시아, Penang)로 정정됨. SAMPLE_CONFIRM_PDF_PATH
# 경로의 파일을 이 수정본으로 교체(구버전은 .bak_*_wrong_mexico_origin으로
# 보관)하고 다시 켬.
SAMPLE_CONFIRM_ENABLED = True

ALERT_MAIL_TO = "yoongil.chae@candelamedical.com"

# Ship From 텍스트(OCR) -> 오라클 Ship-from Organization 코드
# 확인된 것만 넣어둠. 모르는 지역이 나오면 사람이 확인해야 하므로 매핑 안 함.
SHIP_FROM_ORG_MAP = {
    "san diego": "FSD",
    "brucargo": "FBC",
    "ceva-idc": "IDC",
    "ceva idc": "IDC",
}

# FBC(BruCarGo-Candela)와 FBS(BruCarGo-Syneron)는 같은 물리적 창고(벨기에 Brucargo)라
# C.I 텍스트로는 구분이 안 되고 법인만 다르다(2026-07-09 확인). 그래서 텍스트 매칭이
# "FBC"로 나와도 그대로 믿지 말고 실적 파일 Delivery Number 대조로 반드시 재확인한다.
TEXT_AMBIGUOUS_ORGS = {"FBC"}

# 이 날짜 이전 메일은 (이미 수동 처리되었으므로) 절대 자동 처리하지 않음
LOOKBACK_START_DATE = datetime(2026, 7, 8)

# 2026-07-09: FBC+FBS 결합 건 지원용. C.I의 Delivery Number 박스에 "9912602+9911503"
# 처럼 두 Delivery Number가 +로 이어져 나오는 경우가 있음(한 CI가 두 조직 물량을
# 합쳐서 옴). 이때 어느 번호가 FBC고 어느 번호가 FBS인지는 C.I 자체로는 구분이
# 안 되므로, 수입신고실적 파일의 'Delivery Number' 컬럼에서 매칭해 'Ship From'
# (=오라클 Organization 코드, 이 파일에 이미 FBC/FBS/IDC/WAY/FSD로 들어있음)을
# 그대로 가져다 쓴다. 읽기 전용 조회만 한다.
DECL_EXCEL_PATH = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\10. 수입\수입신고실적(20260211)자동화.xlsx"
)
DECL_COL_DELIVERY = "Delivery Number"
DECL_COL_SHIP_FROM = "Ship From"
DECL_COL_SHIP_DATE = "본사선적일자"

# 2026-09-15 사용자 지적: 같은 수입면장에 같이 신고돼야 하는 delivery를 찾는
# 가장 정확하고 빠른 기준은 본사선적일자가 아니라 WayBill/Tracking Number
# (물리적 항공 화물 번호)다 - 같은 Waybill이면 같은 화물. Intransit → 실적 append
# 스크립트(auto_import_complete.py)가 이 값을 실적 파일의 'B/L번호' 컬럼에 통관
# 전부터 미리 심어두므로(2026-09-15 추가), 여기서는 별도 파일을 또 열지 않고
# 이미 로드해둔 실적 파일에서 그대로 읽는다. 다만 이 컬럼이 항상 채워지진
# 않아서(실측: 약 7% 공백 - Intransit 리포트 자체에 Waybill이 비어 오는 경우)
# 선적일자 매칭(find_same_ship_date_siblings)을 폴백으로 둔다.
DECL_COL_BL = "B/L번호"

# 2026-08-20 사용자 요청(안전장치): 인천관세법인에 C.I 회신을 보내는 것은 곧
# "이대로 통관 진행하라"는 승인이다. 그런데 그 shipment가 Intransit 리포트에 아직
# 안 떠서 실적 파일에 행이 없는 상태로 통관이 끝나버리면, 나중에 수입신고필증
# PDF를 파싱하는 pdf_auto_updater.py가 값을 채울 행을 못 찾는다 - 그 파일의 매칭
# 키는 (Delivery Number + 자재코드) 완전일치 하나뿐이고, Delivery가 안 맞으면
# 아무것도 안 채우고 조용히 넘어간다(사람도 자동화도 모르는 게 제일 위험한
# 실패 모드). 그래서 회신 전에 실적 파일 등재 여부를 먼저 확인한다.
#
# 실적 파일의 행은 Intransit 리포트가 append되면서 통관 '전'에 미리 깔린다.
# 2026-08-20 실측 근거(이 가드로 정상 건이 막히는 오탐이 없는지 확인한 것):
#  - 지금까지 자동 처리된 표준 건 22건(FSD/IDC/FBC/FBS)의 Delivery는 전부 실적
#    파일에 있었다 -> 표준 경로 오탐 0.
#  - 재배치(WAY) 2건도 Receive Delivery#가 전부 있었고, 본사선적일이 C.I 회신일보다
#    3~4일 앞선다: 9957493(선적 07-16 / 회신 07-20 / 신고 07-21),
#    9969286(선적 08-07 / 회신 08-10 / 신고 08-10). 즉 재배치도 회신 시점엔
#    Receive Delivery# 행이 이미 깔려 있는 게 정상 패턴 -> 표준 건과 같이 보류한다.
#    (원본 Delivery로 확인하면 안 된다 - 그 조회가 실패해야 재배치 분기로
#     들어오는 구조라 무조건 걸린다. screen_declaration_registered 설명 참고.)
# False로 바꾸면 확인을 아예 건너뛴다(문제 생기면 껐다 쓸 수 있게).
DECL_REGISTER_GUARD = True

_decl_df_cache: dict = {"df": None, "mtime": None}


def _load_declaration_df() -> pd.DataFrame:
    mtime = os.path.getmtime(DECL_EXCEL_PATH)
    if _decl_df_cache["df"] is not None and _decl_df_cache["mtime"] == mtime:
        return _decl_df_cache["df"]
    df = pd.read_excel(DECL_EXCEL_PATH, sheet_name=0, engine="openpyxl")
    df.columns = [str(c).strip() for c in df.columns]
    if DECL_COL_SHIP_FROM in df.columns:
        df[DECL_COL_SHIP_FROM] = df[DECL_COL_SHIP_FROM].ffill()
    _decl_df_cache.update(df=df, mtime=mtime)
    return df


def find_same_waybill_siblings(fbc_delivery_no: str) -> list[tuple[str, str]]:
    """2026-09-15 사용자 지적: 같은 수입면장에 같이 신고돼야 하는 delivery를 찾는
    가장 정확하고 빠른 기준은 본사선적일자(find_same_ship_date_siblings)가 아니라
    WayBill/Tracking Number다 - 실측 확인(DHL 5139580110 건): 9981113/9980017/
    9980022 세 delivery 전부 Intransit 리포트에서 WayBill/Tracking Number=
    "5139580110"으로 동일하게 찍혀 있었음(사용자가 "같은 Waybill인 것들은 같은
    수입면장에 신고돼야 한다"고 확인). 이 값은 auto_import_complete.py가 실적
    파일의 'B/L번호' 컬럼에 통관 전부터 미리 심어두므로 여기서 그대로 읽는다.
    이 컬럼이 항상 채워지는 건 아니라서(실측: 약 7%가 공백 - Intransit 리포트
    자체에 Waybill이 비어 오는 경우) 확정 실패 시 빈 리스트를 반환하고,
    호출부가 find_same_ship_date_siblings로 폴백한다."""
    try:
        df = _load_declaration_df()
    except PermissionError as e:
        raise DeclarationFileLocked(
            f"실적 파일이 열려 있어 조회 실패(B/L번호 매칭용, FBC delivery {fbc_delivery_no}): {e}")
    except Exception as e:
        log(f"[경고] 실적 파일 조회 실패(B/L번호 매칭용, FBC delivery {fbc_delivery_no}): {e}")
        return []
    needed = {DECL_COL_DELIVERY, DECL_COL_SHIP_FROM, DECL_COL_BL}
    if not needed <= set(df.columns):
        return []

    target = _normalize_num_str(fbc_delivery_no)
    col = df[DECL_COL_DELIVERY].apply(_normalize_num_str)
    own_rows = df[col == target]
    if own_rows.empty:
        return []
    bl_no = next(
        (str(v).strip() for v in own_rows[DECL_COL_BL] if pd.notna(v) and str(v).strip()),
        None,
    )
    if not bl_no:
        return []

    bl_col = df[DECL_COL_BL].astype(str).str.strip()
    sib_rows = df.loc[bl_col == bl_no, [DECL_COL_SHIP_FROM, DECL_COL_DELIVERY]].copy()
    sib_rows[DECL_COL_DELIVERY] = sib_rows[DECL_COL_DELIVERY].apply(_normalize_num_str)

    seen = set()
    pairs = []
    for org, delivery in sib_rows.itertuples(index=False):
        if not delivery or delivery == target or delivery in seen:
            continue
        seen.add(delivery)
        pairs.append((org, delivery))
    return pairs


def _normalize_num_str(v) -> str:
    """Delivery Number가 엑셀에서 숫자형(예: 9912602.0)으로 읽힐 수 있어 비교 전 정규화."""
    s = str(v).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def lookup_ship_from_by_delivery(delivery_no: str) -> str | None:
    """실적 파일의 Delivery Number 컬럼에서 정확히 일치하는 행을 찾아 그 행의
    Ship From(오라클 Organization 코드)을 반환. 매칭 실패 시 None(사람 확인 필요).
    2026-07-23 실측: 사용자가 실적 파일을 Excel에서 열어둔 순간과 겹치면
    PermissionError가 나는데, 이걸 그냥 "매칭 실패"로 삼켜버리면 실제로는
    데이터가 있는 건인데도 "Ship From 확정 불가"로 오판해 사람 확인 알림이
    나가버린다(DHL 1696566900 건에서 확인). 파일 잠김은 재시도하면 풀리는
    일시적 상황이므로 DeclarationFileLocked로 구분해서 위로 던진다."""
    try:
        df = _load_declaration_df()
    except PermissionError as e:
        raise DeclarationFileLocked(f"실적 파일이 열려 있어 조회 실패(Delivery {delivery_no}): {e}")
    except Exception as e:
        log(f"[경고] 실적 파일 조회 실패(Delivery {delivery_no}): {e}")
        return None
    if DECL_COL_DELIVERY not in df.columns or DECL_COL_SHIP_FROM not in df.columns:
        return None
    target = _normalize_num_str(delivery_no)
    col = df[DECL_COL_DELIVERY].apply(_normalize_num_str)
    matched = df[col == target]
    if matched.empty:
        return None
    val = matched.iloc[0][DECL_COL_SHIP_FROM]
    return str(val).strip() if pd.notna(val) else None


def find_same_ship_date_siblings(fbc_delivery_no: str) -> list[tuple[str, str]]:
    """2026-07-16 사용자 요청: FBC 단일 건인데 오라클 총액이 원본 C.I보다 작으면
    (가격 불일치), 실은 같은 물류 배치로 같이 온 품목(예: PPS Dongle 같은
    라이선스성 품목)이 별도 Delivery로 잡혀서 오라클 리포트에서 빠진 것일 수
    있다(실측 확인: DHL 5812115621 건, 차액이 정확히 그 FBS 품목 금액과 일치).
    SO/Delivery Number로 직접 매칭은 안 되는 경우가 있어서(그 품목의 SO/Delivery
    자체가 원본 CI 텍스트에서 다른 자릿수로 읽히는 등 신뢰 불가 - 실측 확인)
    대신 실적 파일의 '본사선적일자'(HQ 선적일)가 같은 건을 후보로 찾는다.
    FBC delivery_no의 선적일을 먼저 찾고, 그 날짜와 같은 행들의 (Ship From, Delivery
    Number)를 반환한다(중복 제거). 실적 파일에 아직 없으면(너무 이른 신규 건)
    빈 리스트를 반환 - 호출부가 원래 결과(단일 건 불일치)로 그대로 진행한다.

    2026-09-15 사용자 지적(DHL 5139580110 건): 원래는 Ship From=="FBS"인 행만
    후보로 찾았는데, 실제 형제 delivery(9980022)가 실적 파일에 "FBC"로 찍혀
    있어서 후보에서 누락됐다(367,084원 부족 상태로 자동 발송까지 나가버림).
    FBC/FBS는 같은 물리 창고라 라벨이 실제 조직과 다를 수 있다는 게 이미 알려진
    함정(TEXT_AMBIGUOUS_ORGS 참고) - 그래서 라벨로 거르지 않고 같은 선적일의
    FBC/FBS 행을 전부 후보로 반환하고, 각 후보가 실제 어느 조직인지는 그 행에
    찍힌 Ship From 값을 그대로 써서 오라클 조회 org_code로 넘긴다."""
    try:
        df = _load_declaration_df()
    except PermissionError as e:
        raise DeclarationFileLocked(
            f"실적 파일이 열려 있어 조회 실패(형제 delivery 매칭용, FBC delivery {fbc_delivery_no}): {e}")
    except Exception as e:
        log(f"[경고] 실적 파일 조회 실패(형제 delivery 매칭용, FBC delivery {fbc_delivery_no}): {e}")
        return []
    if not {DECL_COL_DELIVERY, DECL_COL_SHIP_FROM, DECL_COL_SHIP_DATE} <= set(df.columns):
        return []

    target = _normalize_num_str(fbc_delivery_no)
    col = df[DECL_COL_DELIVERY].apply(_normalize_num_str)
    fbc_rows = df[col == target]
    if fbc_rows.empty:
        return []
    ship_dates = pd.to_datetime(fbc_rows[DECL_COL_SHIP_DATE], errors="coerce").dropna()
    if ship_dates.empty:
        return []
    ship_date = ship_dates.iloc[0].date()

    all_dates = pd.to_datetime(df[DECL_COL_SHIP_DATE], errors="coerce").dt.date
    sib_mask = df[DECL_COL_SHIP_FROM].isin(["FBC", "FBS"]) & (all_dates == ship_date)
    sib_rows = df.loc[sib_mask, [DECL_COL_SHIP_FROM, DECL_COL_DELIVERY]].copy()
    sib_rows[DECL_COL_DELIVERY] = sib_rows[DECL_COL_DELIVERY].apply(_normalize_num_str)

    seen = set()
    pairs = []
    for org, delivery in sib_rows.itertuples(index=False):
        if not delivery or delivery == target or delivery in seen:
            continue
        seen.add(delivery)
        pairs.append((org, delivery))
    return pairs


def find_unregistered_deliveries(delivery_nos) -> list[str]:
    """실적 파일에 아직 행이 안 깔린 Delivery Number만 골라서 돌려준다.
    (2026-08-20 사용자 요청 안전장치 - DECL_REGISTER_GUARD 설명 참고)

    파일 잠김(PermissionError)은 "없다"가 아니라 "못 읽었다"이므로 미등재로
    오판해 멀쩡한 건을 막지 않도록 DeclarationFileLocked로 위에 던진다
    (2026-07-23 lookup_ship_from_by_delivery와 같은 방침)."""
    try:
        df = _load_declaration_df()
    except PermissionError as e:
        raise DeclarationFileLocked(f"실적 파일이 열려 있어 등재 확인 실패: {e}")
    except Exception as e:
        # 파일을 아예 못 읽으면 등재 여부를 판정할 수 없다. 여기서 '미등재'로
        # 단정하면 정상 건을 통째로 막게 되므로, 확인 불가로 보고 기존 동작
        # (그냥 진행)을 유지한다.
        log(f"[경고] 실적 파일 등재 확인 실패 - 이번 회차는 확인 없이 진행: {e}")
        return []
    if DECL_COL_DELIVERY not in df.columns:
        log(f"[경고] 실적 파일에 '{DECL_COL_DELIVERY}' 컬럼이 없어 등재 확인 생략")
        return []
    known = set(df[DECL_COL_DELIVERY].apply(_normalize_num_str))
    return [d for d in delivery_nos if _normalize_num_str(d) not in known]


def screen_declaration_registered(cases: list) -> list:
    """C.I 회신(= 인천관세법인에 통관 진행 승인) 전에, 각 건의 Delivery Number가
    실적 파일에 이미 깔려 있는지 확인해서 통과한 case만 돌려준다.

    - standard(FBC/FBS/IDC/FSD): 미등재면 이번 회차 보류 + 알림. state에 안 남기니
      Intransit가 들어온 뒤 다음 스케줄 실행에서 자동으로 이어서 처리된다
      (추출 결과는 _awb_extract_cache.json에 있어 OCR을 다시 하지도 않음).
    - way_rebalance(일본/중국/홍콩발 재고 재배치): 표준 건과 똑같이 보류한다.
      단 확인하는 번호가 다르다 - 원본 Delivery는 실적 파일에 없는 게 정상이고
      (애초에 그 조회가 실패해야 재배치 분기로 들어온다, build_fedex_case의
      resolve_ship_from_org 흐름 참고) 실적 파일에 들어오는 건 SharePoint에서
      찾은 Receive Delivery#다. org_delivery_pairs에 이미 Receive Delivery#가
      들어있으므로 여기서는 표준 건과 같은 코드로 확인된다.
    """
    if not cases or not DECL_REGISTER_GUARD:
        return cases

    all_nos = [d for c in cases for _, d in c["org_delivery_pairs"]]
    try:
        missing = set(find_unregistered_deliveries(all_nos))
    except DeclarationFileLocked as e:
        # 등재 여부를 확정 못 한 상태로 통관을 진행시키면 안전장치가 무의미하다.
        # 파일 잠김은 재시도하면 풀리므로 이번 회차만 전체 보류한다(알림 없음 -
        # 사용자가 엑셀을 닫으면 다음 회차에 그냥 처리됨).
        log(f"[스킵] {e} -> 이번 회차는 등재 확인을 못 해 전체 보류(다음 스케줄에서 재시도)")
        return []

    if not missing:
        log(f"[등재확인] {len(cases)}건 모두 실적 파일에 Delivery 행 있음 - 진행")
        return cases

    kept = []
    for case in cases:
        case_missing = [d for _, d in case["org_delivery_pairs"] if d in missing]
        if not case_missing:
            kept.append(case)
            continue

        nos = ", ".join(case_missing)
        is_rebalance = case.get("kind") == "way_rebalance"
        what = "Receive Delivery#" if is_rebalance else "Delivery"

        log(f"[보류] {case['label']}: {what} {nos}가 실적 파일에 아직 없음(Intransit 미반영) "
            f"-> 통관 회신 보류, 다음 회차에 재확인")
        send_alert(
            f"[Intransit 미반영 - 통관 보류] {case['label']}",
            f"이 건의 {what} {nos}가 수입신고실적 파일에 아직 없습니다.\n"
            f"= Intransit 리포트에 아직 안 뜬 shipment라는 뜻입니다.\n"
            + (f"(재고 재배치 건이라 원본 Delivery가 아니라 SharePoint에서 찾은 "
               f"Receive Delivery# 기준으로 확인했습니다.)\n" if is_rebalance else "")
            + f"\n"
            f"이 상태로 통관을 진행하면, 나중에 수입신고필증을 파싱할 때 채워 넣을 행이"
            f" 없어서 실적이 조용히 비게 됩니다(pdf_auto_updater는 Delivery Number가"
            f" 정확히 일치하는 행에만 값을 채웁니다).\n\n"
            f"그래서 인천관세법인 회신을 보류했습니다. Intransit에 반영되면 다음 실행"
            f"(20분 주기)에서 자동으로 회신됩니다.\n"
            f"급하면 Intransit 반영 상태를 먼저 확인하신 뒤 직접 회신해주세요.",
            dedup_key=f"{case['entry_id']}:not_in_declaration",
        )

    return kept


def resolve_ship_from_org(text_org: str | None, delivery_no: str | None) -> str | None:
    """C.I 텍스트에서 뽑은 Ship From 조직을 확정한다. FBC는 FBS와 물리적으로 같은
    장소(Brucargo)라 텍스트만으로는 구분이 안 되므로(TEXT_AMBIGUOUS_ORGS) 반드시
    실적 파일 Delivery Number 대조로 재확인한다. 그 외 조직은 텍스트 매칭을 그대로
    쓴다. 텍스트 매칭이 없거나(None) 대조까지 실패하면 확정 실패로 None을 반환
    (호출부가 사람 확인 알림으로 처리해야 함)."""
    if text_org is not None and text_org not in TEXT_AMBIGUOUS_ORGS:
        return text_org
    if not delivery_no:
        return None
    return lookup_ship_from_by_delivery(delivery_no)


# ==============================================================
# 일본/중국/홍콩발 재고 재배치(Rebalance) 자동 처리 (2026-07-20)
# ==============================================================
# 일본(JPP)/중국(CHP)/홍콩(ILH)에서 오는 재고 재배치 건은 아직 수입신고 전이라
# 실적 파일에 Delivery Number가 없고, C.I 텍스트에도 본사(미국) 주소만 나와서
# resolve_ship_from_org()가 확정을 못한다(text_org=None, 실적파일 매칭도 실패).
# 지금까지는 사람이 직접 SharePoint 'APAC Stock Movements' 리스트에서 해당
# Delivery#의 'Receive Delivery#'를 찾아 오라클 Org="WAY"로 CI를 새로 뽑고
# Ship From 칸을 국가별 주소로 수기 수정해서 보냈다(사용자 확인, 2026-07-20).
SHAREPOINT_STOCK_MOVEMENTS_URL = (
    "https://syneron.sharepoint.com/sites/APACOperation/Lists/"
    "APAC%20Stock%20Movements/AllItems.aspx"
)
# 2026-09-18 사용자 요청: WAY 재배치 건은 CI를 뽑기 전에 APAC Stock Movements
# 리스트에서 Receive Delivery#를 확인하는 김에 'Receive TO#'(및 원본 'TO#')도
# 같이 확인해서, 용마(창고)에 입고 안내 메일 초안을 만든다. 실제 오라클 Receive
# 처리는 여기서 하지 않는다(창고/담당자 액션) - 안내 메일만 초안으로 저장.
YONGMA_MAIL_TO = "김기훈 <y7221063@yongmalogis.co.kr>; 용호 유 <y7225055@yongmalogis.co.kr>"
# 2026-09-16 사용자 설명으로 확장: 이 WAY 오탐(Ship From이 실제 출발국과 무관하게
# 무조건 WAY로 찍히는 현상)은 CHP/JPP/ILH만의 문제가 아니라 "오라클에서 rebalance는
# 어느 나라든 항상 중간에 WAY를 거쳤다가 최종 국가로 간다"는 구조 자체의 문제다 -
# AUP(호주)/FBC/FBS(스페인)발 rebalance도 똑같이 겪는다(사용자 확인). 그동안
# CHP/JPP/ILH만 지원 대상이라 AUP/FBC/FBS발 rebalance 건은 이 판별을 아예 못
# 타고 "정보 부족(사람 확인 필요)"으로 빠졌었다(SharePoint APAC Stock Movements에
# 없으면 = 진짜 WAY발이 맞다는 뜻이므로, 그 리스트에 있으면서 From이 이 값들 중
# 하나인 경우가 전부 대상). FBS는 참고 엑셀에 전용 시트가 없고 FBC와 같은 물리
# 창고([[TEXT_AMBIGUOUS_ORGS]] 참고)라 주소 조회 시 FBC 시트로 매핑한다.
# 이 자동화가 지원하는 From 조직 코드 = Rebalance Invoice 참고 엑셀의 시트명과 동일
WAY_REBALANCE_COUNTRY_SHEETS = {"CHP", "JPP", "ILH", "AUP", "FBC", "FBS"}
# 참고 엑셀(REBALANCE_INVOICE_XLSX_PATH)에는 FBS 전용 시트가 없다 - FBC와 같은
# 주소를 쓴다(2026-09-16).
WAY_REBALANCE_ADDRESS_SHEET_MAP = {"FBS": "FBC"}
REBALANCE_INVOICE_XLSX_PATH = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\10. 수입\Rebalance Invoice form_Ship to Korea.xlsx"
)

# --- SharePoint 조회 대기/재시도 (2026-08-10) ---
SP_NAV_ATTEMPTS = 3          # 페이지 재이동 횟수(1회차가 SSO 리다이렉트 워밍업 역할)
SP_ROW_WAIT_SEC = 45         # 한 번 이동한 뒤 행이 그려지길 기다리는 시간
SP_POLL_SEC = 1.0
SP_STABLE_POLLS = 4          # 화면 텍스트가 이만큼 연속 그대로면 '렌더 끝'으로 본다
SP_MIN_RENDERED_CHARS = 400  # 로딩 중 빈 화면을 '렌더 끝'으로 오판하지 않기 위한 하한


class SharePointLookupUndetermined(RuntimeError):
    """SharePoint 조회를 '있다/없다'로 확정하지 못했다는 뜻.
    '없다'(정상 판정)와 반드시 구분해야 한다 - 호출부는 이 예외를 받으면
    이번 회차를 건너뛰고 다음 실행에서 다시 시도한다."""


def _sp_body_text(driver) -> str:
    try:
        return driver.execute_script("return document.body.innerText;") or ""
    except Exception:
        return ""


def _sp_on_login_page(driver) -> bool:
    """SharePoint 대신 마이크로소프트 로그인 화면에 있는지 확인한다."""
    try:
        url = (driver.current_url or "").lower()
    except Exception:
        return False
    return ("login.microsoftonline.com" in url
            or "login.live.com" in url
            or "/_forms/default.aspx" in url)


def _sp_find_row(text: str, delivery_no: str):
    """화면 텍스트에서 delivery_no '행'의 줄 위치를 찾는다. 반환 (lines, pos) 또는 None.
    줄 전체가 정확히 delivery_no인 것만 행으로 인정한다 - 검색 결과 안내 문구처럼
    번호가 문장 속에 섞여 나오는 자리를 행으로 오인하면 앞뒤 컬럼을 엉뚱하게
    읽게 된다(예전엔 find()로 첫 등장 위치를 잡아 ±300자만 잘라 썼다)."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    try:
        return lines, lines.index(delivery_no)
    except ValueError:
        return None


def _sp_goto(driver, url: str) -> None:
    """SharePoint 페이지로 이동한다. 완전 로드까지 못 기다려도 실패로 보지 않고,
    로딩만 멈춘 뒤(window.stop) 지금까지 그려진 화면을 그대로 쓴다.
    driver.get()은 '완전 로드'까지 블로킹하는데, SharePoint 모던 리스트는 표가
    다 그려진 뒤에도 잔여 리소스가 한참 남아서 그 차이만으로 실패하곤 했다."""
    from selenium.common.exceptions import TimeoutException
    try:
        driver.get(url)
    except TimeoutException:
        log(f"[정보] SharePoint 페이지 로드가 {PAGE_LOAD_TIMEOUT_SEC}초를 넘김 "
            f"- 로딩을 중단하고 현재 화면으로 계속 진행")
        try:
            driver.execute_script("window.stop();")
        except Exception:
            pass


def _sp_wait_for_row(driver, delivery_no: str):
    """delivery_no 행이 화면에 나타날 때까지 폴링한다.
    반환: (판정, 화면텍스트), 판정 = "found" | "absent" | "login" | "timeout"

    고정 sleep(6초)를 폴링으로 바꾼 이유(2026-08-10): 6초는 SharePoint가 느린
    날 표가 그려지기 전에 화면을 읽어버려서, 실제로는 존재하는 행을 '없음'으로
    보고하는 조용한 오탐이 된다(쉽컨펌 'shipment 0건' 오탐과 같은 종류 -
    없다고 잘못 말하는 쪽이 에러로 죽는 쪽보다 위험하다).
    그래서 '없음'이라고 결론 내리려면 화면이 실제로 다 그려졌다는 근거를
    요구한다 - 텍스트가 SP_STABLE_POLLS회 연속 그대로일 때만 'absent'로 본다."""
    deadline = time.time() + SP_ROW_WAIT_SEC
    prev_text = None
    stable = 0
    text = ""
    while time.time() < deadline:
        if _sp_on_login_page(driver):
            return "login", ""
        text = _sp_body_text(driver)
        if _sp_find_row(text, delivery_no) is not None:
            return "found", text
        if text == prev_text and len(text) >= SP_MIN_RENDERED_CHARS:
            stable += 1
            if stable >= SP_STABLE_POLLS:
                return "absent", text
        else:
            stable = 0
            prev_text = text
        time.sleep(SP_POLL_SEC)
    return "timeout", text


def lookup_receive_delivery_via_sharepoint_legacy(driver, delivery_no: str) -> dict | None:
    """(2026-09-14: REST API 버전으로 대체돼 더 이상 호출되지 않음 - 화면 스크래핑
    방식이 문제 생겼을 때 참고/롤백용으로만 보존. 새 구현은 바로 아래
    lookup_receive_delivery_via_sharepoint() 참고.)
    SharePoint 'APAC Stock Movements' 리스트에서 delivery_no(C.I의 Delivery Number,
    아직 실적 파일엔 없는 상태)에 대응하는 행을 찾아 From 조직 코드와 Receive
    Delivery#를 반환한다. 최신 SharePoint 리스트 UI는 셀 단위로 깔끔한 셀렉터가
    없어(실측 확인) 검색창으로 좁힌 뒤 화면 전체 텍스트(innerText)를 줄 단위로
    쪼개 delivery_no의 위치를 기준으로 앞뒤 컬럼 값을 읽는다. 컬럼 순서는 고정
    (...From, To, TO#, Delivery#, Receive TO#, Receive Delivery#, Oracle Receipt#...)
    이라 delivery_no 기준 -3=From, +1=Receive TO#, +2=Receive Delivery# (2026-07-20
    실측: Delivery 9957464 행에서 From=CHP, Receive Delivery#=9957493로 확인,
    Oracle에서 실제 조회해 원본 C.I 총액과 일치함을 검증함).
    매칭 실패/지원 밖 From이면 None (호출부가 기존 "사람 확인 필요" 흐름으로 넘어감).
    2026-07-20 실측: 검색창을 클릭해서 타이핑하는 방식은 이 자동화 전용 Edge
    창이 (듀얼 모니터 배치 등으로) document.visibilityState='hidden' 상태일 때
    element not interactable로 계속 실패했다(탭이 열려는 있지만 브라우저가
    "안 보이는 탭"으로 취급 - 대기 시간을 늘려도 해결 안 됨). URL에 쿼리
    파라미터(?q=delivery_no)를 붙여 바로 이동하면 이 문제를 완전히 피하면서도
    같은 결과 화면을 얻을 수 있어 이 방식으로 통일.

    2026-08-10 개편: 예전엔 `driver.get()` 한 번 -> `sleep(6)` -> 화면 읽기의
    한 방 승부라, 화면이 조금만 느려도 그대로 실패했다(실측: AWB 875444946121,
    콜드 Edge에서 SSO 리다이렉트까지 겹쳐 페이지 로드가 2분을 넘김).
    실패를 줄이기 위해 세 가지를 바꾼다:
      (1) 페이지 로드 타임아웃을 '실패'로 보지 않는다. SharePoint 모던 리스트는
          표가 다 그려진 뒤에도 잔여 리소스 로딩이 길게 남아서, 타임아웃 시점엔
          이미 찾으려던 행이 화면에 떠 있는 경우가 많다 -> 로딩만 멈추고
          (window.stop) 현재 화면을 그대로 읽는다.
      (2) 고정 sleep 대신 행이 나타날 때까지 폴링한다(_sp_wait_for_row).
      (3) 최대 SP_NAV_ATTEMPTS회 재이동한다. 1회차가 SSO 리다이렉트를 흡수해
          쿠키를 받아두면 2회차는 대체로 즉시 뜨므로, 재시도가 곧 워밍업이다.
    끝내 판정을 못 하면 None(=재배치 건 아님)이 아니라 예외를 올린다 -
    호출부가 이 메일을 '정보 부족(사람 확인 필요)'으로 확정지어 버리면 실제
    재배치 건이 영영 재시도되지 않기 때문이다(그 알림은 dedup_ttl=무한)."""
    url = f"{SHAREPOINT_STOCK_MOVEMENTS_URL}?q={delivery_no}"
    verdict, body_text = "timeout", ""
    for attempt in range(SP_NAV_ATTEMPTS):
        _sp_goto(driver, url)
        verdict, body_text = _sp_wait_for_row(driver, delivery_no)
        if verdict in ("found", "absent"):
            break
        if attempt == SP_NAV_ATTEMPTS - 1:
            break
        if verdict == "login":
            log(f"[정보] SharePoint가 로그인 화면으로 넘어감(delivery={delivery_no}) "
                f"- 계정 타일 클릭 후 재시도 {attempt + 2}/{SP_NAV_ATTEMPTS}")
            try:
                driver.execute_script(_JS_CLICK_VISIBLE_TEXT, SSO_ACCOUNT_EMAIL)
            except Exception:
                pass
            time.sleep(5)
        else:
            log(f"[정보] SharePoint 화면이 아직 안 그려짐(delivery={delivery_no}) "
                f"- 재시도 {attempt + 2}/{SP_NAV_ATTEMPTS}")

    if verdict == "login":
        raise SharePointLookupUndetermined(
            f"SharePoint 로그인 화면에서 못 빠져나옴(delivery={delivery_no})")
    if verdict == "timeout":
        raise SharePointLookupUndetermined(
            f"SharePoint 화면이 {SP_ROW_WAIT_SEC}초 안에 안 그려짐"
            f"(delivery={delivery_no})")
    if verdict == "absent":
        # 2026-08-28 사용자 지적: 실물 운송장(메일)이 SharePoint 'APAC Stock
        # Movements' 리스트 반영보다 먼저 도착하는 경우가 실제로 있다 - 여기서
        # None을 반환하면(=재배치 건 아님으로 확정) 호출부가 "정보 부족(사람
        # 확인 필요)"으로 못박아버려서 리스트에 나중에 올라와도 다시는 재확인
        # 안 됨(진짜 재배치 건을 영영 놓침). login/timeout과 마찬가지로 "아직
        # 판정 불가"로 예외를 올려 다음 자동 실행(20분 주기)에서 계속 재확인되게 한다.
        raise SharePointLookupUndetermined(
            f"SharePoint 'APAC Stock Movements'에 아직 등록 안 됨(실물 도착이 "
            f"시스템 반영보다 빠를 수 있음) - 다음 자동 실행에서 재확인(delivery={delivery_no})")

    found = _sp_find_row(body_text, delivery_no)
    if found is None:
        # _sp_wait_for_row가 "found"를 준 직후라 여기 올 일은 없지만, 화면이
        # 그 사이 다시 그려진 경우를 대비해 '판정 보류'로 안전하게 처리한다.
        raise SharePointLookupUndetermined(
            f"SharePoint 텍스트 파싱 실패(delivery={delivery_no})")
    lines, pos = found

    from_org = lines[pos - 3] if pos - 3 >= 0 else None
    receive_delivery = lines[pos + 2] if pos + 2 < len(lines) else None

    if from_org not in WAY_REBALANCE_COUNTRY_SHEETS:
        log(f"[정보] SharePoint 매칭됐지만 From={from_org}는 지원 대상"
            f"({sorted(WAY_REBALANCE_COUNTRY_SHEETS)}) 아님 (delivery={delivery_no})")
        return None
    if not receive_delivery or not receive_delivery.isdigit():
        log(f"[경고] SharePoint에서 Receive Delivery#를 못 읽음 (delivery={delivery_no}, "
            f"주변값={lines[max(0, pos-1):pos+4]})")
        return None

    log(f"[SharePoint] Delivery {delivery_no} -> From={from_org}, Receive Delivery#={receive_delivery}")
    return {"from_org": from_org, "receive_delivery_no": receive_delivery}


# 2026-09-14: 화면 스크래핑(_sp_goto/_sp_wait_for_row/텍스트 위치 추측) 대신
# SharePoint REST API를 직접 호출한다. 이미 로그인된 브라우저 탭에서 fetch()를
# 실행하면 세션 쿠키가 그대로 실려서 별도 인증이 필요 없다(실측 확인: 2026-09-14
# APAC Stock Movements 리스트에 항목 생성 자동화 작업 중 같은 방식으로 조회 성공).
# DeliveryNumber/ReceiveDelivery_x0023_는 SharePoint 내부적으로 숫자(Number) 필드라
# OData 필터에 따옴표 없이 숫자로 넘겨야 한다(실측: 문자열로 감싸면 0건 매칭).
SHAREPOINT_API_ITEMS_URL = (
    "https://syneron.sharepoint.com/sites/APACOperation/_api/web/"
    "lists/getbytitle('APAC%20Stock%20Movements')/items"
)

_JS_FETCH_JSON = """
var callback = arguments[arguments.length - 1];
var url = arguments[0];
fetch(url, {headers: {Accept: 'application/json;odata=nometadata'}, credentials: 'same-origin'})
  .then(r => r.text().then(t => callback(JSON.stringify({status: r.status, body: t}))))
  .catch(e => callback(JSON.stringify({error: String(e)})));
"""


def lookup_receive_delivery_via_sharepoint(driver, delivery_no: str) -> dict | None:
    """SharePoint 'APAC Stock Movements' 리스트에서 delivery_no에 대응하는 행을
    REST API로 조회해 From 조직 코드와 Receive Delivery#를 반환한다.
    (2026-09-14: 기존 화면 스크래핑 버전은 lookup_receive_delivery_via_sharepoint_legacy로
    이름만 바꿔 그대로 보존 - 문제 생기면 이 함수 이름을 legacy로, legacy를
    이 이름으로 맞바꾸기만 하면 즉시 롤백된다.)

    반환 계약은 legacy와 동일하게 유지한다(호출부 detect_way_rebalance는 무수정):
      - 매칭됐지만 From이 지원 대상(CHP/JPP/ILH) 밖이거나 Receive Delivery#를
        못 읽으면 None (호출부가 "사람 확인 필요" 흐름으로 넘어감)
      - 조회 자체가 안 끝났거나(로그인 세션 끊김 등) 아직 리스트에 없으면
        SharePointLookupUndetermined 예외 (호출부가 다음 자동 실행에서 재확인)

    REST 쿼리는 응답이 오는 즉시 결과가 확정되므로(화면 렌더링을 기다릴 필요가
    없음) legacy에 있던 폴링/재시도/'화면이 안정될 때까지 대기' 로직이 통째로
    필요 없다 - 0건이면 그 자체로 확정된 "아직 없음"이다."""
    try:
        delivery_num = int(delivery_no)
    except (TypeError, ValueError):
        raise SharePointLookupUndetermined(f"delivery_no가 숫자가 아님: {delivery_no!r}")

    # 2026-09-17 버그 수정: 이 함수는 Phase A의 "가벼운 탭"(_open_plain_tab, 새로
    # 열린 빈 탭)에서 호출되는데, fetch()의 credentials:'same-origin'은 탭이
    # 이미 sharepoint.com 오리진에 있어야 세션 쿠키를 실어 보낸다. 탭이 빈 페이지인
    # 채로 바로 fetch부터 하면 쿠키 없이 나가서 로그인 세션이 멀쩡해도 매번 401이
    # 난다(실측: 로그인 상태에서도 재현됨 - 세션 만료가 원인이 아니었음). 먼저
    # 이 오리진으로 이동해야 한다.
    if "sharepoint.com" not in (driver.current_url or ""):
        driver.get(SHAREPOINT_STOCK_MOVEMENTS_URL)
        time.sleep(4)

    url = (f"{SHAREPOINT_API_ITEMS_URL}?$select=From,ReceiveDelivery_x0023_"
           f"&$filter=DeliveryNumber%20eq%20{delivery_num}")

    try:
        raw = driver.execute_async_script(_JS_FETCH_JSON, url)
        outer = json.loads(raw)
    except Exception as e:
        # 브라우저/네트워크 문제로 요청 자체가 안 끝난 경우 - legacy의 login/
        # timeout과 같은 취급으로 "판정 보류" 처리해 다음 자동 실행에서 재확인.
        raise SharePointLookupUndetermined(
            f"SharePoint API 호출 실패(delivery={delivery_no}): {e}")

    if "error" in outer:
        raise SharePointLookupUndetermined(
            f"SharePoint API 네트워크 에러(delivery={delivery_no}): {outer['error']}")
    if outer.get("status") != 200:
        # 401/403 등은 로그인 세션이 끊겼다는 뜻(legacy의 로그인 화면 리다이렉트와
        # 같은 상황) - 판정 보류로 처리한다.
        raise SharePointLookupUndetermined(
            f"SharePoint API가 {outer.get('status')} 응답(delivery={delivery_no}): "
            f"{outer.get('body', '')[:200]}")

    try:
        items = json.loads(outer["body"]).get("value", [])
    except Exception as e:
        raise SharePointLookupUndetermined(
            f"SharePoint API 응답 형식 이상(delivery={delivery_no}): {e}")

    if not items:
        # 2026-08-28 legacy와 동일한 이유(실물 도착이 시스템 반영보다 빠를 수
        # 있음): None(=재배치 건 아님 확정)이 아니라 예외로 재시도 대상에 남긴다.
        raise SharePointLookupUndetermined(
            f"SharePoint 'APAC Stock Movements'에 아직 등록 안 됨(delivery={delivery_no})")

    from_org = items[0].get("From")
    receive_delivery_raw = items[0].get("ReceiveDelivery_x0023_")
    receive_delivery = str(int(receive_delivery_raw)) if receive_delivery_raw is not None else None

    if from_org not in WAY_REBALANCE_COUNTRY_SHEETS:
        log(f"[정보] SharePoint 매칭됐지만 From={from_org}는 지원 대상"
            f"({sorted(WAY_REBALANCE_COUNTRY_SHEETS)}) 아님 (delivery={delivery_no})")
        return None
    if not receive_delivery:
        log(f"[경고] SharePoint에서 Receive Delivery#를 못 읽음 (delivery={delivery_no})")
        return None

    log(f"[SharePoint] Delivery {delivery_no} -> From={from_org}, Receive Delivery#={receive_delivery}")
    return {"from_org": from_org, "receive_delivery_no": receive_delivery}


def lookup_receive_to_no_via_sharepoint(driver, delivery_no: str) -> dict:
    """2026-09-18 추가: 'APAC Stock Movements' 리스트에서 원본 'TO#'와 'Receive
    TO#'를 조회한다(용마 입고 안내 메일에만 쓰는 참고 정보). 내부 필드명은 실측
    확인된 'Receive Delivery#' -> 'ReceiveDelivery_x0023_' 규칙(공백 제거, #은
    _x0023_)을 그대로 적용해 'TO#' -> 'TO_x0023_', 'Receive TO#' ->
    'ReceiveTO_x0023_'로 추정한 것이라 아직 라이브로 검증되지 않았다. 이 조회는
    본 자동화의 핵심 경로(WAY 판별/오라클 CI 발송)와 완전히 분리된 부가 정보라
    실패해도 예외를 올리지 않고 None을 반환한다 - 잘못된 필드명으로 REST 호출
    자체가 400 나더라도 lookup_receive_delivery_via_sharepoint의 기존 동작에는
    영향이 없다."""
    try:
        delivery_num = int(delivery_no)
        url = (f"{SHAREPOINT_API_ITEMS_URL}?$select=TO_x0023_,ReceiveTO_x0023_"
               f"&$filter=DeliveryNumber%20eq%20{delivery_num}")
        raw = driver.execute_async_script(_JS_FETCH_JSON, url)
        outer = json.loads(raw)
        if outer.get("status") != 200:
            raise RuntimeError(f"status={outer.get('status')}: {outer.get('body', '')[:200]}")
        items = json.loads(outer["body"]).get("value", [])
        if not items:
            return {"to_no": None, "receive_to_no": None}
        row = items[0]
        to_raw = row.get("TO_x0023_")
        receive_to_raw = row.get("ReceiveTO_x0023_")
        to_no = str(int(to_raw)) if to_raw is not None else None
        receive_to_no = str(int(receive_to_raw)) if receive_to_raw is not None else None
        return {"to_no": to_no, "receive_to_no": receive_to_no}
    except Exception as e:
        log(f"[정보] TO#/Receive TO# 조회 실패(용마 안내메일 참고용, 필수 아님, "
            f"delivery={delivery_no}): {e}")
        return {"to_no": None, "receive_to_no": None}


def get_ship_from_address_lines(org_code: str) -> list[str] | None:
    """일본(JPP)/중국(CHP)/홍콩(ILH) Ship From 주소를 참고 엑셀(시트명=오라클
    Organization 코드)의 G10:G18 셀에서 그대로 읽어온다(2026-07-20 실측: 어느
    시트든 이 범위에 주소가 줄 단위로 들어있음 - 빈 셀은 건너뛰고, ILH 시트의
    G13처럼 숫자 하나만 있는 줄도 원본 그대로 사용한다).

    G10:G18에는 실주소 뒤에 담당자 연락처(이름/전화/이메일) 3줄이 더 붙어있는데
    (CHP/JPP는 6줄 주소+3줄 연락처, ILH는 우편번호 줄이 없어 5줄 주소+3줄 연락처로
    위치가 한 칸씩 다름) Ship From 칸에는 필요 없고, PDF 패치 시 9줄을 다 욱여넣느라
    폰트가 5.0까지 줄어들어 지저분하게 보이는 원인이었다(2026-07-20 사용자 피드백).
    시트마다 줄 수가 달라 고정 행 범위로는 못 자르므로, 끝에서부터
    이메일(@ 포함) -> 전화번호(숫자/공백/괄호/+/- 만) -> 담당자 이름(숫자 없는
    1~2단어) 패턴을 순서대로 확인해 맞는 만큼만 제외한다."""
    import openpyxl

    sheet_name = WAY_REBALANCE_ADDRESS_SHEET_MAP.get(org_code, org_code)
    try:
        wb = openpyxl.load_workbook(REBALANCE_INVOICE_XLSX_PATH, data_only=True, read_only=True)
    except Exception as e:
        log(f"[경고] Rebalance Invoice 참고 파일 조회 실패: {e}")
        return None
    if sheet_name not in wb.sheetnames:
        return None
    ws = wb[sheet_name]
    lines = []
    for row in range(10, 19):
        v = ws.cell(row=row, column=7).value  # G열
        if v is not None and str(v).strip() != "":
            lines.append(str(v).strip())
    if not lines:
        return None

    # 2026-07-20 사용자 확인: 참고 엑셀 CHP 시트 G10 셀 자체에 "Bejing" 오타가
    # 있어(바로 다음 줄 도시명은 정상적으로 "Beijing") 패치된 CI에 철자가
    # 뒤섞여 나갔다. 원본 엑셀은 다른 용도로도 쓰는 공유 참고 파일이라 여기서는
    # 건드리지 않고, 우리가 뽑아 쓰는 시점에만 교정한다.
    lines = [re.sub(r"\bBejing\b", "Beijing", ln) for ln in lines]

    if "@" in lines[-1]:
        trimmed = lines[:-1]
        if trimmed and re.sub(r"[\d\s()+\-]", "", trimmed[-1]) == "":
            trimmed = trimmed[:-1]
            if trimmed and len(trimmed[-1].split()) <= 2 and not any(c.isdigit() for c in trimmed[-1]):
                trimmed = trimmed[:-1]
        lines = trimmed

    return lines or None


def patch_ship_from_in_pdf(pdf_path: str, address_lines: list[str]) -> str:
    """오라클이 생성한 Commercial Invoice PDF의 SHIP FROM 칸(항상 미국 본사 주소로
    나옴)을 실제 발송국(중국/일본/홍콩) 주소로 바꿔치기한다. "SHIP FROM" 라벨
    (y≈158.7-171.1)은 건드리지 않고 그 아래 주소 영역만 리댁션 후 새 텍스트를
    삽입한다.
    2026-07-20 사용자 피드백: 기존 rect(221,172,379,280)는 실제 표 테두리보다
    커서(get_drawings()로 확인: 이 블록의 실제 하단 테두리는 y=276.25-276.75,
    SHIP FROM|SHIP TO 세로 구분선은 x=378.8-379.3) 리댁션이 그 테두리 선까지
    흰색으로 지워버려 SHIP FROM 칸 밑줄만 끊겨 보이는 문제가 있었다. 1차로
    y1=276.0까지만 줄였을 때도 픽셀 단위로 보면 선 두께(0.5pt) 중 위쪽 절반이
    여전히 지워져 있었다(육안으로는 이어져 보이지만 다른 칸보다 얇아져서
    회색으로 보임 - 사용자가 재차 지적). 실제 선 시작(y=276.246)보다 확실히
    위(y=275.5)에서 끊어 여유를 두고, 세로 구분선(x=378.8~)도 마찬가지로
    x=378.5에서 끊는다.
    같은 이유로 폰트도 문서 본문 전체가 쓰는 Helvetica 9.0pt에 최대한 맞추도록
    9.0부터 시도해서 안 맞으면 단계적으로 줄인다(기존엔 7.5부터 시작해 다른
    칸(9.0pt)보다 눈에 띄게 작아 보였음).
    글자가 넘치면(insert_textbox 반환값<0) 리댁션을 다시 적용해 흰색으로 지운 뒤
    더 작은 폰트로 재시도한다(리댁션 없이 재삽입하면 이전 텍스트와 겹쳐 보임)."""
    import fitz

    rect = fitz.Rect(221, 172, 378.5, 275.5)
    text = "\n".join(address_lines)

    doc = fitz.open(pdf_path)
    page = doc[0]
    ret = -1
    for fontsize in (9.0, 8.5, 8.0, 7.5, 7.0, 6.5, 6.0, 5.5, 5.0):
        page.add_redact_annot(rect, fill=(1, 1, 1))
        page.apply_redactions()
        ret = page.insert_textbox(rect, text, fontsize=fontsize, fontname="helv",
                                   color=(0, 0, 0), align=0)
        if ret >= 0:
            break
    if ret < 0:
        log(f"[경고] Ship From 주소가 가장 작은 폰트(5.0)로도 칸에 안 들어감"
            f"(overflow={ret}): {pdf_path}")

    patched_path = pdf_path[:-4] + "_shipfrom_patched.pdf"
    doc.save(patched_path)
    doc.close()
    return patched_path


def detect_way_rebalance(driver, entry_id: str, label: str, delivery_no: str):
    """SharePoint 'APAC Stock Movements' 대조로 일본/중국/홍콩발 재고 재배치
    건인지 판별한다. 맞으면 {"from_org", "receive_delivery_no", "address_lines"}를
    반환하고(오라클 제출/대기는 여기서 하지 않음 - main()의 제출/폴링 단계에서
    처리), 해당 없음/매칭 실패면 None(호출부가 기존 "사람 확인 필요" 흐름으로
    넘어감). 조회 자체가 실패하면(브라우저 문제 등) "ERROR"를 반환한다 - 이미
    로그/알림을 처리했다는 뜻이므로 호출부는 이 메일을 조용히 스킵하면 된다.
    2026-08-03: 예전엔 이 판별 직후 바로 오라클 Org="WAY" 리포트를 제출하고
    완료까지 대기(run_oracle_ci_report)했는데, 그러면 메일을 하나씩 순서대로
    "판별->제출->완료대기->다음 메일" 처리하게 되어 뒤에 있는 멀쩡한 건들까지
    덩달아 밀렸다. 판별(SharePoint/주소 조회, 빠름)과 오라클 제출+대기(느릴 수
    있음)를 분리해서, 여러 건의 제출을 먼저 다 해두고 완료 확인만 라운드로빈으로
    돌게 재구성했다(main() 참고)."""
    try:
        match = lookup_receive_delivery_via_sharepoint(driver, delivery_no)
    except SharePointLookupUndetermined as e:
        # 2026-08-28: 로그인 화면/타임아웃뿐 아니라 "아직 리스트에 안 올라옴"도
        # 여기로 들어온다 - 실제 에러가 아니라 대부분 정상적으로 시간이 지나면
        # 풀리는 상태라 사용자에게는 "에러"가 아니라 "대기 중"으로 안내한다.
        log(f"[대기] WAY 재배치 판별 보류 ({label}): {e}")
        send_alert(
            f"[재배치 확인 대기] {label}",
            f"WAY(일본/중국/홍콩 재배치) 후보 건인데 아직 판정을 확정할 수 없습니다: {e}\n"
            f"다음 자동 실행(20분 주기)에서 계속 재확인합니다. 오래 반복되면 수동으로 확인해주세요.",
            dedup_key=f"{entry_id}:oracle_query_fail",
        )
        return "ERROR"
    except Exception as e:
        # SharePointLookupUndetermined 외의 진짜 예상 못한 에러(브라우저/네트워크 등).
        log(f"[에러] WAY 재배치 SharePoint 조회 실패 ({label}): {e}\n{traceback.format_exc()}")
        send_alert(
            f"[오라클 조회 실패] {label}",
            f"WAY(일본/중국/홍콩 재배치) SharePoint 조회 중 에러가 발생했습니다: {e}\n"
            f"다음 자동 실행에서 재시도합니다. 계속 반복되면 수동으로 확인해주세요.",
            dedup_key=f"{entry_id}:oracle_query_fail",
        )
        return "ERROR"
    if match is None:
        return None

    address_lines = get_ship_from_address_lines(match["from_org"])
    if not address_lines:
        log(f"[경고] {label}: From={match['from_org']} 참고 주소를 못 읽어서 WAY 자동처리 중단")
        return None

    to_info = lookup_receive_to_no_via_sharepoint(driver, delivery_no)

    return {
        "from_org": match["from_org"],
        "receive_delivery_no": match["receive_delivery_no"],
        "address_lines": address_lines,
        "to_no": to_info["to_no"],
        "receive_to_no": to_info["receive_to_no"],
    }

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH


# ==============================================================
# 유틸
# ==============================================================
def log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        # 콘솔 코드페이지(cp949 등)로 표현 안 되는 문자(메일 제목의 특수기호 등)가
        # 섞여 있어도 로그 출력 때문에 스크립트 전체가 죽으면 안 된다 - 표현 안
        # 되는 문자만 대체하고 계속 진행한다.
        enc = sys.stdout.encoding or "utf-8"
        print(line.encode(enc, errors="replace").decode(enc, errors="replace"))
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ==============================================================
# 상태/캐시 JSON 저장·읽기 (2026-08-06 안전장치 추가)
# ==============================================================
# 배경: 지금까지 상태 파일 저장이 open(path, "w") + json.dump 방식이었다.
# open("w")는 파일을 **먼저 비우고** 쓰기 때문에, 쓰는 도중에 프로세스가 죽으면
# (전원/윈도우 업데이트/강제 종료) 파일이 잘린 채로 남아 JSON 파싱이 깨진다.
# 그런데 읽는 쪽은 `except Exception: return {}`이라 깨진 파일을 "처리한 게
# 하나도 없음"으로 해석한다 -> 컷오프 이후 모든 메일이 다시 "신규"가 되어
# **이미 출고된 주문을 다시 릴리즈하고 완료 메일을 다시 보낸다.**
# 이게 가정이 아닌 이유: pick_release_watcher.py 주석(_save_partial_fg_success)에
# "2026-07-23 SP 도중 프로세스가 통째로 죽어서 FG 성공 기록이 상태에 전혀 안
# 남았음"이라는 실제 사례가 이미 기록돼 있다. 그때 하필 저장 중이었다면
# 파일이 깨졌을 것이다.
#
# 대응 두 가지:
#  (1) 저장은 임시 파일에 다 쓴 뒤 os.replace로 바꿔치기한다(원자적). 도중에
#      죽어도 기존 파일은 손상되지 않고 그대로 남는다.
#  (2) 읽기는, 파일이 아예 없으면 {}(정상 - 첫 실행)이지만 "파일은 있는데
#      깨진" 경우엔 {}로 대체하지 않고 예외를 올려 그 회차를 중단시킨다.
#      중복 처리보다 한 회차 쉬는 쪽이 압도적으로 안전하기 때문이다.
# ==============================================================
# 고정 대기 -> 조건 대기 '안전 전환' (2026-08-06 추가)
# ==============================================================
def wait_or_sleep(driver, condition, seconds: float, *, poll: float = 0.25) -> bool:
    """기존 `time.sleep(seconds)` 자리를 그대로 대체하는 대기 함수.

    동작 규칙(이게 이 함수의 전부이자 안전성의 근거다):
      - condition(driver)이 참이 되면 **즉시** 반환한다(True).
      - 끝까지 참이 되지 않으면 **정확히 seconds만큼** 기다린 뒤 반환한다(False).
    즉 최악의 경우가 기존 time.sleep(seconds)와 완전히 동일하고, 그보다 오래
    기다리는 경우는 없다. 그래서 이 치환은 화면이 빨리 준비되면 빨라지기만 할 뿐,
    기존 동작을 절대 깨지 않는다(클릭 순서/처리 순서/업무 흐름은 그대로).

    condition 평가 중 예외가 나면 '아직 준비 안 됨'으로 보고 계속 기다린다 -
    기존 sleep이 그 시간 동안 아무것도 확인하지 않고 그냥 기다렸던 것과 같은
    결과이므로 이것도 동작 변화가 아니다.

    반환값(True/False)은 호출부에서 굳이 쓰지 않아도 된다 - 로그로 "빨리
    끝났는지 / 끝까지 기다렸는지"를 보고 싶을 때만 쓴다.

    주의: 오라클 트랜잭션(Release Now / Ship Confirm 등) 직후처럼 '결과가
    확정되기까지 기다려야 하는' 자리에는 함부로 쓰지 않는다 - 조건을 잘못
    잡으면 아직 처리 중인데 다음 단계로 넘어갈 수 있다. 화면 이동(읽기 전용)
    구간부터 우선 적용한다."""
    deadline = time.time() + seconds
    while True:
        try:
            if condition(driver):
                return True
        except Exception:
            pass  # 조건 평가 실패 = 아직 준비 안 됨(기존 sleep과 동일하게 계속 대기)
        remaining = deadline - time.time()
        if remaining <= 0:
            return False
        time.sleep(min(poll, remaining))


def text_visible(text: str):
    """wait_or_sleep용 조건 - 화면에 이 텍스트가 보이면 True.
    (화면 전환이 끝났는지 판정하는 가장 흔한 조건이라 헬퍼로 둔다.)"""
    from selenium.webdriver.common.by import By

    def _cond(d):
        return any(el.is_displayed() for el in d.find_elements(
            By.XPATH, f"//*[contains(normalize-space(text()), '{text}')]"))
    return _cond


def element_present(by, selector):
    """wait_or_sleep용 조건 - 이 요소가 화면에 보이면 True."""
    def _cond(d):
        return any(el.is_displayed() for el in d.find_elements(by, selector))
    return _cond


def exc_detail(e: BaseException) -> str:
    """로그에 남길 예외 상세 - 예외 타입 + 메시지 + 파이썬 스택.

    2026-08-06 추가. 배경: 대부분의 [에러] 로그가 f"{e}"만 남기고 있었는데,
    Selenium 예외의 메시지에는 msedgedriver **내부** 스택만 들어있어서
    "우리 코드 어느 줄에서 터졌는지"가 전혀 안 보인다. 그래서 로그를 봐도
    매번 화면을 재현해봐야 원인을 좁힐 수 있었다.
    이 지적은 icbl_ci_watcher.py main()에 2026-07-10 주석으로 이미 적혀 있었고
    거기만 traceback을 남기고 있었다 - 같은 처방을 나머지에도 적용한다.
    (예외 타입을 앞에 따로 붙이는 이유: NoSuchElementException /
     InvalidSessionIdException / TimeoutException 중 무엇인지가 대응 방법을
     가르는데, 메시지만 보면 구분이 잘 안 되는 경우가 많다.)"""
    return f"{type(e).__name__}: {e}\n{traceback.format_exc()}"


class StateFileCorrupted(Exception):
    """상태 파일이 존재하는데 JSON으로 읽히지 않는 경우. 빈 상태로 진행하면
    이미 처리한 건을 처음부터 다시 처리하게 되므로(중복 출고/중복 메일) 이
    예외로 회차를 중단시킨다."""


def atomic_write_json(path: str, data) -> None:
    """JSON을 '중간에 끊겨도 기존 파일이 깨지지 않게' 저장한다.
    임시 파일에 완전히 쓰고 디스크에 반영(flush+fsync)한 뒤, os.replace로
    한 번에 바꿔치기한다(같은 볼륨에서는 원자적 연산)."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read_json_state(path: str, what: str = "상태 파일", strict: bool = True) -> dict:
    """상태/캐시 JSON을 읽는다.
    파일이 없으면 {}(정상 - 첫 실행).
    파일은 있는데 깨져 있으면:
      strict=True  -> StateFileCorrupted를 올려 이번 회차를 중단(처리 이력처럼
                      잃으면 중복 처리로 이어지는 파일).
      strict=False -> {}로 진행(캐시처럼 다시 만들면 그만인 파일)."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        if not strict:
            log(f"[경고] {what}({os.path.basename(path)})이 손상됨 - 다시 만들면 되는 "
                f"파일이라 빈 값으로 진행합니다: {e}")
            return {}
        log(f"[치명] {what}({os.path.basename(path)})을 읽을 수 없습니다: {e}\n"
            f"       빈 상태로 진행하면 이미 처리한 건을 처음부터 다시 처리하게 되어"
            f" 중복 출고/중복 메일 위험이 있으므로 이번 회차를 중단합니다.\n"
            f"       파일을 확인하거나 백업에서 복구한 뒤 다시 실행해주세요.")
        raise StateFileCorrupted(f"{what} 손상: {path}") from e


def load_state() -> dict:
    # 처리 이력 - 잃으면 이미 답장까지 끝난 건을 다시 처리한다(strict).
    return read_json_state(STATE_PATH, "처리 이력", strict=True)


def save_state(state: dict):
    atomic_write_json(STATE_PATH, state)


def load_oracle_process_state() -> dict:
    # 진행 중인 Process ID 기록 - 잃어도 리포트를 다시 제출할 뿐이라 부작용 없음.
    return read_json_state(ORACLE_PROCESS_STATE_PATH, "오라클 진행상태", strict=False)


def save_oracle_process_state(state: dict):
    atomic_write_json(ORACLE_PROCESS_STATE_PATH, state)


def load_extract_cache(state: dict | None = None) -> dict:
    """AWB/DHL 번호별 추출 결과 캐시를 읽는다(오래된 것/이미 처리 끝난 건은 정리).
    2026-08-06 추가 - EXTRACT_CACHE_PATH 설명 참고."""
    # OCR 추출 캐시 - 잃어도 다시 추출하면 그만이라 strict=False.
    cache = read_json_state(EXTRACT_CACHE_PATH, "추출 캐시", strict=False)

    processed_keys = set(state.keys()) if state else set()
    kept = {}
    for key, entry in cache.items():
        if key in processed_keys:
            continue  # 이미 답장까지 끝난 건 - 캐시 필요 없음
        try:
            cached_at = datetime.strptime(entry["cached_at"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            continue
        if (datetime.now() - cached_at).total_seconds() > EXTRACT_CACHE_TTL_HOURS * 3600:
            continue
        kept[key] = entry
    if len(kept) != len(cache):
        save_extract_cache(kept)
    return kept


def save_extract_cache(cache: dict):
    atomic_write_json(EXTRACT_CACHE_PATH, cache)


# 캐시에 저장하지 않는(이번 실행에만 의미 있는) 런타임 키
_CASE_RUNTIME_KEYS = ("process_ids", "results", "submit_error")


def _script_mtime() -> str:
    """이 스크립트의 마지막 수정 시각. 추출 캐시에 같이 넣어두고, 스크립트가
    수정되면(= OCR/추출 로직이 바뀌었을 수 있으면) 캐시를 버리고 새로 추출한다 -
    예전 버그로 잘못 뽑힌 값을 캐시가 며칠씩 붙들고 있는 걸 막기 위함."""
    try:
        return datetime.fromtimestamp(
            os.path.getmtime(os.path.abspath(__file__))).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def case_to_cache(case: dict) -> dict:
    """추출 결과 case를 JSON으로 저장 가능한 형태로 바꾼다.
    org_delivery_pairs는 튜플 리스트라 JSON에선 리스트가 되므로 복원할 때 되돌린다."""
    entry = {k: v for k, v in case.items() if k not in _CASE_RUNTIME_KEYS}
    entry["org_delivery_pairs"] = [list(p) for p in case["org_delivery_pairs"]]
    entry["cached_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry["script_mtime"] = _script_mtime()
    return entry


def case_from_cache(entry: dict) -> dict:
    """캐시에서 읽은 항목을 case 딕셔너리로 복원한다.
    org_delivery_pairs는 dict 키로 쓰이므로(process_ids/results) 반드시 튜플로."""
    case = {k: v for k, v in entry.items() if k not in ("cached_at", "script_mtime")}
    case["org_delivery_pairs"] = [tuple(p) for p in entry["org_delivery_pairs"]]
    return case


def load_alerted_state() -> dict:
    # 알림 중복 방지 기록 - 잃으면 알림이 한 번 더 갈 수 있을 뿐이라 strict=False.
    return read_json_state(ALERTED_STATE_PATH, "알림 발송 이력", strict=False)


def save_alerted_state(state: dict):
    atomic_write_json(ALERTED_STATE_PATH, state)


def load_sample_confirm_sent_state() -> dict:
    # 시료확인서 품목별 1회 발송 이력 - 잃으면 이미 보낸 품목에 확인서를 한 번
    # 더 첨부하는 정도라 strict=False(치명적이지 않음).
    return read_json_state(SAMPLE_CONFIRM_SENT_STATE_PATH, "시료확인서 발송 이력", strict=False)


def save_sample_confirm_sent_state(state: dict):
    atomic_write_json(SAMPLE_CONFIRM_SENT_STATE_PATH, state)


def sample_confirm_already_sent(part_number: str) -> bool:
    return part_number in load_sample_confirm_sent_state()


def mark_sample_confirm_sent(part_number: str, label: str):
    state = load_sample_confirm_sent_state()
    state[part_number] = {
        "sent_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "label": label,
    }
    save_sample_confirm_sent_state(state)


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def match_ship_from_org(text: str) -> str | None:
    """SHIP_FROM_ORG_MAP 키를 공백/하이픈 무시하고 전체 텍스트에서 substring으로
    찾는다 (OCR이 여러 컬럼을 한 줄로 섞어놔서 'SHIP FROM:' 라벨 바로 뒤 텍스트만
    보는 방식은 깨지기 쉬움 — DHL 인보이스처럼 3단 컬럼 헤더에서 특히 그렇다).
    2026-07-24 실측(AWB 874668910609): OCR이 "CEVA - IDC"를 "CEVA - [IDC"로
    대괄호 노이즈를 끼워 읽어서, 공백/하이픈만 제거하는 걸로는 "cevaidc"로 안
    붙고 매칭이 깨졌다. 영숫자가 아닌 문자는 전부 제거하도록 넓혀서 이런
    OCR 잡음(괄호/구두점 등)에 더 관대하게 만든다 -> 1차 시도.
    2026-08-01 실측(AWB 524288040270, 50건 스윕 중 발견): 이번엔 노이즈가
    "끼워지는" 게 아니라 "I"가 아예 "["로 오독됨("CEVA - [DC") - 1차 시도(그냥
    제거)로는 "cevadc"가 되어 "i"가 통째로 사라져 여전히 안 붙는다.
    2026-08-01 재확인(50건 회귀테스트 중 AWB 874668910609에서 발견): "[" ->
    "i"로 무조건 치환하면 위 07-24 케이스("[IDC", 진짜 I가 그대로 남아있고
    대괄호는 순수 노이즈)에서 "i"가 중복돼("iIDC" -> "cevaiidc") 오히려 매칭이
    깨지는 회귀가 남. 즉 "["의 정체가 "노이즈 삽입"인지 "I 오독"인지 텍스트만
    보고는 미리 알 수 없다 -> 1차(그냥 제거)로 먼저 매칭을 시도하고, 그래도
    실패할 때만 2차로 "["->"i" 치환을 시도하는 2단계 방식으로 두 사례 모두
    회귀 없이 처리한다."""
    def _try(norm_text: str) -> str | None:
        norm = re.sub(r"[^a-z0-9]+", "", norm_text.lower())
        for k, v in SHIP_FROM_ORG_MAP.items():
            k_norm = re.sub(r"[^a-z0-9]+", "", k.lower())
            if k_norm and k_norm in norm:
                return v
        return None

    result = _try(text)
    if result:
        return result
    return _try(text.replace("[", "i"))


# ==============================================================
# 1) Outlook에서 신규 통관 메일 찾기 (FedEx / DHL 형식 모두)
# ==============================================================
def extract_exporter_from_body(body: str) -> str | None:
    """메일 본문 '화물 정보' 블록의 '수출업체:' 값을 뽑는다. 줄 자체가 없거나
    (DHL 형식) 값이 비어 있으면(중국발 Rebalance 건에서 실제로 나옴) None을
    돌려 '판정 불가 -> 통과'로 처리한다."""
    m = EXPORTER_LINE_RE.search(body or "")
    if not m:
        return None
    return m.group(1).strip() or None


def is_allowed_exporter(exporter: str) -> bool:
    """수출업체가 우리 물류 경로(Syneron 계열 / CEVA Logistics)인지 판정.
    메일 본문은 사람이 쓴 게 아니라 시스템 출력이라 표기가 거의 일정하지만,
    'CEVA  LOGISTICS'/'CEVA-LOGISTICS'/'SYNERON CANDELA.K.K'처럼 구두점·공백만
    다른 변형이 실제로 나오므로 영숫자만 남겨서 비교한다."""
    norm = re.sub(r"[^A-Z0-9]+", "", (exporter or "").upper())
    return any(re.sub(r"[^A-Z0-9]+", "", k) in norm for k in EXPORTER_ALLOW_KEYWORDS)


def extract_shipment_key(subject: str):
    """제목에서 (포워더 형식, 고유번호)를 뽑는다. 첨부파일명 대신 제목을 쓰는 이유:
    답장([RE]) 메일은 첨부가 원본과 달라질 수 있지만 제목의 번호는 스레드 내내 유지됨."""
    m = FEDEX_KEY_RE.search(subject)
    if m:
        return "fedex", m.group(1)
    m = DHL_KEY_RE.search(subject)
    if m:
        return "dhl", m.group(1)
    return None, None


def _state_key(fmt: str, key: str) -> str:
    # fedex는 기존 state 파일과의 호환을 위해 접두어 없이 그대로 사용,
    # dhl은 신규 네임스페이스라 접두어를 붙여 구분한다.
    return key if fmt == "fedex" else f"{fmt}:{key}"


def find_new_customs_mails(processed_state_keys: set) -> list[dict]:
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    inbox = outlook.GetDefaultFolder(6)  # 받은편지함
    target = None
    for f in inbox.Folders:
        if str(f.Name).strip() == OUTLOOK_INBOX_SUBFOLDER:
            target = f
            break
    if target is None:
        raise RuntimeError(f"Outlook 폴더를 못 찾음: 받은편지함 > {OUTLOOK_INBOX_SUBFOLDER}")

    items = target.Items
    items.Sort("[ReceivedTime]", True)

    mails = []
    # 2026-08-06: 아래 항목 읽기 실패는 예전엔 조용히 건너뛰었다 - 메일 한 통을
    # 통째로 빠뜨리는 건데 로그에 흔적이 없어서 "왜 이 건이 처리 안 됐지"를
    # 추적할 방법이 없었다. 동작(건너뛰기)은 그대로 두고 흔적만 남기되, 목록
    # 전체가 깨진 경우 로그가 폭주하지 않도록 앞의 3건만 남긴다.
    _item_errors = 0
    for i in range(1, min(items.Count, 150) + 1):
        try:
            mail = items.Item(i)
        except Exception as e:
            _item_errors += 1
            if _item_errors <= 3:
                log(f"[경고] Outlook 메일 항목 {i}번을 읽지 못해 건너뜀"
                    f"({type(e).__name__}: {e})")
            elif _item_errors == 4:
                log("[경고] Outlook 항목 읽기 실패가 계속됨 - 이후 같은 로그는 생략합니다")
            continue
        if getattr(mail, "Class", None) != 43:
            continue

        received_dt = datetime(
            mail.ReceivedTime.year, mail.ReceivedTime.month, mail.ReceivedTime.day,
            mail.ReceivedTime.hour, mail.ReceivedTime.minute, mail.ReceivedTime.second,
        )
        if received_dt < LOOKBACK_START_DATE:
            break  # 최신순 정렬이므로 여기부터는 더 볼 필요 없음(과거 메일)

        atts = [str(mail.Attachments.Item(j).FileName or "")
                for j in range(1, mail.Attachments.Count + 1)]
        subject = str(mail.Subject or "")
        # 본문은 요청 메일(제목 매칭되는 것)에서만 읽는다 - 150통 전부 Body를
        # 건드리면 MAPI 왕복이 그만큼 늘어나는데, 수출업체 판정에 쓰는 건
        # 요청 메일뿐이라 낭비다.
        if FEDEX_SUBJECT_CONTAINS in subject or DHL_SUBJECT_CONTAINS in subject:
            try:
                body = str(mail.Body or "")
            except Exception as e:
                # 본문을 못 읽으면 수출업체 판정을 포기하고 기존 동작(통과)으로
                # 둔다 - 여기서 막아버리면 읽기 실패 하나로 우리 건을 놓친다.
                log(f"[경고] 본문을 읽지 못해 수출업체 판정 생략: {subject} "
                    f"({type(e).__name__}: {e})")
                body = ""
        else:
            body = ""
        mails.append({
            "entry_id": mail.EntryID,
            "subject": subject,
            "attachments": atts,
            "body": body,
        })

    # 1차 패스: 인천관세법인이 통관 완료 회신(_IMP_ 첨부)한 건은 이미 종결된 것으로
    # 표시 — 순서와 무관하게(RE가 FW보다 먼저 스캔됨) 같은 키의 FW를 다시 안 집도록.
    closed_keys = set()
    for m in mails:
        if any(a.lower().startswith(IMP_ATTACHMENT_PREFIX) for a in m["attachments"]):
            fmt, key = extract_shipment_key(m["subject"])
            if key:
                closed_keys.add((fmt, key))

    # 2차 패스: 실제 처리 대상(요청 메일) 골라내기
    results = []
    skipped_exporters = []  # 로그 한 줄로 모아 찍기(매 주기 반복되는 내용이라)
    for m in mails:
        subject = m["subject"]
        if FEDEX_SUBJECT_CONTAINS not in subject and DHL_SUBJECT_CONTAINS not in subject:
            continue
        if any(a.lower().startswith(IMP_ATTACHMENT_PREFIX) for a in m["attachments"]):
            continue  # 방어적으로 한 번 더 제외(이미 회신 온 메일 자체)

        # 수출업체가 우리 경로(Syneron/CEVA Logistics)가 아니면 여기서 끝
        # (첨부 저장·OCR·Edge 실행 전에 차단). 필드가 없으면 판정 불가로 보고
        # 통과 - EXPORTER_ALLOW_KEYWORDS 설명 참고.
        exporter = extract_exporter_from_body(m["body"])
        if exporter and not is_allowed_exporter(exporter):
            _, _key = extract_shipment_key(subject)
            skipped_exporters.append(f"{_key or subject[:30]}({exporter})")
            continue

        fmt, key = extract_shipment_key(subject)
        if not key:
            log(f"[경고] 제목에서 고유번호를 못 뽑음(스킵): {subject}")
            continue
        if (fmt, key) in closed_keys:
            continue
        state_key = _state_key(fmt, key)
        if state_key in processed_state_keys:
            continue

        if fmt == "fedex":
            awb_att = next((a for a in m["attachments"] if a.upper().startswith("AWB")), None)
            if awb_att is None:
                continue
            results.append({
                "format": "fedex", "key": key, "state_key": state_key,
                "entry_id": m["entry_id"], "subject": subject,
                "attachment_name": awb_att,
            })
        else:  # dhl
            inv_atts = [a for a in m["attachments"] if "_INV_" in a.upper() or a.upper().startswith("INV")]
            if not inv_atts:
                continue
            ewb_att = next((a for a in m["attachments"] if "_EWB_" in a.upper() or a.upper().startswith("EWB")), None)
            hwb_att = next((a for a in m["attachments"] if "_HWB_" in a.upper() or a.upper().startswith("HWB")), None)
            results.append({
                "format": "dhl", "key": key, "state_key": state_key,
                "entry_id": m["entry_id"], "subject": subject,
                "inv_attachments": inv_atts, "ewb_attachment": ewb_att, "hwb_attachment": hwb_att,
            })

    if skipped_exporters:
        log(f"[스킵] 우리 수출업체(Syneron/CEVA Logistics)가 아니라 처리 대상 아님 "
            f"{len(skipped_exporters)}건: {', '.join(skipped_exporters)}")

    return results


def save_attachment(entry_id: str, attachment_name: str, save_name: str) -> str:
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    mail = outlook.GetItemFromID(entry_id)
    os.makedirs(PDF_SAVE_DIR, exist_ok=True)
    out_path = os.path.join(PDF_SAVE_DIR, safe_filename(save_name))
    for j in range(1, mail.Attachments.Count + 1):
        att = mail.Attachments.Item(j)
        if att.FileName == attachment_name:
            att.SaveAsFile(out_path)
            return out_path
    raise RuntimeError("첨부파일을 다시 찾지 못함: " + attachment_name)


# ==============================================================
# 2) PDF -> OCR로 Delivery Number / Ship From / 총액 추출
# ==============================================================
def _detect_rotation(img) -> int:
    """Tesseract OSD로 이미지의 회전 각도(0/90/180/270)를 감지한다. 감지 실패
    시 0(회전 없음으로 간주)."""
    try:
        osd = pytesseract.image_to_osd(img)
        m = re.search(r"Rotate:\s*(\d+)", osd)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def _ocr_image_auto_rotate(img) -> str:
    """이미지의 회전 상태를 Tesseract OSD로 감지해서 보정한 뒤 OCR한다.
    2026-07-20 실측: 처음엔 ocr_pdf_pages()에만 있던 로직인데, 고배율 단일
    페이지 재OCR(_ocr_page_high_res)에는 이 보정이 빠져있어서, 콘텐츠 자체가
    90도로 인쇄된 CI 페이지(AWB 874419512765)에서 고배율로 다시 찍어도 여전히
    글자가 옆으로 누운 채 OCR되는 문제가 있었음 - 공통 함수로 빼서 둘 다 쓴다."""
    rotate = _detect_rotation(img)
    if rotate:
        img = img.rotate(-rotate, expand=True)

    return pytesseract.image_to_string(img, lang="eng")


def ocr_pdf_pages(pdf_path: str) -> list[str]:
    pdf = pdfium.PdfDocument(pdf_path)
    texts = []
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            bitmap = page.render(scale=2.5)
            img = bitmap.to_pil()
            texts.append(_ocr_image_auto_rotate(img))
    finally:
        pdf.close()
    return texts


def _ocr_page_high_res(pdf_path: str, page_index: int | None = None, scale: float = 4.0) -> str:
    """지정한 페이지 하나만 고배율로 렌더링해서 OCR한다(DHL Delivery Number
    크롭과 같은 발상 - 저배율 전체 OCR에서 작은 숫자가 깨질 때 보완용).
    page_index가 None이면 마지막 페이지(지금까지 실측한 FedEx AWB는 전부
    안내문+AWB+CI 구조라 CI가 마지막 페이지)를 쓴다."""
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        idx = page_index if page_index is not None else len(pdf) - 1
        page = pdf[idx]
        bitmap = page.render(scale=scale)
        img = bitmap.to_pil()
    finally:
        pdf.close()
    return _ocr_image_auto_rotate(img)


def _extract_delivery_and_total(text: str, use_subtotal_as_total: bool = False):
    """FedEx CI OCR 텍스트에서 Delivery Number와 총액을 뽑는 공통 로직.
    2026-07-13: "TOTAL"이 "SUBTOTAL" 뒤에도 나타나므로 진짜 TOTAL 라벨이 있을
    때만 "문서에 등장하는 마지막 쉼표구분 금액이 TOTAL"이라는 고정 구조를 쓴다.
    2026-07-20 실측(AWB 874419512765): 그 마지막 금액이 실은 총액 밑에 참고로
    나오는 USD 환산값("2,805.93 usd")인 경우가 있어, 그런 USD 환산 표기가 바로
    뒤에 붙는 금액은 후보에서 제외한다.
    2026-08-03 실측(AWB 875064614942): OCR이 "₩4,191,083"의 첫 쉼표를 공백으로
    잘못 읽어 "W4 191,083"이 되면서, 쉼표구분 금액 정규식이 뒤쪽 "191,083"만
    잡고 앞자리 "4"를 통째로 놓치는 사례 확인(EXTENSION 합산 폴백에서 이미
    같은 유형을 통화기호 앞자리 고정으로 처리한 적 있음 - 여기 주 경로에도
    동일하게 적용). 통화기호(₩ 또는 그 OCR 오독인 W) 바로 뒤에 숫자, 공백, 쉼표
    구분 숫자가 이어지면 그 공백을 쉼표로 되돌려 붙인 뒤 매칭한다.
    2026-08-24 실측(AWB 875925471995): "그냥 9로 시작하는 7자리" 폴백이 FedEx AWB
    양식 칸의 "Declared value of Customs"를 Delivery Number로 잡아버린 사례 확인 -
    그 칸 값이 9633601(= 인보이스 총액 ₩9,633,601)이라 하필 Delivery Number와
    같은 모양이었다. 실제 Delivery는 C.I의 9973115인데, C.I 페이지 OCR에서는 그
    숫자가 통째로 안 읽혀서(라벨 "NUMBER / DELIVERY"만 읽힘) 라벨 앵커가 먼저
    실패한 상황.
    "AWB 페이지는 폴백 대상에서 빼기"로는 못 고친다 - 실측 AWB 513914058868/
    513914058960에서는 반대로 **AWB 양식 페이지에 찍힌 숫자가 유일하게 살아남은
    정상 Delivery**였고(C.I 페이지 쪽 OCR이 깨졌음), 크롭 OCR은 같은 건에서
    9905901을 9905301로 오독했다. 즉 어느 페이지도, 어느 OCR 방식도 항상 옳지
    않다.
    구별되는 사실은 하나다: 잘못 잡힌 숫자는 "이 문서에 금액으로도 찍혀 있는
    값"이다(Declared value of Customs = 인보이스 금액). 그래서 폴백 후보 중
    문서에 쉼표구분 금액으로 같이 등장하는 값은 건너뛴다."""
    # 문서에 "금액"으로 등장하는 숫자열 - 폴백 후보 배제용
    money_digits = {
        a.replace(",", "") for a in re.findall(r"\d{1,3}(?:,\d{3})+", text)
    }

    m_delivery = re.search(r"DELIVERY[.\s]*[:\-]?\s*(\d{7})", text.upper())
    delivery_no = m_delivery.group(1) if m_delivery else None
    if not delivery_no:
        for m in re.finditer(r"\b(9\d{6})\b", text):
            cand = m.group(1)
            if cand in money_digits:
                log(f"[정보] Delivery Number 폴백 후보 {cand}는 이 문서에 금액으로도 "
                    f"찍혀 있음(Declared value of Customs 등) -> Delivery 아님으로 보고 건너뜀")
                continue
            delivery_no = cand
            break

    total = None
    # use_subtotal_as_total: 진짜 TOTAL 라벨이 OCR에 안 읽힌 경우 SUBTOTAL 라벨
    # "뒤쪽" 텍스트를 총액 구간으로 대신 쓴다. SHIP/HANDLING 칸이 비어 있는 표준
    # Candela C.I에선 SUBTOTAL == TOTAL이라 성립한다. 기존 경로가 답을 내는 건을
    # 흔들지 않도록 호출부에서 "총액을 끝까지 못 구한 경우"에만 켠다.
    total_text = None
    if re.search(r"(?<!SUB)TOTAL\b", text.upper()):
        total_text = text
    elif use_subtotal_as_total:
        m_sub = re.search(r"SUBTOTAL", text.upper())
        if m_sub:
            total_text = text[m_sub.end():]
    if total_text is not None:
        text_fixed = re.sub(
            r"([₩Ww])\s*(\d{1,3})\s+(\d{1,3}(?:,\d{3})+)",
            lambda m: f"{m.group(1)}{m.group(2)},{m.group(3)}",
            total_text,
        )
        amounts = [
            a for a in re.findall(r"\d{1,3}(?:,\d{3})+(?!\.\d+\s*usd)", text_fixed, re.IGNORECASE)
        ]
        if amounts:
            try:
                total = float(amounts[-1].replace(",", ""))
            except Exception:
                total = None

    return delivery_no, total


# 2026-08-24: FedEx 첨부는 "안내문 + AWB 양식 + C.I" 구조라 지금까지 "C.I는 마지막
# 페이지"로 가정해 왔는데, C.I 자체가 2페이지인 4페이지 문서(실측 AWB
# 513914058868/513914058960/513914059831/513914060217)에서는 마지막 페이지가 C.I
# "2 of 2" 연장 페이지라서 Delivery Number 박스가 없다. 그리고 AWB 양식 페이지에는
# Delivery가 아닌 7자리 숫자("Declared value of Customs")가 있어서, 번호를 문서
# 전체에서 훑으면 그걸 Delivery로 오인한다(실측 AWB 875925471995: 실제 9973115
# 인데 9633601을 잡았음). 그래서 페이지를 "AWB 양식", "C.I 헤더", "그 외"로
# 구분해서 쓴다.
_AWB_FORM_MARKERS = (
    "DECLARED VALUE OF CUSTOMS", "INTERNATIONAL AIRWAY", "PACKAGE TRACKING NUMBER",
)
_CI_HEADER_MARKERS = ("COMMERCIAL INVOICE", "NUMBER / DELIVERY", "REMIT TO")


def _reconcile_total(low, high):
    """같은 C.I를 저배율(low) / 고배율(high)로 읽어 나온 총액 후보 중 하나를 고른다.
    반환 (채택값, 로그용 사유 또는 None).
    2026-08-03 실측(AWB 875064614942): 고배율 재OCR이 항상 더 정확한 건 아님 -
    이 건은 저배율 결과(4191083)가 맞았는데 고배율 재OCR이 오히려 앞자리 "4"를
    통째로 놓쳐(191083) 무조건 교체하면 틀린 값을 채택하게 됨. 두 값이 "앞자리
    숫자만 없어진" 관계(한쪽이 다른 쪽의 뒷부분과 그대로 일치)면 더 짧은(작은)
    쪽을 앞자리 손실로 보고 버리며, 그 관계가 아닐 때만(자릿수 오독처럼 앞자리가
    살아있는 경우) 고배율 값을 채택한다."""
    if high is None or high == low:
        return low, None
    low_s = str(int(low)) if low is not None else ""
    high_s = str(int(high))
    if low is not None and len(low_s) > len(high_s) and low_s.endswith(high_s):
        return low, (f"고배율 재OCR TOTAL({high})이 저배율 TOTAL({low})의 뒷자리와만 "
                     f"일치 -> 앞자리 손실로 보고 저배율 값 유지")
    if len(high_s) > len(low_s) and high_s.endswith(low_s) and low_s:
        return high, (f"저배율 TOTAL({low})이 고배율 TOTAL({high})의 뒷자리와만 일치 "
                      f"-> 앞자리 손실로 보고 고배율 값 채택")
    return high, f"CI 페이지 고배율 재OCR로 TOTAL {low} -> {high}로 교체"


def _is_awb_form_page(page_text: str) -> bool:
    up = page_text.upper()
    return any(k in up for k in _AWB_FORM_MARKERS)


def _ci_header_page_index(pages_text: list[str], default: int) -> int:
    """Delivery Number 박스가 있는 C.I 헤더 페이지의 인덱스. 못 찾으면 default."""
    for i, t in enumerate(pages_text):
        if _is_awb_form_page(t):
            continue
        if any(k in t.upper() for k in _CI_HEADER_MARKERS):
            return i
    return default


def extract_ci_info(pdf_path: str) -> dict:
    pages_text = ocr_pdf_pages(pdf_path)
    full_text = "\n".join(pages_text)

    # 크롭 대상은 "마지막 페이지"가 아니라 실제 C.I 헤더 페이지다(2026-08-24:
    # C.I가 2페이지인 4페이지 문서에서는 마지막 페이지가 "2 of 2" 연장 페이지라
    # Delivery 박스가 아예 없어서 크롭이 항상 빈손으로 돌아왔다). 총액 쪽 고배율
    # 재OCR은 마지막 페이지 그대로 둔다 - TOTAL은 그 연장 페이지에 있다.
    ci_header_idx = _ci_header_page_index(pages_text, default=len(pages_text) - 1)

    delivery_no, total = _extract_delivery_and_total(full_text)

    # 2026-07-20 실측(AWB 874419512765): 저배율(2.5) 전체 OCR로 Delivery
    # Number를 못 찾을 정도면, 같은 CI 페이지의 TOTAL 박스 숫자도 같이 깨져
    # 있을 가능성이 높음(실측 확인: 그 건은 총액이 옆의 USD 환산 참고값으로
    # 잘못 잡혔었음) - CI 페이지만 고배율로 다시 OCR해서 둘 다 재시도한다.
    # 2026-07-24 실측(AWB 874668910609): 저배율에서 Delivery Number를 "찾긴"
    # 했지만 자릿수를 잘못 읽은 사례 확인(내용이 90도 회전 인쇄된 페이지에서
    # 9959293 -> 9959003으로 오독, 오라클이 "Invalid value"로 거부하고 나서야
    # 발견됨). "못 찾았을 때만 재시도"로는 이런 조용한 오독을 못 잡으므로,
    # Delivery Number를 찾은 경우에도 항상 고배율로 한 번 더 읽어 교차검증한다
    # - 서로 다르면(자릿수 오독 의심) 해상도가 높은 쪽이 더 신뢰할 만하다고
    # 보고 그 값을 채택하며, 불일치 자체를 로그로 남겨 나중에 원인 추적이
    # 바로 되게 한다.
    high_res_text = None
    try:
        high_res_text = _ocr_page_high_res(pdf_path)
        hr_delivery_no, hr_total = _extract_delivery_and_total(high_res_text)
        if hr_delivery_no and delivery_no and hr_delivery_no != delivery_no:
            # 2026-08-24 실측(AWB 524288040270): "불일치면 무조건 고배율 채택"이
            # 틀린 사례 확인 - 저배율이 맞게 읽은 9911468을 고배율이 9917468로
            # 오독했는데 규칙대로 틀린 쪽을 채택했다(원본 C.I의 NUMBER /
            # DELIVERY는 9911468). 해상도만으로는 어느 쪽이 맞는지 가릴 수 없으니
            # 그 박스만 크롭한 세 번째 판독을 심판으로 세워 2표를 받은 값을
            # 채택한다. 셋이 다 다르면 기존 규칙대로 고배율 값을 쓴다.
            tie = None
            try:
                tie_cropped = extract_delivery_number_from_ci(
                    pdf_path, page_index=ci_header_idx)
                tie = tie_cropped[0] if tie_cropped else None
            except Exception as e:
                log(f"[경고] Delivery Number 불일치 심판용 헤더 크롭 실패: {e}")
            if tie and tie == delivery_no:
                log(f"[경고] 저배율/고배율 OCR Delivery Number 불일치: {delivery_no!r} vs "
                    f"{hr_delivery_no!r} -> 헤더 크롭도 {tie!r}로 읽어 저배율 값 유지")
            else:
                log(f"[경고] 저배율/고배율 OCR Delivery Number 불일치: {delivery_no!r} vs "
                    f"{hr_delivery_no!r} (헤더 크롭={tie!r}) -> 고배율 값 채택")
                delivery_no = hr_delivery_no
        elif not delivery_no and hr_delivery_no:
            log(f"[정보] 저배율 OCR로 Delivery Number 실패 -> CI 페이지 고배율 재시도로 찾음: {hr_delivery_no}")
            delivery_no = hr_delivery_no
        total, reason = _reconcile_total(total, hr_total)
        if reason:
            log(f"[정보] {reason}")
    except Exception as e:
        log(f"[경고] CI 페이지 고배율 재OCR 실패: {e}")

    # 2026-08-03 실측(AWB 875064614942): 위 두 방식(전체 페이지 저배율/고배율
    # OCR) 다 실패할 수 있음 - "NUMBER / DELIVERY" 값이 박스 안 작은 글씨라
    # 페이지 전체를 통째로 OCR하면 통째로 빠지는 경우가 있었음(라벨 "NUMBER /
    # DELIVERY"는 읽히는데 그 옆 실제 숫자는 아예 안 잡힘). DHL/WAY 재배치
    # 경로에서 이미 쓰는 "그 박스만 크롭해서 OCR"(extract_delivery_number_from_ci,
    # 회전 보정 포함)을 FedEx 경로에도 마지막 안전망으로 적용한다 - CI는 항상
    # 마지막 페이지(안내문+AWB+CI 구조) - 정확한 페이지는 위 ci_header_idx 참고.
    if not delivery_no:
        try:
            cropped = extract_delivery_number_from_ci(pdf_path, page_index=ci_header_idx)
            if cropped:
                delivery_no = cropped[0]
                log(f"[정보] 전체 페이지 OCR로 Delivery Number 실패 -> CI 헤더 크롭(회전보정)으로 찾음: {delivery_no}")
        except Exception as e:
            log(f"[경고] CI 헤더 크롭 재시도 실패: {e}")


    m_ship_from = re.search(r"SHIP FROM[:\s]+([A-Za-z ]+)", full_text.upper())
    ship_from_raw = m_ship_from.group(1).strip() if m_ship_from else ""
    ship_from_key = ship_from_raw.lower().strip()
    org_code = None
    for k, v in SHIP_FROM_ORG_MAP.items():
        if k in ship_from_key:
            org_code = v
            break
    if org_code is None:
        # 라벨 기반 파싱 실패 시 전체 텍스트에서 substring으로 재시도
        org_code = match_ship_from_org(full_text)

    # 2026-08-24 실측(AWB 875925471995, 524288040270): 회전 인쇄된 C.I에서 진짜
    # TOTAL 라벨이 OCR에 통째로 안 읽히고 SUBTOTAL만 읽히는 경우가 있다. 표준
    # Candela C.I는 SHIP/HANDLING 칸이 비어 있어 SUBTOTAL == TOTAL이므로, 그
    # 라벨 뒤쪽 금액을 총액으로 쓸 수 있다. 아래 EXTENSION 합산 폴백보다 먼저
    # 시도한다 - 그 폴백은 통화기호 ₩가 "¥4"처럼 오독되면 앞자리 4가 금액에
    # 붙어버려서, 875925471995에서 실제 ₩9,633,601을 49,633,600으로 만들었다
    # (그 상태로 오라클 금액과 비교하면 멀쩡한 건이 가격 불일치로 잡힌다).
    # 기존 경로가 답을 낸 건은 흔들지 않도록 total이 None일 때만 켠다.
    if total is None:
        _, sub_total = _extract_delivery_and_total(full_text, use_subtotal_as_total=True)
        sub_hr_total = None
        if high_res_text is not None:
            _, sub_hr_total = _extract_delivery_and_total(
                high_res_text, use_subtotal_as_total=True)
        picked, reason = _reconcile_total(sub_total, sub_hr_total)
        if picked is not None:
            total = picked
            log(f"[정보] TOTAL 라벨을 못 읽음 -> SUBTOTAL 값을 총액으로 사용: {total}"
                + (f" ({reason})" if reason else ""))

    # 2026-07-13: 위 _extract_delivery_and_total()이 "TOTAL" 라벨과 쉼표구분
    # 금액 규칙으로 총액을 못 찾은 경우(SUBTOTAL만 있거나 TOTAL 라벨 자체가
    # 없는 경우 등, 예: 합계 페이지 누락)엔 아래 EXTENSION 합산 폴백으로 넘어간다.
    if total is None:
        # SUBTOTAL/TOTAL 문구가 아예 없는 경우(예: 인보이스가 원래 여러 페이지인데
        # 합계가 있는 페이지가 통째로 누락된 경우, 2026-07-13 AWB 5139-1406-0630
        # 실측: "PAGE 1 of 2" 중 1페이지만 첨부됨) - 각 품목 행의 마지막 금액
        # (EXTENSION 컬럼)을 합산해서 대체한다. 사용자 확인 하에 채택한 방식.
        # 2026-07-24 실측(AWB 874668910609): OCR이 "₩4,191,083"의 천단위 쉼표
        # 하나를 공백으로 잘못 읽어("₩4 191,083") 앞자리 "4"가 통째로 누락되는
        # 사례 확인. 처음엔 공백도 구분자로 통일 허용했더니, 수량 1건이라
        # 단가=EXTENSION 값이 같은 다른 건(AWB 5139-1406-0630, "W125,408,700
        # 125,408,700" - 두번째 값엔 통화기호가 안 붙음)에서 그 공백 허용이
        # 오히려 서로 다른 두 금액을 하나로 이어붙이는 회귀를 냄(1.25京 같은
        # 말도 안 되는 합계). 그래서 통화기호(₩, OCR로는 보통 "W") 앞자리 고정
        # 방식을 "1순위 시도"로만 쓰고, 그게 안 맞으면(=이 줄엔 그런 패턴이
        # 없다는 뜻) 기존의 쉼표 전용 방식으로 되돌아가는 2단계로 바꾼다 -
        # 이러면 두 실측 사례 모두 안전하게 처리된다.
        extensions = []
        for line in full_text.splitlines():
            if not re.match(r"^\s*7\d{6}\b", line):
                continue
            m = re.search(r"[₩W]\s*(\d{1,3}(?:[,\s]\d{3}){1,3})\s*$", line)
            if not m:
                m = re.search(r"(\d{1,3}(?:,\d{3})+)\s*$", line)
            if m:
                extensions.append(m.group(1))
        if extensions:
            try:
                total = sum(float(x.replace(",", "").replace(" ", "")) for x in extensions)
                log(f"[정보] TOTAL 문구 없음 -> 품목 EXTENSION {len(extensions)}건 합산으로 대체: {total}")
            except Exception:
                total = None

    return {
        "delivery_no": delivery_no,
        "ship_from_raw": ship_from_raw,
        "ship_from_org": org_code,
        "total": total,
        "raw_text": full_text,
    }


def find_sample_confirm_part_number(text: str) -> str | None:
    """SAMPLE_CONFIRM_PART_NUMBERS 중 이 CI 텍스트에 포함된 게 있으면 그 번호를
    반환. 형식이 숫자 4-2-4(대시 포함, 예: 9914-00-9092)와 문자+숫자(대시 없음,
    예: SBA102908) 둘로 섞여있어 영숫자만 남기고(공백/대시 등 제거) 정규화한 뒤
    부분일치로 찾는다(EXPORTER_ALLOW_KEYWORDS/match_ship_from_org와 같은 방식).
    각 대상 번호가 9~10자리의 특정 조합이라 오탐 위험은 낮다."""
    norm_text = re.sub(r"[^A-Z0-9]", "", text.upper())
    for pn in SAMPLE_CONFIRM_PART_NUMBERS:
        if re.sub(r"[^A-Z0-9]", "", pn.upper()) in norm_text:
            return pn
    return None


def extract_customs_value_from_waybill(pdf_path: str) -> float | None:
    """DHL의 EWB/HWB는 스캔이 아니라 텍스트 PDF라 OCR 없이 pdfplumber로 바로 읽을 수
    있고, 'Customs Value: NNNNNNN.00 KRW' 형태로 총액이 명시돼 있어 스캔 CI를 OCR로
    파싱하는 것보다 훨씬 신뢰도가 높다(2026-07-08 DHL 형식 대응 시 확인)."""
    import pdfplumber
    # 2026-08-06: 아래 실패들은 전부 조용히 None을 돌려줬다. None이면 호출부가
    # "운송장에서 금액을 못 구했다"로 넘어가 OCR 결과에 의존하게 되는데, 왜
    # 못 구했는지(파일 손상 / 문구 변경 / 숫자 형식 변경)가 로그에 전혀 안
    # 남아서 가격 대조가 어긋났을 때 원인 추적이 불가능했다. 반환값은 그대로
    # None을 유지하고 이유만 남긴다.
    try:
        with pdfplumber.open(pdf_path) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    except Exception as e:
        log(f"[경고] 운송장 PDF를 읽지 못함({type(e).__name__}: {e}) - "
            f"{os.path.basename(pdf_path)}")
        return None
    m = re.search(r"Customs\s*Value\s*[:\-]?\s*([\d,\.]+)\s*KRW", text, re.IGNORECASE)
    if not m:
        log(f"[경고] 운송장에서 'Customs Value ... KRW' 문구를 못 찾음 - "
            f"{os.path.basename(pdf_path)} (DHL 양식이 바뀌었을 수 있음)")
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except Exception as e:
        log(f"[경고] 운송장 Customs Value 숫자 변환 실패({m.group(1)!r}: {e}) - "
            f"{os.path.basename(pdf_path)}")
        return None


def identify_dhl_ci_pdf(inv_paths: list) -> tuple:
    """DHL 메일은 'INV'로 시작하는 첨부가 1개 이상 오는데, Commercial Invoice와
    Candela Delivery Note(패킹리스트)가 둘 다 이 이름 규칙을 쓴다. OCR 텍스트에
    'COMMERCIAL INVOICE' 문구가 있는 쪽을 진짜 C.I로 판별한다.
    2026-08-31 사용자 지적(AWB 2697218694, 인보이스 3개+Delivery 3개 실제 사례):
    한 메일에 서로 다른 shipment의 C.I가 여러 장(2개 이상) 진짜로 같이 오는
    경우가 있다 - 예전엔 첫 번째로 찾은 것만 쓰고 나머지는 버려서 그 shipment의
    Delivery가 통관 회신에서 통째로 빠졌다. 이제 'COMMERCIAL INVOICE' 문구가
    있는 첨부를 전부 골라 반환한다(보통 1개, 결합 건은 여러 개).
    반환: (ci_paths 리스트(순서 유지, 없으면 빈 리스트), {path: ocr전체텍스트})"""
    texts = {}
    ci_paths = []
    for p in inv_paths:
        try:
            pages = ocr_pdf_pages(p)
        except Exception as e:
            log(f"[경고] INV 첨부 OCR 실패({os.path.basename(p)}): {e}")
            continue
        text = "\n".join(pages)
        texts[p] = text
        if "COMMERCIAL INVOICE" in text.upper():
            ci_paths.append(p)
    return ci_paths, texts


def extract_dhl_ci_fields(ci_text: str) -> dict:
    """스캔 C.I OCR 텍스트에서 SO Number / Ship From을 뽑는다."""
    full_up = ci_text.upper()
    m_so = re.search(r"SO\s*NO\.?\s*[:\-]?\s*(\d{6,8})", full_up)
    if m_so:
        so_no = m_so.group(1)
    else:
        cands = re.findall(r"\b(7\d{5,6})\b", full_up)
        so_no = cands[0] if cands else None

    ship_from_org = match_ship_from_org(ci_text)
    return {"so_no": so_no, "ship_from_org": ship_from_org}


# Candela AR 인보이스 고정 템플릿에서 우측 상단 "NUMBER / DELIVERY" 박스의 위치
# (페이지 크기 대비 비율, x0,y0,x1,y1). 전체 페이지 OCR은 BILL TO/SHIP FROM/SHIP TO
# 3단 컬럼이 한 줄로 섞여서 이 필드를 신뢰성 있게 못 뽑길래(2026-07-08 확인),
# 이 박스만 잘라서 따로 OCR한다 — 훨씬 정확함. 인보이스 양식이 바뀌면 이 좌표도
# 다시 잡아야 한다(그 경우 아래 함수가 None을 반환하니 알림으로 알 수 있음).
# 2026-07-10: DHL 4781407805 건(Brucargo, 프랑스어 "Facture Commerciale" 템플릿)에서
# y1=0.18로는 "Livraison/번호" 줄이 박스 밖으로 잘려서 크롭 OCR이 빈 텍스트만 반환함.
# 실측 확인 결과 y1=0.28까지 넓히면 영어 템플릿("Commercial Invoice")과 프랑스어
# 템플릿("Facture Commerciale") 둘 다 번호까지 안전하게 포함됨(불필요한 다른 숫자는
# 안 걸림, 두 템플릿 모두 검증함).
CI_DELIVERY_BOX_FRAC = (0.68, 0.06, 1.0, 0.28)

# 2026-07-16 실측(DHL 5812115621, Brucargo/FBC 건): 같은 Candela 인보이스
# 템플릿인데 페이지 자체가 가로(landscape, 841x595pt)로 온 경우가 있음. 세로
# 기준 박스(위 CI_DELIVERY_BOX_FRAC)는 가로 페이지에서는 완전히 빈 영역을
# 잘라내서 크롭 OCR이 빈 텍스트만 반환함(실측 확인).
# 2026-07-20 실측(DHL 2099289393, CEVA-IDC 건): 가로 페이지 안에서도 "NUMBER /
# DELIVERY" 박스 위치가 문서마다 다른 최소 2개 하위 템플릿이 있음(Brucargo 건은
# 중앙 우측 x=0.52~0.72, 이 건은 더 오른쪽 x=0.70~0.98) - 원래 좁은 박스로는
# 이 건에서 완전히 빈 텍스트만 나옴. 둘 다 안전하게 포함하도록 x0을 0.52->0.50,
# y0을 0.13->0.08로 넓혀서 하나의 박스로 통일함(둘 다 다른 숫자 안 섞이는 걸로
# 재검증 완료).
CI_DELIVERY_BOX_FRAC_LANDSCAPE = (0.50, 0.08, 1.0, 0.28)


def extract_delivery_number_from_ci(ci_pdf_path: str, page_index: int = 0) -> list[str]:
    """스캔 C.I 1페이지 우측 상단 'NUMBER / DELIVERY' 박스만 크롭해서 OCR.
    2026-07-09: FBC+FBS 결합 건은 이 박스에 "9912602+9911503"처럼 Delivery
    Number 두 개가 +로 이어져 나옴 — findall로 박스 안의 모든 번호를 반환한다
    (보통 1개, 결합 건이면 2개). 어느 번호가 FBC/FBS인지는 여기서 알 수 없으므로
    호출부에서 lookup_ship_from_by_delivery()로 실적 파일과 대조해서 판별한다.
    2026-07-16: 페이지가 가로(width > height)면 박스 위치 자체가 다른 별도
    템플릿이라 CI_DELIVERY_BOX_FRAC_LANDSCAPE를 쓴다(실측 확인).
    2026-08-03 실측(AWB 875064614942): CI 페이지 콘텐츠 자체가 90도로 인쇄된
    경우(_ocr_image_auto_rotate가 대응하는 것과 같은 유형) 회전 보정 없이 고정
    비율로 크롭하면 완전히 다른 칸(예: TOTAL 칸)을 잘라내 버려서 크롭 OCR이
    엉뚱하거나 빈 텍스트만 반환함 - 크롭 전에 OSD로 회전을 감지해 이미지를
    먼저 세운다. page_index로 CI가 여러 페이지 중 특정 페이지(예: FedEx AWB는
    안내문+AWB+CI 구조라 마지막 페이지)에 있는 경우도 지정할 수 있게 함(기본값
    0은 기존 호출부인 DHL 단일 INV 첨부와 동일하게 동작)."""
    pdf = pdfium.PdfDocument(ci_pdf_path)
    try:
        idx = page_index if page_index >= 0 else len(pdf) + page_index
        page = pdf[idx]
        bitmap = page.render(scale=4.0)
        img = bitmap.to_pil()
    finally:
        pdf.close()

    rotate = _detect_rotation(img)
    if rotate:
        img = img.rotate(-rotate, expand=True)

    w, h = img.size
    frac = CI_DELIVERY_BOX_FRAC_LANDSCAPE if w > h else CI_DELIVERY_BOX_FRAC
    x0, y0, x1, y1 = frac
    box = img.crop((int(w * x0), int(h * y0), int(w * x1), int(h * y1)))
    # 2026-08-01 실측(DHL 8346590092): 기본 PSM(자동 페이지 분할)은 이 박스 안의
    # 표 테두리 때문에 레이아웃 분석이 꼬여서, "NUMBER / DELIVERY" 라벨(굵은
    # 글씨)은 읽으면서도 그 바로 아래 실제 값(가는 글씨, 예: "9965632")과 "1 of
    # 1" 같은 값 텍스트를 통째로 빠뜨리는 경우가 있었다(육안으로는 선명하게
    # 보이는데 OCR 결과엔 아예 없음). PSM 6("균일한 텍스트 블록 하나로 취급")로
    # 바꾸면 이 값 텍스트까지 안정적으로 읽힌다 - 기존 11개 실측 건 전부 동일한
    # 결과로 재검증 완료, 회귀 없음.
    text = pytesseract.image_to_string(box, config="--psm 6")
    # 2026-08-03 실측(AWB 875064614942): 정제 없이 원문 그대로에서 먼저 찾는다.
    # 아래 공백-제거 정제는 "9950313"이 "995031 3"처럼 한 번호 안에서 쪼개지는
    # 경우엔 도움이 되지만, 이 건처럼 번호 바로 앞에 무관한 숫자가 OCR로 붙어
    # 나온 경우("... 5 9961698")엔 오히려 그 무관한 숫자까지 붙여버려서
    # "59961698"이 되어 정규식이 못 찾게 만드는 역효과가 있었다(원문에는 이미
    # "9961698"이 온전한 단어로 존재해서 정제 없이도 바로 잡혔어야 했음).
    numbers = re.findall(r"\b9\d{6}\b", text)
    if not numbers:
        # 2026-07-10: DHL 3094922751 건에서 OCR이 "9950313"을 "995031 3"처럼
        # 숫자 사이에 엉뚱한 공백을 끼워 넣어 정규식이 못 잡는 경우가 실측됨 ->
        # 숫자와 숫자 사이의 공백만 제거하고(다른 구분자는 그대로 둬서 서로
        # 다른 줄의 숫자가 잘못 합쳐지는 걸 방지) 매칭 - 원문에서 못 찾았을
        # 때만 이 정제를 시도한다(위 역효과 사례를 피하기 위해 순서를 바꿈).
        cleaned = re.sub(r"(?<=\d)\s+(?=\d)", "", text)
        numbers = re.findall(r"\b9\d{6}\b", cleaned)
    # 2026-08-24 실측(AWB 875925471995): PSM 6이 이 박스의 값 칸을 "ABABA" 같은
    # 글자로 읽어버려서 번호를 통째로 놓치는 경우가 있음(라벨 "NUMBER /
    # DELIVERY"는 정상 인식). 같은 크롭을 PSM 4("가변 폭 컬럼 텍스트")로 다시
    # 읽으면 9973115가 정확히 잡힌다. PSM 11은 같은 박스에서 9973115를
    # 9873115로 오독했으므로(9->8) 쓰지 않는다 - 틀린 번호는 안 잡히는 것보다
    # 나쁘다.
    text_psm4 = None
    if not numbers:
        text_psm4 = pytesseract.image_to_string(box, config="--psm 4")
        numbers = re.findall(r"\b9\d{6}\b", text_psm4)
        if not numbers:
            numbers = re.findall(
                r"\b9\d{6}\b", re.sub(r"(?<=\d)\s+(?=\d)", "", text_psm4))
        if numbers:
            log(f"[정보] C.I 헤더 크롭 PSM 6으로 Delivery Number 실패 "
                f"-> PSM 4 재시도로 찾음: {numbers}")
    if not numbers:
        log(f"[경고] C.I 헤더 크롭 OCR로 Delivery Number 추출 실패. "
            f"크롭 OCR 원문(psm6): {text!r} / (psm4): {text_psm4!r}")
    return numbers


# ==============================================================
# 3) 오라클 Fusion 자동화 (Edge 디버그 포트 9333에 접속)
# ==============================================================
def _prevent_edge_session_restore(owner: str = None):
    """Edge 프로필의 Preferences에서 exit_type/exited_cleanly를 정상 종료로
    미리 표시해둔다. 2026-08-03 실측: 자동화 전용 브라우저가 죽은 뒤 재시작되면
    Chromium이 "비정상 종료"로 판단해 그동안 쌓인 탭들을 전부 복원해버려서
    (재시도가 반복되며 탭이 8개 이상까지 쌓인 사례 확인) 화면이 지저분해지고
    이후 자동화 클릭까지 덩달아 불안정해졌다. 새로 실행하기 직전에 항상 이
    값을 정상 종료로 표시해둬서, 어떤 이유로 죽었든 재시작 시 항상 깨끗한
    탭 하나로만 시작하게 한다. 프로필이 아직 없거나(첫 실행) 파일을 못
    읽어도 치명적이지 않으므로 조용히 넘어간다."""
    _, profile_dir = _resolve_edge_target(owner)
    pref_path = os.path.join(profile_dir, "Default", "Preferences")
    try:
        with open(pref_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("profile", {})["exit_type"] = "Normal"
        data["profile"]["exited_cleanly"] = True
        with open(pref_path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"[경고] Edge 세션 복원 방지 설정 실패(무시하고 계속): {e}")


def _kill_automation_edge(owner: str = None):
    """자동화 전용 프로필(owner가 가리키는 프로필)을 사용 중인 msedge 프로세스만
    골라 강제 종료한다. 사용자의 개인 Edge 창은 다른 프로필을 쓰므로 건드리지
    않고, 다른 owner의 분리된 프로필도 건드리지 않는다(2026-09-18 분리 후)."""
    import psutil
    _, profile_dir = _resolve_edge_target(owner)
    killed = 0
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            if proc.info["name"] != "msedge.exe":
                continue
            cmdline = proc.info["cmdline"] or []
            if any(profile_dir in arg for arg in cmdline):
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if killed:
        log(f"[복구] 자동화 전용 Edge 프로세스 {killed}개 강제 종료")
        time.sleep(2)


def _launch_edge(owner: str = None):
    """2026-08-04 실측: 시작 인자로 ORACLE_HOME_URL을 넘겨서 첫 탭이 이미
    오라클 로그인 화면에 가 있게 했었는데, 실제로는 이 4개 자동화(icbl/
    pick_release/ship_confirm/sco_cancel) 전부 각자 작업 시작 시
    get_oracle_driver_isolated()나 _open_plain_tab()으로 새 탭을 열어 쓰지
    이 첫 탭을 재사용하는 곳이 하나도 없음(동시 실행 충돌 방지 + Phase A의
    오라클 미접속 설계가 이유 - 새 탭을 여는 것 자체는 의도된 것). 그 결과
    이 첫 탭만 아무도 안 쓰는 채로 항상 남아있었음 - about:blank로 바꿔서
    쓸모없이 오라클 로그인 화면을 띄우는 것만 없앤다."""
    port, profile_dir = _resolve_edge_target(owner)
    os.makedirs(profile_dir, exist_ok=True)
    _prevent_edge_session_restore(owner)
    subprocess.Popen([
        EDGE_PATH,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--profile-directory=Default",
        "--start-maximized",
        # 2026-08-20 실측으로 확정된 옵션들. 이 창이 사용자의 다른 창에 완전히
        # 가려지면 크로미움의 창 가림 감지(native window occlusion)가 **최대화
        # 상태인데도** 문서를 `visibilityState='hidden'`으로 내려버린다. 그 상태를
        # 진단으로 직접 확인했다: 창은 windowState='maximized'인데 이 프로필의
        # **모든 탭**(새 탭 페이지까지)이 hidden이었고, 그 결과
        #   1) Selenium의 element.send_keys가 **조용히 버려진다**(예외도 없고
        #      DOM의 value도 안 바뀐다 - 8/11부터 "Release Rule이 안 들어간다"로
        #      나타난 증상의 정체),
        #   2) 배경 탭 타이머 스로틀링으로 **ADF의 PPR(서버 왕복)이 안 돈다**
        #      (Release Rule을 CDP로 억지로 넣어도 Order Type 자동채움이 영원히
        #      안 왔다 = 오라클이 입력을 인지조차 못 함).
        # 창을 normal로 되돌리거나 Page.bringToFront/Target.activateTarget을 해도
        # hidden이 안 풀렸다 - 그래서 런타임 우회가 아니라 이 실행 옵션이 해법이다.
        # 이 코드베이스에서 "백그라운드 Edge에서 클릭/입력이 씹힌다"로 반복 기록된
        # 이슈들(selenium-native-click-swallowed)의 공통 원인으로 의심된다.
        "--disable-features=CalculateNativeWinOcclusion",
        "--disable-backgrounding-occluded-windows",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        # 2026-09-18: 7개 스크립트를 owner별 독립 Edge로 분리(edge-per-script-separation
        # 참고)하면서 msedge.exe 프로세스 수가 크게 늘어 메모리 사용량이 눈에 띄게
        # 커짐(실측 7인스턴스 합계 약 3GB). 이 자동화 프로필들은 매 실행마다 오라클/
        # 페덱스/DHL 중 딱 한 사이트만 오가는 단일 목적 로봇이라, 여러 출처를 서로
        # 못 보게 프로세스를 쪼개는 사이트 격리와 렌더링 가속용 GPU 프로세스가 실질
        # 이득 없이 메모리만 잡아먹는다 - 둘 다 끔.
        "--disable-gpu",
        "--disable-site-isolation-trials",
        # 새 프로필을 처음 켤 때 뜨는 "Welcome to Microsoft Edge"/"Customize your
        # browser"/"Check for leaked passwords" 같은 온보딩 탭들이 자동화와 무관하게
        # 뜨면서 탭+프로세스가 쓸데없이 늘어나는 것도 같은 날 실측으로 확인 - 꺼서
        # 방지(기존 탭은 이 옵션과 무관하게 이미 남아있으므로 별도로 닫아야 함).
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ])
    # 2026-07-10 실측: 6초로는 부족해서 막 재시작된 상태로 다른 자동화가 바로
    # 이어서 클릭하면 SPA가 아직 안정화 안 돼 네비게이션이 반복 실패하는
    # 경우가 확인됨(pick_release_watcher.py) - 여유를 더 준다.
    time.sleep(10)


def _force_restart_edge(owner: str = None):
    """자동화 전용 Edge를 강제로 껐다 새로 켠다. 2026-08-03 실측: 브라우저가
    응답 없음/탭 과다 등으로 불안정해지면 재로그인 시도 자체가 계속 실패하는데,
    껐다 켜면 대부분 바로 정상화됨(사용자 확인, "브라우저 죽었으면 그냥 껐다
    켜봐"). 로그인 복구 흐름(main())에서 SSO 자동 재로그인이 실패했을 때
    사람에게 알리기 전 마지막으로 시도하는 자동 복구 수단."""
    log("[복구] 오라클 재로그인 실패 -> 자동화 전용 Edge를 껐다 다시 켜서 재시도")
    _kill_automation_edge(owner)
    _launch_edge(owner)


def _debug_port_open(port: int = None) -> bool:
    import socket
    if port is None:
        port, _ = _resolve_edge_target()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    try:
        s.connect(("127.0.0.1", port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


# 2026-08-06 추가: pick_release_watcher(워커 2개)와 rebalance_watcher(TO 2건
# 동시)는 한 프로세스 안에서 여러 스레드가 각자 오라클 작업을 한다. 이 스레드들이
# "Edge가 안 떠 있다"를 동시에 발견하면 둘 다 _launch_edge()를 불러서 같은 포트에
# Edge를 두 번 띄우려 하고, 두 번째는 포트 바인딩에 실패해 어중간한 상태가 된다.
# 락으로 한 번에 하나만 띄우게 하고, 락을 잡은 사이에 다른 스레드가 이미 띄웠을
# 수 있으므로 락 안에서 한 번 더 확인한다(double-checked locking). 2026-09-18
# 분리 후에도 스레드 하나(=한 owner)당 이 락 하나면 충분 - 마스터 쿠키 시딩용
# ensure_edge_running(MASTER_EDGE_OWNER) 호출도 같은 락을 타지만 포트가 서로
# 다르므로 문제없다(그냥 살짝 덜 병렬적일 뿐).
_EDGE_LAUNCH_LOCK = threading.Lock()


def ensure_edge_running(owner: str = None) -> bool:
    port, _ = _resolve_edge_target(owner)
    if _debug_port_open(port):
        return True

    with _EDGE_LAUNCH_LOCK:
        # 락을 기다리는 동안 다른 스레드가 이미 띄웠을 수 있다 - 다시 확인.
        if _debug_port_open(port):
            return True
        log(f"디버그 포트({port})로 떠 있는 Edge가 없음 -> 새로 실행 시도")
        _launch_edge(owner)
        # 2026-09-14: 예전엔 Popen을 던지고 **포트 확인 없이 바로 True**를
        # 돌려줬다. Edge가 뜨는 데 몇 초 걸리므로 호출부가 곧장 붙으러 갔다가
        # "cannot connect to microsoft edge at 127.0.0.1:9333"으로 실패한다
        # (실측: 2026-09-14 11:30 rebalance 트리거 스캔).
        # 포트가 실제로 열릴 때까지 기다린다.
        deadline = time.time() + EDGE_LAUNCH_WAIT_SEC
        while time.time() < deadline:
            if _debug_port_open(port):
                log(f"Edge 디버그 포트 준비됨({port})")
                return True
            time.sleep(1)
        # 여기까지 왔으면 포트가 안 열린 것이다. 흔한 원인은 **자동화용이 아닌
        # 일반 Edge가 이미 떠 있어서** 새로 띄운 프로세스가 기존 인스턴스에
        # 붙어버리는 것(크로미움 특성 - 디버그 포트가 아예 안 열린다).
        log(f"[경고] Edge를 띄웠지만 디버그 포트 {port}가 "
            f"{EDGE_LAUNCH_WAIT_SEC}초 안에 열리지 않았습니다 - 자동화용이 아닌 "
            f"Edge가 이미 실행 중이면 그쪽에 붙어 포트가 안 열립니다")
        return False
    return True


# ==============================================================
# 드라이버 공통 타임아웃 (2026-08-06 추가)
# ==============================================================
# 배경: 지금까지 어떤 드라이버에도 페이지 로드 타임아웃을 지정하지 않았다.
# Selenium의 기본값은 "무한 대기"라서, 오라클이 응답을 주다 마는 순간(회사망
# 끊김, VPN 재연결, 오라클 점검, SSO 로그인 화면이 뜨다 마는 경우)에
# driver.get()이 영영 돌아오지 않는다. 예외가 안 나므로 try/except도
# run_with_oracle_retry도 전혀 작동하지 못한다.
# 여기에 작업 스케줄러의 실행 제한이 PT72H(72시간)이고 각 자동화가 파일 락
# (_acquire_singleton_lock)을 잡고 있다는 점이 겹치면, 멈춘 프로세스 하나가
# 최대 3일간 살아있으면서 이후 모든 회차를 "이미 실행 중"으로 스킵시킨다.
# 로그에는 "===== 시작 ====="만 남고 알림 메일도 안 나가서(알림 코드까지
# 도달을 못 하므로) 사람이 직접 눈치채기 전까지 자동화가 조용히 멈춘다.
#
# 값은 정상 상황에서는 절대 안 걸리도록 넉넉하게 잡는다 - 여기 걸렸다는 건
# 이미 비정상이라는 뜻이고, 그때는 TimeoutException으로 올라가서 기존 재시도
# 로직(_goto_scheduled_processes의 3회, navigate_to_create_pick_wave의 3회,
# run_with_oracle_retry 등)이 그대로 받아 처리한다. 즉 "무한 정지"를
# "기존 코드가 이미 다룰 줄 아는 예외"로 바꾸는 것이 이 설정의 목적이다.
# 2026-08-10 수정(180/120 -> 90/60): 위 설계는 맞았지만 값이 잘못돼 있어서
# **이 설정이 한 번도 발동할 수 없는 상태**였다. Selenium이 msedgedriver와
# 주고받는 HTTP 클라이언트의 기본 read timeout이 120초인데, 페이지 로드
# 타임아웃을 그보다 큰 180초로 잡아두면 항상 클라이언트가 먼저 포기한다.
# 실측(2026-08-10 10:03:29, AWB 875444946121): SharePoint 조회에서
#   HTTPConnectionPool(host='localhost', port=53810): Read timed out. (read timeout=120)
# 이때 문제는 단순히 '실패했다'가 아니다 - 클라이언트만 손을 뗐을 뿐
# msedgedriver는 그 명령을 여전히 붙잡고 계속 페이지를 열고 있어서, 같은
# 세션으로 보낸 다음 명령이 버려진 응답과 엇갈릴 수 있다(세션 desync).
# 게다가 올라오는 예외가 WebDriverException이 아니라 urllib3 raw 에러라서
# is_session_dead_error() 같은 기존 분류 로직이 판단을 못 한다.
# 두 값 모두 클라이언트 120초보다 **작게** 두어, 드라이버가 먼저 스스로
# 중단하고 정상적인 TimeoutException을 돌려주도록 만든다.
PAGE_LOAD_TIMEOUT_SEC = 90
SCRIPT_TIMEOUT_SEC = 60


def _apply_driver_timeouts(driver):
    """새로 만든 드라이버에 공통 타임아웃을 건다.
    설정 자체가 실패해도 드라이버는 정상 동작하므로(단지 무한 대기 위험이
    남을 뿐) 조용히 넘어가고 드라이버를 그대로 돌려준다."""
    try:
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SEC)
    except Exception as e:
        log(f"[경고] 페이지 로드 타임아웃 설정 실패(무시하고 계속): {e}")
    try:
        driver.set_script_timeout(SCRIPT_TIMEOUT_SEC)
    except Exception as e:
        log(f"[경고] 스크립트 타임아웃 설정 실패(무시하고 계속): {e}")
    return driver


def get_oracle_driver():
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options

    port, _ = _resolve_edge_target()
    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    driver = _apply_driver_timeouts(webdriver.Edge(options=options))

    # 2026-07-08: 이전 실행이 실패하면 리포트 뷰어 팝업(xmlpserver 도메인)이
    # 안 닫힌 채로 남을 수 있음 - 그 팝업을 메인 창으로 잘못 잡으면 창 크기가
    # 작아서 UI가 다르게 렌더링되어 이후 단계가 연쇄적으로 실패함(실측 확인).
    # 메인 앱(fscmUI) 창을 우선 채택하고, 남은 리포트 뷰어 팝업은 정리한다.
    main_handle = None
    stale_handles = []
    for h in driver.window_handles:
        driver.switch_to.window(h)
        try:
            url = driver.current_url
        except Exception:
            continue
        if "fscmUI" in url and main_handle is None:
            main_handle = h
        elif "xmlpserver" in url:
            stale_handles.append(h)

    for h in stale_handles:
        try:
            driver.switch_to.window(h)
            driver.close()
        except Exception:
            pass

    if main_handle:
        driver.switch_to.window(main_handle)
        return driver

    for h in driver.window_handles:
        driver.switch_to.window(h)
        if "oraclecloud.com" in driver.current_url:
            return driver
    # 오라클 탭이 아예 없으면 첫 탭에 강제 이동
    driver.switch_to.window(driver.window_handles[0])
    driver.get(ORACLE_HOME_URL)
    return driver


def get_oracle_driver_isolated():
    """2026-07-10: icbl_ci_watcher와 pick_release_watcher가 겹쳐서 같은 탭을
    쓰면(둘 다 클릭/입력을 하는 중) 서로 충돌해서 stale element, 요소 못 찾음
    등 연쇄 오류가 난다(실측 확인). 겹치는 게 감지되면(오라클 락이 상대방
    소유) 기존 메인 탭을 건드리지 않고 새 탭을 열어서 그 탭만 쓴다 - 로그인
    세션(쿠키)은 프로필 전체에 공유되므로 새 탭도 이미 로그인된 상태로
    시작한다. 호출부에서 작업이 끝나면 driver.close()로 이 탭을 닫아야 함
    (안 닫으면 탭이 계속 쌓임)."""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options
    from selenium.common.exceptions import NoSuchWindowException

    port, _ = _resolve_edge_target()
    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")

    # 2026-09-18: Edge를 방금 새로 띄운 직후(탭이 1개뿐인 불안정한 상태)
    # 이 디버그 포트를 같이 쓰는 다른 자동화(rebalance_watcher 등)가 하필 같은
    # 순간에 탭을 열고닫으면, switch_to.new_window()가 NoSuchWindowException
    # ("target window already closed")으로 죽는다 - 실측: 같은 날 10:01:20
    # ship_confirm_watcher가 이 경로에서 크래시(로그에 "시작" 이후 아무 줄도
    # 안 남고 종료). get_sharepoint_driver()에 적용해 검증된 것과 동일한
    # 재시도(quit 후 재접속하면 그 시점 최신 창 목록을 다시 봄)를 여기에도 적용.
    last_err = None
    for attempt in range(3):
        driver = None
        try:
            driver = _apply_driver_timeouts(webdriver.Edge(options=options))
            driver.switch_to.new_window("tab")
            _remember_my_tab(driver)
            driver.get(ORACLE_HOME_URL)
            time.sleep(2)
            return driver
        except NoSuchWindowException as e:
            last_err = e
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
            time.sleep(3)
    raise last_err


# ==============================================================
# 죽은 세션 판별 (2026-08-06 추가)
# ==============================================================
# 배경: 로그를 집계해보니 "세션이 이미 끊긴 상태에서 계속 재시도하는" 패턴이
# icbl 16건 + pick_release 8건 있었다. 실제 로그(2026-07-23 00594693):
#   14:34:45  화면 이동 실패(시도 1/3) - invalid session id
#   14:34:50  화면 이동 실패(시도 2/3) - invalid session id
#   14:34:55  화면 이동 실패(시도 3/3) - invalid session id
# 브라우저와의 연결 자체가 끊긴 상태라 같은 driver로는 몇 번을 다시 해도 결과가
# 100% 같다. 시간(15~45초)만 버리는 것도 문제지만, 더 나쁜 건 로그가 "3번이나
# 시도했는데 화면을 못 찾았다"처럼 보여서 오라클 화면 문제로 오진하게 만든다는
# 점이다(실제로는 브라우저를 다시 붙이기만 하면 풀리는 문제).
# 그래서 이 종류의 예외는 재시도 대상에서 빼고, 로그에 원인을 명확히 남긴다.
_SESSION_DEAD_MARKERS = (
    "invalid session id",
    "session deleted",
    "not connected to devtools",
    "no such window",
    "target window already closed",
    "web view not found",
    "chrome not reachable",
    "unable to connect to renderer",
    "browser has closed the connection",
)


def is_session_dead_error(exc) -> bool:
    """예외가 '브라우저 세션/연결 자체가 끊긴' 종류인지 판단한다.
    True면 같은 driver로 재시도해봐야 의미가 없다는 뜻."""
    try:
        from selenium.common.exceptions import (
            InvalidSessionIdException,
            NoSuchWindowException,
            WebDriverException,
        )
    except Exception:
        return False
    if isinstance(exc, (InvalidSessionIdException, NoSuchWindowException)):
        return True
    if not isinstance(exc, WebDriverException):
        return False
    msg = (str(exc) or "").lower()
    return any(k in msg for k in _SESSION_DEAD_MARKERS)


def close_driver(driver) -> None:
    """이 실행이 쓰던 드라이버를 완전히 끝낼 때 부른다 - 내가 연 탭을 닫고
    (close) 드라이버 프로세스까지 정리한다(quit).

    2026-08-06 추가. 배경: 지금까지 모든 자동화가 driver.close()만 불렀는데,
    close()는 '탭'만 닫을 뿐 msedgedriver.exe 프로세스는 그대로 남긴다
    (webdriver.Edge()를 호출할 때마다 msedgedriver.exe가 하나씩 새로 뜬다).
    실측 확인: 부모 파이썬 프로세스가 끝난 지 3시간이 지난 고아
    msedgedriver.exe가 그대로 살아있었다. 특히 pick_release_watcher는 주문
    1건마다 드라이버를 새로 만들기 때문에(재시도 최대 3회 x 워커 2개) 한
    회차에 수십 개까지 쌓일 수 있다. 개당 16~20MB이고 재부팅 전까지
    사라지지 않는다.

    quit()이 공유 Edge까지 죽이지는 않는지 별도 프로필/포트로 실측 검증함
    (2026-08-06): debuggerAddress로 '붙은' 드라이버는 브라우저를 자기가 띄운
    게 아니라서, quit()을 해도 msedgedriver만 정리되고 Edge 프로세스와 디버그
    포트는 그대로 살아있다(검증 후 재접속해서 탭 조회까지 정상 확인). 즉 같은
    Edge를 공유하는 다른 자동화에 영향이 없다.

    주의: 리포트 뷰어 팝업을 닫는 것처럼 '작업 도중 탭 하나만 닫는' 자리에는
    절대 쓰면 안 된다(세션 자체가 끝나버림) - 그런 자리는 driver.close()를
    그대로 둔다."""
    if driver is None:
        return
    try:
        driver.close()
    except Exception:
        pass
    try:
        driver.quit()
    except Exception:
        pass


# 이번 실행이 자기 작업용으로 연 탭(아래 _ensure_my_tab 참고).
# 2026-08-06: 모듈 전역 변수 하나로 기억하면, 한 프로세스 안에서 여러 스레드가
# 각자 get_oracle_driver_isolated()로 자기 탭을 열 때 서로의 핸들을 덮어쓴다.
# 이 함수를 쓰는 자동화 중 pick_release_watcher는 이미 워커 2개로 돌고,
# rebalance_watcher도 2026-08-06부터 TO 2건을 동시에 처리하므로 실제 위험이다 -
# 그러면 _ensure_my_tab이 워커 A의 driver를 워커 B의 탭으로 되돌려버려서,
# 이 함수가 막으려던 "남의 탭을 조작하는" 사고를 오히려 스스로 만든다.
# 스레드별로 따로 기억한다.
_MY_TAB = threading.local()


def _remember_my_tab(driver):
    try:
        _MY_TAB.handle = driver.current_window_handle
    except Exception:
        _MY_TAB.handle = None


def _ensure_my_tab(driver) -> None:
    """2026-08-06: 진단 스크린샷(_diag_pidfilter_20260806_1033*.png)에서 이 스크립트의
    driver가 오라클 Inventory Management 화면(= 재고 재배치/출고 자동화가 쓰는 화면,
    이 스크립트는 절대 안 가는 곳)을 보고 있는 게 확인됐다 - 같은 Edge(포트 9333)를
    공유하는 다른 자동화의 탭을 보고 있었던 것. 그 상태에서 Process ID 검색 필드를
    찾으니 당연히 없고, 그래서 매 폴링이 느린 스크롤 폴백으로 떨어졌다.
    내가 연 탭이 아직 살아있는데 다른 탭을 보고 있으면 내 탭으로 되돌린다(남의 탭을
    내 화면으로 덮어쓰지 않는 것도 중요 - 상대 자동화가 깨진다)."""
    handle = getattr(_MY_TAB, "handle", None)
    if not handle:
        return
    try:
        if driver.current_window_handle == handle:
            return
    except Exception:
        pass
    try:
        if handle in driver.window_handles:
            driver.switch_to.window(handle)
            log("[정보] 다른 탭을 보고 있어서 이 실행이 연 탭으로 되돌림")
    except Exception as e:
        # 2026-08-06: 이 복귀가 실패하면 '남의 자동화 탭에서 계속 작업하는'
        # 상태가 된다 - 진단 스크린샷으로 실제 확인된 사고 경로다(이 함수의
        # docstring 참고). 예전엔 조용히 넘어가서 그 뒤 이어지는 "요소를 못
        # 찾음" 실패의 진짜 원인을 알 수 없었다. 흐름은 그대로 두고(여기서
        # 예외를 올리면 처리 순서가 바뀌므로) 원인만 남긴다.
        log(f"[경고] 내 탭으로 되돌리기 실패({type(e).__name__}: {e}) - "
            f"다른 자동화의 탭에서 작업하게 될 수 있어 이후 '요소를 못 찾음'이 "
            f"발생하면 이 줄을 먼저 의심할 것")


def _on_scheduled_processes(driver) -> bool:
    """지금 화면이 Scheduled Processes(Monitor Processes)인지 - 이 화면에만 있는
    'Schedule New Process' 버튼 유무로 판정."""
    try:
        driver.switch_to.default_content()
        return any(el.is_displayed() for el in driver.find_elements(
            "xpath", "//*[normalize-space(text())='Schedule New Process']"))
    except Exception:
        return False


def _open_plain_tab():
    """2026-08-03: Phase A(메일 OCR 추출)에서 WAY 재배치 판별(SharePoint 조회)에만
    필요한 가벼운 탭. 오라클 페이지로 이동하거나 로그인 확인을 하지 않는다 -
    추출 단계는 대부분 오라클이 전혀 필요 없는데(OCR은 로컬 처리), 정보 부족으로
    매번 "사람 확인 필요" 알림만 내고 끝나는 건도 신규 메일로는 계속 잡혀서
    (state에 안 남으므로) 예전에는 이 단계 전에 무조건 오라클 로그인 확인/복구
    (SSO 재로그인 실패 시 Edge 강제 재시작까지)를 반복했었다(실측: 제출할 게
    없는데도 매 20분 주기마다 반복). 오라클 로그인 확인은 main()에서 Phase A
    결과로 실제 제출할 case가 나온 뒤로 미룬다."""
    from selenium import webdriver
    from selenium.webdriver.edge.options import Options

    port, _ = _resolve_edge_target()
    options = Options()
    options.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    driver = _apply_driver_timeouts(webdriver.Edge(options=options))
    driver.switch_to.new_window("tab")
    _remember_my_tab(driver)
    return driver


def oracle_is_logged_in(driver) -> bool:
    """2026-08-03 실측: 세션이 끊겨 IDCS Sign In 페이지로 리다이렉트된 직후, 페이지
    title이 곧바로 최종값("Cloud Sign In")으로 안 뜨고 몇 초간 중간값("Identity
    Cloud Service")을 거쳐감(그 사이엔 title에 "Sign In"이 없어 로그인된 것으로
    오판할 위험). 반면 URL은 리다이렉트 직후부터 이미 "/ui/v1/signin"으로 바로
    안정적이었음 - title 판정에만 의존하지 않도록 URL에 "signin" 포함 여부도
    같이 확인해 오탐을 줄인다.

    2026-08-06(2차) 실측: 이 판정이 **오류 페이지를 '로그인됨'으로 오판**한다.
    IDCS 루트(https://idcs-.../)로 가면 "401 Authorization Required"가 뜨는데,
    그 페이지는 title에 "Sign In"도 없고 URL에 login/signin도 없어서 이 함수가
    True를 돌려줬다(실측 확인). 그러면 호출부가 "로그인돼 있네"라고 믿고 SSO
    복구를 아예 건너뛴 뒤, 이후 단계에서 "요소를 못 찾음"으로 엉뚱하게 실패한다
    - 복구 기회를 스스로 날리는 셈이라 자동 복구율을 깎아먹는다.
    그래서 '아닌 것을 배제'하는 기존 조건에 더해, **실제로 오라클 앱 도메인에
    있는지**라는 긍정 조건을 하나 추가한다(로그인 성공 시 URL은 항상 이
    도메인이고, 세션이 끊기면 IDCS/마이크로소프트 도메인으로 넘어간다)."""
    time.sleep(2)
    url = driver.current_url.lower()
    on_app = ORACLE_APP_HOST in url
    return (on_app
            and "Sign In" not in driver.title
            and "login" not in url
            and "signin" not in url)


def _select_saved_search(driver, text: str):
    """Scheduled Processes 화면 우측 상단 'Saved Search' 드롭다운(기본값
    'Last hour')을 변경한다. 2026-07-10 사용자 확인: FBC 건은 완료가 1시간을
    넘기는 경우가 있는데, 'Last hour' 필터 그대로 두면 그 시점 이후 내
    프로세스 행이 검색 결과 자체에서 빠져버려서 새로고침해도 안 나타남 ->
    'Last 24 hours' 등으로 넓혀서 계속 보이게 한다. 옵션 선택 시 ADF가 자동으로
    결과를 다시 조회하므로 별도 검색 버튼 클릭은 필요 없음(실측 확인).
    select_by_visible_text는 완전일치라 문구가 정확해야 한다 - 2026-08-07 실측한
    실제 항목: Cancelable Processes / Last 12 hours / Last 24 hours /
    Last 48 hours / Last 72 hours / Last hour(기본값)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    sel_el = driver.find_element(By.CSS_SELECTOR, "select[id*='saveSearch']")
    Select(sel_el).select_by_visible_text(text)
    time.sleep(3)


SSO_RELOGIN_TIMEOUT_SEC = 120  # 2026-08-06: MFA/추가인증 화면 대응 위해 늘림(아래 함수 설명 참고)
SSO_RELOGIN_POLL_SEC = 2

# 2026-08-06(2차) 실측: 'Sign in with AzureAD' 버튼은 로그인 페이지가 뜬 뒤
# **1.0~8.4초 늦게** 렌더링된다(5회 측정: 1.0/1.2/1.2/1.3/1.5초, 이후 재측정에서
# 7.6/8.2/8.4초까지 관측 - 편차가 크다). 그런데 기존 코드는 대기 없이 딱 한 번만
# 찾고 없으면 즉시 False를 반환했다. 그래서 "버튼이 없다"고 오판 -> Edge 강제
# 재시작 -> (콜드 부팅이라 더 느림) -> 또 즉시 확인 -> 또 실패 -> 사람에게 알림,
# 이라는 자기가 만든 악순환에 빠졌다. 실제로 이 상태로 자동 복구가 전부 실패하고
# 있었다(2026-08-06 15:30 확인). 버튼이 나타날 때까지 기다린다.
SSO_BUTTON_WAIT_SEC = 30

# 2026-08-06(2차) 실측: MS 계정 선택 화면의 계정 타일은 Selenium의 is_displayed()가
# **False로 나온다**(화면에는 분명히 보이는데도). 원인은 이 코드베이스에 이미
# 기록된 것과 같은 뿌리 - 무인 실행 중 Edge 창이 백그라운드라 페이드인 애니메이션
# 프레임이 스로틀돼서 opacity가 끝까지 안 올라간다. 실측 결과:
#   contains(text(),'yoongil.chae@candelamedical.com') -> 2개 발견, is_displayed() 통과 0개
#   JS의 offsetParent 기준 -> 정상적으로 보이는 요소로 검출됨
# 기존 코드는 is_displayed()로 걸러서 타일을 영영 못 찾았고(90초를 기다려도 0회),
# 그래서 AzureAD 버튼까지는 눌렀는데 계정 선택 화면에서 멈춰 있었다.
# is_displayed()에 의존하지 않고 JS 가시성(offsetParent)으로 찾아 JS 클릭한다
# (_find_menu_item이 같은 이유로 이미 JS 방식을 쓰고 있다).
_JS_CLICK_VISIBLE_TEXT = """
var want = arguments[0];
var nodes = document.querySelectorAll('*');
for (var i = 0; i < nodes.length; i++) {
  var e = nodes[i];
  if (e.children.length !== 0) continue;          // 말단 텍스트 요소만
  if ((e.textContent || '').indexOf(want) < 0) continue;
  if (e.offsetParent === null) continue;          // 실제로 화면에 없음
  var t = e;                                       // 클릭 가능한 조상까지 올라감
  for (var k = 0; k < 6 && t.parentElement; k++) {
    var r = t.getAttribute('role') || '';
    var c = (t.className || '').toString();
    if (r === 'button' || /tile|table|row/.test(c)) break;
    t = t.parentElement;
  }
  t.click();
  return t.tagName + '.' + ((t.className || '').toString().slice(0, 40));
}
return null;
"""

SSO_ACCOUNT_EMAIL = "yoongil.chae@candelamedical.com"


def _seed_cookies_from_master(driver, log_fn=None) -> bool:
    """2026-09-18 완전 분리 도입: 마스터(icbl_ci_watcher) 프로필이 실제 사람의
    SSO 로그인으로 쌓아온 세션 쿠키를 CDP로 읽어와, 지금 이 owner의 driver에
    실시간으로 주입한다. 파일 복사가 아니라 브라우저간 쿠키 값 복제인 이유:
    마스터 Edge가 켜져 있는 동안 그 프로필의 Cookies SQLite 파일은 OS 레벨로
    계속 잠겨 있어서(실측 확인, `Device or resource busy`) 파일 복사 자체가
    불가능하다. CDP `Network.getAllCookies`/`Network.setCookie`는 파일을 안
    건드리고 살아있는 브라우저에 값만 물어보고 넣어주므로 마스터가 실행 중이든
    아니든 안전하다.

    실측(2026-09-18)으로 확정된 대상 도메인(SSO_COOKIE_DOMAIN_KEYWORDS) -
    오라클 자체 도메인(*.oraclecloud.com)에는 Akamai 봇매니저 쿠키만 있고,
    실제 "로그인 유지"의 핵심은 회사 Azure AD 연동
    (login.microsoftonline.com의 ESTSAUTHPERSISTENT 등)과 SharePoint(FedAuth)
    쪽에 있다 - 이 셋만 복제하면 이후 `sso_relogin()`의 SSO 버튼 클릭이 MFA
    없이 그대로 통과한다(FuseWelcome 도착까지 실측 검증됨).

    마스터가 icbl_ci_watcher 자신이면(현재 owner가 마스터) 아무것도 하지 않고
    True를 돌려준다 - 자기 자신에게서 복제할 필요가 없다."""
    _log = log_fn or log
    if _CURRENT_EDGE_OWNER["name"] == MASTER_EDGE_OWNER:
        return True
    try:
        master_port, _ = _resolve_edge_target(MASTER_EDGE_OWNER)
        if not ensure_edge_running(MASTER_EDGE_OWNER):
            _log("[경고] 쿠키 시딩용 마스터 Edge를 띄우지 못함 - 시딩 생략")
            return False

        from selenium import webdriver
        from selenium.webdriver.edge.options import Options
        opts = Options()
        opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{master_port}")
        master_driver = webdriver.Edge(options=opts)
        try:
            cookies = master_driver.execute_cdp_cmd("Network.getAllCookies", {})["cookies"]
        finally:
            # 2026-09-18: 이 quit()은 지금 붙인 원격 세션만 끊을 뿐, debuggerAddress로
            # 붙은 마스터의 실제 브라우저 프로세스는 안 죽는다
            # (selenium-stability-hardening-2026-08-06 - "quit()은 붙은 Edge 안 죽임" 실증
            # 과 동일 원리, 여기서는 오히려 그 특성이 안전장치가 됨).
            try:
                master_driver.quit()
            except Exception:
                pass

        seeded = 0
        for c in cookies:
            domain = c.get("domain", "")
            if not any(kw in domain for kw in SSO_COOKIE_DOMAIN_KEYWORDS):
                continue
            payload = {
                "name": c["name"], "value": c["value"], "domain": domain,
                "path": c.get("path", "/"), "secure": c.get("secure", False),
                "httpOnly": c.get("httpOnly", False),
            }
            if c.get("sameSite"):
                payload["sameSite"] = c["sameSite"]
            if c.get("expires") and c["expires"] > 0:
                payload["expires"] = c["expires"]
            try:
                driver.execute_cdp_cmd("Network.setCookie", payload)
                seeded += 1
            except Exception as e:
                _log(f"[경고] 쿠키 시딩 실패({c.get('name')}, {domain}): {exc_detail(e)}")
        _log(f"[정보] 마스터 프로필에서 SSO 쿠키 {seeded}개 시딩함")
        return seeded > 0
    except Exception as e:
        _log(f"[경고] 마스터 쿠키 시딩 중 오류(무시하고 계속): {exc_detail(e)}")
        return False


def sso_relogin(driver, log_fn=None) -> bool:
    """오라클 SSO(AzureAD) 자동 재로그인 - 4개 자동화가 공유하는 실제 구현.

    각 파일의 `_try_sso_relogin(driver)`이 자기 log()를 넘겨 이 함수를 부른다
    (로그는 각자의 로그 파일에 그대로 남는다). 2026-08-06에 같은 로직 복사본
    4벌의 대기시간이 24초/48초로 어긋나 있던 걸 발견한 적이 있어, 구현을 하나로
    모아 그런 드리프트가 다시 생기지 않게 한다.

    2026-08-06(2차) 실측으로 확인한 '자동 복구가 실패하던 진짜 이유' 2가지를
    여기서 고친다 - 둘 다 위 상수/JS 주석에 근거를 적어두었다:
      (1) AzureAD 버튼을 대기 없이 한 번만 찾아서, 늦게 뜨는 버튼을 '없다'고 오판
      (2) MS 계정 타일을 is_displayed()로 걸러서, 백그라운드 창에서 영영 못 찾음
    이 둘을 고친 뒤 실제로 사람 개입 없이 오라클 홈까지 로그인되는 것을 확인함
    (AzureAD 버튼 8.2초에 발견 -> 계정 타일 2.9초에 클릭 -> FuseWelcome 도착).

    쿠키까지 만료돼서 정말 로그인이 안 되는 경우엔 예전처럼 False를 반환해
    호출부의 기존 흐름(브라우저 재시작 -> 그래도 안 되면 사람에게 알림)으로
    넘어간다 - 자동 우회는 하지 않는다."""
    from selenium.webdriver.common.by import By

    _log = log_fn or log

    def _click_account_tile():
        """MS 계정 선택 화면이 떠 있으면 내 계정 타일을 눌러준다(있을 때만)."""
        try:
            return driver.execute_script(_JS_CLICK_VISIBLE_TEXT, SSO_ACCOUNT_EMAIL)
        except Exception:
            return None

    try:
        # 2026-09-18: 분리된 owner(마스터가 아닌 6개 스크립트)는 SSO 버튼을
        # 누르기 전에 마스터의 살아있는 세션 쿠키를 먼저 복제해온다 - 이 쿠키가
        # 있어야 아래 버튼 클릭이 MFA 없이 통과한다(실측 검증됨). 마스터
        # 자신이면 _seed_cookies_from_master가 즉시 True를 돌려주고 아무것도
        # 안 한다.
        _seed_cookies_from_master(driver, _log)

        # --- (1) 버튼이 렌더될 때까지 기다린다 ---
        btn = None
        deadline = time.time() + SSO_BUTTON_WAIT_SEC
        while time.time() < deadline:
            try:
                els = [el for el in driver.find_elements(
                    By.XPATH, "//*[contains(text(),'AzureAD')]") if el.is_displayed()]
                if els:
                    btn = els[0]
                    break
            except Exception:
                pass
            time.sleep(0.25)
        if btn is None:
            _log(f"[경고] SSO 재로그인: 'Sign in with AzureAD' 버튼이 "
                 f"{SSO_BUTTON_WAIT_SEC}초 안에 나타나지 않음")
            return False

        # 무인 실행 중엔 창이 백그라운드라 일반 click()이 씹히므로 JS 클릭
        # (2026-08-03 실측, _js_click_text 설명과 같은 이유).
        driver.execute_script("arguments[0].click();", btn)

        # --- (2) 로그인 완료까지 대기하며, 계정 선택 화면이 뜨면 타일을 눌러준다 ---
        deadline = time.time() + SSO_RELOGIN_TIMEOUT_SEC
        tile_clicked = False
        while time.time() < deadline:
            if oracle_is_logged_in(driver):
                return True
            if not tile_clicked:
                hit = _click_account_tile()
                if hit:
                    tile_clicked = True
                    _log(f"[정보] SSO 재로그인: MS 계정 선택 타일 클릭({hit})")
            time.sleep(SSO_RELOGIN_POLL_SEC)

        _log(f"[경고] SSO 재로그인: 버튼은 눌렀지만 약 {SSO_RELOGIN_TIMEOUT_SEC}초 뒤에도 "
             f"로그인 확인 안 됨(MFA 등 추가 인증 대기 포함, 계정타일 클릭="
             f"{tile_clicked})")
        return False
    except Exception as e:
        _log(f"[경고] SSO 자동 재로그인 시도 실패: {exc_detail(e)}")
        return False


def _try_sso_relogin(driver) -> bool:
    """세션이 끊겨 Sign In 페이지에 있으면 SSO 버튼을 눌러 재로그인을 시도한다.
    실제 구현은 위 `sso_relogin()`에 있다(4개 자동화가 공유 - 예전엔 파일마다
    복사본을 두다가 대기시간이 24초/48초로 어긋난 적이 있어 하나로 모았다).
    이 파일의 log()를 넘겨서 로그는 그대로 이 파일의 로그에 남는다."""
    return sso_relogin(driver, log)


def recover_oracle_login(driver, log_fn=None, open_driver=None, allow_restart=True):
    """오라클 로그인 복구 '사다리'. 반환: (성공여부, 앞으로 쓸 driver)

    2026-08-06(2차) 사용자 요청으로 순서를 바꿨다. 예전 순서는
    `SSO 시도 -> 실패하면 곧바로 Edge 강제 재시작`이었는데, 실측해보니 그
    2순위가 잘못돼 있었다:
      - Edge 강제 재시작은 **콜드 부팅**이라 로그인 페이지 렌더가 오히려 더
        느려진다. SSO 버튼이 늦게 뜨는 게 원래 실패 원인이었으므로(1.0~8.4초),
        재시작은 그 원인을 악화시키는 쪽이었다.
      - 반면 **같은 탭에서 오라클 URL을 다시 여는 것**만으로 바로 풀리는 경우가
        확인됐다(실측: 1회차엔 버튼을 못 찾았는데 2회차엔 3초 만에 발견).
    그래서 싼 수단을 앞에, 비싼 수단을 뒤에 두는 사다리로 재배치한다.

      0) 이미 로그인되어 있으면 즉시 성공(아무것도 하지 않음)
      1) SSO 재로그인 시도(버튼 최대 SSO_BUTTON_WAIT_SEC초 대기)
      2) 실패 시 -> 오라클 URL 재진입 후 다시 확인/SSO 재시도  ← 가볍고 효과적
      3) 그래도 실패 시 -> Edge 강제 재시작 후 SSO 재시도       ← 무거워서 3순위
      4) 전부 실패 -> (False, driver) 반환. 사람 알림은 **호출부가** 기존 그대로
         처리한다(이 함수는 알림을 보내지 않는다 - 자동화마다 문구/수신자가 달라서).

    open_driver: 3단계에서 Edge를 재시작한 뒤 새 드라이버를 만드는 콜백.
    호출부마다 쓰는 팩토리가 달라 주입받는다(기본값 get_oracle_driver_isolated).
    **3단계를 타면 드라이버가 새로 만들어지므로 반환된 driver를 반드시 쓸 것.**
    (3단계에서 드라이버 생성까지 실패하면 driver가 None으로 반환될 수 있다 -
     호출부의 close_driver(None)은 안전하게 무시하도록 되어 있다.)

    allow_restart=False: 3단계(Edge 재시작)를 건너뛴다. 호출부가 이미 방금
    Edge를 재시작한 뒤라서 또 재시작해봐야 의미가 없는 경우에 쓴다
    (rebalance_watcher.py의 _restart_browser_and_login)."""
    _log = log_fn or log
    _open = open_driver or get_oracle_driver_isolated

    # --- 0) 이미 로그인? ---
    if oracle_is_logged_in(driver):
        return True, driver

    # --- 1) SSO 재로그인 ---
    if sso_relogin(driver, _log):
        _log("[복구] 1단계: 세션 끊김 감지 -> SSO 자동 재로그인 성공")
        time.sleep(5)  # 재로그인 직후 홈 렌더 대기(기존 호출부 동작 유지)
        return True, driver

    # --- 2) 오라클 URL 재진입 후 재시도(가장 싼 복구) ---
    _log("[복구] 1단계 SSO 실패 -> 2단계: 오라클 URL 재진입 후 재시도")
    try:
        _ensure_my_tab(driver)
        driver.get(ORACLE_HOME_URL)
        if oracle_is_logged_in(driver):
            _log("[복구] 2단계: URL 재진입만으로 로그인 확인됨")
            time.sleep(5)
            return True, driver
        if sso_relogin(driver, _log):
            _log("[복구] 2단계: URL 재진입 후 SSO 재로그인 성공")
            time.sleep(5)
            return True, driver
    except Exception as e:
        _log(f"[복구] 2단계(URL 재진입) 중 오류: {exc_detail(e)}")

    # --- 3) Edge 재시작 후 재시도(마지막 자동 수단) ---
    if not allow_restart:
        _log("[복구] 2단계 실패 -> 3단계(Edge 재시작)는 호출부가 이미 재시작한 "
             "직후라 건너뜀")
        return False, driver
    _log("[복구] 2단계 실패 -> 3단계: 자동화 전용 Edge 재시작 후 재시도")
    close_driver(driver)
    driver = None
    try:
        _force_restart_edge()
        driver = _open()
        if oracle_is_logged_in(driver) or sso_relogin(driver, _log):
            _log("[복구] 3단계: Edge 재시작 후 오라클 로그인 확인됨")
            time.sleep(5)
            return True, driver
    except Exception as e:
        _log(f"[복구] 3단계(Edge 재시작) 중 오류: {exc_detail(e)}")

    _log("[복구] 1~3단계 자동 복구 모두 실패 -> 사람이 직접 로그인해야 함")
    return False, driver


# Tools 메뉴에서 Scheduled Processes 항목이 렌더될 때까지 기다리는 최대 시간(2026-08-06)
SCHED_PROC_RENDER_TIMEOUT_SEC = 20

# 2026-08-07: send_keys가 조용히 씹힐 때(배경 창 문제 - _js_click_text 설명 참고)
# 쓰는 폴백. 값만 바꾸면 ADF가 모르므로 input/change/keyup을 직접 발생시킨다.
# 이 방식이 서버 검색 조건까지 실제로 반영되는 것을 확인함(_diag_js_type.py:
# 15일 지난 Process ID 48662766을 이 방식으로 넣어 검색 성공).
SET_INPUT_VALUE_JS = """
var el = arguments[0], v = arguments[1];
el.focus();
el.value = v;
el.dispatchEvent(new Event('input', {bubbles: true}));
el.dispatchEvent(new Event('change', {bubbles: true}));
el.dispatchEvent(new KeyboardEvent('keyup', {bubbles: true}));
el.blur();
return el.value;
"""

# Scheduled Processes 화면에서 쓸 Saved Search(2026-08-07 사용자 지정).
# 기본값 'Last hour'로는 전날 저녁에 제출한 걸 다음날 아침에 확인할 때 안 잡힌다.
# 드롭다운 실제 항목(2026-08-07 확인): Cancelable Processes / Last 12 hours /
# Last 24 hours / Last 48 hours / Last 72 hours / Last hour.
SCHED_PROC_SAVED_SEARCH = "Last 24 hours"

# Schedule New Process 다이얼로그 관련(2026-08-07 실측으로 확정 - _do_schedule_new_process 설명 참고)
SNP_NAME_CSS = "input[id$='selectOneChoice2::content']"   # 다이얼로그의 Name 입력칸
SNP_OK_BTN_CSS = "button[id$='snpokbtnid']"               # 다이얼로그의 진짜 OK 버튼
SNP_PROCESS_NAME = "Print Commercial Invoice Report"
SNP_NAME_RENDER_TIMEOUT_SEC = 30   # 다이얼로그가 뜬 뒤 Name 칸이 나타날 때까지
SNP_OK_ENABLE_TIMEOUT_SEC = 30     # Tab(LOV 검증 서버 왕복) 후 OK가 활성화될 때까지
# 2026-08-14: Name 칸에 프로세스명을 넣어보는 총 횟수와 회차 간 대기.
# 처음엔 "ADF 바인딩이 느려서 지워진다"고 보고 3회 -> 6회로 늘렸는데, 같은 날
# 실측으로 그 진단이 **틀렸음이 드러나** 원래 3회로 되돌렸다. TO 7872710 통계:
#   - 망가진 라운드는 6회를 다 써도 매번 value=''로 단 한 번도 안 붙음(3라운드 × 6회)
#   - 건강한 라운드는 1~2회차에 바로 붙음(17:43:51에 2회차로 성공)
# 즉 붙을 라운드는 3회 안에 붙고, 안 붙을 라운드는 6회를 줘도 안 붙는다 -
# 4·5·6회차는 라운드당 11초를 버리기만 했다. 이 라운드가 '망가진' 상태일 때의
# 실제 해법은 재입력이 아니라 **화면을 새로 여는 것**(_do_schedule_new_process를
# 감싸는 submit_oracle_ci_report의 3회 루프)이고, 더 근본적으로는 Edge를 껐다 켜
# 세션을 되살리는 것이었다(그날 이걸 뚫은 건 rebalance_watcher의 _RESTART_HINTS에
# "Tools 탭을 못 찾음"을 추가해 에스컬레이션이 발동하게 만든 수정이다).
# 아래 회차별 로그는 남겨둔다 - 이 진단을 가능하게 해준 게 그 로그였다.
SNP_NAME_ENTRY_ATTEMPTS = 3
SNP_NAME_RETRY_WAIT_SEC = 2.5
SNP_PARAM_RENDER_TIMEOUT_SEC = 30  # OK 후 파라미터 입력 화면이 뜰 때까지


def _goto_scheduled_processes(driver, attempts: int = 3) -> None:
    """Tools > Scheduled Processes 로 이동. 2026-08-03 실측: 동시처리 리팩터링으로
    한 실행 안에서 이 탭을 재사용해 여러 건을 연달아 제출하게 됐는데, 그 중
    "Scheduled Processes" 클릭이 (특히 로그인 직후 첫 시도에서) 가끔 못 찾는
    현상이 확인됨(재현 시도에선 같은 코드가 바로 성공해서 타이밍성 플레이키니스로
    추정). 원인을 확정하기보다 완전한 재현 실패에 대비해, 실패하면 페이지를
    새로 고쳐서 처음부터 다시 시도하는 재시도를 추가한다.
    2026-08-06 실측(10:04 회차, DHL 1670899683): 3차까지 전부 "클릭할 요소를 못
    찾음: Scheduled Processes"로 실패하고 바깥 재시도의 4번째 시도에서 바로
    성공했다 - 즉 화면이 안 뜨는 게 아니라 Tools 클릭 후 springboard 아이콘
    렌더가 늦은 것뿐이었다(고정 sleep(1) + _click_text 자체 재시도 2초 =
    약 3초 창이 모자랐음). 고정 대기를 없애고 항목이 실제로 보일 때까지
    기다린다."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    # 2026-08-06 실측(진단 _diag_nav_*.png): 'Scheduled Processes' 아이콘은 Tools를
    # 누르기 **전에도 이미 화면에 보인다**(홈 기본 탭에 rect y=412). Tools를 누르면
    # 앱 그리드가 다시 배치되면서 같은 아이콘이 y=202로 **이동**한다. 그래서 "보이면
    # 통과"인 조건은 Tools 클릭 직후 즉시 만족되고, 아이콘이 아직 움직이는 중에
    # 클릭해서 빈 곳을 누른다 - 화면은 안 넘어가는데 예외도 안 난다(이번 nav 실패의
    # 원인). 좌표가 두 번 연속 같을 때까지(=배치가 끝날 때까지) 기다린 뒤 클릭한다.
    def _text_is_displayed(d, label: str) -> bool:
        try:
            return any(e.is_displayed() for e in d.find_elements(
                By.XPATH, f"//*[normalize-space(text())='{label}']"))
        except Exception:
            return False

    _last_rect = []

    def _sched_proc_settled(d):
        try:
            els = [e for e in d.find_elements(
                By.XPATH, "//*[normalize-space(text())='Scheduled Processes']")
                if e.is_displayed()]
            if not els:
                return False
            rect = d.execute_script(
                "var b=arguments[0].getBoundingClientRect();"
                "return [Math.round(b.x), Math.round(b.y)];", els[0])
        except Exception:
            return False
        prev = _last_rect[0] if _last_rect else None
        _last_rect.clear()
        _last_rect.append(rect)
        return prev is not None and prev == rect

    def _sched_proc_arrived(d):
        """Scheduled Processes 화면에 실제로 도착했는지 - 이 화면에만 있는
        "Schedule New Process" 버튼 유무로 판정한다."""
        try:
            d.switch_to.default_content()
            return any(el.is_displayed() for el in d.find_elements(
                By.XPATH, "//*[normalize-space(text())='Schedule New Process']"))
        except Exception:
            return False

    last_err = None
    for i in range(attempts):
        try:
            # 2026-08-06: 다른 자동화 탭을 보고 있는 상태에서 driver.get()을 하면
            # 남의 화면을 덮어써서 그쪽 자동화가 깨진다 - 내 탭으로 먼저 돌아온다.
            _ensure_my_tab(driver)
            driver.get(ORACLE_HOME_URL)
            # message= 를 꼭 준다: WebDriverWait의 TimeoutException은 기본 메시지가
            # 빈 문자열이라, 안 주면 로그에 "이동 실패: Message:"만 찍혀서 어디서
            # 터졌는지 알 수 없다(2026-08-06 사용자 지적으로 확인).
            # 2026-08-06 실측: 고정 sleep(3)으로는 홈 렌더가 안 끝나 Tools/아이콘을
            # 아예 못 찾는 경우가 반복됨(6초를 줬을 때는 정상 발견) - 고정 대기 대신
            # 실제로 보일 때까지 기다린다.
            WebDriverWait(driver, SCHED_PROC_RENDER_TIMEOUT_SEC, poll_frequency=0.5).until(
                lambda d: _text_is_displayed(d, "Tools"),
                message=f"오라클 홈이 {SCHED_PROC_RENDER_TIMEOUT_SEC}초 안에 렌더되지 "
                        f"않음(Tools 탭을 못 찾음)",
            )
            # 2026-08-06(2차): 네이티브 클릭이 백그라운드 창에서 예외 없이 조용히
            # 씹히는 게 실측된 문제라 JS 클릭으로 바꾼다(_js_click_text 설명 참고).
            # 여기는 화면 이동(읽기 전용)이고, 아래에 도착 확인 + 재시도가 이미
            # 있어서 혹시 잘못 눌려도 그 재시도가 받아준다.
            _js_click_text(driver, "Tools")
            WebDriverWait(driver, SCHED_PROC_RENDER_TIMEOUT_SEC, poll_frequency=0.5).until(
                lambda d: _text_is_displayed(d, "Scheduled Processes"),
                message=f"Tools 클릭 후 'Scheduled Processes' 아이콘이 "
                        f"{SCHED_PROC_RENDER_TIMEOUT_SEC}초 안에 안 나타남",
            )
            # 2026-08-06: 한때 "아이콘 좌표가 두 번 연속 같을 때까지" 기다리게 해봤는데
            # 스프링보드가 계속 미세하게 움직여서 안정 판정이 아예 안 나고 클릭조차
            # 못 하는 역효과가 났다(실측) - 짧은 고정 대기로 배치가 끝나길 기다리고,
            # 클릭이 안 먹은 경우는 아래 도착 확인이 잡아서 재시도로 넘긴다.
            time.sleep(2)
            _js_click_text(driver, "Scheduled Processes")
            # 2026-08-06 실측: 클릭이 "성공"해도 실제로는 화면이 안 넘어가고 홈
            # 스프링보드에 그대로 머무는 경우가 있다(진단 스크린샷
            # _diag_pidfilter_20260806_102418.png - Tools만 펼쳐진 홈 화면).
            # 그러면 예외도 안 나서 그대로 통과하고, 뒤이은 상태확인이 홈 화면에서
            # Process ID 필터를 찾다 실패해 스크롤 폴백으로 떨어진 뒤 영원히
            # Succeeded를 못 찾는다(08-03~08-06 필터 실패의 진짜 원인).
            # 도착을 확인해서 안 넘어갔으면 예외로 올려 위 재시도를 태운다.
            WebDriverWait(driver, SCHED_PROC_RENDER_TIMEOUT_SEC, poll_frequency=0.5).until(
                _sched_proc_arrived,
                message=f"'Scheduled Processes'를 클릭했는데 "
                        f"{SCHED_PROC_RENDER_TIMEOUT_SEC}초 안에 그 화면"
                        f"('Schedule New Process' 버튼)에 도착하지 못함",
            )
            time.sleep(1)
            return
        except Exception as e:
            last_err = e
            log(f"[경고] Tools > Scheduled Processes 이동 실패({i + 1}/{attempts}차): {e} -> 재시도")
            time.sleep(3)
    raise last_err


# ==============================================================
# 오라클 화면 조작 공통 재시도 (2026-08-05 추가)
# ==============================================================
# 2026-08-05 사용자 요청으로 오라클을 쓰는 자동화 5종에 동일하게 넣은 헬퍼.
# 배경: pick_release_watcher 실측(2026-08-05 18:00 회차)에서 SSO 재로그인 직후
# "no such element: //img[@title='Tasks']"(화면 진입 실패)가 연달아 났는데,
# 자체 재시도 레이어가 있던 경로는 살아남고 없던 경로는 그대로 실패해 다음
# 예약 실행(20분 뒤)까지 밀렸다 - 같은 실행 안에서 짧게 쉬었다 다시 시도한다.
# 이 스크립트에서 재시도를 붙이는 대상은 오라클 리포트 제출/상태확인처럼
# 결과물이 리포트(읽기 전용)라 다시 해도 업무상 부작용이 없는 단계다. 답장
# 발송/초안 생성 같은 대외 동작에는 붙이지 않는다(중복 발송 위험).
ORACLE_RETRY_ATTEMPTS = 3        # 최초 1회 + 재시도 2회
ORACLE_RETRY_WAIT_SEC = (5, 15)  # 재시도 전 대기(점증)


def run_with_oracle_retry(label: str, fn, *, attempts: int = ORACLE_RETRY_ATTEMPTS,
                          no_retry_exceptions: tuple = (), before_retry=None,
                          should_retry=None):
    """fn()이 일시적 오류로 실패하면 잠깐 쉬었다 다시 시도한다.
    no_retry_exceptions: 재시도해도 결론이 같은 '확정' 예외(그대로 올려보냄).
    before_retry: 재시도 직전 화면을 원위치시키는 콜백(실패해도 무시하고 진행).
    should_retry: 예외를 받아 "지금 재시도해도 되는가"를 판단하는 콜백(False면
    즉시 중단). 이미 커밋된 트랜잭션 뒤라 재시도가 의미 없을 때 쓴다.
    모든 시도가 실패하면 마지막 예외를 그대로 올려 호출부의 기존 처리를 탄다."""
    last_exc = None
    for attempt in range(attempts):
        try:
            return fn()
        except no_retry_exceptions:
            raise
        except Exception as e:
            last_exc = e
            # 2026-08-06: 브라우저 세션 자체가 끊긴 경우엔 같은 driver로 다시
            # 해봐야 결과가 100% 같다 - 15~45초를 버릴 뿐 아니라, 로그가
            # "3번 시도했는데 화면을 못 찾음"처럼 보여 오라클 화면 문제로
            # 오진하게 만든다(is_session_dead_error 설명 참고).
            if is_session_dead_error(e):
                log(f"  [재시도] {label}: 브라우저 세션이 끊김({type(e).__name__}) "
                    f"- 같은 세션으로는 재시도해도 결과가 같아 여기서 중단")
                raise
            if should_retry is not None and not should_retry(e):
                log(f"  [재시도] {label}: 재시도 조건이 아니라 여기서 중단")
                raise
            if attempt == attempts - 1:
                break
            wait = ORACLE_RETRY_WAIT_SEC[min(attempt, len(ORACLE_RETRY_WAIT_SEC) - 1)]
            # 2026-08-06: 예전엔 예외 타입만 찍어서(예: "RuntimeError") 무엇이
            # 실패했는지 로그만 봐선 알 수 없었다 - 메시지 첫 줄까지 남긴다
            # (Selenium 예외는 스택트레이스가 수십 줄이라 첫 줄만).
            detail = str(e).strip().splitlines()[0] if str(e).strip() else "(메시지 없음)"
            log(f"  [재시도] {label}: 오라클 처리 실패({type(e).__name__}: {detail}) - "
                f"{wait}초 후 {attempt + 2}/{attempts}번째 시도")
            time.sleep(wait)
            if before_retry is not None:
                try:
                    before_retry()
                except Exception as e2:
                    log(f"  [재시도] {label}: 재시도 전 화면 복구 실패(무시하고 진행): {e2}")
    raise last_exc


def submit_oracle_ci_report(driver, org_code: str, delivery_no: str) -> str:
    """Print Commercial Invoice Report를 제출(또는 기존 제출을 재사용)하고
    Process ID만 반환한다 - 완료될 때까지 기다리지 않는다.
    2026-08-03 사용자 요청: 메일을 하나씩 "제출->완료대기->다음 메일" 순서로
    처리하면, 앞선 건이 Blocked로 오래 걸릴 때 뒤에 있는 멀쩡한 건들까지 덩달아
    밀리는 문제가 있었다. 제출은 여기서 순차적으로 다 해두고(오라클 서버 쪽
    큐에 쌓여 백그라운드로 같이 처리 시작됨), 완료 확인은 poll_oracle_ci_report()로
    여러 건을 라운드로빈으로 돌며 확인한다(main() 참고).
    2026-07-10 사용자 요청: 같은 (org_code, delivery_no) 건에 대해 이미 제출된
    Process ID가 있으면(저장된 지 6시간 이내) 재사용하고 새로 제출하지 않는다 —
    같은 delivery로 오라클에 중복 리포트가 쌓이는 것 방지."""
    _goto_scheduled_processes(driver)

    proc_key = f"{org_code}:{delivery_no}"
    oracle_proc_state = load_oracle_process_state()
    saved_entry = oracle_proc_state.get(proc_key)
    if saved_entry:
        try:
            saved_dt = datetime.strptime(saved_entry["submitted_at"], "%Y-%m-%d %H:%M:%S")
            if (datetime.now() - saved_dt).total_seconds() < 6 * 3600:
                log(f"[재개] 이전에 제출한 Process ID({saved_entry['process_id']})를 재사용 - "
                    f"새로 제출 안 함 (key={proc_key})")
                return saved_entry["process_id"]
            log(f"[경고] 저장된 Process ID({saved_entry['process_id']})가 6시간 넘게 지나 있어 폐기하고 새로 제출함")
        except Exception as e:
            # 2026-08-06: 여기서 조용히 넘어가면 이미 제출해둔 Process ID를
            # 재사용하지 못하고 같은 리포트를 오라클에 또 제출한다(결과물이
            # 리포트라 업무 사고는 아니지만, 오라클 부하와 대기 시간이 그만큼
            # 늘어난다). 왜 재사용을 못 했는지 흔적을 남긴다.
            log(f"[경고] 저장된 제출 기록을 해석하지 못해 새로 제출함"
                f"({type(e).__name__}: {e}, key={proc_key})")

    # 2026-08-03 실측: Tools>Scheduled Processes 이동뿐 아니라 "Schedule New
    # Process" 다이얼로그 진행 중에도(Organization 입력 필드 등을 못 찾는 등)
    # 같은 종류의 타이밍성 실패가 확인됨(첫 시도만 불안정하고 이후 재시도는
    # 바로 성공 - 세션 초반 플레이키니스로 추정). Invalid value(입력값 자체가
    # 잘못된 확정적 거부)가 아닌 한, 화면을 처음(Scheduled Processes)부터 다시
    # 열어 재시도한다.
    last_err = None
    process_id = None
    for i in range(3):
        try:
            process_id = _do_schedule_new_process(driver, org_code, delivery_no)
            break
        except RuntimeError as e:
            if "오라클이 입력값을 거부함" in str(e):
                raise
            last_err = e
        except Exception as e:
            last_err = e
        log(f"[경고] Schedule New Process 제출 실패({i + 1}/3차): {last_err} -> 화면 새로고침 후 재시도")
        _goto_scheduled_processes(driver)
    if process_id is None:
        raise last_err

    # 2026-07-10: 제출 직후 즉시 저장 — 이후 완료확인 중 타임아웃/크래시가
    # 나도 다음 실행이 이 Process ID를 이어서 확인할 수 있게.
    oracle_proc_state[proc_key] = {
        "process_id": process_id,
        "submitted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_oracle_process_state(oracle_proc_state)
    return process_id


def _do_schedule_new_process(driver, org_code: str, delivery_no: str) -> str:
    """Scheduled Processes 화면에서 "Schedule New Process" 다이얼로그를 열어
    실제로 제출하고 확인 다이얼로그에서 Process ID를 읽어 반환한다."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select, WebDriverWait

    # 2026-08-06(2차): 같은 화면의 Tools/Scheduled Processes 클릭이 네이티브로는
    # 3/3 실패(조용히 씹힘)하는 것이 실측돼서 여기도 JS 클릭으로 바꾼다. 이 버튼은
    # ADF 다이얼로그를 여는 것이라 새 창(window.open)이 아니므로 JS 클릭이 안전하다
    # (팝업을 띄우는 republish_img.click()만 네이티브로 남겨둠).
    _js_click_text(driver, "Schedule New Process")

    # 2026-08-07 실측(_diag_schednew_dialog 1~3차, DHL 1186918773이 11번 헛돈 뒤 원인
    # 확정)으로 밝혀진 이 다이얼로그의 실제 동작:
    #   (1) Name 칸은 다이얼로그가 뜬 뒤 약 3초 지나야 DOM에 나타난다. 나타나자마자
    #       타이핑하면 ADF가 바인딩을 끝내면서 값을 도로 지워버린다(1차 진단에서
    #       Tab 후 value=''로 확인).
    #   (2) 프로세스명을 넣기만 해서는 OK 버튼이 **비활성(disabled)** 이다. Tab을
    #       눌러 LOV 검증 서버 왕복이 끝나야 비로소 활성화되고, 그게 약 1.5초 걸린다
    #       (3차 진단에서 시간별로 관찰: t=0.0s disabled -> t=1.5s enabled).
    # 기존 코드는 Tab 뒤 **고정 1.5초**만 기다린 다음 "OK"를 텍스트로 찾아 JS 클릭했다.
    # 왕복이 1.5초보다 조금이라도 늦은 회차(SSO 재로그인 직후 등)에는 아직 비활성인
    # 버튼을 누른 셈이 되는데, 비활성 버튼 클릭은 예외도 안 나고 아무 일도 안 일어난다
    # -> 파라미터 화면이 안 뜨고 바로 아래 Organization 칸에서 NoSuchElement로 터졌다.
    # 로그에는 "Organization 칸을 못 찾음"으로만 남아서 화면 구조가 바뀐 것처럼 보였다.
    # 고정 대기를 없애고 (a) 값이 실제로 들어갔는지, (b) OK가 실제로 활성화됐는지를
    # 확인한 뒤 그 OK 버튼을 **id로 직접** 누른다(텍스트 'OK'는 화면 밖 유령 버튼
    # 2개가 같이 걸리는 것도 3차 진단에서 확인됨: d1::msgDlg::cancel, j_id6::ok).
    _wait_find(driver, By.CSS_SELECTOR, SNP_NAME_CSS, timeout=SNP_NAME_RENDER_TIMEOUT_SEC)
    time.sleep(1)  # (1) 방금 나타난 칸에 곧바로 치면 값이 지워진다

    def _ok_btn_enabled(d):
        for b in d.find_elements(By.CSS_SELECTOR, SNP_OK_BTN_CSS):
            if b.is_displayed() and b.is_enabled():
                return b
        return False

    ok_btn = None
    name_fail = ""
    # 2026-08-14: 시도 횟수를 3 -> SNP_NAME_ENTRY_ATTEMPTS로, 회차 간 대기를
    # 1.5 -> SNP_NAME_RETRY_WAIT_SEC로 늘린다. 초기 sleep(1)은 그대로 둬서 정상
    # 상황의 속도는 손대지 않고, **ADF 바인딩이 느린 회차에서만** 더 참는다.
    # 계기: rebalance TO 7872710(2026-08-14 17:06~17:09)이 이 지점에서 3회차를
    # 전부 소진해 실패했고, 상위 재시도 3번까지 합쳐 9번 다 지워졌다. 이 함수
    # 주석에 이미 "SSO 재로그인 직후 등에는 서버 왕복이 늦다"는 실측이 있는데,
    # 그날은 17:02:56에 Edge를 껐다 켜고 SSO 재로그인을 한 직후였다.
    # 지워질 때마다 로그를 남겨(예전엔 3회 다 실패해야 흔적이 남았다) 실제로
    # 몇 회차에서 붙는지를 보고 이 값을 조정할 근거를 만든다.
    for _attempt in range(1, SNP_NAME_ENTRY_ATTEMPTS + 1):
        el = driver.find_element(By.CSS_SELECTOR, SNP_NAME_CSS)
        el.click(); el.clear(); el.send_keys(SNP_PROCESS_NAME)
        time.sleep(0.5)
        typed = (driver.find_element(By.CSS_SELECTOR, SNP_NAME_CSS)
                 .get_attribute("value") or "").strip()
        if typed != SNP_PROCESS_NAME:
            name_fail = f"프로세스명이 Name 칸에 안 남음(현재 값={typed!r}) - ADF가 지운 것"
            log(f"  [SNP] 프로세스명이 ADF에 지워짐(입력 {_attempt}/"
                f"{SNP_NAME_ENTRY_ATTEMPTS}회차, 현재 값={typed!r}) - "
                f"{SNP_NAME_RETRY_WAIT_SEC}초 쉬고 다시 입력")
            time.sleep(SNP_NAME_RETRY_WAIT_SEC)
            continue
        if _attempt > 1:
            log(f"  [SNP] 프로세스명 입력 {_attempt}회차에 붙음 - 재입력으로 건짐")
        driver.find_element(By.CSS_SELECTOR, SNP_NAME_CSS).send_keys("\t")
        try:
            ok_btn = WebDriverWait(
                driver, SNP_OK_ENABLE_TIMEOUT_SEC, poll_frequency=0.3
            ).until(_ok_btn_enabled, message="")
            break
        except Exception:
            name_fail = (f"Tab 후 {SNP_OK_ENABLE_TIMEOUT_SEC}초 안에 OK 버튼이 "
                         f"활성화되지 않음(프로세스명 LOV 검증이 안 끝남)")
    if ok_btn is None:
        raise RuntimeError(f"Schedule New Process 다이얼로그에서 프로세스명 확정 실패: {name_fail}")

    # 활성화된 진짜 OK 버튼을 JS로 클릭(백그라운드 창에서 네이티브 클릭이 조용히
    # 씹히는 문제는 _js_click_text 설명 참고 - 여기도 새 창이 아니라 안전하다).
    driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", ok_btn)

    # 2026-07-08: 로그인 직후 첫 호출에서는 이 다이얼로그의 필드들이 렌더링되기까지
    # 고정 sleep보다 오래 걸릴 때가 있어(실측: name_inputs[0] IndexError 발생) 폴링으로 대기.
    try:
        el = _wait_find(driver, By.CSS_SELECTOR, "input[id*='paramDynForm_Organization']",
                        timeout=SNP_PARAM_RENDER_TIMEOUT_SEC)
    except Exception:
        raise RuntimeError(
            f"OK를 눌렀는데 {SNP_PARAM_RENDER_TIMEOUT_SEC}초 안에 파라미터 입력 화면"
            f"(Organization 칸)이 안 뜸")
    el.click(); el.clear(); el.send_keys(org_code)
    time.sleep(1)

    sel_el = _wait_find(driver, By.CSS_SELECTOR, "select[id*='paramDynForm_ItemDisplay']")
    Select(sel_el).select_by_visible_text("Both")
    time.sleep(0.5)

    el2 = _wait_find(driver, By.CSS_SELECTOR, "input[id*='paramDynForm_Delivery']")
    el2.click(); el2.clear(); el2.send_keys(delivery_no)
    time.sleep(1)

    submit = [a for a in driver.find_elements(By.TAG_NAME, "a") if a.is_displayed() and a.text.strip() == "Submit"][-1]
    submit.click()

    # 2026-07-08: 확인 다이얼로그("Process NNNNN was submitted.")에서 Process ID를
    # 읽어둔다 — 검색 결과 목록엔 과거에 이미 끝난 다른 Print Commercial Invoice
    # Report 행들도 같이 보이므로, 페이지 전체에서 "Succeeded" 문자열만 찾으면
    # 남의 완료 상태를 내 것으로 착각한다(실측 확인: 아직 Blocked/Wait인 새 건을
    # 붙잡고 Republish를 찾다가 매번 실패했음). 반드시 이 프로세스 ID로 범위를
    # 좁혀서 판정해야 함.
    # 2026-07-24 실측(AWB 874668910609): 고정 3초 대기 후 단 한 번만 확인하는
    # 방식이라, 오라클 응답이 평소보다 느린 날엔(SSO 재로그인 직후 등) 다이얼로그가
    # 아직 안 떴는데 확인해버려서 Process ID를 못 읽고 연속으로 실패했다. 최대
    # 10초까지 폴링하도록 넓힌다.
    process_id = None
    invalid_value_msg = None
    for _ in range(20):
        try:
            msg_el = driver.find_element(By.XPATH, "//*[contains(text(),'was submitted')]")
            pm = re.search(r"(\d{5,})", msg_el.text)
            if pm:
                process_id = pm.group(1)
                break
        except Exception:
            pass
        # 2026-07-24 실측(AWB 874668910609, 실제 Delivery는 9959293인데 OCR이
        # 9959003으로 오독): 이 경우 다이얼로그가 아예 안 뜨고 대신 "Invalid
        # value: <입력값>" 에러가 뜬다 - 이걸 그냥 "Process ID를 못 읽음"으로
        # 뭉뚱그리면 매번 화면을 직접 열어봐야 원인을 알 수 있으므로, 여기서
        # 감지해서 원인이 분명한 메시지로 바로 알려준다.
        try:
            err_el = driver.find_element(By.XPATH, "//*[contains(text(),'Invalid value')]")
            invalid_value_msg = err_el.text
            break
        except Exception:
            pass
        time.sleep(0.5)

    # 제출 확인 다이얼로그의 OK는 버전에 따라 <a> 또는 <button>일 수 있어
    # 태그 무관하게 텍스트로 찾는 _click_text 사용(2026-07-08: <button>으로 확인).
    # 다이얼로그가 이미 자동으로 닫혀있는 경우도 있어 실패해도 치명적이지 않게 무시.
    try:
        _js_click_text(driver, "OK")  # 2026-08-06(2차): 같은 이유로 JS 클릭
    except Exception:
        pass
    time.sleep(2)

    if invalid_value_msg:
        raise RuntimeError(
            f"오라클이 입력값을 거부함({invalid_value_msg}) - Delivery Number "
            f"{delivery_no}가 Org={org_code}에 존재하지 않음. OCR이 숫자를 "
            f"잘못 읽었을 가능성이 높으니 원본 C.I에서 Delivery Number를 직접 확인 필요."
        )
    if not process_id:
        raise RuntimeError("제출 확인 다이얼로그에서 Process ID를 못 읽음")
    return process_id


def _apply_process_id_filter(driver, process_id: str) -> bool:
    """Scheduled Processes 화면의 Search 패널을 펼쳐 Process ID로 직접 검색한다.
    2026-08-01 도입: "Last hour"/"Last 12 hours" 같은 Saved Search 날짜 필터에
    의존하면 (a) FBC 건처럼 1시간 넘게 걸리면 필터를 넓혀야 하고, (b) 넓혀도
    그 사이 pick_release_watcher 등이 쌓은 수십~수백 건 밑에 내 건이 묻혀서
    화면(가상 스크롤)엔 안 보이는 문제가 있었다(Blocked였다가 2시간 뒤 Succeeded
    됐는데 못 찾거나, 8시간까지 걸린 사례 확인). Search 패널을 펼치면 전용
    "Process ID" 필드가 있어서, 여기 직접 입력하면 결과 개수와 무관하게 서버
    쪽에서 정확히 그 1건만 걸러준다. 실패하면 False(호출부가 스크롤 폴백으로 대체).
    2026-08-06(2차) 원인 확정 - 실패 원인이 두 개였고 둘 다 고쳤다:
    (a) **화면이 Scheduled Processes가 아니었음**: 진단 스크린샷을 보니 오라클 홈
        스프링보드(FuseWelcome)나 Inventory Management(다른 자동화 화면)였다. 이 함수는
        호출부(poll_oracle_ci_report)가 이미 Scheduled Processes에 있다고 전제했는데
        그 전제가 깨져 있었던 것 - 이제 화면을 직접 확인해서 아니면 내 탭으로 되돌리고
        (_ensure_my_tab) Tools > Scheduled Processes로 다시 이동한다.
    (b) **Search 버튼을 누른 게 아니라 패널 제목을 눌렀음**: 이 화면엔 'Search'라는
        텍스트가 두 곳에 있다 - 검색 패널 제목(<h1 class="xte">Search</h1>)과 실제 검색
        버튼(<button id="...srRssdfl::search">). _click_text은 DOM 순서상 먼저 나오는
        제목 h1을 잡아서 클릭했고, h1은 아무 동작이 없으니 예외도 안 나면서 검색이
        아예 실행되지 않았다(그래서 필터가 걸린 줄 알고 결과에서 내 행을 못 찾아
        "아직 처리 중"으로 오판, Succeeded를 영원히 못 봄). 이제 id가 '::search'로
        끝나는 진짜 버튼만 누른다(CDP로 실제 DOM 확인, 2026-08-06).
    2026-08-07 원인 확정(사용자 지적 + 실측) - **Submission Time을 비워야 한다**:
    예전 주석에는 "Submission Time 기본값이 비어 있다"고 적혀 있었지만 사실이 아니었다.
    Search 패널을 펼쳐서 실제 필드를 덤프해보니 Submission Time에는 연산자 AFTER와
    함께 **Saved Search에 대응하는 시각이 이미 채워져 있다**(Last hour -> 1시간 전,
    Last 24 hours -> 24시간 전). 그래서 Process ID로 검색해도 그 시각보다 오래된
    프로세스는 결과에서 아예 빠졌다. 실측:
      - 1시간 19분 전 Process ID(48970823): Last hour 상태에서 2.0초 만에 찾음
      - 25시간 전 Process ID(48951334): Last hour 상태에서 **못 찾음**
    전날 저녁에 제출한 걸 다음날 아침 회차가 저장된 Process ID로 이어서 확인하는
    경우(예: 18시 제출 -> 다음날 9시 확인 = 15시간)가 여기 정통으로 걸린다.
    그래서 검색 전에 (1) Saved Search를 'Last 24 hours'로 맞추고 (2) Submission Time
    입력칸을 비운다. 비우면 날짜 하한이 사라져 Process ID만으로 판정된다.
    **순서 주의**: Saved Search를 바꾸면 ADF가 Process ID 칸을 지워버리는 것이
    실측됐다(48970823이 ''로 초기화됨). 반드시 Saved Search -> Submission Time 비우기
    -> Process ID 입력 순서로 해야 한다.
    검색이 실제로 걸렸는지는 결과에 그 Process ID 행이 나타나는지로 확인하고,
    실패하면 False(호출부가 기존 스크롤 폴백으로 대체)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

    def _visible(els):
        for el in els:
            try:
                if el.is_displayed() and el.is_enabled():
                    return el
            except Exception:
                continue
        return None

    def _visible_pid_input():
        return _visible(driver.find_elements(
            By.XPATH, "//label[normalize-space(text())='Process ID']/following::input[1]"))

    def _visible_submission_time_input():
        return _visible(driver.find_elements(
            By.XPATH, "//label[normalize-space(text())='Submission Time']/following::input[1]"))

    step = "시작"
    try:
        _ensure_my_tab(driver)
        driver.switch_to.default_content()

        if not _on_scheduled_processes(driver):
            step = "Scheduled Processes 화면으로 재이동"
            log("[정보] 현재 화면이 Scheduled Processes가 아님 -> 다시 이동한 뒤 Process ID 검색")
            _goto_scheduled_processes(driver)

        pid_input = _visible_pid_input()
        if pid_input is None:
            # 검색 패널이 접혀 있을 때만 펼친다. 화살표의 title이 'Expand Search'/
            # 'Collapse Search'로 상태를 알려주므로(실측 확인) 펼쳐진 패널을 잘못
            # 접어버리지 않도록 Expand인 것만 누른다.
            #
            # 2026-08-07 원인 확정(_diag_expand_search.py): 이 화살표가 **네이티브
            # 클릭이 조용히 씹히는 마지막 자리**였다. 실측에서 요소는 정확히 찾히고
            # (title='Expand Search', 화면에 보이는 24x24) 예외도 안 나는데 화면이
            # 그대로였고, 같은 요소에 JS 클릭을 하니 바로 펼쳐졌다. 2026-08-06에
            # 30회 가까이 찍힌 "Search 패널을 펼쳐도 Process ID 입력 필드가 보이지
            # 않음"과 2026-08-07 11:00 회차 실패가 전부 이것이다(_js_click_text 설명 참고).
            # JS 클릭으로 바꾸고, 눌렀다고 믿지 말고 입력칸이 실제로 보일 때까지
            # 기다린다. 안 되면 한 번 더 누른다(토글이므로 상태를 다시 읽고 누른다).
            step = "Search 패널 펼치기"

            def _expand_arrow():
                for a in driver.find_elements(By.CSS_SELECTOR, "a[id$='::_afrDscl']"):
                    try:
                        t = a.get_attribute("title") or ""
                        if a.is_displayed() and t.startswith("Expand") and "Search" in t:
                            return a
                    except Exception:
                        continue
                return None

            for _ in range(2):
                arrow = _expand_arrow()
                if arrow is None:
                    break  # 이미 펼쳐져 있거나 화살표가 없음 - 아래에서 판정
                driver.execute_script(
                    "arguments[0].scrollIntoView(true); arguments[0].click();", arrow)
                try:
                    WebDriverWait(driver, 8, poll_frequency=0.3).until(
                        lambda d: _visible_pid_input() is not None,
                        message="펼치기 클릭 후 Process ID 입력칸이 8초 안에 안 나타남")
                    break
                except Exception:
                    continue
            pid_input = _visible_pid_input()
        if pid_input is None:
            raise RuntimeError("Search 패널을 펼쳐도 Process ID 입력 필드가 보이지 않음")

        # 아래 두 단계는 반드시 Process ID 입력 **전에** 해야 한다(함수 설명 참고).
        step = "Saved Search를 'Last 24 hours'로 맞추기"
        sel_el = _visible(driver.find_elements(By.CSS_SELECTOR, "select[id*='saveSearch']"))
        if sel_el is not None:
            cur = driver.execute_script(
                "var s=arguments[0]; return s.options[s.selectedIndex].text;", sel_el)
            if cur != SCHED_PROC_SAVED_SEARCH:
                _select_saved_search(driver, SCHED_PROC_SAVED_SEARCH)

        step = "Submission Time 비우기"
        # 이걸 비워야 날짜 하한(AFTER <시각>)이 사라져서 하루 넘은 Process ID도 잡힌다.
        # 날짜칸을 클릭하면 달력 팝업이 떠서 Search 버튼을 가릴 수 있으므로(기존 주석)
        # 클릭하지 않고 값만 지우고 Tab으로 확정한다.
        st_input = _visible_submission_time_input()
        if st_input is not None and (st_input.get_attribute("value") or "").strip():
            st_input.clear()
            st_input.send_keys("\t")
            time.sleep(1.5)
            left = (( _visible_submission_time_input() or st_input)
                    .get_attribute("value") or "").strip()
            if left:
                log(f"[경고] Submission Time을 비우지 못함(현재 값={left!r}) - "
                    f"그보다 오래된 Process ID는 검색에 안 잡힐 수 있음")

        step = "Process ID 입력"
        # 2026-08-07 실측: 여기서 send_keys가 **예외 없이 씹히는** 경우가 재현됐다
        # (진단 스크린샷: Process ID 칸에 커서는 가 있는데 값이 비어 있음). 그 상태로
        # Search를 누르면 내 조건이 아닌 검색이 돌아서 "결과에 그 행이 없음"으로만
        # 보이고, 날짜 필터 문제로 오진하게 된다. 클릭/타이핑이 씹히는 것은 이 파일에
        # 이미 여러 번 기록된 배경 창 문제와 같은 뿌리다(_js_click_text 설명 참고).
        # 넣었다고 믿지 말고 값이 실제로 남았는지 확인하고, 아니면 다시 넣는다.
        def _pid_value():
            el = _visible_pid_input()
            return (el.get_attribute("value") or "").strip() if el else ""

        typed = ""
        for _ in range(3):
            pid_input = _visible_pid_input()
            if pid_input is None:
                raise RuntimeError("Saved Search 변경 후 Process ID 입력 필드를 다시 못 찾음")
            driver.execute_script("arguments[0].scrollIntoView(true);", pid_input)
            try:
                pid_input.click()
            except Exception:
                pass  # 포커스가 안 잡혀도 clear/send_keys는 대개 동작한다
            pid_input.clear()
            pid_input.send_keys(process_id)
            time.sleep(0.5)
            typed = _pid_value()
            if typed == process_id:
                break

            # send_keys가 씹힌 경우 - JS로 직접 넣고 입력 이벤트를 발생시킨다.
            el = _visible_pid_input()
            if el is not None:
                driver.execute_script(SET_INPUT_VALUE_JS, el, process_id)
                time.sleep(0.5)
                typed = _pid_value()
                if typed == process_id:
                    break
            time.sleep(1)
        if typed != process_id:
            raise RuntimeError(
                f"Process ID 입력이 씹힘 - {process_id}를 3번 넣었는데 칸에 남은 값이 "
                f"{typed!r} (이 상태로 Search하면 엉뚱한 검색이 된다)")

        step = "Search 버튼 클릭"
        btn = _visible(driver.find_elements(By.CSS_SELECTOR, "button[id$='::search']"))
        if btn is None:
            raise RuntimeError("Search 버튼(id가 '::search'로 끝나는 button)을 못 찾음")
        # 2026-08-07: 여기도 네이티브 우선이었는데, 그게 씹히면 예외가 안 나므로 JS
        # 폴백이 영영 안 걸린다. 그러면 **이전 검색 결과가 그대로 남아 있는 화면**을
        # 보고 "내 행이 없다"고 판정해서, 실제로는 Succeeded인 건을 계속 대기로
        # 오판한다(2026-08-07 실측: 25시간 전 건이 한 회차는 3.3초에 찾히고 다음
        # 회차는 못 찾는 식으로 오락가락). 처음부터 JS 클릭으로 통일한다.
        driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", btn)

        step = "검색 결과 확인"
        # 2026-08-06 실측: 검색 직후엔 행이 DOM에 붙어도 셀 텍스트가 아직 안 그려져
        # row.text가 빈 문자열인 순간이 있다(그 상태로 호출부가 판정하면 Succeeded인
        # 건도 "아직 처리 중"으로 오판) - 행 텍스트가 채워질 때까지 기다린다.
        def _row_rendered(d):
            cells = d.find_elements(By.XPATH, f"//td[normalize-space(.)='{process_id}']")
            if not cells:
                return False
            try:
                return bool(cells[0].find_element(By.XPATH, "./ancestor::tr[1]").text.strip())
            except Exception:
                return False

        # message= 를 꼭 준다: 안 주면 TimeoutException의 기본 메시지가 빈 문자열이라
        # 로그에 "실패(단계='검색 결과 확인'): Message:"만 남아서 원인을 알 수 없다
        # (2026-08-07: 실제로 이 빈 메시지 때문에 날짜 필터 문제를 한참 못 봤다).
        WebDriverWait(driver, 15, poll_frequency=0.5).until(
            _row_rendered,
            message=f"Search는 실행됐는데 15초 안에 결과에 Process ID {process_id} 행이 "
                    f"나타나지 않음(날짜 필터에 걸렸거나 그 ID가 실제로 없음)")
        return True
    except Exception as e:
        first_line = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
        log(f"[경고] Process ID 검색 필드 적용 실패(단계='{step}', 기존 스크롤 방식으로 대체): {first_line}")
        try:
            diag_path = os.path.join(
                ROOT, f"_diag_pidfilter_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
            driver.save_screenshot(diag_path)
            log(f"  [진단] 화면 캡처 저장: {os.path.basename(diag_path)}")
        except Exception:
            pass
        return False


def poll_oracle_ci_report(driver, org_code: str, delivery_no: str, process_id: str) -> dict | None:
    """이 Process ID의 현재 상태를 "한 번만" 확인한다(대기 루프 없음 - main()의
    라운드로빈 폴링에서 여러 건을 돌아가며 호출하기 위해 submit_oracle_ci_report와
    분리했다). 아직 Succeeded가 아니면 None, Succeeded면 Republish->Export까지
    끝내고 총액/PDF를 반환한다."""
    from selenium.webdriver.common.by import By

    process_id_filtered = _apply_process_id_filter(driver, process_id)
    # 2026-07-10 사용자 확인: Process ID 필터 적용 자체가 실패한 경우에만(드묾),
    # 기본 "Last hour" 필터로는 1시간 지난 오래된 건이 검색 결과에서 빠져버리므로
    # 아래 스크롤 폴백이 찾을 수 있도록 미리 넓혀둔다.
    # 2026-08-07 사용자 지적으로 "Last 12 hours" -> "Last 24 hours"로 변경:
    # 전날 오후 6시에 제출한 건을 다음날 오전 9시 회차에서 저장된 Process ID로
    # 이어서 확인하면 15시간이 지난 뒤라 12시간짜리 필터에는 아예 안 잡힌다.
    # (드롭다운 실제 항목: Last hour / Last 12 hours / Last 24 hours /
    #  Last 48 hours / Last 72 hours / Cancelable Processes - 2026-08-07 확인)
    if not process_id_filtered:
        try:
            _select_saved_search(driver, SCHED_PROC_SAVED_SEARCH)
        except Exception as e:
            log(f"[경고] 검색 필터를 '{SCHED_PROC_SAVED_SEARCH}'로 변경 실패: {e}")

    def _my_row():
        # 2026-07-08: `//tr[.//text()[contains(...)]]`는 페이지 레이아웃용 거대한
        # 바깥쪽 <tr>까지 걸려서(중첩된 조상 tr도 함께 매칭됨) 엉뚱한 요소를
        # 잡았었다(실측 확인). Process ID 셀은 값이 그 텍스트와 "정확히" 일치하는
        # <td> 하나뿐이므로 normalize-space 완전일치로 좁혀서 진짜 데이터 행만 찾는다.
        driver.switch_to.default_content()
        cells = driver.find_elements(By.XPATH, f"//td[normalize-space(.)='{process_id}']")
        if cells:
            return cells[0].find_element(By.XPATH, "./ancestor::tr[1]")
        if process_id_filtered:
            # 이미 Process ID로 서버 쪽 필터링을 해뒀으니 화면에 없으면 진짜 없는
            # 것 - 스크롤해봤자 나올 리 없다(폴백 불필요).
            return None
        # 2026-07-23 실측(DHL 1696566900, Process 48662766): Process ID 필터
        # 적용 자체가 실패했을 때의 방어적 폴백 - 결과 목록이 가상 스크롤 방식이라
        # 스크롤해야 그 구간이 DOM에 렌더링되는데, 위 XPath는 화면에 이미 그려진
        # 부분만 본다 - 실제로는 Succeeded인데 화면에 없어서 계속 "아직"으로
        # 오판하는 걸 확인함. 스크롤 가능한 컨테이너를 찾아 아래로 내리면서
        # 다시 찾아본다(최대 40번, 약 12초).
        for _ in range(40):
            driver.execute_script(
                "var els = document.querySelectorAll('div');"
                "for (var i = 0; i < els.length; i++) {"
                "  var el = els[i];"
                "  if (el.scrollHeight > el.clientHeight + 20 && el.clientHeight > 100) {"
                "    el.scrollTop = el.scrollTop + 300;"
                "  }"
                "}"
            )
            time.sleep(0.3)
            cells = driver.find_elements(By.XPATH, f"//td[normalize-space(.)='{process_id}']")
            if cells:
                return cells[0].find_element(By.XPATH, "./ancestor::tr[1]")
        return None

    driver.switch_to.default_content()
    img = driver.execute_script(
        "return document.querySelector(\"img[id*='processRefreshId']\");"
    )
    if img:
        driver.execute_script("arguments[0].click();", img)
    time.sleep(3)

    row = _my_row()
    if row is None:
        return None
    # 2026-08-06 실측: 새로고침/검색 직후 행이 DOM엔 있는데 셀 텍스트가 아직
    # 비어 있는 순간이 있다 - 그때 판정하면 실제로 Succeeded인 건도 "아직 처리
    # 중"으로 보고 20분 뒤로 미뤄진다. 텍스트가 채워질 때까지 잠깐 기다린다.
    row_text = row.text
    for _ in range(10):
        if row_text.strip():
            break
        time.sleep(0.5)
        row = _my_row()
        if row is None:
            return None
        row_text = row.text
    if "Succeeded" not in row_text:
        return None

    # Republish 아이콘은 프로세스 행을 펼쳐 Output & Delivery 섹션이 렌더링된
    # 뒤에만 DOM에 존재함 - 펼치는 클릭 없이 바로 찾으면 매번 실패함(실측 확인).
    # 행 전체가 아니라 Name 컬럼(1번째 td)을 클릭해야 선택+펼침이 트리거됨
    # (2026-07-08 실측 확인).
    # 2026-08-07 실측(_diag_gear_export.py): 이 클릭은 **토글**이다. 앞 회차가
    # 이미 이 행을 펼쳐둔 상태에서 또 누르면 Output & Delivery 섹션이 **접히고**,
    # 그러면 바로 아래 _republish_and_export_pdf의 `iframe[1]`이
    # "IndexError: list index out of range"로 터진다(2026-08-07 11:20 회차의 1차
    # 실패가 정확히 이것). 행 선택 자체는 꼭 해야 하므로(선택한 행이 곧 Republish
    # 대상이다) 클릭은 그대로 하되, 접혀버린 경우 다시 펼친다.
    def _detail_frames():
        driver.switch_to.default_content()
        return len(driver.find_elements(By.TAG_NAME, "iframe"))

    row.find_element(By.XPATH, "./td[1]").click()
    time.sleep(3)
    if _detail_frames() < 2:
        cells = driver.find_elements(By.XPATH, f"//td[normalize-space(.)='{process_id}']")
        if cells:
            driver.execute_script(
                "arguments[0].click();",
                cells[0].find_element(By.XPATH, "./ancestor::tr[1]/td[1]"))
            time.sleep(3)
    if _detail_frames() < 2:
        raise RuntimeError(
            f"Process {process_id} 행을 펼쳐도 상세(Output & Delivery) 프레임이 "
            f"안 나타남 - Republish 아이콘을 찾을 수 없는 상태")

    pdf_path = _republish_and_export_pdf(driver)
    total = extract_total_from_oracle_pdf(pdf_path)

    proc_key = f"{org_code}:{delivery_no}"
    oracle_proc_state = load_oracle_process_state()
    oracle_proc_state.pop(proc_key, None)
    save_oracle_process_state(oracle_proc_state)

    return {"total": total, "pdf_path": pdf_path}


def _wait_for_oracle_report(driver, org_code: str, delivery_no: str, process_id: str,
                             max_seconds: int = 17 * 60, poll_interval: int = 20) -> dict:
    """poll_oracle_ci_report를 완료될 때까지(또는 max_seconds 초과할 때까지) 반복
    확인하는 예전 방식(블로킹 대기) 래퍼. 대부분의 처리는 main()의 라운드로빈
    폴링으로 여러 건을 동시에 확인하지만, FBC/FBS 형제건 재확인처럼 1차 결과가
    나와야만 알 수 있는 드문 후속 조회는 이 블로킹 방식을 그대로 쓴다."""
    deadline = time.time() + max_seconds
    while True:
        r = poll_oracle_ci_report(driver, org_code, delivery_no, process_id)
        if r is not None:
            return r
        if time.time() >= deadline:
            raise OracleStillProcessing(
                f"리포트 실행 결과(Succeeded)를 시간 내에 확인 못함(약 {max_seconds // 60}분 대기, "
                f"Process ID는 저장되어 있으니 다음 스케줄 실행에서 이어서 확인함)")
        time.sleep(poll_interval)


def extract_total_from_oracle_pdf(pdf_path: str) -> float | None:
    """Candela Commercial Invoice Report PDF에서 총액(TOTAL) 추출.
    품목 라인(단가/금액)들이 먼저 나오고 SUBTOTAL/TOTAL 요약 줄이 문서 맨 뒤에
    나오는 고정 구조라, 문서에 등장하는 마지막 원화(₩) 금액이 곧 TOTAL이다
    (2026-07-08 실측: DHL 5078642660 건에서 정확히 일치 확인)."""
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join((p.extract_text() or "") for p in pdf.pages)
    amounts = re.findall(r"₩\s*([\d,]+)", text)
    # 2026-08-06: 여기서 None을 조용히 돌려주면 호출부의 가격 대조가 "총액 없음"
    # 으로 흘러가는데, 그 이유(리포트 양식 변경 / 빈 PDF / 숫자 형식)가 로그에
    # 안 남아서 추적이 불가능했다. 반환값은 그대로 두고 이유만 남긴다.
    if not amounts:
        log(f"[경고] 오라클 리포트 PDF에서 원화(₩) 금액을 못 찾음 - "
            f"{os.path.basename(pdf_path)} (리포트 양식이 바뀌었을 수 있음)")
        return None
    try:
        return float(amounts[-1].replace(",", ""))
    except Exception as e:
        log(f"[경고] 오라클 리포트 총액 숫자 변환 실패({amounts[-1]!r}: {e}) - "
            f"{os.path.basename(pdf_path)}")
        return None


def _wait_find(driver, by, selector, timeout: float = 8.0):
    """driver.find_element을 폴링으로 감싼 버전. ADF 다이얼로그가 로그인 직후
    첫 렌더링 때 고정 sleep보다 늦게 뜨는 경우가 있어(2026-07-08 실측) 사용.
    2026-07-10: DOM에 붙자마자(find_element 성공하자마자) 바로 반환하면 다이얼로그
    페이드인 애니메이션이 아직 안 끝난 상태라 곧바로 이어지는 .click()이
    ElementNotInteractableException을 내는 경우가 실측됨(DHL 4781407805 건,
    Organization 입력창) -> is_displayed()/is_enabled()까지 확인되어야 반환한다."""
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            el = driver.find_element(by, selector)
            if el.is_displayed() and el.is_enabled():
                return el
            last_err = None  # 찾긴 했으나 아직 상호작용 불가 상태 -> 계속 재시도
        except Exception as e:
            last_err = e
        time.sleep(0.3)
    if last_err:
        raise last_err
    raise RuntimeError(f"요소를 찾았지만 끝까지 상호작용 가능한 상태가 되지 않음(timeout): {selector}")


def _wait_find_all(driver, by, selector, filter_fn=None, timeout: float = 8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        els = driver.find_elements(by, selector)
        if filter_fn:
            els = [el for el in els if filter_fn(el)]
        if els:
            return els
        time.sleep(0.3)
    raise RuntimeError(f"요소를 못 찾음(timeout): {selector}")


def _find_menu_item(driver, text: str):
    """BI Publisher 뷰어의 gear/Export 드롭다운 메뉴 항목(class="itemTxt")을
    텍스트로 찾는다. XPath text() 기반 _click_text는 이 메뉴에서 Selenium
    is_displayed() 내부 JS 에러가 재현되어(2026-07-08 실측) 대신 사용.
    2026-07-10: 같은 텍스트("Export" 등)를 가진 .itemTxt 요소가 화면 밖
    수천 픽셀 떨어진 곳에 하나 더 존재하는 경우가 실측됨(DHL 4781407805 건,
    스크린샷+좌표로 확인 - Oracle ADF가 메뉴 템플릿을 항상 화면 밖에 대기시켜
    두는 것으로 추정). querySelectorAll 순서상 그 화면 밖 유령 요소가 먼저
    걸리면 클릭이 ElementNotInteractableException으로 실패하므로, 실제
    뷰포트 안에 있는 요소만 반환하도록 좌표로 필터링한다."""
    return driver.execute_script("""
        var els = document.querySelectorAll('.itemTxt');
        for (var i=0;i<els.length;i++) {
            if ((els[i].textContent||'').trim() !== arguments[0]) continue;
            var r = els[i].getBoundingClientRect();
            if (r.x >= 0 && r.y >= 0 && r.x < window.innerWidth && r.y < window.innerHeight
                && r.width > 0 && r.height > 0) {
                return els[i];
            }
        }
        return null;
    """, text)


# PDF Export 클릭이 씹혔을 때 다시 눌러보는 횟수와, 한 번 누른 뒤 파일이 받아지길
# 기다리는 시간(2026-08-19 추가 - 자세한 배경은 Export 블록 주석 참고).
# 폴링이라 받아지는 즉시 진행하므로 정상 회차의 소요시간에는 영향이 없다.
PDF_EXPORT_CLICK_ATTEMPTS = 3
PDF_EXPORT_WAIT_SEC = 25


def _menu_items_visible(driver) -> bool:
    """gear 드롭다운 메뉴가 지금 열려 있는지 - 뷰포트 안에 보이는 .itemTxt 항목이
    하나라도 있으면 열린 것으로 본다(2026-08-06 추가, gear 토글 오작동 방지용)."""
    try:
        return bool(driver.execute_script("""
            var els = document.querySelectorAll('.itemTxt');
            for (var i=0;i<els.length;i++) {
                var r = els[i].getBoundingClientRect();
                if (r.x >= 0 && r.y >= 0 && r.x < window.innerWidth && r.y < window.innerHeight
                    && r.width > 0 && r.height > 0) return true;
            }
            return false;
        """))
    except Exception:
        return False


def _find_gear_icon(driver):
    """BI Publisher 뷰어의 gear(설정) 아이콘. title/className이 비어 있어서
    이미지 파일명(popupmenu_ena.png)으로 식별한다(2026-07-08 확인).
    2026-07-10: Republish를 반복 실행하면(이 세션에서 테스트 중 여러 차례 반복)
    같은 popupmenu 아이콘이 화면 밖/잔존 상태로 여러 개 쌓일 수 있어 보여서,
    Export/PDF 메뉴 항목과 동일하게 화면 안에 실제로 보이는 것만 반환한다."""
    return driver.execute_script("""
        var imgs = document.querySelectorAll("img");
        for (var i=0;i<imgs.length;i++) {
            if ((imgs[i].src||'').indexOf('popupmenu') < 0) continue;
            var r = imgs[i].getBoundingClientRect();
            if (r.x >= 0 && r.y >= 0 && r.x < window.innerWidth && r.y < window.innerHeight
                && r.width > 0 && r.height > 0) {
                return imgs[i];
            }
        }
        return null;
    """)


def _click_menu_item_with_retry(driver, text: str, attempts: int = 10, delay: float = 0.3,
                                 reopen_fn=None):
    """_find_menu_item으로 찾은 메뉴 항목을 클릭 재시도까지 포함해서 처리.
    2026-07-10: 팝업 메뉴가 뜨자마자(애니메이션 안 끝난 상태) 바로 클릭하면
    ElementNotInteractableException이 나는 경우가 실측됨(DHL 4781407805 건,
    Export 메뉴). 이 위젯은 is_displayed()/is_enabled() 호출 자체가 내부 JS
    에러를 내므로(2026-07-08 확인) 표시 여부를 미리 확인하는 대신, 매번 요소를
    새로 찾아 클릭 자체를 예외 캐치하며 재시도한다(스테일 참조 방지 겸용).
    reopen_fn: 메뉴 항목을 아예 못 찾았을 때(메뉴가 이미 닫혔을 가능성) 재시도
    전에 호출하는 콜백(예: gear 아이콘 재클릭으로 메뉴 다시 열기) — 2026-07-10
    실측 결과 메뉴가 열리자마자 다시 닫히는 듯한 타이밍 이슈가 있어서 추가."""
    last_err = None
    last_el = None
    for _ in range(attempts):
        el = _find_menu_item(driver, text)
        if el is None:
            last_err = RuntimeError(f"{text} 메뉴 항목을 못 찾음")
            if reopen_fn:
                try:
                    reopen_fn()
                except Exception:
                    pass
            time.sleep(delay)
            continue
        last_el = el
        try:
            el.click()
            return
        except Exception as e:
            last_err = e
            time.sleep(delay)

    # 2026-07-10: 재시도로도 안 풀리면, 매번 2분 걸리는 오라클 왕복을 반복하며
    # 추측으로 고치는 대신 실측 데이터(스크린샷 + 엘리먼트 좌표/가시성)를 남겨서
    # 다음 조사 때 바로 원인을 좁힐 수 있게 한다.
    try:
        diag_path = os.path.join(ROOT, f"_diag_{text}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        driver.save_screenshot(diag_path)
        rect = driver.execute_script(
            "var r = arguments[0].getBoundingClientRect();"
            "var s = getComputedStyle(arguments[0]);"
            "return {rect:[r.x,r.y,r.width,r.height], display:s.display, "
            "visibility:s.visibility, opacity:s.opacity};",
            last_el,
        ) if last_el is not None else None
        log(f"[진단] {text} 메뉴 클릭 실패 진단 - 스크린샷: {diag_path}, 엘리먼트 정보: {rect}")
    except Exception as diag_e:
        log(f"[진단] 진단 정보 수집 실패: {diag_e}")

    raise last_err


def _hover_menu_item_with_retry(driver, text: str, attempts: int = 10, delay: float = 0.3,
                                 reopen_fn=None):
    """_find_menu_item으로 찾은 메뉴 항목을 "클릭"이 아니라 실제 마우스 호버로
    처리한다. 2026-07-13 실측: "Export" 항목은 하위 포맷(PDF/HTML/RTF/...) 목록을
    펼치는 서브메뉴 트리거로 보이는데, 이 하위 목록의 표시 여부가 CSS :hover
    의사클래스 기반이라 JS로 dispatchEvent('mouseover')를 흉내 내도 전혀 안 먹힘
    (:hover는 실제 브라우저 포인터 위치로만 갱신됨) — 반드시 ActionChains로 진짜
    포인터를 그 위치까지 이동시켜야 한다. click()이 아니라 move_to_element()를
    쓰는 이유가 이것이다."""
    from selenium.webdriver.common.action_chains import ActionChains
    last_err = None
    last_el = None
    for _ in range(attempts):
        el = _find_menu_item(driver, text)
        if el is None:
            last_err = RuntimeError(f"{text} 메뉴 항목을 못 찾음(호버 대상)")
            if reopen_fn:
                try:
                    reopen_fn()
                except Exception:
                    pass
            time.sleep(delay)
            continue
        last_el = el
        try:
            ActionChains(driver).move_to_element(el).pause(0.4).perform()
            return
        except Exception as e:
            last_err = e
            time.sleep(delay)

    try:
        diag_path = os.path.join(ROOT, f"_diag_hover_{text}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
        driver.save_screenshot(diag_path)
        log(f"[진단] {text} 호버 실패 진단 - 스크린샷: {diag_path}")
    except Exception as diag_e:
        log(f"[진단] 진단 정보 수집 실패: {diag_e}")

    raise last_err


def tasks_panel_open(driver) -> bool:
    """Inventory Management의 Tasks 패널이 지금 열려 있는지 판정한다.
    이 패널에만 있는 카테고리 드롭다운(Inventory/Counts/Shipments/Picks/Receipts)
    존재 여부로 본다.

    2026-08-06(2차) 추가 - 공유 브라우저 상태 간섭 대응. Tasks 아이콘은 **토글**
    이라서, 이미 열려 있는데 또 누르면 패널이 닫힌다. 그런데 이 패널의 열림
    상태는 페이지를 다시 열어도(driver.get) 유지되고, 같은 Edge를 공유하는
    자동화 중 **아무도 패널을 닫지 않는다** - 즉 앞선 자동화가 열어둔 채로
    끝내면 다음 자동화가 무조건 클릭해서 스스로 닫아버린다.
    그러면 바로 뒤의 `_wait_find(Shipments select, ...)`가 실패하고, 상위
    재시도가 다시 열어서 결국 복구는 되지만 회차당 40초 이상을 버리고 로그에는
    "요소를 못 찾음"으로 남아 원인을 오진하게 만든다(실측 확인).
    sco_cancel_watcher에서 먼저 이 가드를 넣어 검증했고(실패조건 3종 3/3 성공),
    같은 함수를 파일마다 복사하면 또 어긋나므로 여기 공용으로 둔다.

    호출부는 `if not tasks_panel_open(driver): <클릭>` 형태로 쓴다."""
    from selenium.webdriver.common.by import By
    try:
        return any(e.is_displayed() for e in driver.find_elements(
            By.XPATH, "//select[option[normalize-space(text())='Inventory']]"))
    except Exception:
        return False


def _js_click_text(driver, text: str):
    """_click_text와 같은 방식으로 요소를 찾되, 네이티브 click() 대신 JS 클릭을 쓴다.

    2026-08-06 pick_release_watcher.py에서 실측(진단 스크립트 5종)한 내용을 그대로
    옮겨온 것이다. Create Pick Wave 화면 이동이 계속 실패한 진짜 원인은 오라클
    화면 구조 변경도, 대기시간 부족도 아니라 **네이티브 클릭이 예외 없이 조용히
    씹히는 것**이었다:
      - 요소는 정확히 찾힘, 뷰포트 안, elementFromPoint도 그 요소를 가리킴(= 안 가려짐)
      - el.click()은 **예외 없이** 실행되는데 60초를 기다려도 화면이 안 바뀜(3/3 실패)
      - 같은 요소에 JS 클릭을 하면 2초 만에 화면 전환 성공
    _click_text는 네이티브 클릭이 '예외를 던질 때만' JS로 폴백하는데, 이 경우는
    조용히 무시되는 거라 폴백이 영영 안 걸린다. 원인은 2026-08-03 SSO 버튼에서
    확인된 "무인 실행 중엔 Edge 창이 백그라운드라 일반 click()이 씹힌다"와 같다.

    2026-08-06(2차): 이 헬퍼가 pick_release_watcher.py에만 있어서 icbl/ship에는
    같은 병이 그대로 남아 있었다. 구현을 여기(공용 모듈)로 옮기고 pick_release는
    이걸 import해서 쓴다 - SSO 로직이 파일별로 어긋났던 전례를 반복하지 않기 위함.

    주의: 새 창(window.open)을 띄우는 버튼에는 쓰면 안 된다. JS 클릭은 브라우저가
    '신뢰된 사용자 제스처'로 보지 않아서 팝업이 차단된다(실측 확인) -
    _republish_and_export_pdf의 republish_img.click()이 그런 경우라 거기는
    네이티브 클릭을 그대로 둔다.

    2026-08-07 추가 - **비활성(disabled) 버튼 걸러내기**: 여기서 다시 같은 병을 만났다.
    Schedule New Process 다이얼로그의 OK는 프로세스명 LOV 검증이 끝나기 전까지
    disabled인데, disabled여도 is_displayed()는 True라 이 함수가 그걸 골라 눌렀고,
    비활성 버튼 클릭은 예외도 안 나고 아무 일도 안 일어났다(2026-08-06~07 DHL
    1186918773이 11번 헛돈 원인). 눌러도 아무 일이 없을 게 확실한 요소는 애초에
    후보에서 빼고, 후보가 전부 비활성이면 조용히 넘어가지 말고 그 사실을 던진다."""
    from selenium.webdriver.common.by import By

    def _pick(xpath):
        shown = [el for el in driver.find_elements(By.XPATH, xpath) if el.is_displayed()]
        return shown, [el for el in shown if el.is_enabled()]

    shown, els = _pick(f"//*[normalize-space(text())='{text}']")
    if not els:
        shown2, els = _pick(f"//*[contains(normalize-space(text()), '{text}')]")
        shown = shown or shown2
    if not els:
        if shown:
            raise RuntimeError(f"'{text}' 요소는 있는데 전부 비활성 상태라 누를 수 없음")
        raise RuntimeError(f"클릭할 요소를 못 찾음: {text}")
    driver.execute_script(
        "arguments[0].scrollIntoView(true); arguments[0].click();", els[0])


def _click_text(driver, text: str, attempts: int = 5, delay: float = 0.4):
    """텍스트로 요소를 찾아 클릭.
    2026-07-10: 클릭 직전에 페이지가 다시 렌더링되면(예: "OK" 버튼 클릭 전
    ADF의 비동기 검증/postback) 미리 찾아둔 요소 참조가 무효화되어
    StaleElementReferenceException이 나는 경우가 실측됨(DHL 4781407805 건) ->
    매 시도마다 요소를 처음부터 새로 찾아 재시도한다."""
    from selenium.webdriver.common.by import By
    last_err = None
    for _ in range(attempts):
        try:
            candidates = [el for el in driver.find_elements(By.XPATH, f"//*[normalize-space(text())='{text}']") if el.is_displayed()]
            if not candidates:
                candidates = [el for el in driver.find_elements(By.XPATH, f"//*[contains(normalize-space(text()), '{text}')]") if el.is_displayed()]
            if not candidates:
                last_err = RuntimeError(f"클릭할 요소를 못 찾음: {text}")
                time.sleep(delay)
                continue
            el = candidates[0]
            driver.execute_script("arguments[0].scrollIntoView(true);", el)
            time.sleep(0.3)
            try:
                el.click()
            except Exception:
                driver.execute_script("arguments[0].click();", el)
            return
        except Exception as e:
            last_err = e
            time.sleep(delay)
    raise last_err


# ==============================================================
# 4) Outlook 답장 초안 작성
# ==============================================================
# 2026-08-10 사용자 요청: 인천관세법인으로 나가는 답장은 전부 이 인사말로 통일.
# 문구를 여기 한 곳에만 두어 아래 3가지 경우(금액불일치/첨부있음/이상없음)가
# 따로 놀지 않게 한다.
# 2026-08-28 사용자 요청: 특정 담당자(권순구 과장님) 지칭 제거, 발신자 소개로 변경.
ICBL_GREETING = "안녕하세요 켄델라코리아 채윤길입니다,"

# 2026-08-10 사용자 요청: 자동 발송/초안 메일 글꼴을 굴림 -> 맑은 고딕으로 통일.
# 굴림이 나오던 이유: 우리가 끼워 넣던 <div>에 글꼴 지정이 없어서 원본 메일
# (인천관세법인 메일은 RTF에서 변환돼 굴림 마크업이 붙어 있다)의 글꼴을 그대로
# 물려받았다. 평문(.Body)으로 만들던 메일도 Outlook의 평문 기본 글꼴을 따라간다.
MAIL_FONT_CSS = "font-family:'맑은 고딕',Malgun Gothic,sans-serif;font-size:10.0pt"


def mail_text_to_html(text: str) -> str:
    """평문 본문을 맑은 고딕 HTML로 감싼다.
    HTML은 연속 공백을 하나로 줄이므로, 들여쓰기가 있는 알림 본문이 뭉개지지
    않도록 2칸 이상 연속 공백은 &nbsp;로 보존한다."""
    import html as html_module
    esc = html_module.escape(str(text or ""))
    esc = esc.replace("\r\n", "\n").replace("\r", "\n")
    esc = re.sub(r"  +", lambda mm: "&nbsp;" * len(mm.group()), esc)
    esc = esc.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
    return f'<div style="{MAIL_FONT_CSS}">' + esc.replace("\n", "<br>") + "</div>"


def create_reply_draft(entry_id: str, attachment_paths, mismatch: bool, send: bool = False):
    """attachment_paths: 단일 경로(str) / 경로 리스트(list) / None 모두 허용.
    2026-07-09: FBC+FBS 결합 건은 오라클 PDF가 2개(조직별 1개씩) 나와서 둘 다
    첨부해야 하므로 리스트를 지원하도록 확장.
    2026-07-24 사용자 요청: 가격이 일치하는(이상 없는) 건은 임시보관함에 초안만
    만들지 말고 바로 발송한다 - 사람이 볼 것도 없이 "문제 없음"으로 확정된
    건이므로.
    2026-08-21 사용자 요청: 가격 불일치 건도 send=True로 바로 발송한다(오라클
    기준 인보이스 첨부). 현재 호출부는 전부 send=True이며, send 기본값 False는
    수동 디버깅용으로만 남겨둔다."""
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    mail = ns.GetItemFromID(entry_id)

    reply = mail.ReplyAll()
    has_attachments = False
    if attachment_paths:
        paths = [attachment_paths] if isinstance(attachment_paths, str) else attachment_paths
        for p in paths:
            if p:
                reply.Attachments.Add(p)
                has_attachments = True

    # 2026-08-31 사용자 요청: 수입신고 시 Delivery Number가 누락/오기재되면
    # pdf_auto_updater가 나중에 필증을 파싱해도 매칭할 행을 못 찾아 실적이
    # 조용히 빈다(한 메일에 Delivery가 여러 개인 결합 건일수록 더 그렇다) -
    # 매 회신마다 명시적으로 기입을 요청해서 이 사각지대를 줄인다.
    delivery_note = "수입신고필증 신고인기재란에 Delivery number 기입 부탁드립니다."
    if mismatch:
        body = (f"{ICBL_GREETING}\n\n검토 결과 금액에 차이가 있어, 오라클 시스템 기준 Commercial Invoice를 "
                f"첨부해드립니다. 첨부드린 인보이스로 진행 부탁드립니다.\n\n{delivery_note}\n\n감사합니다.\n\n")
    elif has_attachments:
        # 2026-07-16 사용자 요청: 조직 2개(FBC+FBS 등)라 가격은 맞아도 오라클
        # 인보이스를 여러 건 첨부하는 경우 - 각 Delivery Number가 수입면장에
        # 다 기재되도록 원본 CI 대신 오라클 인보이스로 진행해달라고 안내한다.
        # "문제 없습니다"는 파일을 첨부해서 보낼 때는 혼동을 줄 수 있어 안 쓴다
        # (사용자 요청).
        body = f"{ICBL_GREETING}\n\n첨부된 invoice로 진행 부탁드립니다.\n\n{delivery_note}\n\n감사합니다.\n\n"
    else:
        body = f"{ICBL_GREETING}\n\n확인 결과 문제 없습니다. 해당 invoice로 진행 부탁드립니다.\n\n{delivery_note}\n\n감사합니다.\n\n"

    # 2026-08-03 사용자 요청: 인천관세법인 답장 서식이 깨짐 - 원본 메일이 HTML
    # 형식(BodyFormat != 1, 서명/폰트/표 등 포함)인데 reply.Body(순수 텍스트)를
    # 직접 건드리면 Outlook이 HTMLBody 전체를 이 텍스트 기준의 밋밋한 HTML로
    # 새로 만들어버려서 원본 서식이 통째로 깨진다(실측). <body> 태그 바로 뒤에
    # 우리 문구만 HTML로 끼워 넣어 원본 서식(인용된 원본 메일 포함)은 그대로
    # 보존한다. 원본이 순수 텍스트 형식이면 서식 깨질 게 없으니 기존 방식 그대로.
    try:
        is_plain_text = reply.BodyFormat == 1
    except Exception:
        is_plain_text = False
    if is_plain_text:
        reply.Body = body + reply.Body
    else:
        html_prefix = mail_text_to_html(body)
        existing_html = reply.HTMLBody
        m = re.search(r"(<body[^>]*>)", existing_html, re.IGNORECASE)
        if m:
            insert_at = m.end()
            reply.HTMLBody = existing_html[:insert_at] + html_prefix + existing_html[insert_at:]
        else:
            reply.Body = body + reply.Body
    if send:
        # 2026-07-27 실측(DHL 2848658831): .Send() 호출 자체는 성공해서 실제로
        # 발송됐는데(Sent Items에서 확인), 그 직후 reply.EntryID를 읽으려다가
        # "The item has been moved or deleted" COM 에러가 났다 - Send()가 항목을
        # Sent Items로 옮기면서 기존 COM 참조가 무효화되는 것으로 보임. 이
        # 에러가 위로 전파되면 실제로는 발송에 성공한 건을 "실패"로 착각해서
        # 상태 저장을 안 하고 재시도하다가 중복 발송으로 이어질 위험이 있다.
        # 호출부 어디도 반환값(EntryID)을 쓰지 않으므로, 발송 후에는 아예
        # 접근하지 않고 None을 반환한다.
        reply.Send()
        return None
    reply.Save()
    return reply.EntryID


def create_yongma_receive_notice_draft(case: dict):
    """2026-09-18 사용자 요청: IDC가 아닌 경로로 들어온 WAY 재배치(일본/중국/홍콩/
    호주/스페인발) 건은 APAC Stock Movements 리스트에서 Receive Delivery#를
    확인해 CI를 뽑는데, 이때 Receive TO#도 같이 확인해서 용마(창고)에 입고 안내
    메일 초안을 만든다. 인천관세법인 앞 답장(create_reply_draft)과 달리 이 메일은
    새 메일이며(용마가 보낸 원본 메일에 대한 답장이 아님), 오라클 Receive 처리
    자체는 여기서 하지 않는다(창고/담당자가 직접 하는 액션) - 안내 메일만 초안
    저장한다. 사용자 지시(2026-09-18)로 지금은 자동발송하지 않고 초안까지만
    만든다. CI는 첨부하지 않는다(2026-09-18 사용자 지시). TO#/Receive TO#는
    아직 라이브 검증 전이라 못 읽으면 "확인 필요"로 표기해서 사람이 채워 넣게
    한다."""
    import win32com.client

    to_no = case.get("way_to_no") or "확인 필요"
    receive_to_no = case.get("way_receive_to_no") or "확인 필요"
    receive_delivery_no = case["org_delivery_pairs"][0][1]
    from_org = case["way_from_org"]

    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)  # olMailItem
    mail.To = YONGMA_MAIL_TO
    mail.Subject = f"TO {to_no} Rebalance 입고 안내 (Receive TO {receive_to_no})"
    body = (
        f"안녕하세요 기훈님 용호님\n\n"
        f"IDC가 아닌 경로로 들어온 Rebalance 입고 건 안내드립니다.\n\n"
        f"From: {from_org}\n"
        f"TO#: {to_no}\n"
        f"Receive TO#: {receive_to_no}\n"
        f"Receive Delivery#: {receive_delivery_no}\n\n"
        f"Receive 처리 부탁드립니다.\n\n"
        f"감사합니다.\n"
    )
    mail.HTMLBody = mail_text_to_html(body)
    mail.Save()  # 초안만 저장, 자동 발송 안 함(사용자 지시, 2026-09-18)
    log(f"[용마 안내] {case['label']}: TO={to_no}, Receive TO={receive_to_no}, "
        f"Receive Delivery={receive_delivery_no} 초안 저장")


def send_alert(subject: str, body: str, dedup_key: str | None = None,
                dedup_ttl_hours: float | None = None):
    """알림 메일 초안을 저장한다. dedup_key를 주면(보통 f"{entry_id}:사유" 형태),
    같은 키로 dedup_ttl_hours(기본 ALERT_DEDUP_TTL_HOURS) 이내에 이미 보낸 적이
    있으면 또 보내지 않고 조용히 스킵한다. 2026-07-14: 처리가 안 끝나는 건(재발송
    대기 중 등)은 20분 스케줄마다 계속 재시도되는데, 그때마다 똑같은 알림이 또
    쌓이는 걸 막기 위함(사용자 확인). entry_id를 키에 포함시켜서, 같은 AWB/DHL
    번호라도 다른 메일(예: 재발송)이면 별개로 취급해 알림이 정상적으로 나가게
    한다.
    2026-07-14 추가: C.I 확인 필요 알림은 사용자 요청으로 dedup_ttl_hours=inf를
    넘겨 "재발송 오기 전까지 딱 한 번만" 알리도록 함(같은 entry_id는 내용이
    안 바뀌므로 재알림 자체가 무의미 - 재발송은 어차피 다른 entry_id라 정상
    알림됨). 오라클 재로그인 필요/조회 실패는 상황이 바뀔 수 있어 기본
    TTL(6시간) 그대로 유지."""
    ttl_hours = ALERT_DEDUP_TTL_HOURS if dedup_ttl_hours is None else dedup_ttl_hours
    if dedup_key:
        alerted = load_alerted_state()
        prev = alerted.get(dedup_key)
        if prev:
            try:
                prev_dt = datetime.strptime(prev["alerted_at"], "%Y-%m-%d %H:%M:%S")
                if (datetime.now() - prev_dt).total_seconds() < ttl_hours * 3600:
                    log(f"[정보] 동일 건 알림 이미 발송함(재발송 전까지 스킵) -> 중복 스킵: {subject}")
                    return
            except Exception as e:
                # 2026-08-06: 여기서 조용히 넘어가면 중복 방지가 풀려서 같은
                # 알림이 매 회차(20분마다) 반복 발송된다 - 받는 사람 입장에선
                # "왜 같은 메일이 계속 오지"가 되는데 원인이 로그에 안 남았다.
                log(f"[경고] 알림 중복 방지 기록을 해석하지 못해 중복 발송될 수 있음"
                    f"({type(e).__name__}: {e}, key={dedup_key})")

    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = ALERT_MAIL_TO
    mail.Subject = subject
    mail.HTMLBody = mail_text_to_html(body)
    mail.Save()  # 초안만 저장, 자동 발송 안 함 (알림 목적이므로 임시보관함에서 바로 확인 가능)
    log(f"알림 메일 초안 저장: {subject}")

    if dedup_key:
        alerted = load_alerted_state()
        alerted[dedup_key] = {"alerted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "subject": subject}
        save_alerted_state(alerted)


# ==============================================================
# 5) 건별 처리 (FedEx / DHL)
# ==============================================================
class OracleLoginRequired(Exception):
    pass


class OracleStillProcessing(Exception):
    """2026-07-13: 오라클 리포트가 아직 Succeeded가 안 돼서(Blocked/큐 지연) 이번
    실행의 짧은 대기(약 17분) 안에 못 끝난 경우. 진짜 에러가 아니라 다음 스케줄
    실행이 저장된 Process ID로 이어서 재시도할 정상적인 상황이므로, 사람 확인
    알림(오라클 조회 실패) 없이 조용히 넘어가야 한다."""
    pass


def finalize_way_case(case: dict, state: dict) -> None:
    """WAY(일본/중국/홍콩 재배치) 케이스의 오라클 리포트가 완료된 뒤 Ship From
    패치 + 답장 발송 + 상태 저장. 이 케이스는 원본 C.I가 현지 통화라 오라클
    KRW 금액과 직접 비교가 무의미해서(사용자의 수기 절차에도 금액 대조 단계가
    없음) 가격 검증 없이 오라클 인보이스로 바로 진행한다."""
    label = case["label"]
    pair = case["org_delivery_pairs"][0]
    result = case["results"][pair]
    if result.get("pdf_path") is None:
        log(f"[경고] {label}: WAY Org PDF 생성 실패")
        send_alert(
            f"[오라클 조회 실패] {label}",
            "WAY(일본/중국/홍콩 재배치) PDF 생성에 실패했습니다. 다음 자동 실행에서 재시도합니다.",
            dedup_key=f"{case['entry_id']}:oracle_query_fail",
        )
        return

    patched_path = patch_ship_from_in_pdf(result["pdf_path"], case["way_address_lines"])
    log(f"[WAY 재배치 자동처리] {label}: Delivery={case['way_orig_delivery_no']} -> "
        f"From={case['way_from_org']}, Receive Delivery#={pair[1]}, 패치된 PDF={patched_path}")
    create_reply_draft(case["entry_id"], [patched_path], mismatch=False, send=True)

    try:
        create_yongma_receive_notice_draft(case)
    except Exception as e:
        # 용마 안내 메일은 부가 기능이라 실패해도 인천관세법인 답장/상태 저장 등
        # 기존 핵심 흐름을 막지 않는다.
        log(f"[경고] {label}: 용마 입고 안내 메일 초안 생성 실패: {e}\n{traceback.format_exc()}")

    state[case["state_key"]] = {
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "format": "way_rebalance",
        "delivery_no": case["way_orig_delivery_no"],
    }
    save_state(state)
    log(f"완료(WAY 재배치): {label}")


def finalize_standard_case(driver, case: dict, state: dict) -> None:
    """오라클 Print Commercial Invoice Report 결과가 다 모인 뒤 가격 대조 ->
    결과에 따라 답장 발송/초안 + 상태 저장. FedEx/DHL 공통 로직.

    org_delivery_pairs: [(org_code, delivery_no), ...]. 보통 1개인데, 2026-07-09
    추가된 FBC+FBS 결합 건은 2개(조직별로 오라클 리포트를 따로 뽑아야 함) — 이 경우
    두 리포트의 총액을 합산해서 원본 C.I 총액과 비교하고, 불일치 시 PDF 2개를
    모두 답장에 첨부한다."""
    label = case["label"]
    entry_id = case["entry_id"]
    total = case["doc_total"]
    org_delivery_pairs = list(case["org_delivery_pairs"])
    oracle_results = [case["results"][p] for p in org_delivery_pairs]
    sample_confirm_pn = case.get("sample_confirm_pn")
    # 2026-09-18 사용자 확인: 확인서 PDF가 잘못 만들어져 수정본 대기 중 -
    # 잘못된 파일이 실제 회신에 나가면 안 되므로 SAMPLE_CONFIRM_ENABLED=False인
    # 동안은 첨부를 건너뛰고, 이 건이 놓치지 않게 알림만 남긴다(회신 자체는
    # 평소대로 자동 진행).
    if sample_confirm_pn and not SAMPLE_CONFIRM_ENABLED:
        log(f"[시료확인서] {label}: 품목 {sample_confirm_pn} 포함이지만 확인서 PDF가 수정본 대기 중이라 첨부 생략")
        send_alert(
            f"[시료확인서 첨부 보류] {label}",
            f"품목번호 {sample_confirm_pn}이(가) 포함된 CI 회신이 나갔지만, 확인서 PDF가 "
            f"수정본 대기 중(SAMPLE_CONFIRM_ENABLED=False)이라 첨부하지 못했습니다.\n"
            f"수정본이 오면 SAMPLE_CONFIRM_PDF_PATH 파일을 교체하고 SAMPLE_CONFIRM_ENABLED를 "
            f"다시 켠 뒤, 이 건은 확인서만 별도로 인천관세법인에 보내주세요.",
            dedup_key=f"{entry_id}:sample_confirm_paused",
        )
        sample_confirm_pn = None
    # 2026-09-17 사용자 확정: 품목당 확인서는 1회만 첨부하면 됨 - 이미 보낸
    # 품목이면 이번엔 확인서 없이 평소처럼 회신한다.
    elif sample_confirm_pn and sample_confirm_already_sent(sample_confirm_pn):
        log(f"[시료확인서] {label}: 품목 {sample_confirm_pn}은 이미 이전에 확인서 발송함 -> 이번엔 첨부 생략")
        sample_confirm_pn = None

    if any(r["total"] is None for r in oracle_results):
        oracle_total = None
    else:
        oracle_total = sum(r["total"] for r in oracle_results)

    price_match = (
        oracle_total is not None
        and abs(oracle_total - total) <= max(1.0, total * 0.001)
    )

    # 2026-07-16 사용자 요청: FBC 단일 건인데 불일치가 나면, 같은 선적일의
    # FBS 건이 실은 같이 와야 하는 별도 Delivery일 수 있어(예: PPS Dongle -
    # DHL 5812115621 건에서 실측 확인, 차액이 정확히 그 FBS 품목 금액과
    # 일치했음) 찾아서 추가로 대조해본다. 처음부터 무조건 찾지 않고 불일치
    # 때만 시도하는 이유: 같은 날 우연히 무관한 FBS 건이 있어도 잘못 엮는
    # 걸 방지하기 위함. 합산해도 안 맞으면 이 시도는 버리고 원래 결과
    # (단일 건 불일치)로 그대로 진행한다.
    # 2026-08-03: 이 재확인은 1차 결과(불일치 여부)가 나와야만 알 수 있는
    # 후속 조회라 다른 건들과 미리 같이 제출해둘 수 없다 - 여기서만 예전처럼
    # 제출+블로킹 대기(_wait_for_oracle_report)로 처리한다(드문 경로라 전체
    # 처리 속도에 미치는 영향은 작음).
    if not price_match and len(org_delivery_pairs) == 1 and org_delivery_pairs[0][0] == "FBC":
        fbc_delivery_no = org_delivery_pairs[0][1]
        # 2026-09-15 사용자 확정 순서: 1) B/L번호(=WayBill/Tracking Number, 가장
        # 정확) 먼저 확인 -> 2) 없으면 같은 선적일 전체 대조(라벨 FBC/FBS 무관,
        # find_same_ship_date_siblings 설명 참고 - FBS만 찾다가 실제로는 FBC로
        # 찍힌 형제 delivery를 놓친 사고 발생).
        match_method = "B/L번호"
        extra_pairs = find_same_waybill_siblings(fbc_delivery_no)
        if not extra_pairs:
            match_method = "선적일자"
            extra_pairs = find_same_ship_date_siblings(fbc_delivery_no)
        if extra_pairs:
            log(f"[FBC/FBS 재확인] {label}: 불일치 발생 -> {match_method} 기준 형제 후보 발견: "
                f"{extra_pairs}, 추가 대조 시도")
            extra_results = []
            try:
                for org_code, delivery_no in extra_pairs:
                    pid = submit_oracle_ci_report(driver, org_code, delivery_no)
                    r = _wait_for_oracle_report(driver, org_code, delivery_no, pid)
                    log(f"오라클 조회 결과 ({label}, org={org_code}, delivery={delivery_no}) "
                        f"total={r['total']}")
                    extra_results.append(r)
            except OracleStillProcessing as e:
                log(f"[대기] {label}: FBC/FBS 재확인 중 {e} -> 이번 회차 종료, 다음 스케줄에서 이어서 확인")
                return
            if oracle_total is not None and not any(r["total"] is None for r in extra_results):
                widened_total = oracle_total + sum(r["total"] for r in extra_results)
                widened_match = abs(widened_total - total) <= max(1.0, total * 0.001)
                log(f"[FBC/FBS 재확인] {label}: 합산 후 총액={widened_total} "
                    f"(문서 금액={total}) -> {'일치' if widened_match else '여전히 불일치'}")
                if widened_match:
                    org_delivery_pairs = org_delivery_pairs + extra_pairs
                    oracle_results = oracle_results + extra_results
                    oracle_total = widened_total
                    price_match = True

    if price_match:
        if len(org_delivery_pairs) > 1:
            # 2026-07-16 사용자 요청: 조직이 2개(FBC+FBS 등)면 가격이 맞아도
            # 원본 CI 하나만 회신하면 안 됨 - 각 조직의 Delivery Number가
            # 수입면장에 다 기재돼야 pdf_auto_updater가 나중에 파싱할 수
            # 있는데, 원본 CI엔 두 Delivery가 같이 안 적혀있는 경우가 있음
            # (예: 같은 선적일로만 엮인 FBC+FBS - 서로 다른 문서). 그래서
            # 오라클에서 뽑은 인보이스를 조직 수만큼 전부 첨부해서 보낸다.
            # 2026-07-24 사용자 요청: 가격 일치(이상 없음)면 사람이 볼 것도
            # 없이 바로 발송한다 - 초안만 만들고 기다리지 않음.
            log(f"가격 일치 ({label}, 조직 {len(org_delivery_pairs)}개) -> "
                f"오라클 인보이스 {len(oracle_results)}건 첨부해서 자동 발송")
            pdf_paths = [r.get("pdf_path") for r in oracle_results]
            if sample_confirm_pn:
                log(f"[시료확인서] {label}: 품목 {sample_confirm_pn} -> 확인서 PDF 첨부")
                pdf_paths.append(SAMPLE_CONFIRM_PDF_PATH)
            create_reply_draft(entry_id, pdf_paths, mismatch=False, send=True)
            if sample_confirm_pn:
                mark_sample_confirm_sent(sample_confirm_pn, label)
        else:
            log(f"가격 일치 ({label}) -> 원본 C.I로 자동 발송")
            if sample_confirm_pn:
                log(f"[시료확인서] {label}: 품목 {sample_confirm_pn} -> 확인서 PDF 첨부")
                create_reply_draft(entry_id, [SAMPLE_CONFIRM_PDF_PATH], mismatch=False, send=True)
                mark_sample_confirm_sent(sample_confirm_pn, label)
            else:
                create_reply_draft(entry_id, None, mismatch=False, send=True)
    else:
        # 2026-08-21 사용자 요청: 가격 불일치도 초안으로 세워두지 말고 바로 발송한다.
        # 불일치 건의 처리 방법(오라클 기준 인보이스를 첨부해서 그걸로 진행 요청)이
        # 항상 같아서 사람이 검토해도 결국 그대로 보내게 되기 때문. 알림 메일은
        # 사후 확인용으로 계속 남긴다.
        log(f"가격 불일치 ({label}, 문서금액={total} vs Oracle={oracle_total})"
            f" -> 오라클 PDF 첨부({len(oracle_results)}건)해서 자동 발송")
        pdf_paths = [r.get("pdf_path") for r in oracle_results]
        if sample_confirm_pn:
            log(f"[시료확인서] {label}: 품목 {sample_confirm_pn} -> 확인서 PDF 첨부")
            pdf_paths.append(SAMPLE_CONFIRM_PDF_PATH)
        create_reply_draft(entry_id, pdf_paths, mismatch=True, send=True)
        if sample_confirm_pn:
            mark_sample_confirm_sent(sample_confirm_pn, label)
        send_alert(
            f"[가격 불일치·자동발송] {label}",
            f"{label} 건, 문서 금액={total} / Oracle 합산 금액={oracle_total} "
            f"({', '.join(f'{o}:{d}' for o, d in org_delivery_pairs)}).\n"
            f"오라클 기준 인보이스를 첨부해 인천관세법인으로 **자동 발송**했습니다. "
            f"(사후 확인용 알림 - 금액 차이가 이상하면 발송함에서 확인하세요.)"
        )

    state_entry = {
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "price_match": price_match,
    }
    state_entry.update(case["state_extra"])
    if case["format"] == "dhl":
        state_entry["org_delivery_pairs"] = org_delivery_pairs
    state[case["state_key"]] = state_entry
    save_state(state)
    log(f"완료: {label}")


def build_fedex_case(driver, m: dict, state: dict) -> dict | None:
    """FedEx 메일 1건의 추출(OCR)과 WAY 재배치 판별까지만 수행하고, 오라클 제출은
    하지 않는다(main()의 제출/폴링 단계에서 처리). 처리할 게 있으면 case 딕셔너리를,
    이 회차에 더 할 게 없으면(정보 부족 알림 처리 완료, 일시적 스킵 등) None을 반환."""
    awb_no = m["key"]
    label = f"AWB {awb_no}"
    log(f"[FedEx] 신규 건 발견: {label} / {m['subject']}")

    try:
        pdf_path = save_attachment(m["entry_id"], m["attachment_name"], f"AWB{awb_no}.pdf")
        log(f"첨부 저장: {pdf_path}")
    except Exception as e:
        log(f"[에러] 첨부 저장 실패 ({label}): {exc_detail(e)}")
        return None

    try:
        ci = extract_ci_info(pdf_path)
        log(f"OCR 추출: delivery={ci['delivery_no']} ship_from={ci['ship_from_raw']}"
            f"({ci['ship_from_org']}) total={ci['total']}")
    except Exception as e:
        log(f"[에러] OCR 추출 실패 ({label}): {exc_detail(e)}")
        return None

    text_org = ci["ship_from_org"]
    try:
        ci["ship_from_org"] = resolve_ship_from_org(text_org, ci["delivery_no"])
    except DeclarationFileLocked as e:
        # 2026-07-23 실측(DHL 1696566900): 실적 파일이 Excel로 열려 있어 일시적으로
        # 못 읽는 것뿐인데 "Ship From 확정 불가"로 오판해 사람 확인 알림을 보내면
        # 안 된다. 알림/상태 저장 없이 이번 회차만 조용히 넘기고 다음 스케줄에서
        # 재시도한다(파일이 닫히면 자연히 풀림).
        log(f"[대기] {e} -> {label} 이번 회차 스킵(다음 주기에 재시도)")
        return None
    if text_org in TEXT_AMBIGUOUS_ORGS and ci["ship_from_org"] != text_org:
        log(f"[FBC/FBS 확정] {label}: 텍스트={text_org} -> 실적파일 대조 결과={ci['ship_from_org']}")

    # 2026-07-20: Ship From 조직 확정이 안 됐지만(SHIP_FROM_ORG_MAP/실적파일 모두
    # 실패) Delivery Number는 뽑혔으면, 일본/중국/홍콩발 재고 재배치(Rebalance)
    # 건일 수 있다 - SharePoint 대조 후 맞으면 WAY Org로 처리(오라클 제출/완료는
    # main()의 제출/폴링 단계에서 처리).
    if not ci["ship_from_org"] and ci["delivery_no"]:
        way = detect_way_rebalance(driver, m["entry_id"], label, ci["delivery_no"])
        if way == "ERROR":
            return None
        if way:
            return {
                "kind": "way_rebalance", "format": "fedex",
                "entry_id": m["entry_id"], "label": label,
                "state_key": m["state_key"],
                "org_delivery_pairs": [("WAY", way["receive_delivery_no"])],
                "way_address_lines": way["address_lines"],
                "way_from_org": way["from_org"],
                "way_orig_delivery_no": ci["delivery_no"],
                "way_to_no": way.get("to_no"),
                "way_receive_to_no": way.get("receive_to_no"),
            }
        # way is None(예외 없이) -> SharePoint에 이 delivery가 없거나 From이
        # WAY_REBALANCE_COUNTRY_SHEETS 밖(지원 대상이 아닌 낯선 조직) -> WAY
        # 재배치 건이 아닌 것으로 보고 아래 기존 "정보 부족" 흐름(사람 확인 필요)으로 계속 진행

    if not ci["delivery_no"] or not ci["ship_from_org"] or ci["total"] is None:
        log(f"[경고] 필요한 정보를 다 못 뽑음 ({label}) -> 사람 확인 필요, 스킵")
        send_alert(
            f"[C.I 확인 필요] {label}",
            f"자동으로 정보 추출이 부족하여 확인이 필요합니다.\n"
            f"Delivery: {ci['delivery_no']}\nShip From: {ci['ship_from_raw']}\nTotal(OCR): {ci['total']}\n"
            f"PDF: {pdf_path}",
            dedup_key=f"{m['entry_id']}:ci_missing",
            dedup_ttl_hours=float("inf"),  # 재발송(다른 entry_id) 오기 전까지 딱 한 번만
        )
        return None

    sample_confirm_pn = find_sample_confirm_part_number(ci["raw_text"])
    if sample_confirm_pn:
        log(f"[시료확인서] {label}: 품목 {sample_confirm_pn} 포함 -> 회신에 시료확인서 첨부 예정")

    return {
        "kind": "standard", "format": "fedex",
        "entry_id": m["entry_id"], "label": label,
        "state_key": m["state_key"],
        "org_delivery_pairs": [(ci["ship_from_org"], ci["delivery_no"])],
        "doc_total": ci["total"],
        "state_extra": {"delivery_no": ci["delivery_no"]},
        "sample_confirm_pn": sample_confirm_pn,
    }


def build_dhl_case(driver, m: dict, state: dict) -> dict | None:
    """DHL 형식(2026-07-08 지원 추가): EWB/HWB(텍스트 PDF)에서 총액(Customs Value)을
    뽑고, INV 첨부 중 OCR로 판별한 진짜 C.I에서 SO Number/Ship From/Delivery Number를
    뽑는다(오라클 제출은 main()의 제출/폴링 단계에서 처리).
    Delivery Number는 전체 페이지 OCR 대신 우측 상단 고정 박스만 크롭해서 뽑는다
    (extract_delivery_number_from_ci) — 3단 컬럼 헤더가 섞여서 전체 OCR로는 신뢰 불가.

    2026-07-09: FBC+FBS 결합 건 지원 추가. Delivery Number 박스에 번호가 2개
    (+로 연결)면 오라클 리포트를 조직별로 각각 뽑아야 하는데, C.I 자체엔 어느
    번호가 FBC/FBS인지 안 나오므로 lookup_ship_from_by_delivery()로 실적 파일과
    대조해서 판별한다."""
    key = m["key"]
    label = f"DHL {key}"
    log(f"[DHL] 신규 건 발견: {label} / {m['subject']}")

    saved = {"inv_list": []}
    try:
        if m.get("ewb_attachment"):
            saved["ewb"] = save_attachment(m["entry_id"], m["ewb_attachment"], f"DHL{key}_{m['ewb_attachment']}")
        if m.get("hwb_attachment"):
            saved["hwb"] = save_attachment(m["entry_id"], m["hwb_attachment"], f"DHL{key}_{m['hwb_attachment']}")
        saved["inv_list"] = [
            save_attachment(m["entry_id"], a, f"DHL{key}_{a}") for a in m["inv_attachments"]
        ]
    except Exception as e:
        log(f"[에러] DHL 첨부 저장 실패 ({label}): {exc_detail(e)}")
        return None

    total = None
    for wb_path in [saved.get("ewb"), saved.get("hwb")]:
        if wb_path:
            total = extract_customs_value_from_waybill(wb_path)
            if total is not None:
                break

    ci_paths = []
    texts = {}
    try:
        ci_paths, texts = identify_dhl_ci_pdf(saved["inv_list"])
    except Exception as e:
        log(f"[에러] DHL C.I 판별 실패 ({label}): {exc_detail(e)}")

    # 2026-08-31 사용자 지적(AWB 2697218694): 한 메일에 서로 다른 shipment의
    # C.I가 진짜로 여러 장(각각 다른 Delivery) 같이 오는 경우가 있다 - 예전엔
    # identify_dhl_ci_pdf가 첫 번째 C.I만 골라서 나머지 shipment의 Delivery가
    # 통관 회신에서 통째로 빠졌다. 이제 C.I 파일별로 각각 필드/Delivery Number를
    # 뽑아서 전부 반영한다. per_ci[i] = {"path", "fields", "delivery_numbers"}.
    per_ci = []
    for p in ci_paths:
        entry = {"path": p, "fields": {"so_no": None, "ship_from_org": None}, "delivery_numbers": []}
        try:
            ci_text = texts.get(p) or "\n".join(ocr_pdf_pages(p))
            texts[p] = ci_text
            entry["fields"] = extract_dhl_ci_fields(ci_text)
        except Exception as e:
            log(f"[에러] DHL C.I 필드 추출 실패 ({label}, {os.path.basename(p)}): {exc_detail(e)}")
        try:
            entry["delivery_numbers"] = extract_delivery_number_from_ci(p)
        except Exception as e:
            log(f"[에러] DHL Delivery Number 크롭 OCR 실패 ({label}, {os.path.basename(p)}): {exc_detail(e)}")
        per_ci.append(entry)

    log(f"[DHL] 추출 결과 ({label}): CI파일 {len(ci_paths)}개={[os.path.basename(p) for p in ci_paths]} "
        f"SO={[e['fields']['so_no'] for e in per_ci]} "
        f"ShipFrom(CI)={[e['fields']['ship_from_org'] for e in per_ci]} "
        f"Delivery={[e['delivery_numbers'] for e in per_ci]} Total(waybill)={total}")

    missing = []
    if not ci_paths:
        missing.append("Commercial Invoice 판별 실패(INV 첨부 중 어느 것이 C.I인지 OCR로 못 찾음)")
    if ci_paths and not any(e["delivery_numbers"] for e in per_ci):
        missing.append("Delivery Number")
    if total is None:
        missing.append("Customs Value(총액)")

    # 2026-07-09: 한 C.I 안에서 Delivery Number가 2개면 FBC+FBS 결합 건 — C.I
    # 자체엔 어느 번호가 FBC/FBS인지 안 나오므로 실적 파일의 Delivery Number
    # 컬럼과 대조해서 판별한다. 1개면 그 C.I에서 OCR로 뽑은 ship_from_org를
    # 그대로 쓴다. C.I가 딱 1장뿐이고 그 안에 번호도 1개인데 조직 확정이
    # 안 되면(=기존 단일 건 케이스) WAY(일본/중국/홍콩 재배치) 후보로 본다 -
    # C.I가 여러 장인 결합 건은 재배치 대상이 아니므로 이 판별을 시도하지 않는다.
    org_delivery_pairs: list[tuple[str, str]] = []
    try:
        for idx, e in enumerate(per_ci):
            dns = e["delivery_numbers"]
            text_org = e["fields"]["ship_from_org"]
            label_ci = f"CI#{idx + 1}({os.path.basename(e['path'])})" if len(per_ci) > 1 else label
            if len(dns) > 2:
                log(f"[경고] Delivery Number가 2개 초과로 검출됨 ({label_ci}): {dns}")
                missing.append(f"{label_ci} Delivery Number 3개 이상 검출(예상 밖 형식): {dns}")
            elif len(dns) == 2:
                for dn in dns:
                    o = lookup_ship_from_by_delivery(dn)
                    if o is None:
                        missing.append(f"{label_ci} Delivery {dn}의 조직(실적 파일 매칭 실패)")
                    else:
                        org_delivery_pairs.append((o, dn))
            elif len(dns) == 1:
                dn = dns[0]
                org = resolve_ship_from_org(text_org, dn)
                if text_org in TEXT_AMBIGUOUS_ORGS and org != text_org:
                    log(f"[FBC/FBS 확정] {label_ci}: 텍스트={text_org} -> 실적파일 대조 결과={org}")
                if org is not None:
                    org_delivery_pairs.append((org, dn))
                elif len(per_ci) == 1:
                    # 2026-07-20: DHL로 오는 일본/중국/홍콩발 재고 재배치 건도
                    # FedEx와 마찬가지로 Ship From이 구조적으로 확정 불가능하다
                    # (SHIP_FROM_ORG_MAP/실적파일 둘 다 매칭 대상이 아님) -
                    # SharePoint 대조로 바로 넘어간다. C.I가 여러 장인 결합
                    # 건에서는 이 판별을 하지 않는다(재배치는 항상 단일 C.I임).
                    way = detect_way_rebalance(driver, m["entry_id"], label, dn)
                    if way == "ERROR":
                        return None
                    if way:
                        return {
                            "kind": "way_rebalance", "format": "dhl",
                            "entry_id": m["entry_id"], "label": label,
                            "state_key": m["state_key"],
                            "org_delivery_pairs": [("WAY", way["receive_delivery_no"])],
                            "way_address_lines": way["address_lines"],
                            "way_from_org": way["from_org"],
                            "way_orig_delivery_no": dn,
                            "way_to_no": way.get("to_no"),
                            "way_receive_to_no": way.get("receive_to_no"),
                        }
                    # way is None(예외 없이) -> SharePoint에 없거나 From이
                    # CHP/JPP/ILH가 아님 -> WAY 재배치 건이 아닌 것으로 보고 계속 진행
                    missing.append("Ship From 조직코드")
                else:
                    missing.append(f"{label_ci}(Delivery {dn})의 Ship From 조직코드 확정 실패")
            elif ci_paths:
                # C.I가 여러 장인데 이 파일만 Delivery Number 추출에 실패한 경우
                # (OCR 실패 등) - 전체를 뭉뚱그린 상단 체크(any())로는 안 걸리므로
                # 여기서 개별적으로 놓치지 않게 명시한다.
                missing.append(f"{label_ci}: Delivery Number 추출 실패")
    except DeclarationFileLocked as e:
        # 2026-07-23 실측(DHL 1696566900): 실적 파일이 Excel로 열려 있어 일시적으로
        # 못 읽는 것뿐인데 "Ship From 확정 불가"로 오판해 사람 확인 알림을 보내면
        # 안 된다. 알림/상태 저장 없이 이번 회차만 조용히 넘기고 다음 스케줄에서
        # 재시도한다(파일이 닫히면 자연히 풀림).
        log(f"[대기] {e} -> {label} 이번 회차 스킵(다음 주기에 재시도)")
        return None

    if missing:
        log(f"[경고] 필요한 정보를 다 못 뽑음 ({label}) -> 사람 확인 필요, 스킵")
        send_alert(
            f"[DHL C.I 확인 필요] {label}",
            f"자동으로 정보 추출이 부족하여 확인이 필요합니다.\n"
            f"SO Number: {[e['fields']['so_no'] for e in per_ci]}\n"
            f"Ship From(CI): {[e['fields']['ship_from_org'] for e in per_ci]}\n"
            f"Delivery: {[e['delivery_numbers'] for e in per_ci]}\nTotal(waybill): {total}\n"
            f"C.I 파일: {[os.path.basename(p) for p in ci_paths]}\n\n누락/실패 항목: " + ", ".join(missing),
            dedup_key=f"{m['entry_id']}:ci_missing",
            dedup_ttl_hours=float("inf"),  # 재발송(다른 entry_id) 오기 전까지 딱 한 번만
        )
        return None

    so_nos = [e["fields"]["so_no"] for e in per_ci]

    sample_confirm_pn = None
    for p in ci_paths:
        sample_confirm_pn = find_sample_confirm_part_number(texts.get(p, ""))
        if sample_confirm_pn:
            break
    if sample_confirm_pn:
        log(f"[시료확인서] {label}: 품목 {sample_confirm_pn} 포함 -> 회신에 시료확인서 첨부 예정")

    return {
        "kind": "standard", "format": "dhl",
        "entry_id": m["entry_id"], "label": label,
        "state_key": m["state_key"],
        "org_delivery_pairs": org_delivery_pairs,
        "doc_total": total,
        "state_extra": {"so_no": so_nos[0] if len(so_nos) == 1 else so_nos, "total": total},
        "sample_confirm_pn": sample_confirm_pn,
    }


# ==============================================================
# main
# ==============================================================
def main():
    """2026-08-03 사용자 요청: 메일을 하나씩 "추출 -> 오라클 제출 -> 완료대기 ->
    다음 메일" 순서로 처리하면, 앞선 건이 Blocked로 오래 걸릴 때(2시간~8시간까지도
    걸린 사례 있음) 뒤에 있는 멀쩡한 건들까지 덩달아 밀리는 문제가 있었다. 아래
    4단계로 재구성한다:
      A) 새 메일 전부 OCR 추출(+ WAY 재배치 판별) - 오라클 제출은 아직 안 함
      B) 추출 성공한 건들의 오라클 리포트 제출을 순차로 다 해둠(완료 대기 없음)
      C) 제출해둔 것들을 라운드로빈으로 돌며 완료 확인 - Succeeded 되는 대로
         그 자리에서 바로 가격대조/답장까지 마무리
      D) 시간 예산(약 15분, 20분 스케줄 주기 안쪽) 초과 시 남은 건은 Process ID를
         저장해둔 채로 종료 -> 다음 스케줄 실행이 이어서 확인(기존과 동일한 특성).

    2026-08-03(2차) 사용자 요청: 오라클 로그인 확인/복구(SSO 재로그인, 실패 시
    Edge 강제 재시작까지)는 원래 Phase A보다 앞서 무조건 수행했는데, 이러면 OCR
    추출 정보 부족 등으로 "사람 확인 필요" 알림만 내고 오라클 제출 자체가 필요
    없는 건도 매 스케줄 주기(20분)마다 이 무거운 로그인 복구를 반복하게 된다
    (실측: 정보 부족 알림이 이미 나간 AWB 2건이 state에 안 남아 계속 "신규"로
    잡히면서, 매번 SSO 재로그인 시도 -> 실패 -> Edge 프로세스 강제종료 -> 재시작을
    거친 뒤에야 "오라클 제출할 건 없음"으로 끝났음). Phase A(추출)를 먼저 마치고
    실제로 오라클에 제출할 case가 하나라도 나온 뒤에만 로그인 확인/복구를
    수행하도록 순서를 바꾼다. Phase A 중 WAY 재배치 판별(SharePoint 조회)은
    오라클 로그인이 필요 없으므로 가벼운 탭(_open_plain_tab)만 열어서 쓴다."""
    log("===== icbl_ci_watcher 시작 =====")
    state = load_state()
    processed = set(state.keys())

    try:
        new_mails = find_new_customs_mails(processed)
    except Exception as e:
        log(f"[에러] 메일 검색 실패: {exc_detail(e)}")
        return

    if not new_mails:
        log("신규 통관 메일 없음. 종료.")
        return

    # 2026-08-03 사용자 지적: "정보 부족 -> 사람 확인 필요" 알림이 이미 나간 건
    # (entry_id 기준, ci_missing 알림은 dedup_ttl_hours=inf라 재알림도 안 나감)은
    # state에는 저장이 안 되므로(재발송 시 재시도하기 위해 의도적으로 안 남김)
    # 매 스케줄 주기(20분)마다 계속 "신규"로 잡혀 Phase A가 Edge를 켜고 똑같은
    # 추출을 반복해왔다(실측: AWB 874968887443/875064614942가 11:05부터 계속
    # 재시도됨). 재발송은 어차피 다른 entry_id로 오므로, 이미 알림 보낸 entry_id는
    # 재발송 전까지 Phase A 자체를 건너뛰어 불필요한 Edge 실행을 막는다.
    alerted = load_alerted_state()
    already_alerted_entry_ids = {
        k[: -len(":ci_missing")] for k in alerted if k.endswith(":ci_missing")
    }
    if already_alerted_entry_ids:
        before = len(new_mails)
        new_mails = [m for m in new_mails if m["entry_id"] not in already_alerted_entry_ids]
        skipped = before - len(new_mails)
        if skipped:
            log(f"[정보] 이미 '정보 부족' 알림 보낸 건 {skipped}개는 재발송 전까지 재시도 안 함 (Edge 안 켬)")

    if not new_mails:
        log("===== icbl_ci_watcher 종료 (신규는 정보부족 알림 처리된 건뿐, 오라클 안 켬) =====\n")
        return

    # 2026-09-18: 공유 브라우저 락은 같은 날 도입 직후 stale 판정 구멍으로
    # 바로 실전 충돌을 냈다 - 대신 이 파일 자신을 포함한 7개 스크립트를 완전히
    # 분리된 Edge 프로세스/프로필/포트로 바꿔서(EDGE_OWNER_CONFIGS 참고) 겹칠
    # 일 자체를 없앴다. icbl_ci_watcher는 원래 쓰던 포트 9333/프로필을 그대로
    # 전용으로 쓰므로 락이 더 이상 필요 없어 제거함.
    driver = None
    try:
        # ---- Phase A: 추출 + WAY 판별 (오라클 로그인 불필요) ----
        # 2026-07-14: find_new_customs_mails는 같은 AWB/DHL 번호로 메일이 여러 통
        # (예: 최초 요청 메일의 C.I가 페이지 누락 등으로 불완전해서 나중에 완전한
        # 내용으로 재발송된 경우) 있으면 전부 후보로 반환한다(최신 메일이 먼저 옴).
        # 최신순으로 훑다가 어떤 건이 case로 만들어지면 그 키를 가진 나머지(더
        # 오래된, 대개 불완전한) 후보는 건너뛴다.
        ensure_edge_running()
        driver = _open_plain_tab()

        # 2026-08-06 사용자 요청: 같은 AWB/DHL 번호가 다음 주기에 또 잡혔을 때
        # 첨부 저장 + OCR을 처음부터 다시 하지 않고 저장해둔 추출 결과를 재사용한다
        # (EXTRACT_CACHE_PATH 설명 참고). 메일이 재발송되면 entry_id가 달라지므로
        # 그때는 캐시를 무시하고 새로 추출한다.
        extract_cache = load_extract_cache(state)

        cases = []
        done_this_run = set()
        for m in new_mails:
            if m["state_key"] in done_this_run:
                log(f"[정보] {m['state_key']} 관련 다른 메일이 이번 회차에 이미 처리됨 "
                    f"-> 중복/구버전 메일 스킵: {m['subject']}")
                continue
            cached = extract_cache.get(m["state_key"])
            if (cached and cached.get("entry_id") == m["entry_id"]
                    and cached.get("script_mtime") == _script_mtime()):
                case = case_from_cache(cached)
                log(f"[캐시] {case['label']}: {cached['cached_at']}에 추출한 결과 재사용 "
                    f"(OCR 생략) - {', '.join(f'{o}:{d}' for o, d in case['org_delivery_pairs'])}")
            else:
                builder = build_fedex_case if m["format"] == "fedex" else build_dhl_case
                case = builder(driver, m, state)
                if case:
                    extract_cache[m["state_key"]] = case_to_cache(case)
                    save_extract_cache(extract_cache)
            if case:
                cases.append(case)
                done_this_run.add(m["state_key"])

        if not cases:
            log("===== icbl_ci_watcher 종료 (오라클 제출할 건 없음) =====\n")
            return

        # ---- Phase A-2: 실적 파일 등재 확인 (2026-08-20 안전장치) ----
        # 오라클 로그인/제출보다 앞에 두는 이유: 미등재 건은 어차피 회신을
        # 안 하므로, 오라클 리포트를 뽑는 작업(제출 + 최대 15분 폴링)을 낭비할
        # 필요가 없다. 여기서 걸러진 건은 state에 안 남으니 다음 회차에 재시도된다.
        cases = screen_declaration_registered(cases)
        if not cases:
            log("===== icbl_ci_watcher 종료 (실적 파일 미등재로 전부 보류, 오라클 안 켬) =====\n")
            return

        # ---- 오라클 로그인 확인/복구 (제출할 case가 있을 때만) ----
        driver.get(ORACLE_HOME_URL)
        time.sleep(2)
        # 2026-08-06(2차): 복구 순서를 recover_oracle_login()의 사다리로 통일했다
        # (SSO -> URL 재진입 -> Edge 재시작 -> 실패). 예전에는 SSO가 실패하면
        # 곧바로 Edge를 강제 재시작했는데, 실측 결과 재시작은 콜드 부팅이라
        # 로그인 페이지 렌더를 더 느리게 만들어 원인을 악화시키는 쪽이었고,
        # 반대로 URL 재진입만으로 풀리는 경우가 확인됐다 - 싼 수단을 앞에 둔다.
        # 알림/종료 처리는 예전과 완전히 동일하다.
        ok, driver = recover_oracle_login(driver, log)
        if not ok:
            # 2026-08-03: 예전엔 메일마다 각자 로그인 체크를 해서 로그인이
            # 끊기면 메일 수만큼 똑같은 알림이 반복됐다. 이제 드라이버를
            # 이번 실행 전체에서 하나만 열어 쓰므로 여기서 한 번만 확인하고,
            # 끊겨 있으면 이번 실행 전체를 알림 한 번으로 종료한다(메일들은
            # state에 안 남으므로 다음 스케줄 실행이 처음부터 재시도).
            log("[경고] 자동 복구 실패 -> 사람이 재로그인 필요, 이번 회차 전체 스킵")
            send_alert(
                "[오라클 재로그인 필요] 전체",
                "오라클 Fusion 세션이 끊겨서 이번 회차 자동 처리를 못했습니다. Edge에서 한 번 로그인해주세요.",
                dedup_key="oracle_login_global",
            )
            return

        # ---- Phase B: 오라클 제출(순차, 완료 대기 없음) ----
        for case in cases:
            case["process_ids"] = {}
            case["results"] = {}
            case["submit_error"] = None
            for pair in case["org_delivery_pairs"]:
                try:
                    # 화면 진입 실패 같은 일시적 오류면 같은 실행 안에서 재시도
                    # (제출 결과물은 리포트라 중복돼도 업무상 부작용 없음, 2026-08-05)
                    pid = run_with_oracle_retry(
                        f"{case['label']} 리포트 제출(org={pair[0]}, delivery={pair[1]})",
                        lambda p=pair: submit_oracle_ci_report(driver, *p),
                    )
                    case["process_ids"][pair] = pid
                    log(f"[제출] {case['label']}: org={pair[0]} delivery={pair[1]} -> Process ID {pid}")
                except Exception as e:
                    log(f"[에러] 오라클 제출 실패 ({case['label']}, org={pair[0]}, delivery={pair[1]}): "
                        f"{e}\n{traceback.format_exc()}")
                    case["submit_error"] = e
                    break
            if case["submit_error"] is not None:
                send_alert(
                    f"[오라클 조회 실패] {case['label']}",
                    f"오라클 자동 제출 중 에러가 발생했습니다: {case['submit_error']}\n수동으로 확인해주세요.",
                    dedup_key=f"{case['entry_id']}:oracle_query_fail",
                )

        # ---- Phase C: 라운드로빈 완료 확인 ----
        # 2026-07-13 기존 방침 계승: 한 번의 실행이 작업스케줄러 재실행 주기(20분)를
        # 넘기지 않도록 약 15분 예산 안에서 끊는다 - 넘는 건 다음 스케줄 실행이
        # 저장된 Process ID로 이어서 확인.
        budget_seconds = 15 * 60
        deadline = time.time() + budget_seconds
        pending = [c for c in cases if c["submit_error"] is None]

        while pending:
            still_pending = []
            for case in pending:
                remaining = [p for p in case["org_delivery_pairs"] if p not in case["results"]]
                had_error = False
                for pair in remaining:
                    try:
                        # 상태 확인은 읽기 전용이라 재시도해도 안전(2026-08-05).
                        # OracleStillProcessing은 "아직 처리 중"이라는 정상 신호라
                        # 재시도 대상에서 제외한다.
                        r = run_with_oracle_retry(
                            f"{case['label']} 상태확인(org={pair[0]}, delivery={pair[1]})",
                            lambda p=pair: poll_oracle_ci_report(
                                driver, p[0], p[1], case["process_ids"][p]),
                            no_retry_exceptions=(OracleStillProcessing,),
                        )
                    except Exception as e:
                        log(f"[에러] 오라클 상태 확인 실패 ({case['label']}, org={pair[0]}, "
                            f"delivery={pair[1]}): {e}\n{traceback.format_exc()}")
                        send_alert(
                            f"[오라클 조회 실패] {case['label']}",
                            f"오라클 자동 조회 중 에러가 발생했습니다: {e}\n수동으로 확인해주세요.",
                            dedup_key=f"{case['entry_id']}:oracle_query_fail",
                        )
                        had_error = True
                        break
                    if r is not None:
                        case["results"][pair] = r
                if had_error:
                    continue  # 알림 이미 보냄 -> 이번 회차는 여기서 포기(다음 스케줄에서 재시도)
                if len(case["results"]) == len(case["org_delivery_pairs"]):
                    try:
                        if case["kind"] == "way_rebalance":
                            finalize_way_case(case, state)
                        else:
                            finalize_standard_case(driver, case, state)
                    except Exception as e:
                        # 2026-07-10: 메시지만 남기면 Selenium 예외처럼 우리 코드
                        # 어느 줄에서 터졌는지 안 보여서(msedgedriver 내부 스택만
                        # 남음), 파이썬 traceback을 같이 남겨 다음에 재현 없이도
                        # 원인 줄을 바로 찾을 수 있게 함.
                        log(f"[에러] 오라클 조회/답장 실패 ({case['label']}): {e}\n{traceback.format_exc()}")
                        send_alert(
                            f"[오라클 조회 실패] {case['label']}",
                            f"오라클 자동 조회 중 에러가 발생했습니다: {e}\n수동으로 확인해주세요.",
                            dedup_key=f"{case['entry_id']}:oracle_query_fail",
                        )
                else:
                    still_pending.append(case)

            pending = still_pending
            if not pending:
                break
            if time.time() >= deadline:
                break
            time.sleep(20)

        for case in pending:
            log(f"[대기] {case['label']}: 이번 실행 시간 예산(약 {budget_seconds // 60}분) 내 완료 못함 "
                f"(Process ID는 저장되어 있으니 다음 스케줄 실행에서 이어서 확인)")

    finally:
        close_driver(driver)

    log("===== icbl_ci_watcher 종료 =====\n")


def _log_republish_diag(driver, attempt: int) -> None:
    """Republish 클릭 후 리포트 뷰어 팝업이 안 열렸을 때, 원인 판별에 필요한
    정보를 로그와 스크린샷으로 남긴다. 네이티브 클릭이 씹히는 경우는 예외가
    안 나기 때문에, 화면이 그대로인지 / 팝업이 차단됐는지 / 같은 탭에서 열렸는지를
    사후에 구분할 방법이 이것뿐이다(2026-08-12 추가)."""
    try:
        cur = driver.current_window_handle
        infos = []
        for h in driver.window_handles:
            try:
                driver.switch_to.window(h)
                infos.append(f"{'*' if h == cur else ''}{driver.title!r} <{driver.current_url[:120]}>")
            except Exception as e:
                infos.append(f"(조회실패 {type(e).__name__})")
        driver.switch_to.window(cur)
        log(f"  [진단] Republish {attempt}차 실패 - 열려있는 창 {len(infos)}개: " + " | ".join(infos))
    except Exception as e:
        log(f"  [진단] Republish {attempt}차 실패 - 창 목록 조회 실패: {type(e).__name__}: {e}")

    try:
        diag_path = os.path.join(
            ROOT, f"_diag_republish_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{attempt}.png")
        driver.save_screenshot(diag_path)
        log(f"  [진단] 스크린샷: {diag_path}")
    except Exception as e:
        log(f"  [진단] 스크린샷 실패: {type(e).__name__}: {e}")


def _republish_and_export_pdf(driver) -> str:
    """Republish -> 톱니바퀴 -> Export -> PDF. run_oracle_ci_report가 총액을
    뽑기 위해 매번 호출하고, 그 결과 PDF는 불일치 시 답장 첨부로도 재사용된다.
    2026-07-08: republish_img.click()은 반드시 진짜 Selenium 클릭이어야 함 —
    execute_script로 흉내낸 클릭은 브라우저가 신뢰된 사용자 제스처로 안 봐서
    새 창(window.open) 팝업이 차단됨(실측 확인).

    2026-08-05 실측(Rebalance TO 7866440 케이스, 여러 번 실패 후 원인 파악):
    이 함수를 반복 호출/재시도하는 동안(특히 수동 디버깅 중) 이전 호출에서 열린
    "Commercial Invoice Report" 리포트 뷰어 팝업이 안 닫힌 채로 남아있으면, 이번
    호출이 새로 여는 팝업을 `before/after window_handles diff`로 잡을 때 어떤
    창이 "새 창"인지 헷갈려서(또는 stale 팝업 쪽을 잘못 잡아서) 이후 gear/Export
    단계가 계속 실패하는 것으로 보임(재현 확인: 남아있는 팝업들을 전부 닫고
    나니 gear->hover Export->PDF가 즉시 정상 동작함). 그래서 시작 시 이 리포트
    타이틀의 잔여 팝업을 먼저 정리한다."""
    from selenium.webdriver.common.by import By

    main_handle = driver.current_window_handle

    # 2026-08-05: 잔여 리포트 뷰어 팝업 정리(위 실측 참고) - 메인 창/현재 창은
    # 절대 건드리지 않고, "Commercial Invoice Report"나 "Loading..." 타이틀을
    # 가진 팝업만 골라서 닫는다.
    for h in list(driver.window_handles):
        if h == main_handle:
            continue
        try:
            driver.switch_to.window(h)
            title = driver.title or ""
            if "Commercial Invoice Report" in title or title == "Loading...":
                driver.close()
        except Exception:
            pass
    driver.switch_to.window(main_handle)

    driver.switch_to.default_content()
    iframe1 = driver.find_elements(By.TAG_NAME, "iframe")[1]
    driver.switch_to.frame(iframe1)

    republish_img = driver.execute_script("""
        var imgs = document.querySelectorAll("img");
        for (var i=0;i<imgs.length;i++) {
            if ((imgs[i].title||'').indexOf('Republish') >= 0) return imgs[i];
        }
        return null;
    """)
    if not republish_img:
        raise RuntimeError("Republish 아이콘을 못 찾음")

    before = set(driver.window_handles)

    # 2026-08-12: 원래는 클릭 1회 + 6초(20x0.3)만 기다리고 포기했다. DHL 4132340284
    # (대형 리포트, 제출 후 Succeeded까지 3시간 걸린 건)이 이 지점에서 연속 실패해서
    # 클릭 3회 x 20초 대기로 넓힌다 - '뷰어가 느리게 뜸'과 '네이티브 클릭이 조용히
    # 씹힘'(다른 화면에서 실측된 적 있음) 둘 다를 커버하기 위함. 여기 클릭은 반드시
    # 네이티브여야 한다(JS 클릭은 신뢰된 사용자 제스처가 아니라 window.open이 팝업
    # 차단됨 - 함수 docstring 참고). 실패할 때마다 화면/창 목록을 진단으로 남긴다.
    new_handle = None
    for attempt in range(1, 4):
        try:
            republish_img.click()
        except Exception as e:
            log(f"  [진단] Republish 클릭 {attempt}차 예외: {type(e).__name__}: {e}")
        wait_deadline = time.time() + 20
        while time.time() < wait_deadline:
            time.sleep(0.3)
            diff = set(driver.window_handles) - before
            if diff:
                new_handle = list(diff)[0]
                break
        if new_handle:
            if attempt > 1:
                log(f"  [정보] Republish 클릭 {attempt}차 시도에서 리포트 뷰어가 열림")
            break

        _log_republish_diag(driver, attempt)

        # 재클릭 전에 아이콘 참조를 다시 잡는다(화면이 다시 그려졌으면 기존 참조가
        # stale이라 클릭이 조용히 무시될 수 있다). 재조회 실패 시 기존 참조 유지.
        try:
            driver.switch_to.default_content()
            frames = driver.find_elements(By.TAG_NAME, "iframe")
            if len(frames) > 1:
                driver.switch_to.frame(frames[1])
                again = driver.execute_script("""
                    var imgs = document.querySelectorAll("img");
                    for (var i=0;i<imgs.length;i++) {
                        if ((imgs[i].title||'').indexOf('Republish') >= 0) return imgs[i];
                    }
                    return null;
                """)
                if again:
                    republish_img = again
        except Exception:
            pass
    if not new_handle:
        raise RuntimeError("리포트 뷰어 새 탭이 안 열림")

    try:
        driver.switch_to.window(new_handle)
        # 2026-08-06 실측(DHL 1670899683, _diag_hover_Export_20260806_110846.png):
        # 고정 2초만 기다리고 gear를 누르면, 리포트 본문이 아직 비어 있는(렌더링 중)
        # 상태라 gear 메뉴가 열리지 않고 "Export 메뉴 항목을 못 찾음"으로 실패한다.
        # 뷰어 로딩이 끝나고 gear가 실제로 잡힐 때까지 최대 30초 기다린다.
        ready_deadline = time.time() + 30
        while time.time() < ready_deadline:
            try:
                if (driver.execute_script("return document.readyState") == "complete"
                        and _find_gear_icon(driver) is not None):
                    break
            except Exception:
                pass
            time.sleep(0.5)
        time.sleep(1)

        # gear 아이콘 클릭. 2026-07-08: 이 아이콘은 title/className에 'preferences'나
        # 'gear'가 없어서(둘 다 빈 값) 원래 검색 조건이 애초에 매칭 불가능했음
        # (실측 확인 - 실제로는 title도 class도 없는 <img>). 이미지 파일명이
        # "popupmenu_ena.png"인 것으로 식별한다.
        gear = _find_gear_icon(driver)
        if not gear:
            raise RuntimeError("gear 아이콘을 못 찾음")
        # 2026-08-07: 여기만 네이티브 클릭으로 남아 있었다. 이 클릭이 씹히면 메뉴가
        # 안 열리고, 아래 40회 재시도가 전부 "Export 메뉴 항목을 못 찾음(호버 대상)"
        # 으로 소진된다(11:20 회차 실패가 이것). 측정해보니 팝업은 0.6초 만에 뜨고
        # gear도 그때 이미 잡히며, 리포트 본문이 비어 있는 것은 성공 회차에서도
        # 마찬가지였다(inner_nodes 0~16) - 즉 '렌더링 대기 부족'이 아니라 클릭이
        # 문제였다. 이 메뉴는 새 창(window.open)이 아니라 ADF 팝업 메뉴라 JS 클릭이
        # 안전하다(_js_click_text 설명의 예외 조건에 해당하지 않음).
        driver.execute_script("arguments[0].click();", gear)
        time.sleep(1)

        # 2026-07-08: 이 팝업 메뉴 항목에 _click_text(XPath text() 검색)를 쓰면
        # 왜인지 Selenium의 is_displayed() 내부에서 "Cannot convert undefined or
        # null to object" JS 에러가 매번 재현됨(실측 확인, 원인 불명 - 아마 팝업
        # 메뉴의 DOM 구조가 XPath text() 매칭과 안 맞는 케이스가 섞여 있는 듯).
        # 메뉴 항목의 class(itemTxt)로 직접 찾아 native click하는 방식으로 우회.
        # 2026-07-10: 메뉴가 열리자마자 다시 닫히는 듯한 타이밍 이슈가 실측되어
        # (스크린샷으로 확인: 재시도 다 실패한 뒤 봐도 메뉴가 안 열린 상태),
        # Export 항목을 못 찾을 때마다 gear를 다시 클릭해서 메뉴를 재오픈한다.
        # 2026-08-06: 예전엔 항목을 못 찾을 때마다 gear를 무조건 다시 클릭했는데,
        # gear 클릭은 토글이라 "메뉴는 열려 있는데 항목 탐색만 실패한" 상황에서
        # 오히려 메뉴를 닫아버린다(열림/닫힘이 번갈아 반복). 예전에 관찰된
        # "메뉴가 열리자마자 다시 닫히는 듯한" 증상도 이 자기유발 토글이었을
        # 가능성이 높다 - 메뉴가 닫혀 있을 때만 다시 연다.
        def _reopen_gear_menu():
            if _menu_items_visible(driver):
                return
            g = _find_gear_icon(driver)
            if g:
                # 2026-08-07: 위 gear 클릭과 같은 이유로 JS 클릭(네이티브는 조용히 씹힘)
                driver.execute_script("arguments[0].click();", g)

        # 2026-07-13 실측: "Export"는 클릭 대상이 아니라 PDF/HTML/RTF/... 하위
        # 목록을 펼치는 호버 트리거였음(:hover 기반이라 클릭해도 하위 목록이 안 뜸).
        # 2026-08-06: 재시도 창이 10회x0.3초 = 약 3초뿐이라, 뷰어가 느리게 뜨는
        # 회차에는 메뉴가 준비되기 전에 시도를 다 소진하고 실패했다(실측). 약 30초로
        # 넓힌다 - 성공하면 즉시 반환하므로 정상 케이스의 소요시간은 그대로다.
        _hover_menu_item_with_retry(driver, "Export", attempts=40, delay=0.7,
                                    reopen_fn=_reopen_gear_menu)
        time.sleep(0.5)

        downloads_dir = os.path.expanduser("~/Downloads")
        before_files = set(os.listdir(downloads_dir))

        # 2026-08-19 실측(Rebalance TO 7874410/7872959): "PDF Export 다운로드 확인
        # 안됨"으로 **9번 연속** 실패했는데, Downloads 폴더를 확인해보니 그 시각에
        # 만들어진 파일이 아예 없었다(.crdownload 임시파일조차 없음). 즉 다운로드가
        # 늦은 게 아니라 **시작조차 안 됐다** = PDF 메뉴 클릭이 씹힌 것이다.
        # (같은 회차에서 바로 앞 TO 7874424는 성공했다 - 타이밍/포커스에 따라
        #  되기도 하고 안 되기도 하는, 이 코드베이스에 이미 여러 번 기록된 증상)
        #
        # 원인은 _click_menu_item_with_retry가 쓰는 **네이티브 el.click()**이다.
        # 이 Edge에서 네이티브 클릭이 조용히 씹히는 건 실측으로 확인돼 있고, 바로 위
        # gear 아이콘은 그래서 이미 JS 클릭으로 바꿨는데(2026-08-07) 이 메뉴 항목
        # 클릭만 네이티브로 남아 있었다. 씹혀도 예외가 안 나므로 호출부는 "클릭
        # 성공"으로 알고 넘어가고, 파일만 안 생긴 채 20초를 기다리다 실패한다.
        #
        # 그래서 (1) JS 클릭으로 바꾸고, (2) **클릭이 먹었는지를 예외가 아니라
        # '파일이 생겼는가'라는 결과로 확인**한다. 안 생겼으면 메뉴를 다시 열어
        # 몇 번 더 눌러본다(navigate_to_create_pick_wave가 Tasks 아이콘으로 화면
        # 전환을 확인하는 것과 같은 방식).
        def _new_pdf_files():
            return [f for f in (set(os.listdir(downloads_dir)) - before_files)
                    if f.lower().endswith(".pdf")]

        def _click_pdf_menu_item():
            """PDF 항목을 JS로 클릭한다(네이티브 클릭은 조용히 씹힌다)."""
            for _ in range(20):
                el = _find_menu_item(driver, "PDF")
                if el is not None:
                    driver.execute_script("arguments[0].click();", el)
                    return True
                _reopen_gear_menu()
                try:
                    _hover_menu_item_with_retry(driver, "Export", attempts=8, delay=0.5,
                                                reopen_fn=_reopen_gear_menu)
                except Exception:
                    pass
                time.sleep(0.5)
            return False

        pdf_files = []
        for click_attempt in range(1, PDF_EXPORT_CLICK_ATTEMPTS + 1):
            if not _click_pdf_menu_item():
                log(f"  [Export] PDF 메뉴 항목을 못 찾음(클릭 {click_attempt}회차)")
            # 2026-07-10: 고정 3초 대기 후 한 번만 확인하던 방식이, 리포트가 크거나
            # 다운로드가 평소보다 느린 경우 시간이 부족해서 실패하는 게 실측됨
            # (DHL 4781407805 건) -> 폴링하며 확인.
            deadline = time.time() + PDF_EXPORT_WAIT_SEC
            while time.time() < deadline:
                pdf_files = _new_pdf_files()
                if pdf_files:
                    break
                time.sleep(1)
            if pdf_files:
                if click_attempt > 1:
                    log(f"  [Export] PDF 다운로드 확인({click_attempt}회차 클릭에서 성공)")
                break
            if click_attempt < PDF_EXPORT_CLICK_ATTEMPTS:
                log(f"  [Export] {PDF_EXPORT_WAIT_SEC}초 안에 PDF가 안 받아짐"
                    f"(클릭 {click_attempt}/{PDF_EXPORT_CLICK_ATTEMPTS}회차) "
                    f"- 클릭이 씹힌 것으로 보고 메뉴를 다시 열어 재시도")
                _reopen_gear_menu()
                try:
                    _hover_menu_item_with_retry(driver, "Export", attempts=20, delay=0.7,
                                                reopen_fn=_reopen_gear_menu)
                except Exception as e:
                    log(f"  [Export] Export 하위메뉴 재오픈 실패(무시하고 재시도): {exc_detail(e)}")
                time.sleep(0.5)
        if not pdf_files:
            try:
                shot = os.path.join(
                    PDF_SAVE_DIR,
                    f"_diag_export_fail_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png")
                driver.save_screenshot(shot)
                log(f"  [Export] 실패 시점 화면 저장: {shot}")
            except Exception:
                pass
            raise RuntimeError(
                f"PDF Export 다운로드 확인 안됨"
                f"(클릭 {PDF_EXPORT_CLICK_ATTEMPTS}회 x 대기 {PDF_EXPORT_WAIT_SEC}초)")

        src = os.path.join(downloads_dir, pdf_files[0])
        dst = os.path.join(PDF_SAVE_DIR, "Oracle_" + pdf_files[0])
        shutil.copy(src, dst)
        return dst
    finally:
        # 2026-07-08: 성공/실패 관계없이 팝업을 닫고 메인 창으로 돌아가야 다음
        # 실행이 이 팝업을 메인 창으로 잘못 잡는 사고를 막을 수 있음(실측 확인 -
        # 팝업이 계속 쌓이면서 좁은 창 크기 때문에 UI가 다르게 렌더링되어
        # 연쇄적으로 실패했었음).
        try:
            driver.switch_to.window(new_handle)
            driver.close()
        except Exception:
            pass
        try:
            driver.switch_to.window(main_handle)
        except Exception:
            pass


if __name__ == "__main__":
    main()
