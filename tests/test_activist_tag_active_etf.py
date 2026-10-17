"""행동주의 뉴스 태그 · 액티브 ETF 보유 합의도 (10/17 축소판) — 픽스처만, 네트워크 없음."""
import json

from screener import drivers, etf
from screener.news import ACTIVIST_LABEL, activist_tag


def test_activist_tag_kr_us():
    assert activist_tag("얼라인파트너스, 주주서한 공개") == ACTIVIST_LABEL
    assert activist_tag("KCGI 주주제안 제출") == ACTIVIST_LABEL
    assert activist_tag("Elliott Management builds stake in X") == ACTIVIST_LABEL
    assert activist_tag("Activist investor Starboard pushes board changes") == ACTIVIST_LABEL
    assert activist_tag("Fund files Schedule 13D") == ACTIVIST_LABEL
    assert activist_tag("삼성전자 3분기 실적 개선") is None
    assert activist_tag("Pershing hires new CFO") is None   # Pershing Square 만
    assert activist_tag("") is None and activist_tag(None) is None


def test_news_events_label_not_scored():
    titles = [{"title": "트러스톤, 태광산업에 주주서한", "date": "2026-10-16", "link": "u1"},
              {"title": "A사 수주 공급 계약 체결", "date": "2026-10-16", "link": "u2"}]
    out = drivers.news_events(titles, None)
    assert [a["title"] for a in out["activist"]] == ["트러스톤, 태광산업에 주주서한"]
    assert out["recent"][0]["tag"] == ACTIVIST_LABEL and "tag" not in out["recent"][1]
    base = drivers.news_events(titles[1:], None)
    assert out["score"] == base["score"] and out["n_scored"] == base["n_scored"]   # 점수 합산 없음
    assert "activist" not in base


def _snap(asof, close, hold):
    return {"asof": asof, "etfs": {e: {"close": close[e], "holdings": h} for e, h in hold.items()}}


def test_active_consensus_count_and_price_effect():
    e1, e2 = "385720", "494890"
    prev = _snap("2026-10-16", {e1: 100.0, e2: 100.0}, {
        e1: {"005930": {"name": "삼성전자", "w": 0.20, "px": 100.0}, "000660": {"name": "SK하이닉스", "w": 0.10, "px": 100.0}},
        e2: {"005930": {"name": "삼성전자", "w": 0.25, "px": 100.0}, "000660": {"name": "SK하이닉스", "w": 0.10, "px": 100.0,
                                                                         "shares": 100.0}}})
    cur = _snap("2026-10-17", {e1: 100.0, e2: 100.0}, {
        # 삼성: 주가 +10%, 비중 0.20→0.22 (+10%) = 가격효과
        e1: {"005930": {"name": "삼성전자", "w": 0.22}, "000660": {"name": "SK하이닉스", "w": 0.10},
             "035420": {"name": "NAVER", "w": 0.03}, "KRD010010001": {"name": "원화현금", "w": 0.05}},
        # 하이닉스: 주가 0%, 비중 0.10→0.13, 계약수 100→130 = 실질 증가
        e2: {"005930": {"name": "삼성전자", "w": 0.275}, "000660": {"name": "SK하이닉스", "w": 0.13, "shares": 130.0}}})
    px = {"005930": 110.0, "000660": 100.0, "035420": 50.0}
    r = etf.active_consensus(cur, prev, px)
    byc = {x["code"]: x for x in r["by_count"]}
    assert "KRD010010001" not in byc                                      # 현금 제외
    assert byc["005930"]["n_etf"] == 2 and byc["005930"]["w_sum"] == round(0.22 + 0.275, 4)
    assert byc["005930"]["verdicts"] == {"가격효과": 2} and byc["005930"]["n_real"] == 0
    assert byc["005930"]["note"] == "비중 증가는 주가 상승 효과일 수 있음"
    assert byc["000660"]["verdicts"].get("실질 증가(수량↑)") == 1 and byc["000660"]["n_real"] == 1
    assert byc["035420"]["n_new_top20"] == 1
    assert r["by_increase"][0]["code"] == "000660"                        # 실질 증가가 앞
    assert r["prev_asof"] == "2026-10-16"


def test_verdict_rules():
    assert etf._verdict(0.10, 0.10, None, None, 0.0) == "변화 없음"
    assert etf._verdict(0.10, 0.08, None, None, 0.0) == "비중 감소"
    assert etf._verdict(0.10, 0.12, None, None, 0.02) == "실질 증가 추정"   # +20% vs 상대수익 +2%
    assert etf._verdict(0.10, 0.12, None, None, 0.19) == "가격효과"
    assert etf._verdict(0.10, 0.12, None, None, None).startswith("주가 상승 효과일 수 있음")


def test_run_active_consensus_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(etf, "ACTIVE_OUT", tmp_path / "active_etf_consensus.json")
    monkeypatch.setattr(etf, "ACTIVE_SNAP", tmp_path / "active_etf_snap.json")
    monkeypatch.setattr(etf, "_stock_closes", lambda codes: {c: 100.0 for c in codes})
    import screener.guard as guard
    monkeypatch.setattr(guard, "write_json", lambda p, o, **k: p.write_text(json.dumps(o, ensure_ascii=False)) or True)
    hold = [{"code": "005930", "name": "삼성전자", "weight": 0.2}]
    assert etf.run_active_consensus({"385720": ([], None)}, "2026-10-16") is None   # 전부 미수집 → 안 씀
    assert not etf.ACTIVE_SNAP.exists()
    r = etf.run_active_consensus({"385720": (hold, None)}, "2026-10-16")
    assert r["by_count"][0]["code"] == "005930" and r["prev_asof"] is None
    assert etf.run_active_consensus({"385720": (hold, None)}, "2026-10-16") is None  # 같은 날 재실행 → 유지
    r2 = etf.run_active_consensus({"385720": ([{**hold[0], "weight": 0.25}], None)}, "2026-10-17")
    assert r2["prev_asof"] == "2026-10-16" and r2["by_increase"][0]["code"] == "005930"
    snap = json.loads(etf.ACTIVE_SNAP.read_text())
    assert snap["asof"] == "2026-10-17" and "prev" not in snap                  # 최신 1개만
