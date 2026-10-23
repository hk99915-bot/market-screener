"""사내톡 피드(scripts/msgr_feed.py)·회신(scripts/ask.py --reply) — 10/23 겸이 '사내톡 탭, 실제 누나들의 voc로'."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ask  # noqa: E402
import msgr_feed  # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 23, 17, 0, tzinfo=KST)


def _ledger():
    return {"requests": [
        {"id": "req-dev-aaaaaaaa", "from": "pb", "to": "dev", "text": "탭 추가", "opened": "2026-10-22",
         "opened_at": "2026-10-22T10:00+09:00", "status": "open"},
        {"id": "req-data-bbbbbbbb", "from": "quant", "to": "data", "text": "백필", "opened": "2026-10-23",
         "opened_at": "2026-10-23T12:40+09:00", "status": "done", "done_by": "데이터"},
    ]}


def test_reply_voc_flag_and_unknown(tmp_path):
    L, r = ask.reply(_ledger(), "req-dev-aaaaaaaa", "개발", "내일 오전까지 올릴게요", True, NOW)
    p = r["replies"][-1]
    assert p["by"] == "dev" and p["voc"] is True and p["at"].startswith("2026-10-23T17:00")
    try:
        ask.reply(_ledger(), "req-x-00000000", "개발", "x", False, NOW)
        assert False
    except KeyError:
        pass


def test_build_merges_round_lines_as_proxy(tmp_path):
    (tmp_path / "2026-10-23-msg-1241.md").write_text(
        "# 라운드\n\n## 보류\n- `req-dev-aaaaaaaa` (pb→dev): 큰 개발 → 다음 라운드\n", encoding="utf-8")
    L, _ = ask.reply(_ledger(), "req-data-bbbbbbbb", "데이터", "백필 끝", True, NOW)
    f = msgr_feed.build(L, tmp_path, NOW)
    assert f["n"] == 2 and f["n_voc"] == 1 and f["n_reply"] == 2
    assert f["items"][0]["id"] == "req-data-bbbbbbbb"            # 최신 요청 먼저
    dev = next(x for x in f["items"] if x["id"] == "req-dev-aaaaaaaa")
    assert dev["replies"][0]["voc"] is False and dev["replies"][0]["by"] == "dev"
    assert dev["replies"][0]["text"].startswith("큰 개발")
    json.dumps(f, ensure_ascii=False)
