원본 경로: OneDrive `10. 수입/작업스케줄러`. 월별 납부고지서/DHL·FedEx 청구서 초안 생성, Finance Calendar OCR→Outlook 일정 등록. 초안 생성까지만 자동화(발송은 사람이 확인 후 진행).

- **실행 방법**: `customs_email_generator.py`, `dhl_forwarder.py`, `finance_calendar_to_outlook.py`는 각각 독립 진입점(작업 스케줄러 `GROUP_C_Finance.bat` 등에서 실행). `fedex_forwarder.py`는 `dhl_forwarder.py`의 로직을 `from dhl_forwarder import (...)`로 재사용하므로 같은 폴더에 `dhl_forwarder.py`가 있어야 동작.
- **필요 패키지**: `openpyxl`, `pdfplumber`(PDF에서 금액/기한 파싱), `holidays`(영업일 계산), `pywin32`(`win32com.client`, `pythoncom` — Outlook 메일 읽기/초안 작성용).
- **외부 의존성**: Outlook 데스크톱 클라이언트(로그인된 상태에서 win32com으로 제어), `finance_calendar_to_outlook.py`는 easyocr류 OCR 스택도 쓰는 것으로 보이는 환경변수(`PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK`, `KMP_DUPLICATE_LIB_OK`)가 있음 — OCR 관련 패키지(easyocr/torch)가 별도로 필요할 수 있음(정확한 패키지명은 해당 파일 상단 import 직접 확인 권장).
- **필요 환경변수/시크릿**: 이 폴더 코드에서는 하드코딩된 비밀번호가 발견되지 않음(Outlook은 로그인된 데스크톱 세션을 그대로 사용).
- **재사용 시 반드시 고쳐야 할 것**: 각 스크립트 상단의 실적 파일/고지서 PDF 폴더 경로(OneDrive 절대경로)를 새 환경 경로로 교체. state 파일(`customs_email_state.json`, `_dhl_forwarder_state.json`, `_fin_cal_cache.json` 등)과 로그는 이 저장소에 없고 최초 실행 시 자동 생성됨.
