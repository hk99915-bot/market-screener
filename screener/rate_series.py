"""macro_series 에 금리 일봉 2종 추가 (req-data-5046a78b, 매크로: trade plan 금리 필터용).

- KR3Y  = 한국 국고채 3년 (%) — reports/bonds_hist.json 의 kr_3Y (KRX 정보데이터시스템 [14017] 단일 출처, 2025-09-19~ 일별 누적).
          req-data-1fd3dc04: 국고 3Y 의 단일 출처 = KRX [14017] 확정값(bonds.json·committee 가 읽는 값). 토스·타 출처는 참고용.
- TIPS10Y = 미 10년 TIPS 실질금리 (%) — FRED DFII10 (fredgraph.csv, 키 불필요, 재무부 일별). 휴일은 '.' → 버림.
행 형식은 macro_series 와 같은 dohlcv: [날짜, 시, 고, 저, 종, 0] (금리는 종가만 있어 O=H=L=C). 수집 실패 시 호출자가 이전 값을 stale 로 유지.
"""
from __future__ import annotations

import json
import logging

from .config import REPORT_DIR

log = logging.getLogger(__name__)
KEEP = 520   # 약 2년 (영업일)


def _rows(pairs: list[tuple[str, float]]) -> list[list]:
    return [[d, v, v, v, v, 0] for d, v in pairs[-KEEP:]]


def kr3y_from_hist(hist: dict) -> list[tuple[str, float]]:
    return [(r["date"], float(r["kr_3Y"])) for r in (hist.get("rows") or []) if r.get("kr_3Y") is not None]


def parse_fred_csv(text: str) -> list[tuple[str, float]]:
    out = []
    for ln in text.strip().splitlines()[1:]:
        d, _, v = ln.partition(",")
        try:
            out.append((d.strip(), float(v)))
        except ValueError:   # '.' = 휴일 결측
            continue
    return out


def fetch_fred(sid: str = "DFII10") -> list[tuple[str, float]]:
    import requests   # 기본 UA — 브라우저 UA 는 FRED 읽기 타임아웃(calendar_ev 주석, req-data-fb0157f5)
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=(10, 20))
    r.raise_for_status()
    return parse_fred_csv(r.text)


def merge_into(ser: dict, hist: dict | None = None, fred=None) -> dict[str, str]:
    """ser 에 KR3Y·TIPS10Y 를 넣는다. 반환 = 키별 상태 문자열(실패는 '실패: …', ser 는 건드리지 않음)."""
    st: dict[str, str] = {}
    try:
        if hist is None:
            hist = json.loads((REPORT_DIR / "bonds_hist.json").read_text(encoding="utf-8"))
        p = kr3y_from_hist(hist)
        if len(p) < 2:
            raise ValueError("kr_3Y 2행 미만")
        ser["KR3Y"] = _rows(p)
        st["KR3Y"] = f"ok {len(p)}일 {p[-1][0]}"
    except Exception as e:  # noqa: BLE001
        st["KR3Y"] = f"실패: {type(e).__name__}: {e}"
    try:
        p = (fred or fetch_fred)()
        if len(p) < 2:
            raise ValueError("DFII10 2행 미만")
        ser["TIPS10Y"] = _rows(p)
        st["TIPS10Y"] = f"ok {len(p)}일 {p[-1][0]}"
    except Exception as e:  # noqa: BLE001
        st["TIPS10Y"] = f"실패: {type(e).__name__}: {e}"
    for k, v in st.items():
        if v.startswith("실패"):
            log.warning("금리 시계열 %s %s", k, v)
    return st
