원본 경로: OneDrive `10. 수입/PDF-수입면장 파이썬`, `Intransit-수입면장 파이썬`, `Intransit 내부공유`, `작업스케줄러`, `OTBI 실입고 파이썬`, `인천관세법인 C.I 확인`. 작업 스케줄러(GROUP_A/B/C)로 평일 자동 실행.

- **실행 방법**: `group_a.py`/`group_b.py`/`group_c.py`가 각 그룹의 오케스트레이터(스케줄러 .bat이 이걸 호출). `icbl_ci_watcher.py`, `outlook_imp_pdf_saver.py`, `outlook_intransit_downloader.py`, `urgent_item_freezer.py`, `pdf_auto_updater.py`, `otbi_receipt_updater.py` 등은 각 그룹 안에서 순서대로 호출되는 개별 단계 스크립트. `intransit_to_ir_append_only_sorted_paths_set.py`는 `intransit_internal_share.py` 등에서 `as updater`로 import됨.
- **필요 패키지**: `openpyxl`, `pandas`, `pdfplumber`, `pypdfium2`, `pytesseract`(+시스템에 Tesseract OCR 설치 필요), `Pillow`(PIL), `pywin32`(`win32com.client` — Outlook).
- **외부 의존성**: Outlook 데스크톱 클라이언트, Microsoft Edge + Selenium(`icbl_ci_watcher.py`, `intransit_internal_share.py`), Oracle Fusion 로그인(SSO), SharePoint(REST API 호출 부분 있음).
- **필요 환경변수/시크릿**: 이 폴더 코드에서는 하드코딩된 비밀번호가 발견되지 않음(Oracle은 SSO, Outlook은 로그인된 데스크톱 세션 사용).
- **재사용 시 반드시 고쳐야 할 것**:
  - 수입신고실적 엑셀(`10. 수입/수입신고실적(20260211)자동화.xlsx`), IR/Intransit 통합 파일(`IR 신청목록 & Instransit(20260303~).xlsx`), 필증 PDF 폴더 등 다수의 OneDrive 절대경로를 새 환경 경로로 교체해야 함.
  - state/cache json, 로그, `.bak` 백업 파일은 포함하지 않음(최초 실행 시 자동 생성).
  - `icbl_ci_watcher.py`는 `../export-rebalance/`, `../outbound-rpa/`, `../sco-cancellation/`의 스크립트에서도 import해서 쓰므로, 다른 폴더 자동화와 같이 실행하려면 경로를 맞춰 한 디렉토리에 모아야 함.
