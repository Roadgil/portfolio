"""
IR/Intransit 통합파일 외부 링크(실적파일 참조) 복구 도우미
- 2026-09-29 발견: Excel은 외부 링크 경로를 2개(rId1=상대경로, rId2=SharePoint URL)로
  저장하는데 openpyxl로 저장하면 rId2 하나만 남는다. 그런데 링크 본문(externalBook)은
  여전히 rId1을 가리키므로, 다음에 Excel로 열 때 "복구"되면서 링크가
  RecoveredExternalLink1(경로 없음)로 끊긴다 → Urgent Item J열(용마입고날짜)이
  실적파일 최신값을 못 읽고 옛 캐시(0)를 보여줌.
- openpyxl 저장 직후 fix_external_links(path)를 호출하면, 본문이 가리키는 Id로
  상대경로 링크를 다시 써준다. (정상이면 아무것도 안 바꿈)
"""

import os
import re
import tempfile
import urllib.parse
import zipfile
from xml.sax.saxutils import escape

LINK_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/externalLinkPath"

# 경로 정보가 완전히 사라진 경우(RecoveredExternalLink) 링크 시트명으로 원래 파일명을 찾는다
KNOWN_LINK_TARGETS = {
    "수입신고실적(20260211)": "수입신고실적(20260211)자동화.xlsx",
}


def _attr(s, name):
    m = re.search(rf'\b{name}="([^"]*)"', s)
    return m.group(1) if m else None


def fix_external_links(path):
    """고친 링크 설명 리스트를 반환 (빈 리스트면 이상 없음)."""
    fixes = []
    replace = {}
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        for n in sorted(names):
            m = re.fullmatch(r"xl/externalLinks/(externalLink\d+)\.xml", n)
            if not m:
                continue
            rel_name = f"xl/externalLinks/_rels/{m.group(1)}.xml.rels"
            if rel_name not in names:
                continue
            body = z.read(n).decode("utf-8")
            b = re.search(r'<externalBook\b[^>]*\br:id="([^"]+)"', body)
            if not b:
                continue
            rid = b.group(1)
            rels = re.findall(r"<Relationship\b[^>]*/>", z.read(rel_name).decode("utf-8"))
            if any(_attr(r, "Id") == rid and _attr(r, "Type") == LINK_TYPE for r in rels):
                continue  # 정상

            target = None
            for r in rels:
                t = _attr(r, "Target") or ""
                if t.lower().endswith((".xlsx", ".xlsm", ".xls")):
                    target = urllib.parse.unquote(t.replace("\\", "/").split("/")[-1])
                    break
            if target is None:
                sheet = re.search(r'<sheetName val="([^"]*)"', body)
                target = KNOWN_LINK_TARGETS.get(sheet.group(1) if sheet else "")
            if target is None:
                fixes.append(f"{m.group(1)}: 원래 파일명을 알 수 없어 복구 못 함")
                continue

            replace[rel_name] = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="{rid}" Type="{LINK_TYPE}" Target="{escape(target)}" TargetMode="External"/>'
                "</Relationships>"
            ).encode("utf-8")
            fixes.append(f"{m.group(1)}: {rid} → {target}")

        if not replace:
            return fixes

        fd, tmp = tempfile.mkstemp(suffix=".xlsx", dir=os.path.dirname(path))
        os.close(fd)
        try:
            with zipfile.ZipFile(tmp, "w") as out:
                for info in z.infolist():
                    data = replace.get(info.filename)
                    out.writestr(info, data if data is not None else z.read(info.filename))
        except Exception:
            os.remove(tmp)
            raise

    os.replace(tmp, path)
    return fixes


if __name__ == "__main__":
    import sys
    for p in sys.argv[1:]:
        print(p, fix_external_links(p) or "이상 없음")
