"""미국 소형주 급등 사건연구(reports/studies/2026-10-21_us_smallcap_spikes.md) 원자료 수집 — Actions 전용(컨테이너는 야후·SEC 차단).

.github/workflows/us_spikes_data.yml 이 실행 → data/study/spikes/* 를 study-data/us-spikes-<run_id> 브랜치에만 올린다(main 미변경).

산출물
  events.parquet   후보 사건(느슨한 문턱: 종가 +25%↑ & 거래량 20일 평균 3배↑ & 전일 '원가격' $0.5↑)의 D-1~D+20 일봉.
                   열: yf, d0(사건일), k(-1..20), date, open/high/low/close(분할 조정), volume, raw_f(원가격 = 조정가×raw_f),
                   vol20(D-20..D-1 평균 거래량), n_hist(사건 전 관측일수)
  meta.csv         종목별 first/last 날짜·행 수·분할 횟수(역분할 수)·이름·시장
  elig_days.csv    연도별 '적격 종목일'(전일 원가격 $1~$20, 관측 60일↑) 수 — 사건 빈도의 분모
  bench.csv        IWM·SPY 일봉(시가·종가)
  sec_shares.csv   SEC XBRL frames dei:EntityCommonStockSharesOutstanding 분기 스냅숏(cik,end,val) → 시총 근사
  sec_tickers.json SEC company_tickers.json(현재 티커↔CIK)
  form25.csv       EDGAR full-index form.idx 분기별 Form 25/25-NSE(상장폐지 통지) 건수 — 생존편향 크기 추정용
  borrow.csv       iborrowdesk(IB 차입 수수료·가능 수량) 최근 사건 종목 — 실패하면 빈 파일 + 경고
  halts.csv        nasdaqtrader 거래정지 RSS(사건일·익일) — 실패하면 빈 파일 + 경고
분할 조정: 야후 Close 는 분할 조정가. 원가격(그날 실제 호가) = Close × Π(그 날 이후 분할 비율). 역분할 많은 잡주는
조정가가 과거에 수십~수천 달러로 보이므로 가격 구간 필터는 반드시 원가격으로 건다.
금액·보유 없음(공개 시세·공시만).
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import requests

OUT = Path("data/study/spikes")
START = "2011-10-01"
CHUNK = 80
EXCL = r"Warrant|Unit|Right|ETF|ETN|Fund|Notes?\b|Preferred|Debenture|Trust Units|Index|Shares of Beneficial|%"
LOOSE_RET, LOOSE_VM, LOOSE_PX = 0.25, 3.0, 0.5
SEC_UA = os.environ.get("SEC_USER_AGENT", "").strip() or "market-screener research noreply@anthropic.com"
UA = {"User-Agent": "Mozilla/5.0"}


def universe() -> pd.DataFrame:
    u = pd.read_csv("universe/us.csv", keep_default_na=False, dtype=str)
    u = u[~u["name"].str.contains(EXCL, case=False, regex=True)]
    return u.reset_index(drop=True)


def split_factor(splits: pd.Series) -> pd.Series:
    """raw_f(t) = Π_{s>t} ratio_s (ratio = 야후 'Stock Splits', 역분할 1:50 → 0.02). 원가격 = 조정가 × raw_f."""
    r = splits.fillna(0.0).replace(0.0, 1.0)
    # 그날 이후(당일 제외) 비율의 곱: 뒤에서 누적곱 후 한 칸 당김
    rev = r[::-1].cumprod()[::-1]
    return (rev / r).astype(float)


def process(sym: str, df: pd.DataFrame, elig: Counter) -> tuple[list[pd.DataFrame], dict]:
    df = df.dropna(subset=["Close"]).copy()
    df = df[df["Close"] > 0]
    if len(df) < 30:
        return [], {"yf": sym, "rows": len(df)}
    sp = df["Stock Splits"] if "Stock Splits" in df else pd.Series(0.0, index=df.index)
    f = split_factor(sp)
    c = df["Close"]
    raw = c * f
    v = df["Volume"].astype(float)
    vol20 = v.shift(1).rolling(20, min_periods=15).mean()
    ret = c / c.shift(1) - 1
    nh = pd.Series(np.arange(len(df)), index=df.index)
    prev_raw = raw.shift(1)
    ok = (nh >= 60) & prev_raw.between(1, 20)
    for y, n in Counter(df.index[ok].year).items():
        elig[int(y)] += int(n)
    cand = (ret >= LOOSE_RET) & (v >= LOOSE_VM * vol20) & (prev_raw >= LOOSE_PX) & (nh >= 21)
    out = []
    pos = np.flatnonzero(cand.to_numpy())
    for p in pos:
        lo, hi = p - 1, min(p + 20, len(df) - 1)
        w = df.iloc[lo:hi + 1]
        out.append(pd.DataFrame({
            "yf": sym, "d0": df.index[p].strftime("%Y-%m-%d"), "k": np.arange(lo - p, hi - p + 1),
            "date": w.index.strftime("%Y-%m-%d"), "open": w["Open"].to_numpy(), "high": w["High"].to_numpy(),
            "low": w["Low"].to_numpy(), "close": w["Close"].to_numpy(), "volume": w["Volume"].to_numpy(),
            "raw_f": f.iloc[lo:hi + 1].to_numpy(), "vol20": float(vol20.iloc[p]), "n_hist": int(p),
        }))
    nrev = int(((sp > 0) & (sp < 1)).sum())
    meta = {"yf": sym, "rows": len(df), "first": df.index[0].strftime("%Y-%m-%d"),
            "last": df.index[-1].strftime("%Y-%m-%d"), "splits": int((sp > 0).sum()), "rev_splits": nrev,
            "n_cand": len(pos)}
    return out, meta


def prices(u: pd.DataFrame) -> list[str]:
    import yfinance as yf
    syms = u["yf"].tolist()
    elig: Counter = Counter()
    ev, metas = [], []
    t0 = time.time()
    missing = []
    for i in range(0, len(syms), CHUNK):
        ch = syms[i:i + CHUNK]
        raw = None
        for att in range(3):
            try:
                raw = yf.download(ch, start=START, auto_adjust=False, actions=True, group_by="ticker",
                                  threads=True, progress=False, timeout=60)
                break
            except Exception as e:  # noqa: BLE001
                print(f"::warning::chunk {i // CHUNK} 시도 {att} 실패: {e}")
                time.sleep(10)
        got = 0
        for s in ch:
            try:
                d = raw[s] if raw is not None and len(ch) > 1 else raw
                if d is None or d.dropna(how="all").empty:
                    missing.append(s)
                    continue
                d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
                o, m = process(s, d, elig)
                ev += o
                m["src"] = "chunk"
                metas.append(m)
                got += 1
            except Exception as e:  # noqa: BLE001
                missing.append(s)
                print(f"::warning::{s} 처리 실패: {e}")
        print(f"chunk {i // CHUNK + 1}/{(len(syms) + CHUNK - 1) // CHUNK}: {got}/{len(ch)} ok, 누적 사건창 {len(ev)}, {time.time() - t0:.0f}s")
    # 빠진 종목 한 번 더(단건)
    retry_ok = 0
    for s in missing[:]:
        try:
            d = yf.download(s, start=START, auto_adjust=False, actions=True, progress=False, timeout=30)
            if d is None or d.empty:
                continue
            if hasattr(d.columns, "levels"):
                d.columns = [c[0] for c in d.columns]
            d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
            o, m = process(s, d, elig)
            ev += o
            m["src"] = "retry"
            metas.append(m)
            missing.remove(s)
            retry_ok += 1
        except Exception:  # noqa: BLE001
            pass
    print(f"재시도 {retry_ok} 성공, 최종 결측 {len(missing)}종목")
    E = pd.concat(ev, ignore_index=True) if ev else pd.DataFrame()
    E.to_parquet(OUT / "events.parquet", index=False)
    M = pd.DataFrame(metas).merge(u[["yf", "name", "market"]], on="yf", how="left")
    M.to_csv(OUT / "meta.csv", index=False)
    pd.Series(missing, name="yf").to_csv(OUT / "missing.csv", index=False)
    pd.DataFrame(sorted(elig.items()), columns=["year", "elig_days"]).to_csv(OUT / "elig_days.csv", index=False)
    b = yf.download(["IWM", "SPY"], start=START, auto_adjust=True, group_by="ticker", progress=False)
    rows = []
    for s in ("IWM", "SPY"):
        x = b[s][["Open", "Close"]].dropna()
        x.index = pd.to_datetime(x.index).tz_localize(None).normalize()
        rows.append(pd.DataFrame({"symbol": s, "date": x.index.strftime("%Y-%m-%d"), "open": x["Open"].to_numpy(),
                                  "close": x["Close"].to_numpy()}))
    pd.concat(rows).to_csv(OUT / "bench.csv", index=False)
    print(f"사건창 행 {len(E)}, 후보 사건 {E[['yf', 'd0']].drop_duplicates().shape[0] if len(E) else 0}, 메타 {len(M)}")
    if not len(E):
        return []
    return strict_events(E)


def strict_events(E: pd.DataFrame, thr: float = 0.30) -> list[tuple[str, str]]:
    d0 = E[E.k == 0].set_index(["yf", "d0"])["close"]
    dm1 = E[E.k == -1].set_index(["yf", "d0"])["close"].reindex(d0.index)
    r = d0 / dm1 - 1
    return sorted(r[r >= thr].index.tolist(), key=lambda t: t[1])


def sec(u_syms: set[str]) -> None:
    h = {"User-Agent": SEC_UA, "Accept-Encoding": "gzip, deflate"}
    try:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers=h, timeout=60)
        r.raise_for_status()
        (OUT / "sec_tickers.json").write_text(r.text, encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        print(f"::warning::SEC company_tickers 실패: {e}")
    rows = []
    for y in range(2011, 2027):
        for q in (1, 2, 3, 4):
            if (y, q) > (2026, 3):
                break
            url = f"https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/shares/CY{y}Q{q}I.json"
            for att in range(3):
                try:
                    r = requests.get(url, headers=h, timeout=60)
                    if r.status_code == 404:
                        break
                    r.raise_for_status()
                    for d in r.json().get("data", []):
                        rows.append((d.get("cik"), d.get("end"), d.get("val")))
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"::warning::frames CY{y}Q{q} 시도 {att}: {e}")
                    time.sleep(3)
            time.sleep(0.15)
    S = pd.DataFrame(rows, columns=["cik", "end", "val"]).drop_duplicates()
    S.to_csv(OUT / "sec_shares.csv", index=False)
    print(f"SEC shares 스냅숏 {len(S)}행, CIK {S.cik.nunique() if len(S) else 0}")
    f25 = []
    for y in range(2012, 2027):
        for q in (1, 2, 3, 4):
            if (y, q) > (2026, 4) or (y == 2026 and q == 4):
                break
            url = f"https://www.sec.gov/Archives/edgar/full-index/{y}/QTR{q}/form.idx"
            try:
                r = requests.get(url, headers=h, timeout=120)
                r.raise_for_status()
                c = Counter()
                for line in r.text.splitlines():
                    ft = line[:12].strip()
                    if ft in ("25", "25-NSE", "25/A", "25-NSE/A"):
                        c[ft] += 1
                f25.append({"year": y, "q": q, **{k: c.get(k, 0) for k in ("25", "25-NSE", "25/A", "25-NSE/A")}})
            except Exception as e:  # noqa: BLE001
                print(f"::warning::form.idx {y}Q{q}: {e}")
            time.sleep(0.2)
    pd.DataFrame(f25).to_csv(OUT / "form25.csv", index=False)
    print(f"form25 분기 {len(f25)}")


def borrow(events: list[tuple[str, str]]) -> None:
    recent = sorted({s for s, d in events if d >= "2022-01-01"})[:400]
    rows, fails = [], 0
    for s in recent:
        try:
            r = requests.get(f"https://iborrowdesk.com/api/ticker/{s}", headers=UA, timeout=20)
            if r.status_code != 200:
                fails += 1
                if fails <= 3:
                    print(f"::warning::iborrowdesk {s} HTTP {r.status_code}")
                if fails >= 25 and not rows:
                    break
                continue
            j = r.json()
            for d in j.get("daily", []) or []:
                rows.append((s, str(d.get("date"))[:10], d.get("fee"), d.get("available"), d.get("rebate")))
        except Exception as e:  # noqa: BLE001
            fails += 1
            if fails <= 3:
                print(f"::warning::iborrowdesk {s}: {e}")
            if fails >= 25 and not rows:
                break
        time.sleep(0.6)
    pd.DataFrame(rows, columns=["yf", "date", "fee", "available", "rebate"]).to_csv(OUT / "borrow.csv", index=False)
    print(f"borrow {len(rows)}행 / 종목 {len(recent)} 시도, 실패 {fails}")


def halts(events: list[tuple[str, str]]) -> None:
    dates = sorted({d for _, d in events if d >= "2023-01-01"})
    ev_by_date: dict[str, set] = {}
    bd = pd.bdate_range("2023-01-01", "2026-12-31")
    nxt = {d.strftime("%Y-%m-%d"): bd[i + 1].strftime("%Y-%m-%d") for i, d in enumerate(bd[:-1])}
    for s, d in events:
        if d >= "2023-01-01":
            ev_by_date.setdefault(d, set()).add(s)
            if d in nxt:
                ev_by_date.setdefault(nxt[d], set()).add(s)
    rows, fails = [], 0
    for d in sorted(ev_by_date)[:900]:
        dt = pd.Timestamp(d)
        url = f"https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts&haltdate={dt:%m%d%Y}"
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            for it in re.findall(r"<item>(.*?)</item>", r.text, flags=re.S):
                sym = re.search(r"<ndaq:IssueSymbol>(.*?)</ndaq:IssueSymbol>", it)
                rc = re.search(r"<ndaq:ReasonCode>(.*?)</ndaq:ReasonCode>", it)
                if sym and sym.group(1).strip() in ev_by_date[d]:
                    rows.append((sym.group(1).strip(), d, rc.group(1).strip() if rc else ""))
        except Exception as e:  # noqa: BLE001
            fails += 1
            if fails <= 3:
                print(f"::warning::halts {d}: {e}")
            if fails >= 20 and not rows:
                break
        time.sleep(0.3)
    pd.DataFrame(rows, columns=["yf", "date", "reason"]).to_csv(OUT / "halts.csv", index=False)
    print(f"halts {len(rows)}행 / 날짜 {len(ev_by_date)}, 실패 {fails} (dates 원본 {len(dates)})")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    u = universe()
    print(f"유니버스 {len(u)}종목(보통주 필터 후)")
    stage = os.environ.get("STAGE", "all")
    events: list[tuple[str, str]] = []
    if stage in ("all", "prices"):
        events = prices(u)
        json.dump(events, open(OUT / "strict_events.json", "w"))
    if stage in ("all", "sec"):
        sec(set(u["yf"]))
    if stage in ("all", "extra") and events:
        borrow(events)
        halts(events)
    for p in sorted(OUT.iterdir()):
        print(f"{p.name}: {p.stat().st_size / 1e6:.1f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
