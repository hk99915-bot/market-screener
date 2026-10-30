"""pb_call 텔레그램 HTML 이스케이프 — payload why/lines/tg 의 '<' 가 400 'Unsupported start tag' 로 번지지 않게
+ 전송이 실패해도 기록(decisions.json)은 남는다 (req-dev-472431f7, 10/30 run 41010299116)."""
import json
import re

import pytest

from screener import decisions, duel, report


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(decisions, "OUT", tmp_path / "decisions.json")
    monkeypatch.setattr(duel, "mark_crash_day", lambda *a, **k: None)
    monkeypatch.setattr(duel, "is_crash_day", lambda d: False)
    import screener.views as views
    monkeypatch.setattr(views, "compact", lambda: {})
    return tmp_path


PAYLOAD = {"pick": {"cash": True}, "why": "코스피 PER < 10 이고 a<b 구간", "tg": "변동성 <5% 면 관망",
           "lines": ["VIX<20 유지", "<script>x</script> & 금리"], "conviction": "중",
           "bold": {"cash": True, "why": "손절 <3% 조건"}, "real": {"ok": True, "note": "비중 <10%"}}


def _bad_tags(body):
    allowed = {"b", "a", "i", "u", "s", "code", "pre"}
    return [t for t in re.findall(r"</?([A-Za-z][\w-]*)", body) if t.lower() not in allowed]


def test_user_text_is_escaped(env, monkeypatch):
    sent = []
    monkeypatch.setattr(report, "send_telegram", lambda body, **k: sent.append(body))
    duel.record_pb(PAYLOAD, send=True)
    body = sent[0]
    assert not _bad_tags(body), body            # <script> 같은 비허용 태그가 그대로 나가면 Telegram 이 400
    assert "PER &lt; 10" in body and "&lt;5%" in body and "VIX&lt;20" in body and "&amp; 금리" in body
    assert "<b>PB 판단</b>" in body             # 우리가 붙인 태그는 그대로


def test_record_survives_send_failure(env, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("400 Unsupported start tag")
    monkeypatch.setattr(report, "send_telegram", boom)
    out = duel.record_pb(PAYLOAD, send=True)      # 예외로 죽지 않는다 → 워크플로 커밋 단계가 돈다
    assert "전송 실패" in out
    data = json.loads((env / "decisions.json").read_text(encoding="utf-8"))
    it = next(x for x in data["items"] if x["id"].endswith("-entry"))
    assert it["picks"]["PB"]["cash"] and it["pb_view"]["why"].startswith("코스피 PER < 10")   # 원문은 그대로 저장
