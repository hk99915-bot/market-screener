"""주식 수 (가치평가의 분모).

우선순위
1. DART 주식의 총수 현황(stockTotqySttus): 최근 정기보고서 기준 (보통주+우선주) 발행 − 자기주식 = 유통주식
   → 자사주를 빼고, 우선주를 포함한다 (지배주주 순이익은 우선주 몫까지 포함하므로).
2. KRX 상장주식수 (pykrx, 보통주만, 자사주 포함) — DART 가 없을 때
3. 시가총액 / 종가 근사 — 둘 다 없을 때
결과는 universe/kr_shares.csv (분기마다 갱신, 하루 예산 내 순환).
"""
from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import polars as pl

from .config import UNIVERSE_DIR

log = logging.getLogger(__name__)
OUT = UNIVERSE_DIR / "kr_shares.csv"
SCHEMA = {"code": pl.Utf8, "year": pl.Int32, "reprt": pl.Utf8, "common_issued": pl.Float64, "common_treasury": pl.Float64,
          "pref_issued": pl.Float64, "pref_treasury": pl.Float64, "out_total": pl.Float64, "krx_listed": pl.Float64,
          "stamp": pl.Float64}


def load() -> pl.DataFrame:
    if OUT.exists():
        return pl.read_csv(OUT, schema_overrides=SCHEMA)
    return pl.DataFrame(schema=SCHEMA)


def _parse(rows: list[dict]) -> dict | None:
    from .fin import _num
    c = p = t = None
    for r in rows:
        se = (r.get("se") or "").replace(" ", "")
        issued, tre = _num(r.get("istc_totqy")), _num(r.get("tlstk")) or 0.0
        if issued is None:
            continue
        if "보통" in se:
            c = (issued, tre)
        elif "우선" in se or "종류" in se:
            p = (p[0] + issued, p[1] + tre) if p else (issued, tre)
        elif "합계" in se:
            t = (issued, tre)
    if not c and not t:
        return None
    ci, ct = c or (None, None)
    pi, pt = p or (0.0, 0.0)
    if c:
        out = ci - ct + pi - pt
    else:
        out = t[0] - t[1]
    return {"common_issued": ci, "common_treasury": ct, "pref_issued": pi, "pref_treasury": pt, "out_total": out}


def update_dart(codes: list[str], budget: int = 3000) -> int:
    from . import fin
    if not fin.key():
        log.info("DART 키 없음 — 주식 수 건너뜀")
        return 0
    cmap = fin.corp_codes()
    per = fin.periods(1)[::-1]   # 최근 정기보고서부터
    latest = per[0]
    old = load()
    have = {r["code"]: (r["year"], r["reprt"]) for r in old.to_dicts() if r.get("out_total")}
    krx_old = {r["code"]: r["krx_listed"] for r in old.to_dicts() if r.get("krx_listed")}
    todo = [c for c in codes if c in cmap and have.get(c) != latest][:budget]
    new, n = [], 0
    for code in todo:
        for y, rc in per[:3]:
            try:
                j = fin._api("stockTotqySttus.json", {"corp_code": cmap[code], "bsns_year": str(y), "reprt_code": rc})
            except RuntimeError as e:
                if "020" in str(e):
                    log.warning("DART 한도 — 주식 수 중단")
                    todo = []
                    break
                continue
            n += 1
            v = _parse(j.get("list") or [])
            if v:
                new.append({"code": code, "year": y, "reprt": rc, **v, "krx_listed": krx_old.get(code), "stamp": time.time()})
                break
        if not todo:
            break
    if new:
        add = pl.DataFrame(new, schema=SCHEMA)
        df = pl.concat([old.filter(~pl.col("code").is_in(add["code"].implode())), add], how="vertical_relaxed")
        df.sort("code").write_csv(OUT)
    log.info("DART 주식 수 %d종목 갱신 (호출 %d)", len(new), n)
    return len(new)


def update_krx() -> int:
    """KRX 상장주식수(보통주) 일괄 — DART 미보유 종목 대체용 + 공시 이후 변동 감지용."""
    try:
        from pykrx import stock  # type: ignore
        df = None
        for back in range(8):
            ymd = (date.today() - timedelta(days=back)).strftime("%Y%m%d")
            d = stock.get_market_cap(ymd, market="ALL")
            if d is not None and len(d) and d["상장주식수"].sum() > 0:
                df = d
                break
        if df is None:
            return 0
        m = {str(k): float(v) for k, v in df["상장주식수"].items()}
    except Exception as e:  # noqa: BLE001
        log.warning("KRX 상장주식수 실패: %s", e)
        return 0
    old = load()
    known = set(old["code"].to_list())
    old = old.with_columns(pl.col("code").replace_strict(m, default=None, return_dtype=pl.Float64).fill_null(pl.col("krx_listed")).alias("krx_listed"))
    extra = [{"code": c, "year": None, "reprt": None, "common_issued": None, "common_treasury": None, "pref_issued": None,
              "pref_treasury": None, "out_total": None, "krx_listed": v, "stamp": time.time()} for c, v in m.items() if c not in known]
    df = pl.concat([old, pl.DataFrame(extra, schema=SCHEMA)], how="vertical_relaxed") if extra else old
    df.sort("code").write_csv(OUT)
    log.info("KRX 상장주식수 %d종목", len(m))
    return len(m)


def shares_map() -> dict[str, dict]:
    """{code: {"n": 분모 주식 수, "src": 출처, "treasury_pct", "pref_pct", "listed_change"}}"""
    from .fin import REPRT
    out = {}
    for r in load().to_dicts():
        if r.get("out_total"):
            ci = r.get("common_issued") or 0
            chg = None
            if r.get("krx_listed") and ci:
                chg = r["krx_listed"] / ci - 1   # 보고서 이후 보통주 발행 수 변동 (유증·소각·CB 전환)
            n = r["out_total"]
            if chg is not None and abs(chg) > 0.005:   # 보고서 이후 변동분 반영
                n += r["krx_listed"] - ci
            out[r["code"]] = {"n": n, "src": f"DART {r['year']} {REPRT.get(r['reprt'], (0, r['reprt']))[1]} (자사주 제외·우선주 포함)"
                              + (f", 이후 보통주 {chg*100:+.1f}% 변동 반영" if chg is not None and abs(chg) > 0.005 else ""),
                              "treasury_pct": round((r.get("common_treasury") or 0) / ci, 4) if ci else None,
                              "pref_pct": round((r.get("pref_issued") or 0) / (ci + (r.get("pref_issued") or 0)), 4) if ci else None,
                              "listed_change": round(chg, 4) if chg is not None else None}
        elif r.get("krx_listed"):
            out[r["code"]] = {"n": r["krx_listed"], "src": "KRX 상장주식수 (보통주, 자사주 포함)"}
    return out


def update(codes: list[str], budget: int = 3000) -> dict:
    d = update_dart(codes, budget)
    return {"dart": d, "krx": update_krx()}
