"""local_config.json의 target_folders에 지정된 폴더들(기본값: OM > Parts Order,
OM > 출고)을 스캔해 신규 출고요청 메일을 찾아 parser.py로 구조화한 뒤
ready(자동생성 가능) / review(사람 확인 필요)로 분류한다.

- 두 폴더 모두 대상으로 하되, 같은 건이 "출고" 폴더에 RE:로 다시 나타나는
  중복을 막기 위해 Outlook의 ConversationTopic(스레드 제목, RE:/FW: 제거됨)
  기준으로 같은 스레드는 가장 먼저 도착한 항목 하나만 채택한다.
- 이미 처리한 스레드는 processed_log.json에 기록해 재실행 시 건너뛴다.
- 오늘 날짜 항목만 훑어본다 (과거 수천 건을 매번 다시 읽지 않기 위한
  테스트 단계용 제한 - 운영 전환 시 정책 재검토 필요).
- 이 스크립트는 Outlook을 읽기만 하며 아무 것도 수정/삭제하지 않는다.
"""

import json
import os
from datetime import datetime, timedelta

import win32com.client

import local_config
from parser import parse_email_body

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROCESSED_LOG_PATH = os.path.join(SCRIPT_DIR, "processed_log.json")
OUTPUT_PATH = os.path.join(SCRIPT_DIR, "scan_result.json")

LOOKBACK_DAYS = 1  # 오늘 기준 최근 N일 (테스트용 제한)


def find_folder(root, path_names):
    folder = root
    for name in path_names:
        found = None
        for sub in folder.Folders:
            if sub.Name == name:
                found = sub
                break
        if found is None:
            return None
        folder = found
    return folder


def load_processed_log():
    if os.path.exists(PROCESSED_LOG_PATH):
        with open(PROCESSED_LOG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_processed_log(log):
    with open(PROCESSED_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def collect_candidates(folder, cutoff_date):
    """폴더에서 cutoff_date 이후 항목만 최신순으로 수집한다."""
    items = folder.Items
    items.Sort("[ReceivedTime]", True)  # 최신순 정렬 -> cutoff 이전이면 조기 종료 가능

    candidates = []
    for item in items:
        try:
            if item.Class != 43:  # olMail이 아니면 스킵
                continue
            received = item.ReceivedTime
        except Exception:
            continue

        received_date = received.date() if hasattr(received, "date") else None
        if received_date is not None and received_date < cutoff_date:
            break  # 최신순 정렬이므로 여기서부터는 더 오래된 항목들 -> 중단

        try:
            topic = item.ConversationTopic
            subject = item.Subject
            body = item.Body
            entry_id = item.EntryID
        except Exception:
            continue

        candidates.append({
            "topic": topic,
            "subject": subject,
            "body": body,
            "received": str(received),
            "entry_id": entry_id,
        })

    return candidates


def signature_for(parsed):
    """같은 주문인지 판단하는 키. 이메일 스레드 제목이 아니라 실제 파싱된
    핵심 내용(병원명+내역+결제일자+금액)으로 판단한다 - 회신 메일이 제목에
    "- 택배 7/7" 같은 문구를 붙이면 스레드 제목 매칭이 깨지기 때문."""
    return "|".join([
        str(parsed.get("hospital_name", "")),
        str(parsed.get("item_raw", "")),
        str(parsed.get("payment_date", "")),
        str(parsed.get("amount", "")),
    ])


def main(lookback_days=None):
    """lookback_days: 주어지면 LOOKBACK_DAYS 대신 이 값을 쓴다 (예: 무인 배치는
    사람이 매일 실행을 보장하지 않으므로 더 넉넉한 기간을 넘겨서 호출함).
    signature_for() 기반 dedup이 있어 기간을 넓게 잡아 재스캔해도 중복 생성되지
    않는다."""
    config = local_config.load()
    outlook = win32com.client.Dispatch("Outlook.Application")
    ns = outlook.GetNamespace("MAPI")
    store = ns.Folders[config["outlook_mailbox"]]
    inbox_parent = store.Folders["받은 편지함"]

    effective_lookback_days = lookback_days if lookback_days is not None else LOOKBACK_DAYS
    cutoff_date = (datetime.now() - timedelta(days=effective_lookback_days - 1)).date()

    all_candidates = []
    for path in config["target_folders"]:
        folder = find_folder(inbox_parent, path)
        if folder is None:
            print(f"[경고] 폴더를 찾지 못함: {' > '.join(path)}")
            continue
        found = collect_candidates(folder, cutoff_date)
        print(f"[{' > '.join(path)}] 최근 {effective_lookback_days}일 후보 {len(found)}건")
        all_candidates.extend(found)

    all_candidates.sort(key=lambda c: c["received"])  # 오래된 것(원본 가능성 높은 것)부터

    processed_log = load_processed_log()  # signature -> {status, topic, received}
    seen_review_topics = set()

    ready = []
    review = []
    duplicates = []

    for c in all_candidates:
        parsed = parse_email_body(c["body"])
        is_valid = "error" not in parsed and not any(
            u.startswith("필수 필드 누락") for u in parsed.get("unparsed", [])
        )

        record = {
            "topic": c["topic"],
            "subject": c["subject"],
            "received": c["received"],
            "entry_id": c["entry_id"],
            "parsed": parsed,
        }

        if is_valid:
            sig = signature_for(parsed)
            if sig in processed_log:
                record["duplicate_of_topic"] = processed_log[sig].get("topic")
                duplicates.append(record)
                continue
            ready.append(record)
            processed_log[sig] = {"status": "ready", "topic": c["topic"], "received": c["received"]}
        else:
            # review 항목은 내용이 불완전해 신뢰할 만한 서명을 만들 수 없으므로
            # 스레드 제목으로만 대략 중복을 거른다 (완벽하지 않음 - 사람이 어차피 확인함)
            if c["topic"] in processed_log or c["topic"] in seen_review_topics:
                continue
            seen_review_topics.add(c["topic"])
            review.append(record)
            processed_log[c["topic"]] = {"status": "review", "received": c["received"]}

    save_processed_log(processed_log)

    result = {"ready": ready, "review": review, "duplicates": duplicates}
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"\n신규 - 자동생성 가능(ready): {len(ready)}건")
    print(f"신규 - 확인 필요(review): {len(review)}건")
    print(f"중복으로 제외(duplicates): {len(duplicates)}건")
    print(f"\n결과 저장: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
