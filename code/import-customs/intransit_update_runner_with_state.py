# -*- coding: utf-8 -*-
"""
intransit_update_runner_with_state_v2.py

문제 해결:
- Windows CMD(한국어)에서는 보통 CP949 코드페이지를 사용합니다.
- wrapper가 stdout을 UTF-8로 디코딩하면 한글 로그가 깨져서(  ) 파싱도 실패합니다.
- 그래서 stdout 디코딩을 CP949 우선으로 처리하고, 실패 시 UTF-8로 fallback 합니다.

결과:
- 콘솔 출력 한글 정상
- added_rows/max_ship/report_file/backup_path 파싱 정상
- intransit_update_state.json 생성/갱신
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path


HERE = Path(__file__).resolve().parent
TARGET_SCRIPT = HERE / "intransit_to_ir_append_only_sorted_paths_set.py"
STATE_PATH = HERE / "intransit_update_state.json"


def parse_output(lines: list[str]) -> dict:
    added_rows = None
    max_ship = None
    report_file = None
    backup_path = None

    re_max_ship = re.compile(r"최댓값\s*:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})")
    re_report = re.compile(r"Intransit\s*리포트\s*선택\s*:\s*(.+)$")
    re_backup = re.compile(r"백업\s*완료\s*:\s*(.+)$")

    re_no_new = re.compile(r"추가할\s*신규\s*데이터\s*없음")
    re_new_num = re.compile(r"추가할\s*신규\s*데이터.*?(\d+)\s*(?:건|row|rows|행)?")

    for line in lines:
        m = re_max_ship.search(line)
        if m:
            max_ship = m.group(1)

        m = re_report.search(line)
        if m:
            report_file = m.group(1).strip()

        m = re_backup.search(line)
        if m:
            backup_path = m.group(1).strip()

        if re_no_new.search(line):
            added_rows = 0

        m = re_new_num.search(line)
        if m and added_rows is None:
            try:
                added_rows = int(m.group(1))
            except Exception:
                pass

    return {
        "run_at": datetime.now().isoformat(timespec="seconds"),
        "added_rows": added_rows,
        "max_ship": max_ship,
        "report_file": report_file,
        "backup_path": backup_path,
    }


def main() -> int:
    if not TARGET_SCRIPT.exists():
        print(f"[ERROR] Target script not found: {TARGET_SCRIPT}")
        return 2

    proc = subprocess.Popen(
        [sys.executable, str(TARGET_SCRIPT)],
        cwd=str(HERE),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    lines: list[str] = []
    assert proc.stdout is not None

    while True:
        b = proc.stdout.readline()
        if not b:
            break

        # ✅ CP949 우선 디코딩(한국 Windows)
        try:
            line = b.decode("cp949")
        except Exception:
            try:
                line = b.decode("utf-8")
            except Exception:
                line = b.decode("utf-8", errors="replace")

        print(line, end="")           # 콘솔 출력 유지
        lines.append(line.rstrip("\n"))

    rc = proc.wait()

    state = parse_output(lines)
    state["return_code"] = rc

    try:
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[STATE] Saved: {STATE_PATH}")
    except Exception as e:
        print(f"[WARN] Failed to write state file: {e}")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
