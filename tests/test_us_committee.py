"""미장 운용회의 v2 (screener/us_committee.py) — 섹터 판정·독립 표본·요인 분해·헤지·프리모템·결론·채점."""
import math
from datetime import date, timedelta

from screener import committee, study
from screener import us_committee as U


# ── d) 섹터 판정: 드라이버만 보지 않고 가격 추세를 넣는다 ──
def test_semis_falling_price_is_not_overweight():
    # 10/20 판: 반도체 드라이버 +0.35 · 20일 −12.7% → 예전엔 '비중 확대'(drv ≥0.25 만 봄)
    sc = U.sector_score(0.352, -0.127)
    assert U.sector_stance(sc) == "중립"
    assert sc < U.OW


def test_sector_score_matches_kr_construction():
    # 가격 성분 만점(±14%) · 가중 0.6 · 드라이버 2성분 → (2×0.5 + 0.6×1)/3
    assert math.isclose(U.sector_score(0.5, 0.20), round((2 * 0.5 + 0.6 * 1) / 3, 3))
    assert U.sector_stance(U.sector_score(0.5, 0.20)) == "비중 확대"
    assert U.sector_stance(U.sector_score(-0.1, -0.20)) == "비중 축소"
    assert U.sector_score(None, 0.1) is None


def test_sector_rows_weights_and_sort():
    peers = [{"s": f"A{i}", "g": "반도체", "mc": 1, "drv": 0.35, "r5": -0.08, "r20": -0.127} for i in range(5)]
    peers += [{"s": f"B{i}", "g": "에너지", "mc": 1, "drv": 0.35, "r5": 0.02, "r20": 0.086} for i in range(5)]
    peers += [{"s": "C", "g": "소수", "mc": 1, "drv": 0.9, "r20": 0.1}]   # 5종목 미만 → 제외
    rows = U.sector_rows(peers)
    assert [r["sector"] for r in rows] == ["에너지", "반도체"]
    assert rows[0]["stance"] == "비중 확대" and rows[1]["stance"] == "중립"


# ── e) 겹치는 20일 표본 → 독립 블록 ──
def test_indep_count_greedy_non_overlapping():
    assert study.indep_count(list(range(100))) == 5
    assert study.indep_count([0, 5, 25, 26, 50]) == 3
    assert study.indep_count([]) == 0


def test_basis_fields_range_and_exact():
    b = U.basis_fields({"n": 4333}, 6947)
    assert b["n"] == 4333 and b["n_indep"] is None
    assert b["n_indep_range"] == {"lo": 217, "hi": 348}
    assert "217~348" in b["indep_note"]
    e = U.basis_fields({"n": 4333, "n_indep": 260}, 6947)
    assert e["n_indep"] == 260 and "n_indep_range" not in e and "260" in e["indep_note"]
    assert U.rng_txt({"lo": 342, "hi": 342}) == "약 342"
    assert committee._indep_suffix(b) == " (겹치지 않는 20일 블록 약 217~348개)"


# ── b) 매크로 요인 분해 ──
def _series(n=320):
    d0 = date(2025, 1, 1)
    days = [str(d0 + timedelta(days=i)) for i in range(n)]
    rate, dxy, vix, spx, nq = [4.0], [100.0], [15.0], [5000.0], [15000.0]
    for i in range(1, n):
        dr = 0.03 * math.sin(i * 0.7)                    # bp/100
        dd = 0.002 * math.cos(i * 1.3)
        dv = 0.05 * math.sin(i * 0.9 + 1)
        rate.append(rate[-1] + dr)
        dxy.append(dxy[-1] * math.exp(dd))
        vix.append(vix[-1] * math.exp(dv))
        r = -0.0005 * dr * 100 - 0.2 * dd - 0.05 * dv     # 금리·달러·VIX 만으로 결정되는 S&P
        spx.append(spx[-1] * math.exp(r))
        nq.append(nq[-1] * math.exp(1.2 * r))
    row = lambda d, c: [d, c, c, c, c, 0]   # noqa: E731  (6열: 종가 = [4])
    return {"SPX": [row(d, c) for d, c in zip(days, spx)], "US10Y": [row(d, c) for d, c in zip(days, rate)],
            "DXY": [row(d, c) for d, c in zip(days, dxy)], "VIX": [row(d, c) for d, c in zip(days, vix)],
            "NASDAQ": [row(d, c) for d, c in zip(days, nq)]}


def test_factor_decomp_recovers_betas_and_adds_up():
    out = U.factor_decomp(_series())
    b = {r["k"]: r["beta"] for r in out["rows"]}
    assert math.isclose(b["금리"], -0.0005, rel_tol=1e-3)
    assert math.isclose(b["달러"], -0.2, rel_tol=1e-3)
    assert math.isclose(b["VIX"], -0.05, rel_tol=1e-3)
    assert abs(out["resid"]) < 1e-6 and out["r2"] > 0.99
    assert out["nasdaq"]["corr"] > 0.99 and "다중공선성" in out["nasdaq_line"]
    assert out["line"].startswith("S&P500 ")


def test_factor_decomp_short_series_none():
    ms = _series(50)
    assert U.factor_decomp(ms) is None


# ── a) 헤지·비대칭·프리모템·결론 ──
SCEN = [{"name": "강세 — 고점 경신", "prob": 0.22, "trigger": "T강세", "action": "A강세"},
        {"name": "기본 — 박스권", "prob": 0.63, "trigger": "T기본", "action": "A기본"},
        {"name": "약세 — 금리·밸류 조정", "prob": 0.15, "trigger": "T약세", "action": "A약세"}]
K = {"last": 7690.0, "low20": 7652.0, "hi5": 7805.0, "hi52": 7819.0, "vix": 18.4}


def test_hedges_consistent_with_bear_action_and_honest_asymmetry():
    h = U.hedges_us(K, SCEN, {"deep_bear": 0.009}, {"etf": [{"s": "SHY", "y": 4.77, "dur": 1.9, "date": "2026-10-19"}]})
    assert "SH" in h["hedges"][0]["name"] and "PSQ" in h["hedges"][0]["name"]
    assert any("SHY" in x["name"] for x in h["hedges"])
    assert h["worst"].startswith("약세") and h["worst_p"] == 0.15
    a = h["asymmetry"]
    assert "데이터 없음" in a["cond"] and a["down_room"] < 0 < a["up_room"]
    assert math.isclose(a["sigma20"], 0.184 * (20 / 252) ** 0.5)


def test_premortem_picks_second_most_likely():
    pm = U.premortem_us(SCEN, K, {"deep_bear": 0.009})
    assert pm["wrong"].startswith("'기본'이 틀린 경우: 강세")
    assert pm["tell"] == "T강세" and pm["action"] == "A강세" and pm["p"] == 0.22
    assert U.premortem_us([], K, {}) == {}


def test_bottom_line_red_on_verdict_flip_yellow_on_near_line():
    o = {"scenarios": SCEN, "sectors": [], "macro": {"changed": []}}
    prev = {"date": "2026-10-19", "head": ["S&P500 7,659 (+0.1%)"], "scenarios": [{**SCEN[0], "prob": 0.5}, {**SCEN[1], "prob": 0.3}, SCEN[2]]}
    bl = U.bottom_line_us(o, K, prev, [], date(2026, 10, 20), committee.LIGHTS, "f")
    assert bl["light"] == "red" and "결론 강세→기본" in bl["lines"][0]
    same = {**prev, "scenarios": SCEN}
    bl2 = U.bottom_line_us(o, K, same, [], date(2026, 10, 20), committee.LIGHTS, "f")
    assert bl2["light"] == "yellow" and "가격선 근접" in bl2["lines"][2]   # 20일 저점 −0.5% < VIX 하루 1σ 1.2%
    far = {**K, "low20": 7000.0, "hi5": 8200.0, "hi52": 8300.0}
    assert U.bottom_line_us(o, far, same, [], date(2026, 10, 20), committee.LIGHTS, "f")["light"] == "green"
    assert U.bottom_line_us(o, far, None, [], date(2026, 10, 20), committee.LIGHTS, "f")["lines"][0].startswith("직전 회의 기록 없음")


# ── c) 기록·채점·아이디어 추적 ──
def _px(n=30):
    d0 = date(2026, 9, 1)
    days = [str(d0 + timedelta(days=i)) for i in range(n)]
    spx = {d: 100 * (1.001 ** i) for i, d in enumerate(days)}
    up = {d: 50 * (1.003 ** i) for i, d in enumerate(days)}
    dn = {d: 50 * (0.999 ** i) for i, d in enumerate(days)}
    return days, spx, {"UP": up, "DN": dn}


def test_score_hist_excess_and_brier():
    days, spx, px = _px()
    rows = [{"date": "x", "ref": days[0], "long": ["UP"], "avoid": ["DN"], "probs": {"강세": 0.2, "기본": 0.6, "약세": 0.2}},
            {"date": "y", "ref": days[-2], "long": ["UP"], "avoid": []}]
    tr = U.score_hist(rows, spx, px)
    s = tr["summary"]
    assert s["h5"]["n"] == 1 and s["h5"]["long_avg"] > 0 and s["h5"]["avoid_avg"] < 0 and s["h5"]["long_hit"] == 1.0
    assert s["h20"]["n"] == 1
    mk = spx[days[20]] / spx[days[0]] - 1          # +2.0% → 기본(±3%)
    assert -0.03 <= mk <= 0.03
    assert s["brier"]["avg"] == round(0.2 ** 2 + 0.4 ** 2 + 0.2 ** 2, 3)
    assert tr["pending"] and tr["pending"][0]["date"] == "y"
    assert U.track_lines(tr, 2, "x")[0].startswith("매수 후보 5거래일")
    assert U.track_lines({"summary": {}}, 3, "2026-10-15")[0].startswith("채점 전 — 기록 3회")


def test_ideas_tracking_first_proposal_only():
    days, spx, px = _px()
    rows = [{"date": "2026-09-02", "ref": days[0], "long": ["UP"], "avoid": ["DN"]},
            {"date": "2026-09-05", "ref": days[3], "long": ["UP", "NOPE"], "avoid": []}]
    it = U.ideas_tracking(rows, spx, px)
    tk = [(r["s"], r["side"]) for r in it["rows"]]
    assert tk.count(("UP", "매수 후보")) == 1
    nope = next(r for r in it["rows"] if r["s"] == "NOPE")
    assert nope["status"].startswith("가격 없음")
    up = next(r for r in it["rows"] if r["s"] == "UP")
    assert up["status"] == "20일 종료" and up["excess"] > 0
    assert it["summary"]["hit"] == 1.0 and it["summary"]["closed"] == 2


def test_ref_session_is_prior_us_close():
    assert U._ref_session(["2026-10-16", "2026-10-19", "2026-10-20"], "2026-10-20") == "2026-10-19"
    assert U._ref_session([], "2026-10-20") is None
