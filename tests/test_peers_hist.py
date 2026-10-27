"""peers_US drv·r20·r1 거래일 누적 (req-dev-808893e4 → 묶음 C ④)."""
from screener import peers_hist as P

ROWS = [{"s": "MU", "drv": 0.52, "r20": -0.1, "r1": 0.0123456}, {"s": "A", "drv": None, "r20": 0.0058, "r1": 0.0}, {"n": "no symbol"}]


def test_append_replaces_same_asof_and_sorts(tmp_path):
    fp = tmp_path / "US.csv"
    assert P.append("US", "2026-10-26", ROWS, fp) == 2
    assert P.append("US", "2026-10-23", [{"s": "MU", "drv": 0.4, "r20": 0, "r1": 0}], fp) == 1    # 백필(과거)도 날짜순
    assert P.append("US", "2026-10-26", [{"s": "MU", "drv": 0.6, "r20": -0.1, "r1": 0.01}], fp) == 1   # 같은 날 재실행 = 교체
    lines = fp.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "asof,s,drv,r20,r1"
    assert lines[1:] == ["2026-10-23,MU,0.4,0,0", "2026-10-26,MU,0.6,-0.1,0.01"]


def test_number_format(tmp_path):
    fp = tmp_path / "US.csv"
    P.append("US", "2026-10-26T00:00", ROWS[:2], fp)
    body = fp.read_text(encoding="utf-8")
    assert "2026-10-26,A,,0.0058,0\n" in body and "2026-10-26,MU,0.52,-0.1,0.0123\n" in body
