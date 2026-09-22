원본 경로: OneDrive `10. 수입/RMA 자동답장`. Salesforce 스크레이핑 기반 RMA 자동답장(초안), Unused/Defective 판정. Rebalance(본사반송) 트리거의 RMA 분기 로직은 `../export-rebalance/rebalance_watcher.py`에 같이 있음.

- **실행 방법**: `rma_auto_reply.py` 단독 진입점(작업 스케줄러로 반복 실행하는 감시형 스크립트로 추정).
- **필요 패키지**: 이 파일 자체의 import는 표준 라이브러리(`datetime`, `html`, `socket`)뿐이라, Selenium 등 브라우저 제어 로직은 같은 원본 폴더의 다른 헬퍼/공유 모듈(이 저장소에는 미포함)에 있을 가능성이 높음 — 원본 폴더 확인 필요.
- **외부 의존성**: Salesforce(RMA Case 정보 스크레이핑), Outlook(답장 초안 생성으로 추정).
- **재사용 시 반드시 고쳐야 할 것**: 브라우저/Salesforce 로그인 관련 헬퍼가 이 파일에 안 보이므로, 실제 재사용 전에 원본 `10. 수입/RMA 자동답장` 폴더에 공유 모듈이 더 있는지 먼저 확인할 것(이 저장소는 단일 파일만 옮겨온 상태).
