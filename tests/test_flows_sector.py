from screener import flows


def test_sector_moves_cap_weighted_and_filters():
    rows = [{"g": "A", "mc": 9, "ret1": 0.02}] * 4 + [{"g": "A", "mc": 1, "ret1": -0.08}]
    rows += [{"g": "B", "mc": 1, "ret1": -0.01}] * 5 + [{"g": "기타", "mc": 1, "ret1": 0.5}] * 9
    rows += [{"g": "C", "mc": 1, "ret1": 0.9}] * 4  # 종목 수 미달
    up, dn = flows.sector_moves(rows, n=1)
    assert up[0][0] == "A" and abs(up[0][1] - (36 * 0.02 - 0.08) / 37) < 1e-12 and up[0][2] == 5
    assert dn[0][0] == "B"


def test_close_comment_sector_lines():
    L = flows.close_comment({}, {}, {}, [], [], [], [], ([("A", 0.012, 5)], [("B", -0.03, 6)]))
    assert L == ["강한 업종(시총 가중): A +1.2%", "약한 업종(시총 가중): B -3.0%"]
