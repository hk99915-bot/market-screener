"""신호·후보·대결 성과 추적 공통 유틸 (2026-10-20 dev: signal-tracking · battle-scoreboard · us-entry-ideas).

가격 원천 (네트워크 없음 — 저장소에 이미 있는 것만):
  KR = data/kr_prices.parquet (screener.prices.load_kr, 기업행위 조정) — idea_tracking 과 같은 원천
  US = reports/detail/US/*.json 의 chart (최근 ~260거래일 OHLC, 미장 마감 스크리너 06:52 KST 갱신)
일봉 형식(공통): {"date","open","high","low","close"} — 날짜 오름차순.

forward 수익 = 신호일 종가(그날 봉이 없으면 그 이전 마지막 봉) → h 거래일 뒤 종가. 비용 미반영.
시장 중앙값 = 같은 창(같은 시작·끝 날짜)에서 원천 전종목 forward 수익의 중앙값 (KR=kr_prices 전종목, US=detail/US 전종목).
초과 = 종목 forward − 시장 중앙값. h 거래일이 아직 안 지났으면 None('대기').
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DATA_DIR, REPORT_DIR

KST = ZoneInfo("Asia/Seoul")
HORIZONS = (5, 20, 60)


def _num(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v) and v > 0


def kr_bars(now: datetime | None = None, path: Path | None = None, codes=None) -> dict[str, list[dict]]:
    """{code: [bar…]} — 오늘(KST) 봉은 15:45 전이면 제외(장중 잠정 가격 금지). codes 를 주면 그 종목만."""
    from .prices import load_kr
    now = now or datetime.now(KST)
    today = str(now.date())
    by: dict[str, list[dict]] = {}
    df = load_kr(path=path or DATA_DIR / "kr_prices.parquet")
    if codes is not None and hasattr(df, "filter"):
        import polars as pl
        df = df.filter(pl.col("yf").str.split(".").list.first().is_in([str(c) for c in codes]))
    for b in df.iter_rows(named=True):
        day = str(b["date"])
        if day > today or (day == today and (now.hour, now.minute) < (15, 45)):
            continue
        code = str(b["yf"]).split(".")[0]
        by.setdefault(code, []).append({**b, "date": day})
    for v in by.values():
        v.sort(key=lambda x: x["date"])
    return by


def detail_bars(market: str, tickers=None, detail_dir: Path | None = None) -> dict[str, list[dict]]:
    """{ticker: [bar…]} from reports/detail/<market>/*.json chart. tickers=None 이면 전종목."""
    return us_bars(tickers, detail_dir or REPORT_DIR / "detail" / market)


def bars_for(market: str, codes, now: datetime | None = None) -> dict[str, list[dict]]:
    """대결·후보용 소수 종목 일봉. KR = kr_prices(주식) → 없으면 detail/KR chart(ETF 등). US = detail/US chart."""
    codes = [str(c) for c in codes]
    if market == "US":
        return us_bars(codes)
    out = {}
    try:
        out = kr_bars(now, codes=codes)
    except Exception:  # noqa: BLE001
        out = {}
    miss = [c for c in codes if c not in out]
    if miss:
        now = now or datetime.now(KST)
        today = str(now.date())
        for c, bs in detail_bars("KR", miss).items():
            out[c] = [b for b in bs if b["date"] < today or (b["date"] == today and (now.hour, now.minute) >= (15, 45))]
    return out


def us_bars(tickers=None, detail_dir: Path | None = None) -> dict[str, list[dict]]:
    """{ticker: [bar…]} from detail/US chart. tickers=None 이면 전종목(시장 중앙값용)."""
    dd = Path(detail_dir or REPORT_DIR / "detail" / "US")
    files = [dd / f"{t}.json" for t in tickers] if tickers is not None else sorted(dd.glob("*.json"))
    out: dict[str, list[dict]] = {}
    for f in files:
        try:
            ch = json.loads(f.read_text(encoding="utf-8")).get("chart") or []
        except Exception:  # noqa: BLE001
            continue
        bars = [{"date": b["t"], "open": b.get("o"), "high": b.get("h"), "low": b.get("l"), "close": b.get("c")}
                for b in ch if b.get("t") and _num(b.get("c"))]
        if bars:
            out[f.stem] = sorted(bars, key=lambda x: x["date"])
    return out


def _idx_at(bars: list[dict], d0: str) -> int | None:
    """d0 이하 마지막 봉 위치."""
    k = None
    for i, b in enumerate(bars):
        if b["date"] <= d0:
            k = i
        else:
            break
    return k


def fwd(bars: list[dict], d0: str, h: int) -> dict | None:
    """신호일 d0 종가 → h 거래일 뒤 종가. 반환 {ret, d0, d1} 또는 None(기간 미경과·가격 없음)."""
    i = _idx_at(bars, d0)
    if i is None or i + h >= len(bars):
        return None
    a, b = bars[i].get("close"), bars[i + h].get("close")
    if not (_num(a) and _num(b)):
        return None
    return {"ret": b / a - 1, "d0": bars[i]["date"], "d1": bars[i + h]["date"]}


def ret_between(bars: list[dict], d0: str, d1: str) -> float | None:
    """d0 이하 마지막 종가 → d1 이하 마지막 종가 수익 (벤치마크 같은 창 비교용)."""
    i, j = _idx_at(bars, d0), _idx_at(bars, d1)
    if i is None or j is None or j < i:
        return None
    a, b = bars[i].get("close"), bars[j].get("close")
    return (b / a - 1) if _num(a) and _num(b) else None


class MarketMedian:
    """같은 창(d0 종가 → d1 종가) 전종목 수익 중앙값. 날짜→종가 사전을 한 번 만들고 창별로 캐시."""

    def __init__(self, universe: dict[str, list[dict]], min_n: int = 30):
        self.cl = {c: {b["date"]: b["close"] for b in bs if _num(b.get("close"))} for c, bs in universe.items()}
        self.min_n = min_n
        self._cache: dict[tuple[str, str], float | None] = {}

    def __call__(self, d0: str, d1: str) -> float | None:
        k = (d0, d1)
        if k not in self._cache:
            rs = sorted(m[d1] / m[d0] - 1 for m in self.cl.values() if d0 in m and d1 in m)
            n = len(rs)
            self._cache[k] = None if n < self.min_n else (rs[n // 2] if n % 2 else (rs[n // 2 - 1] + rs[n // 2]) / 2)
        return self._cache[k]


def fwd_excess(bars: list[dict], d0: str, med: MarketMedian, horizons=HORIZONS) -> dict:
    """{"h5": {ret, mkt, ex, d1} | None, …} — None = 기간 미경과 또는 가격 없음."""
    out = {}
    for h in horizons:
        f = fwd(bars, d0, h)
        if not f:
            out[f"h{h}"] = None
            continue
        m = med(f["d0"], f["d1"])
        out[f"h{h}"] = {"ret": round(f["ret"], 5), "mkt": None if m is None else round(m, 5),
                        "ex": None if m is None else round(f["ret"] - m, 5), "d1": f["d1"]}
    return out


def summarize(rows: list[dict], horizons=HORIZONS) -> dict:
    """rows[*]["fwd"]["hN"]["ex"] 집계: n·평균 초과·중앙 초과·적중(초과>0). n<1 이면 None."""
    out = {}
    for h in horizons:
        xs = sorted(r["fwd"][f"h{h}"]["ex"] for r in rows
                    if (r.get("fwd") or {}).get(f"h{h}") and r["fwd"][f"h{h}"].get("ex") is not None)
        n = len(xs)
        out[f"h{h}"] = None if not n else {
            "n": n, "avg_ex": round(sum(xs) / n, 5),
            "med_ex": round(xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2, 5),
            "hit": round(sum(1 for x in xs if x > 0) / n, 3)}
    return out
