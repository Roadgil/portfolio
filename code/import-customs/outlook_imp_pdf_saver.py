import os
import re
import json
from datetime import datetime, timedelta
import win32com.client

# ==============================
# 설정
# ==============================
SAVE_DIR = r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입\수입신고필증_자동화"

LOOKBACK_DAYS = 30
FILENAME_PREFIX = "_IMP_"
FILENAME_EXT = ".pdf"

# ✅ 받은편지함 바로 아래 '인천관세법인'
TARGET_SUBFOLDER_PATH = r"인천관세법인"

STATE_FILE = os.path.join(SAVE_DIR, "_outlook_saver_state.json")
STATE_KEY_LAST_RUN = "last_run_iso"

# ✅ 디버그 로그(왜 스킵됐는지 보고 싶으면 True)
DEBUG_LOG = True


def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def outlook_dt_to_py(dt) -> datetime:
    # Outlook COM datetime -> python datetime (초 단위까지만)
    return datetime(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)


def get_inbox_subfolder(outlook_ns, sub_path: str):
    """Inbox(받은편지함) 기준으로 sub_path를 타고 들어감"""
    inbox = outlook_ns.GetDefaultFolder(6)  # 받은편지함
    cur = inbox
    for part in [p for p in sub_path.split("\\") if p.strip()]:
        found = None
        for f in cur.Folders:
            if str(f.Name).strip() == part.strip():
                found = f
                break
        if not found:
            raise ValueError(f"폴더를 찾을 수 없음: Inbox\\{sub_path} (실패 구간: {part})")
        cur = found
    return cur


def _is_target_attachment(filename: str) -> bool:
    if not filename:
        return False
    fn = str(filename).strip()
    upper = fn.upper()
    if not (upper.startswith("_IMP_") or upper.startswith("IMP_")):
        return False
    if not fn.lower().endswith(FILENAME_EXT):
        return False
    return True

def main():
    print(f"Outlook PDF 저장 시작 | Inbox\\{TARGET_SUBFOLDER_PATH}")
    os.makedirs(SAVE_DIR, exist_ok=True)

    state = load_state()
    now = datetime.now()

    # 안전장치: 너무 오래된 메일은 안 훑도록
    safety_cutoff = now - timedelta(days=LOOKBACK_DAYS)
    last_run_iso = state.get(STATE_KEY_LAST_RUN)

    if last_run_iso:
        try:
            last_run_dt = datetime.fromisoformat(last_run_iso)
        except Exception:
            last_run_dt = safety_cutoff
    else:
        last_run_dt = safety_cutoff

    cutoff = max(last_run_dt, safety_cutoff)
    print(f"- 기준시간(이 이후 메일만): {cutoff}")
    print(f"- 저장경로: {SAVE_DIR}")
    print("- 동작: 조건에 맞는 첨부는 '전부 저장' (동일 파일명은 덮어쓰기)")

    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")

    target_folder = get_inbox_subfolder(outlook, TARGET_SUBFOLDER_PATH)
    print(f"- 대상폴더: {target_folder.FolderPath}")

    items = target_folder.Items
    # 최신 메일부터
    items.Sort("[ReceivedTime]", True)

    saved = 0
    scanned_mails = 0
    latest_seen_dt = None  # 이번 실행에서 본 메일 중 가장 최신 ReceivedTime

    for mail in items:
        try:
            if getattr(mail, "Class", None) != 43:  # MailItem
                continue

            received_dt = outlook_dt_to_py(mail.ReceivedTime)

            # cutoff보다 과거면 더 볼 필요 없음(정렬이 최신->과거라 break)
            if received_dt < cutoff:
                if DEBUG_LOG:
                    print(f"[STOP] {received_dt} < cutoff {cutoff}")
                break

            scanned_mails += 1
            if (latest_seen_dt is None) or (received_dt > latest_seen_dt):
                latest_seen_dt = received_dt

            if mail.Attachments.Count == 0:
                if DEBUG_LOG:
                    subj = getattr(mail, "Subject", "")
                    print(f"[SKIP] 첨부없음 | {received_dt} | {subj}")
                continue

            subj = getattr(mail, "Subject", "")
            if DEBUG_LOG:
                print(f"[MAIL] {received_dt} | att={mail.Attachments.Count} | {subj}")

            for i in range(1, mail.Attachments.Count + 1):
                att = mail.Attachments.Item(i)
                fn = (att.FileName or "").strip()

                if not _is_target_attachment(fn):
                    if DEBUG_LOG:
                        print(f"  - [SKIP ATT] {fn!r} (prefix/ext 불일치)")
                    continue

                save_name = safe_filename(fn)
                save_path = os.path.join(SAVE_DIR, save_name)

                # ✅ 동일 파일명은 덮어쓰기(수정신고는 이전 파일 불필요 정책)
                try:
                    if os.path.exists(save_path):
                        os.remove(save_path)
                except Exception as e:
                    if DEBUG_LOG:
                        print(f"  - [WARN] 기존 파일 삭제 실패: {save_name} | {e}")

                att.SaveAsFile(save_path)

                print(f"  - 저장 완료: {save_name}")
                saved += 1

        except Exception as e:
            print("오류:", e)

    # ✅ 상태 저장: latest_seen_dt 기반인데, 같은 초(ReceivedTime 동일)인 메일이 여러 통이면
    # 다음 실행에서 누락될 수 있으니 1초 되돌려 저장(안전 마진)
    if latest_seen_dt is not None:
        safe_last_run = latest_seen_dt - timedelta(seconds=1)
        state[STATE_KEY_LAST_RUN] = safe_last_run.isoformat(timespec="seconds")
        save_state(state)
        print(f"- 상태 저장(last_run, -1s safety): {state[STATE_KEY_LAST_RUN]}")
    else:
        print("- 처리한 메일이 없어 상태를 갱신하지 않았습니다.")

    print(f"총 저장된 파일: {saved} | 스캔한 메일: {scanned_mails}")


if __name__ == "__main__":
    main()
