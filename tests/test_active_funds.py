"""액티브 ETF 편입·편출 diff (screener/active_funds.py) — 픽스처만, 네트워크 없음."""
from screener import active_funds as af

A, B = af.TARGETS[0]["code"], af.TARGETS[1]["code"]


def _pdf(rows):
    return [{"code": c, "name": n, "shares": s, "amount": a} for c, n, s, a in rows]


def test_normalize_drops_cash_and_futures():
    h = af.normalize(_pdf([("005930", "삼성전자", 10, 700), ("KRD010010001", "원화현금", 1, 300),
                           ("KR4101V90009", "코스피200 F", 1, 50), ("000660", "SK하이닉스", 0, 0)]))
    assert list(h) == ["005930"]
    assert h["005930"]["w"] == 1.0   # 비중은 주식 합 기준


def test_flow_inflow_is_not_a_buy():
    """자금 유입으로 펀드가 2배가 돼도 1CU 당 수량은 그대로 → 이벤트 0 (비중이 주가로 바뀌어도 무시)."""
    prev = af.normalize(_pdf([("005930", "삼성전자", 10, 700), ("000660", "SK하이닉스", 2, 300)]))
    cur = af.normalize(_pdf([("005930", "삼성전자", 10, 900), ("000660", "SK하이닉스", 2, 300)]))
    assert af.diff(prev, cur) == []


def test_real_increase_new_exit_and_split():
    prev = af.normalize(_pdf([("005930", "삼성전자", 10, 700), ("000660", "SK하이닉스", 2, 300), ("035420", "NAVER", 5, 100),
                              ("012450", "한화에어로", 4, 100)]))
    cur = af.normalize(_pdf([("005930", "삼성전자", 12, 840), ("000660", "SK하이닉스", 2, 300), ("068270", "셀트리온", 3, 60),
                             ("012450", "한화에어로", 20, 100), ("000001", "시범", 1, 1)]))
    ev = {e["stock"]: e for e in af.diff(prev, cur)}
    assert ev["005930"]["kind"] == "up" and ev["005930"]["chg"] == 0.2
    assert "000660" not in ev
    assert ev["068270"]["kind"] == "new" and not ev["068270"]["trial"]
    assert ev["000001"]["trial"] is True          # 비중 0.2% 미만 = 시범 편입
    assert ev["035420"]["kind"] == "exit"
    assert ev["012450"].get("split_suspect")      # 5배 = 액면분할 의심


def test_step_consensus_idempotent_and_failed_fetch_keeps_prev():
    s0 = af.normalize(_pdf([("005930", "삼성전자", 10, 700), ("000660", "SK하이닉스", 2, 300)]))
    snap, out = af.step({}, {}, {A: s0, B: s0}, "2026-10-15")
    assert out["events"] == [] and snap["funds"][A]["asof"] == "2026-10-15"
    s1 = af.normalize(_pdf([("005930", "삼성전자", 10, 700), ("000660", "SK하이닉스", 3, 450)]))
    snap, out = af.step(snap, out, {A: s1, B: s1}, "2026-10-16", universe={"000660"})
    top = out["consensus"][0]
    assert top["stock"] == "000660" and top["n_buy"] == 2 and top["in_universe"] is True
    # 같은 날 재실행 → 이벤트 중복 없음
    snap2, out2 = af.step(snap, out, {A: s1, B: s1}, "2026-10-16")
    assert len(out2["events"]) == len(out["events"]) == 2
    # 다음 날 A 수집 실패(빈 PDF) → '전량 편출'이 아니라 미수집, 스냅샷 유지
    snap3, out3 = af.step(snap2, out2, {B: s1}, "2026-10-17")
    assert not [e for e in out3["events"] if e["date"] == "2026-10-17"]
    assert out3["fund_status"][A].startswith("미수집") and snap3["funds"][A]["asof"] == "2026-10-16"
    assert out3["status"] == "partial"


def test_event_log_trimmed_to_keep_days():
    h0 = af.normalize(_pdf([("005930", "삼성전자", 10, 700)]))
    snap, out = af.step({}, {}, {A: h0}, "2026-10-01")
    for i, d in enumerate(["2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07"]):
        h = af.normalize(_pdf([("005930", "삼성전자", 10 * (1.1 ** (i + 1)), 700)]))
        snap, out = af.step(snap, out, {A: h}, d, keep_days=2, cons_days=1)
    assert sorted({e["date"] for e in out["events"]}) == ["2026-10-06", "2026-10-07"]
    assert out["consensus_days"] == ["2026-10-07"]
