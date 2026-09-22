원본 경로: OneDrive `10. 수입/SCO 취소 자동화`. 백오더/재고부족 건 자동 감지 및 취소 처리.

- **실행 방법**: `sco_cancel_watcher.py` 단독 진입점(작업 스케줄러 반복 실행형 감시 스크립트).
- **필요 패키지**: 이 파일에서 확인되는 추가 패키지는 없음(표준 라이브러리 위주). `from icbl_ci_watcher import (...)`로 다른 모듈을 가져다 쓰므로 그 모듈의 의존성(selenium 등)이 실행 시 같이 필요함.
- **외부 의존성**: Microsoft Edge + Selenium WebDriver, Oracle Fusion 로그인(SSO) — `icbl_ci_watcher.py` 경유.
- **재사용 시 반드시 고쳐야 할 것**: **이 폴더만으로는 실행 불가** — `../import-customs/icbl_ci_watcher.py`를 같은 경로로 가져와야 `import` 에러 없이 동작함. 리포트 보관 폴더(원본의 `리포트_보관`)는 최초 실행 시 필요하면 새로 만들어야 함(이 저장소에는 없음).
