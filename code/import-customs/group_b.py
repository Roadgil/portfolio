import subprocess
import os
import sys
import time
from datetime import datetime

root = r'C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입'
log_path = os.path.join(root, r'작업스케줄러\run_log.txt')

# Group B = 수입(면장 PDF 저장 + 엑셀 반영) 전용
# (finance 관련 imp_tax_updater / finance_calendar_to_outlook 는 Group C로 이동)
# 다른 step 의 bat 들이 쓰는 고정 파이썬(PDF_UPDATER 환경). 작업 스케줄러로 돌 때는 PATH 가
# 대화형 셸과 달라서 그냥 'python' 을 쓰면 pdfplumber 를 못 찾고 조용히 실패할 수 있다.
# → 고정 경로를 우선 쓰고, 없으면 현재 인터프리터로 폴백.
FIXED_PY = r'C:\Users\YOONGI~1.CHA\MINICO~1\envs\PDF_UP~1\python.exe'
PY = FIXED_PY if os.path.exists(FIXED_PY) else sys.executable

steps = [
    ('5', os.path.join(root, r'PDF-수입면장 파이썬\run_outlook_saver.bat')),
    ('6', os.path.join(root, r'PDF-수입면장 파이썬\run_Excelupdater.bat')),
    # 2026-08-20 추가: 필증 ↔ 실적파일 금액 대조 검증 (읽기 전용).
    # 8050-00-9004 렌즈 4 EA 가 실적파일에서 조용히 빠져 한 달 넘게 발견되지 않은 일이 있었음.
    # 원인(중복키)은 auto_import_complete.py 에서 고쳤지만, 원인과 무관하게 결과를 매일 검증한다.
    # 불일치가 있으면 stdout 에 [ALERT] 로 찍히고, 아래 run_step 이 run_log.txt 에 남긴다.
    ('7', [PY, os.path.join(root, r'PDF-수입면장 파이썬\verify_declarations.py')]),
]

def log(msg):
    line = f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
    print(line)
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

# 2026-07-10: 실패해도 exit code만 남고 실제 에러 내용은 전혀 안 남아서(오늘
# ICBL_CI_Watcher 크래시를 Windows 이벤트 로그까지 뒤져서 찾은 일이 있었음),
# stdout/stderr를 캡처해서 실패 시 run_log.txt에 같이 남기도록 변경.
def run_step(num, cmd):
    target = cmd if isinstance(cmd, str) else ' '.join(cmd)
    log(f'[{num}] Running: {target}')
    # 자식 프로세스의 기본 콘솔 인코딩이 cp949라 그대로 두면 캡처한 한글
    # stdout/stderr를 utf-8로 디코드할 때 깨짐 -> PYTHONIOENCODING으로 강제 통일.
    kwargs = dict(capture_output=True, text=True, encoding='utf-8', errors='replace',
                  env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    if isinstance(cmd, list):
        result = subprocess.run(cmd, **kwargs)                      # 직접 실행 (shell 없음)
    else:
        result = subprocess.run(f'"{cmd}"', shell=True, **kwargs)   # bat 경로 = cmd 경유
    detail = ((result.stdout or '') + (result.stderr or '')).strip()
    if result.returncode == 0:
        log(f'[{num}] OK')
        # 2026-07-13: 성공해도 "OK"만 남아서 pdf_auto_updater.py의 자체 요약
        # 로그([SUMMARY] 정정/신규 PDF 건수, 업데이트 행수 등)가 안 보였던 문제.
        # 이 요약이 있어야 "PDF는 파싱됐는데 채울 빈 행이 없어서 조용히 스킵됨"
        # 같은 상황을 로그만 보고도 알 수 있음 -> 성공해도 출력 내용을 남긴다.
        if detail:
            log(f'[{num}] 출력: {detail[-3000:]}')
    else:
        log(f'[{num}] FAILED (code {result.returncode})')
        if detail:
            log(f'[{num}] 에러 출력: {detail[-2000:]}')
        else:
            log(f'[{num}] 에러 출력 없음 (크래시로 아무 것도 못 남겼을 가능성)')

log('====== Group B Start ======')
for num, cmd in steps:
    run_step(num, cmd)
log('====== Group B Done ======')
log('')
time.sleep(3)
