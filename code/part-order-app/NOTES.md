원본 경로: OneDrive `14. 창작소/FSE PO 앱`(현재 운영), `14. 창작소/part_order_backup`(보현과장님 휴가 시 백업 운영용 변형). Salesforce Case → Oracle Fusion Purchase Order 생성/릴리즈 자동화. `local_config*.json`, `batch_result.json` 등 실행결과/개인용 설정 파일은 제외.

- **실행 방법**: `part_order_app.py`(tkinter GUI, 사람이 직접 실행), `run_batch.py`/`run_unattended.py`/`run_approved.py`(무인 배치 실행용 진입점). `po_create.py`/`po_finish.py`/`release_one.py`/`scan_new_orders.py`/`fse_po_release.py`/`fse_po_oracle_release.py`는 위 진입점들이 내부적으로 import해서 쓰는 단계별 모듈.
- **필요 패키지**: `playwright`(+ `playwright install`로 브라우저 바이너리 설치), `pywin32`(`win32com.client` — Outlook 메일 읽기).
- **외부 의존성**: Salesforce(로그인 필요, `sf_actions.py`가 화면 조작), Oracle Fusion(로그인 필요), Outlook 데스크톱 클라이언트, `sf_form_helpers` 모듈(이 폴더의 `sf_actions.py`가 import하는데 이 폴더에 파일이 없음 — 원본 위치에서 별도로 가져와야 함).
- **필요 환경변수**: `PART_ORDER_DIR`, `USERNAME`, `COMPUTERNAME`(PC별 경로/식별을 위해 `paths.py`가 읽음 — `OneDrive`, `OneDriveCommercial` 환경변수도 참조).
- **재사용 시 반드시 고쳐야 할 것**:
  - `paths.py`가 "PC마다 다른 경로를 이 PC 기준으로 자동 해석"하는 구조라, 새 PC에서 쓰려면 `env_check.py`를 먼저 실행해서 이 PC에서 어떤 경로가 잡히는지 점검할 것(코드 주석에 이 절차가 명시돼 있음).
  - `sf_form_helpers.py` 모듈이 빠져 있어 `import` 단계에서 에러가 날 수 있음 — 원본 폴더에서 추가로 가져와야 함.
  - `local_config.<사용자명>.json` 같은 PC별 개인 설정 파일은 최초 실행 시 새로 만들어야 함(이 저장소에는 없음).
