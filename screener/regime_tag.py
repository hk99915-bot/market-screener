"""리서치 발간일의 시장 국면 태그 — 코스피 기준(rg_k)·해당 종목 주가 기준(rg_s) (10/17 겸이 요청).

정의 (macroview 의 '고점 대비' 구간과 같은 문턱):
- 하락: 52주(가용 기간) 고점 대비 −20% 이하
- 조정: 고점 대비 −10%~−20%, 또는 종가 < 200일선(200일 데이터가 있을 때)
- 상승: 그 밖 (고점 −10% 이내이고 200일선 위)
기준은 발간일 당일(없으면 직전 거래일) 종가. 종목 시세는 data/kr_prices.parquet(2025-09~)라 그 이전 고점은 모름 → 'n' (관측일 수) 함께 기록.
"""
from __future__ import annotations

import bisect

DD_BEAR, DD_CORR, MA_N, HI_N = -0.20, -0.10, 200, 252


def classify(closes: list[float]) -> dict | None:
    """closes: 발간일까지의 종가(오래된 → 최신). 20개 미만이면 None."""
    c = [x for x in closes if x and x > 0]
    if len(c) < 20:
        return None
    last, hi = c[-1], max(c[-HI_N:])
    dd = last / hi - 1
    ma = sum(c[-MA_N:]) / MA_N if len(c) >= MA_N else None
    if dd <= DD_BEAR:
        lab = "하락"
    elif dd <= DD_CORR or (ma is not None and last < ma):
        lab = "조정"
    else:
        lab = "상승"
    r20 = last / c[-21] - 1 if len(c) > 20 else None
    return {"l": lab, "dd": round(dd, 3), "r20": None if r20 is None else round(r20, 3), "n": len(c[-HI_N:])}


def at(dates: list[str], closes: list[float], d: str) -> dict | None:
    """정렬된 dates 에서 d 이하 마지막 거래일까지로 classify."""
    i = bisect.bisect_right(dates, d)
    return classify(closes[:i]) if i else None


def tag_items(items: list[dict], kospi: tuple[list[str], list[float]] | None,
              stocks: dict[str, tuple[list[str], list[float]]]) -> int:
    """items 에 rg_k(코스피)·rg_s(종목) 붙임. 붙인 개수."""
    n = 0
    for it in items:
        d = str(it.get("date"))[:10]
        if kospi:
            it["rg_k"] = at(kospi[0], kospi[1], d)
        s = stocks.get(it.get("code"))
        if s:
            it["rg_s"] = at(s[0], s[1], d)
        n += 1 if (it.get("rg_k") or it.get("rg_s")) else 0
    return n


def load_series(data_dir, codes: set[str]):
    """(코스피 시계열, {code: 시계열}) — 파일 없으면 None/빈 dict."""
    import polars as pl
    kp = None
    ip = data_dir / "hist" / "kr_index_daily.parquet"
    if ip.exists():
        k = pl.read_parquet(ip, columns=["date", "symbol", "close"]).filter(pl.col("symbol") == "KOSPI").sort("date")
        kp = ([str(x)[:10] for x in k["date"].to_list()], [float(x) for x in k["close"].to_list()])
    st = {}
    pp = data_dir / "kr_prices.parquet"
    if pp.exists() and codes:
        from .prices import load_kr   # 고점 대비 낙폭이 분할·병합으로 왜곡되지 않게 조정 가격
        p = (load_kr(path=pp).select("yf", "date", "close").with_columns(pl.col("yf").str.slice(0, 6).alias("code"))
               .filter(pl.col("code").is_in(sorted(codes))).sort(["code", "date"]))
        for code, g in p.group_by("code", maintain_order=True):
            code = code[0] if isinstance(code, tuple) else code
            st[code] = ([str(x)[:10] for x in g["date"].to_list()], [float(x) for x in g["close"].to_list()])
    return kp, st
