"""타점 대결 trail 청산 −8% 손절 재현 (req-dev-4dcda5cb → 묶음 C ②).

10/16 '나' 475310(SOL 반도체후공정, exit=trail): 10/16 종가 27,590 → 10/22 종가 25,105(−9.0%, 종가 기준 −8% 첫 하회)
→ 그날 종가 청산. 10/23 10:26 채점분(reports/decisions.json)과 같은 결과인지 고정 일봉으로 확인.
종가 판정이라 실현 손실(−9.06%, 비용 0.05% 포함)은 −8%보다 깊을 수 있다(장중 손절 아님).
"""
from screener import decisions as D

BARS = [  # reports/detail/KR/475310.json 10/12~10/23 종가 (시가 = 종가로 단순화)
    ("2026-10-12", 31670), ("2026-10-13", 31340), ("2026-10-14", 29800), ("2026-10-15", 26200), ("2026-10-16", 27590),
    ("2026-10-19", 27305), ("2026-10-20", 26170), ("2026-10-21", 26560), ("2026-10-22", 25105), ("2026-10-23", 24620),
]


def test_trail_stops_at_minus_8_close(monkeypatch):
    bars = [{"d": d, "o": float(c), "c": float(c)} for d, c in BARS]
    monkeypatch.setattr(D, "_bars", lambda code, start: [b for b in bars if b["d"] >= start])
    r = D._score_pick({"ticker": "475310", "entry": "close", "exit": "trail", "notional": 1}, "2026-10-16")
    assert r is not None and "2026-10-22" in r["detail"] and "−8% 손절" in r["detail"]
    assert r["sell"] == 25105.0 and r["ret"] == round(25105 / 27590 - 1 - 0.0005, 4)   # −0.0906


def test_trail_still_open_returns_none(monkeypatch):
    bars = [{"d": d, "o": float(c), "c": float(c)} for d, c in BARS[:7]]   # 10/20 까지 — −8% 미도달, 20일선 무장 전
    monkeypatch.setattr(D, "_bars", lambda code, start: [b for b in bars if b["d"] >= start])
    assert D._score_pick({"ticker": "475310", "entry": "close", "exit": "trail"}, "2026-10-16") is None
