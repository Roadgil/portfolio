# -*- coding: utf-8 -*-
"""
pick_release_watcher.py

Bohyun Kim(bohyunk@candelamedical.com)이 보내는 "DCD 출고 요청의 건" /
"소모품 출고 요청의 건" / "불량 및 프로모션..." / "프로모션 및 불량..." 메일
(받은편지함 > Operation > Bohyun Kim 폴더)을 감시해서 본문의 8자리 주문번호
(00으로 시작)를 뽑아 Oracle Fusion Inventory Management에서
Create Pick Wave -> Release Now를 자동 실행하고, 릴리즈가 성공한 건에 대해서만
"Release 완료됐습니다" 답장을 자동으로 발송한다(2026-07-15부터, 사용자 요청 -
그 전까지는 초안만 저장). 실패/확인 필요 건에 대한 알림은 여전히 사람(담당자)
앞으로 초안만 저장한다(자동발송 안 함).

- DCD: Release Rule = KRP_Pick_Release_FG 1회. 제목에 "출고 요청"이 없어도
  본문에 "케어봇"/"CareBot"이 있으면 DCD로 처리(2026-07-10 추가 - 원장님이
  케어봇 챗봇으로 직접 주문하면 보현 과장님이 제목을 매번 자유롭게 써서
  전달하므로 제목 패턴으로는 못 잡음, 전달 시 원본이 인용돼 본문에는
  항상 남음). 제목에 "DCD"/"소모품" 문자열이 아예 없어도(예: "모던 스탠다드
  4 박스 - 8월 4일 택배") 택배/퀵발송류 표현과 함께 "박스"라는 단위 표현이
  있으면 DCD로 처리(2026-08-04 추가, 사용자 확인 - "박스"는 보통 DCD 제품에
  쓰는 단위).
- 소모품: Release Rule = KRP_Pick_Release_SP 1회 먼저, 결과에 백오더가 있을
  때만 KRP_Pick_Release_FG를 추가로 한 번 더 실행(2026-08-04 변경 - 원래는
  FG+SP를 항상 순서대로 둘 다 무조건 실행했으나, "SP부터 하고 백오더 있으면
  FG도 돌려라"는 사용자 요청으로 DCD/이노메드와 같은 1차/2차 조건부 방식으로
  통일(순서만 반대) - `PRIMARY_SECONDARY_RULES` 참고). 제목에 "DCD"/"소모품"/
  "박스" 등 기존 신호가 전혀 없어도 택배/퀵발송류 표현만 있으면(예: "밴스의원
  용산 울템 1개 - 택배 8/4") 제품을 특정 못하는 것으로 보고 소모품으로 처리하는
  catch-all이 있음(2026-08-04 추가, 사용자 판단).
- 이노메드(외부 협력업체) 부품주문(2026-07-24 추가): 제목에 "이노메드"와
  "부품주문"이 같이 있고 택배/퀵발송 등 실제 출고 표현이 있을 때만 매칭
  (같은 제목 패턴이라도 "...Unused 요청"처럼 재고조정만 요청하는 건은
  택배 단어가 없어서 제외됨) - DCD와 동일하게 Release Rule = FG 1회만, FG
  결과에 백오더가 있을 때만 SP를 추가로 한 번 더 실행(둘 다 무조건 도는
  소모품 방식이 아님 - "backordered 안 나오면 그냥 성공으로 해달라"는 사용자
  요청 반영). 2026-07-24 INOMED_LOOKBACK_START_DATE 이전 백로그는 사용자가
  이미 수동 처리했으므로 그 이후 신규 수신분부터만 자동 처리.
- 불량/프로모션(제목에 "불량 및 프로모션" 또는 "프로모션 및 불량" 이 포함 - 보통
  "6월 19~6월 26일주 불량 및 프로모션 택배 발송 요청"처럼 날짜 뒤에 옴, 맨 앞은 아님):
  Release Rule = KRP_Pick_Release_FG 1회만. 이 카테고리는 메일 1건에 여러 병원
  (주문번호)이 묶여서 오므로(실측 최대 25건) 본문의 8자리 번호를 전부(findall)
  뽑아 각각 개별 릴리즈한다. 답장은 그 메일에 있던 전체 건이 다 성공했을 때
  단 한 번만 보낸다(부분완료 상태로 "완료" 답장이 나가면 안 되므로, 라인 0건도
  DCD/소모품과 달리 상태에 기록하지 않고 계속 재시도한다).
- FIBER 백오더(2026-08-19 추가): 제목에 "FIBER HOOK 백오더"가 들어간 메일
  (예: "Fw: FIBER HOOK 백오더 리스트 택배 수령 장소 확인 요청의 건 - 서초 및
  부산 택배"). Release Rule = KRP_Pick_Release_SP 1회, Order Type은 다른
  건과 같은 Sales order(사용자 지정: "release rule SP / sales order").
  이 카테고리는 본문에 8자리 주문번호가 아예 없다. 표의 **"오더번호2" 칸**
  6자리 앞에 "00"을 붙인 것이 sales order 번호다(232157 -> 00232157, 사용자
  확정). 바로 옆 "오더번호" 칸(589904 등)은 릴리즈 대상이 아니다 - 2026-08-19에
  이걸 잘못 써서 릴리즈를 시도한 적이 있으니 헷갈리지 말 것.
  게다가 윤길님 앞으로 온 요청 표에는 오더번호2 칸이 빠져 있고 아래 인용된
  원본 표에만 있어서, 두 표를 오더번호 값으로 맞춰 끌어와야 한다
  (extract_fiber_backorder_order_nos 참고 - 그래서 이 카테고리만 평문이 아니라
  HTML 본문의 표를 파싱한다). 불량/프로모션과 마찬가지로 메일 1건에 여러
  병원(실측 23건)이 표로 묶여 오므로 전부 뽑아 개별 릴리즈하고, 답장은 그 메일
  전체가 다 성공했을 때 한 번만 보낸다.
- 완료 답장 수신자: 카테고리 구분 없이 원본 메일의 To/CC를 따르지 않고
  To=bohyunk/haejoonk, CC=용마로지스 김기훈/유용호로 고정(PICK_RELEASE_REPLY_TO/CC,
  2026-07-09부터 전체 카테고리 공통 적용).
- 성공 판정: 확인 다이얼로그의
  "Number of shipment lines released to warehouse: N" 에서 합산 N > 0
- **완료(성공) 답장만 자동발송, 그 외 알림은 여전히 초안(2026-07-15부터):**
  `create_completion_reply`(릴리즈 성공 시 "Release 완료됐습니다" 답장)는
  `reply.Send()`로 실제 발송한다 - 사용자가 "무조건 성공한 것에 대해서만
  전송해달라"고 명시적으로 요청함. 반면 `send_alert`(재로그인 필요/확인 필요
  등 사람이 봐야 하는 알림)은 여전히 `mail.Save()`로 초안만 저장하고 본인
  앞으로 보냄(자동발송 안 함) - icbl_ci_watcher.py와 동일 원칙 유지. 2026-07-09
  확인: 예전 Save() 방식일 때 Sent Items에 뜬 항목은 사람이 드래프트를 열어서
  직접 수정/발송한 것이었음(자동발송 버그 아니었음) - 참고로 남겨둠.
- 오라클 세션 관리(Edge 디버그 포트 9333, 로그인 확인 등)는 icbl_ci_watcher.py의
  검증된 로직을 그대로 재사용한다(같은 브라우저 인스턴스를 공유).

주의:
- 이 스크립트는 실제 창고 출고 릴리즈를 트리거하는 진짜 트랜잭션이다.
  같은 주문번호를 중복 릴리즈하지 않도록 _processed_orders.json으로 추적한다.
  한 번 기록된 오더번호는(라인이 일부만 나가고 백오더가 남았어도) 원래는 다시
  릴리즈를 시도하지 않는다 - 재고가 나중에 들어와도 자동 재확인은 안 해서 사람이
  오라클에서 직접 확인/릴리즈해야 했다. 단, 2026-09-17부터 같은 오더번호가 언급된
  새 메일 제목에 "백오더"가 있으면 processed 판정을 무시하고 강제로 재릴리즈를
  시도하도록 예외를 뒀다(BACKORDER_ALERT_SUBJECT_KEYWORD 참고) - 재고가 있으면
  릴리즈되어 완료 답장까지 자동 발송, 없으면 여느 재고부족과 동일하게 조용히 끝남.
- 본문에 "윤길"이 없는 메일은 릴리즈 대상이 아니다(2026-08-10 추가) -
  보현 과장님이 이미 오라클에서 직접 release를 끝내고 용마(기훈님/용호님)에게
  발송만 요청하는 메일이라 뽑을 라인이 없다. RELEASE_REQUEST_NAME_TOKEN 참고.
- Order 입력 후 Customer가 자동으로 안 뜨는 경우가 있는데, 보통 ServiceMax ->
  오라클 주문 연동이 아직 안 끝난 것(연동 지연). 3분 대기 후 한 번 더 시도하고,
  그래도 안 뜨면 실패로 두어 다음 예약 실행(20분 뒤)에서 다시 시도하게 한다.
- LOOKBACK_START_DATE 이전 메일은 절대 건드리지 않는다(DCD/소모품, 그 전 것들은
  이미 수동으로 처리됨).
- DEFECT_PROMO_LOOKBACK_START_DATE 이전의 불량/프로모션 메일도 건드리지 않는다
  (2026-07-09 이 스크립트에 카테고리를 추가하기 전 백로그는 사용자가 이미 전부
  수동으로 release 완료함 - 그 이후 신규 수신분부터만 자동 처리).
- NEW_SUBJECT_RULES_LOOKBACK_START_DATE(2026-08-04) 이전 메일은 그날 새로
  추가된 제목 매칭 규칙 3개(박스->DCD, DCD+불량->DCD, 택배류 catch-all->소모품)
  대상이 아니다(사용자가 "한미인 불량 건은 이미 내가 처리했다"며 오늘 이후
  신규 수신분부터만 이 규칙들을 적용해달라고 요청 - 기존 "출고 요청"/DCD·소모품
  명시 키워드 매칭은 이 컷오프의 영향을 받지 않고 원래 LOOKBACK_START_DATE만
  따른다).
- 작업 스케줄러에 "Pick_Release_Watcher"(DCD/소모품용)와
  "Pick_Release_Watcher_불량프로모션"(불량/프로모션용) 두 태스크가 등록돼 있는데
  둘 다 같은 이 스크립트를 부른다(카테고리 구분은 스크립트 안에서 다 함).
  2026-07-10부터 둘 다 10:00~14:00(30분 간격) + 14:00~14:40(5분 간격) 트리거
  2개로 동일 - 같은 시각에 겹쳐 실행될 수 있으므로 파일 락으로 동시 실행을
  막는다(_acquire_singleton_lock).
"""

from __future__ import annotations

import json  # 2026-08-24: Edge 재시작 쿨다운 스탬프 읽기/쓰기용
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# icbl_ci_watcher.py의 검증된 오라클 세션 관리 로직 재사용(2026-09-18부터는
# Edge 인스턴스를 공유하지 않고 이 스크립트 전용 포트/프로필로 완전 분리 -
# set_edge_owner 호출 참고, edge-per-script-separation.md)
ICBL_DIR = (
    r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation"
    r"\10. 수입\인천관세법인 C.I 확인"
)
sys.path.insert(0, ICBL_DIR)
from icbl_ci_watcher import (  # noqa: E402
    ensure_edge_running,
    get_oracle_driver_isolated,
    close_driver,
    is_session_dead_error,
    atomic_write_json,
    read_json_state,
    exc_detail,
    sso_relogin,
    recover_oracle_login,
    wait_or_sleep,
    text_visible,
    element_present,
    oracle_is_logged_in,
    OracleLoginRequired,
    ORACLE_HOME_URL,
    _click_text,
    _js_click_text,
    tasks_panel_open,
    _wait_find,
    _force_restart_edge,
    set_edge_owner,
    _ensure_my_tab,
)

# 2026-09-18: 이 프로세스는 자기 전용 Edge(포트/프로필)를 쓴다 - import 직후
# 딱 한 번만 호출(이 파일 안에서 이후 ensure_edge_running() 등을 owner 인자
# 없이 그대로 불러도 전부 이 owner로 풀린다).
set_edge_owner("pick_release_watcher")

import time  # noqa: E402


# ==============================================================
# 경로/설정
# ==============================================================
ROOT = os.path.dirname(__file__)
LOG_PATH = os.path.join(ROOT, "pick_release_watcher.log")
STATE_PATH = os.path.join(ROOT, "_processed_orders.json")

OUTLOOK_PARENT_SUBFOLDER = "Operation"
OUTLOOK_SUBFOLDER = "Bohyun Kim"

ALERT_MAIL_TO = "yoongil.chae@candelamedical.com"

# 이 시각 이전 메일은 (이미 수동 처리되었거나 사용자가 완료 확인했으므로) 절대
# 자동 처리하지 않음. 2026-07-09: 00592082/00592081(7/8 메일)이 Customer
# 미표시로 반복 실패하다 알고보니 이미 다른 경로로 release 완료된 건이었음.
# 2026-07-10: 오늘 아침(08:54~09:01) 온 선출고 전산 처리 메일 배치가 전부
# Customer 미표시/네비게이션 오류로 실패 반복 - 사용자가 이미 직접 처리했다며
# 10:34(닥터스의원 광교, 00592512) 메일부터 자동 처리하도록 요청 -> 컷오프를
# 이 시각으로 올려 그 이전 잔여 메일을 더 이상 긁지 않게 함.
LOOKBACK_START_DATE = datetime(2026, 7, 10, 10, 34, 0)

# 불량/프로모션 카테고리는 2026-07-09 이 시점 이전 백로그를 사용자가 전부 수동으로
# release 완료함 - 그 이후 신규 수신분부터만 자동 처리 (중복 release 방지)
DEFECT_PROMO_LOOKBACK_START_DATE = datetime(2026, 7, 9, 10, 57, 0)

# 2026-07-24 사용자 요청으로 추가: 이노메드(외부 협력업체) 부품주문 건도 자동
# 처리. 처음엔 소모품처럼 FG+SP를 무조건 둘 다 실행하게 만들었으나, 곧이어
# "backordered 안 나오면 그냥 성공으로 해줘 굳이 돌릴 필요 없어"라고 정정 -
# DCD와 동일하게 FG만 먼저 돌리고 백오더가 감지될 때만 SP를 추가 실행하는
# 방식으로 바꿈(RELEASE_RULES는 FG 1개만, SP 추가 실행 조건에 "이노메드"를
# DCD와 함께 포함 - 아래 _process_single_order 참고). 이전 백로그(예: 6/23
# IHP26008)는 이미 수동 처리됐으므로 오늘부터만 자동 처리(사용자 확인:
# "오늘 온 것만 실행해").
INOMED_LOOKBACK_START_DATE = datetime(2026, 7, 24, 0, 0, 0)

# 2026-08-04 추가된 제목 매칭 규칙 3개(박스->DCD, DCD+불량->DCD, 택배류 표현만
# 있는 catch-all->소모품) 전용 컷오프. 사용자가 "한미인 불량 건은 이미 내가
# 처리했다"며, 오늘 새로 추가한 규칙들은 오늘 이전 백로그까지 소급해서 긁지
# 말고 오늘 이후 신규 수신분부터만 적용해달라고 요청 - 이 세 규칙으로 매칭된
# 경우에만(기존 "출고 요청"/DCD·소모품 명시 키워드 매칭은 영향 없음) 아래에서
# 이 시각 이전 메일을 건너뛴다(`find_new_order_mails`의 `matched_by_new_rule`
# 플래그 참고).
NEW_SUBJECT_RULES_LOOKBACK_START_DATE = datetime(2026, 8, 4, 0, 0, 0)

# 2026-09-18 발견: "Re: 소모품 구매의 건- 아티움 울템 9.18"(00603907, 서비스팀
# 정재필 과장이 원청으로 넣은 요청을 보현 과장님이 전달) - 제목에 "출고 요청"도
# 없고 택배/퀵발송/퀵/선출고/박스 같은 발송 단어도 없어서(본문에는 "택배 발송
# 부탁드립니다"가 있지만 제목만 봄) 기존 어떤 규칙에도 안 걸려 **경고 로그도 없이
# 완전히 조용히 스킵됐다(find_new_order_mails가 kind=None으로 continue)** -
# "8자리 주문번호 못 찾음" 경고조차 못 뜨는, 발견하기 가장 어려운 유형의 누락.
# 제목에 "구매의 건"이 있으면 "출고 요청"과 동일하게 취급(DCD/소모품 판정은
# 그대로). 신규 규칙이라 소급 적용하지 않고 오늘 이후 신규 수신분부터만 적용
# (matched_by_new_rule과 같은 원칙, 별도 플래그로 컷오프 분리).
PURCHASE_SUBJECT_RULE_START_DATE = datetime(2026, 9, 18, 0, 0, 0)

# 2026-08-10 사용자 확인: 보현 과장님이 용마(기훈님/용호님) 앞으로 바로 쓰는
# 출고 메일("기훈님 용호님, ... 택배 발송 부탁드립니다 / 00597481")은 **보현
# 과장님이 이미 오라클에서 직접 release를 끝낸 뒤** 창고에 발송만 요청하는 건이다 -
# 자동화가 이걸 또 release하려 하면 뽑을 라인이 없어 Customer가 영원히 안 뜨고
# (실측 2026-08-10: 00597444 / 00597463 / 00597481) 3분 대기 + "확인 필요" 초안만
# 반복 생성됐다. 판별 기준은 본문의 한글 "윤길" 유무 - 윤길님에게 릴리즈를
# 요청하는 메일은 "윤길님, 선출고 릴리즈 부탁드립니다" / "안녕하세요 윤길님" /
# "@채윤길님" 처럼 항상 이름이 들어간다(역검증: 지금까지 release 성공한 주문이
# 담긴 메일 109건 전부 "윤길" 포함, 위 실패 3건은 전부 미포함).
# 영문 표기(yoongil.chae@candelamedical.com)는 인용된 메일 헤더/서명에 딸려
# 들어와서 실패 3건에도 전부 있으므로 판별에 쓸 수 없다 - 한글 "윤길"만 본다.
RELEASE_REQUEST_NAME_TOKEN = "윤길"


def _body_before_quote(body: str) -> str:
    """인용된 이전 메일을 잘라내고 **이번에 새로 쓴 부분만** 돌려준다.

    2026-08-26 실증(00599914, "Re: DCD 출고 요청의 건 (크림의원 안양) - 퀵 2박스
    8월 26일"): 보현 과장님이 용마(기훈님/용호님)에게 2박스 **추가 발송**을 부탁한
    메일인데, 스레드에 윤길님이 전날 보낸 "Release 완료됐습니다" 답장이 인용문으로
    딸려와 본문 전체에는 '윤길'이 들어 있었다(윤길 위치 1007 > 인용 시작 618).
    그래서 아래 RELEASE_REQUEST_NAME_TOKEN 검사가 "윤길이 있으니 나에게 온 릴리즈
    요청"으로 오판해, **이미 release가 끝난 주문**을 붙잡고 Customer 미표시로
    실패시킨 뒤 확인 필요 알림까지 냈다. 같은 날 같은 성격의 00599924
    (모던스탠다드의원)는 인용문이 없어 정상 스킵됐다 - 인용문 유무로 결과가 갈렸다.

    Outlook이 붙이는 인용 헤더는 줄 맨 앞의 'From:'이다(이 스레드 전수 확인).
    한국어 로케일 발신자가 섞이면 '보낸 사람:'일 수 있는데, 그때 증상은
    "스킵돼야 할 메일이 또 처리됨"으로 똑같이 나타나므로 그 시점에 문구를 더한다.
    """
    m = re.search(r"(?m)^\s*From:", body)
    return body[:m.start()] if m else body

RELEASE_RULES = {
    "DCD": ["KRP_Pick_Release_FG"],
    "소모품": ["KRP_Pick_Release_SP"],
    "불량/프로모션": ["KRP_Pick_Release_FG"],
    "이노메드": ["KRP_Pick_Release_FG"],
    # 2026-08-19 사용자 지정: FIBER 백오더는 SP 룰 1회만(백오더 있을 때 FG를
    # 추가로 도는 조건부 대상 아님 - PRIMARY_SECONDARY_RULES에 넣지 않음).
    "FIBER백오더": ["KRP_Pick_Release_SP"],
}

# 2026-08-04 사용자 요청: 소모품은 원래 FG+SP를 무조건 둘 다 돌렸으나, "SP부터
# 하고 백오더 있으면 FG도 돌려라"로 정정 - DCD/이노메드(1차 룰 먼저, 백오더 있을
# 때만 2차 룰 추가)와 같은 조건부 방식으로 통일하되 소모품만 1차/2차 순서가
# 반대(SP가 1차, FG가 2차). {kind: (1차 룰, 백오더 감지 시 추가 실행할 2차 룰)}
PRIMARY_SECONDARY_RULES = {
    "DCD": ("KRP_Pick_Release_FG", "KRP_Pick_Release_SP"),
    "이노메드": ("KRP_Pick_Release_FG", "KRP_Pick_Release_SP"),
    "소모품": ("KRP_Pick_Release_SP", "KRP_Pick_Release_FG"),
}

DEFECT_PROMO_SUBJECT_KEYWORDS = ("불량 및 프로모션", "프로모션 및 불량")

# 2026-09-17 사용자 요청: 이미 처리완료로 기록된 오더번호라도, 그 오더번호가 언급된
# 새 메일 제목에 "백오더"가 들어 있으면(= 재고 부족으로 남은 라인을 나중에 다시
# 릴리즈해달라는 후속 메일로 추정) processed 판정을 무시하고 강제로 재릴리즈를
# 시도한다(00602410 엠레드 사례로 발견 - 원래는 한 번 기록되면 영영 다시 안 건드림).
# 재고가 아직 없으면 여느 재고부족 케이스처럼 Customer 미표시/0건으로 조용히
# 끝나고, 재고가 들어와 있으면 정상 릴리즈되어 기존과 동일한 완료 답장까지
# 자동 발송된다(별도 알림 경로 없음 - 사용자가 "초안 말고 그냥 릴리즈+답장"으로 확정).
BACKORDER_ALERT_SUBJECT_KEYWORD = "백오더"

# 2026-08-19 사용자 요청으로 추가한 FIBER 백오더 카테고리.
# 제목 예: "Fw: FIBER HOOK 백오더 리스트 택배 수령 장소 확인 요청의 건 - 서초 및
# 부산 택배" - 영문 부분만 대문자로 비교한다(한글 "백오더"는 upper()의 영향 없음).
FIBER_BACKORDER_SUBJECT_KEYWORD = "FIBER HOOK 백오더"

# 이 카테고리도 오늘(추가한 날) 이후 신규 수신분부터만 자동 처리한다.
# 기존 백로그 중 유일하게 남아 있는 8/5 원본 메일("...요청의 건 -8/5", 영업
# 담당자들에게 수령 장소를 묻는 메일)은 애초에 본문에 한글 "윤길"이 없어서
# RELEASE_REQUEST_NAME_TOKEN 규칙으로도 걸러지지만(실측 확인), 그것 하나에만
# 기대지 않고 다른 카테고리와 같은 방식으로 컷오프도 같이 둔다.
FIBER_BACKORDER_LOOKBACK_START_DATE = datetime(2026, 8, 19, 0, 0, 0)

# FIBER 백오더 메일 표의 컬럼 이름.
#
# 2026-08-19 사용자 확정: **릴리즈에 쓸 sales order 번호는 "오더번호2" 칸의
# 6자리 앞에 00을 붙인 것**이다(예: 232157 -> 00232157). 옆의 "오더번호"
# (589904 같은 5로 시작하는 6자리)는 릴리즈 대상이 아니다.
#
# 그런데 보현 과장님이 윤길님 앞으로 보내는 요청 표에는 이 오더번호2 칸이
# 빠져 있고(실측 2026-08-19 메일: 요청 표 7칸 = LN/담당자/거래처/상태/오더번호/
# 파트/수량), 오더번호2는 그 아래 인용된 8/5 원본 표(8칸)에만 있다.
# 그래서 요청 표의 각 행을 "오더번호" 값으로 인용부 표에서 찾아 같은 행의
# 오더번호2를 끌어와 쓴다(위치가 아니라 값으로 맞추므로 행 순서가 달라도 안전).
# 못 찾은 행은 릴리즈하지 않고 경고만 남긴다 - 잘못된 번호로 릴리즈를 시도하면
# 엉뚱한 주문의 재고가 나갈 수 있어서, 빠뜨리는 쪽이 낫다.
FIBER_COL_ORDER = "오더번호"
FIBER_COL_ORDER_SO = "오더번호2"

# 2026-07-13: 한 메일(특히 불량/프로모션 배치, 최대 25건)에 담긴 여러 주문을
# 순차 처리하면 시간이 오래 걸려 탭을 여러 개(주문별로 독립 탭) 동시에 열어
# 병렬 처리한다. 오라클이 같은 로그인 세션의 동시 요청을 문제없이 처리하는지
# 아직 실측 검증 전이라, 사용자와 상의해 작게(3개) 시작 - 문제없으면 나중에 올림.
# 2026-07-15: 3개로 처음 돌린 날 같은 실행에서 stale element reference 오류가
# 2건 발생(둘 다 자동 재시도로 해소되긴 함) - 동시 탭이 같은 오라클 로그인
# 세션에 부담을 주는 것으로 의심돼 사용자 요청으로 2개로 낮춤.
MAX_PARALLEL_ORDERS = 2

LOCK_FILE_PATH = os.path.join(ROOT, "_watcher.lock")


def _acquire_singleton_lock():
    """이미 다른 인스턴스(다른 스케줄 트리거 포함)가 돌고 있으면 None 반환."""
    import msvcrt
    f = open(LOCK_FILE_PATH, "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


def _release_singleton_lock(f):
    import msvcrt
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        f.close()
    except Exception as e:
        # 2026-08-06: 예전에는 조용히 넘어갔다. 락이 안 풀리면 다음 회차부터
        # 계속 "이미 다른 인스턴스가 실행 중"으로 즉시 종료돼 자동화가 멈추는데,
        # 그 원인이 로그에 전혀 안 남아서 추적이 불가능했다. 동작(무시하고 진행)은
        # 그대로 두고 흔적만 남긴다.
        log(f"[경고] 실행 락 해제 실패({type(e).__name__}: {e}) - 다음 회차가 "
            f"'이미 실행 중'으로 스킵되면 {os.path.basename(LOCK_FILE_PATH)}를 확인하세요")


def _try_sso_relogin(driver) -> bool:
    """세션이 끊겨 Sign In 페이지에 있으면 SSO 버튼을 눌러 재로그인을 시도한다.

    2026-08-06(2차): 실제 구현을 icbl_ci_watcher.sso_relogin()으로 모았다.
    예전엔 이 로직을 파일마다 복사해 뒀는데, 같은 날 확인해보니 복사본끼리
    대기시간이 24초/48초로 어긋나 있었다(주석은 전부 "24초"라고 적혀 있었음).
    그리고 이번에 발견한 자동 복구 실패 원인 2가지(버튼 렌더 지연을 '버튼 없음'
    으로 오판 / MS 계정 타일이 is_displayed()로는 안 잡힘)도 4곳에 따로 고치면
    또 어긋난다. 구현은 하나만 두고 여기서는 이 파일의 log()만 넘긴다 -
    로그는 그대로 이 파일의 로그에 남는다."""
    return sso_relogin(driver, log)


# ==============================================================
# 유틸
# ==============================================================
def log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_state() -> dict:
    """2026-08-06: 예전에는 파일이 깨져 있으면 `except: return {}`로 빈 상태를
    돌려줬는데, 이 스크립트에서 그건 "아직 아무 주문도 처리 안 했다"는 뜻이라
    LOOKBACK_START_DATE 이후의 모든 메일이 다시 '신규'가 되어 **이미 출고된
    주문을 다시 릴리즈하고 완료 메일을 다시 보낸다.** 실제 창고 출고를
    트리거하는 스크립트라 절대 그렇게 두면 안 된다 - 파일이 있는데 깨져 있으면
    그 회차를 중단시킨다(read_json_state의 strict=True). 파일이 아예 없는
    첫 실행은 예전처럼 {}로 정상 진행한다."""
    return read_json_state(STATE_PATH, "출고 처리 이력", strict=True)


# 2026-07-23: 병렬 처리 도입 이후 여러 스레드(+메인 스레드의 _finalize_order_mail)
# 가 동시에 이 상태 파일에 저장을 시도할 수 있어(백오더 후속 SP 도중 진행상황을
# 즉시 저장하는 기능 추가로 빈도가 늘어남) - save_state() 자체를 락으로 감싸서
# 어느 호출부에서 부르든 파일 쓰기가 서로 안 겹치게 한다.
_state_file_lock = threading.Lock()


def save_state(state: dict):
    # 2026-08-06: open("w")는 파일을 먼저 비우고 쓰기 때문에 도중에 프로세스가
    # 죽으면 이력 파일이 통째로 깨진다(이 스크립트는 실제로 2026-07-23에 처리
    # 도중 프로세스가 죽은 전력이 있다 - _save_partial_fg_success 주석 참고).
    # 임시 파일에 다 쓰고 바꿔치기하는 방식으로 바꿔 그 위험을 없앤다.
    # 스레드 락은 그대로 유지(워커 2개가 동시에 저장할 수 있음).
    with _state_file_lock:
        atomic_write_json(STATE_PATH, state)


# 2026-07-23 실측(00594646, 부천 휴먼피부과): FG는 이미 released_lines=1로
# 성공했는데, 백오더 감지로 추가 실행한 SP 도중 프로세스 자체가(원인 불명,
# 아마도 Windows 업데이트와 시점이 겹침) 통째로 죽어서 FG 성공 기록이 상태에
# 전혀 안 남았음 - 이런 경우는 예외처리로 못 잡음(프로세스가 죽어버리니
# except 블록 자체가 실행 안 됨). 그 다음 재시도들은 FG부터 다시 시작했는데
# FG는 이미 유일한 released 라인을 다 뺐어서 재시도해도 Customer가 절대 안
# 뜨는(더 뺄 게 없는) 00594053과 같은 무한반복 함정에 또 빠짐. 대응: FG가
# 성공하는 즉시(SP를 시도하기 전에) 그 결과를 디스크에 먼저 기록해두고,
# 다음 실행이 이 기록을 발견하면 FG를 재실행하지 않고 그 결과를 그대로 써서
# SP부터 이어서 처리한다 - 프로세스가 중간에 몇 번을 죽어도 FG 성공만큼은
# 절대 잃지 않음.
# 2026-08-19: 처리 이력(state)의 키는 원래 주문번호 그 자체였다. 그런데 FIBER
# 백오더를 추가하면서 실측으로 문제가 드러났다 - 00593940(YOU&I Clinic Sanbon)은
# 2026-07-23 불량/프로모션 건으로 **다른 라인**이 이미 released_lines=1로 처리돼
# 이력에 남아 있는데, 이번 FIBER 표에는 아직 Backordered인 fiber 라인이 또
# 들어 있다. 키가 주문번호뿐이면 이 건이 "이미 처리됨"으로 조용히 빠지고,
# 그런데도 배치 완료 집계에는 들어가서 **그 병원 것만 안 나간 채 "완료" 답장이
# 나간다.** 그래서 FIBER 백오더만 키에 카테고리를 붙여 다른 카테고리의 이력과
# 섞이지 않게 한다(기존 카테고리는 키가 예전 그대로라 이력 파일/조회 영향 없음).
FIBER_STATE_KEY_PREFIX = "FIBER:"


def state_key(kind: str, order_no: str) -> str:
    if kind == "FIBER백오더":
        return FIBER_STATE_KEY_PREFIX + order_no
    return order_no


def _save_partial_fg_success(state: dict, order_no: str, r: dict):
    partial = state.setdefault("_partial_fg_backorder", {})
    partial[order_no] = {
        "released_lines": r["released_lines"],
        "backordered_lines": r.get("backordered_lines"),
        "customer": r["customer"],
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(state)


def _clear_partial_fg_success(state: dict, order_no: str):
    state.get("_partial_fg_backorder", {}).pop(order_no, None)
    save_state(state)


# 2026-08-10 사용자 요청: 자동 발송/초안 메일 글꼴을 굴림 -> 맑은 고딕으로 통일.
# 굴림이 나오던 이유: 답장에 끼워 넣던 <div>에 글꼴 지정이 없어 원본 메일의
# 글꼴을 그대로 물려받았고, 평문(.Body)으로 만들던 메일은 Outlook 평문
# 기본 글꼴을 따라갔다.
MAIL_FONT_CSS = "font-family:'맑은 고딕',Malgun Gothic,sans-serif;font-size:10.0pt"


def mail_text_to_html(text: str) -> str:
    """평문 본문을 맑은 고딕 HTML로 감싼다.
    HTML은 연속 공백을 하나로 줄이므로 들여쓰기가 뭉개지지 않도록 2칸 이상
    연속 공백은 &nbsp;로 보존한다."""
    import html as html_module
    esc = html_module.escape(str(text or ""))
    esc = esc.replace("\r\n", "\n").replace("\r", "\n")
    esc = re.sub(r"  +", lambda mm: "&nbsp;" * len(mm.group()), esc)
    esc = esc.replace("\t", "&nbsp;&nbsp;&nbsp;&nbsp;")
    return f'<div style="{MAIL_FONT_CSS}">' + esc.replace("\n", "<br>") + "</div>"


def send_alert(subject: str, body: str):
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)
    mail.To = ALERT_MAIL_TO
    mail.Subject = subject
    mail.HTMLBody = mail_text_to_html(body)
    mail.Save()
    log(f"알림 메일 초안 저장: {subject}")


# 2026-08-24: 같은 내용의 "확인 필요" 알림 반복 억제.
# 실패한 주문은 상태파일에 안 남아 다음 회차에 자동 재시도되는데(그게 설계 의도다),
# 원인이 **Salesforce -> 오라클 미연동**이면 몇 시간이고 안 풀린다. 그동안 5~10분마다
# 같은 알림 초안이 계속 쌓인다 - 8/24 실측: 주문 3건에 대해 초안 9통이 생겼고,
# 이 상태로 두면 그날 안에 수십 통이 된다(사용자 확인: 그날 5건 전부 미연동이었다).
# 첫 통은 그대로 보내되, **같은 조합이 반복되는 동안만** 조용히 넘긴다.
# 실패 주문 조합이 바뀌면(새 주문이 끼면) 키가 달라져 즉시 다시 알린다.
ALERT_REPEAT_COOLDOWN_SEC = 3 * 3600      # 같은 내용이면 3시간에 한 번만
ALERT_REPEAT_STATE = os.path.join(ROOT, "_alert_repeat_state.json")


def _should_send_repeat_alert(key: str) -> bool:
    """이번 알림을 실제로 보낼지. 보낼 때만 True를 주고 시각을 기록한다.
    상태 파일을 못 읽으면 '보낸 적 없음'으로 보고 보낸다 - 억제가 실패하는 쪽이
    알림을 놓치는 쪽보다 안전하다."""
    now = time.time()
    try:
        with open(ALERT_REPEAT_STATE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    try:
        last = float(data.get(key, 0))
    except (TypeError, ValueError):
        last = 0.0
    if now - last < ALERT_REPEAT_COOLDOWN_SEC:
        return False
    # 하루 지난 항목은 버려서 파일이 무한정 커지지 않게 한다.
    cutoff = now - 24 * 3600
    kept = {}
    for k, v in data.items():
        try:
            if float(v) >= cutoff:
                kept[k] = v
        except (TypeError, ValueError):
            continue
    kept[key] = now
    try:
        with open(ALERT_REPEAT_STATE, "w", encoding="utf-8") as f:
            json.dump(kept, f, ensure_ascii=False)
    except Exception as e:
        log(f"[경고] 알림 억제 상태 기록 실패({e}) - 같은 알림이 또 올 수 있음")
    return True


# ==============================================================
# 1) Outlook에서 신규 출고 요청 메일 찾기
# ==============================================================
def _parse_html_tables(html: str) -> list:
    """HTML 본문의 표를 [[행1칸들, 행2칸들, ...], ...] 로 돌려준다.

    평문(.Body)이 아니라 HTML(.HTMLBody)을 보는 이유: FIBER 백오더 메일은
    "몇 번째 칸이 어느 컬럼인가"가 중요한데(오더번호 vs 오더번호2), 평문으로
    변환되면 표의 칸들이 그냥 한 줄씩 나열돼 컬럼 구분이 사라진다. 그러면
    "Backordered 뒤 몇 번째 숫자" 같은 위치 추측에 기대야 하고, 그 추측은
    컬럼이 하나 늘거나 줄면 조용히 틀린 주문을 집는다(2026-08-19 실제로 그렇게
    틀렸다). HTML에는 <th>/<td>가 그대로 있어 헤더 이름으로 컬럼을 찾을 수 있다.
    Word가 만든 메일 HTML은 표가 중첩되기도 해서 정규식 대신 lxml로 파싱한다."""
    import lxml.html
    doc = lxml.html.fromstring(html)
    tables = []
    for tb in doc.xpath("//table"):
        rows = []
        for tr in tb.xpath("./tr | ./thead/tr | ./tbody/tr"):
            cells = [" ".join(c.text_content().split()) for c in tr.xpath("./td | ./th")]
            if cells:
                rows.append(cells)
        if len(rows) >= 2:
            tables.append(rows)
    return tables


def extract_fiber_backorder_order_nos(html_body: str) -> list:
    """FIBER 백오더 메일에서 릴리즈할 sales order 번호 목록을 뽑는다.

    사용자 확정(2026-08-19): 릴리즈에 쓰는 번호는 **"오더번호2" 칸**의 6자리
    앞에 00을 붙인 것(232157 -> 00232157). 옆의 "오더번호"(589904 등)가 아니다.

    처리 순서:
    1) 메일 안의 모든 표를 읽어 헤더에 "오더번호"가 있는 표만 남긴다.
    2) 그중 "오더번호2" 칸이 있는 표(= 보통 아래 인용된 원본)에서
       {오더번호: 오더번호2} 대응표를 만든다.
    3) **첫 번째 표**(= 보현 과장님이 윤길님 앞으로 새로 붙인 이번 요청 표)의
       행만 대상으로, 그 행에 오더번호2가 있으면 그대로 쓰고 없으면 2)의
       대응표에서 찾아 쓴다. 위치가 아니라 오더번호 값으로 맞추므로 두 표의
       행 순서가 달라도, 요청이 원본의 일부만 담고 있어도 정확하다.
    4) 끝내 못 찾은 행은 **릴리즈하지 않고** 경고만 남긴다 - 번호를 잘못 넣으면
       엉뚱한 주문의 재고가 실제로 출고되므로 빠뜨리는 쪽이 안전하다."""
    tables = []
    for rows in _parse_html_tables(html_body):
        header = rows[0]
        if FIBER_COL_ORDER not in header:
            continue
        i_order = header.index(FIBER_COL_ORDER)
        i_so = header.index(FIBER_COL_ORDER_SO) if FIBER_COL_ORDER_SO in header else None
        tables.append((i_order, i_so, rows[1:]))

    if not tables:
        log(f"[경고] FIBER 백오더 메일에서 '{FIBER_COL_ORDER}' 컬럼이 있는 표를 못 찾음")
        return []

    def cell(row, idx):
        if idx is None or idx >= len(row):
            return None
        v = row[idx].strip()
        return v if re.fullmatch(r"\d{6}", v) else None

    # 인용된 원본 표에서 오더번호 -> 오더번호2 대응표
    order_to_so = {}
    for i_order, i_so, body_rows in tables:
        if i_so is None:
            continue
        for row in body_rows:
            o, so = cell(row, i_order), cell(row, i_so)
            if o and so:
                order_to_so.setdefault(o, so)

    i_order, i_so, request_rows = tables[0]
    order_nos, unresolved = [], []
    for row in request_rows:
        o = cell(row, i_order)
        if not o:
            continue
        so = cell(row, i_so) or order_to_so.get(o)
        if so:
            order_nos.append("00" + so)
        else:
            unresolved.append(o)
    if unresolved:
        log(f"[경고] FIBER 백오더: 오더번호 {unresolved}의 "
            f"'{FIBER_COL_ORDER_SO}'를 메일 안에서 못 찾아 제외함 "
            f"(이 건들은 수동 확인 필요)")
    return list(dict.fromkeys(order_nos))


def find_near_miss_order_nos(body: str) -> list:
    """"오더번호: 0059761"처럼 00으로 시작하는데 8자리가 아닌 번호를 찾아준다.

    2026-08-20 실측: 리쥬베리의원 선출고 건("DCD 출고 요청의 건 (리쥬베리의원) -
    선출고 택배 8월 11일")은 본문 오더번호가 **7자리(0059761)** 로 적혀 있었다.
    릴리즈 대상은 `00`+6자리라 정규식에 안 걸려 8/11부터 열흘간 매 회차
    "주문번호 못 찾음"으로 **조용히 스킵**됐고(오늘 하루만 12번), 그동안 물건은
    이미 선출고된 채 전산 처리만 안 된 상태로 방치됐다. 조용한 스킵이 문제의
    본질이므로, 자리수만 어긋난 게 눈에 보이면 사람 앞으로 알림을 남긴다.
    번호를 자동으로 보정하지는 않는다 - 빠진 한 자리를 추측하면 **엉뚱한 병원
    주문을 출고**시킬 수 있어서, 판단은 사람이 해야 한다."""
    found = []
    for m in re.finditer(r"오더\s*번호[^0-9\n]{0,10}(\d{4,10})", body):
        num = m.group(1)
        if num.startswith("00") and len(num) != 8:
            found.append(num)
    return list(dict.fromkeys(found))


def find_new_order_mails(processed_orders: set, manual_skip_entry_ids: set = frozenset(),
                         prereleased_entry_ids: set = None,
                         bad_order_no_entry_ids: set = None,
                         backorder_reprocessed_entry_ids: set = None) -> list:
    """prereleased_entry_ids: 본문에 "윤길"이 없어서(= 보현 과장님이 이미 오라클에서
    release 완료) 건너뛴 메일의 EntryID 집합. **주문번호가 아니라 메일 단위로**
    기록하는 이유: 같은 주문번호가 나중에 "윤길님, 선출고 릴리즈 부탁드립니다"
    메일로 다시 오면 그때는 정상 처리돼야 하므로 주문번호를 처리완료로 못 박으면
    안 된다. 이 집합은 호출부(main)가 상태파일에 저장해서 같은 메일에 매 회차
    같은 로그가 쌓이는 것만 막는다(넘어온 set에 새로 발견한 것을 직접 추가함).

    backorder_reprocessed_entry_ids: 처리완료된 오더번호를 제목의 "백오더" 키워드로
    강제 재처리한 메일의 EntryID 집합(2026-09-17). **메일 1건당 딱 1번만** 강제
    재처리하기 위한 장치 - 없으면 그 메일이 받은편지함에 남아있는 한 스캔마다
    (20~40분 간격) 매번 오라클에 재접속해 같은 오더번호를 다시 릴리즈 시도하게
    되는데, 첫 시도로 이미 완전히 끝난 주문이라도 Customer 미표시가 "확정 종료"가
    아니라 "확인 필요"로 잡혀 매번 새 알림까지 나가는 문제가 실전에서 확인됨
    (00602410/00602411 - 12:09에 성공 릴리즈+완료답장까지 끝났는데 12:20 스캔이
    같은 메일을 또 강제 재처리해 false-positive "확인 필요" 알림을 만듦)."""
    import win32com.client

    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    inbox = outlook.GetDefaultFolder(6)

    op = None
    for f in inbox.Folders:
        if str(f.Name).strip() == OUTLOOK_PARENT_SUBFOLDER:
            op = f
            break
    if op is None:
        raise RuntimeError(f"Outlook 폴더를 못 찾음: 받은편지함 > {OUTLOOK_PARENT_SUBFOLDER}")

    target = None
    for f in op.Folders:
        if OUTLOOK_SUBFOLDER in str(f.Name):
            target = f
            break
    if target is None:
        raise RuntimeError(
            f"Outlook 폴더를 못 찾음: 받은편지함 > {OUTLOOK_PARENT_SUBFOLDER} > {OUTLOOK_SUBFOLDER}"
        )

    items = target.Items
    items.Sort("[ReceivedTime]", True)

    results = []
    # 2026-08-06: 아래 항목 읽기 실패는 예전엔 조용히 건너뛰었다 - 출고 요청
    # 메일 한 통을 통째로 빠뜨리는 건데 로그에 흔적이 없어서 "왜 이 주문이
    # 처리 안 됐지"를 추적할 방법이 없었다. 동작(건너뛰기)은 그대로 두고
    # 흔적만 남기되, 로그 폭주를 막기 위해 앞의 3건만 남긴다.
    _item_errors = 0
    for i in range(1, min(items.Count, 100) + 1):
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

        subject = str(mail.Subject or "")
        body = str(mail.Body or "")

        kind = None
        matched_by_new_rule = False  # 2026-08-04 추가 규칙 3개 전용 컷오프 판별용
        matched_by_purchase_rule = False  # 2026-09-18 "구매의 건" 규칙 전용 컷오프 판별용
        if FIBER_BACKORDER_SUBJECT_KEYWORD in subject.upper():
            # 2026-08-19 추가. 제목에 "택배"가 들어 있어 그냥 두면 아래 마지막
            # catch-all이 소모품으로 잡아가는데, 그 경로는 본문에서 00으로 시작하는
            # 8자리를 찾으므로 이 메일은 "주문번호 못 찾음"으로 계속 스킵된다
            # (실측 로그 2026-08-19 14:15). 그래서 다른 어떤 규칙보다 먼저 본다.
            kind = "FIBER백오더"
        if kind is None and "출고 요청" in subject:
            if "DCD" in subject.upper():
                kind = "DCD"
            elif "소모품" in subject:
                kind = "소모품"
        if kind is None and "구매의 건" in subject:
            # 2026-09-18 추가: "소모품 구매의 건- 아티움 울템 9.18"처럼 "출고
            # 요청" 대신 "구매의 건"을 쓰는 제목도 있음 - 나머지 판정(DCD/소모품)은
            # "출고 요청"과 동일하게 취급.
            if "DCD" in subject.upper():
                kind = "DCD"
                matched_by_purchase_rule = True
            elif "소모품" in subject:
                kind = "소모품"
                matched_by_purchase_rule = True
        if kind is None:
            # 2026-07-13 사용자 확인: "출고 요청"이라는 말 없이 "아주대 4캔 DCD
            # - 퀵발송 7/13"처럼 택배/퀵발송 표현만 있는 제목도 많음(실측 58건
            # 확인). GMPP 장비납품이동 스레드는 "DCD 퀵발송"을 언급해도 실제
            # 출고요청이 아니라서 제외.
            has_ship_word = any(kw in subject for kw in ("택배", "퀵발송", "퀵", "선출고"))
            is_equipment_move = any(kw in subject for kw in ("GMPP", "장비납품", "릴리즈"))
            if has_ship_word and not is_equipment_move:
                if "DCD" in subject.upper():
                    kind = "DCD"
                elif "소모품" in subject:
                    kind = "소모품"
                elif "박스" in subject:
                    # 2026-08-04 사용자 확인: 제목에 "DCD"/"소모품" 문자열이 아예
                    # 없어도(예: "모던 스탠다드 4 박스 - 8월 4일 택배") "박스"라는
                    # 단위 표현은 보통 DCD 제품에 쓰인다고 확인 - DCD로 처리.
                    kind = "DCD"
                    matched_by_new_rule = True
        if kind is None:
            if any(kw in subject for kw in DEFECT_PROMO_SUBJECT_KEYWORDS):
                kind = "불량/프로모션"
        if kind is None:
            # 2026-08-04 사용자 요청: 택배/퀵발송류 표현이 전혀 없어도("DCD
            # 한박스 불량"처럼 불량품 회수/교환 성격의 제목) 제목에 "DCD"와
            # "불량"이 같이 있으면 DCD로 처리한다. "불량 및 프로모션"/
            # "프로모션 및 불량"(위 불량/프로모션 카테고리, 여러 병원이 묶여
            # 오는 별도 케이스)과는 문구가 달라 겹치지 않고, 그 카테고리 체크가
            # 이미 먼저 끝났으니 여기 걸리는 건 순수 DCD 개별 건이다. 본문에
            # 00으로 시작하는 8자리 주문번호가 없으면 이 뒤 로직에서 어차피
            # 경고 로그 후 스킵되므로 여기서 별도로 확인하지 않는다.
            is_equipment_move = any(kw in subject for kw in ("GMPP", "장비납품", "릴리즈"))
            if "DCD" in subject.upper() and "불량" in subject and not is_equipment_move:
                kind = "DCD"
                matched_by_new_rule = True
        if kind is None:
            # 2026-08-04 실측 확인: "하얀피부과 광주 DCD 2박스 - 8월 4일"처럼
            # 택배/퀵발송/퀵/선출고 같은 발송 단어가 아예 없이 날짜만 붙은
            # 제목도 있음(본문에 "우선 발송 부탁드립니다" 같은 요청 문구는
            # 있으나 제목엔 발송 단어가 없어 위 has_ship_word 분기를 못 탐).
            # 제목에 "DCD"와 "박스"가 같이 있으면(둘 다 이미 충분히 구체적인
            # 신호라 발송 단어가 없어도 안전) DCD로 처리한다.
            is_equipment_move = any(kw in subject for kw in ("GMPP", "장비납품", "릴리즈"))
            if "DCD" in subject.upper() and "박스" in subject and not is_equipment_move:
                kind = "DCD"
                matched_by_new_rule = True
        if kind is None:
            # 2026-07-24 사용자 요청: 이노메드(외부 협력업체) 부품주문 건도
            # 자동 처리. 제목 예: "[External] [이노메드] 부품주문의 건_IHP26009
            # - 택배 7월24일" - 실측 확인: 같은 "이노메드 부품주문의 건" 제목
            # 패턴이라도 "...Unused 요청"처럼 택배/발송 단어 없이 재고조정만
            # 요청하는 건도 있어(출고 대상 아님) - 택배 단어가 같이 있을 때만
            # 실제 출고 요청으로 판단.
            has_ship_word = any(kw in subject for kw in ("택배", "퀵발송", "퀵", "선출고"))
            if "이노메드" in subject and "부품주문" in subject and has_ship_word:
                kind = "이노메드"
        if kind is None:
            # 2026-07-10: 보현 과장님이 "케어봇"(원장님이 직접 주문 넣는 챗봇)
            # 주문을 전달할 때는 제목을 매번 자유롭게 씀("OO의원 DCD 2박스 -
            # 택배 발송 7/10" 등, "출고 요청"이라는 말이 아예 없는 경우가 많음) -
            # 대신 전달 과정에서 원본 메일이 인용되므로 본문에 "케어봇"/"CareBot"
            # 이 항상 들어있음. 전부 DCD 성격의 주문이라 DCD와 동일하게 처리.
            if ("케어봇" in body) or ("CareBot" in body):
                kind = "DCD"
        if kind is None:
            # 2026-08-04 사용자 요청: 택배/퀵발송류 표현은 있는데 위 어떤 신호
            # (DCD/소모품/박스/불량프로모션/이노메드/케어봇)에도 안 걸리는 제목이
            # 계속 나옴(예: "밴스의원 용산 울템 1개 - 택배 8/4" - "울템"처럼
            # 매번 다른 제품명이 들어옴). "택배"라고 나오는 건 다 체크해야 하고,
            # 어떤 제품인지 확신이 없으면(= "박스" 표현이 없으면) 소모품처럼
            # FG+SP를 둘 다(SP도 처음부터) 도는 쪽이 더 안전하다는 사용자 판단에
            # 따라 이 마지막 catch-all은 kind="소모품"으로 처리한다.
            has_ship_word = any(kw in subject for kw in ("택배", "퀵발송", "퀵", "선출고"))
            is_equipment_move = any(kw in subject for kw in ("GMPP", "장비납품", "릴리즈"))
            if has_ship_word and not is_equipment_move:
                kind = "소모품"
                matched_by_new_rule = True
        if kind is None:
            continue

        if kind == "불량/프로모션" and received_dt < DEFECT_PROMO_LOOKBACK_START_DATE:
            continue
        if kind == "이노메드" and received_dt < INOMED_LOOKBACK_START_DATE:
            continue
        if kind == "FIBER백오더" and received_dt < FIBER_BACKORDER_LOOKBACK_START_DATE:
            continue
        if matched_by_new_rule and received_dt < NEW_SUBJECT_RULES_LOOKBACK_START_DATE:
            continue
        if matched_by_purchase_rule and received_dt < PURCHASE_SUBJECT_RULE_START_DATE:
            continue

        # 불량/프로모션은 한 메일에 여러 병원(주문번호)이 묶여서 올 수 있으므로
        # 전부 뽑아야 함(DCD/소모품은 메일당 1건이라 findall도 결과가 1개뿐).
        # FIBER 백오더는 본문에 8자리 주문번호가 아예 없고, 표의 "오더번호2" 칸
        # 6자리 앞에 00을 붙여야 sales order 번호가 된다 - 어느 칸인지 알아야
        # 하므로 이 카테고리만 평문이 아니라 HTML 본문을 본다
        # (extract_fiber_backorder_order_nos 참고, 2026-08-19).
        if kind == "FIBER백오더":
            order_nos = extract_fiber_backorder_order_nos(str(mail.HTMLBody or ""))
        else:
            order_nos = list(dict.fromkeys(re.findall(r"\b(00\d{6})\b", body)))
        if not order_nos:
            if mail.EntryID in manual_skip_entry_ids:
                # 2026-07-13: 주문번호가 아예 없어서 사용자가 직접 수동으로
                # 처리한 메일 - 상태파일은 주문번호 기준이라 여기 기록할 수
                # 없으므로 EntryID로 따로 추적해 매번 경고 로그가 안 쌓이게 함.
                continue
            # 2026-08-20: 자리수만 어긋난 오더번호는 "못 찾음"으로 조용히 흘리지
            # 않고 사람 앞으로 알림 초안을 남긴다(find_near_miss_order_nos 주석 -
            # 리쥬베리의원 건이 이 때문에 열흘간 방치됐다). 알림은 메일 1건당
            # 한 번만(EntryID로 기억) - 20분마다 도는 스크립트라 아니면 초안이 쌓인다.
            near_miss = find_near_miss_order_nos(body)
            if near_miss and bad_order_no_entry_ids is not None \
                    and mail.EntryID not in bad_order_no_entry_ids:
                log(f"[경고] 오더번호 자리수가 안 맞음 {near_miss} (8자리여야 함) "
                    f"- 알림 초안 저장: {subject}")
                try:
                    send_alert(
                        f"[Pick Release] 오더번호 자리수 확인 필요 - {subject}",
                        f"아래 메일의 본문 오더번호가 8자리가 아니어서 자동 릴리즈를 "
                        f"건너뛰었습니다.\n\n"
                        f"제목: {subject}\n"
                        f"본문에 적힌 번호: {', '.join(near_miss)}\n\n"
                        f"릴리즈 대상은 00으로 시작하는 8자리 sales order 번호입니다.\n"
                        f"빠진 자리를 임의로 추측하면 다른 병원 주문이 출고될 수 있어 "
                        f"자동 보정은 하지 않았습니다. 정확한 주문번호를 확인해 "
                        f"수동으로 릴리즈하거나, 요청자에게 번호 정정을 요청해 주세요.")
                except Exception as e:
                    log(f"[에러] 오더번호 자리수 알림 발송 실패: {exc_detail(e)}")
                else:
                    bad_order_no_entry_ids.add(mail.EntryID)
                continue
            log(f"[경고] 본문에서 8자리 주문번호를 못 찾음(스킵): {subject}")
            continue

        new_order_nos = [o for o in order_nos if state_key(kind, o) not in processed_orders]
        if not new_order_nos:
            # 2026-09-17: 오더번호는 이미 처리완료로 기록돼 있지만, 제목에 "백오더"가
            # 있으면(=재고 부족으로 남았던 라인을 나중에 다시 릴리즈해달라는 후속
            # 메일로 추정) processed 판정을 무시하고 강제로 재처리 대상에 넣는다.
            # 사용자 요청: 알림만 보내지 말고 실제로 재릴리즈 시도 + 성공하면 기존과
            # 동일한 "Release 완료됐습니다" 완료 답장을 자동 발송할 것.
            #
            # **메일당 딱 1번만** - 안 그러면 이 메일이 받은편지함에 남아있는 한
            # 스캔마다(20~40분 간격) 계속 강제 재처리된다. 실전 확인(12:07 회차):
            # 00602410/00602411/00602838 재릴리즈 성공+완료답장까지 끝났는데, 20분
            # 뒤 12:20 회차가 같은 메일을 EntryID 기억 없이 또 강제 재처리해 이미
            # 끝난 주문에 대해 Customer 미표시(=더 뺄 라인 없음, 정상)를 "확인
            # 필요"로 오판해 잘못된 알림을 만들었다. EntryID를 한 번 쓰면 그 뒤로는
            # (성공/백오더 지속/실패 관계없이) 이 메일로 다시 강제 재처리하지 않는다 -
            # 재고가 그래도 안 들어왔다면 이번 시도 결과(0건 확정 시 "확인 필요"
            # 알림, 재고부족 확정 아니면 상태 미기록으로 다음 회차 자연 재시도)를
            # 그대로 신뢰한다. 병원에서 또 새 "백오더" 메일(다른 EntryID)이 오면
            # 그건 정상적으로 다시 강제 재처리된다.
            if BACKORDER_ALERT_SUBJECT_KEYWORD in subject \
                    and backorder_reprocessed_entry_ids is not None \
                    and mail.EntryID not in backorder_reprocessed_entry_ids:
                log(f"[백오더 재시도] 처리완료된 오더번호({', '.join(order_nos)})의 "
                    f"백오더 후속 메일로 보여 재릴리즈 시도(이 메일 최초 1회): {subject}")
                backorder_reprocessed_entry_ids.add(mail.EntryID)
                new_order_nos = order_nos
            else:
                continue

        # 본문에 "윤길"이 없으면 릴리즈 요청 메일이 아니라 이미 보현 과장님이
        # 오라클에서 release를 끝내고 용마에 발송만 요청한 메일 - 시도해봐야
        # 뽑을 라인이 없어 Customer 미표시로만 끝난다(RELEASE_REQUEST_NAME_TOKEN 주석).
        # 2026-08-26: 인용문(이전 메일)은 빼고 **이번에 새로 쓴 부분만** 본다.
        # 예전엔 본문 전체를 봐서, 스레드에 윤길님의 옛 답장이 딸려오면 그것만으로
        # "릴리즈 요청"으로 오판했다(_body_before_quote 주석의 00599914 사례).
        request_body = _body_before_quote(body)
        if RELEASE_REQUEST_NAME_TOKEN not in request_body:
            if prereleased_entry_ids is None or mail.EntryID not in prereleased_entry_ids:
                quoted_only = RELEASE_REQUEST_NAME_TOKEN in body
                log(f"[스킵] 본문에 '{RELEASE_REQUEST_NAME_TOKEN}' 언급 없음 - 보현 과장님이 "
                    f"이미 오라클에서 release한 건(용마 앞 발송 요청)으로 판단: "
                    f"{subject} {new_order_nos}"
                    + ("  ※'윤길'이 인용문에만 있어 제외(2026-08-26 규칙) - 혹시 이게 "
                       "진짜 릴리즈 요청이었다면 이 줄을 근거로 규칙을 재검토할 것"
                       if quoted_only else ""))
                if prereleased_entry_ids is not None:
                    prereleased_entry_ids.add(mail.EntryID)
            continue

        results.append({
            "entry_id": mail.EntryID,
            "subject": subject,
            "kind": kind,
            "order_nos": new_order_nos,
            "all_order_nos": order_nos,
        })

    return results


# ==============================================================
# 2) 오라클 Create Pick Wave -> Release Now
# ==============================================================
class RuleInputDeadError(RuntimeError):
    """Release Rule 칸에 키 입력이 끝내 도달하지 못한 상태.

    2026-08-20에 규명된 대로 이건 **그 Edge 세션 전체가 키 입력을 안 받는 상태**다
    (창 가림 감지로 visibilityState='hidden' → send_keys가 예외 없이 버려짐).
    2026-08-24 실측으로 이게 왜 하루 종일 반복되는지가 드러났다: 이 증상은 결국
    Customer 미표시로 나타나 `CustomerNotShownError`로 분류되는데, 상위
    `_process_single_order`가 그 분류를 "뽑을 라인 없음 확정"으로 보고 **재시도 없이
    즉시 사람 확인으로 넘긴다.** 그래서 죽은 세션이 그대로 남고, 5~10분 뒤 다음
    회차가 **같은 죽은 Edge에 다시 붙어** 똑같이 실패한다 - 00599358이 13:35/13:45/
    13:55에 증상까지 동일하게 3번 실패한 게 이것이다.

    새 탭을 열어봐야 같은 세션이라 소용없으므로, 이 오류는 **Edge 프로세스 재시작**
    으로 에스컬레이션해야 한다(_process_single_order에서 처리).
    """


class CustomerNotShownError(RuntimeError):
    """Order 입력 후 Customer가 3분 대기+재시도까지 해도 안 뜨는 경우 - 원인이
    (1) ServiceMax 연동 지연이거나 (2) 이미 다른 경로로 release 끝나서 남은
    라인이 없는 경우, 둘 다 가능해 일반적으로는 사람 확인이 필요하다. 단,
    2026-07-14에 추가된 "DCD 백오더 감지 시 SP 룰 추가 실행" 케이스에서는
    2026-07-21 사용자가 명확히 확인: 이 경우 SP에서 Customer가 안 뜨는 건
    "SP로 뽑을 라인이 없다"는 뜻일 뿐이라 정상 처리로 봐야 함(원인 (2)로 확정,
    사람 확인 불필요) - 그래서 이 예외를 별도 타입으로 분리해 그 호출부에서만
    구분해서 잡는다."""


def _field_by_label(driver, label_text: str):
    from selenium.webdriver.common.by import By
    label = _wait_find(driver, By.XPATH, f"//label[normalize-space(text())='{label_text}']")
    input_id = label.get_attribute("for")
    return _wait_find(driver, By.ID, input_id)



def _click_blank_area(driver) -> bool:
    """Create Pick Wave 폼의 **빈 화면**을 실제 마우스로 한 번 클릭한다.

    Order 번호를 넣고 Tab만 치면 오라클이 주문 조회(PPR)를 늦게 거는 일이 잦은데,
    빈 곳을 한 번 클릭하면 Customer가 눈에 띄게 빨리 뜬다(2026-09-02 사용자 관찰).
    Rebalance TO 자동화의 시리얼 입력 화면에서 이미 같은 방식이 검증돼 있다
    (2026-08-27: "기입하고 대기보다 그냥 흰 화면 한번 클릭해야하네").

    입력칸 아래 여백 좌표를 계산하고, 그 지점에 **정말 아무것도 없는지**
    elementFromPoint로 확인한 뒤에만 누른다. 버튼/입력칸 위면 클릭하지 않는다.
    """
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        point = driver.execute_script(r"""
            // 폼 입력칸들 중 가장 아래를 찾아 그보다 더 아래(여백) 지점을 고른다
            const els = document.querySelectorAll("input, select");
            let bottom = 0;
            for (const e of els) {
              const r = e.getBoundingClientRect();
              if (r.width && r.height && r.bottom > bottom) bottom = r.bottom;
            }
            const y = Math.min(bottom + 80, window.innerHeight - 20);
            const x = Math.round(window.innerWidth * 0.5);
            const hit = document.elementFromPoint(x, y);
            return {x: x, y: Math.round(y),
                    tag: hit ? hit.tagName.toLowerCase() : null,
                    id: hit ? (hit.id || '') : ''};
        """)
        if not point or not point.get("tag"):
            return False
        # 누르면 뭔가 동작하는 자리면 건드리지 않는다
        if point["tag"] in ("a", "button", "input", "select", "option",
                            "textarea", "label"):
            return False
        rect = body.rect
        dx = int(point["x"] - (rect["x"] + rect["width"] / 2))
        dy = int(point["y"] - (rect["y"] + rect["height"] / 2))
        ActionChains(driver).move_to_element_with_offset(body, dx, dy).click().perform()
        return True
    except Exception:
        return False           # 클릭은 속도 최적화일 뿐 - 실패해도 원래대로 진행


# 2026-08-07: Order 입력 후 Customer가 채워질 때까지 기다리는 한도.
# 예전에는 탭아웃 후 고정 3초만 자고 Customer를 딱 한 번 읽어, 그 순간 비어
# 있으면 곧바로 "미표시"로 판정하고 3분(180초)을 대기했다. 그런데 오늘 12:21
# 회차(불량/프로모션 38건 배치) 실측에서 미표시 판정 7건이 **전부** 3분 뒤
# 재시도에서 released_lines=1로 정상 성공했다 - 값이 없었던 게 아니라 3초
# 안에 안 그려졌을 뿐이다. 병렬 2개 탭이 같은 Edge를 공유하는데 백그라운드
# 창은 크로미움이 렌더링/타이머를 늦추므로 이 PPR(Partial Page Render)이
# 3초를 넘기는 일이 잦다. 그래서 고정 대기 대신 채워질 때까지 폴링한다 -
# 채워지는 즉시 반환하므로 정상 상황의 속도는 그대로고, 느릴 때만 더 기다린다.
# 이 한도까지 기다려도 비어 있으면 주문번호를 **다시 입력**해서 재시도하고
# (아래 CUSTOMER_ENTRY_ATTEMPTS 참고), 그래도 안 되면 그때 비로소 기존의 3분
# 대기 경로로 간다(진짜 ServiceMax 연동 지연이나 "뽑을 라인 없음"일 수 있으므로
# 그 판정 로직 자체는 건드리지 않음).
#
# 2026-08-07(2차 관찰로 진단 수정): 위 "3초로는 부족하다"는 진단만으로 30초
# 폴링을 넣고 12:47 회차를 돌려봤더니, 미표시가 난 건들은 **30초를 꽉 채워
# 60번을 들여다봐도 끝내 안 떴고**(00596265/00596411/00596280 ...), 그런데
# 3분 뒤 재시도에서 주문번호를 *다시 입력*하자 즉시 떴다. 즉 이 케이스의
# 실제 원인은 "느리게 그려진다"가 아니라 **첫 입력의 탭아웃이 조회를 아예
# 못 걸었다**(입력/포커스가 씹힘 - 이 코드베이스에서 반복되는 백그라운드 창
# 클릭 씹힘과 같은 계열)에 가깝다. 그러면 아무리 오래 쳐다봐도 영원히 안
# 뜨므로 폴링 한도를 늘리는 건 낭비고, **다시 입력하는 것**이 유일한 해법이다.
# 그래서 한도를 짧게(10초) 줄이고 대신 재입력을 최대 2번 더 한다.
# 다만 "정말 느리게 그려지는 케이스"가 존재하는지는 아직 실측된 적이 없어,
# 폴링으로 건져낸 경우 몇 초 만에 떴는지를 로그에 남겨 다음에 판단할 수 있게 함
# (그 로그가 계속 안 보이면 폴링 자체는 사실상 불필요하다는 뜻이고, 자주
# 보이면 한도를 다시 늘릴 근거가 된다).
CUSTOMER_FILL_TIMEOUT_SEC = 10
CUSTOMER_FILL_POLL_SEC = 0.5

# 주문번호를 입력해보는 총 횟수(최초 1회 + 재입력 2회). 재입력이 실제 해법이라
# 3분 대기로 넘어가기 전에 여기서 대부분 해소되기를 기대한다 - 최악이라도
# 10초×3 + 입력/탭 오버헤드 = 40초 안쪽이라 기존 3분 대기보다 훨씬 싸다.
CUSTOMER_ENTRY_ATTEMPTS = 3
# 백오더 후속 SP(skip_customer_wait)는 빈 Customer가 곧 "뽑을 라인 없음"이라
# 대부분 진짜로 안 채워진다 - 3회까지 갈 이유는 없지만, 입력이 씹힌 것뿐인데
# "라인 없음"으로 오판하면 조용히 미출고가 되므로 확인 사살로 1번은 더 해본다.
CUSTOMER_ENTRY_ATTEMPTS_SKIPWAIT = 2

# 2026-08-11: Create Pick Wave 폼(Release Rule/Order Type/Order)을 채워보는 총 횟수.
# 실측(00597604 소모품 SP, 00597607 DCD FG): Order를 입력/탭아웃하는 과정에서
# 오라클이 화면을 다시 그리며 **Release Rule 칸이 비어버리는** 경우가 있다
# (00597604는 Customer 미표시로 주문번호를 재입력한 뒤, 00597607은 재입력도 없이
# 1회차에 Customer가 4.3초 만에 채워진 뒤 - 즉 재입력 여부와 무관하게 발생).
# Release Now 직전 검증이 이걸 잡아내 예외를 올리면 상위가 '화면을 새로 열어'
# 재시도해서 결국 성공하지만(둘 다 2회차에 성공), 회차마다 네비게이션에 40~60초를
# 버린다. 화면을 새로 열 것 없이 같은 화면에서 폼 전체를 다시 채우면 되므로
# (아래 검증부 주석 참고 - 순서를 지켜 rule -> Order Type -> Order를 통째로 다시
# 채우기 때문에 "rule만 다시 넣어 Order가 리셋되는" 위험이 없다) 여기서 1번 더
# 채워본다. 그래도 어긋나면 예전처럼 예외를 올려 화면 재오픈 경로로 넘긴다.
FORM_FILL_ATTEMPTS = 2

# 2026-08-18: Release Rule 칸의 값이 반영될 때까지 **기다렸다가** 확인한다.
#
# 이 칸을 읽으면 ''가 나오는 현상은 8/11부터 계속 로그에 남아(00597604/00597607,
# 08-13 00597953, 08-14 00597852/00597841/00597837, 08-18 00598544/00598542)
# 그때마다 "입력이 씹혔다"는 진단으로 이어졌는데, **오진이었다.** 8/18 15:00
# 실측으로 확정: 넣은 직후 2.5초 뒤에 읽는 확인을 넣었더니 00598547은 3/3회,
# 00598548은 6/6회 전부 ''로 읽혔는데 **두 건 다 그대로 released_lines=1로
# 정상 출고됐다**(14:56:20, 14:57:22). 즉 값은 제대로 들어가 있고, 오라클이
# 서버 왕복(PPR)을 마치고 DOM의 value에 반영하는 데 2.5초보다 오래 걸릴 뿐이다.
# 실제로 30초쯤 뒤 Release Now 직전 검증은 같은 읽기로 정상 통과한다.
#
# 그래서 해법은 '다시 입력하기'가 아니라 **채워질 때까지 기다리기**다(Customer
# 칸이 이미 같은 이유로 폴링을 쓰고 있다 - _wait_customer_value 참고). 고정 대기
# 뒤 한 번 읽는 방식은 오라클이 느린 날마다 멀쩡한 입력을 "씹혔다"고 오진하고,
# 그 오진에 따른 재입력(clear + 재타이핑)이 왕복을 처음부터 다시 시작시켜
# 오히려 상황을 악화시킨다.
# 2026-08-19 스크린샷으로 확정된 뒤 조정: 이 칸이 ''로 읽힐 때는 **진짜로 비어
# 있다**(읽기가 거짓말하는 게 아니었다 - 8/18의 '읽기가 늦게 반영된다'는 추정은
# 틀렸다). 그러니 오래 기다리는 건 낭비고, 해법은 **다시 넣는 것**이다.
# 그래서 대기는 짧게(8초) 줄이고 재입력 횟수를 늘린다.
RULE_VALUE_TIMEOUT_SEC = 8
RULE_VALUE_POLL_SEC = 0.5
RULE_FILL_ATTEMPTS = 3


# 2026-08-07: Create Pick Wave의 Order Type. 이 스크립트가 처리하는 건(DCD/소모품/
# 불량프로모션/이노메드/케어봇)은 전부 병원으로 나가는 판매주문이라 항상 이 값이다
# (드롭다운의 다른 값: Return to customer / Return to supplier / Unreferenced
# supplier return / Return transfer order / Transfer order - Rebalance 같은
# 이전주문은 이 스크립트 소관이 아님).
PICK_WAVE_ORDER_TYPE = "Sales order"


def _set_order_type(driver, expected: str = PICK_WAVE_ORDER_TYPE) -> str:
    """Order Type 드롭다운을 expected로 맞추고, 실제로 반영된 표시값을 돌려준다.
    이미 그 값이면 건드리지 않는다(불필요한 화면 다시 그리기 방지)."""
    from selenium.webdriver.support.ui import Select

    sel = Select(_field_by_label(driver, "Order Type"))
    cur = (sel.first_selected_option.text or "").strip()
    if cur == expected:
        return cur
    sel.select_by_visible_text(expected)
    # 값이 바뀌면 오라클이 화면 일부를 다시 그린다(PPR) - 다음 단계(Order 입력)와
    # 겹쳐 stale element가 나지 않게 Release Rule 탭아웃과 같은 정도로 쉬어준다.
    time.sleep(2.5)
    return (Select(_field_by_label(driver, "Order Type"))
            .first_selected_option.text or "").strip()


def _wait_customer_value(driver, resolve_popup, timeout: float = CUSTOMER_FILL_TIMEOUT_SEC):
    """Customer 입력칸에 값이 들어올 때까지 폴링해서 읽어온다.
    반환: (값, 기다린 초) - 끝내 비면 값은 "". 호출부가 '몇 초 만에 떴는지'를
    로그로 남길 수 있도록 걸린 시간도 같이 준다.
    폴링 도중 뒤늦게 "Search and Select: Order" 팝업이 뜰 수 있어(그게 떠 있으면
    Customer는 영원히 안 채워짐) 매 회차마다 resolve_popup으로 함께 확인한다."""
    started = time.time()
    deadline = started + timeout
    while True:
        resolve_popup()
        try:
            val = _field_by_label(driver, "Customer").get_attribute("value") or ""
        except Exception:
            # PPR 도중이면 요소가 방금 다시 그려져 stale일 수 있다 - 다음 회차에
            # 다시 찾으면 되므로 여기서는 비어 있는 것으로 보고 계속 기다린다.
            val = ""
        if val.strip() or time.time() >= deadline:
            return val, time.time() - started
        time.sleep(CUSTOMER_FILL_POLL_SEC)


def _save_diag_screenshot(driver, tag: str) -> str:
    """실패 순간의 화면을 PNG로 남긴다.

    2026-08-19: Release Rule 칸이 비는 원인을 이틀 동안 로그만 보고 추측하다
    번번이 오진했는데, 사용자가 **직접 찍어준 스크린샷 한 장**으로 즉시 확정됐다
    (Release Rule만 비고 Order/Customer는 정상 = 입력이 그 칸에만 도달 못 함).
    사람이 그 순간에 화면을 보고 있어야만 알 수 있다는 게 문제였으므로, 실패
    시점에 스스로 남긴다. 파일명은 `_diag_`로 시작해 나중에 정리하기 쉽게 한다.
    스크린샷 저장 실패가 본 처리를 막으면 안 되므로 예외는 삼킨다."""
    try:
        name = f"_diag_{tag}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        path = os.path.join(ROOT, name)
        driver.save_screenshot(path)
        return name
    except Exception:
        return ""


def _focus_field(driver, el) -> bool:
    """입력칸에 **실제로 포커스가 갔는지 확인**하고, 안 갔으면 JS로 직접 준다.

    2026-08-19 스크린샷 실증(00597152, 14:03:53): Create Pick Wave 화면에서
    Release Rule 칸만 빈 채로 남고 Order/Customer는 정상으로 채워져 있었다.
    즉 이 칸에 대한 입력이 **화면에 아예 도달하지 못한다**. 백그라운드 Edge에서
    네이티브 click()이 조용히 씹혀 포커스가 안 잡히는 건 이 코드베이스의 반복
    이슈이고(Tasks 아이콘도 같은 이유로 execute_script 클릭으로 바꿨다),
    포커스가 없으면 뒤따르는 send_keys는 아무 데도 안 들어간다.
    반환값이 False면 그 회차 입력은 어차피 헛발질이므로 호출부가 로그를 남긴다."""
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
    except Exception:
        pass
    try:
        el.click()
    except Exception:
        # 유리창(AFModalGlassPane)에 막히는 등으로 네이티브 클릭이 아예 예외를
        # 낼 수 있다 - 아래 JS focus로 이어서 시도한다.
        pass
    try:
        if driver.execute_script("return document.activeElement === arguments[0];", el):
            return True
        driver.execute_script("arguments[0].focus();", el)
        return bool(driver.execute_script(
            "return document.activeElement === arguments[0];", el))
    except Exception:
        return False


def _read_field(driver, label_text: str) -> str:
    """label_text 칸의 현재 value를 한 번만 읽는다(폴링 없음).
    PPR 도중이라 요소가 stale이면 ''로 본다 - 호출부가 '지금 화면에 값이 있나'만
    보려는 용도이므로 예외로 흐름을 끊지 않는다."""
    try:
        return _field_by_label(driver, label_text).get_attribute("value") or ""
    except Exception:
        return ""


def _js_set_field_value(driver, label_text: str, value: str) -> bool:
    """JS로 입력칸에 값을 직접 박는다.

    ⚠️ **본 처리 경로에서는 쓰지 말 것 (2026-08-20 실측으로 확인).**
    이 방식은 DOM의 value만 바꾸고 **오라클 ADF의 서버 모델까지는 닿지 않는다.**
    판정 근거: Release Rule이 ADF에 정상 반영되면 오라클이 Order Type을
    'Sales order'로 자동 채워주는데(같은 날 네이티브 입력 성공 회차에서 실제로
    자동채움 확인), JS로 넣은 회차는 값이 화면에 보이고 탭아웃 후에도 남아 있는데
    **Order Type이 끝까지 ''였다.** Order 칸도 마찬가지로 JS로 00597616을 넣으니
    화면엔 보이는데 Customer가 끝내 안 떴다(= ADF가 주문 조회를 안 걸었다).

    즉 이걸 본 처리에 쓰면 **Release Now 직전 3칸 검증(DOM을 읽는다)이 통과해버리는데
    서버는 빈 조건인 상태**가 된다 - 그 검증은 잘못된 출고를 막는 load-bearing
    가드이므로(pickwave-empty-rule-not-proven-cause) 무력화하면 안 된다.
    그래서 실제 호출부에서 뺐고, 진단용으로만 남긴다.

    (아래는 이 함수를 처음 넣을 때의 근거 - 증상 자체는 여전히 유효하다.)
    2026-08-20 확정(캡쳐 `_diag_rule_00597773_20260820_114303.png` + 로그):
    Release Rule 칸은 **포커스는 정상으로 잡히는데**(2026-08-19에 넣은
    `_focus_field` 실패 로그가 그 뒤 한 건도 안 찍혔다) send_keys한 글자가 화면에
    아예 안 남는다. 게다가 **같은 회차의 Order 칸은 같은 방식으로 잘 들어간다**
    (그 캡쳐를 남긴 00597773도 검증 로그가 `('', 'Sales order', '00597773')`).
    즉 창 포커스 문제도, 세션 문제도 아니고 이 칸에 대한 키 입력만 사라진다.
    ("Order 칸은 잘 들어간다"는 부분은 그 회차 한정이었다 - 같은 날 오후
    harness 실측에서는 **Release Rule과 Order가 같은 회차에 둘 다** 씹혔다.
    즉 특정 칸의 문제가 아니라 그 세션/회차 전체가 키 입력을 안 받는 상태다.)

    반환값은 'DOM에 넣기까지 성공했는지'일 뿐, ADF가 받아들였는지가 아니다."""
    try:
        el = _field_by_label(driver, label_text)
        driver.execute_script(
            "arguments[0].value = arguments[1];"
            "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
            "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));",
            el, value)
        return True
    except Exception:
        return False


def _wait_field_value(driver, label_text: str, expected: str,
                      timeout: float = RULE_VALUE_TIMEOUT_SEC):
    """label_text 칸의 value가 expected가 될 때까지 폴링한다.
    반환: (읽은 값, 기다린 초) - 끝내 다르면 마지막으로 읽은 값을 그대로 준다.
    오라클 PPR이 끝나는 시점이 매번 다르기 때문에 고정 대기 뒤 한 번 읽는 방식은
    느린 회차에서 멀쩡한 입력을 '빈칸'으로 오진한다(RULE_VALUE_TIMEOUT_SEC 주석)."""
    started = time.time()
    deadline = started + timeout
    val = ""
    while True:
        try:
            val = (_field_by_label(driver, label_text).get_attribute("value") or "").strip()
        except Exception:
            # PPR 도중이면 방금 다시 그려져 stale일 수 있다 - 다음 회차에 다시 찾는다.
            val = ""
        if val == expected or time.time() >= deadline:
            return val, time.time() - started
        time.sleep(RULE_VALUE_POLL_SEC)


# 2026-08-06: Inventory Management 화면이 다 그려질 때까지 기다리는 한도.
# _wait_find의 기본값 8초로는 부족한 경우가 로그로 확인됨(13:41:13 회차: Tasks
# 아이콘이 DOM에는 있는데 8초 안에 클릭 가능 상태가 안 됨). _wait_find는 0.3초
# 간격 폴링이라 준비되는 즉시 반환하므로, 이 값을 크게 잡아도 정상 상황의 처리
# 속도에는 영향이 없다(느릴 때만 더 기다려줄 뿐).
INV_PAGE_READY_TIMEOUT_SEC = 40
INV_NAV_CLICK_ATTEMPTS = 2  # 클릭이 씹혔을 때 같은 화면에서 다시 눌러보는 횟수




def navigate_to_create_pick_wave(driver):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select

    # 2026-07-10 실측: 11건 배치처럼 여러 주문을 연달아 처리할 때, 페이지 전환이
    # 다 끝나기 전에 다음 클릭이 나가서 "Tasks 아이콘 못 찾음" 등으로 실패하는
    # 경우가 있었음(사용자 확인) - 각 단계 대기 시간을 넉넉하게 늘림.
    # 2026-08-06: 같은 Edge를 공유하는 다른 자동화의 탭을 보고 있으면 아래
    # driver.get()이 남의 탭을 덮어쓰고, 그 뒤 "Inventory Management" 클릭이
    # 엉뚱한 화면에서 실패한다(실측: Rebalance TO 7866552가 이 지점에서
    # "클릭할 요소를 못 찾음: Inventory Management"로 3번 다 실패) - 내 탭으로
    # 먼저 되돌린다.
    # 2026-08-06 (#3 안전 전환): 고정 대기 중 '조건이 미리 참일 수 없는 것이
    # 확실한 자리'만 wait_or_sleep으로 바꾼다. wait_or_sleep은 조건이 충족되면
    # 즉시 진행하고, 끝까지 안 되면 **원래 sleep과 정확히 같은 시간**을 기다린
    # 뒤 진행하므로 최악의 경우가 기존과 동일하다. 클릭 대상과 순서는 그대로다.
    _ensure_my_tab(driver)
    driver.get(ORACLE_HOME_URL)
    # driver.get()으로 페이지를 새로 받았으니 이 텍스트는 '새 홈 화면이 그려진
    # 뒤에만' 존재할 수 있다(이전 DOM은 사라짐) - 미리 참이 될 수 없어 안전.
    wait_or_sleep(driver, text_visible("Supply Chain Execution"), 5)

    # 2026-08-06: 아래 클릭들이 네이티브 click()으로는 조용히 씹히는 게 실측으로
    # 확인돼 JS 클릭으로 바꿨다(_js_click_text 설명 참고).
    _js_click_text(driver, "Supply Chain Execution")
    # 여기는 일부러 고정 sleep을 유지한다: 스프링보드에서는 'Inventory Management'
    # 아이콘이 이 클릭 **전에도 이미 보이는** 경우가 있어서(icbl_ci_watcher.py
    # _goto_scheduled_processes에 같은 함정이 실측 기록돼 있다 - 아이콘이 재배치되는
    # 중에 눌러 빈 곳을 클릭하고, 예외도 안 나면서 화면이 안 넘어감) 조건이 미리
    # 참이 되어 지금보다 '이르게' 클릭할 위험이 있다. 오라클 화면으로 직접
    # 확인하기 전까지는 기존 동작을 그대로 둔다.
    time.sleep(3)

    # 클릭이 씹혔는지는 예외로 알 수 없고 '화면이 안 바뀐 것'으로만 드러나므로,
    # Tasks 아이콘이 뜨는지로 진입 성공을 직접 확인하고 안 됐으면 다시 누른다.
    tasks_icon = None
    for attempt in range(INV_NAV_CLICK_ATTEMPTS):
        _js_click_text(driver, "Inventory Management")
        try:
            tasks_icon = _wait_find(driver, By.XPATH, "//img[@title='Tasks']",
                                    timeout=INV_PAGE_READY_TIMEOUT_SEC)
            break
        except Exception:
            if attempt == INV_NAV_CLICK_ATTEMPTS - 1:
                raise
            log(f"  Inventory Management 진입 확인 안 됨(클릭 {attempt + 1}회) - "
                f"홈으로 되돌아가 다시 시도")
            driver.get(ORACLE_HOME_URL)
            # 위와 같은 이유로 안전(페이지를 새로 받았으므로 미리 참일 수 없음).
            wait_or_sleep(driver, text_visible("Supply Chain Execution"), 5)
            _js_click_text(driver, "Supply Chain Execution")
            time.sleep(3)  # 위와 같은 이유로 고정 대기 유지

    # 2026-08-06(2차) 공유 브라우저 상태 간섭 대응: Tasks 아이콘은 **토글**이라
    # 이미 열려 있는데 또 누르면 패널이 닫힌다. 이 열림 상태는 driver.get()으로
    # 페이지를 다시 열어도 유지되고, 같은 Edge를 공유하는 자동화 중 아무도
    # 패널을 닫지 않는다 - 앞선 자동화(sco_cancel 등)가 열어둔 채 끝내면 여기서
    # 스스로 닫아버려 바로 아래 _wait_find(Shipments select)가 실패한다. 상위
    # 재시도가 다시 열어서 결국 복구는 되지만 회차당 40초 이상을 버리고 로그에는
    # "요소를 못 찾음"으로 남아 원인을 오진하게 만든다.
    # sco_cancel_watcher에서 같은 가드를 먼저 넣어 검증했다(실패조건 3종 3/3 성공).
    if not tasks_panel_open(driver):
        driver.execute_script("arguments[0].click();", tasks_icon)
    # Shipments 옵션을 가진 select는 Tasks 패널이 열려야 생긴다 - 이 클릭 전에는
    # 존재할 수 없으므로 미리 참이 될 수 없어 안전. 2초 안에 안 뜨면 기존처럼
    # 그냥 진행하고, 바로 아래 _wait_find(최대 40초)가 이어서 기다린다.
    wait_or_sleep(driver, element_present(
        By.XPATH, "//select[option[normalize-space(text())='Shipments']]"), 2)

    # Tasks 패널이 열리며 그려지는 항목도 같은 이유로 늦을 수 있어 함께 늘림.
    sel_el = _wait_find(
        driver, By.XPATH,
        "//select[option[normalize-space(text())='Shipments']]",
        timeout=INV_PAGE_READY_TIMEOUT_SEC,
    )
    Select(sel_el).select_by_visible_text("Shipments")
    # 2026-08-06(2차): 'Create Pick Wave'는 Shipments 카테고리 작업이라 다른
    # 카테고리(예: sco_cancel이 남긴 Inventory)에서는 안 보인다 - 카테고리를
    # 실제로 바꿔야 하는 경우엔 조건이 미리 참일 수 없어 안전하고, 이미
    # Shipments였다면 즉시 진행하는 것이 맞다(기다릴 대상이 없음).
    # ship_confirm_watcher의 같은 구간에서 A/B 실측 검증함(-55%).
    wait_or_sleep(driver, text_visible("Create Pick Wave"), 2)

    # 같은 이유(백그라운드 창에서 네이티브 클릭 씹힘)로 여기도 JS 클릭. 이 클릭이
    # 씹히면 다음 단계의 "Release Rule" 라벨을 못 찾아 실패하므로, 화면이 실제로
    # 열렸는지 그 라벨로 확인하고 안 됐으면 한 번 더 누른다.
    for attempt in range(INV_NAV_CLICK_ATTEMPTS):
        _js_click_text(driver, "Create Pick Wave")
        try:
            _wait_find(driver, By.XPATH, "//label[normalize-space(text())='Release Rule']",
                       timeout=INV_PAGE_READY_TIMEOUT_SEC)
            break
        except Exception:
            if attempt == INV_NAV_CLICK_ATTEMPTS - 1:
                raise
            log(f"  Create Pick Wave 화면 확인 안 됨(클릭 {attempt + 1}회) - 다시 시도")
            time.sleep(3)
    time.sleep(3)


def create_and_release_pick_wave(driver, release_rule: str, order_no: str, skip_customer_wait: bool = False) -> dict:
    """_create_and_release_pick_wave_once를 감싸서, 화면이 채워지는 도중 오라클
    ADF가 부분적으로 다시 그려지며(Partial Page Render) 방금 찾아둔 요소 참조가
    무효화되는 stale element reference 오류가 나면 화면을 처음부터 다시 열어
    (재네비게이션) 딱 1번만 재시도한다(원래 시도 1회 + 재오픈 1회 = 총 2회 시도,
    그 이상은 안 함).
    2026-07-15 실측: 00593293/00593106 두 건이 이 오류로 실패했는데, 예전엔
    그대로 실패 처리하고 다음 예약 실행(최대 5분 뒤)에서 새로 화면을 열며
    저절로 해소되길 기다렸음 - 실제로 둘 다 그렇게 해소됐음. 그렇다면 5분을
    기다릴 이유가 없으므로, 같은 실행 안에서 화면을 처음부터 다시 열어 바로
    재시도하도록 당김 - 새로 연 화면에는 오래된 참조가 있을 수 없어 안전하다.
    재오픈을 2번 이상 허용하면(예: Customer 미표시로 인한 3분 대기가 매번 겹칠
    경우) 한 건 처리가 너무 길어져 5분 뒤 다음 예약 실행과 겹칠 위험이 있다고
    사용자가 우려함 - 그래서 재오픈은 딱 1번으로 제한(더 필요하면 알림 후 다음
    예약 실행에 맡김, 기존 방식과 동일).
    skip_customer_wait: True면 Customer 미표시를 3분 대기+재시도 없이 즉시
    확정으로 처리한다(2026-07-23, 백오더 후속 SP 전용 - 그 경로는 Customer
    미표시=확정 뽑을 라인 없음으로 이미 결론이 정해져 있어 3분씩 기다릴
    이유가 없음, `_run_backorder_secondary`에서 True로 넘김)."""
    from selenium.common.exceptions import StaleElementReferenceException

    try:
        return _create_and_release_pick_wave_once(driver, release_rule, order_no, skip_customer_wait)
    except StaleElementReferenceException as e:
        log(
            f"  {order_no}: stale element reference 발생 - 화면을 새로 열어 "
            f"딱 1번만 재시도합니다"
        )
        time.sleep(2)
        return _create_and_release_pick_wave_once(driver, release_rule, order_no, skip_customer_wait)


def _create_and_release_pick_wave_once(driver, release_rule: str, order_no: str, skip_customer_wait: bool = False) -> dict:
    """Create Pick Wave 화면을 새로 열어 Release Rule/Order를 채우고 Release Now.
    반환: {"released_lines": int, "backordered_lines": int|None, "customer": str}"""
    from selenium.webdriver.common.by import By

    # 2026-07-10 실측: icbl_ci_watcher.py가 거의 같은 시각에 "디버그 포트로 떠
    # 있는 Edge가 없음 -> 새로 실행 시도" 로그를 남긴 직후에 이 네비게이션이
    # 반복 실패하는 패턴이 확인됨 - Edge가 막 재시작된 직후라 SPA가 아직 안정화
    # 안 된 것으로 추정. 대기시간만으로는 부족한 경우가 있어, 네비게이션 자체를
    # 최대 2번 더 재시도한다(총 3회 시도).
    last_err = None
    for attempt in range(3):
        try:
            navigate_to_create_pick_wave(driver)
            last_err = None
            break
        except Exception as e:
            last_err = e
            log(f"  {order_no}: Create Pick Wave 화면 이동 실패(시도 {attempt + 1}/3) - {e}")
            # 2026-08-06: 브라우저 세션이 끊긴 거라면 같은 driver로 5초씩 쉬며
            # 2번을 더 시도해봐야 똑같이 실패한다(실측 로그 00594693: 14:34:45/
            # 50/55에 5초 간격으로 동일한 invalid session id 3줄). 바로 위로
            # 올려서 _process_single_order가 '새 드라이버로' 재시도하게 한다.
            if is_session_dead_error(e):
                log(f"  {order_no}: 브라우저 세션이 끊김 - 같은 세션 재시도를 중단하고 "
                    f"새 드라이버로 다시 받도록 올려보냄")
                break
            time.sleep(5)
    if last_err:
        raise last_err

    # 2026-08-11: Release Rule/Order Type 채우기를 함수로 묶는다 - Release Now 직전
    # 검증에서 값이 어긋났을 때(FORM_FILL_ATTEMPTS 주석 참고) 화면을 새로 열지 않고
    # 같은 화면에서 이 순서 그대로 다시 채워 복구하기 위함. 동작/대기시간은 예전
    # 코드 그대로이고 감싸기만 했다.
    # 2026-08-24: Release Rule 입력이 끝내 도달 못 했는지를 기록해둔다. 이게 True면
    # Customer가 안 뜨는 건 "뽑을 라인 없음"이 아니라 죽은 세션 탓이므로 분류를
    # 바꿔야 한다(RuleInputDeadError 주석 참고).
    rule_state = {"dead": False}

    def _fill_rule_and_order_type(is_refill: bool = False):
        if is_refill:
            # 재입력 회차에서는 잔여 모달(AFModalGlassPane)이 떠 있으면 아래 클릭이
            # 통째로 막히므로 먼저 정리한다 - 첫 회차는 화면을 방금 열어서 떠 있을
            # 수 없다(_dismiss_stray_modal 주석 참고).
            _dismiss_stray_modal()
        # 2026-08-18: 넣은 직후 값이 남았는지 확인하고, 안 남았으면 여기서 바로
        # 다시 넣는다(RULE_FILL_ATTEMPTS 주석 참고). 예전에는 확인 없이 넘어가서
        # 빈 Release Rule이 한참 뒤에야 드러났다.
        # 2026-08-19 사용자 확인: **Release Rule이 비면 Release Now를 눌러도 성공으로
        # 뜨지 않는다** - 인자가 전부 기입돼야 릴리즈가 된다. 그러니 이 칸을 여기서
        # 확실히 넣는 게 이 함수의 핵심이다.
        # (주의: Customer 표시 여부는 Release Rule과 무관하다 - 빈 채로도 Customer는
        # 뜬다(08-19 스샷). "Customer가 떴으니 폼이 정상"으로 판단하면 안 된다.)
        for rule_try in range(1, RULE_FILL_ATTEMPTS + 1):
            rule_el = _field_by_label(driver, "Release Rule")
            # 2026-08-19: 포커스가 실제로 잡혔는지 확인하고 넣는다(_focus_field 주석 -
            # 스크린샷상 이 칸만 비어 있었다 = 입력이 화면에 도달을 못 한 것).
            if not _focus_field(driver, rule_el):
                log(f"  {order_no}: Release Rule 칸에 포커스가 안 잡힘"
                    f"(입력 {rule_try}/{RULE_FILL_ATTEMPTS}회차, 클릭 씹힘 의심) - "
                    f"그래도 입력은 시도함")
            rule_el.clear()
            rule_el.send_keys(release_rule)
            time.sleep(1)
            # 2026-08-20: **탭아웃 전에** 한 번 읽는다. 이 한 줄이 열흘째 오진을
            # 반복해온 두 가설을 갈라준다(pickwave-empty-rule-not-proven-cause):
            # 여기서 값이 없으면 키 입력 자체가 화면에 못 닿은 것이고, 여기선
            # 있는데 아래 폴링에서 ''로 읽히면 탭아웃/PPR이 지운 것이다.
            # 그리고 못 닿은 경우는 기다려도 안 생기므로 바로 JS로 넣는다
            # (_js_set_field_value 주석 - 8/19의 '포커스 씹힘' 진단으로는
            # 안 고쳐지는 증상임이 8/20 캡쳐로 확정됐다).
            typed = _read_field(driver, "Release Rule")
            if typed != release_rule:
                log(f"  {order_no}: send_keys가 화면에 도달 못 함(탭아웃 전 읽은 값 "
                    f"{typed!r}, 입력 {rule_try}/{RULE_FILL_ATTEMPTS}회차)")
            driver.switch_to.active_element.send_keys("\t")
            # 2026-07-15: 탭아웃 직후 오라클이 Order 필드 쪽을 리셋하며 화면 일부를
            # 백그라운드에서 다시 그리는데(Partial Page Render), 이 시점과 다음 단계의
            # 요소 탐색이 겹치면 stale element reference가 나는 것으로 의심돼(00593293/
            # 00593106 사례) 대기시간을 늘려 겹칠 확률을 줄인다(1.5초 -> 2.5초. 근본
            # 차단은 아니고 확률을 낮추는 정도 - 그래도 나면 위 재오픈 1회로 복구).
            time.sleep(2.5)
            # 반영될 때까지 기다린다 - 여기서 한 번만 읽고 판단하면 느린 회차의
            # 멀쩡한 입력을 '씹혔다'고 오진한다(RULE_VALUE_TIMEOUT_SEC 주석).
            landed, waited = _wait_field_value(driver, "Release Rule", release_rule)
            if landed == release_rule:
                if waited >= 1.0:
                    # 고정 대기 방식이었다면 오진했을 회차 - 이 줄이 얼마나 자주
                    # 찍히는지가 폴링 한도를 조정할 근거가 된다.
                    log(f"  {order_no}: Release Rule이 {2.5 + waited:.1f}초 만에 반영됨"
                        f"(폴링으로 확인)")
                break
            log(f"  {order_no}: Release Rule이 {2.5 + waited:.1f}초를 기다려도 안 들어감"
                f"(입력 {rule_try}/{RULE_FILL_ATTEMPTS}회차, 읽은 값 {landed!r}) - 다시 입력")
            if rule_try < RULE_FILL_ATTEMPTS:
                # 입력이 "Search and Select: Release Rule" 팝업으로 새 나갔다면
                # 유리창이 다음 클릭을 통째로 막으므로 먼저 정리한다.
                _dismiss_stray_modal()
            else:
                # 마지막 회차까지 안 들어갔다 - 이 순간의 화면을 남긴다. Release
                # Rule이 비면 Release Now가 성공으로 뜨지 않으므로(2026-08-19
                # 사용자 확인) 여기서 못 넣으면 아래 Release Now 직전 검증이
                # 폼 전체를 다시 채우거나 화면을 새로 열게 된다 - 그 전에 증거를
                # 확보해둬야 다음에 또 추측으로 헤매지 않는다.
                rule_state["dead"] = True
                shot = _save_diag_screenshot(driver, f"rule_{order_no}")
                log(f"  {order_no}: Release Rule {RULE_FILL_ATTEMPTS}회 입력 모두 실패"
                    + (f" - 화면 저장: {shot}" if shot else " (화면 저장도 실패)"))

        # 2026-08-07: Order Type을 명시적으로 'Sales order'로 박아둔다.
        # 화면을 처음 열면 Order Type은 비어(value='0') 있고, Release Rule을 넣고
        # 탭아웃하면 오라클이 알아서 'Sales order'(value='5')로 채워준다 - 실측 확인.
        # 그래서 평소에는 안 넣어도 돌아갔지만, 이건 "오라클이 채워주기를 기대하는"
        # 암묵적 의존이라 화면이 리셋되거나 재입력이 끼면 비어버릴 수 있고, 그러면
        # Release Now가 조용히 released_lines=0으로 끝난다(00597212 실측: 13:12
        # 자동실행은 Customer 미표시 재입력 2회를 거친 뒤 SP로 0건이 나왔는데,
        # 13:44에 같은 주문/같은 SP 룰로 Order Type을 직접 채워 돌리니 1건 출고됨).
        # 기대에 맡기지 않고 매번 직접 세팅한다.
        _set_order_type(driver)

    # 2026-07-08 실측: Release Rule 확정(탭아웃) 시 Order 필드가 리셋되므로
    # 반드시 그 다음에 입력해야 함(Order Type도 Order보다 먼저 세팅해야 한다 -
    # Order Type 변경이 화면을 다시 그리며 Order를 날릴 수 있어서).
    def _dismiss_stray_modal():
        # 2026-07-09 실측: Order가 아직 인식 안 되는 상태(ServiceMax 연동 지연)에서
        # 탭아웃하면 "Search and Select: Order"(No rows to display) 팝업이 뜨고
        # 그 유리창(AFModalGlassPane)이 화면을 막아 다음 시도의 클릭이 막힘.
        # ESC는 이 팝업을 안 닫음(실측 확인) - 팝업의 Cancel 버튼을 직접 눌러야
        # 닫힘. 주의: 팝업이 없는 정상 상태에서도 메인 페이지 우측 상단에
        # "Cancel"(Create Pick Wave 전체 취소) 버튼이 항상 보이므로, 유리창이
        # 실제로 떠 있는지(AFModalGlassPane 존재) 먼저 확인한 뒤에만 Cancel을
        # 누른다 - 그래야 정상 상태에서 잘못 페이지 전체를 취소하는 사고를 막음.
        try:
            if not driver.find_elements(By.CLASS_NAME, "AFModalGlassPane"):
                return
            cancel_btns = [
                el for el in driver.find_elements(By.XPATH, "//*[normalize-space(text())='Cancel']")
                if el.is_displayed()
            ]
            if cancel_btns:
                cancel_btns[0].click()
                time.sleep(1)
        except Exception as e:
            # 2026-08-06: 이 정리가 실패하면 유리창(AFModalGlassPane)이 화면을
            # 막은 채로 남아 뒤따르는 클릭이 전부 막힌다 - 이 함수 주석에
            # 기록된 연쇄 실패의 원인 그대로다. 예전엔 조용히 넘어가서 그
            # 뒤의 "요소를 못 찾음"만 로그에 남았다. 동작은 그대로 두고
            # 원인을 남긴다.
            log(f"  [경고] 잔여 모달 정리 실패({type(e).__name__}: {e}) - "
                f"이후 클릭이 막히면 이 줄을 먼저 의심할 것")

    def _resolve_order_search_popup_if_any():
        # 2026-07-10 실측/사용자 확인: Order 입력 후 탭아웃 시 인라인 자동완성이
        # 안 되면 "Search and Select: Order" 팝업이 뜨는데, 그냥 OK를 누르면
        # (팝업 자체 검색 없이) Customer가 채워짐. 이걸 안 닫고 넘어가면 유리창
        # (AFModalGlassPane)이 남아 다음 주문 처리까지 연쇄적으로 깨지므로
        # (stale element, 요소 못 찾음 등) 뜨는 즉시 여기서 닫는다. OK가 안 보이면
        # (정말 못 찾은 경우) Cancel로 정리.
        if not driver.find_elements(By.CLASS_NAME, "AFModalGlassPane"):
            return
        ok_btns = [
            el for el in driver.find_elements(By.XPATH, "//*[normalize-space(text())='OK']")
            if el.is_displayed()
        ]
        if ok_btns:
            ok_btns[0].click()
            time.sleep(2)
        if driver.find_elements(By.CLASS_NAME, "AFModalGlassPane"):
            cancel_btns = [
                el for el in driver.find_elements(By.XPATH, "//*[normalize-space(text())='Cancel']")
                if el.is_displayed()
            ]
            if cancel_btns:
                cancel_btns[0].click()
                time.sleep(1)

    def _enter_order_and_read_customer(refill_form_first: bool = False):
        # 2026-08-14: "Customer는 3칸이 다 채워져야만 뜬다"고 봤으나, 2026-08-19
        # 스크린샷(00597152)에서 **Release Rule이 빈 채로도 Customer가 정상 표시**됐다.
        # 그래도 아래 재입력 로직은 그대로 두는 게 맞다 - Release Rule이 비면
        # Release Now가 성공으로 뜨지 않으므로(08-19 사용자 확인) 어차피 순서대로
        # 다시 세워야 하기 때문이다. 다만 **Customer가 안 뜨는 원인을 Release Rule
        # 빈칸으로 단정하지는 말 것**(그 추론이 8/14~8/18 내내 오진을 만들었다).
        # 예전 코드는 재입력 회차에서 Order만 다시 넣었는데, 그 사이 오라클 PPR이
        # Release Rule을 날려버린 상태였다면 재입력이 구조적으로 무의미했다. 게다가
        # 그렇게 Customer가 끝내 안 뜨면 CustomerNotShownError로 함수 밖으로 튀어
        # 나가기 때문에, Release Now 직전 검증(= 폼 전체를 다시 채우는 복구 경로,
        # FORM_FILL_ATTEMPTS)에는 **도달조차 못 한다** - 원인이 "폼이 비었다"인데
        # "ServiceMax 연동 지연이거나 뽑을 라인 없음"으로 오진되어 실패로 남았다.
        # 실측 00597837(불량/프로모션, Daybeau Clinic Busan): 13:05 회차와 13:29
        # 회차 모두 Order만 4번(3회 + 3분 대기 후 1회) 다시 치고 그대로 실패.
        # 그래서 재입력 회차에서는 앞의 두 칸부터 순서대로 다시 세운 뒤 Order를 넣는다.
        if refill_form_first:
            try:
                from selenium.webdriver.support.ui import Select
                # 2026-08-18: 예전엔 여기서 한 번 읽고 ''가 나오면 "Customer가 안 뜬
                # 원인이 이것일 수 있음"이라고 남겼는데, 그 줄이 8/11부터 계속된
                # 오진의 출처였다(멀쩡히 출고된 00598544/00598547/00598548에도 그대로
                # 찍혔다). 기다렸다 읽고, 그러고도 어긋날 때만 남긴다.
                cur_rule = _wait_field_value(driver, "Release Rule", release_rule)[0]
                cur_type = (Select(_field_by_label(driver, "Order Type"))
                            .first_selected_option.text or "").strip()
                if cur_rule != release_rule or cur_type != PICK_WAVE_ORDER_TYPE:
                    log(f"  {order_no}: 재입력 직전 폼이 어긋나 있음 - "
                        f"Release Rule={cur_rule!r}, Order Type={cur_type!r} "
                        f"(기대 {release_rule!r}/{PICK_WAVE_ORDER_TYPE!r}) - "
                        f"{RULE_VALUE_TIMEOUT_SEC}초를 기다려도 이 상태임")
            except Exception as e:
                # 상태를 못 읽는 건 진단 로그가 빠질 뿐이라 치명적이지 않다 -
                # 아래에서 어차피 통째로 다시 채운다.
                log(f"  {order_no}: 재입력 직전 폼 상태를 못 읽음"
                    f"({type(e).__name__}) - 그대로 다시 채움")
            _fill_rule_and_order_type(is_refill=True)
        _dismiss_stray_modal()
        order_el = _field_by_label(driver, "Order")
        order_el.click()
        order_el.clear()
        order_el.send_keys(order_no)
        time.sleep(1)
        driver.switch_to.active_element.send_keys("\t")
        # 탭아웃만으로는 조회가 늦게 걸릴 때가 있어 빈 화면을 한 번 눌러준다
        if not _click_blank_area(driver):
            log(f"  {order_no}: 빈 영역 클릭 지점을 못 찾음(탭아웃만으로 진행)")
        # Customer 자동완성 대기(오라클이 서버에서 주문 정보를 채워오는 백그라운드
        # 렌더링 구간) - 2026-07-15: 여기서도 같은 이유로 2초 -> 3초로 늘림.
        # 2026-08-07: 이 3초는 "팝업이 떴는지 판단할 수 있을 만큼"의 최소 대기로만
        # 남기고, 실제 Customer가 채워지는 건 아래 폴링으로 기다린다
        # (_wait_customer_value 주석 참고 - 고정 3초 뒤 한 번만 읽어서 생기던
        # 오탐 "Customer 미표시" + 불필요한 3분 대기를 없애기 위함).
        time.sleep(3)
        return _wait_customer_value(driver, _resolve_order_search_popup_if_any)

    def _fill_order_and_wait_customer(is_refill: bool = False) -> str:
        # 2026-08-07: Customer가 안 뜨면 곧바로 주문번호를 다시 입력해서 재시도한다
        # (CUSTOMER_ENTRY_ATTEMPTS 주석 참고 - 실측상 이 케이스의 해법은 '더 기다리기'가
        # 아니라 '다시 입력하기'였다). 3분 대기 경로는 이걸 다 해보고 나서야 간다.
        attempts = (CUSTOMER_ENTRY_ATTEMPTS_SKIPWAIT if skip_customer_wait
                    else CUSTOMER_ENTRY_ATTEMPTS)
        customer_val = ""
        for attempt in range(1, attempts + 1):
            # 1회차는 방금 _fill_rule_and_order_type을 거쳐온 직후라 폼이 살아 있다.
            # 2회차부터는 그 사이 PPR로 Release Rule/Order Type이 날아갔을 수 있으므로
            # 순서대로 다시 세우고 넣는다(_enter_order_and_read_customer 주석 참고).
            customer_val, waited = _enter_order_and_read_customer(
                refill_form_first=(attempt > 1))
            if customer_val and customer_val.strip():
                if waited >= 1.0:
                    # 폴링이 실제로 건져낸 케이스 - 예전의 '고정 3초 뒤 한 번 읽기'
                    # 였다면 미표시로 샜을 건이다. 이 줄이 로그에 얼마나 자주 찍히는지가
                    # 폴링 한도(CUSTOMER_FILL_TIMEOUT_SEC)를 조정할 근거가 된다.
                    log(f"  {order_no}: Customer가 {waited:.1f}초 만에 채워짐"
                        f"(입력 {attempt}회차) - 폴링으로 건짐")
                break
            if attempt < attempts:
                log(f"  {order_no}: Customer 미표시(입력 {attempt}/{attempts}회차, "
                    f"{waited:.0f}초 폴링) - 주문번호 다시 입력해서 재시도")

        customer_val = customer_val or ""
        if customer_val.strip():
            return customer_val

        if is_refill:
            # 2026-08-11: 폼 재입력 회차에서는 "뽑을 라인 없음" 확정도, 3분 대기도
            # 하지 않는다. 이 회차까지 온 건 **첫 회차에는 Customer가 떴는데**
            # Release Now 직전 검증에서 값이 어긋난 경우뿐이라, 주문이 오라클에
            # 살아있는 건 이미 확인된 상태다 - 그러니 여기서 안 뜨는 건 연동 지연이
            # 아니라 화면 상태 문제로 보는 게 맞다. CustomerNotShownError로 올리면
            # 상위가 이걸 '뽑을 라인 없음' 확정으로 받아 재시도 없이 사람 확인으로
            # 넘겨버려(조용한 미출고 위험) 기술적 오류로 올린다.
            raise RuntimeError(
                f"폼 재입력 후 Customer 미표시 - 첫 회차에는 채워졌던 주문이라 "
                f"화면 상태 문제로 보고 화면 새로 열어 재시도"
            )

        if skip_customer_wait:
            # 2026-07-23: 백오더 후속 SP(또는 2026-09-17부터: 이미 이전에 release된
            # 적이 있는 주문의 1차 룰)는 Customer 미표시가 곧 "뽑을 라인 없음"
            # 확정이라 결론이 이미 정해져 있음 - ServiceMax/Salesforce 연동 지연
            # 가능성을 고려할 필요가 없으므로(주문이 이미 오라클에 살아있는 게
            # 확인된 상태) 3분 대기 없이 즉시 확정한다.
            # 2026-09-17: 단, Release Rule 입력 자체가 화면에 도달 못 한 죽은
            # 세션이면(아래 3분대기 경로와 동일 판단) "뽑을 라인 없음"이 아니라
            # RuleInputDeadError로 올려 Edge 재시작을 유도해야 한다 - 안 그러면
            # 죽은 세션에 계속 새 요청을 붙여 매번 잘못된 "확정 완료"로 흘려버린다.
            if rule_state["dead"]:
                raise RuleInputDeadError(
                    f"주문 {order_no}: Release Rule 입력이 화면에 도달하지 못함 "
                    f"({RULE_FILL_ATTEMPTS}회 모두) - 세션이 키 입력을 안 받는 상태로 "
                    f"보고 Edge를 재시작해 재시도"
                )
            raise CustomerNotShownError(
                f"주문 {order_no}: Customer 미표시(즉시 확정) - 뽑을 라인 없음"
            )
        # 2026-07-09: Customer가 안 뜨는 경우 원인이 두 가지일 수 있음 -
        # (1) ServiceMax -> 오라클 주문 연동이 아직 안 끝난 경우(보통 몇 분 내 해소)
        # (2) 이미 다른 경로로 release가 끝나서 남은 라인이 없는 경우(연동 지연이
        #     아니라 "더 이상 할 게 없음" - 실제로 00592082/00592081이 이 경우였음,
        #     사용자가 이미 release된 건이라고 확인). 둘 다 겉보기 증상이 같아서
        #     코드에서 구분할 수 없으므로, 일단 3분 기다렸다가 한 번 더 시도하고
        #     (1)이면 이걸로 해소됨) 그래도 안 되면 실패로 남겨 사람이 확인하게
        # 한다((2)인 경우는 알림을 보고 사용자가 상태 파일에 완료로 기록해줘야 함).
        log(f"  {order_no}: Customer 미표시(입력 {attempts}회 + 재입력 모두 실패) - "
            f"3분 대기 후 재시도")
        time.sleep(180)
        # 3분 대기 동안 화면이 방치돼 폼이 더 확실하게 날아가 있을 수 있다 -
        # 여기서도 Release Rule -> Order Type -> Order 순서를 다시 세우고 넣는다.
        customer_val, _ = _enter_order_and_read_customer(refill_form_first=True)
        if not customer_val or not customer_val.strip():
            # 2026-08-24: 여기서 두 갈래로 나눈다.
            # (1) Release Rule 입력이 끝내 도달 못 한 회차 → 죽은 세션이다.
            #     "뽑을 라인 없음"으로 분류하면 상위가 재시도도 Edge 재시작도 없이
            #     사람 확인으로 넘겨버려, 다음 회차가 같은 죽은 Edge에 또 붙는다
            #     (00599358이 13:35/13:45/13:55 동일 증상 3연속 실패한 이유).
            # (2) 폼은 정상인데 Customer만 안 뜬 회차 → 예전 그대로 사람 확인.
            #     실제로 같은 날 00599329가 이 경우였다(rule 실패 로그도 캡쳐도 없음).
            # 08-18에도 비슷한 분기를 넣었다가 "빈 rule은 성공 건에서도 읽힌다"는
            # 이유로 되돌렸는데, 그때는 판단 근거가 '읽은 값'뿐이었다. 지금은
            # **입력 자체가 3회 다 도달 실패했다는 사실**을 근거로 쓰므로 다르다.
            if rule_state["dead"]:
                raise RuleInputDeadError(
                    f"주문 {order_no}: Release Rule 입력이 화면에 도달하지 못함 "
                    f"({RULE_FILL_ATTEMPTS}회 모두) - 세션이 키 입력을 안 받는 상태로 "
                    f"보고 Edge를 재시작해 재시도"
                )
            raise CustomerNotShownError(
                f"주문 {order_no}: Customer 미표시 - ServiceMax 연동 지연이거나 "
                f"이미 다른 경로로 release 완료돼 남은 라인이 없는 경우일 수 있음"
            )
        return customer_val

    # 2026-08-07: Release Now 직전 세 값을 확인한다. 이 확인이 없으면 값이 날아가도
    # 오류 없이 released_lines=0으로 조용히 끝나서 "뽑을 라인 없음"과 구별이 안 된다
    # (00597212 건에서 원인 파악이 오래 걸린 이유).
    # 2026-08-11: 어긋났을 때 예전에는 곧바로 예외로 올려 상위가 화면을 새로 열게
    # 했지만(회차당 40~60초), 이제 같은 화면에서 폼 전체를 한 번 더 채워보고
    # (rule -> Order Type -> Order 순서 그대로) 그래도 어긋날 때만 예외로 올린다.
    # 예전 주석의 "Release Rule을 다시 넣으면 Order가 리셋돼 엉뚱한 범위가 나갈 수
    # 있다"는 우려는 rule만 다시 넣는 경우의 얘기다 - 여기서는 리셋되는 Order까지
    # 그 뒤에 다시 채우고, 같은 검증을 통과해야만 Release Now로 넘어가므로 그
    # 위험이 없다(검증 없이 넘어가는 경로는 아래에도 없다).
    from selenium.webdriver.support.ui import Select
    expected = (release_rule, PICK_WAVE_ORDER_TYPE, order_no)
    customer_val = ""
    for fill_attempt in range(1, FORM_FILL_ATTEMPTS + 1):
        _fill_rule_and_order_type(is_refill=(fill_attempt > 1))
        customer_val = _fill_order_and_wait_customer(is_refill=(fill_attempt > 1))
        # 2026-08-18: 여기서도 한 번만 읽지 않고 기대값이 될 때까지 기다렸다 읽는다.
        # 이 검증은 8월에 7번 어긋남으로 걸렸는데(그때마다 폼 재입력 또는 화면
        # 재오픈으로 40~60초를 씀), 같은 읽기가 멀쩡한 값도 ''로 읽는다는 게
        # 8/18에 확인됐으므로 그 중 상당수가 헛걸음이었을 가능성이 크다
        # (RULE_VALUE_TIMEOUT_SEC 주석 참고). Order Type은 순수 <select>라
        # 서버 왕복이 끼지 않아 즉시 읽어도 된다.
        actual = (
            _wait_field_value(driver, "Release Rule", release_rule)[0],
            (Select(_field_by_label(driver, "Order Type")).first_selected_option.text or "").strip(),
            _wait_field_value(driver, "Order", order_no)[0],
        )
        if actual == expected:
            break
        if fill_attempt < FORM_FILL_ATTEMPTS:
            log(f"  {order_no}: Release Now 직전 입력값 어긋남 - 실제 {actual}, "
                f"기대 {expected} (폼 입력 {fill_attempt}/{FORM_FILL_ATTEMPTS}회차) - "
                f"화면은 그대로 두고 폼 전체를 다시 채워 재시도")
            continue
        raise RuntimeError(
            f"Release Now 직전 입력값 어긋남 - 실제 {actual}, 기대 {expected} "
            f"(폼을 {FORM_FILL_ATTEMPTS}회 채웠는데도 어긋남 - 화면 새로 열어 재시도)"
        )

    release_btns = [
        el for el in driver.find_elements(By.XPATH, "//*[normalize-space(text())='Release Now']")
        if el.is_displayed()
    ]
    if not release_btns:
        raise RuntimeError("Release Now 버튼을 못 찾음")
    release_btns[0].click()
    time.sleep(4)

    dialog_text = None
    for _ in range(15):
        if "released to warehouse" in driver.page_source:
            break
        time.sleep(1)
    m = re.search(r"Number of shipment lines released to warehouse:\s*(\d+)", driver.page_source)
    if not m:
        raise RuntimeError(
            f"Release 결과 확인 실패(확인 다이얼로그를 못 찾음) - rule={release_rule}, order={order_no}"
        )
    released = int(m.group(1))

    # 2026-07-14 사용자 요청: 같은 확인 다이얼로그에 백오더 라인 수도 같이 나옴.
    # DCD 건은 FG만 도는데, 여기서 백오더가 나오면(재고는 있는데 FG 룰로는 못 뺀
    # 라인이 있다는 뜻) SP 룰도 한 번 더 돌려야 해서 이 값을 같이 읽어둔다.
    # 정확한 오라클 문구를 아직 실측 확인 전이라, 못 찾으면 None으로 두고
    # (0으로 단정하지 않음) 다음에 실제로 백오더 뜬 사례가 나오면 문구를 확인해서
    # 정규식을 맞출 것 - 그 전까지는 호출부가 None을 "백오더 없음과 동일하게"
    # 취급해 SP를 추가로 돌리지 않는다(과도한 추가 조작 방지가 안전한 기본값).
    m_bo = re.search(r"Number of shipment lines backordered:\s*(\d+)", driver.page_source)
    backordered = int(m_bo.group(1)) if m_bo else None
    if backordered is None:
        log(f"  {order_no}: 백오더 문구를 다이얼로그에서 못 찾음(정규식 확인 필요) - rule={release_rule}")

    ok_btns = [el for el in driver.find_elements(By.TAG_NAME, "button")
               if el.is_displayed() and el.text.strip() == "OK"]
    if ok_btns:
        ok_btns[-1].click()
    time.sleep(1)

    return {"released_lines": released, "backordered_lines": backordered, "customer": customer_val}


# ==============================================================
# 3) Outlook 완료 답장 (성공 건에 한해 실제 발송)
# ==============================================================
# 완료 답장은 카테고리(DCD/소모품/불량프로모션) 구분 없이 수신자를 고정한다
# (원본 메일의 To/CC를 그대로 따르지 않음 - 2026-07-09).
PICK_RELEASE_REPLY_TO = "bohyunk@candelamedical.com; haejoonk@candelamedical.com"
PICK_RELEASE_REPLY_CC = (
    "김기훈 <y7221063@yongmalogis.co.kr>; 용호 유 <y7225055@yongmalogis.co.kr>"
)

# 2026-08-06 사용자 요청: "선출고" 건(물건은 용마에서 이미 나갔고 전산 릴리즈만
# 뒤늦게 처리하는 건 - 제목 예: "Fw: DCD 출고 요청의 건 (퓨린의원) - 선출고 택배
# 7/31 - 전산 처리 요청")의 완료 답장은 용마로지스 두 분(김기훈/유용호)에게만
# 보낸다. 보현 과장님/해준님은 이미 선출고를 진행·확인한 쪽이라 전산 처리 완료
# 통보를 다시 받을 필요가 없어 제외. 일반(선출고가 아닌) 건은 기존 수신자 유지.
PICK_RELEASE_REPLY_TO_PRESHIP = (
    "김기훈 <y7221063@yongmalogis.co.kr>; 용호 유 <y7225055@yongmalogis.co.kr>"
)
PRESHIP_SUBJECT_KEYWORD = "선출고"

# 메일 1건에 여러 병원(주문번호)이 표로 묶여 오는 카테고리. 이 카테고리는
# 전체가 다 성공했을 때만 완료 답장을 한 번 보내고, 라인 0건은 상태에 기록하지
# 않아 다음 실행에서 자동 재시도된다(_finalize_order_mail 참고).
BATCH_KINDS = ("불량/프로모션", "FIBER백오더")


def _prepend_html_text(reply, text: str):
    """reply.Body(plain text)에 직접 대입하면 Outlook이 답장 전체(원본 인용부 포함)를
    서식 없는 텍스트로 재생성해버려 원본 서식이 깨진다. HTMLBody의 <body> 태그
    바로 뒤에 텍스트만 끼워 넣어 원본 서식을 보존한다. 2026-07-23 사용자 보고로 수정
    (rma_auto_reply.py에서 같은 재생성 과정 중 장식용 이미지가 실제 첨부파일로
    튀어나오는 부작용도 확인된 바 있어, 혹시 남을 수 있는 그런 첨부도 아래서 제거한다)."""
    import html as html_module
    html_body = reply.HTMLBody or ""
    content_html = html_module.escape(text).replace("\n", "<br>")
    m = re.search(r"(<body[^>]*>)", html_body, re.IGNORECASE)
    wrapped = f'<div style="{MAIL_FONT_CSS}">{content_html}</div>'
    if m:
        insert_at = m.end()
        reply.HTMLBody = html_body[:insert_at] + wrapped + html_body[insert_at:]
    else:
        reply.HTMLBody = wrapped + html_body


def create_completion_reply(entry_id: str, kind: str = None):
    """릴리즈가 성공한 건에 대해서만 호출됨(호출부 참고) - "Release 완료됐습니다"
    답장을 실제로 발송한다. 2026-07-15부터: 사용자가 "무조건 성공한 것에
    대해서만 이 완료 답장은 자동 전송해달라"고 명시적으로 요청 - 그 전까지는
    Save()로 초안만 남겼음. 확인 필요/재로그인 필요 등 사람이 봐야 하는
    알림(send_alert)은 이 요청 대상이 아니므로 계속 초안만 저장한다."""
    import win32com.client
    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    mail = ns.GetItemFromID(entry_id)
    subject = str(mail.Subject or "")
    reply = mail.ReplyAll()
    # 카테고리(DCD/소모품/불량프로모션) 구분 없이 완료 답장은 항상 이 수신자로
    # 고정한다 - 원본 스레드에 딸려오는 다른 참조인은 다 뺀다.
    # 단, 선출고 건만 용마로지스 두 분에게만 발송(위 PICK_RELEASE_REPLY_TO_PRESHIP 주석 참고).
    if PRESHIP_SUBJECT_KEYWORD in subject:
        reply.To = PICK_RELEASE_REPLY_TO_PRESHIP
        reply.CC = ""
        greeting = "안녕하세요,\n\n선출고 건 전산 처리(Release) 완료됐습니다.\n\n"
    else:
        reply.To = PICK_RELEASE_REPLY_TO
        reply.CC = PICK_RELEASE_REPLY_CC
        greeting = "안녕하세요 보현 과장님,\n\nRelease 완료됐습니다.\n\n"
    reply.BCC = ""
    _prepend_html_text(reply, greeting)
    for idx in range(reply.Attachments.Count, 0, -1):
        try:
            reply.Attachments.Item(idx).Delete()
        except Exception:
            pass
    reply.Send()


# ==============================================================
# 4) 건별 처리 (한 메일에 주문번호가 여러 개일 수 있음 - 불량/프로모션은 보통 여러 병원이
#    한 메일에 묶여서 옴. DCD/소모품은 메일당 1건이라 order_nos 길이가 항상 1)
# ==============================================================
def _run_backorder_secondary(driver, order_no: str, label: str, secondary_rule: str) -> tuple:
    """백오더 감지로 추가 실행하는 2차 룰 콜(1차 룰은 이미 성공한 상태 -
    DCD/이노메드는 1차=FG/2차=SP, 소모품은 1차=SP/2차=FG. 2026-08-04에
    `_run_backorder_sp`를 룰 이름 파라미터화해서 일반화함, 로직 자체는 동일).
    2026-07-21 사용자 확인: Customer 미표시는 "2차 룰로 뽑을 라인이 없다"로
    확정 처리(정상, released_lines=0). 기술적 오류(네비게이션 실패/세션 끊김
    등)는 Customer 유무 자체를 확인 못 한 것뿐이라 한 번 재시도해보고, 재시도
    에서도 Customer 미표시가 나오면 마찬가지로 "뽑을 라인 없음" 확정으로 정상
    처리한다(기술적 오류 자체가 반복돼도 아니고, Customer 미표시로 명확히
    확인됐으므로). 재시도까지 기술적 오류로 끝나면(Customer 유무를 끝내 확인
    못 함) 그때만 released_lines=0으로 두고 사람 확인 알림이 필요함을 알리기
    위해 에러 메시지를 반환한다(호출부가 send_alert).
    반환: (2차 룰 결과 dict, 확인 필요 에러 메시지|None)
    2026-07-23: Customer 미표시 결론이 어차피 정해져 있으므로(뽑을 라인 없음
    확정) 3분 대기 없이 즉시 확정하도록 skip_customer_wait=True로 호출한다
    - 사용자 지적: 한 번에 안 뜨면 바로 확정하면 되는데 3분씩 기다릴 필요가
    없었음."""
    for attempt in range(2):
        try:
            r2 = create_and_release_pick_wave(
                driver, secondary_rule, order_no, skip_customer_wait=True
            )
            log(f"  {label} {secondary_rule}(백오더 대응): "
                f"released_lines={r2['released_lines']} customer={r2['customer']}")
            return r2, None
        except CustomerNotShownError:
            log(f"  {label} {secondary_rule}(백오더 대응): Customer 미표시 "
                f"-> {secondary_rule}로 뽑을 라인 없음(정상, 1차 성공분으로 완료 처리)")
            return {"released_lines": 0, "backordered_lines": None, "customer": None}, None
        except Exception as e2:
            if attempt == 0:
                log(f"  {label} {secondary_rule}(백오더 대응) 기술적 오류: "
                    f"{e2} - 1회 재시도")
                time.sleep(5)
                continue
            log(f"  {label} {secondary_rule}(백오더 대응) 재시도도 기술적 오류로 "
                f"실패: {e2} -> 1차 성공분으로 완료 처리하되 확인 필요 알림 발송")
            return {"released_lines": 0, "backordered_lines": None, "customer": None}, str(e2)


# ==============================================================
# 오라클 화면 조작 공통 재시도 (2026-08-05 추가)
# ==============================================================
# 2026-08-05 사용자 요청: 오라클 화면 진입 실패(예: Tasks 아이콘 미발견 -
# "no such element: //img[@title='Tasks']")처럼 일시적인 네비게이션/세션 오류로
# 한 건이 통째로 실패하면, 예전에는 그대로 실패로 두고 다음 예약 실행(20~40분
# 뒤)에서야 재시도됐다. 실측(2026-08-05 18:00 회차): SSO 재로그인 직후 같은
# 오류가 8번 났는데 자체 재시도 레이어가 있던 경로(_run_backorder_secondary)는
# 살아남고, 없던 1차 시도 경로는 그대로 실패(00595662)했다 - 같은 실행 안에서
# 짧게 쉬었다 다시 시도해 스스로 완료하게 한다.
# 2026-08-24: Edge 강제 재시작 쿨다운.
# _force_restart_edge()는 자동화 프로필 Edge를 **전부** 죽이므로, 같은 Edge를 공유하는
# 다른 자동화(icbl/ship_confirm/sco_cancel/rebalance)의 진행 중 세션까지 같이 끊는다.
# 실제로 8/24 14:14:43에 pick_release가 처리 중이던 00599329가 남이 띄운 재시작에
# 말려 NoSuchWindowException으로 죽었다. 여기에 우리까지 무제한으로 재시작을 걸면
# "서로 죽이는" 재시작 폭풍이 된다 - Release Rule 미도달은 회차마다 반복되는
# 증상이라 특히 위험하다. 그래서 프로세스를 넘어 유지되는 타임스탬프로 간격을 강제한다.
EDGE_RESTART_COOLDOWN_SEC = 900   # 15분
EDGE_RESTART_STAMP = os.path.join(ROOT, "_edge_restart_stamp.json")


def _try_force_restart_edge(label: str) -> bool:
    """쿨다운을 지켜서만 Edge를 강제 재시작한다. 실제로 재시작했으면 True.
    스탬프 파일을 못 읽거나 못 쓰는 건 재시작을 막을 이유가 아니므로 조용히 넘어간다
    (다만 못 쓰면 다음 회차가 쿨다운을 모르게 되므로 쓰기 실패는 로그로 남긴다)."""
    now = time.time()
    try:
        with open(EDGE_RESTART_STAMP, encoding="utf-8") as f:
            last = float(json.load(f).get("last_restart", 0))
    except Exception:
        last = 0.0
    waited = now - last
    if waited < EDGE_RESTART_COOLDOWN_SEC:
        log(f"  [재시도] {label}: Edge 재시작이 필요하지만 마지막 재시작 후 "
            f"{waited / 60:.1f}분밖에 안 지나 건너뜀"
            f"(쿨다운 {EDGE_RESTART_COOLDOWN_SEC // 60}분 - 다른 자동화 세션을 "
            f"연달아 끊지 않기 위함)")
        return False
    _force_restart_edge()
    try:
        with open(EDGE_RESTART_STAMP, "w", encoding="utf-8") as f:
            json.dump({"last_restart": now,
                       "by": label,
                       "at": time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False)
    except Exception as e:
        log(f"  [재시도] {label}: Edge 재시작 시각 기록 실패({e}) - "
            f"다음 회차가 쿨다운을 모를 수 있음")
    return True


ORACLE_RETRY_ATTEMPTS = 3        # 최초 1회 + 재시도 2회
ORACLE_RETRY_WAIT_SEC = (5, 15)  # 재시도 전 대기(점증)


def run_with_oracle_retry(label: str, fn, *, attempts: int = ORACLE_RETRY_ATTEMPTS,
                          no_retry_exceptions: tuple = (), before_retry=None,
                          should_retry=None):
    """fn()을 실행하다 일시적 오류가 나면 잠깐 쉬었다 다시 시도한다.
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
            # 해봐야 결과가 100% 같다(실측 로그: 00594693이 5초 간격으로 똑같은
            # invalid session id를 3번 남기고 실패) - is_session_dead_error 참고.
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
            log(f"  [재시도] {label}: 오라클 처리 실패({type(e).__name__}) - "
                f"{wait}초 후 {attempt + 2}/{attempts}번째 시도")
            time.sleep(wait)
            if before_retry is not None:
                try:
                    before_retry()
                except Exception as e2:
                    log(f"  [재시도] {label}: 재시도 전 화면 복구 실패(무시하고 진행): {e2}")
    raise last_exc


def _process_single_order(kind: str, order_no: str, rules: list, state: dict) -> tuple:
    """_process_single_order_once를 감싸 일시적 오라클 오류를 같은 실행 안에서
    재시도한다(2026-08-05 추가).

    중복 출고 방지 안전장치: 이미 released_lines>0인 결과가 하나라도 있으면
    (=일부라도 실제로 출고가 나갔으면) 재시도하지 않는다. 실제로 이 경로로
    예외가 새어나오는 건 룰 실행 자체가 시작도 못 한 경우뿐이고(1차 룰이
    성공한 뒤의 2차 룰 실패는 _run_backorder_secondary가 예외 대신 err를
    돌려주므로 여기까지 오지 않는다), 1차 성공분은 _save_partial_fg_success로
    디스크에도 남아 재시도 시 건너뛴다.

    Customer 미표시(CustomerNotShownError)는 화면 진입에는 성공했고 안에서
    이미 대기+재시도를 거쳐 "뽑을 라인 없음"으로 확인된 결론이라 재시도 대상이
    아니다 - 그대로 사람 확인으로 넘긴다."""
    label = f"{kind} {order_no}"
    result = None
    for attempt in range(ORACLE_RETRY_ATTEMPTS):
        result = _process_single_order_once(kind, order_no, rules, state)
        info = result[1]
        if not info["error"]:
            return result
        if info.get("error_kind") == "customer_not_shown":
            return result
        if any(res.get("released_lines", 0) > 0 for _, res in info["results"]):
            log(f"  [재시도] {label}: 이미 출고된 라인이 있어 재시도하지 않음(사람 확인 필요)")
            return result
        if attempt == ORACLE_RETRY_ATTEMPTS - 1:
            break
        wait = ORACLE_RETRY_WAIT_SEC[min(attempt, len(ORACLE_RETRY_WAIT_SEC) - 1)]
        log(f"  [재시도] {label}: 오라클 처리 실패 - {wait}초 후 새 탭으로 "
            f"{attempt + 2}/{ORACLE_RETRY_ATTEMPTS}번째 시도")
        time.sleep(wait)
        # 2026-08-06: 이 재시도는 _process_single_order_once가 매번
        # get_oracle_driver_isolated()로 '새 드라이버'를 받으므로, 세션이 끊긴
        # 경우에도 실제로 복구가 가능한 경로다. 다만 Edge 프로세스 자체가 죽어
        # 있으면 새 드라이버를 받는 것부터 실패하므로, 여기서 Edge 생존을 먼저
        # 확인해준다(포트가 열려 있으면 아무것도 하지 않는 가벼운 확인이고,
        # 죽어 있을 때만 다시 띄운다. 워커가 동시에 불러도 안전하도록
        # ensure_edge_running 안에서 락으로 한 번만 띄운다).
        if info.get("error_kind") == "rule_input_dead":
            # 2026-08-24: 이 증상은 Edge 세션 전체가 키 입력을 안 받는 상태라
            # (RuleInputDeadError 주석) 새 탭/새 드라이버로는 절대 안 풀린다 -
            # 프로세스를 껐다 켜야 창 가림 방지 실행 옵션이 다시 걸린다.
            # _force_restart_edge는 자동화 프로필 Edge만 죽이므로 개인 Edge는 안전하다.
            log(f"  [재시도] {label}: Release Rule 입력 미도달 - Edge 재시작 시도")
            try:
                _try_force_restart_edge(label)
            except Exception as e2:
                log(f"  [재시도] {label}: Edge 재시작 실패(그냥 재시도함): {e2}")
        else:
            try:
                ensure_edge_running()
            except Exception as e2:
                log(f"  [재시도] {label}: Edge 생존 확인 실패(무시하고 진행): {e2}")
    log(f"  [재시도] {label}: {ORACLE_RETRY_ATTEMPTS}회 모두 실패 - 사람 확인 알림으로 넘김")
    return result


def _process_single_order_once(kind: str, order_no: str, rules: list, state: dict) -> tuple:
    """주문 1건을 처리. 자기 전용 탭을 직접 열고 끝나면 닫는다 - 병렬 실행 시
    스레드마다 독립된 driver 인스턴스/탭을 갖게 하기 위함(다른 스레드와 DOM/
    ViewState를 공유하지 않음).
    2026-07-14 사용자 요청: DCD 건(rules=[FG]만)은 원래 FG 한 번만 도는데, FG
    결과에 백오더가 있으면(재고는 있는데 FG 룰로는 못 뺀 라인이 있다는 뜻) SP
    룰도 추가로 한 번 돌린다. 2026-07-24부터 이노메드도 같은 방식(FG만 먼저,
    백오더 있을 때만 SP 추가) 적용. 2026-08-04부터 소모품도 같은 조건부 방식에
    합류하되 1차/2차가 반대(SP 먼저, 백오더 있을 때만 FG 추가) - 사용자 요청
    ("소모품은 SP부터 하고 백오더 있으면 FG도 돌려라")으로 기존 "무조건 FG+SP
    둘 다" 방식에서 변경. 이 세 kind는 `PRIMARY_SECONDARY_RULES`에 (1차, 2차)
    룰로 정의돼 있고, 불량/프로모션만 이 대상에서 제외(항상 FG 1회, 조건부
    추가 없음).
    2026-07-23: FG가 이전 실행에서 이미 성공했다는 기록(`_partial_fg_backorder`,
    _save_partial_fg_success 참고)이 있으면 FG를 다시 돌리지 않고 그 결과를
    그대로 써서 SP부터 이어서 처리한다 - 프로세스가 SP 도중 죽어도 FG 성공을
    잃지 않기 위함.
    2026-07-23 실측(00594693): 이 함수는 ThreadPoolExecutor 워커 스레드에서
    실행되는데, 그 안에서 SP 기술적 오류 시 send_alert()(win32com으로 Outlook
    COM 호출)를 부르면 "CoInitialize has not been called" 오류가 남 - 메인
    스레드는 COM이 암묵적으로 초기화돼 있지만 새로 만든 스레드는 그렇지 않기
    때문. 이 오류가 그대로 밖으로 퍼져 이미 성공한 FG 결과까지 이 실행에서는
    또 "실패"로 처리됨(다행히 _save_partial_fg_success로 디스크에는 이미
    남아있어서 다음 실행이 이어서 처리함, 완전히 잃지는 않았음) - 근본 원인인
    COM 미초기화 자체를 여기서 고친다."""
    import pythoncom
    pythoncom.CoInitialize()
    label = f"{kind} {order_no}"
    order_results = []
    driver = None
    try:
        driver = get_oracle_driver_isolated()

        primary_rule, secondary_rule = PRIMARY_SECONDARY_RULES.get(kind, (None, None))

        resumed = state.get("_partial_fg_backorder", {}).get(order_no)
        if primary_rule and resumed:
            log(f"  {label}: 이전 실행에서 {primary_rule} 성공 기록 발견(released_lines="
                f"{resumed['released_lines']}, {resumed['recorded_at']}) - "
                f"{primary_rule} 재실행 없이 {secondary_rule}부터 이어서 처리")
            r = {
                "released_lines": resumed["released_lines"],
                "backordered_lines": resumed["backordered_lines"],
                "customer": resumed["customer"],
            }
            order_results.append((primary_rule, r))
            if (r.get("backordered_lines") or 0) > 0:
                r2, err2 = _run_backorder_secondary(driver, order_no, label, secondary_rule)
                order_results.append((secondary_rule, r2))
                if err2:
                    send_alert(
                        f"[Pick Release {secondary_rule} 확인 필요] {label}",
                        f"{label} 주문은 {primary_rule}로 released_lines={r['released_lines']}건 성공했고, "
                        f"백오더 {r['backordered_lines']}건이 있어 {secondary_rule}를 추가 실행했으나(1회 재시도 포함) "
                        f"기술적 오류로 끝까지 확인하지 못했습니다: {err2}\n\n"
                        f"{primary_rule} 성공분으로 완료 처리(답장 발송)는 진행되지만, {secondary_rule}에 실제로 남은 "
                        f"백오더가 있었는지는 오라클에서 직접 한 번 확인해주세요."
                    )
            _clear_partial_fg_success(state, order_no)
            return order_no, {"results": order_results, "error": None}

        # 2026-09-17 사용자 확인: Release Rule/Order Type/Order 세 값이 다 제대로
        # 들어갔는데 Customer가 안 뜨는 원인은 딱 두 가지뿐이다 - (1) 이 주문이
        # 예전에 이미 한 번 release된 적이 있는 경우(그러면 ServiceMax/Salesforce
        # 연동 지연일 수가 없다 - 이미 한 번 오라클에 살아있는 게 확인된 주문이므로,
        # Customer 미표시는 "뽑을 라인이 더 없다"는 확정 신호다), (2) 이 주문의
        # 첫 release 시도인 경우(그러면 Salesforce->오라클 연동이 아직 안 끝났을
        # 가능성이 실제로 있어 여전히 애매하다 - 기존처럼 3분 대기 후 재확인 필요).
        # `state`에 이미 이 주문 기록이 있으면 (1)로 간주해 **1차 룰부터** 즉시
        # 확정 처리한다(전에는 1차 룰 첫 시도는 항상 애매한 3분대기 경로만 탔음 -
        # 처리완료 오더번호를 "백오더" 후속으로 강제 재처리하는 경로에서, 이미 다
        # 끝난 주문에 대해서도 매번 "확인 필요" 알림이 잘못 나가던 문제의 근본
        # 원인이었다. 00602410/00602411이 12:20 회차에서 실제로 이렇게 오탐됨).
        already_released_before = state_key(kind, order_no) in state
        for rule in rules:
            already_succeeded = already_released_before or any(
                res["released_lines"] > 0 for _, res in order_results)
            try:
                r = create_and_release_pick_wave(driver, rule, order_no, skip_customer_wait=already_succeeded)
            except CustomerNotShownError:
                if not already_succeeded:
                    raise
                if any(res["released_lines"] > 0 for _, res in order_results):
                    log(f"  {label} {rule}: Customer 미표시 -> 이미 다른 룰에서 성공(주문 "
                        f"확인됨) - 이 룰은 뽑을 라인 없음(정상)으로 처리")
                else:
                    log(f"  {label} {rule}: Customer 미표시 -> 이 주문은 이전에 이미 "
                        f"release된 적이 있음(state 기록 존재) - 뽑을 라인 없음(정상)으로 처리")
                r = {"released_lines": 0, "backordered_lines": None, "customer": None}
            order_results.append((rule, r))
            log(f"  {label} {rule}: released_lines={r['released_lines']} "
                f"backordered_lines={r.get('backordered_lines')} customer={r['customer']}")

            if (rule == primary_rule and (r.get("backordered_lines") or 0) > 0):
                # 2차 룰을 시도하기 전에, 방금 성공한 1차 룰 결과를 먼저 디스크에
                # 남긴다 - 이 아래 2차 룰 실행 중 프로세스가 죽어도 다음 실행이
                # 이 기록을 보고 1차 룰을 건너뛸 수 있게(2026-07-23, 2026-08-04에
                # 소모품 SP->FG 순서까지 일반화).
                _save_partial_fg_success(state, order_no, r)
                log(f"  {label}: 백오더 {r['backordered_lines']}건 감지 -> "
                    f"{secondary_rule} 추가 실행")
                r2, err2 = _run_backorder_secondary(driver, order_no, label, secondary_rule)
                order_results.append((secondary_rule, r2))
                if err2:
                    send_alert(
                        f"[Pick Release {secondary_rule} 확인 필요] {label}",
                        f"{label} 주문은 {primary_rule}로 released_lines={r['released_lines']}건 성공했고, "
                        f"백오더 {r['backordered_lines']}건이 있어 {secondary_rule}를 추가 실행했으나(1회 재시도 포함) "
                        f"기술적 오류로 끝까지 확인하지 못했습니다: {err2}\n\n"
                        f"{primary_rule} 성공분으로 완료 처리(답장 발송)는 진행되지만, {secondary_rule}에 실제로 남은 "
                        f"백오더가 있었는지는 오라클에서 직접 한 번 확인해주세요."
                    )
                _clear_partial_fg_success(state, order_no)
        return order_no, {"results": order_results, "error": None,
                          "already_released_before": already_released_before}
    except RuleInputDeadError as e:
        # 2026-08-24: 죽은 세션이라 같은 Edge에서 새 탭을 열어봐야 소용없다 -
        # 별도 error_kind로 올려 _process_single_order가 Edge를 재시작하게 한다.
        log(f"[에러] {label} 처리 실패(Release Rule 입력 미도달): {exc_detail(e)}")
        return order_no, {"results": order_results, "error": str(e),
                          "error_kind": "rule_input_dead"}
    except CustomerNotShownError as e:
        # 화면 진입 자체는 성공했고 안에서 대기+재시도까지 거친 "뽑을 라인 없음"
        # 확정 결론이라 재시도해도 결과가 같다 - error_kind로 표시해 위 재시도
        # 래퍼가 그냥 사람 확인으로 넘기게 한다(2026-08-05).
        log(f"[에러] {label} 처리 실패(Customer 미표시): {exc_detail(e)}")
        return order_no, {"results": order_results,
                          "error": str(e) or "Customer 미표시",
                          "error_kind": "customer_not_shown"}
    except Exception as e:
        log(f"[에러] {label} 처리 실패: {exc_detail(e)}")
        return order_no, {"results": order_results, "error": str(e),
                          "error_kind": "technical"}
    finally:
        # 주문 1건마다 드라이버를 새로 만드므로(재시도 최대 3회 x 워커 2개) 여기서
        # 프로세스까지 정리하지 않으면 msedgedriver.exe가 회차마다 쌓인다
        # (close()는 탭만 닫는다 - close_driver 설명 참고, 2026-08-06).
        close_driver(driver)


def _build_order_entry(kind: str, subject: str, info: dict) -> dict:
    """상태파일에 남길 주문 1건의 기록. 즉시 저장(_save_completed_order_now)과
    메일 마무리(_finalize_order_mail) 두 곳에서 같은 모양을 써야 하므로 한 군데로
    모아둔다(따로 만들면 나중에 한쪽만 고쳐져 어긋난다)."""
    return {
        "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind,
        "subject": subject,
        "results": [{"rule": rule, "released_lines": res["released_lines"]}
                    for rule, res in info["results"]],
        "error": info["error"],
    }


def _save_completed_order_now(m: dict, order_no: str, info: dict, state: dict) -> None:
    """주문 1건이 **실제로 출고된 즉시** 상태파일에 기록한다(2026-08-07 추가).

    왜 필요한가 - 2026-08-07 실측 사고: 원래는 상태 저장이 `_finalize_order_mail`
    한 곳에만 있어서, 한 메일의 주문이 **전부** 끝나야 디스크에 남았다. 그런데
    불량/프로모션 38건 배치를 돌던 12:21 회차가 12:43에 원인불명으로 죽으면서,
    **이미 오라클에서 release가 끝난 15건이 상태파일에 하나도 안 남았다**
    (_processed_orders.json이 전날 것 그대로였음). 그대로 뒀으면 다음 실행이
    38건을 처음부터 다시 시도 -> 이미 나간 15건은 남은 라인이 없어 전부 Customer
    미표시 실패 -> 메일이 영영 완료되지 않는 무한 재시도(과거 00594053/00594646와
    같은 함정). 로그를 뒤져 수동 복구했지만 같은 날 세 번이나 반복됐다.
    배치가 30분 넘게 걸리는 이상 "다 끝나야 저장"은 그 시간 내내 유실 위험을
    안고 가는 구조라, 성공한 건은 그 자리에서 바로 남긴다.

    **답장 조건은 건드리지 않는다(사용자 요구: 모든 건이 다 완료돼야 답장).**
    답장은 여전히 `_finalize_order_mail`에서만 보내고, 조건도 그대로
    "all_order_nos가 전부 state에 있을 때" 하나뿐이다. 이 함수는 저장 '시점'만
    앞당길 뿐 저장 '대상'을 넓히지 않는다 - `_finalize_order_mail`의 succeeded
    분기와 똑같이 **에러 없고 released_lines 합계가 1 이상인 건만** 남긴다
    (라인 0건/실패 건은 여기서 절대 안 건드림 - 불량/프로모션의 0건은 다음
    실행에서 재시도돼야 하므로 기록하면 안 된다).

    또한 `_finalize_order_mail`은 메일의 이번 회차 주문이 **전부** 끝난 뒤에만
    호출되므로, 여기서 미리 저장한다고 답장이 일찍 나갈 수는 없다.
    """
    if info.get("error"):
        return
    if sum(r["released_lines"] for _, r in info["results"]) <= 0:
        return
    key = state_key(m["kind"], order_no)
    if key in state:
        return
    state[key] = _build_order_entry(m["kind"], m["subject"], info)
    save_state(state)


def _finalize_order_mail(m: dict, per_order: dict, state: dict) -> None:
    """process_order_mails가 이 메일의 주문을 전부 처리한 뒤 호출 - 완료 집계/
    상태 저장/답장/알림. 2026-07-14: 원래 process_order_mail 안에 있던 로직을
    메일 간 병렬 처리 리팩터하며 분리(주문 실행은 process_order_mails가 담당)."""
    order_nos = m["order_nos"]
    all_order_nos = m.get("all_order_nos", order_nos)
    kind = m["kind"]

    # 불량/프로모션은 메일 1건에 여러 병원(주문)이 묶여 있고, 답장은 그 메일에 있던
    # 전체 건이 다 성공했을 때 한 번만 보내야 함(25건 중 20건만 됐는데 "완료"라고
    # 보내면 보현 과장님/용마 쪽이 오해함). 그래서 라인 0건도 DCD/소모품과 달리
    # 상태에 기록하지 않고 계속 재시도해서 결국 전부 성공하도록 한다.
    # FIBER 백오더도 같은 모양(실측 23개 병원이 한 표에 묶여 옴)이라 같이 묶는다
    # (2026-08-19) - 게다가 이 카테고리는 애초에 백오더 건이라 지금 라인이 안
    # 나오면 재고가 더 들어온 뒤 저절로 완료되는 게 맞다.
    is_batch = kind in BATCH_KINDS

    succeeded, zero_line, failed = [], [], []
    confirmed_done = []  # 2026-09-17: 이미 이전에 release된 주문을 "백오더" 후속으로
    # 재확인했더니 진짜로 더 뽑을 라인이 없어 확정된 경우 - 알림 대상 아님(아래 참고)
    for order_no in order_nos:
        info = per_order.get(order_no, {"results": [], "error": "처리 안 됨(내부 오류)"})
        total = sum(r["released_lines"] for _, r in info["results"])
        entry = _build_order_entry(kind, m["subject"], info)
        key = state_key(kind, order_no)
        if info["error"]:
            failed.append(order_no)
        elif total > 0:
            succeeded.append(order_no)
            # 2026-08-07: 성공 건은 보통 _save_completed_order_now가 출고 직후
            # 이미 남겨뒀다 - 그 경우 실제 완료 시각을 보존하려고 덮어쓰지 않는다
            # (집계/답장 판정에는 영향 없음, state에 있기만 하면 됨).
            if key not in state:
                state[key] = entry
        elif info.get("already_released_before"):
            # 2026-09-17: Customer 미표시가 "이 주문은 이전에 이미 release된 적이
            # 있어 더 뽑을 라인이 없다"는 확정 신호였던 경우(스레드가 "백오더" 후속
            # 메일이라 재확인했을 뿐) - ServiceMax 지연 같은 애매함이 아니라 결론이
            # 이미 난 것이므로 "확인 필요" 알림 대상에서 뺀다. 안 그러면 이미 완료
            # 답장까지 나간 주문에 대해 재확인할 때마다 매번 헷갈리는 "확인 필요"
            # 알림이 또 생긴다(00602189 - 10:04에 완료 답장 나갔는데 10:20 재확인
            # 회차가 또 "확인 필요" 알림을 만든 사례로 발견).
            confirmed_done.append(order_no)
            if not is_batch and key not in state:
                state[key] = entry
        else:
            zero_line.append(order_no)
            # 2026-09-17: 성공 분기와 같은 이유로 이미 state에 있으면 덮어쓰지
            # 않는다 - 이전에 실제 release된 기록(note 등)이 있는 주문을 "백오더"
            # 후속으로 강제 재처리했는데 이번엔 확정 0건(뽑을 라인 없음)으로
            # 끝난 경우, 예전 기록을 빈 0건 결과로 지워버리면 안 되므로.
            if not is_batch and key not in state:
                state[key] = entry  # DCD/소모품: 0건은 재시도 안 하고 사람이 확인
            # 불량/프로모션·FIBER는 상태에 기록하지 않음 -> 다음 실행에서 자동 재시도
    if confirmed_done:
        log(f"  {kind} 이미 완료된 주문 재확인(추가 조치 불필요): {confirmed_done} ({m['subject']})")
    save_state(state)

    # 2026-09-18 발견: DCD/소모품은 "메일당 주문 1건"을 전제로 `elif succeeded:`가
    # 하나라도 성공하면 바로 완료 답장을 보냈는데, 보현 과장님이 번호 매긴 목록으로
    # 여러 병원(오더번호)을 한 메일에 담는 경우가 실제로 있다("추가 불량건 택배
    # 발송 9/18" - "불량 및 프로모션"이라는 정확한 문구가 없어 소모품 catch-all로
    # 분류됐지만, 본문 findall은 kind와 무관하게 6개 오더번호를 다 뽑는다). 이런
    # 메일은 6건 중 5건만 성공해도 `succeeded`가 비어있지 않아 **아직 안 끝난
    # 6번째 건이 있는데도 "Release 완료됐습니다" 답장이 나가버렸다**(00603889가
    # 그 6번째 건 - 다행히 사용자가 오라클에서 직접 확인해 실제로는 이미 release돼
    # 있었지만, 진짜 미완료 건이었다면 잘못된 완료 통보였을 것). is_batch 여부와
    # 무관하게 **all_order_nos 전부가 실제로 성공(0건 확정이 아니라 진짜
    # released_lines>0 또는 수동 확인 note)했을 때만** 답장을 보내도록 통일한다.
    def _order_confirmed_released(o):
        e = state.get(state_key(kind, o))
        if not e:
            return False
        if e.get("note"):
            return True  # 수동으로 완료 확인해 기록한 건(note 기반) - 완료로 신뢰
        return sum((r.get("released_lines") or 0) for r in e.get("results", [])) > 0

    done_count = sum(1 for o in all_order_nos if _order_confirmed_released(o))
    if done_count == len(all_order_nos):
        try:
            create_completion_reply(m["entry_id"], kind=kind)
            log(f"전체 완료({done_count}/{len(all_order_nos)}건) 및 완료 답장 발송: {kind} ({m['subject']})")
        except Exception as e:
            log(f"[경고] 완료 답장 발송 실패 ({kind}, {m['subject']}): {e}")
    else:
        log(
            f"{kind} 진행중: {done_count}/{len(all_order_nos)}건 완료 - "
            f"전체 완료 전까지 답장 보류 ({m['subject']})"
        )

    if zero_line or failed:
        log(f"[경고] {kind} 일부 확인 필요 - 라인0건: {zero_line}, 실패: {failed} ({m['subject']})")
        note = (
            "- 라인 0건 건은 재시도됩니다(불량/프로모션·FIBER 백오더는 원인 해소 시 "
            "자동 완료, DCD/소모품은 상태에 기록되어 재시도되지 않으니 수동 확인 필요).\n"
            if is_batch else
            "- 라인 0건 건은 상태에 기록해 재알림하지 않습니다(수동 확인 후 필요시 직접 처리해주세요).\n"
        )
        # 2026-08-24: 같은 조합이 반복되는 동안은 첫 통만 보낸다
        # (_should_send_repeat_alert 주석 - 미연동 건이 몇 시간씩 이어지면
        # 5~10분마다 같은 초안이 쌓여 정작 봐야 할 알림이 묻힌다).
        alert_key = "|".join([
            kind,
            m["subject"],
            ",".join(sorted(str(x) for x in zero_line)),
            ",".join(sorted(str(x) for x in failed)),
        ])
        if not _should_send_repeat_alert(alert_key):
            log(f"  같은 내용의 확인 필요 알림을 최근에 보냈으므로 이번 초안은 생략"
                f"(쿨다운 {ALERT_REPEAT_COOLDOWN_SEC // 3600}시간, 실패 조합이 바뀌면 즉시 재알림)")
        else:
            send_alert(
                f"[Pick Release 확인 필요] {kind} ({m['subject']})",
                f"성공: {succeeded}\n라인 0건(수동 확인 필요): {zero_line}\n에러로 실패: {failed}\n"
                f"메일 제목: {m['subject']}\n"
                f"{note}"
                f"- 에러로 실패한 건은 상태에 기록하지 않아 다음 실행 때 자동 재시도됩니다.\n"
                f"- Customer 미표시가 계속되면 대개 **Salesforce -> 오라클 미연동**입니다"
                f"(오더가 아직 오라클에 안 넘어온 상태). 연동되면 자동으로 처리됩니다.\n"
                f"- 같은 내용의 알림은 {ALERT_REPEAT_COOLDOWN_SEC // 3600}시간에 한 번만 보냅니다."
            )


def process_order_mails(new_mails: list, state: dict) -> None:
    """2026-07-14 사용자 요청: 메일 여러 통에 걸친 주문들을 하나의 풀에 모아
    동시에 최대 MAX_PARALLEL_ORDERS개까지 처리한다. 예전엔 메일 단위로 순차
    처리하면서 그 메일 "안에서만" 최대 3개씩 병렬화했는데, 실측 결과 최근
    메일들이 대부분 주문 1건짜리라 3슬롯 중 2개가 노는 채로 메일을 하나씩
    순서대로 처리하고 있었음(사용자 지적) - `_process_single_order`는 애초에
    주문 단위로 완전히 독립적(자기 탭을 직접 열고 닫음, 어느 메일 소속인지
    모름)이라 메일 경계를 없애고 전체 주문을 한 풀에 넣어도 안전함(메일별
    탭 같은 걸 새로 만들 필요가 없음). 완료 집계/답장/알림은 여전히 메일
    단위(_finalize_order_mail)이고, 한 메일의 주문이 전부 끝나는 즉시 그
    메일만 먼저 마무리한다(다른 메일의 더 큰 배치가 끝날 때까지 기다리지 않음)."""
    total_orders = sum(len(m["order_nos"]) for m in new_mails)
    n_workers = min(MAX_PARALLEL_ORDERS, total_orders)
    log(f"신규 메일 {len(new_mails)}건, 총 주문 {total_orders}건 발견 - 동시 {n_workers}건 처리")

    # icbl_ci_watcher.py와 같은 Edge 인스턴스(프로필/로그인 세션)를 공유하지만,
    # 탭은 매번 새로 연다(2026-07-13, 겹침 감지 로직 자체를 없애 단순화).
    # 로그인 세션 확인/재로그인은 병렬 처리를 시작하기 전에 탭 하나로 딱 한 번만
    # 한다 - 여러 탭이 동시에 SSO 재로그인 버튼을 누르려다 꼬일 수 있어서다.
    check_driver = None
    try:
        ensure_edge_running()
        check_driver = get_oracle_driver_isolated()
        # 2026-08-06(2차): 복구 순서를 recover_oracle_login()의 사다리로 통일
        # (SSO -> URL 재진입 -> Edge 재시작 -> 실패). 예전에는 SSO가 실패하면
        # 바로 Edge를 강제 재시작했는데, 실측 결과 재시작은 콜드 부팅이라 로그인
        # 페이지 렌더가 더 느려져 오히려 실패 확률을 높였고, 반대로 URL 재진입
        # 만으로 풀리는 경우가 확인됐다. 재로그인 성공 후의 대기(5초, 홈 렌더
        # 대기)도 사다리 안에서 그대로 한다. 실패 시 흐름(OracleLoginRequired ->
        # 알림 -> 회차 스킵)은 예전과 완전히 동일하다.
        ok, check_driver = recover_oracle_login(check_driver, log)
        if not ok:
            raise OracleLoginRequired("오라클 Fusion 세션이 끊김(자동 복구 1~3단계 모두 실패)")
    except OracleLoginRequired:
        log(f"[경고] 오라클 로그인 세션 끊김 -> 사람이 재로그인 필요, 이번 회차 메일 {len(new_mails)}건 전체 스킵")
        send_alert(
            "[오라클 재로그인 필요] Pick Release 전체",
            "오라클 Fusion 세션이 끊겨서 자동 처리를 못했습니다. Edge에서 한 번 로그인해주세요.\n"
            "대상 메일: " + "; ".join(m["subject"] for m in new_mails)
        )
        return
    finally:
        close_driver(check_driver)

    # (메일 인덱스 -> 주문 결과 dict)로 어느 메일 소속인지 추적하며 전체 주문을
    # 한 풀에 제출. 한 메일의 주문이 전부 끝나면(remaining이 0) 바로 그 메일만
    # 마무리한다.
    per_order_by_mail = [dict() for _ in new_mails]
    remaining_by_mail = [len(m["order_nos"]) for m in new_mails]

    # 2026-09-18: 이 배치 도중 공유 Edge 락을 계속 갱신해주던 데몬 스레드가
    # 여기 있었으나, 이 스크립트가 아예 전용 Edge(포트/프로필)로 완전히
    # 분리되면서(EDGE_OWNER_CONFIGS, set_edge_owner 참고) 공유 락 자체가 더
    # 이상 필요 없어져 제거함 - 다른 스크립트와 겹칠 일이 없다.
    with ThreadPoolExecutor(max_workers=n_workers) as ex:
        future_to_mail_idx = {}
        for mi, m in enumerate(new_mails):
            rules = RELEASE_RULES[m["kind"]]
            for order_no in m["order_nos"]:
                fut = ex.submit(_process_single_order, m["kind"], order_no, rules, state)
                future_to_mail_idx[fut] = mi

        for fut in as_completed(future_to_mail_idx):
            mi = future_to_mail_idx[fut]
            order_no, result = fut.result()
            per_order_by_mail[mi][order_no] = result
            # 2026-08-07: 출고가 실제로 나간 건은 여기서 바로 디스크에 남긴다 -
            # 아래 _finalize_order_mail(메일 전체가 끝나야 호출)까지 기다리면
            # 그 사이 프로세스가 죽을 때 이미 나간 출고가 통째로 유실된다
            # (_save_completed_order_now 주석의 2026-08-07 사고 참고).
            # 메인 스레드에서 부르므로 워커의 COM 초기화 문제와 무관하고,
            # 답장은 여전히 _finalize_order_mail에서만 나간다.
            _save_completed_order_now(new_mails[mi], order_no, result, state)
            remaining_by_mail[mi] -= 1
            if remaining_by_mail[mi] == 0:
                _finalize_order_mail(new_mails[mi], per_order_by_mail[mi], state)


# ==============================================================
# main
# ==============================================================
def main():
    lock = _acquire_singleton_lock()
    if lock is None:
        log("이미 다른 인스턴스가 실행 중 - 종료 (겹치는 스케줄 트리거로 추정)")
        return
    try:
        log("===== pick_release_watcher 시작 =====")
        state = load_state()
        processed = set(state.keys())
        manual_skip_entry_ids = set(state.get("_manual_skip_entry_ids", []))
        # 본문에 "윤길"이 없어 건너뛴 메일(= 보현 과장님이 이미 release 완료).
        # 매 회차 같은 스킵 로그가 쌓이지 않게 EntryID로 기억해둔다.
        prereleased_entry_ids = set(state.get("_bohyun_prereleased_entry_ids", []))
        prereleased_before = len(prereleased_entry_ids)
        # 2026-08-20: 오더번호 자리수가 안 맞아 알림을 이미 보낸 메일
        # (find_near_miss_order_nos 주석) - 20분마다 도니까 EntryID로 기억해서
        # 같은 메일로 초안이 쌓이는 걸 막는다.
        bad_order_no_entry_ids = set(state.get("_bad_order_no_entry_ids", []))
        bad_order_no_before = len(bad_order_no_entry_ids)
        # 2026-09-17: 처리완료된 오더번호를 "백오더" 제목으로 강제 재처리한 메일의
        # EntryID - 메일 1건당 딱 1번만 강제 재처리하도록 막는다(없으면 메일이
        # 받은편지함에 남아있는 한 스캔마다 계속 재처리됨 - 실전에서 false-positive
        # "확인 필요" 알림을 만든 버그, find_new_order_mails 주석 참고).
        backorder_reprocessed_entry_ids = set(state.get("_backorder_reprocessed_entry_ids", []))
        backorder_reprocessed_before = len(backorder_reprocessed_entry_ids)

        try:
            new_mails = find_new_order_mails(processed, manual_skip_entry_ids,
                                             prereleased_entry_ids,
                                             bad_order_no_entry_ids,
                                             backorder_reprocessed_entry_ids)
        except Exception as e:
            log(f"[에러] 메일 검색 실패: {exc_detail(e)}")
            return

        if len(prereleased_entry_ids) != prereleased_before:
            state["_bohyun_prereleased_entry_ids"] = sorted(prereleased_entry_ids)
            save_state(state)
        if len(bad_order_no_entry_ids) != bad_order_no_before:
            state["_bad_order_no_entry_ids"] = sorted(bad_order_no_entry_ids)
            save_state(state)
        if len(backorder_reprocessed_entry_ids) != backorder_reprocessed_before:
            state["_backorder_reprocessed_entry_ids"] = sorted(backorder_reprocessed_entry_ids)
            save_state(state)

        if not new_mails:
            log("신규 출고 요청 메일 없음. 종료.")
            return

        # 오래된 것부터 순서대로 처리(완료 순서 자체는 병렬 처리라 메일마다
        # 달라질 수 있음 - 이 reverse는 작업 제출 순서/로그 표시 순서용)
        new_mails.reverse()
        # 2026-09-18: 공유 Edge 락을 걸었다가(TO 7882258 FedEx 어레인지 실사고로
        # 도입) 같은 날 stale 판정 구멍으로 또 실전 충돌을 냈다 - 대신 이
        # 스크립트를 전용 Edge(포트/프로필)로 완전히 분리해 겹칠 일 자체를
        # 없앴다(set_edge_owner("pick_release_watcher") 참고). 락 제거.
        process_order_mails(new_mails, state)

        log("===== pick_release_watcher 종료 =====\n")
    finally:
        _release_singleton_lock(lock)


if __name__ == "__main__":
    main()
