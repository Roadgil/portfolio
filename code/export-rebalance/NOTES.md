원본 경로: OneDrive `12. 수출/Rebalance TO 자동화`, `12. 수출/ci_invoice_html.py`. Rebalance TO → Pick Wave → CI 생성 → DHL/FedEx 수출 arrange → Oracle Tracking# 기입까지 이어지는 파이프라인.

- **실행 방법**: `rebalance_watcher.py`가 메인 감시/오케스트레이션 스크립트(작업 스케줄러로 상시 실행), `dhl_export_arrange.py`/`fedex_ship_watcher.py`/`oracle_shipment_tracking.py`/`ci_invoice_html.py`는 각 단계별 모듈로 `rebalance_watcher.py`에서 import돼 호출됨. 단독 실행용 `--stop` 등 디버그 옵션이 일부 있음(파일 상단 docstring 참고).
- **필요 패키지**: `selenium`(Edge WebDriver 필요), `pandas`, `beautifulsoup4`(bs4), `openpyxl`.
- **외부 의존성**: Microsoft Edge + Selenium WebDriver, Oracle Fusion 로그인(SSO), Salesforce, DHL MyDHL+ 포털 로그인, FedEx Ship Manager 포털 로그인. `oracle_shipment_tracking.py`, `dhl_export_arrange.py`, `fedex_ship_watcher.py` 등은 수출신고실적 엑셀(`12. 수출/수출신고실적20260126~.xlsx`)과 수입신고실적 엑셀(`10. 수입/수입신고실적(20250916~).xlsx`), 담당자 주소록 엑셀 등 여러 회사 내부 엑셀 파일 경로를 하드코딩하고 있음.
- **필요 환경변수**: `DHL_PASSWORD`, `FEDEX_PASSWORD` (2026-09-22부터 코드에서 하드코딩 제거하고 환경변수로 전환).
- **재사용 시 반드시 고쳐야 할 것**:
  - 코드 안의 OneDrive 절대경로(수출/수입 실적 엑셀, CI 템플릿, 로고 html 등)를 새 환경 경로로 전부 바꿔야 함.
  - `rebalance_watcher.py`는 같은 저장소의 `../import-customs/icbl_ci_watcher.py`, `../outbound-rpa/pick_release_watcher.py`를 import한다 — 폴더 하나만 떼어서 실행하면 `ModuleNotFoundError`가 나므로, 실제로 돌리려면 세 폴더의 파일들을 한 디렉토리에 모아야 함.
  - `ci_invoice_html.py`는 `import ci_invoice_excel`을 하는데, **`ci_invoice_excel.py` 원본은 로컬에서도 이미 사라지고 컴파일 캐시(.pyc)만 남아있어서 이 저장소에도 포함하지 못함** — 재사용 시 이 모듈을 새로 작성해야 함.
  - state/cache json, 로그 파일은 포함하지 않았고 최초 실행 시 자동 생성됨.
