원본 경로: OneDrive `Operation/19. Monthly Closing/automation`. 실행: Windows 작업 스케줄러
"FSE_Monthly_Runner"(매달 마지막 영업일 11:00, 절전/미실행 시 다음날 자동 캐치업).

Monthly Closing 대시보드(../warehouse-monthly-closing)에 들어가는 월마감 자료 4종 중
3종(소모/입고/온핸드)을 Oracle Fusion Cloud + Salesforce에서 Playwright로 자동 수집해
대시보드 자체 UI/데이터 구조에 직접 반영하는 파이프라인. 나머지 1종(Intransit)은
이미 있던 별도 메일 다운로드 자동화가 매일 채워주므로 파일 존재만 확인한다.
수집이 전부 성공하면 이어서 대시보드 반영과 SLOB(6개월 미소모) 재고 갱신까지 한다.

- **oracle_login.py**: Oracle Fusion Cloud 공용 로그인. "Sign in with AzureAD" 버튼 클릭
  한 번으로 세션 진입(브라우저 영속 프로필이라 이후 재실행 시 로그인 생략).
- **fse_consumption_puller.py**: Salesforce Classic 소모 리포트를 받는다. 리포트의 저장된
  기본 필터("Work Order Status not equal to Closed")를 이번 실행에서만 해제하고, 12개월치를
  화면 폼 상태 그대로 POST로 내보낸 뒤 Scheduled Date 기준으로 월별 파일로 나눈다.
- **fse_receipt_puller.py**: Oracle Fusion "Review Completed Transactions"에서
  Transfer Order 입고 내역을 Export to Excel로 받는다. 종료일 입력을 확정·재확인하고,
  월 범위/5000행 잘림 검증을 통과한 파일만 월별로 보관한다.
- **fse_onhand_puller.py**: Oracle BI Publisher 리포트(Inventory On-hand)를 iframe
  파라미터 폼 조작(Inventory Organization 체크박스 전환) 후 다운로드.
- **fse_monthly_runner.py**: 위 3개를 병렬 실행(`subprocess.Popen`)하는 오케스트레이터.
  매달 마지막 영업일에만 실제로 도는 날짜 가드, 실패한 스크립트만 골라 재시도,
  성공 못 한 달은 "완료"로 기록하지 않아 다음날 자동 재시도(catch-up)된다. 수집 성공 후
  대시보드 반영/SLOB 갱신은 별도 단계로 돌려, 실패해도 수집을 다시 하지 않고 그 단계만
  다음 실행에서 재시도한다.
- **fse_dashboard_patch.py**: 소모/입고 결과를 대시보드 HTML의 SEED 상수(JS 객체)에
  정규식으로 직접 패치. 항상 타임스탬프 백업을 먼저 만든 뒤 BEGIN/END 마커 사이
  `const NAME = {...};` 선언 한 줄만 정확히 치환(주변 설명 주석은 보존). 소모되지 않는
  공구 품목은 집계에서 제외한다.
- **fse_dashboard_upload.py**: 온핸드 파일을 대시보드 자체 "현재 월 업로드" UI에
  드롭 → "저장 & 시계열에 추가" → 대시보드가 만든 공유용 HTML을 받아 원본 파일 교체까지
  Playwright로 대신 한다. 계산 로직(집계/카테고리 분류)은 전부 대시보드 자체 JS를
  그대로 쓰고, 이 스크립트는 브라우저 조작만 한다(Python으로 재구현 안 함 —
  대시보드 로직과 미묘하게 어긋날 위험 회피). 매번 브라우저 저장소를 비우고 파일 기준으로
  시작하며, 같은 달을 다시 저장할 때는 기존 특이사항을 입력칸에 채워 보존한다.
- **fse_item_stats_build.py**: 월별 입고/소모 원본과 최신 On-hand를 읽어 품목별 통계를 만드는
  로더 모음. 소모되지 않는 공구 품목 목록(설정 파일)을 읽어 재고 구성 분석에서 제외한다.
- **fse_dead_stock_build.py**: 최근 6개월 동안 그 담당자가 한 번도 소모하지 않았는데 재고가
  있는 품목(SLOB)을 담당자별 "마지막 소모월"과 함께 엑셀과 대시보드 SEED 블록으로 낸다.
  FSE 간 이동은 하지 않고 6개월이 넘으면 SP/FG로 반납해 관리한다.

**실행 방법**: 사내 Oracle Fusion Cloud / Salesforce 인스턴스 접근 권한과 SSO 세션이
필요해 그대로 실행할 수 없다(사내 전용 자동화). Oracle/Salesforce 인스턴스 URL과 리포트 ID는
`<your-instance>`/`<your-org>`/`<report-id>`로 마스킹했다. 공구 품목 목록(JSON)은 사내 데이터라
넣지 않았고, 파일이 없으면 제외 없이 동작한다.

**필요 패키지**: `playwright`, `pandas`, `openpyxl`(입고 리포트가 xlsx 형식일 때).

**겪은 함정들**:
- Playwright의 `expect_download()`/`download.save_as()`가 이 환경에서 스크립트들에서 독립적으로
  "Target page, context or browser has been closed" 오류로 불안정했다 → 입고는 `page.route()` +
  `route.fetch()` 인터셉션으로, 대시보드 공유본은 대시보드가 만든 HTML 문자열을 `page.evaluate`로
  직접 받아 쓰는 방식으로 다운로드 이벤트를 피했다.
- Salesforce 소모 리포트의 내보내기 주소(`?export=1`)는 화면에서 지정한 기간과 필터 변경을 무시하고
  저장된 기본값을 내려줬다(서로 다른 달 파일이 같게 나옴). 게다가 기본 필터가 Closed 작업을 빼고 있어
  지난달을 다시 받으면 값이 작게 나왔다. 화면 폼 상태를 그대로 POST로 내보내는 방식으로 바꾸고, 기존
  수기 집계와 같은 달 값이 수량·금액까지 일치하는지로 검증했다.
- Oracle 검색 폼의 종료일을 채우고 바로 검색하면 종료일이 확정되기 전에 검색이 나가 "시작일~현재"가
  조회되고, 5000행 근처에서 내보내기가 시간초과로 반복 실패했다. 입력 후 확정(Tab)하고 값을 다시 읽어
  확인하도록 했다.
- 자동 업로드용 브라우저 프로필에 지난 실행이 저장해 둔 월 데이터가 남아 있으면 대시보드가 파일에 구워진
  값(사람이 나중에 적은 특이사항)보다 그 저장본을 우선해, 새 월을 저장할 때 지난달 특이사항이 지워졌다.
  업로드 전에 저장소를 비우도록 했다.
- Oracle Fusion Home이 브라우저 프로필별로 마지막 방문 탭을 기억한다 — 온핸드/입고가
  한 프로필을 공유하던 시절엔 이 탭 상태가 오염돼 "60초를 기다려도 타임아웃"이
  발생했다(부하 문제로 오판하기 쉬움). 실패 스크린샷을 직접 확인해서야 원인을
  찾았고, 프로필을 완전히 분리하고 원하는 탭을 매번 명시적으로 클릭하게 해 해결했다.
- 자식 스크립트가 예외를 잡고 `return`만 하면 프로세스 종료코드가 0(성공)으로 남아
  오케스트레이터가 실패를 놓친다 — 실제로 입고 수집이 화면 진입도 못했는데
  "완료"로 잘못 기록된 사고가 있었다. 모든 실패 경로를 `sys.exit(1)`로 바꿔 해결.
