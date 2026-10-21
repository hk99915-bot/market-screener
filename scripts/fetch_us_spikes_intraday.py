"""미국 소형주 폭등 '장중 분봉 단타' 연구(reports/studies/2026-10-21_us_spikes_intraday.md) 원자료 수집 — Actions 전용.

컨테이너는 야후·nasdaqtrader 차단 → .github/workflows/us_spikes_intraday_data.yml 이 실행해
data/study/spikes_intraday/* 를 study-data/us-spikes-intraday-<run_id> 브랜치에만 올린다(main 미변경).
일봉 연구 파일(scripts/fetch_us_spikes.py·study_us_spikes.py·2026-10-21_us_smallcap_spikes.*)은 건드리지 않는다
(검증 데스크 재현 중) — 유니버스·원가격 함수만 import 해서 정의를 같게 맞춘다.

단계
  1) 일봉(최근 400일, 분할 정보 포함) 5,198종목 → 최근 62일 안의 '후보 종목일'
       = 장중 고가 ≥ 전일 종가 +30%(종가가 아니라 고가 — 장중에 떴다 꺼진 날도 넣어야 실시간 트리거 표본이 편향 안 됨)
         & 전일 원가격 $0.5↑ & 관측 21일↑.  열: yf, d0, d1(다음 거래일), pc(전일 조정 종가), raw_f, vol20, n_hist,
         o0,h0,l0,c0,v0 (일봉).  → cand_daily.csv
  2) 후보 종목의 5분봉(period=60d, prepost=True — 프리·애프터 포함) 중 D0·D+1 날짜만 → bars5.parquet
  3) 1분봉(최근 29일, 7일 창 4번, prepost=True) 중 D0·D+1 → bars1.parquet (야후 1m 한계 확인용)
  4) nasdaqtrader 거래정지 RSS(후보 D0·D+1 날짜) — 사유·정지 시각·재개 시각 → halts.csv
실패는 ::warning:: 로그 + 빈 파일(조용한 대체 금지). 금액·보유 없음(공개 시세만).
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_us_spikes import CHUNK, UA, split_factor, universe  # noqa: E402

OUT = Path("data/study/spikes_intraday")
TOUCH = 0.30
WIN_DAYS = 62


def daily(u: pd.DataFrame) -> pd.DataFrame:
    import yfinance as yf
    syms = u["yf"].tolist()
    start = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
    since = pd.Timestamp.utcnow().tz_localize(None).normalize() - pd.Timedelta(days=WIN_DAYS)
    rows, miss = [], 0
    for i in range(0, len(syms), CHUNK):
        ch = syms[i:i + CHUNK]
        raw = None
        for att in range(3):
            try:
                raw = yf.download(ch, start=start, auto_adjust=False, actions=True, group_by="ticker",
                                  threads=True, progress=False, timeout=60)
                break
            except Exception as e:  # noqa: BLE001
                print(f"::warning::daily chunk {i // CHUNK} 시도 {att}: {e}")
                time.sleep(10)
        for s in ch:
            try:
                d = raw[s] if raw is not None and len(ch) > 1 else raw
                if d is None or d.dropna(how="all").empty:
                    miss += 1
                    continue
                d = d.dropna(subset=["Close"])
                d = d[d["Close"] > 0].copy()
                if len(d) < 30:
                    continue
                d.index = pd.to_datetime(d.index).tz_localize(None).normalize()
                sp = d["Stock Splits"] if "Stock Splits" in d else pd.Series(0.0, index=d.index)
                f = split_factor(sp)
                c = d["Close"]
                v = d["Volume"].astype(float)
                vol20 = v.shift(1).rolling(20, min_periods=15).mean()
                pc = c.shift(1)
                nh = pd.Series(np.arange(len(d)), index=d.index)
                cand = (d["High"] / pc - 1 >= TOUCH) & (pc * f.shift(1) >= 0.5) & (nh >= 21) & (d.index >= since)
                for p in np.flatnonzero(cand.to_numpy()):
                    rows.append({
                        "yf": s, "d0": d.index[p].strftime("%Y-%m-%d"),
                        "d1": d.index[p + 1].strftime("%Y-%m-%d") if p + 1 < len(d) else "",
                        "pc": float(pc.iloc[p]), "raw_f_m1": float(f.iloc[p - 1]), "vol20": float(vol20.iloc[p]),
                        "n_hist": int(nh.iloc[p]), "o0": float(d["Open"].iloc[p]), "h0": float(d["High"].iloc[p]),
                        "l0": float(d["Low"].iloc[p]), "c0": float(c.iloc[p]), "v0": float(v.iloc[p]),
                        "o1": float(d["Open"].iloc[p + 1]) if p + 1 < len(d) else np.nan,
                        "c1": float(c.iloc[p + 1]) if p + 1 < len(d) else np.nan,
                        "split_in_win": bool((sp.iloc[max(0, p - 1):p + 2].fillna(0) != 0).any()),
                    })
            except Exception as e:  # noqa: BLE001
                print(f"::warning::{s} 일봉 처리 실패: {e}")
        print(f"chunk {i // CHUNK + 1}/{(len(syms) + CHUNK - 1) // CHUNK}: 후보 누적 {len(rows)}")
    C = pd.DataFrame(rows)
    C.to_csv(OUT / "cand_daily.csv", index=False)
    print(f"일봉 결측 {miss}종목, 후보 종목일 {len(C)}, 종목 {C.yf.nunique() if len(C) else 0}")
    return C


def _bars(syms: list[str], keep: dict[str, set], **kw) -> pd.DataFrame:
    import yfinance as yf
    out = []
    for i in range(0, len(syms), 40):
        ch = syms[i:i + 40]
        raw = None
        for att in range(3):
            try:
                raw = yf.download(ch, group_by="ticker", threads=True, progress=False, timeout=60,
                                  auto_adjust=False, prepost=True, **kw)
                break
            except Exception as e:  # noqa: BLE001
                print(f"::warning::bars {kw.get('interval')} chunk {i // 40} 시도 {att}: {e}")
                time.sleep(10)
        for s in ch:
            try:
                d = raw[s] if raw is not None and len(ch) > 1 else raw
                if d is None or d.dropna(how="all").empty:
                    continue
                if hasattr(d.columns, "levels"):
                    d.columns = [c[0] for c in d.columns]
                d = d.dropna(subset=["Close"])
                idx = pd.to_datetime(d.index)
                idx = idx.tz_convert("America/New_York") if idx.tz is not None else idx
                d.index = idx.tz_localize(None)
                day = d.index.strftime("%Y-%m-%d")
                d = d[np.isin(day, list(keep[s]))]
                if d.empty:
                    continue
                out.append(pd.DataFrame({"yf": s, "ts": d.index, "o": d["Open"].to_numpy(), "h": d["High"].to_numpy(),
                                         "l": d["Low"].to_numpy(), "c": d["Close"].to_numpy(),
                                         "v": d["Volume"].astype(float).to_numpy()}))
            except Exception as e:  # noqa: BLE001
                print(f"::warning::{s} 분봉 실패: {e}")
        print(f"bars {kw.get('interval')} {i + len(ch)}/{len(syms)}")
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=["yf", "ts", "o", "h", "l", "c", "v"])


def intraday(C: pd.DataFrame) -> None:
    keep: dict[str, set] = {}
    for r in C.itertuples():
        keep.setdefault(r.yf, set()).update({r.d0} | ({r.d1} if r.d1 else set()))
    syms = sorted(keep)
    b5 = _bars(syms, keep, interval="5m", period="60d")
    b5.to_parquet(OUT / "bars5.parquet", index=False)
    print(f"5분봉 {len(b5)}행, 종목 {b5.yf.nunique() if len(b5) else 0}, 날짜 {b5.ts.min() if len(b5) else '-'}~{b5.ts.max() if len(b5) else '-'}")
    now = pd.Timestamp.utcnow().tz_localize(None).normalize()
    parts = []
    for w in range(4):
        end = now - pd.Timedelta(days=7 * w) + pd.Timedelta(days=1)
        st = end - pd.Timedelta(days=7)
        recent = {s: {d for d in ds if st.strftime("%Y-%m-%d") <= d < end.strftime("%Y-%m-%d")} for s, ds in keep.items()}
        recent = {s: ds for s, ds in recent.items() if ds}
        if not recent:
            continue
        parts.append(_bars(sorted(recent), recent, interval="1m", start=st.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d")))
    b1 = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=["yf", "ts", "o", "h", "l", "c", "v"])
    b1.to_parquet(OUT / "bars1.parquet", index=False)
    print(f"1분봉 {len(b1)}행, 종목 {b1.yf.nunique() if len(b1) else 0}, 날짜 {b1.ts.min() if len(b1) else '-'}~{b1.ts.max() if len(b1) else '-'}")


def halts(C: pd.DataFrame) -> None:
    by_date: dict[str, set] = {}
    for r in C.itertuples():
        for d in (r.d0, r.d1):
            if d:
                by_date.setdefault(d, set()).add(r.yf)
    rows, fails = [], 0
    tag = lambda k, it: (m.group(1).strip() if (m := re.search(rf"<ndaq:{k}>(.*?)</ndaq:{k}>", it, flags=re.S)) else "")
    for d in sorted(by_date):
        url = f"https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts&haltdate={pd.Timestamp(d):%m%d%Y}"
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            for it in re.findall(r"<item>(.*?)</item>", r.text, flags=re.S):
                s = tag("IssueSymbol", it)
                if s in by_date[d]:
                    rows.append((s, d, tag("ReasonCode", it), tag("HaltTime", it), tag("ResumptionQuoteTime", it),
                                 tag("ResumptionTradeTime", it)))
        except Exception as e:  # noqa: BLE001
            fails += 1
            print(f"::warning::halts {d}: {e}")
        time.sleep(0.3)
    pd.DataFrame(rows, columns=["yf", "date", "reason", "halt_time", "resume_quote", "resume_trade"]).to_csv(
        OUT / "halts.csv", index=False)
    print(f"halts {len(rows)}행 / 날짜 {len(by_date)}, 실패 {fails}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    u = universe()
    print(f"유니버스 {len(u)}종목")
    C = daily(u)
    if len(C):
        intraday(C)
        halts(C)
    for p in sorted(OUT.iterdir()):
        print(f"{p.name}: {p.stat().st_size / 1e6:.2f}MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
