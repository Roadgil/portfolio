원본 경로: OneDrive `10. 수입/DCD 소모품 Pick Release 자동화`, `10. 수입/쉽컨펌 자동화`. Oracle Fusion Selenium RPA로 출고요청 Release·Ship Confirm 자동화. 저수준 Oracle DOM 탐색용 진단 스크립트(오라클 자동화 폴더의 oracle_click.py 등 26개)는 전시 목적상 제외.

- **실행 방법**: `pick_release_watcher.py`, `ship_confirm_watcher.py`가 각각 독립 실행되는 감시 스크립트(작업 스케줄러로 매시간 등 반복 실행). 둘 다 `icbl_ci_watcher.py`를 `from icbl_ci_watcher import (...)`로 가져다 씀.
- **필요 패키지**: `selenium`(Edge WebDriver 필요). 표준 라이브러리(`concurrent.futures`, `json`, `time`) 외 추가 패키지는 이 두 파일 기준으로는 확인되지 않음.
- **외부 의존성**: Microsoft Edge + Selenium WebDriver, Oracle Fusion 로그인(SSO).
- **재사용 시 반드시 고쳐야 할 것**:
  - **이 폴더만으로는 실행 불가** — `pick_release_watcher.py`/`ship_confirm_watcher.py`가 `../import-customs/icbl_ci_watcher.py`를 import하므로, `import-customs` 폴더의 `icbl_ci_watcher.py`를 같은 경로에 가져와야 함(위 26개 저수준 진단 스크립트까지는 필요 없을 가능성이 높지만, `icbl_ci_watcher.py`가 그 중 일부를 추가로 import한다면 그것도 따라와야 함 — 실제 실행 전 import 에러로 확인 필요).
  - state/cache json, `_edge_restart` 관련 쿨다운 스탬프 파일, 로그는 포함하지 않음(최초 실행 시 자동 생성).
