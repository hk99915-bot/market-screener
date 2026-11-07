"""그림자 파생 북 (screener/shadow_book.py) — 행사가·월물 선택, 다리 마킹, 만기 청산·롤, 미니 없을 때 정규 대체."""
from datetime import date

from screener import shadow_book as sb


def _opt(nm, settle, vol=10, oi=100):
    return {"ISU_NM": nm, "SETL_PRC": str(settle), "TDD_CLSPRC": str(settle), "ACC_TRDVOL": str(vol), "ACC_OPNINT_QTY": str(oi)}


def _board(prefix, quotes):
    return sb.parse_board([_opt(f"{prefix}코스피200 P {ym} {k:,.1f}", px) for (ym, k), px in quotes.items()]
                          + [{"ISU_NM": f"{prefix}코스피200 P 202612 700.0 (야간)", "SETL_PRC": "1"}], "O")


def test_parse_pick_and_expiry():
    b = _board("미니", {("202611", 702.5): 0.5, ("202612", 702.5): 9.0, ("202612", 707.5): 10.5, ("202612", 1_005.0): 230})
    assert ("P", "202612", 1005.0) in b and all("야간" not in str(k) for k in b)   # 쉼표 행사가·야간 제외
    assert b[("P", "202612", 702.5)]["px_basis"] == "settle"
    # 정산가 없는 종목은 종가(마지막 체결가)가 있어도 마킹 가격 없음 — '현재가' 마킹 금지(11/7)
    nb = sb.parse_board([{"ISU_NM": "미니코스피200 P 202611 842.5", "SETL_PRC": "-", "TDD_CLSPRC": "56.75"}], "O")
    assert nb[("P", "202611", 842.5)]["px"] is None and nb[("P", "202611", 842.5)]["close"] == 56.75
    # 11/10 진입: 202611(11/12 만기, 2일) 건너뛰고 202612 — 만기까지 20일 이상
    assert sb.pick_month(b, "P", date(2026, 11, 10), 20) == "202612"
    assert sb.expiry_of("202612") == date(2026, 12, 10)
    # 목표 783.23×0.9 = 704.9 → 702.5(2.4)·707.5(2.6) 중 가까운 702.5. 동률이면 더 외가(낮은 쪽)
    assert sb.pick_strike(b, "P", "202612", 704.907) == 702.5
    assert sb.pick_strike(b, "P", "202612", 705.0) == 702.5
    assert sb.intrinsic("P", 690, 702.5) == 12.5 and sb.intrinsic("C", 690, 702.5) == 0 and sb.intrinsic("F", 690, None) == 690


def test_mark_entry_theta_expiry_roll_and_proxy():
    s = dict(sb.BUILTIN[0], status="waiting", rows=[], cycles=[])
    mini = lambda q: {("mini", "O"): _board("미니", q)}  # noqa: E731
    d0 = sb.Day(date(2026, 11, 10), 783.0, mini({("202612", 705.0): 10.0, ("202612", 702.5): 9.4}))
    r = sb.mark(s, d0)
    assert r["status"] == "진입" and s["legs_open"][0]["k"] == 705.0 and s["legs_open"][0]["entry_px"] == 10.0
    assert r["theta_krw_day"] < 0 and r["delta_krw_per_pt"] < 0                          # 풋 매수: 세타 −, 델타 −
    # 다음 날: 미니 옵션 마킹 1순위 = 정규 같은 종목 정산가(k2i_ref, 상품명세상 기준가격 동일) · 미니 체결 없음(거래량 0) → thin, 미니 값은 대조 칸
    d1 = sb.Day(date(2026, 11, 11), 743.85, {("mini", "O"): _board("미니", {("202612", 705.0): 17.9}),
                                              ("k2i", "O"): _board("", {("202612", 705.0): 18.0})})
    d1.boards[("mini", "O")][("P", "202612", 705.0)]["vol"] = 0.0
    r = sb.mark(s, d1)
    lg = r["legs"][0]
    assert lg["src"] == "k2i_ref" and lg["px"] == 18.0 and lg["mini_px"] == 17.9 and lg["thin"]
    assert r["pnl_day"] == 8.0 * 50_000 and r["pnl_cum"] == 400_000
    assert r["r_s"] < -0.04 and 0 < r["offset_vs_1mini"] < 1
    # 만기일: 내재가치(705−690=15)로 청산 → 같은 날 다음 월물(202701, 1/14 만기)로 롤
    d2 = sb.Day(date(2026, 12, 10), 690.0, mini({("202612", 705.0): 15.2, ("202701", 620.0): 6.0, ("202701", 622.5): 6.5}))
    r = sb.mark(s, d2)
    assert r["status"] == "만기 청산 → 롤" and r["pnl_day"] == (15.0 - 18.0) * 50_000
    c = s["cycles"][0]
    assert c["premium_krw"] == 500_000 and c["pnl_krw"] == 250_000
    assert s["legs_open"][0]["ym"] == "202701" and s["legs_open"][0]["k"] == 620.0       # 690×0.9 = 621 → 620·622.5 중 620(1.0 차)
    assert sb.summary(dict(s, rows=[r]))["cycles"] == 1
    assert sb.margin_slot(s) is None and sb.margin_slot({"legs": [{"side": -1}]})["approx_krw"] is None


def test_hf_registry_reads_json_block(tmp_path):
    p = tmp_path / "shadow_book_prereg.md"
    p.write_text('# x\n```json\n{"shadow_strategies": [{"id": "S2_straddle", "name": "ATM 스트래들", "legs": ['
                 '{"kind": "C", "side": 1, "product": "mini", "moneyness": 0, "qty": 1},'
                 '{"kind": "P", "side": 1, "product": "mini", "moneyness": 0, "qty": 1}]},'
                 '{"id": "bad", "name": "x", "legs": [{"kind": "Z"}]}]}\n```\n', encoding="utf-8")
    hf, meta = sb.hf_strategies(p)
    assert meta["found"] and meta["n"] == 1 and meta["errors"]
    ids = [s["id"] for s in sb.registry(hf)]
    assert ids == ["S1_mini_put_10", "S2_straddle"] and hf[0]["min_dte"] == 20
