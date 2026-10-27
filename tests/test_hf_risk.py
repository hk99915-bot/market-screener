"""scripts/hf_risk.py 고정 입력 테스트 (req-hf-c7fd8c65 → 묶음 C req-dev-a3f3a6b4 ⑤, 감사 10/24 L2).

외부 파일 없이: 지수 시계열·베타를 monkeypatch 로 고정 → 스트레스 1종(손익 = 방향 × 비중 × 베타 × 충격)과
VaR 95% 분위(정렬 손익의 k=max(1, 5%×n) 번째)·ES(하위 k 평균)를 손으로 계산한 값과 대조.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hf_risk as R  # noqa: E402


@pytest.fixture
def book(monkeypatch):
    monkeypatch.setattr(R.H, "beta_of", lambda kind, code, n=60: 1.0)
    return {"open": [
        {"kind": "stock", "side": "롱", "weight": 0.10, "code": "000660", "name": "가", "beta": 1.5},
        {"kind": "us_stock", "side": "숏", "weight": 0.05, "code": "MU", "name": "나", "beta": 2.0},
    ]}


def test_exposure_stock_signed(book):
    assert R.exposure(book["open"][0], None, None) == pytest.approx(0.10)
    assert R.exposure(book["open"][1], None, None) == pytest.approx(-0.05)


def test_stress_2020_03(book):
    nm, k200, ndx, mkr, mus = R.STRESS[0]
    assert nm == "2020-03형 폭락"
    got = R.stress_pnl(book, None, None, k200, ndx, mkr, mus)
    # 롱 0.10×1.5×(−30%) = −4.5%p, 숏 −0.05×2.0×(−25%) = +2.5%p → −2.0%
    assert got == pytest.approx(0.10 * 1.5 * -0.30 + -0.05 * 2.0 * -0.25)
    assert got == pytest.approx(-0.02)


def test_var_es_quantile(monkeypatch):
    # 101일 → 수익 100개: 국장 지수 수익 r_i = (i−50)/1000 (−4.9%~+5.0%), 미장 0
    kr, us, v = {}, {}, 1000.0
    for i in range(101):
        dt = f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}"
        if i:
            v *= 1 + (i - 50) / 1000
        kr[dt], us[dt] = v, 100.0
    monkeypatch.setattr(R, "_series", lambda: (kr, us))
    var, es, n = R.var_es(0.5, 0.2)
    assert n == 100
    pl = sorted(0.5 * (i - 50) / 1000 for i in range(1, 101))
    assert var == pytest.approx(-pl[4])                 # k = 5 → 5번째 최악 = 0.5 × 4.5% = 2.25%
    assert var == pytest.approx(0.0225)
    assert es == pytest.approx(-sum(pl[:5]) / 5)        # 하위 5개 평균 = 0.5 × 4.7% = 2.35%


def test_var_es_needs_60_days(monkeypatch):
    monkeypatch.setattr(R, "_series", lambda: ({"2026-01-01": 1.0}, {"2026-01-01": 1.0}))
    assert R.var_es(0.1, 0.1) is None
