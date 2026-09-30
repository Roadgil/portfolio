원본 경로: OneDrive `10. 수입/Monthly Closing/automation`. 실행: Windows 작업 스케줄러
"FSE_Monthly_Runner"(매달 마지막 영업일 11:00, 절전/미실행 시 다음날 자동 캐치업).

Monthly Closing 대시보드(../warehouse-monthly-closing)에 들어가는 월마감 자료 4종 중
3종(소모/입고/온핸드)을 Oracle Fusion Cloud + Salesforce에서 Playwright로 자동 수집해
대시보드 자체 UI/데이터 구조에 직접 반영하는 파이프라인. 나머지 1종(Intransit)은
이미 있던 별도 메일 다운로드 자동화가 매일 채워주므로 파일 존재만 확인한다.

- **oracle_login.py**: Oracle Fusion Cloud 공용 로그인. "Sign in with AzureAD" 버튼 클릭
  한 번으로 세션 진입(브라우저 영속 프로필이라 이후 재실행 시 로그인 생략).
- **fse_consumption_puller.py**: Salesforce Classic 리포트를 직접 export URL
  (`?export=1&enc=UTF-8&xf=csv`)로 받아 엔지니어별 월 소모 수량 집계.
- **fse_receipt_puller.py**: Oracle Fusion "Review Completed Transactions"에서
  Transfer Order 입고 내역을 Export to Excel로 받는다.
- **fse_onhand_puller.py**: Oracle BI Publisher 리포트(Inventory On-hand)를 iframe
  파라미터 폼 조작(Inventory Organization 체크박스 전환) 후 다운로드.
- **fse_monthly_runner.py**: 위 3개를 병렬 실행(`subprocess.Popen`)하는 오케스트레이터.
  매달 마지막 영업일에만 실제로 도는 날짜 가드, 실패한 스크립트만 골라 재시도,
  성공 못 한 달은 "완료"로 기록하지 않아 다음날 자동 재시도(catch-up)된다.
- **fse_dashboard_patch.py**: 소모/입고 결과를 대시보드 HTML의 SEED 상수(JS 객체)에
  정규식으로 직접 패치. 항상 타임스탬프 백업을 먼저 만든 뒤 BEGIN/END 마커 사이
  `const NAME = {...};` 선언 한 줄만 정확히 치환(주변 설명 주석은 보존).
- **fse_dashboard_upload.py**: 온핸드 파일을 대시보드 자체 "현재 월 업로드" UI에
  드롭 → "저장 & 시계열에 추가" → "공유용 HTML 다운로드" → 원본 파일 교체까지
  Playwright로 대신 클릭. 계산 로직(집계/카테고리 분류)은 전부 대시보드 자체 JS를
  그대로 쓰고, 이 스크립트는 브라우저 조작만 한다(Python으로 재구현 안 함 —
  대시보드 로직과 미묘하게 어긋날 위험 회피).

**실행 방법**: 사내 Oracle Fusion Cloud / Salesforce 인스턴스 접근 권한과 SSO 세션이
필요해 그대로 실행할 수 없다(사내 전용 자동화). Oracle/Salesforce 인스턴스 URL은
`<your-instance>`/`<your-org>`로 마스킹했다.

**필요 패키지**: `playwright`, `pandas`, `openpyxl`(입고 리포트가 xlsx 형식일 때).

**겪은 함정들**:
- Playwright의 `expect_download()`/`download.save_as()`가 이 환경에서 3개 스크립트
  전부 독립적으로 "Target page, context or browser has been closed" 오류로 불안정했다
  → `page.route()` + `route.fetch()` 인터셉션(또는 Salesforce는 직접 URL fetch)으로 통일.
- Oracle Fusion Home이 브라우저 프로필별로 마지막 방문 탭을 기억한다 — 온핸드/입고가
  한 프로필을 공유하던 시절엔 이 탭 상태가 오염돼 "60초를 기다려도 타임아웃"이
  발생했다(부하 문제로 오판하기 쉬움). 실패 스크린샷을 직접 확인해서야 원인을
  찾았고, 프로필을 완전히 분리하고 원하는 탭을 매번 명시적으로 클릭하게 해 해결했다.
- 자식 스크립트가 예외를 잡고 `return`만 하면 프로세스 종료코드가 0(성공)으로 남아
  오케스트레이터가 실패를 놓친다 — 실제로 입고 수집이 화면 진입도 못했는데
  "완료"로 잘못 기록된 사고가 있었다. 모든 실패 경로를 `sys.exit(1)`로 바꿔 해결.
