import subprocess
import os
import time
from datetime import datetime

root = r'C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입'
log_path = os.path.join(root, r'작업스케줄러\run_log.txt')

steps = [
    ('1', r'작업스케줄러\RUN_URGENT_ITEM_FREEZER.bat'),
    ('2', r'Intransit-수입면장 파이썬\RUN_INTRANSIT_V2.bat'),
    ('3', r'Intransit-수입면장 파이썬\RUN_AUTO_IMPORT_COMPLETE_V2.bat'),
    ('4', r'Intransit 내부공유\intransit_run_padded.bat'),
    ('5', r'Intransit 내부공유\RUN_INTRANSIT_INTERNAL_SHARE.bat'),

]

def log(msg):
    line = f'[{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}] {msg}'
    print(line)
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

# 2026-07-10: 실패해도 exit code만 남고 실제 에러 내용은 전혀 안 남아서(오늘
# ICBL_CI_Watcher 크래시를 Windows 이벤트 로그까지 뒤져서 찾은 일이 있었음),
# stdout/stderr를 캡처해서 실패 시 run_log.txt에 같이 남기도록 변경.
def run_step(num, path):
    log(f'[{num}] Running: {path}')
    # 자식 프로세스(대개 conda python)의 기본 콘솔 인코딩이 cp949라 그대로 두면
    # 캡처한 한글 stdout/stderr를 utf-8로 디코드할 때 깨짐 -> PYTHONIOENCODING으로
    # 자식의 출력 인코딩 자체를 utf-8로 강제해서 맞춘다.
    child_env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
    result = subprocess.run(
        path, shell=True, capture_output=True, text=True, encoding='utf-8', errors='replace',
        env=child_env,
    )
    detail = ((result.stdout or '') + (result.stderr or '')).strip()
    if result.returncode == 0:
        log(f'[{num}] OK')
        if detail:
            log(f'[{num}] 출력: {detail[-2000:]}')
    else:
        log(f'[{num}] FAILED (code {result.returncode})')
        if detail:
            log(f'[{num}] 에러 출력: {detail[-2000:]}')
        else:
            log(f'[{num}] 에러 출력 없음 (크래시로 아무 것도 못 남겼을 가능성)')

log('====== Group A Start ======')
for num, rel in steps:
    path = os.path.join(root, rel)
    run_step(num, path)
log('====== Group A Done ======')
log('')
time.sleep(3)