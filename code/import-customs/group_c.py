import subprocess
import os
import time
from datetime import datetime

root = r'C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입'
log_path = os.path.join(root, r'작업스케줄러\run_log.txt')

# 스케줄러에선 BAT/cmd를 거치지 않고 conda 파이썬으로 .py를 직접 실행
# (리스트 형태 → cmd 미경유 → OneDrive·공백 경로 문제 원천 회피)
PY = r'C:\Users\yoongil.chae\Miniconda\envs\pdf_updater\python.exe'

# 작업스케줄러 폴더 (group_c.py·dhl_forwarder·customs_email_generator·finance_calendar 가 함께 있는 곳)
SCHED_DIR = os.path.join(root, r'작업스케줄러')

# 1번: 수입신고필증 관세/부가세 → 엑셀 (Finance 검토용, 별도 폴더에 위치)
IMP_SCRIPT     = r'C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\수입신고필증 검토 with Finance\imp_tax_updater.py'
# 2번: 재무팀 Finance Calendar → Outlook 일정 자동 등록
FIN_SCRIPT     = os.path.join(SCHED_DIR, 'finance_calendar_to_outlook.py')
# 3번: DHL 미납 청구서 → finance(전은평) 비용처리 요청 메일 초안 저장(검토 후 직접 발송)
DHL_SCRIPT     = os.path.join(SCHED_DIR, 'dhl_forwarder.py')
# 4번: 관세법인 월납부 고지서 → finance(전은평) 비용처리 요청 메일 초안 저장(검토 후 직접 발송)
CUSTOMS_SCRIPT = os.path.join(SCHED_DIR, 'customs_email_generator.py')
# 5번: FedEx 청구서(Miae Jang 전달) → finance(전은평) 비용처리 요청 메일 초안 저장(검토 후 직접 발송)
#      (2026-09-15 추가, DHL SELR 처리와 동일한 방식)
FEDEX_SCRIPT   = os.path.join(SCHED_DIR, 'fedex_forwarder.py')

steps = [
    ('1', [PY, '-B', IMP_SCRIPT]),
    ('2', [PY, '-B', FIN_SCRIPT]),
    ('3', [PY, '-B', DHL_SCRIPT]),
    ('4', [PY, '-B', CUSTOMS_SCRIPT]),
    ('5', [PY, '-B', FEDEX_SCRIPT]),
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
    if result.returncode == 0:
        log(f'[{num}] OK')
    else:
        log(f'[{num}] FAILED (code {result.returncode})')
        detail = ((result.stdout or '') + (result.stderr or '')).strip()
        if detail:
            log(f'[{num}] 에러 출력: {detail[-2000:]}')
        else:
            log(f'[{num}] 에러 출력 없음 (크래시로 아무 것도 못 남겼을 가능성)')

log('====== Group C (Finance) Start ======')
for num, cmd in steps:
    run_step(num, cmd)
log('====== Group C (Finance) Done ======')
log('')
time.sleep(3)
