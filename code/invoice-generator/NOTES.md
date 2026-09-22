원본 경로: OneDrive `14. 창작소/part_order_backup`. 릴리즈가 막히는 날 거래명세서+선출고요청서를 먼저 발송하는 월마감 선출고 워크플로.

- **실행 방법**: `make_preship_docs.py`가 문서 생성, `make_preship_draft.py`가 Outlook 초안 생성(발송은 사람이 확인 후 진행하는 것으로 추정 — 다른 초안류 스크립트와 동일 패턴).
- **필요 패키지**: `playwright`(브라우저 자동화, `playwright install`로 브라우저 바이너리 별도 설치 필요), `pywin32`(`win32com.client` — Outlook).
- **외부 의존성**: `paths` 모듈(같은 폴더 또는 `part-order-app/paths.py`)에 의존 — "사용자마다 다른 경로를 이 PC 기준으로 풀어준다"는 주석대로, PC마다 다른 절대경로를 이 모듈이 해석해줌. `paths.py`가 이 폴더에는 없으므로 `part-order-app/paths.py`를 같이 가져와야 동작.
- **재사용 시 반드시 고쳐야 할 것**: `paths.py` 의존성 때문에 이 폴더만 단독으로는 실행 불가 — `part-order-app` 폴더의 `paths.py`(및 필요 시 `local_config` 관련 파일)를 같은 경로에 둬야 함. Playwright 브라우저 바이너리 설치 필요.
