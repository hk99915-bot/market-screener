import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import kofia_notice as kn  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "kofia_notice_list.html"


def test_parse_and_tag():
    rows = kn.parse(FIX.read_text(encoding="utf-8"))
    assert rows[0]["seq"] == 2403 and len(rows) == 4
    r0 = rows[0]
    assert r0["date"] == "2026-11-02" and r0["files"] >= 1 and r0["link"].endswith("view.do?seq=2403")
    assert kn.classify(r0["title"])["tags"] == ["시총비중"]
    assert kn.classify("[입찰공고] 비상장주식 공동평가 용역 사업자 선정") is None
    c = kn.classify("2027년 투자자산운용사 시험 일정 안내")
    assert c["exam_schedule"] and "자격시험" in c["tags"]


def test_merge_dedup():
    rows = kn.parse(FIX.read_text(encoding="utf-8"))
    d = {"state": {"seen": []}, "items": []}
    now = datetime(2026, 11, 3)
    d, added, n = kn.merge(d, rows, now)
    assert n == len(rows) and len(added) == 2
    d, added2, n2 = kn.merge(d, rows, now)
    assert n2 == 0 and added2 == [] and len(d["items"]) == 2
