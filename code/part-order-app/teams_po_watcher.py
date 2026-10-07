"""Teams 예외 문의 감시 (FSE PO) - 평일 아침 공백(8~10시) 대응용.

배경: FSE PO 알림 메일은 fse_po_release.py(FSE_PO_Scan)가 거의 다 처리한다. 가끔 SF 알림
메일이 안 오는 등 예외 건은 엔지니어가 Teams로 "PO 00605435 입니다" 식으로 문의한다.
출근(10시) 전까지는 이걸 볼 사람이 없으므로, 이 스크립트가 그 구간에만 Teams를 읽는다.

동작
1. 헤드리스 claude(-p)가 M365 커넥터(chat_message_search)로 새 Teams 메시지를 읽어 JSON으로 준다
   (이미 승인된 커넥터라 별도 IT 승인/Playwright 로그인 불필요).
2. 메시지에서 PO 번호(00으로 시작하는 8자리)를 파이썬이 정규식으로 뽑는다.
3. fse_po_release_state.json에서 해당 PO 상태를 본다.
   - 이미 처리 완료(DONE_STATUSES) -> "이미 처리됨"으로 기록만
   - 미처리 -> shadow 모드: "실행했을 것"만 로그 / live 모드: fse_po_release.py direct <PO> 실행
     (Billable 판별, 보낸편지함 중복 확인, release->메일 순서는 모두 process_one이 이미 처리)
4. PO 번호는 없고 파트오더/누락 등 키워드가 있는 메시지는 사람 확인용으로
   teams_po_exceptions.txt에 모은다(10시에 확인).

실행: python teams_po_watcher.py [--live] [--force] [--since "YYYY-MM-DD HH:MM"]
  --live   미처리 PO에 대해 direct를 실제 실행(기본은 shadow = 기록만)
  --force  시간창/요일 검사 무시(테스트용)
  --since  이 시각 이후 메시지부터 조회(테스트용, state의 last_checked 무시)
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

STATE_PATH = os.path.join(SCRIPT_DIR, "teams_po_watcher_state.json")
RELEASE_STATE_PATH = os.path.join(SCRIPT_DIR, "fse_po_release_state.json")
EXCEPTIONS_PATH = os.path.join(SCRIPT_DIR, "teams_po_exceptions.txt")
LOCK_PATH = os.path.join(SCRIPT_DIR, "teams_po_watcher.lock")
RELEASE_SCRIPT = os.path.join(SCRIPT_DIR, "fse_po_release.py")

CLAUDE_EXE = r"C:\Users\<user>\.local\bin\claude.exe"
CLAUDE_CWD = r"C:\mcp\import_mcp"          # 아침브리핑과 같은 헤드리스 작업 폴더
CLAUDE_TIMEOUT_SEC = 240
DIRECT_TIMEOUT_SEC = 20 * 60               # 오라클 release 대기까지 포함

MY_EMAIL = "me@example.com"
WINDOW_START = (7, 50)                     # 평일만, 이 구간에서만 동작
WINDOW_END = (10, 15)
FIRST_RUN_LOOKBACK_MIN = 30
OVERLAP_MIN = 15                           # last_checked보다 앞에서 다시 읽어 LLM 조회 누락 보완(seen으로 중복 제거)
MAX_LIVE_ATTEMPTS_PER_PO = 2               # 같은 PO를 하루에 direct로 돌리는 최대 횟수

PO_RE = re.compile(r"(?<!\d)(00\d{6})(?!\d)")
# PO 번호는 없지만 사람이 봐야 할 만한 문의
KEYWORD_RE = re.compile(r"파트\s*오더|파츠\s*오더|\bPO\b|오더|누락|출고|릴리즈|release|알림|메일", re.I)


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------ state
def load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            log("[경고] teams_po_watcher_state.json 파싱 실패 - 빈 상태로 시작")
    return {"last_checked": None, "seen": {}, "po_attempts": {}}


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    # OneDrive가 방금 쓴 파일을 잠깐 잡고 있으면 os.replace가 PermissionError를 낸다
    for i in range(6):
        try:
            os.replace(tmp, STATE_PATH)
            return
        except PermissionError:
            time.sleep(0.5 * (i + 1))
    # 끝내 안 되면 직접 덮어쓴다(이 파일은 이 스크립트만 쓰고, 잠금으로 동시 실행도 막혀 있다)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_release_state():
    try:
        with open(RELEASE_STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def done_statuses():
    """처리 완료 상태 목록은 fse_po_release.py의 것을 그대로 쓴다(복붙하면 서로 어긋난다)."""
    try:
        import fse_po_release
        return tuple(fse_po_release.DONE_STATUSES)
    except Exception as e:
        log(f"[경고] DONE_STATUSES import 실패({e}) - 보수적 기본값 사용")
        return ("released", "skipped_billable", "skipped_closed", "skipped_already_sent",
                "mail_sent_release_pending", "release_failed_final", "shipline_failed")


def load_engineers():
    """엔지니어 매핑 {이메일(소문자): 영문이름}. fse_po_release.py의 발신자 표(_SENDER_TABLE,
    FSE PO 폴더 발신자 전수조사 기반)를 그대로 쓴다. 퇴사자(유창규/한재환/김요한)도 들어
    있지만 개인톡을 보낼 일이 없어 무해하다. 새 엔지니어가 오면 그 표에 추가하면 여기도 반영된다.
    표를 못 읽으면 엉뚱한 사람 메시지를 처리하느니 이번 회차를 중단한다."""
    import fse_po_release
    return {e.lower(): n for n, e in fse_po_release._SENDER_TABLE}


def is_direct_chat(m):
    """1:1 개인톡 여부. Teams chatId가 ...@unq.gbl.spaces면 1:1, ...@thread.v2면 그룹/채널/회의."""
    chat = str(m.get("chat_id") or m.get("chat") or "")
    return "@unq.gbl.spaces" in chat


# ------------------------------------------------------------------ 단일 실행 잠금
def acquire_single_instance():
    import msvcrt
    f = open(LOCK_PATH, "a+")
    try:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


# ------------------------------------------------------------------ Teams 읽기 (헤드리스 claude)
PROMPT = """Microsoft 365 Teams 메시지 검색 도구(chat_message_search)를 사용해라.
afterDateTime={after} (KST) 이후에 온 Teams 메시지를 query "*" 로 전부 가져와라
(한 페이지는 최대 25건이다. nextOffset이 있으면 없어질 때까지 반드시 다음 페이지를 계속 가져와라,
최대 8페이지). 단 chatId가 "@thread.v2"로 끝나는 메시지(그룹 채팅/채널/회의)는 결과에서 제외하고,
chatId가 "@unq.gbl.spaces"로 끝나는 1:1 개인톡 메시지만 남겨라. 1:1 안의 잡담은 빼지 말고 전부 포함해라.
{self_email} 이 보낸 메시지는 제외해라.

결과는 설명 없이 JSON 배열만 출력해라. 각 원소는 다음 키를 가진다:
  "id": 메시지 id (문자열),
  "chat_id": chatId 원문 (예: 19:...@unq.gbl.spaces 또는 19:...@thread.v2. 가공 금지),
  "sender_name": 보낸 사람 이름,
  "sender_email": 보낸 사람 이메일,
  "sent_kst": "YYYY-MM-DD HH:MM:SS" (UTC로 오면 +9시간 해서 KST로),
  "text": 메시지 본문(summary)을 가공하지 말고 그대로.
메시지가 없으면 [] 만 출력해라. 도구를 쓸 수 없으면 NO_TOOL 만 출력해라."""


def fetch_teams_messages(after_dt):
    prompt = PROMPT.format(after=after_dt.strftime("%Y-%m-%d %H:%M:%S"), self_email=MY_EMAIL)
    # 프롬프트는 stdin으로 넘긴다(인자로 주면 공백/한글에서 잘려 엉뚱한 요청이 된다).
    proc = subprocess.run(
        [CLAUDE_EXE, "-p", "--allowedTools", "mcp__claude_ai_Microsoft_365__chat_message_search"],
        input=prompt, capture_output=True, text=True, encoding="utf-8",
        cwd=CLAUDE_CWD, timeout=CLAUDE_TIMEOUT_SEC)
    out = (proc.stdout or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(f"claude 종료코드 {proc.returncode}: {(proc.stderr or out)[:300]}")
    if out.startswith("NO_TOOL") or "NO_TOOL" == out:
        raise RuntimeError("헤드리스 claude에서 Teams 검색 도구를 못 씀(커넥터 미연결)")
    start, end = out.find("["), out.rfind("]")
    if start < 0 or end < start:
        raise RuntimeError(f"JSON 배열을 못 찾음: {out[:300]}")
    msgs = json.loads(out[start:end + 1])
    if not isinstance(msgs, list):
        raise RuntimeError("JSON 최상위가 배열이 아님")
    return msgs


# ------------------------------------------------------------------ 처리
def run_direct(po_no):
    log(f"  -> fse_po_release.py direct {po_no} 실행")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    proc = subprocess.run([sys.executable, RELEASE_SCRIPT, "direct", po_no],
                          capture_output=True, text=True, encoding="utf-8", errors="replace",
                          cwd=SCRIPT_DIR, env=env, timeout=DIRECT_TIMEOUT_SEC)
    tail = "\n".join((proc.stdout or "").strip().splitlines()[-8:])
    log(f"  -> direct 종료코드 {proc.returncode}\n{tail}")
    return proc.returncode


def note_exception(m, reason):
    with open(EXCEPTIONS_PATH, "a", encoding="utf-8") as f:
        f.write(f"[{m.get('sent_kst', '?')}] {m.get('sender_name', '?')} - {reason}\n"
                f"    {str(m.get('text', '')).strip()[:300]}\n")


def handle_message(m, state, done, live, engineers):
    mid = str(m.get("id"))
    text = str(m.get("text", ""))
    sender = f"{m.get('sender_name', '?')} {m.get('sent_kst', '')}"
    pos = list(dict.fromkeys(PO_RE.findall(text)))
    results = {}

    # 그룹 채팅/채널은 보지 않는다(2026-10-07 사용자 지시: 잡담은 읽지 말고 엔지니어 개인톡만).
    # 프롬프트에서도 제외시키지만 LLM이 흘릴 수 있어 여기서 한 번 더 거른다.
    if not is_direct_chat(m):
        results["_"] = "group_ignored"
        return results

    # 개인톡이지만 엔지니어 표에 없는 사람(예: 영업지원팀)은 자동 처리하지 않는다.
    # 단 PO 번호/문의 키워드가 있으면 놓치지 않게 사람 확인 목록에는 올린다.
    if (m.get("sender_email") or "").lower() not in engineers:
        if pos or KEYWORD_RE.search(text):
            log(f"[비엔지니어 개인톡] {sender}: {text[:80]!r}")
            note_exception(m, "엔지니어 아닌 사람의 개인톡(자동처리 안 함) - 사람 확인")
            results["_"] = "non_engineer_dm"
        else:
            results["_"] = "ignored"
        return results

    if not pos:
        if KEYWORD_RE.search(text):
            log(f"[확인필요] {sender}: PO 번호 없음 - {text[:80]!r}")
            note_exception(m, "PO 번호 없는 문의 - 사람 확인")
            results["_"] = "needs_human"
        else:
            results["_"] = "ignored"
        return results

    rel = load_release_state()
    for po in pos:
        st = (rel.get(po) or {}).get("status")
        if st in done:
            log(f"[이미처리] {sender}: PO {po} 상태={st}")
            results[po] = f"already_done:{st}"
            continue

        attempts = state["po_attempts"].setdefault(po, {"date": "", "n": 0})
        today = time.strftime("%Y-%m-%d")
        if attempts["date"] != today:
            attempts.update(date=today, n=0)

        if not live:
            log(f"[SHADOW] {sender}: PO {po} 상태={st or '없음'} -> live였다면 direct 실행했을 것")
            results[po] = f"would_run_direct:{st or 'none'}"
            continue

        if attempts["n"] >= MAX_LIVE_ATTEMPTS_PER_PO:
            log(f"[한도] PO {po}: 오늘 direct {attempts['n']}회 시도함 - 사람 확인으로 넘김")
            note_exception(m, f"PO {po} direct 오늘 {attempts['n']}회 시도했으나 미완료(상태={st})")
            results[po] = "attempt_limit"
            continue

        attempts["n"] += 1
        save_state(state)
        try:
            rc = run_direct(po)
        except subprocess.TimeoutExpired:
            log(f"[오류] PO {po}: direct 시간 초과")
            note_exception(m, f"PO {po} direct 시간 초과 - 사람 확인")
            results[po] = "direct_timeout"
            continue
        after = (load_release_state().get(po) or {}).get("status")
        log(f"[완료] PO {po}: direct rc={rc}, 상태 {st or '없음'} -> {after or '없음'}")
        if after not in done:
            note_exception(m, f"PO {po} direct 후에도 미완료(상태={after}) - 사람 확인")
        results[po] = f"direct_rc{rc}:{after}"
    return results


def in_window(now):
    if now.weekday() >= 5:
        return False
    cur = (now.hour, now.minute)
    return WINDOW_START <= cur <= WINDOW_END


def parse_args(argv):
    args = {"live": "--live" in argv, "force": "--force" in argv, "since": None}
    if "--since" in argv:
        args["since"] = datetime.strptime(argv[argv.index("--since") + 1], "%Y-%m-%d %H:%M")
    return args


def main():
    args = parse_args(sys.argv[1:])
    now = datetime.now()
    if not args["force"] and not in_window(now):
        return  # 시간창 밖은 조용히 종료(로그도 안 남김 - 로그가 불어나지 않게)

    lock = acquire_single_instance()
    if lock is None:
        log("이미 다른 teams_po_watcher가 실행 중 - 이번 회차는 건너뜀")
        return

    state = load_state()
    mode = "LIVE" if args["live"] else "SHADOW"
    if args["since"]:
        after = args["since"]
    elif state.get("last_checked"):
        after = datetime.fromisoformat(state["last_checked"]) - timedelta(minutes=OVERLAP_MIN)
    else:
        after = now - timedelta(minutes=FIRST_RUN_LOOKBACK_MIN)
    log(f"[{mode}] Teams 조회 시작: {after:%Y-%m-%d %H:%M} 이후")

    fetch_started = datetime.now()
    try:
        msgs = fetch_teams_messages(after)
    except Exception as e:
        # last_checked를 갱신하지 않으므로 다음 회차가 같은 구간을 다시 읽는다.
        log(f"[오류] Teams 읽기 실패: {e}")
        sys.exit(1)
    log(f"메시지 {len(msgs)}건 수신")

    done = done_statuses()
    try:
        engineers = load_engineers()
    except Exception as e:
        log(f"[오류] 엔지니어 표 로드 실패 - 이번 회차 중단: {e}")
        sys.exit(1)
    for m in msgs:
        mid = str(m.get("id"))
        if not mid or mid in state["seen"]:
            continue
        if (m.get("sender_email") or "").lower() == MY_EMAIL:
            state["seen"][mid] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "result": "self"}
            continue
        try:
            res = handle_message(m, state, done, args["live"], engineers)
        except Exception as e:
            # seen에 넣지 않아 다음 회차에 재시도된다
            log(f"[오류] 메시지 {mid} 처리 실패: {e}")
            continue
        state["seen"][mid] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "result": res,
                              "sender": m.get("sender_name"), "sent_kst": m.get("sent_kst")}
        save_state(state)

    # 7일 지난 seen 정리
    cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    state["seen"] = {k: v for k, v in state["seen"].items() if v.get("at", "") >= cutoff}
    if not args["since"]:
        state["last_checked"] = fetch_started.isoformat(timespec="seconds")
    save_state(state)


if __name__ == "__main__":
    main()
