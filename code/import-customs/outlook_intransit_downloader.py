import os
import re
from datetime import datetime, timedelta
import win32com.client

# ==============================
# 설정
# ==============================
SAVE_DIR = r"C:\Users\yoongil.chae\OneDrive - Candela\Syneron-Candela Korea - Operation\10. 수입\Intransit Details Report"

# ✅ 폴더 경로 (받은편지함 아래)
FOLDER_PATH = ["Operation", "Intransit Details Report"]

TARGET_ATTACHMENT_NAME = "APAC Candela Intransit Details Report.xlsx"

# 최근 N일 이내 메일만 확인 (휴가 등 공백 + 여유). 너무 오래된 메일은 안 훑음.
LOOKBACK_DAYS = 60

# ==============================
# 유틸
# ==============================
def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name)

def to_py_datetime(outlook_dt) -> datetime:
    return datetime(
        outlook_dt.year, outlook_dt.month, outlook_dt.day,
        outlook_dt.hour, outlook_dt.minute, outlook_dt.second
    )

def find_subfolder(parent_folder, target_name: str):
    target = target_name.strip().lower()
    for f in parent_folder.Folders:
        if str(f.Name).strip().lower() == target:
            return f
    return None

def get_folder_by_path(root_folder, path_list):
    """root_folder 아래에서 path_list 순서대로 폴더를 찾아 내려감"""
    cur = root_folder
    for name in path_list:
        nxt = find_subfolder(cur, name)
        if nxt is None:
            return None, name, cur
        cur = nxt
    return cur, None, None

# ==============================
# 메인
# ==============================
def main():
    os.makedirs(SAVE_DIR, exist_ok=True)
    print(f"[INFO] Intransit Report 미저장분 전부 다운로드 시작 (최근 {LOOKBACK_DAYS}일)")

    outlook = win32com.client.Dispatch("Outlook.Application").GetNamespace("MAPI")
    inbox = outlook.GetDefaultFolder(6)  # 받은편지함

    target_folder, missing_name, parent = get_folder_by_path(inbox, FOLDER_PATH)
    if target_folder is None:
        parent_name = "(Inbox)" if parent is None else str(parent.Name)
        print(f"[ERROR] 폴더를 찾을 수 없습니다: '{missing_name}' (부모: {parent_name})")
        print(f"[HINT] 현재 설정 경로: Inbox -> " + " -> ".join(FOLDER_PATH))
        return

    items = target_folder.Items
    items.Sort("[ReceivedTime]", True)  # 최신순

    if items.Count == 0:
        print("[INFO] 폴더에 메일이 없습니다.")
        return

    cutoff = datetime.now() - timedelta(days=LOOKBACK_DAYS)
    base_name, ext = os.path.splitext(TARGET_ATTACHMENT_NAME)

    saved, skipped, no_att = 0, 0, 0

    # 최신순으로 훑되, 이미 저장된 날짜는 건너뛰고 빠진 날짜만 저장.
    # (파일 존재 여부로 판단 → 몇 번을 돌려도 안전, 휴가 후 한 번이면 공백 메움)
    for i in range(1, items.Count + 1):
        try:
            mail = items.Item(i)
        except Exception:
            continue

        if getattr(mail, "Class", None) != 43:  # MailItem
            continue

        received_dt = to_py_datetime(mail.ReceivedTime)

        # 최신순 정렬이라, cutoff보다 과거가 나오면 그 뒤는 더 볼 필요 없음
        if received_dt < cutoff:
            break

        date_suffix = received_dt.strftime("%Y%m%d")
        out_name = safe_filename(f"{base_name}_{date_suffix}{ext}")
        out_path = os.path.join(SAVE_DIR, out_name)

        # 이미 그 날짜 스냅샷이 저장돼 있으면 skip
        if os.path.exists(out_path):
            skipped += 1
            continue

        if mail.Attachments.Count == 0:
            no_att += 1
            continue

        done = False
        for j in range(1, mail.Attachments.Count + 1):
            att = mail.Attachments.Item(j)
            if str(att.FileName).strip() == TARGET_ATTACHMENT_NAME:
                att.SaveAsFile(out_path)
                print(f"[SAVE] {out_name}")
                saved += 1
                done = True
                break
        if not done:
            no_att += 1
            print(f"[INFO] {date_suffix} 메일에 대상 첨부 없음")

    print(f"[DONE] 신규 저장 {saved}건 / 이미 있어 skip {skipped}건 / 대상첨부 없음 {no_att}건")

if __name__ == "__main__":
    main()
