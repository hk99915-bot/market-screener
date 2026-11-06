"""req-dev-69bc1203: 등락률의 '전일 종가' 규약 회귀. 야후 chart API meta.chartPreviousClose(조회 기간 시작 전 종가)를 전일 종가로
쓰면 range>1d 에서 은 −12.5%(실제 +5.1%) 오보. 코드는 일봉 직전 행(rows[-2])만 쓰고, 분할일 가짜 등락률은 걸러낸다.
합성 데이터 검증 — 야후 실응답은 미확인."""
import re
from pathlib import Path

import pandas as pd

from screener import usmarket
from screener.prices import split_artifact

ROOT = Path(__file__).resolve().parent.parent


def test_no_chart_previous_close_in_code():
    bad = []
    for base in ("screener", "scripts", "tools", "apps-script"):
        for p in (ROOT / base).rglob("*"):
            if p.suffix in (".py", ".gs", ".js", ".html") and p.is_file():
                txt = p.read_text(encoding="utf-8", errors="ignore")
                if re.search(r"chartPreviousClose|meta\W+previousClose", txt) and "금지" not in txt:
                    bad.append(str(p.relative_to(ROOT)))
    assert not bad, bad


def test_split_artifact():
    assert split_artifact(68.0, 212.0)          # 3:1 분할일 −68%
    assert split_artifact(636.0, 212.0)         # 1:3 병합
    assert not split_artifact(214.0, 212.0)
    assert not split_artifact(95.0, 100.0)      # 실제 −5%
    assert not split_artifact(5.0, None)
    assert not split_artifact(5.0, 0)


def test_snapshot_uses_prev_row_and_drops_split_artifact(monkeypatch):
    idx = pd.date_range("2026-11-02", periods=3)
    cols = pd.MultiIndex.from_product([["SLV", "ITA"], ["Close"]])
    df = pd.DataFrame({("SLV", "Close"): [30.0, 28.0, 29.4], ("ITA", "Close"): [210.0, 212.0, 70.0]}, index=idx, columns=cols)
    import sys
    import types
    fake = types.ModuleType("yfinance")
    fake.download = lambda *a, **k: df
    monkeypatch.setitem(sys.modules, "yfinance", fake)
    out = usmarket.snapshot({"은": "SLV", "ITA": "ITA"})
    assert abs(out["은"]["chg"] - 0.05) < 1e-9          # 기간 시작(30.0) 기준이면 −2% — 직전 행 28.0 기준 +5%
    assert "ITA" not in out                              # 3:1 분할 불연속 −67% 는 등락률로 내지 않음
