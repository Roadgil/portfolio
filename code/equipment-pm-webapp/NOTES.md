원본 경로: OneDrive `14. 창작소/장비_PM_웹앱`. Google Apps Script 웹앱, 장비 정기점검(PM) 일정을 추적하고 자동 알림.

- **실행 방법**: Google Apps Script 프로젝트. `Code.gs`가 서버 로직, `Index.html`이 화면, `SeedData.gs`는 초기 시드 데이터 로딩용. Apps Script 에디터에서 "배포 → 웹앱"으로 배포하고, 수정 후에는 새 버전으로 재배포해야 반영됨.
- **필요 패키지**: 없음(Apps Script는 Google 서버 실행, pip/npm 불필요).
- **외부 의존성**: `Code.gs`/`SeedData.gs`에 별도 `SHEET_ID`/`openById` 호출이 보이지 않음 — 컨테이너 바인딩 스프레드시트(Apps Script 프로젝트가 특정 시트에 종속된 형태)일 가능성이 있으니, 재사용 시 원본 Apps Script 프로젝트가 어느 시트에 묶여 있는지 원본 위치에서 먼저 확인할 것.
- **재사용 시 반드시 고쳐야 할 것**: 이 두 파일만으로는 백엔드 시트 연결 정보가 확인되지 않으므로, 새 환경에 옮길 때는 Apps Script 프로젝트를 새로 만들고 필요한 시트를 직접 연결해야 함.
