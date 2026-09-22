원본 경로: OneDrive `14. 창작소/DCD_캔회수_웹앱`. Google Apps Script 웹앱, DCD 소모품 빈 캔 회수 신청/추적(2026-09-01 배포).

- **실행 방법**: Google Apps Script 프로젝트. `Code.gs`가 서버 로직(`doGet` 라우팅), `RequestForm.html`/`AdminList.html`/`CommonStyle.html`/`KakaoSearch.html`이 클라이언트 화면. Apps Script 에디터에서 "배포 → 웹앱"으로 배포. **코드를 고친 뒤에는 반드시 새 버전으로 재배포해야 반영됨**(기존 배포에 덮어쓰기만 하면 안 됨).
- **필요 패키지**: 없음(Apps Script는 Google 서버에서 실행, pip/npm 불필요).
- **외부 의존성**: Google Sheets(데이터 저장소, `SpreadsheetApp.openById`), Kakao 주소/지도 검색 API(`KakaoSearch.html` 관련).
- **재사용 시 반드시 고쳐야 할 것**:
  - `Code.gs`의 `SHEET_ID`는 원 소유자(윤길)의 Google Sheet ID라 다른 계정에서 그대로 못 씀 — 새 시트를 만들어 ID를 바꿔야 함.
  - ⚠️ `Code.gs`에 `ADMIN_TOKEN`과 `KAKAO_KEY`가 **실제 값으로 하드코딩**돼 있고 이미 이 public 저장소에 커밋되어 있음. 재사용 전에 반드시 두 값을 모두 새로 발급/변경할 것(Kakao 키는 콘솔에서 재발급, ADMIN_TOKEN은 임의의 새 문자열로 교체).
